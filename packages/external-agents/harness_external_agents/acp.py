"""ACP v1 client for an explicitly configured external agent on stdio."""

from concurrent.futures import Future
from contextlib import suppress
from base64 import b64encode
import itertools
import json
import mimetypes
import os
from pathlib import Path
import hashlib
from queue import Full, Queue
import signal
import subprocess
import threading
import time
import secrets

from harness.sdk import file_lock, home, read_records

from .session import Session
from .scope import ProjectGrant


MAX_FRAME = 16 * 1024 * 1024


class Peer:
    def __init__(self, argv, cwd, receive, lost, environment=None):
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        self.process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=environment, **flags)
        self.receive, self.lost = receive, lost
        self.ids = itertools.count(1)
        self.pending = {}
        self.lock = threading.Lock()
        self.closed = False
        self.outbound = Queue(maxsize=64)

    def start(self):
        threading.Thread(target=self._write, name="acp-stdin", daemon=True).start()
        threading.Thread(target=self._read, name="acp-stdout", daemon=True).start()

    def _send(self, message):
        line = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        if len(line) > MAX_FRAME:
            raise ValueError("ACP frame is too large")
        if self.closed:
            raise RuntimeError("the ACP connection ended")
        try:
            self.outbound.put_nowait(line)
        except Full:
            raise RuntimeError("the ACP agent is no longer accepting input") from None

    def _write(self):
        try:
            for line in iter(self.outbound.get, None):
                if self.closed:
                    return
                self.process.stdin.write(line)
                self.process.stdin.flush()
        except (OSError, ValueError):
            self.close()

    def request(self, method, params):
        with self.lock:
            identifier = next(self.ids)
            result = self.pending[identifier] = Future()
            try:
                self._send({"id": identifier, "method": method, "params": params})
            except BaseException:
                self.pending.pop(identifier, None)
                raise
        return result

    def notify(self, method, params):
        with self.lock:
            self._send({"method": method, "params": params})

    def reply(self, identifier, *, result=None, error=None):
        with self.lock:
            self._send({"id": identifier, **({"error": error} if error else {"result": result})})

    def _read(self):
        problem = "the ACP agent disconnected"
        try:
            while line := self.process.stdout.readline(MAX_FRAME + 1):
                if len(line) > MAX_FRAME or not line.endswith(b"\n"):
                    raise ValueError("invalid ACP frame size")
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError("invalid ACP JSON-RPC message")
                if "method" in message:
                    self.receive(message)
                elif "id" in message:
                    with self.lock:
                        result = self.pending.pop(message["id"], None)
                    if result is not None:
                        if "error" in message:
                            error = message["error"] or {}
                            result.set_exception(RuntimeError(f"ACP request failed ({error.get('code')}). "
                                                              "Check the adapter and its native authentication."))
                        else:
                            result.set_result(message.get("result") or {})
        except (ValueError, TypeError, OSError, RuntimeError) as error:
            problem = str(error)
        finally:
            with self.lock:
                pending, self.pending = self.pending, {}
            for result in pending.values():
                result.set_exception(RuntimeError(problem))
            self.process.stdout.close()
            self.lost(problem)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            with suppress(Full):
                self.outbound.put_nowait(None)
        if self.process.poll() is None:
            if os.name == "nt":
                with suppress(OSError, subprocess.TimeoutExpired):
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                with suppress(OSError):
                    self.process.kill()
            else:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
        with suppress(OSError):
            self.process.stdin.close()
        with suppress(subprocess.TimeoutExpired):
            self.process.wait(5)


class AcpSession(Session):
    def __init__(self, directory, adapter, cwd, argv, model=None, effort=None, environment=None, *, restore=None):
        super().__init__(directory, adapter, cwd, model, effort, append=restore is not None)
        self.argv, self.environment = argv, environment
        self.peer = None
        self.external_id = None
        self.negotiated = {}
        self.options = []
        self.modes = []
        self.commands = []
        self.active = None
        self.stopping = False
        self.next_prompt = None
        self.reply_chunks = []
        self.tools = {}
        self.cancel_timer = None
        self.restore = restore
        self.replay = None
        self.lease = None
        self.mcp_tools = ()
        self.grant = None
        self.question = None
        self.auth_method = None
        self.permission_ids = set()

    @property
    def capabilities(self):
        return {**super().capabilities, **({"configure": bool(self.options or self.modes),
                                            "answer": self.question is not None,
                                            "config_options": self.options, "modes": self.modes,
                                            "commands": self.commands} if not self.ended else {})}

    def open(self, text, files):
        with self.lock:
            if self.ended:
                return
            self.peer = Peer(self.argv, self.cwd, self.receive, self.disconnected, self.environment)
            self.peer.start()
        answer = self.peer.request("initialize", {"protocolVersion": 1,
                                                "clientCapabilities": {"elicitation": {"form": {}}},
                                                "clientInfo": {"name": "the-harness", "version": "1"}}).result(20)
        if answer.get("protocolVersion") != 1:
            raise ValueError("the agent did not negotiate ACP v1")
        self.negotiated = answer.get("agentCapabilities") or {}
        methods = answer.get("authMethods") or []
        if methods:
            self.trace.emit("external_auth_methods", methods=[{"id": row.get("id"), "name": row.get("name")}
                                                              for row in methods])
        if self.auth_method:
            if self.auth_method not in {row.get("id") for row in methods}:
                raise ValueError("the configured ACP authentication method was not advertised")
            self.peer.request("authenticate", {"methodId": self.auth_method}).result(30)
        lifecycle = self.negotiated.get("sessionCapabilities") or {}
        with self.lock:
            if self.ended:
                return
            if self.mcp_tools:
                if not (self.negotiated.get("mcpCapabilities") or {}).get("http"):
                    raise ValueError("the selected ACP agent did not advertise HTTP MCP")
                self.grant = ProjectGrant(self, self.mcp_tools)
                self.session_metadata["mcp_tools"] = list(self.mcp_tools)
            params = {"cwd": str(self.cwd), "mcpServers": [self.grant.options()] if self.grant else []}
        if self.restore:
            identifier = self.restore["external_id"]
            self._claim(identifier)
            with self.lock:
                self.external_id = identifier
                self.replay = []
            if lifecycle.get("resume"):
                method = "session/resume"
            elif self.negotiated.get("loadSession"):
                method = "session/load"
            else:
                raise ValueError("this ACP agent did not advertise original session recovery")
            session = self.peer.request(method, {**params, "sessionId": identifier}).result(45)
        else:
            session = self.peer.request("session/new", params).result(30)
            identifier = session["sessionId"]
            self._claim(identifier)
        with self.lock:
            if self.ended:
                return
            self.external_id = identifier
            self.session_metadata["external_id"] = self.external_id
            if self.replay is not None:
                self._merge_replay()
                self.replay = None
            self.identity_changed()
            self.options = session.get("configOptions") or []
            self.modes = (session.get("modes") or {}).get("availableModes") or []
            self.controls.update(send=True, steer=True, cancel_turn=True,
                                 load=bool(self.negotiated.get("loadSession")), resume=bool(lifecycle.get("resume")),
                                 discover=bool(lifecycle.get("list")), attachments=True)
        if any(self.config.main.values()):
            self.set_model(**self.config.main)
        if text or files:
            self.send_message(text, files)
        else:
            with self.lock:
                self.state("IDLE", "message")

    def _merge_replay(self):
        if not self.replay:
            return
        history = []
        for item in self.replay:
            event = "user_message" if item["role"] == "user" else "agent_message"
            if history and history[-1][0] == event:
                history[-1] = event, history[-1][1] + item["text"]
            else:
                history.append((event, item["text"]))
        previous = [(row["event"], row["text"]) for row in read_records(self.directory)
                    if row.get("event") in ("user_message", "agent_message") and isinstance(row.get("text"), str)]
        if len(self.replay) < 256 and history[:len(previous)] == previous:
            for event, text in history[len(previous):]:
                self.trace.emit(event, text=text, replay=True)
        else:
            self.trace.emit("external_history_snapshot", replay=True, messages=self.replay,
                            incomplete=len(self.replay) >= 256)

    def _claim(self, identifier):
        # ACP session IDs are opaque. Serialize all local Harness controllers for the
        # same configured adapter and native session even across host restarts.
        adapter = self.session_metadata["adapter_id"]
        name = hashlib.sha256(f"{adapter}\0{identifier}".encode()).hexdigest()
        lease = file_lock(home() / "acp-registry" / "leases" / f"{name}.lock", blocking=False)
        with self.lock:
            if self.ended:
                raise RuntimeError("the ACP session closed while connecting")
            lease.__enter__()
            self.lease = lease

    def _prompt(self, text, files):
        prompt = [{"type": "text", "text": text}] if text else []
        for file in files:
            path = Path(file).expanduser().resolve(strict=True)
            if not path.is_file():
                raise ValueError("ACP attachments must be files")
            media = mimetypes.guess_type(path.name)[0]
            media_kind = media.split("/", 1)[0] if media else None
            supported = self.negotiated.get("promptCapabilities") or {}
            if media_kind in ("image", "audio") and supported.get(media_kind):
                if path.stat().st_size > 4 * 1024 * 1024:
                    raise ValueError("inline ACP attachments are limited to 4 MiB")
                prompt.append({"type": media_kind, "mimeType": media, "data": b64encode(path.read_bytes()).decode()})
                continue
            prompt.append({"type": "resource_link", "uri": path.as_uri(), "name": path.name,
                           **({"mimeType": media} if media else {})})
        if not prompt:
            raise ValueError("write a message or attach a file")
        return prompt

    def send_message(self, text, files=()):
        prompt = self._prompt(text, files)
        with self.lock:
            self._start_turn(text, prompt)

    def _start_turn(self, text, prompt):
        if self.ended or not self.external_id or self.active is not None:
            raise ValueError("the ACP session is busy or unavailable")
        self.begin(text)
        self.reply_chunks.clear()
        self.active = self.peer.request("session/prompt", {"sessionId": self.external_id, "prompt": prompt})
        threading.Thread(target=self._finish_turn, args=(self.active,), name="acp-turn", daemon=True).start()

    def steer(self, text, files=()):
        prompt = self._prompt(text, files)
        with self.lock:
            if self.active is None:
                self._start_turn(text, prompt)
                return
            if self.ended or self.next_prompt is not None:
                raise ValueError("an ACP interruption is already queued or the session ended")
            self.next_prompt = (text, prompt)
            self._cancel()

    def cancel(self):
        with self.lock:
            self.next_prompt = None
            self._cancel()

    def _cancel(self):
        if self.active is None or self.ended or self.stopping:
            return
        self.stopping = True
        self.state("RUNNING", "cancelling")
        self.cancel_permissions()
        self.peer.notify("session/cancel", {"sessionId": self.external_id})
        self.cancel_timer = threading.Timer(15, self._cancel_timeout, args=(self.active,))
        self.cancel_timer.daemon = True
        self.cancel_timer.start()

    def _cancel_timeout(self, future):
        with self.lock:
            timed_out = self.active is future and self.stopping and not self.ended
        if timed_out:
            self.fail("the ACP agent did not finish the cancelled turn; reconnect to recover it")

    def _finish_turn(self, future):
        try:
            answer = future.result()
            with self.lock:
                if self.ended or self.active is not future:
                    return
                if self.cancel_timer:
                    self.cancel_timer.cancel()
                self.cancel_permissions()
                for span in self.tools.values():
                    self.trace.emit("span_end", id=span, status="interrupted")
                self.tools.clear()
                if self.reply_chunks:
                    self.trace.emit("agent_message", text="".join(self.reply_chunks))
                self.trace.emit("external_turn_end", stop_reason=answer.get("stopReason"))
                self.active = None
                self.stopping = False
                next_prompt, self.next_prompt = self.next_prompt, None
                self.state("IDLE", "message")
                if next_prompt is not None:
                    self._start_turn(*next_prompt)
        except Exception as error:
            self.fail(error)

    def disconnected(self, reason):
        with self.lock:
            if not self.ended:
                self.trace.emit("external_connection", connected=False, reason=reason)
                self.end("INTERRUPTED")
        self.stop_transport()

    def close_transport(self):
        if self.peer:
            self.peer.close()
        with self.lock:
            if self.grant is not None:
                self.grant.close()
                self.grant = None
            if self.lease is not None:
                self.lease.__exit__(None, None, None)
                self.lease = None

    def receive(self, message):
        method, params = message["method"], message.get("params") or {}
        identifier = message.get("id")
        with self.lock:
            if method == "session/update" and identifier is None and params.get("sessionId") == self.external_id:
                if not self.ended:
                    self.update(params.get("update") or {})
            elif method == "session/request_permission" and identifier is not None:
                self._permission(identifier, params)
            elif method == "elicitation/create" and identifier is not None:
                self._elicit(identifier, params)
            elif method == "$/cancel_request":
                target = params.get("requestId")
                if self.question and self.question["peer_id"] == target:
                    self._dismiss_question("cancel")
            elif identifier is not None:
                self.peer.reply(identifier, error={"code": -32601, "message": "Unsupported client method"})

    def _permission(self, identifier, params):
        def reply(choice):
            outcome = {"outcome": "cancelled"} if choice is None else {"outcome": "selected", "optionId": choice}
            self.peer.reply(identifier, result={"outcome": outcome})

        if (self.ended or self.stopping or self.active is None or self.question
                or params.get("sessionId") != self.external_id):
            reply(None)
            return
        if type(identifier) not in (int, str):
            return
        if identifier in self.permission_ids:
            return
        self.permission_ids.add(identifier)
        tool = params.get("toolCall") or {}
        options = {row["kind"]: row["optionId"] for row in params.get("options", [])
                   if row.get("kind") in ("allow_once", "reject_once") and isinstance(row.get("optionId"), str)}
        if not options:
            reply(None)
            return
        description = {"title": tool.get("title"), "kind": tool.get("kind"),
                       "locations": tool.get("locations"), "input": tool.get("rawInput"),
                       "content": tool.get("content")}
        self.offer(str(tool.get("toolCallId") or identifier), json.dumps(description, ensure_ascii=False), options, reply)

    def _elicit(self, identifier, params):
        schema = params.get("requestedSchema") or {}
        fields = schema.get("properties") or {}
        if (self.ended or self.stopping or self.active is None or self.question or self.pending
                or params.get("sessionId") != self.external_id or params.get("mode") != "form"
                or schema.get("type") != "object" or not isinstance(fields, dict) or len(fields) > 20
                or any(not isinstance(field, dict) or field.get("type") not in ("string", "number", "integer", "boolean")
                       for field in fields.values())):
            self.peer.reply(identifier, result={"action": "decline"})
            return
        local_id = secrets.token_urlsafe(18)
        timer = threading.Timer(120, self._expire_question, args=(local_id,))
        timer.daemon = True
        self.question = {"id": local_id, "peer_id": identifier, "turn": self.turn, "schema": schema,
                         "deadline": time.monotonic() + 120, "timer": timer}
        self.trace.emit("external_question", id=local_id, text=str(params.get("message") or ""), schema=schema)
        self.state("WAITING_FOR_INPUT", "agent question")
        timer.start()

    def _expire_question(self, identifier):
        with self.lock:
            if (self.question or {}).get("id") == identifier:
                self._dismiss_question("cancel")

    def _dismiss_question(self, action, content=None):
        item, self.question = self.question, None
        if item is None:
            return
        item["timer"].cancel()
        self.trace.emit("external_question_resolved", id=item["id"], action=action)
        try:
            self.peer.reply(item["peer_id"], result={"action": action, **({"content": content} if content else {})})
        except (OSError, RuntimeError):
            pass
        if self.status == "WAITING_FOR_INPUT" and not self.ended:
            self.state("RUNNING", "agent question resolved")

    def answer(self, request_id, content):
        with self.lock:
            item = self.question
            if (not item or item["id"] != request_id or item["turn"] != self.turn
                    or item["deadline"] <= time.monotonic() or self.stopping or self.ended):
                raise ValueError("the agent's question is no longer pending")
            if content is None:
                self._dismiss_question("decline")
                return
            fields = item["schema"].get("properties") or {}
            if not isinstance(content, dict) or set(content) - fields.keys() or set(item["schema"].get("required", [])) - content.keys():
                raise ValueError("answer with the required fields of the advertised form")
            types = {"string": (str,), "number": (int, float), "integer": (int,), "boolean": (bool,)}
            for name, value in content.items():
                field = fields[name]
                if (type(value) not in types[field["type"]] or "enum" in field and value not in field["enum"]
                        or isinstance(value, str) and (len(value) < field.get("minLength", 0)
                                                      or len(value) > min(8192, field.get("maxLength", 8192)))
                        or type(value) in (int, float) and not field.get("minimum", -float("inf")) <= value <= field.get("maximum", float("inf"))):
                    raise ValueError(f"invalid answer for {name}")
            self._dismiss_question("accept", content)

    def cancel_permissions(self):
        self._dismiss_question("cancel")
        super().cancel_permissions()

    def update(self, value):
        kind = value.get("sessionUpdate")
        if self.replay is not None and kind in ("user_message_chunk", "agent_message_chunk"):
            content = value.get("content") or {}
            if content.get("type") == "text" and len(self.replay) < 256:
                self.replay.append({"role": kind.split("_", 1)[0], "text": str(content.get("text") or "")[:8192]})
            return
        if kind == "config_option_update":
            self.options = value.get("configOptions") or []
        elif kind == "available_commands_update":
            self.commands = value.get("availableCommands") or []
        elif kind == "agent_message_chunk" and self.active is not None:
            part = value.get("content") or {}
            if part.get("type") == "text":
                self.reply_chunks.append(str(part.get("text") or ""))
                self.trace.emit("external_message_chunk", text=self.reply_chunks[-1])
        elif kind == "tool_call" and self.active is not None:
            identifier = value.get("toolCallId")
            if identifier and identifier not in self.tools:
                span = self.tools[identifier] = f"acp-{self.turn}-{identifier}"
                self.trace.emit("span_start", id=span, lane="program", name=str(value.get("title") or "external tool"))
                if value.get("status") in ("completed", "failed"):
                    self.trace.emit("span_end", id=self.tools.pop(identifier), status=value["status"])
        elif kind == "tool_call_update" and value.get("status") in ("completed", "failed"):
            span = self.tools.pop(value.get("toolCallId"), None)
            if span:
                self.trace.emit("span_end", id=span, status=value["status"])
        elif kind == "usage_update":
            self.trace.emit("external_usage", usage={key: value[key] for key in ("used", "size", "cost") if key in value})
        elif kind == "plan":
            self.trace.emit("plan", steps=[{"step": item.get("content"), "done": item.get("status") == "completed"}
                                          for item in value.get("entries") or []])
        elif kind in ("current_mode_update", "session_info_update"):
            self.trace.emit("external_update", update=value)

    def set_model(self, model=None, reasoning_effort=None):
        changes = {"model": model, "thought_level": reasoning_effort}
        for category, value in changes.items():
            if value is None:
                continue
            option = next((item for item in self.options if item.get("category") == category), None)
            if option is None:
                raise ValueError(f"the agent did not advertise a {category} option")
            self.set_config(option["id"], value)
        self.config.main.update({key: value for key, value in (("model", model), ("reasoning_effort", reasoning_effort))
                                 if value is not None})
        return dict(self.config.main)

    def set_config(self, identifier, value):
        with self.lock:
            if self.ended or self.active is not None:
                raise ValueError("wait for the current ACP turn to end before changing configuration")
            if any(option.get("id") == identifier for option in self.options):
                method, changes = "session/set_config_option", {"configId": identifier, "value": value}
            elif identifier == "mode" and any(mode.get("id") == value for mode in self.modes):
                method, changes = "session/set_mode", {"modeId": value}
            else:
                raise ValueError("the agent did not advertise this configuration option")
            response = self.peer.request(method, {"sessionId": self.external_id, **changes})
        answer = response.result(20)
        if "configOptions" in answer:
            self.options = answer["configOptions"]
        return {"config_options": self.options, "modes": self.modes}
