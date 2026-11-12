"""The Harness as an MCP server: the tools an MCP client (an app, an editor or an agent)
calls to give The Harness tasks on this computer and follow them.

The tools drive the user's session host (harness.sdk Host): a task starts a session of
the app's agent, the same as `harness run "task"` or the app's window does, and every
harness frontend lists and follows it. The host is connected on the first tool call that
needs it (and started when none runs); `host` gives one instead (tests give a fake).

Messages are JSON-RPC 2.0 (MCP protocol 2025-06-18; 2025-03-26 is accepted too). Two
transports, both standard library:

    serve_stdio(server)          newline-delimited messages on stdin and stdout
    http_server(server, port)    streamable HTTP on 127.0.0.1: POST /mcp takes a message
                                 (or a batch) and answers application/json

What a session waits for is reported, never answered: a program to confirm or a step of
physical input the physical-input policy holds is approved by the user in a harness
frontend (the app, the terminal chat, harness run's prompt). There is
no approve tool, so the agent that calls these tools never approves its own input.
"""

import base64
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import sys
import threading
import time
from urllib.parse import quote, urlparse

from harness.sdk import OwnPort, sessions, transcript


PROTOCOL_VERSION = "2025-06-18"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
SERVER_NAME = "the-harness"
# run_task waits at most this long for an answer; a longer task is polled with get_session.
WAIT_DEFAULT = 30
WAIT_MAX = 120
# Seconds between two reads of a session's new records while run_task waits.
POLL = 0.5
# Lines of progress run_task returns.
PROGRESS_LINES = 10
# A registry package's name: no path, URL or archive.
PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

INSTRUCTIONS = (
    "The Harness does tasks on this computer: in a browser, on the desktop and in its apps. "
    "run_task gives it a task and waits up to wait_seconds for the answer; a longer task returns its "
    "session id, which get_session polls. start_session, send_message and stop_session hold a "
    "conversation; observe_screen shows what it sees, read_events what it did. A session that waits "
    "for approval (a program, or physical input) is approved by the user in a harness frontend, never "
    "by these tools.")

APPROVAL = ("It waits for the user's approval (a program to confirm, or physical input the physical-input "
            "policy holds). The user approves it in a harness frontend: the app, or /approve in the terminal chat "
            "(`harness`, where /sessions picks session {session}). These tools cannot approve it; poll get_session.")


def harness_version() -> str:
    """The harness's version."""
    from harness.sdk import version

    return version


class ToolError(Exception):
    """A tool could not do what it was asked; its message goes to the caller (isError)."""


class RpcError(Exception):
    """A JSON-RPC error answer: its code and message."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def waiting_note(session: str, waiting) -> str | None:
    """What the caller can do about what a session waits for."""
    if not waiting:
        return None
    if waiting == "approval":
        return APPROVAL.format(session=session)
    if waiting == "message":
        return "It waits for a message: send_message, or stop_session when it is done."
    if waiting == "resume":
        return "It is paused; the user resumes it in a harness frontend."
    return f"It waits: {waiting}."


def _short(value, limit: int = 400):
    """A record's field, small: images as a mark, long text cut, nested values as short JSON."""
    if isinstance(value, str):
        if value.startswith("data:image") or (len(value) > 1000 and " " not in value[:1000]):
            return "<image>" if value.startswith("data:image") else "<binary>"
        return value if len(value) <= limit else value[:limit] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = json.dumps(value, ensure_ascii=False, default=str)
    text = re.sub(r"data:image/[a-z+.-]+;base64,[A-Za-z0-9+/=]+", "<image>", text)
    return text if len(text) <= limit else text[:limit] + "..."


# Fields of a record that hold images or whole observations: left out.
_HEAVY = {"image", "images", "frames", "screenshot", "observation", "cameras", "png", "jpeg"}


def compact(record: dict) -> dict:
    """A trace record as read_events gives it: seq, event, time and the main fields."""
    out = {"seq": record.get("seq"), "event": record.get("event"), "time": record.get("time")}
    for key, value in record.items():
        if key in out or key in _HEAVY:
            continue
        out[key] = _short(value)
    return out


def _schema(properties: dict, required=()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


_SESSION = {"type": "string", "description": "A session's id (or the unique start of one), as the tools return it."}
_WORKSPACE = {"type": "string", "default": "auto",
              "description": "Workspace kind supplied by an installed package; auto resolves the explicit binding."}
_BINDING = {
    "folder": {"type": "string", "description": "Existing project folder explicitly bound to this task."},
    "budget": {"type": "object", "additionalProperties": False, "properties": {
        "max_wall_seconds": {"type": "number", "exclusiveMinimum": 0},
        "max_model_calls": {"type": "integer", "minimum": 1},
        "max_cost_usd": {"type": "number", "exclusiveMinimum": 0}}}}

TOOLS = [
    {"name": "run_task",
     "description": "Give The Harness a task to do on this computer (in a browser, on the desktop, in its apps) "
                    "and wait at most wait_seconds for its answer. Returns the session id, its status, the "
                    "answer when there is one, what it waits for and its last lines of progress. A task that "
                    "takes longer keeps running: poll it with get_session.",
     "inputSchema": _schema({"task": {"type": "string", "description": "The task, in plain words."},
                             "workspace": _WORKSPACE, **_BINDING,
                             "wait_seconds": {"type": "number", "minimum": 0, "maximum": WAIT_MAX,
                                              "default": WAIT_DEFAULT,
                                              "description": f"How long to wait for the answer (at most {WAIT_MAX})."}},
                            ["task"])},
    {"name": "list_sessions",
     "description": "The sessions of The Harness on this computer, newest first: id, title, status and what "
                    "each waits for. With all, those that ended too.",
     "inputSchema": _schema({"all": {"type": "boolean", "default": False,
                                     "description": "Include the sessions that ended."}}),
     "annotations": {"readOnlyHint": True}},
    {"name": "start_session",
     "description": "Start a session on a task and return at once with its id; follow it with get_session, "
                    "talk to it with send_message, end it with stop_session.",
     "inputSchema": _schema({"task": {"type": "string", "description": "The task, in plain words."},
                             "workspace": _WORKSPACE, **_BINDING}, ["task"])},
    {"name": "send_message",
     "description": "Send a message to a session's agent: a follow-up task, an answer to its question, a "
                    "correction. It reads it at its next model call.",
     "inputSchema": _schema({"session": _SESSION, "text": {"type": "string", "description": "The message."}},
                            ["session", "text"])},
    {"name": "stop_session",
     "description": "End a session and every agent in it.",
     "inputSchema": _schema({"session": _SESSION}, ["session"]),
     "annotations": {"destructiveHint": True, "idempotentHint": True}},
    {"name": "get_session",
     "description": "A session now: its status, what it waits for (and who can answer it), its answer when it "
                    "has one, its agents and the last lines of its progress.",
     "inputSchema": _schema({"session": _SESSION,
                             "lines": {"type": "integer", "minimum": 0, "maximum": 200, "default": 20,
                                       "description": "How many lines of progress."}}, ["session"]),
     "annotations": {"readOnlyHint": True}},
    {"name": "observe_screen",
     "description": "The screen of a session's workspace now, as an image.",
     "inputSchema": _schema({"session": _SESSION}, ["session"]),
     "annotations": {"readOnlyHint": True}},
    {"name": "read_events",
     "description": "A session's trace records after seq `after`, compact (event, time and the main fields, "
                    "no images), at most `limit` of them; next_after pages on.",
     "inputSchema": _schema({"session": _SESSION,
                             "after": {"type": "integer", "default": -1,
                                       "description": "The seq to read after (-1: from the start)."},
                             "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50,
                                       "description": "At most this many records."}}, ["session"]),
     "annotations": {"readOnlyHint": True}},
    {"name": "list_packages",
     "description": "The installed packages of The Harness, or with query the registry's packages that match.",
     "inputSchema": _schema({"query": {"type": "string", "description": "Search the registry for this."}}),
     "annotations": {"readOnlyHint": True}},
    {"name": "install_package",
     "description": "Install an official package of The Harness from its registry, by name (list_packages "
                    "with a query finds them). Other sources are installed by the user in a harness frontend.",
     "inputSchema": _schema({"name": {"type": "string", "description": "The package's name in the registry."}},
                            ["name"])},
    {"name": "list_library",
     "description": "What The Harness learned: its libraries, or with name one library's entries.",
     "inputSchema": _schema({"name": {"type": "string", "description": "A library's name."}}),
     "annotations": {"readOnlyHint": True}},
]


def _text_argument(arguments: dict, key: str, required: bool = True) -> str | None:
    value = arguments.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"give {key} (a non-empty string)")
    return value.strip()


def _number_argument(arguments: dict, key: str, default, low, high, kind=float):
    value = arguments.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError(f"{key} is a number")
    return kind(min(max(value, low), high))


class McpServer:
    """The protocol and the tools over one session host. `host` is the host to use; else
    `connect()` gives it (default: Host.connect, starting the host when none runs) on the
    first tool call that needs it. `log` takes the server's notes (default: stderr)."""

    def __init__(self, host=None, connect=None, log=None, poll: float = POLL):
        self._host = host
        self._connect = connect
        self._lock = threading.Lock()
        self.log = log or (lambda message: print(f"harness mcp: {message}", file=sys.stderr, flush=True))
        self.poll = poll
        self.version = harness_version()

    # The host.

    def host(self):
        with self._lock:
            if self._host is None:
                if self._connect is not None:
                    self._host = self._connect()
                else:
                    from harness.sdk import Host

                    self._host = Host.connect(start=True, log=self.log)
                if self._host is None:
                    raise ToolError("no session host runs and none could be started")
            return self._host

    # The protocol.

    def handle(self, message):
        """The answer to one message or a batch (a list); None when nothing is answered
        (notifications, responses)."""
        if isinstance(message, list):
            if not message:
                return _error(None, -32600, "an empty batch")
            answers = [answer for answer in map(self._one, message) if answer is not None]
            return answers or None
        return self._one(message)

    def _one(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(message.get("id") if isinstance(message, dict) else None, -32600,
                          "not a JSON-RPC 2.0 message")
        method = message.get("method")
        has_id = "id" in message
        if method is None:
            return None  # a response to a request of ours: none are sent
        if not isinstance(method, str):
            return _error(message.get("id"), -32600, "method is a string")
        params = message.get("params") or {}
        try:
            if not isinstance(params, dict):
                raise RpcError(-32602, "params is an object")
            result = self._request(method, params)
        except RpcError as error:
            return _error(message.get("id"), error.code, str(error)) if has_id else None
        except Exception as error:  # a fault of the server's own
            self.log(f"{method}: {error!r}")
            return _error(message.get("id"), -32603, f"internal error: {error}") if has_id else None
        if not has_id:
            return None  # a notification
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    def _request(self, method: str, params: dict):
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": self.version},
                    "instructions": INSTRUCTIONS}
        if method.startswith("notifications/"):
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self.call(params.get("name"), params.get("arguments") or {})
        raise RpcError(-32601, f"method not found: {method}")

    def call(self, name, arguments) -> dict:
        """A tool's result: {"content", "isError"} and, for data, "structuredContent"."""
        if name not in {tool["name"] for tool in TOOLS}:
            raise RpcError(-32602, f"no tool {name!r}")
        if not isinstance(arguments, dict):
            raise RpcError(-32602, "arguments is an object")
        try:
            result = getattr(self, f"tool_{name}")(arguments)
        except ToolError as error:
            return {"content": [{"type": "text", "text": str(error)}], "isError": True}
        except Exception as error:  # the host refused, or is gone
            return {"content": [{"type": "text", "text": f"{name}: {error}"}], "isError": True}
        if isinstance(result, dict) and "content" in result:
            return {"isError": False, **result}
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                "structuredContent": result, "isError": False}

    # Sessions.

    def _start(self, arguments: dict) -> tuple[str, str]:
        """Start a session of the app's agent on the task: (session id, run)."""
        task = _text_argument(arguments, "task")
        workspace = arguments.get("workspace") or "auto"
        if not isinstance(workspace, str) or not workspace.strip():
            raise ToolError("workspace must be the name of an installed workspace kind")
        binding = {}
        if "folder" in arguments:
            binding["folder"] = _text_argument(arguments, "folder")
        if "budget" in arguments:
            if not isinstance(arguments["budget"], dict):
                raise ToolError("budget must be an object")
            binding["budget"] = arguments["budget"]
        host = self.host()
        run = host.task(task, workspace, **binding).run
        try:
            session = host.session(run, lines=0).row["id"]
        except Exception:
            session = run
        return session, run

    def _row(self, session: str, lines: int = 0) -> dict:
        return self.host().session(session, lines=lines).row

    @staticmethod
    def _progress(row: dict) -> list[str]:
        agents = row.get("agents") or []
        lines = (agents[0].get("lines") if agents else None) or []
        return [line if len(line) <= 300 else line[:300] + "..." for line in map(str, lines)]

    def _describe(self, row: dict, answer=None, error=None) -> dict:
        out = {"session": row.get("id"), "run": row.get("run"), "title": row.get("title"),
               "status": row.get("status")}
        if answer is not None:
            out["answer"] = answer
        if error is not None:
            out["error"] = error
        waiting = row.get("waiting")
        if waiting and row.get("status") not in sessions.ENDED:
            out["waiting"] = waiting
            out["note"] = waiting_note(row.get("id"), waiting)
        out["progress"] = self._progress(row)
        return out

    def tool_run_task(self, arguments: dict) -> dict:
        begun = time.monotonic()
        wait = _number_argument(arguments, "wait_seconds", WAIT_DEFAULT, 0, WAIT_MAX)
        deadline = begun + wait
        session, run = self._start(arguments)
        host = self.host()
        after, answer, error, status, over = -1, None, None, None, False
        while True:
            for record in host.get(f"/api/events?run={quote(run, safe='')}&after={after}") or []:
                after = max(after, int(record.get("seq", after)))
                found = transcript.answer_of(record)
                if found is not None:
                    answer = found
                if record.get("event") == "error":
                    error = str(record.get("message") or "")
                if record.get("event") == "state":
                    status = record.get("status")
                # The turn's result: an answer, or the limit or error that ended it.
                over = over or record.get("event") == "turn_result"
            if (over or status in sessions.ENDED or status == "WAITING_FOR_CONFIRMATION"
                    or (status == "IDLE" and answer is not None)):
                break
            left = deadline - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(self.poll, left))
        if (over or answer is not None) and status not in sessions.ENDED:
            # The turn is over: the session ends, as `harness run "task"` ends it.
            try:
                host.stop_session(session)
            except Exception as stop_error:
                self.log(f"stopping {session}: {stop_error}")
        row = self._row(session, PROGRESS_LINES)
        out = self._describe(row, answer, error)
        out["session"], out["run"] = session, run
        if answer is None and out.get("status") not in sessions.ENDED and "waiting" not in out:
            out["note"] = "It still works on the task: poll it with get_session."
        return out

    def tool_start_session(self, arguments: dict) -> dict:
        session, run = self._start(arguments)
        row = self._row(session)
        return {"session": session, "run": run, "status": row.get("status")}

    def tool_list_sessions(self, arguments: dict) -> dict:
        rows = [item.row for item in self.host().sessions(all=bool(arguments.get("all")), limit=50)]
        return {"sessions": [{"session": row.get("id"), "title": row.get("title"), "status": row.get("status"),
                              "waiting": row.get("waiting"), "frontend": row.get("frontend"),
                              "created": row.get("created"), "agents": len(row.get("agents") or [])}
                             for row in rows]}

    def tool_send_message(self, arguments: dict) -> dict:
        session = _text_argument(arguments, "session")
        text = _text_argument(arguments, "text")
        self.host().conversation(session).send_message(text)
        return {"session": session, "sent": True}

    def tool_stop_session(self, arguments: dict) -> dict:
        session = _text_argument(arguments, "session")
        return {"session": session, "stopped": list(self.host().stop_session(session) or [])}

    def tool_get_session(self, arguments: dict) -> dict:
        session = _text_argument(arguments, "session")
        lines = _number_argument(arguments, "lines", 20, 0, 200, int)
        row = self._row(session, lines)
        answer = None
        for record in self.host().get(f"/api/events?run={quote(str(row.get('run') or session), safe='')}"
                                      "&after=-1") or []:
            found = transcript.answer_of(record)
            if found is not None:
                answer = found
        out = self._describe(row, answer)
        out["agents"] = [{"agent": agent.get("id"), "status": agent.get("status"), "waiting": agent.get("waiting"),
                          "depth": agent.get("depth")} for agent in row.get("agents") or []]
        return out

    def tool_observe_screen(self, arguments: dict) -> dict:
        session = _text_argument(arguments, "session")
        row = self._row(session)
        image = self.host().fetch(f"/api/app/screen?run={quote(str(row.get('run') or session), safe='')}")
        if not image:
            raise ToolError(f"session {session} shows no screen now")
        return {"content": [{"type": "image", "data": base64.b64encode(image).decode("ascii"),
                             "mimeType": "image/jpeg"},
                            {"type": "text", "text": f"The screen of session {row.get('id') or session} now "
                                                     f"({row.get('status')})."}]}

    def tool_read_events(self, arguments: dict) -> dict:
        session = _text_argument(arguments, "session")
        after = arguments.get("after", -1)
        if isinstance(after, bool) or not isinstance(after, int):
            raise ToolError("after is an integer")
        limit = _number_argument(arguments, "limit", 50, 1, 500, int)
        records = self.host().get(f"/api/events?run={quote(session, safe='')}&after={after}") or []
        taken = records[:limit]
        next_after = taken[-1].get("seq", after) if taken else after
        return {"session": session, "events": [compact(record) for record in taken], "next_after": next_after,
                "more": len(records) > limit}

    # Packages and the library.

    def tool_list_packages(self, arguments: dict) -> dict:
        query = arguments.get("query")
        if query is not None and not isinstance(query, str):
            raise ToolError("query is a string")
        host = self.host()
        if query:
            answer = host.get(f"/api/app/packages/search?q={quote(query, safe='')}")
            return {"query": query, "results": answer.get("results") or [],
                    **({"error": answer["error"]} if answer.get("error") else {})}
        answer = host.get("/api/app/packages")
        return {"packages": answer.get("packages") or [], "skills": answer.get("skills") or [],
                "auto_install": answer.get("auto_install")}

    def tool_install_package(self, arguments: dict) -> dict:
        name = _text_argument(arguments, "name")
        if not PACKAGE_NAME.match(name):
            raise ToolError(f"{name!r} is not a registry package's name; a folder, archive or URL is installed "
                            "by the user in a harness frontend")
        answer = self.host().post("/api/app/packages/install", {"source": name}, timeout=900)
        if answer.get("needs_trust"):
            raise ToolError(f"{name} is not an official package; the user installs it in a harness frontend")
        installed = [{"name": item.get("name"), "version": item.get("version")}
                     for item in answer.get("installed") or []]
        problems = [str(problem) for problem in answer.get("problems") or []]
        if problems and not installed:
            raise ToolError(f"{name} was not installed: " + "; ".join(problems))
        return {"installed": installed, "problems": problems}

    def tool_list_library(self, arguments: dict) -> dict:
        name = _text_argument(arguments, "name", required=False)
        host = self.host()
        if name is None:
            return {"libraries": host.get("/api/libraries").get("libraries") or []}
        answer = host.get(f"/api/library?name={quote(name, safe='')}")
        return {"name": answer.get("name", name), "version": answer.get("version"),
                "columns": answer.get("columns") or [], "entries": answer.get("entries") or []}


def _error(identifier, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


# stdio.

def serve_stdio(server: McpServer, stdin, stdout) -> None:
    """Read messages from `stdin` (one JSON message or batch a line) until it ends and
    write each answer as a line to `stdout`. Each request runs on a thread of its own, so a
    run_task that waits does not hold back a ping; the answers are written whole, one at a
    time. Returns when stdin ends and every request is answered."""
    lock = threading.Lock()
    pending = []

    def write(answer):
        with lock:
            stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
            stdout.flush()

    def answer(message):
        found = server.handle(message)
        if found is not None:
            write(found)

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError as error:
            write(_error(None, -32700, f"parse error: {error}"))
            continue
        if isinstance(message, dict) and message.get("method") == "initialize":
            answer(message)  # answered before anything that follows it
            continue
        thread = threading.Thread(target=answer, args=(message,), name="mcp-request", daemon=True)
        thread.start()
        pending.append(thread)
        pending = [item for item in pending if item.is_alive()]
    for thread in pending:
        thread.join()


# Streamable HTTP.

LOCAL_NAMES = ("localhost", "127.0.0.1", "::1")


def _local_origin(origin: str | None) -> bool:
    """Whether a request's Origin (when it has one) is a page of this computer."""
    if origin is None:
        return True
    try:
        return urlparse(origin).hostname in LOCAL_NAMES
    except ValueError:
        return False


class _Handler(BaseHTTPRequestHandler):
    server_version = "the-harness-mcp"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _reply(self, status: int, data: bytes = b"", content_type: str | None = None, headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _json(self, status: int, value, headers=None):
        self._reply(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json", headers)

    def _allowed(self) -> bool:
        if urlparse(self.path).path != "/mcp":
            self._json(HTTPStatus.NOT_FOUND, _error(None, -32600, "the endpoint is /mcp"))
            return False
        if not _local_origin(self.headers.get("Origin")):
            self._json(HTTPStatus.FORBIDDEN, _error(None, -32600, "requests come only from this computer"))
            return False
        return True

    def do_GET(self):
        if self._allowed():
            self._reply(HTTPStatus.METHOD_NOT_ALLOWED, headers={"Allow": "POST, DELETE"})

    def do_DELETE(self):
        if not self._allowed():
            return
        session = self.headers.get("Mcp-Session-Id")
        with self.server.lock:
            known = session in self.server.sessions
            self.server.sessions.discard(session)
        self._reply(HTTPStatus.OK if known else HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not self._allowed():
            return
        version = self.headers.get("MCP-Protocol-Version")
        if version and version not in PROTOCOL_VERSIONS:
            return self._json(HTTPStatus.BAD_REQUEST, _error(None, -32600, f"protocol version {version} is not "
                                                                         f"one of {', '.join(PROTOCOL_VERSIONS)}"))
        session = self.headers.get("Mcp-Session-Id")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            message = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            return self._json(HTTPStatus.BAD_REQUEST, _error(None, -32700, f"parse error: {error}"))
        messages = message if isinstance(message, list) else [message]
        initializes = any(isinstance(item, dict) and item.get("method") == "initialize" for item in messages)
        if session and not initializes:
            with self.server.lock:
                if session not in self.server.sessions:
                    return self._json(HTTPStatus.NOT_FOUND, _error(None, -32600, "no such session"))
        answer = self.server.mcp.handle(message)
        headers = {}
        if initializes:
            session = secrets.token_hex(16)
            with self.server.lock:
                self.server.sessions.add(session)
            headers["Mcp-Session-Id"] = session
        if answer is None:
            return self._reply(HTTPStatus.ACCEPTED, headers=headers)
        self._json(HTTPStatus.OK, answer, headers)


class _HttpServer(OwnPort, ThreadingHTTPServer):
    pass


def http_server(server: McpServer, port: int = 8790) -> ThreadingHTTPServer:
    """The streamable HTTP transport on 127.0.0.1:`port` (0: any free port), not yet
    serving: call serve_forever() (and shutdown() to stop)."""
    httpd = _HttpServer(("127.0.0.1", int(port)), _Handler)
    httpd.daemon_threads = True
    httpd.mcp = server
    httpd.sessions = set()
    httpd.lock = threading.Lock()
    return httpd
