"""The Harness as an agent of the Agent Client Protocol (https://agentclientprotocol.com).

An editor (Zed, or any other ACP client) starts `harness acp` and talks JSON-RPC 2.0 to
it over stdio, one JSON message per line: stdout carries protocol messages only, logs go
to stderr. Each ACP session is one conversation of the app's agent on this computer in
the user's session host: the first prompt starts it with its text, later prompts are
messages to it, and its trace records reach the editor as session updates while a turn
runs (Updates). When an agent of the session waits for the user's approval (a program's
confirmation, or physical input under the physical-input policy), the editor is asked
with session/request_permission and its answer goes to the host; nothing is approved
without it. session/cancel closes the conversation and ends the open prompt with
"cancelled".

Methods handled: initialize, authenticate, session/new, session/prompt, session/cancel;
any other request is answered with -32601.
"""

import itertools
import json
import sys
import threading
import uuid

from harness.sdk import approval, format as formats, sessions, transcript

from . import __version__

PROTOCOL_VERSION = 1

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# What the editor's user may answer a permission request with.
OPTIONS = [{"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
           {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"}]

# The status of a conversation that waits for the user's approval (the host's sessions).
WAITING = "WAITING_FOR_CONFIRMATION"
# Results of a program that count as a failed tool call.
FAILED = ("error", "escalated", "timeout", "protocol_error")


def _log(message: str) -> None:
    print(f"harness acp: {message}", file=sys.stderr, flush=True)


def _connect(log):
    from harness.sdk import Host

    return Host.connect(start=True, log=log)


class AcpError(Exception):
    """A request the agent answers with a JSON-RPC error."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _content(text: str) -> list[dict]:
    """A tool call's content: one block of text."""
    return [{"type": "content", "content": _text(text)}]


def result_text(result: dict) -> str:
    """A program's result in short, in the transcript's words: status and time, output, error."""
    return "\n".join(row for item in transcript.items({"event": "cell", "result": result}, {})
                     for row in formats.clip_lines(item["text"], 8 if item["kind"] == "cell_error" else 20))


def prompt_text(blocks) -> str:
    """The text of a prompt's content blocks: text blocks, links by their address,
    embedded text resources by their text."""
    parts = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and block.get("text"):
            parts.append(str(block["text"]))
        elif kind == "resource_link" and block.get("uri"):
            parts.append(str(block["uri"]))
        elif kind == "resource" and isinstance(block.get("resource"), dict) and block["resource"].get("text"):
            parts.append(str(block["resource"]["text"]))
    return "\n".join(parts).strip()


def approval_call(request: dict | None) -> tuple[str, str, list[dict]]:
    """(title, kind, content) of the tool call the editor's user approves for what an agent
    waits for: a program (a confirmation_request record) or physical input (a
    physical_request record)."""
    request = request or {}
    if request.get("event") == "physical_request" or "actions" in request:
        doing, app = transcript.physical(request)
        doing = approval.say(doing)
        asked = approval.say("request", doing=doing, app=app)
        lines = [asked[:1].upper() + asked[1:] + "."]
        if request.get("window") and request["window"] != app:
            lines.append(f"Window: {request['window']}")
        if request.get("why"):
            lines.append(f"Why: {request['why']}")
        return f"Use your mouse and keyboard: {doing} in {app}", "other", _content("\n".join(lines))
    code = str(request.get("code") or "")
    return "Run a program", "execute", _content(f"```python\n{code}\n```") if code else []


class Updates:
    """The session updates of one conversation's trace records, in order: what the agent
    says, a reply's thought, and a tool call for each program it runs."""

    def __init__(self):
        # The program the last reply wrote, for the tool call of its run.
        self.code = None
        # Program spans that run: span id -> tool call id.
        self.spans = {}
        # The tool call of the last program span that ended, for its cell's result.
        self.last = None
        # A tool call already shown for a program the user approved: its run takes it over.
        self.adopt = None
        self.count = itertools.count(1)

    def of(self, record: dict) -> list[dict]:
        kind = record.get("event")
        if kind in ("agent_message", "finish"):
            text = str(record.get("text") or "").strip()
            return [{"sessionUpdate": "agent_message_chunk", "content": _text(text)}] if text else []
        if kind == "model_reply":
            return self._reply(record)
        if kind == "span_start" and record.get("lane") == "program":
            return self._program(record)
        if kind == "span_end" and record.get("id") in self.spans:
            tool = self.last = self.spans.pop(record["id"])
            failed = bool(record.get("error")) or record.get("status") in FAILED
            update = {"sessionUpdate": "tool_call_update", "toolCallId": tool,
                      "status": "failed" if failed else "completed"}
            if record.get("error"):
                update["content"] = _content(str(record["error"]))
            return [update]
        if kind == "cell":
            return self._cell(record)
        if kind in ("error", "kernel_died"):
            updates = [{"sessionUpdate": "tool_call_update", "toolCallId": tool, "status": "failed"}
                       for tool in self.spans.values()]
            self.spans.clear()
            message = str(record.get("message") or "").strip()
            if message:
                updates.append({"sessionUpdate": "agent_message_chunk", "content": _text(f"Error: {message}")})
            return updates
        return []

    def _reply(self, record: dict) -> list[dict]:
        if record.get("ahead", "used") != "used":
            # Written while a program ran and set aside: a look's thought is shown.
            thought = transcript.LOOK_TAGS.sub("", str(record.get("text") or "")).strip() if record.get("think") else ""
            return [{"sessionUpdate": "agent_thought_chunk", "content": _text(thought)}] if thought else []
        presentation = transcript.presentation(record)
        if presentation.get("kind") in ("python", "action"):
            self.code = str(presentation.get("body") or "")
        thought = str(presentation.get("thought") or "").strip()
        # A plain message is the agent_message record that follows.
        if not thought or presentation.get("kind") in ("message", "invalid"):
            return []
        return [{"sessionUpdate": "agent_thought_chunk", "content": _text(thought)}]

    def _program(self, record: dict) -> list[dict]:
        title = str(record.get("name") or "program")
        code, self.code = self.code, None
        detail = {"title": title, "kind": "execute", "status": "in_progress"}
        if code:
            detail.update(rawInput={"code": code}, content=_content(f"```python\n{code}\n```"))
        if self.adopt is not None:
            tool, self.adopt = self.adopt, None
            self.spans[record.get("id")] = tool
            return [{"sessionUpdate": "tool_call_update", "toolCallId": tool, **detail}]
        tool = f"program-{record.get('id') or next(self.count)}"
        self.spans[record.get("id")] = tool
        return [{"sessionUpdate": "tool_call", "toolCallId": tool, **detail}]

    def _cell(self, record: dict) -> list[dict]:
        result = record.get("result") or {}
        status = "failed" if result.get("status") in FAILED or result.get("error") else "completed"
        update = {"sessionUpdate": "tool_call_update", "status": status, "content": _content(result_text(result))}
        tool, self.last = self.last, None
        if tool is not None:
            return [{**update, "toolCallId": tool}]
        # A program run without a span of its own.
        tool = f"program-cell-{next(self.count)}"
        code = str(record.get("code") or "")
        self.code = None
        return [{"sessionUpdate": "tool_call", "toolCallId": tool, "title": "program", "kind": "execute",
                 "status": "in_progress", **({"rawInput": {"code": code}} if code else {})},
                {**update, "toolCallId": tool}]


class Connection:
    """JSON-RPC 2.0 over a pair of text streams, one message per line. Writes are whole
    lines under a lock; a request to the client blocks until the client answers."""

    def __init__(self, writer, log=_log):
        self.writer = writer
        self.log = log
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending = {}
        self.closed = threading.Event()

    def send(self, message: dict) -> None:
        line = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False)
        with self._lock:
            if self.closed.is_set():
                return
            try:
                self.writer.write(line + "\n")
                self.writer.flush()
            except (OSError, ValueError) as error:
                self.log(f"cannot write to the client: {error}")

    def notify(self, method: str, params: dict) -> None:
        self.send({"method": method, "params": params})

    def respond(self, identifier, result: dict) -> None:
        self.send({"id": identifier, "result": result})

    def fail(self, identifier, code: int, message: str) -> None:
        self.send({"id": identifier, "error": {"code": code, "message": message}})

    def request(self, method: str, params: dict) -> dict | None:
        """Send a request to the client and wait for its result; None when the connection
        closes first or the client answers with an error."""
        with self._lock:
            identifier = next(self._ids)
            waiter = self._pending[identifier] = {"done": threading.Event()}
        if self.closed.is_set():
            return None
        self.send({"id": identifier, "method": method, "params": params})
        waiter["done"].wait()
        if "error" in waiter:
            self.log(f"the client answered {method} with an error: {waiter['error']}")
            return None
        return waiter.get("result")

    def answered(self, message: dict) -> None:
        """A response of the client to one of the agent's requests."""
        with self._lock:
            waiter = self._pending.pop(message.get("id"), None)
        if waiter is None:
            self.log(f"a response to no request: {message.get('id')!r}")
            return
        if "error" in message:
            waiter["error"] = message["error"]
        else:
            waiter["result"] = message.get("result") if isinstance(message.get("result"), dict) else {}
        waiter["done"].set()

    def close(self) -> None:
        """No more messages: the requests still waiting get None."""
        with self._lock:
            self.closed.set()
            waiters, self._pending = list(self._pending.values()), {}
        for waiter in waiters:
            waiter["done"].set()


# The stop reason of a prompt for how the conversation's turn ended (its turn_result record).
STOP_REASONS = {"answer": "end_turn", "budget": "max_turn_requests", "wall_time": "max_turn_requests",
                "cost": "max_turn_requests", "error": "refusal", "interrupted": "cancelled"}


class Turn:
    """One prompt of a session, from the request to its stop reason."""

    def __init__(self):
        self.done = threading.Event()
        self.reason = None
        self.error = None
        self.cancelled = False

    def end(self, reason: str | None, error: Exception | None = None) -> None:
        if self.done.is_set():
            return
        self.reason, self.error = reason, error
        self.done.set()


class Session:
    """An ACP session: the host conversation its first prompt starts, the threads that
    follow its agents' records, and the turn that runs."""

    def __init__(self, agent: "Agent", identifier: str, cwd: str):
        self.agent = agent
        self.id = identifier
        self.cwd = cwd
        self.lock = threading.RLock()
        self.conversation = None
        # Set when the conversation ends or is closed: its followers stop.
        self.stop = None
        self.host_session = None
        self.agent_id = "main"
        self.turn = None
        self.updates = Updates()
        # Per agent: the last request record it waits on, and whether the editor is asked.
        self.requests = {}
        self.asking = set()
        self.followed = set()
        self.calls = itertools.count(1)

    # Prompts.

    def prompt(self, text: str) -> dict:
        with self.lock:
            if self.turn is not None and not self.turn.done.is_set():
                raise AcpError(INVALID_REQUEST, "a prompt of this session still runs")
            turn = self.turn = Turn()
            conversation = self.conversation
        try:
            if conversation is None:
                self._start(text, turn)
            else:
                conversation.send_message(text)
        except Exception as error:
            turn.end(None, error)
        turn.done.wait()
        if turn.error is not None:
            raise AcpError(INTERNAL_ERROR, f"{type(turn.error).__name__}: {turn.error}")
        return {"stopReason": turn.reason}

    def _start(self, text: str, turn: Turn) -> None:
        host = self.agent.host()
        conversation = host.task(text, self.agent.workspace)
        with self.lock:
            if turn.cancelled:
                cancelled = True
            else:
                cancelled = False
                stop = self.stop = threading.Event()
                self.conversation = conversation
                self.updates = Updates()
                self.host_session = getattr(conversation, "session", None) or conversation.run
                self.followed = set()
        if cancelled:
            self._close(conversation)
            return
        try:
            row = conversation.describe()
            self.agent_id = next((item["id"] for item in row.get("agents") or [] if item.get("run") == conversation.run),
                                 "main")
        except Exception as error:
            self.agent.log(f"cannot describe session {self.host_session}: {error}")
            self.agent_id = "main"
        self.followed.add(self.agent_id)
        threading.Thread(target=self._follow, args=(conversation, self.agent_id, True, stop), daemon=True,
                         name=f"acp-follow-{self.id}").start()
        threading.Thread(target=self._watch, args=(stop,), daemon=True, name=f"acp-watch-{self.id}").start()

    def cancel(self) -> None:
        """End the conversation's turn (the conversation stays for the next prompt), then
        answer the open prompt with cancelled."""
        with self.lock:
            turn = self.turn
            if turn is None or turn.done.is_set():
                return
            turn.cancelled = True
            conversation = self.conversation
        if conversation is not None:
            try:
                conversation.cancel()
            except Exception as error:
                self.agent.log(f"cancelling the turn of {getattr(conversation, 'run', '?')}: {error}")
        turn.end("cancelled")

    def shut(self) -> None:
        """The client went away: close the conversation and end the open turn."""
        with self.lock:
            turn = self.turn
            conversation, self.conversation = self.conversation, None
            if turn is not None:
                turn.cancelled = True
            if self.stop is not None:
                self.stop.set()
        if conversation is not None:
            self._close(conversation)
        if turn is not None:
            turn.end("cancelled")

    def _close(self, conversation) -> None:
        try:
            conversation.close()
        except Exception as error:
            self.agent.log(f"closing {getattr(conversation, 'run', '?')}: {error}")

    # Records.

    def _follow(self, conversation, agent: str, main: bool, stop: threading.Event) -> None:
        """Follow one agent's records until its conversation ends or `stop` is set."""
        try:
            for record in conversation.records(stop=stop):
                if stop.is_set():
                    return
                self._record(record, agent, main, stop)
        except Exception as error:
            if main:
                self.agent.log(f"lost session {self.host_session}: {error}")
                with self.lock:
                    if self.stop is stop:
                        stop.set()
                        self.conversation = None
                        if self.turn is not None:
                            self.turn.end(None, error)
            return
        if main:
            with self.lock:
                if self.stop is stop and not stop.is_set():
                    stop.set()
                    self.conversation = None
                    if self.turn is not None:
                        self.turn.end("end_turn")

    def _record(self, record: dict, agent: str, main: bool, stop: threading.Event) -> None:
        with self.lock:
            if stop.is_set():
                return
            kind = record.get("event")
            if kind in ("confirmation_request", "physical_request"):
                self.requests[agent] = record
            if kind == "state" and record.get("status") == WAITING:
                request = self.requests.get(agent)
                if record.get("reason") == "physical" and isinstance(record.get("request"), dict):
                    request = {"event": "physical_request", **record["request"]}
                key = (self.host_session, agent, (request or {}).get("id"))
                if key[2] and key not in self.asking:
                    self.asking.add(key)
                    threading.Thread(target=self._ask, args=(key, main, request, stop), daemon=True,
                                     name=f"acp-ask-{self.id}").start()
            if not main:
                return
            for update in self.updates.of(record):
                self.agent.update(self.id, update)
            turn = self.turn
            if turn is None or turn.done.is_set():
                return
            if kind == "turn_result":
                # The turn's result ends the prompt; the conversation stays for the next one.
                turn.end(STOP_REASONS.get(record.get("reason"), "end_turn"))
            elif kind == "state" and record.get("status") in sessions.ENDED:
                stop.set()
                self.conversation = None
                turn.end("refusal" if record.get("status") == "ERROR" else "end_turn")

    def _watch(self, stop: threading.Event) -> None:
        """Follow the session's other agents (sub-agents) for what they wait for."""
        host = self.agent.host()
        while not stop.wait(self.agent.poll):
            try:
                row = host.session(self.host_session).row
            except Exception:
                continue
            for item in row.get("agents") or []:
                name = item.get("id")
                if not name or name in self.followed or item.get("status") in sessions.ENDED:
                    continue
                self.followed.add(name)
                try:
                    conversation = host.conversation(f"{self.host_session}/{name}")
                except Exception as error:
                    self.agent.log(f"cannot follow agent {name} of {self.host_session}: {error}")
                    continue
                threading.Thread(target=self._follow, args=(conversation, name, False, stop), daemon=True,
                                 name=f"acp-follow-{self.id}-{name}").start()

    # Approvals.

    def _waits(self, session: str, agent: str, request_id: str) -> bool:
        """Whether the same request is still pending in the host."""
        try:
            row = self.agent.host().session(session, lines=0).row
        except Exception:
            return False
        return any(item.get("id") == agent and item.get("status") == WAITING
                   and item.get("approval_id") == request_id for item in row.get("agents") or [])

    def _ask(self, key: tuple, main: bool, request: dict, stop: threading.Event) -> None:
        """Ask the editor's user to approve what `agent` waits for, and answer the host."""
        session, agent, request_id = key
        try:
            # A sub-agent's records are read from its start: a wait already answered is
            # not asked about.
            if not main and not self._waits(session, agent, request_id):
                return
            with self.lock:
                if stop.is_set():
                    return
                title, kind, content = approval_call(request)
                if not main:
                    title = f"{title} (agent {agent})"
                tool = f"approval-{next(self.calls)}"
                program = main and kind == "execute"
                self.agent.update(self.id, {"sessionUpdate": "tool_call", "toolCallId": tool, "title": title,
                                            "kind": kind, "status": "pending", "content": content})
            answer = self.agent.connection.request("session/request_permission", {
                "sessionId": self.id, "toolCall": {"toolCallId": tool, "title": title, "kind": kind},
                "options": OPTIONS})
            outcome = (answer or {}).get("outcome") or {}
            if stop.is_set():
                # Cancelled or ended meanwhile: the prompt has its answer already.
                return
            selected = outcome.get("outcome") == "selected"
            accept = selected and outcome.get("optionId") == "allow_once"
            reason = "" if accept else ("the user rejected it in the editor" if selected else
                                        "the editor cancelled the request")
            with self.lock:
                if accept and program:
                    # The program's run shows in this tool call.
                    self.updates.adopt = tool
            try:
                self.agent.host().approve(session, accept, reason, agent, "once", request_id=request_id)
            except Exception as error:
                self.agent.log(f"approving for agent {agent} of {session}: {error}")
                with self.lock:
                    if self.updates.adopt == tool:
                        self.updates.adopt = None
                self.agent.update(self.id, {"sessionUpdate": "tool_call_update", "toolCallId": tool,
                                            "status": "failed", "content": _content(str(error))})
                return
            if accept and program:
                return
            self.agent.update(self.id, {"sessionUpdate": "tool_call_update", "toolCallId": tool,
                                        "status": "completed" if accept else "failed",
                                        "content": _content("allowed" if accept else f"rejected: {reason}")})
        finally:
            with self.lock:
                self.asking.discard(key)


class Agent:
    """The ACP agent. `host` is the session host's client (harness.sdk Host); without one,
    the user's host is connected to (and started) at the first prompt. `poll` is how
    often a session's other agents are looked for, in seconds."""

    def __init__(self, host=None, *, connect=None, workspace: str = "auto", log=_log, poll: float = 1.0):
        self._host = host
        self._connect = connect or _connect
        self._host_lock = threading.Lock()
        self.workspace = workspace
        self.log = log
        self.poll = poll
        self.sessions = {}
        self.connection = None

    def host(self):
        with self._host_lock:
            if self._host is None:
                self._host = self._connect(self.log)
            return self._host

    def update(self, session: str, update: dict) -> None:
        self.connection.notify("session/update", {"sessionId": session, "update": update})

    def serve(self, reader, writer) -> int:
        """Answer the client's messages from `reader` on `writer` until `reader` ends."""
        self.connection = Connection(writer, self.log)
        try:
            for line in iter(reader.readline, ""):
                if line.strip():
                    self._message(line)
        finally:
            self.connection.close()
            for session in list(self.sessions.values()):
                session.shut()
        return 0

    def _message(self, line: str) -> None:
        try:
            message = json.loads(line)
        except ValueError as error:
            self.connection.fail(None, PARSE_ERROR, f"not JSON: {error}")
            return
        if not isinstance(message, dict):
            self.connection.fail(None, INVALID_REQUEST, "a message is a JSON object")
            return
        method = message.get("method")
        if method is None:
            if "id" in message and ("result" in message or "error" in message):
                self.connection.answered(message)
            else:
                self.connection.fail(message.get("id"), INVALID_REQUEST, "neither a request nor a response")
            return
        identifier = message.get("id")
        request = "id" in message
        params = message.get("params") or {}
        handler = {"initialize": self.initialize, "authenticate": self.authenticate, "session/new": self.new_session,
                   "session/prompt": self.prompt, "session/cancel": self.cancel}.get(method)
        if handler is None:
            if request:
                self.connection.fail(identifier, METHOD_NOT_FOUND, f"method not found: {method}")
            return
        if method == "session/prompt" and request:
            # A prompt runs while the loop goes on reading (cancel, permission answers).
            threading.Thread(target=self._call, args=(handler, identifier, params, request), daemon=True,
                             name="acp-prompt").start()
            return
        self._call(handler, identifier, params, request)

    def _call(self, handler, identifier, params, request: bool) -> None:
        try:
            if not isinstance(params, dict):
                raise AcpError(INVALID_PARAMS, "params is an object")
            result = handler(params)
        except AcpError as error:
            if request:
                self.connection.fail(identifier, error.code, str(error))
            return
        except Exception as error:
            self.log(f"{type(error).__name__}: {error}")
            if request:
                self.connection.fail(identifier, INTERNAL_ERROR, f"{type(error).__name__}: {error}")
            return
        if request:
            self.connection.respond(identifier, result if result is not None else {})

    # Methods.

    def initialize(self, params: dict) -> dict:
        return {"protocolVersion": PROTOCOL_VERSION,
                "agentCapabilities": {"loadSession": False,
                                      "promptCapabilities": {"image": False, "audio": False, "embeddedContext": False},
                                      "mcpCapabilities": {"http": False, "sse": False}},
                "authMethods": [],
                "agentInfo": {"name": "harness-acp", "title": "The Harness", "version": __version__}}

    def authenticate(self, params: dict) -> dict:
        # No method to authenticate with: the session host is the user's own.
        return {}

    def new_session(self, params: dict) -> dict:
        if params.get("mcpServers"):
            self.log("the client's MCP servers are not used; the agent has its own")
        identifier = f"sess_{uuid.uuid4().hex}"
        self.sessions[identifier] = Session(self, identifier, str(params.get("cwd") or ""))
        return {"sessionId": identifier}

    def _session(self, params: dict) -> Session:
        session = self.sessions.get(params.get("sessionId"))
        if session is None:
            raise AcpError(INVALID_PARAMS, f"no session {params.get('sessionId')!r}")
        return session

    def prompt(self, params: dict) -> dict:
        session = self._session(params)
        text = prompt_text(params.get("prompt"))
        if not text:
            raise AcpError(INVALID_PARAMS, "the prompt has no text")
        return session.prompt(text)

    def cancel(self, params: dict) -> None:
        session = self.sessions.get(params.get("sessionId"))
        if session is not None:
            threading.Thread(target=session.cancel, daemon=True, name="acp-cancel").start()
