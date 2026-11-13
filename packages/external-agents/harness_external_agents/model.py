"""An ACP agent as a model: each completion is one turn of a session of the agent, and its
text is the reply. The agent decides nothing else: it is given no client capabilities, an
empty directory and no built-in tools where it lets a client say so, its requests for
permission are refused, and a turn in which it starts a tool of its own is cancelled and
fails.

An ACP session keeps its own history, a completion request carries all of it. A request that
extends what a session has already seen sends only what is new to that session; any other
request (a shortened or rewritten history, a second request at the same time) gets a session
of its own with the whole conversation.
"""

from base64 import b64decode
import hashlib
import json
import os
from queue import Empty, Queue
import re
import shutil
import tempfile
import threading
import time
import weakref

from .acp import Peer


# What a session is told when the agent takes no system prompt from its client.
ROLE = (
    "In this session you are the language model of another program. That program reads each of your "
    "replies as the next assistant message of the conversation it sends you. Reply with text only and "
    "use none of your own tools (no files, no shell, no search, no sub-agents): whatever is to be done "
    "is written in the reply the way the instructions below say, and the program does it. Requests for "
    "permission are refused.\n\nThe instructions:\n\n")
HISTORY = "The conversation so far follows, each message under its role. Reply with the next assistant message only."
NO_IMAGE = "[an image was left out: this agent reads none]"
# Session modes that ask before the agent acts, by the names agents give them; the first one
# an agent offers is set. A model role's `mode` names another.
ASKING_MODES = ("read-only", "readonly", "default", "ask", "manual")
SESSIONS = 4
# What a new session asks of the agent beyond the protocol, under the names agents read
# (an agent ignores another's): no built-in tools, and for Claude's agent none of the
# user's settings, memory files or connected MCP servers either. Without the last two its
# session carries every tool the user connected (about 230,000 tokens a turn, measured,
# against under 1,000). A model role's `session_meta` adds to it.
SESSION_META = {"disableBuiltInTools": True,
                "claudeCode": {"options": {"settingSources": [], "strictMcpConfig": True}}}
DATA_URL = re.compile(r"data:([^;,]+);base64,(.*)", re.DOTALL)


# How many messages at a session's end the caller may have left out of its next request (a
# reply it did not keep, with the question that got it) for the session still to go on.
DROPPED = 4
# The text a caller puts where an image was once it stops sending it (the harness's history
# keeps a view for a reply or two): a message that differs only in that is the same message.
OMITTED = ("[earlier image omitted]", "[image not sent: this model reads no images]")
NOT_KEPT = "(The program did not keep your last {count} message(s) of this session: go on from the conversation before them.)\n\n"
SYSTEM_CHANGED = ("(The {what} changed. After the part ending with\n«{before}»\nit now reads:\n{now}\n"
                  "{after}What it said there before no longer holds.)\n\n")


def _key(message) -> str:
    """A message's identity for matching a request against what a session saw: its role and
    its text, without its images and without the notes that stand where an image was."""
    content = message.get("content")
    if not isinstance(content, str):
        content = [part.get("text") or "" for part in content or []
                   if part.get("type") == "text" and part.get("text") not in OMITTED]
    return hashlib.sha256(json.dumps([message.get("role"), content], ensure_ascii=False).encode()).hexdigest()


def _follows(seen: list, asked: list):
    """How many messages of the request `asked` a session that `seen` these (both lists of
    message keys) already has, or None when the request is not its conversation. It is when
    it begins as the session did, goes on as it did up to at most DROPPED messages before
    the session's end (the caller left out what came last), and has at least one message
    new to the session. A conversation that was compacted begins with another message: it
    is a new session, which then holds the summary and no more."""
    length = 0
    while length < len(seen) and length < len(asked) and seen[length] == asked[length]:
        length += 1
    return length if length and len(seen) - length <= DROPPED and length < len(asked) else None


def _system_change(old: str, new: str, what: str = "instructions") -> str:
    """What to tell a session whose system prompt was `old` when the request's is `new`."""
    if old == new:
        return ""
    start = 0
    while start < min(len(old), len(new)) and old[start] == new[start]:
        start += 1
    end = 0
    while end < min(len(old), len(new)) - start and old[-1 - end] == new[-1 - end]:
        end += 1
    now = new[start:len(new) - end]
    after = "and go on as before.\n" if end else ""
    return SYSTEM_CHANGED.format(what=what, before=new[max(0, start - 80):start],
                                 now=now or "(nothing: that part was removed)", after=after)


def _blocks(content, images: bool) -> list:
    """Chat Completions content (a string or parts) as ACP content blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks = []
    for part in content or []:
        if part.get("type") == "text":
            blocks.append({"type": "text", "text": part.get("text") or ""})
        elif part.get("type") == "image_url":
            found = DATA_URL.fullmatch(str((part.get("image_url") or {}).get("url") or ""))
            if images and found:
                b64decode(found.group(2), validate=True)
                blocks.append({"type": "image", "mimeType": found.group(1), "data": found.group(2)})
            else:
                blocks.append({"type": "text", "text": NO_IMAGE})
        else:
            raise ValueError(f"unsupported content part: {part.get('type')}")
    return blocks


def _text(message) -> str:
    """A message's text, without its images."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text") or "" for part in content or [] if part.get("type") == "text")


def _shape(message) -> str:
    """A message in a few words, for the trace of why a session could not go on."""
    content = message.get("content")
    if isinstance(content, str):
        return f"{message.get('role')} text {len(content)}: {content[:70]!r}"
    texts = [part.get("text") or "" for part in content or [] if part.get("type") == "text"]
    images = sum(1 for part in content or [] if part.get("type") != "text")
    return f"{message.get('role')} {len(texts)} texts {sum(map(len, texts))} chars, {images} images: {(texts[0] if texts else '')[:70]!r}"


class _Conversation:
    """One session of the agent and the messages it has seen."""

    def __init__(self, identifier, system, native_system):
        self.id = identifier
        self.system = system
        # Whether the agent took `system` as the session's own system prompt.
        self.native_system = native_system
        self.keys = []
        self.busy = True
        self.used = time.monotonic()
        self.updates = Queue()
        self.cost = 0.0
        self.shapes = {}
        self.dropped = 0
        # For a request that goes on from it: where its new messages begin.
        self.sent = 0


def _weak(method):
    """`method` of an object, called through a weak reference: the peer's reader thread
    holds these, and a strong one would keep the model (and its process) alive for ever."""
    reference = weakref.WeakMethod(method)

    def call(*arguments):
        target = reference()
        if target is not None:
            return target(*arguments)
    return call


def _close(holder):
    peer, holder["peer"] = holder.get("peer"), None
    if peer is not None:
        peer.close()
    shutil.rmtree(holder["directory"], ignore_errors=True)


class AcpModel:
    """The transport of a model role with backend "acp" (runtime/decision/model.py
    ChatModel): called with a Chat Completions request, it answers in that shape. `argv`
    and `environment` start the agent; `config` is the role (agent, model,
    reasoning_effort, mode)."""

    streams_text = True
    cancellable = True

    def __init__(self, config, argv, environment=None, auth_method=None):
        self.agent = str(config.get("agent") or "acp")
        self.model = config.get("model") or None
        self.effort = config.get("reasoning_effort") or None
        self.mode = config.get("mode") or None
        self.meta = {**SESSION_META, **(config.get("session_meta") or {})}
        self.argv, self.environment, self.auth_method = argv, environment, auth_method
        self.lock = threading.Lock()
        self.connecting = threading.Lock()
        self.starting = None
        self.sessions = {}
        self.capabilities = {}
        # The agent works nowhere: an empty directory of this model's own.
        self.holder = {"peer": None, "directory": tempfile.mkdtemp(prefix="harness-acp-model-")}
        weakref.finalize(self, _close, self.holder)

    def close(self):
        with self.lock:
            self.sessions.clear()
        _close(self.holder)

    # ------------------------------------------------------------ the connection

    def _peer(self):
        with self.connecting:
            peer = self.holder["peer"]
            if peer is not None and not peer.closed and peer.process.poll() is None:
                return peer
            with self.lock:
                self.sessions.clear()
            os.makedirs(self.holder["directory"], exist_ok=True)   # closed once: it is used again
            peer = self.starting = Peer(self.argv, self.holder["directory"], _weak(self._receive),
                                        _weak(self._lost), self.environment)
            peer.start()
            try:
                answer = peer.request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                                     "clientInfo": {"name": "the-harness", "version": "1"}}).result(30)
                if answer.get("protocolVersion") != 1:
                    raise ValueError("the agent did not negotiate ACP v1")
                self.capabilities = answer.get("agentCapabilities") or {}
                if self.auth_method:
                    peer.request("authenticate", {"methodId": self.auth_method}).result(30)
            except BaseException:
                peer.close()
                raise
            self.holder["peer"] = peer
            return peer

    def _lost(self, problem):
        with self.lock:
            sessions, self.sessions = self.sessions, {}
        for conversation in sessions.values():
            conversation.updates.put({"lost": problem})

    def _receive(self, message):
        method, params, identifier = message["method"], message.get("params") or {}, message.get("id")
        if method == "session/update" and identifier is None:
            with self.lock:
                conversation = self.sessions.get(params.get("sessionId"))
            if conversation is not None:
                conversation.updates.put(params.get("update") or {})
        elif method == "session/request_permission" and identifier is not None:
            refusal = next((row.get("optionId") for row in params.get("options") or []
                            if row.get("kind") == "reject_once"), None)
            outcome = {"outcome": "selected", "optionId": refusal} if refusal else {"outcome": "cancelled"}
            self._reply(identifier, result={"outcome": outcome})
        elif method == "elicitation/create" and identifier is not None:
            self._reply(identifier, result={"action": "decline"})
        elif identifier is not None:
            self._reply(identifier, error={"code": -32601, "message": "Unsupported client method"})

    def _reply(self, identifier, **answer):
        # A request can come while the connection is still being set up (self.holder has no peer yet).
        peer = self.holder["peer"] or self.starting
        if peer is not None:
            peer.reply(identifier, **answer)

    # ------------------------------------------------------------ sessions

    def _session(self, system, keys):
        """The idle session that can go on with `keys`, or a new one: (conversation, whether
        it is new). A session goes on when the request follows from what it saw (_follows):
        it begins and goes on as the session did, possibly without a reply at its end. What
        changed is told (_prompt). Among several, the one that shares most with the request."""
        peer = self._peer()
        with self.lock:
            best, found = None, None
            for conversation in self.sessions.values():
                match = None if conversation.busy else _follows(conversation.keys, keys)
                if match is not None and (found is None or match > found):
                    best, found = conversation, match
            if best is not None:
                best.busy = True
                best.dropped = len(best.keys) - found
                best.keys = best.keys[:found]
                best.sent = found          # the request's messages from here on are new to it
                return best, False
        self._why_new(system, keys)
        native = bool((((self.capabilities.get("sessionCapabilities") or {}).get("systemPrompt") or {})
                       .get("mode") or {}).get("override") is not None) and bool(system)
        params = {"cwd": self.holder["directory"], "mcpServers": [], "_meta": self.meta}
        if native:
            params["systemPrompt"] = {"mode": "override", "content": [{"type": "text", "text": system}]}
        answer = peer.request("session/new", params).result(60)
        conversation = _Conversation(answer["sessionId"], system, native)
        with self.lock:
            self.sessions[conversation.id] = conversation
            idle = sorted((row for row in self.sessions.values() if not row.busy), key=lambda row: row.used)
            for stale in idle[:max(0, len(idle) - SESSIONS)]:
                self._drop(stale, peer)
        try:
            self._configure(peer, conversation, answer)
        except BaseException:
            with self.lock:
                self._drop(conversation, peer)
            raise
        return conversation, True

    def _why_new(self, system, keys):
        """With HARNESS_ACP_TRACE set to a file: why no session could go on (for each one:
        whether the system prompt differs, how many messages match, where they part)."""
        import os

        path = os.environ.get("HARNESS_ACP_TRACE")
        if not path:
            return
        rows = []
        with self.lock:
            for conversation in self.sessions.values():
                seen = conversation.keys
                same = 0
                while same < min(len(seen), len(keys)) and seen[same] == keys[same]:
                    same += 1
                rows.append({"follows": _follows(seen, keys),"busy": conversation.busy, "same_system": conversation.system == system,
                             "system_lengths": [len(conversation.system), len(system)],
                             "seen": len(seen), "asked": len(keys), "same_prefix": same,
                             "parts_at": getattr(self, "_shapes", {}).get(keys[same]) if same < len(keys) else None,
                             "had_at": conversation.shapes.get(seen[same]) if same < len(seen) else None})
        with open(path, "a", encoding="utf-8") as file:
            file.write(json.dumps({"time": time.time(), "sessions": rows}) + "\n")

    def _drop(self, conversation, peer):
        self.sessions.pop(conversation.id, None)
        if (self.capabilities.get("sessionCapabilities") or {}).get("close") is not None and not peer.closed:
            try:
                peer.request("session/close", {"sessionId": conversation.id})
            except (RuntimeError, ValueError):
                pass

    def _configure(self, peer, conversation, session):
        options = session.get("configOptions") or []
        modes = [row.get("id") for row in (session.get("modes") or {}).get("availableModes") or []]

        def choose(category, value, what):
            option = next((row for row in options if row.get("category") == category), None)
            if option is None:
                # Running on its own choice under the name asked for would put a result under a
                # model that never ran.
                raise ValueError(f"{self.agent} has no {what} to set: it chooses its own. Write \"default\" "
                                 f"as the {what} to take that.")
            offered = [row.get("value") for row in option.get("options") or []]
            if value not in offered:
                raise ValueError(f"{self.agent} offers no {what} {value!r}: choose one of {', '.join(map(str, offered))}")
            if option.get("currentValue") != value:
                peer.request("session/set_config_option", {"sessionId": conversation.id, "configId": option["id"],
                                                           "value": value}).result(30)

        if self.model and self.model != "default":
            choose("model", self.model, "model")
        if self.effort and self.effort != "default":
            choose("thought_level", self.effort, "reasoning effort")
        mode_option = next((row for row in options if row.get("category") == "mode"), None)
        offered = [row.get("value") for row in (mode_option or {}).get("options") or []] or modes
        if self.mode and self.mode not in offered:
            raise ValueError(f"{self.agent} offers no mode {self.mode!r}: choose one of {', '.join(map(str, offered))}")
        mode = self.mode or next((name for name in ASKING_MODES if name in offered), None)
        current = (mode_option or {}).get("currentValue") or (session.get("modes") or {}).get("currentModeId")
        if mode and mode != current:
            if mode_option is not None:
                peer.request("session/set_config_option", {"sessionId": conversation.id, "configId": mode_option["id"],
                                                           "value": mode}).result(30)
            else:
                peer.request("session/set_mode", {"sessionId": conversation.id, "modeId": mode}).result(30)

    # ------------------------------------------------------------ a completion

    def _prompt(self, conversation, new, messages, system=""):
        """What to send for `messages` (those the session has not seen), under `system`."""
        images = bool((self.capabilities.get("promptCapabilities") or {}).get("image"))
        prompt = []
        if new and conversation.system and not conversation.native_system:
            prompt.append({"type": "text", "text": ROLE + conversation.system + "\n\n"})
        if not new:
            # What the caller changed about what this session saw.
            note = NOT_KEPT.format(count=conversation.dropped) if conversation.dropped else ""
            note += _system_change(conversation.system, system)
            conversation.system, conversation.dropped = system, 0
            if note:
                prompt.append({"type": "text", "text": note})
        if len(messages) == 1 and messages[0].get("role") == "user":
            return prompt + _blocks(messages[0].get("content"), images)
        prompt.append({"type": "text", "text": HISTORY})
        for message in messages:
            prompt.append({"type": "text", "text": f"\n[{message.get('role')}]\n"})
            prompt.extend(_blocks(message.get("content"), images))
        return prompt

    def __call__(self, url, headers, payload, timeout, on_text=None, *, cancellation=None):
        messages = list(payload["messages"])
        system = ""
        if messages and messages[0].get("role") == "system":
            content = messages.pop(0)["content"]
            system = content if isinstance(content, str) else "".join(part.get("text") or "" for part in content)
        if not messages:
            raise ValueError("a completion needs a message")
        keys = [_key(message) for message in messages]
        self._shapes = {key: _shape(message) for key, message in zip(keys, messages)}
        conversation, new = self._session(system, keys)
        peer = self.holder["peer"]
        kept = False
        try:
            if new:
                conversation.sent = 0
            kept_keys, fresh = conversation.keys, conversation.sent
            prompt = self._prompt(conversation, new, messages[fresh:], system)
            while True:  # what an earlier turn left behind
                try:
                    conversation.updates.get_nowait()
                except Empty:
                    break
            turn = peer.request("session/prompt", {"sessionId": conversation.id, "prompt": prompt})
            text, reasoning, cost = [], [], conversation.cost
            quiet = time.monotonic()
            while not turn.done() or not conversation.updates.empty():
                if cancellation is not None and cancellation.event.is_set():
                    peer.notify("session/cancel", {"sessionId": conversation.id})
                    cancellation.check()
                    raise RuntimeError("the completion was cancelled")
                try:
                    update = conversation.updates.get(timeout=0.05)
                except Empty:
                    if time.monotonic() - quiet > timeout:
                        peer.notify("session/cancel", {"sessionId": conversation.id})
                        raise OSError(f"{self.agent} sent nothing for {timeout:g} s")
                    continue
                quiet = time.monotonic()
                kind = update.get("sessionUpdate")
                if "lost" in update:
                    raise OSError(f"{self.agent} ended: {update['lost']}")
                if kind in ("agent_message_chunk", "agent_thought_chunk"):
                    part = update.get("content") or {}
                    piece = str(part.get("text") or "") if part.get("type") == "text" else ""
                    if piece:
                        (text if kind == "agent_message_chunk" else reasoning).append(piece)
                        if on_text is not None:
                            on_text("text" if kind == "agent_message_chunk" else "reasoning", piece)
                elif kind == "tool_call":
                    # It acts for itself instead of answering: nothing of that turn is a reply.
                    peer.notify("session/cancel", {"sessionId": conversation.id})
                    name = update.get("title") or update.get("kind") or "a tool"
                    raise OSError(f"{self.agent} started a tool of its own ({name}) instead of replying")
                elif kind == "usage_update":
                    amount = update.get("cost") or {}
                    if amount.get("currency") == "USD" and isinstance(amount.get("amount"), (int, float)):
                        conversation.cost = float(amount["amount"])
            answer = turn.result()
            reply = "".join(text)
            reason = answer.get("stopReason")
            if not reply and reason != "end_turn":
                raise OSError(f"{self.agent} ended the turn without a reply ({reason})")
            # What the session has now seen: what it kept, what was new, and its reply.
            conversation.keys = kept_keys + keys[fresh:] + [_key({"role": "assistant", "content": reply})]
            conversation.shapes = {**self._shapes, conversation.keys[-1]: _shape({"role": "assistant", "content": reply})}
            conversation.used = time.monotonic()
            kept = True
            usage = answer.get("usage") or {}
            spent = conversation.cost - cost
            return {"id": conversation.id,
                    "usage": {"prompt_tokens": sum(int(usage.get(name) or 0) for name in
                                                   ("inputTokens", "cachedReadTokens", "cachedWriteTokens")),
                              "completion_tokens": int(usage.get("outputTokens") or 0),
                              "cost": spent if spent > 0 else None,
                              "session": "new" if new else "continued"},
                    "choices": [{"message": {"content": reply, **({"reasoning": "".join(reasoning)} if reasoning else {})},
                                 "finish_reason": {"end_turn": "stop", "max_tokens": "length",
                                                   "max_turn_requests": "length"}.get(reason, reason or "stop")}]}
        finally:
            with self.lock:
                if kept:
                    conversation.busy = False
                else:  # what the session holds is no longer known
                    self._drop(conversation, peer)
