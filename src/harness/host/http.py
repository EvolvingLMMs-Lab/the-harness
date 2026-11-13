"""The session host's HTTP server: the API every frontend drives conversations and follows
episodes through, over a runs directory, and the app package's pages when it is installed.

Standard library only (http.server). Every API call needs the session key: the
`token` query parameter of the URL harness app prints (the page then keeps it in a
cookie), or the X-Session-API-Key header. Records are followed with server-sent
events: a client that reconnects sends Last-Event-ID (the last `seq` it has) and gets
what came after it. Every record they send carries `view`, its items (transcript.py).

  GET  /api/runs                         the episodes, newest first
  GET  /api/meta?run=R                   an episode's manifest, summary, ending and usage
  GET  /api/events?run=R&after=N         its trace records after seq N
  GET  /api/lanes?run=R                  its timeline's lanes, spans and markers (core/lanes.py
                                         Lanes.snapshot), what every web view draws
  GET  /api/stream?run=R                 the same, then new ones as they are written
  GET  /api/file?run=R&name=F            one of its files (videos, logs), or a range of it

The page at / (the app's), the runs page at /dev, and at
/overlay?run=R the timeline overlay's (the app package's overlay: one run's timeline, or
without run the newest session that runs). Another package's pages are at the paths its host
module declares (pages(), harness/extensions.py), their files at /static/<package>/<file>;
its API (`api`) at /api/<package>/<name>, GET and POST alike, with the session key as every
other route.

Conversations the server runs itself (runtime/conversation.py, interactive), written
under <runs>/ui/; a POST takes a JSON body and the session key:

  GET  /api/options                      experiments, model files and the deploy to start from
  GET  /api/libraries                    what the agent learned: the libraries under $HARNESS_HOME
  GET  /api/library?name=N | run=R       a library's entries, or a run's memory beside its library's
                                         (runtime/task/context.py rows: one format, columns and cells)
  POST /api/conversations                start one: experiment, task, seed, model, endpoint,
                                         instruction, confirmation, sets, deploy, title,
                                         frontend, workspace (a kind: the app's server
                                         takes one from its pool for the session);
                                         {run, session}
  POST /api/conversations/message        {run, text, files}: a message for the model's next call (files:
                                         paths on this computer it attaches)
  POST /api/conversations/pause          {run}: stop at the next execution step
  POST /api/conversations/resume         {run}
  POST /api/conversations/model          {run, model, reasoning_effort}: the main model (another id of
                                         its provider) and its effort (none, low, medium, high; "" the
                                         provider's default) from its next call on
  POST /api/conversations/confirm        {run, accept, reason, remember}: the verdict on a waiting program, or
                                         on a step waiting for physical input (remember: once, app,
                                         session, always)
  POST /api/conversations/close          {run}: end the episode

A conversation's programs may start sub-agents (runtime/task/delegation.py); this server gives
them no workspaces (it has no pool: delegate says so), the app's does (app.py).

A run is the path of an episode under the runs directory or, for a conversation the
server runs, also its session's id ("<session>/<agent>" for an agent of it). The sessions
it runs, each a tree of agents (host/sessions.py):

  GET  /api/sessions                     the sessions, newest first
  GET  /api/sessions/show?id=S&lines=N   one session, its agents and the last lines of each
  POST /api/sessions/stop                {id, agent}: end its agents (or that one)
  POST /api/sessions/approve             {id, agent, accept, reason}: the verdict on what waits
"""

from contextlib import suppress
from functools import partial
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
import time
import traceback
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..settings import ChoiceRequired
from .sessions import ENDED, LIVE, Sessions, live
from ..paths import find
from harness.runtime.safety import approval
from harness.core import episodes as runs
from ..core.ports import OwnPort
from ..transcript import TextTranscript, items


def statics() -> dict:
    """{package: its ui/static/ folder} of the packages this process uses that have one."""
    from ..paths import packages

    return {package.name: (package.path / "ui" / "static").resolve() for package in packages()
            if (package.path / "ui" / "static").is_dir()}


def static() -> Path | None:
    """The folder of the page at / and of the files at /static/<file>: the app package's
    ui/static/; without it, that of the first package whose host module gives a page at /,
    else of the first package that has pages. None when no package this process uses has them."""
    from ..extensions import hosts

    folders = statics()
    if "app" in folders or not folders:
        return folders.get("app")
    for package, module in hosts():
        if "/" in (getattr(module, "pages", None) or {}) and package.name in folders:
            return folders[package.name]
    return next(iter(folders.values()))


def pages() -> dict:
    """{path: (folder, file)}: the pages this server has. The legacy ones (PAGES) are files
    of static()'s folder; a package's host module adds its own (`pages`, harness/extensions.py),
    files of its ui/static/. The page at / stays the app's; "/": None is the server's own
    (Server.page)."""
    from ..extensions import hosts

    folders = statics()
    default = static()
    found = {path: (default, page) for path, page in PAGES.items()
             if page is None or default is not None and (default / page).is_file()}
    for package, module in hosts():
        folder = folders.get(package.name)
        for path, page in (getattr(module, "pages", None) or {}).items():
            if folder is None or (path == "/" and folder != default) or path in found and path != "/":
                continue
            found[path] = (folder, page)
    return found


def package_api(path: str):
    """The handler a package's host module gives for /api/<package>/<name> (its `api`,
    harness/extensions.py), or None."""
    from ..extensions import hosts

    package, _, name = path.removeprefix("/api/").partition("/")
    if not path.startswith("/api/") or not name:
        return None
    for found, module in hosts():
        if found.name == package:
            return (getattr(module, "api", None) or {}).get(name)
    return None


MISSING = (b"<!doctype html><meta charset=utf-8><title>The Harness</title><p>No web frontend is installed. Use the terminal CLI or install a frontend package. "
           b"")
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                ".json": "application/json; charset=utf-8"}
COOKIE = "harness_ui"
# The pages of the package at / besides that one (the server's own: Server.page); other
# packages' pages are their host modules' (pages()).
PAGES = {"/": None, "/dev": "index.html", "/overlay": "overlay.html", "/replay": "app.html"}
# The workspace kind of a bench's worker (the computer package's workspaces.py KINDS, the
# other way round); a computer worker with the option workspace = "apps" or "display"
# serves that kind.
BENCH_KINDS = {"browser": "browser", "computer": "desktop"}


def bench_kind(bench: str, worker: dict | None = None) -> str | None:
    """The workspace kind an experiment's worker serves (None: one no pool starts)."""
    if bench == "computer" and (worker or {}).get("workspace") in ("apps", "display"):
        return worker["workspace"]
    return BENCH_KINDS.get(bench)
# Seconds between looks at a followed trace, and between keep-alive comments.
POLL_SECONDS = 0.25
KEEPALIVE_SECONDS = 15.0


# A run's lanes as last computed: {directory: ((size, mtime) of its trace, snapshot)}.
_LANES = {}
_LANES_LOCK = threading.Lock()


def lanes_of(directory: Path) -> dict:
    """The lanes of the run in `directory` (core/lanes.py: the one computation of them), as
    a snapshot every web view draws; computed again only when its trace changed."""
    from ..core.lanes import Lanes

    trace = Path(directory) / "events.jsonl"
    try:
        stat = trace.stat()
        mark = (stat.st_size, stat.st_mtime_ns)
    except OSError:
        mark = None
    with _LANES_LOCK:
        cached = _LANES.get(str(directory))
        if cached and cached[0] == mark:
            return cached[1]
    lanes = Lanes()
    for record in runs.read_records(Path(directory)):
        lanes.add(record)
    snapshot = lanes.snapshot()
    with _LANES_LOCK:
        _LANES[str(directory)] = (mark, snapshot)
    return snapshot


class Server(OwnPort, ThreadingHTTPServer):
    """The GUI's HTTP server over the runs directory `root`, with the session key
    `token` (a new random one by default)."""

    daemon_threads = True
    # The page at /, and the request handler (the app's server adds routes).
    page = "index.html"
    handler_class = None

    def __init__(self, address, root: Path, token: str | None = None, deploy: str | None = None):
        self.root = Path(root).resolve()
        self.token = token or secrets.token_urlsafe(18)
        # The deploy experiments are resolved against (default $HARNESS_DEPLOY).
        self.deploy = deploy
        # The conversations this server runs, by run, as sessions (host/sessions.py).
        self.conversations = Sessions()
        self._starting = threading.Lock()
        super().__init__(address, self.handler_class or Handler)

    def url(self) -> str:
        """The address to open, with the session key."""
        host, port = self.server_address[:2]
        host = "127.0.0.1" if host in ("0.0.0.0", "") else host
        return f"http://{host}:{port}/?token={self.token}"

    def info(self) -> dict:
        """What the page is told about the server, the statuses of a conversation and the words of an approval."""
        return {"version": __version__, "root": str(self.root), "live": True, "statuses": {"live": LIVE, "ended": ENDED},
                "words": approval.WORDS}

    def touch(self) -> None:
        """A client asked for something (the session host counts this as activity)."""

    def model_changed(self, run: str, changed: dict) -> None:
        """A conversation's model or reasoning effort changed (POST /api/conversations/model)."""

    def session_directory(self, request: dict, config, seed: int) -> tuple[Path, str | None]:
        """Where a conversation started here is written, and its run (None: its session's id)."""
        directory = self.root / "ui" / runs.new_name(config.task) / f"seed-{seed}"
        return directory, directory.relative_to(self.root).as_posix()

    def directory(self, run: str) -> Path:
        """The episode directory of `run`: a conversation's this server runs, else an episode
        under the root (ValueError when there is none)."""
        found = self.conversations.resolve(run)
        if found is not None:
            return Path(self.conversations[found].directory).resolve()
        return runs.episode_dir(self.root, run)

    def sub_agents(self, kind: str | None):
        """The sub-agents of a session started here whose workspace is of `kind` (None: a
        bench no workspace pool serves)."""
        from harness.runtime.task.delegation import Agents

        return Agents(sessions=self.conversations)

    def start_conversation(self, request: dict) -> str:
        """Start an interactive conversation (see the module docstring) and return its run."""
        from ..config.agent import REPO, package_lock
        from ..core import sha256
        from ..bench import bench_spec
        from ..extensions import require
        from harness.runtime.task.run import TaskRun
        from harness.runtime.safety.approval import confirmation_policy

        # An experiment's worker: the eval package's (installed first when it is not).
        load_experiment = require("load_experiment", "commands", "program")
        preflight = require("preflight", "commands", "program")
        experiment = request.get("experiment") or "dev"
        path = Path(experiment)
        if not path.suffix:
            path = (find(f"configs/experiments/{experiment}.toml")
                    or [REPO / "configs" / "experiments" / f"{experiment}.toml"])[0]
        if not path.is_file():
            raise ValueError(f"no experiment {experiment}")
        seed = int(request.get("seed", 0))
        sets = [str(item) for item in request.get("sets") or []]
        task = request.get("task") or None
        experiment = load_experiment(path, deploy=request.get("deploy") or self.deploy, sets=sets,
                                     tasks=[task] if task else None,
                                     seeds=[seed], model=request.get("model") or None)
        confirmation = confirmation_policy(request.get("confirmation") or None)
        workspace = self.workspace(request, experiment)
        try:
            config = experiment.task_config(task, [seed], endpoint=(workspace or {}).get("endpoint")
                                            or request.get("endpoint") or None)
            if config.lock is not None and config.lock.get("schema") == 3:
                packages = {**config.lock["packages"], **package_lock([bench_spec(experiment.bench).path])}
                config.lock = {**config.lock, "packages": packages}
                config.agent_id = sha256(config.lock)[:16]
            if (workspace or {}).get("python"):
                config.runtime = {**config.runtime, "python": workspace["python"]}
            if not config.environment.get("endpoint"):
                raise ValueError("no worker endpoint: give one, or set endpoint in the experiment")
            # As harness program: the agent's services must answer (on-demand ones get the broker).
            preflight(experiment, log=lambda message: print(message, flush=True))
            with self._starting:
                directory, run = self.session_directory(request, config, seed)
                kind = (workspace or {}).get("kind") or bench_kind(experiment.bench, experiment.worker)
                conversation = TaskRun(config, seed, directory, interactive=True, confirmation=confirmation,
                                            environment=(workspace or {}).get("environment"),
                                            instruction=(request.get("instruction") or "").strip() or None,
                                            agents=self.sub_agents(kind),
                                            )
                conversation.workspace_kind = kind
                session = self.conversations.add(run, conversation, title=request.get("title") or None,
                                                 frontend=request.get("frontend") or None)
            thread = conversation.start()
        except BaseException:
            if workspace is not None:
                workspace["release"]()
            raise
        if workspace is not None:
            # The workspace goes back to the pool when the episode ends.
            threading.Thread(target=lambda: (thread.join(), workspace["release"]()), name="workspace-release",
                             daemon=True).start()
        return run or session

    def workspace(self, request: dict, experiment):
        """The workspace a conversation asked for ({endpoint, python, release}), or None.
        This server keeps none: the app's server takes one from its pool."""
        if request.get("workspace"):
            raise ValueError("this server keeps no workspaces: give the worker's endpoint")
        return None


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    # Answers.

    def send_response(self, code, message=None):
        self.answered = True  # this request's answer has begun (see _failed)
        super().send_response(code, message)

    def _send(self, status, body: bytes, content_type: str, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _file(self, path: Path, content_type: str):
        """A file, or the one byte range a Range header asks for (206; 416 outside it), so a video can seek."""
        data = path.read_bytes()
        asked = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", self.headers.get("Range") or "")
        first, last, size = *(asked.groups() if asked else ("", "")), len(data)
        if not first and not last:
            return self._send(HTTPStatus.OK, data, content_type, [("Accept-Ranges", "bytes")])
        start, end = (int(first), min(int(last or size - 1), size - 1)) if first else (max(size - int(last), 0), size - 1)
        if start > end or start >= size:
            return self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"", content_type, [("Content-Range", f"bytes */{size}")])
        self._send(HTTPStatus.PARTIAL_CONTENT, data[start:end + 1], content_type,
                   [("Accept-Ranges", "bytes"), ("Content-Range", f"bytes {start}-{end}/{size}")])

    def _json(self, data, status=HTTPStatus.OK):
        self._send(status, json.dumps(data, ensure_ascii=False, allow_nan=False).encode(),
                   "application/json; charset=utf-8")

    def _error(self, status, message):
        self._json({"error": message}, status)

    # The session key.

    # Routes that take more than 1 MB (the app's skill upload).
    body_limits = {}

    def _body(self) -> dict:
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            raise ValueError("send JSON")
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 <= size <= self.body_limits.get(urlparse(self.path).path, 1024 * 1024):
            raise ValueError("body too large")
        data = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("send a JSON object")
        return data

    def _authorized(self, query) -> bool:
        self.server.touch()
        given = self.headers.get("X-Session-API-Key") or (query.get("token") or [None])[0]
        if given is None:
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
            given = cookie[COOKIE].value if COOKIE in cookie else None
        return given is not None and hmac.compare_digest(str(given), self.server.token)

    # Requests.

    def do_GET(self):
        self.answered = False
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path.startswith("/static/"):
            return self._static(url.path[len("/static/"):])
        found = pages()
        if not self._authorized(query):
            if url.path in found:
                return self._send(HTTPStatus.UNAUTHORIZED, b"Open the address harness app printed (it has the "
                                                           b"session key).\n", "text/plain; charset=utf-8")
            return self._error(HTTPStatus.UNAUTHORIZED, "missing or wrong session key")
        try:
            if url.path in found:
                folder, page = found[url.path]
                return self._page(query, page or self.server.page, folder)
            route = getattr(self, "get_" + url.path.removeprefix("/api/").replace("/", "_"), None)
            if not url.path.startswith("/api/") or route is None:
                handler = package_api(url.path)
                if handler is None:
                    return self._error(HTTPStatus.NOT_FOUND, "no such route")
                data = {key: values[0] for key, values in query.items() if key != "token"}
                return self._answer(handler(self.server, data))
            return route(query)
        except (ValueError, KeyError) as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return None
        except Exception as error:
            return self._failed(error)

    def _failed(self, error):
        """Any other error of a route (a bug, or a package's code that does not fit): logged,
        and answered with what it was, so the client says why instead of losing the connection."""
        traceback.print_exc()
        if getattr(self, "answered", False):
            return None  # part of an answer was sent: nothing more can be said on it
        return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")

    do_HEAD = do_GET

    def do_POST(self):
        self.answered = False
        url = urlparse(self.path)
        if not self._authorized({}):
            return self._error(HTTPStatus.UNAUTHORIZED, "missing or wrong session key")
        route = getattr(self, "post_" + url.path.removeprefix("/api/").replace("/", "_"), None)
        if not url.path.startswith("/api/") or route is None:
            handler = package_api(url.path)
            if handler is None:
                return self._error(HTTPStatus.NOT_FOUND, "no such route")
            route = lambda body: self._answer(handler(self.server, body))  # noqa: E731
        try:
            return route(self._body())
        except ChoiceRequired as error:
            return self._json({"error": str(error), "choice_required": error.choice}, HTTPStatus.CONFLICT)
        except (ValueError, KeyError, RuntimeError, OSError) as error:
            return self._error(HTTPStatus.BAD_REQUEST, f"{type(error).__name__}: {error}")
        except Exception as error:
            return self._failed(error)

    def _answer(self, answer):
        """A package handler's answer: JSON, or a tuple (body, content type, headers) as it is."""
        if isinstance(answer, tuple):
            body, content_type, headers = answer
            return self._send(HTTPStatus.OK, body, content_type, headers)
        return self._json(answer)

    def _conversation(self, body):
        run = self.server.conversations.resolve(body.get("run"))
        if run is None:
            raise ValueError("this server does not run that conversation")
        return self.server.conversations[run]

    def get_options(self, query):
        from ..config.agent import MODELS_ROOT

        experiments = sorted({path.stem for folder in find("configs/experiments") for path in folder.glob("*.toml")})
        models = sorted(path.stem for path in MODELS_ROOT.glob("*.toml"))
        self._json({"experiments": experiments, "models": models, "deploy": self.server.deploy,
                    "confirmation": ["never", "always"]})

    def post_conversations(self, body):
        run = self.server.start_conversation(body)
        found = self.server.conversations.session_of(run)
        self._json({"run": run, "session": found[0] if found else None})

    def post_conversations_message(self, body):
        self._conversation(body).send_message(str(body.get("text") or ""), files=body.get("files") or ())
        self.server.conversations.interact(self.server.conversations.resolve(body.get("run")))
        self._json({"ok": True})

    def _control(self, body, capability, method, *args):
        conversation = self._conversation(body)
        if not (getattr(conversation, "capabilities", None) or {}).get(capability):
            raise ValueError(f"the conversation does not support {capability}")
        return getattr(conversation, method)(*args)

    def post_conversations_steer(self, body):
        self._control(body, "steer", "steer", str(body.get("text") or ""), body.get("files") or ())
        self.server.conversations.interact(self.server.conversations.resolve(body.get("run")))
        self._json({"ok": True})

    def post_conversations_cancel(self, body):
        self._control(body, "cancel_turn", "cancel")
        self._json({"ok": True})

    def post_conversations_config(self, body):
        self._json(self._control(body, "configure", "set_config", body.get("id"), body.get("value")))

    def post_conversations_answer(self, body):
        self._control(body, "answer", "answer", body.get("request_id"), body.get("content"))
        self._json({"ok": True})

    def post_conversations_diff(self, body):
        self._json(self._control(body, "diff", "diff"))

    def post_conversations_merge(self, body):
        self._json(self._control(body, "merge", "merge"))

    def post_conversations_discard(self, body):
        self._json(self._control(body, "discard", "discard"))

    def post_conversations_terminal(self, body):
        self._control(body, "terminal_input", "terminal_input", body.get("text"))
        self._json({"ok": True})

    def post_conversations_terminal_resize(self, body):
        self._control(body, "terminal_resize", "terminal_resize", body.get("columns"), body.get("rows"))
        self._json({"ok": True})

    def post_conversations_pause(self, body):
        self._conversation(body).pause()
        self._json({"ok": True})

    def post_conversations_resume(self, body):
        self._conversation(body).resume()
        self.server.conversations.interact(self.server.conversations.resolve(body.get("run")))
        self._json({"ok": True})

    def post_conversations_confirm(self, body):
        if type(body.get("accept")) is not bool:
            raise ValueError("accept must be a boolean")
        self._conversation(body).confirm(body["accept"], str(body.get("reason") or ""),
                                         body.get("remember") or None,
                                         **({"request_id": body["request_id"]} if body.get("request_id") else {}))
        self._json({"ok": True})

    def post_conversations_model(self, body):
        run = self.server.conversations.resolve(body.get("run"))
        changed = self._conversation(body).set_model(body.get("model") or None, body.get("reasoning_effort"))
        self.server.model_changed(run, changed)
        self._json({"ok": True, **changed})

    def post_conversations_close(self, body):
        self._conversation(body).close()
        self._json({"ok": True})

    def _page(self, query, page="index.html", folder=None):
        folder = folder or static()
        body = (folder / page).read_bytes() if folder is not None and (folder / page).is_file() else MISSING
        headers = []
        if query.get("token"):
            headers.append(("Set-Cookie", f"{COOKIE}={self.server.token}; HttpOnly; SameSite=Strict; Path=/"))
        self._send(HTTPStatus.OK, body, STATIC_TYPES[".html"], headers)

    def _static(self, name):
        # /static/<package>/<file>: a package's; /static/<file>: static()'s (the app's).
        package, _, rest = name.partition("/")
        folders = statics()
        folder = folders[package] if rest and package in folders else static()
        name = rest if rest and package in folders else name
        path = (folder / name).resolve() if folder is not None else None
        if path is None or folder not in path.parents or not path.is_file() or path.suffix not in STATIC_TYPES:
            return self._error(HTTPStatus.NOT_FOUND, "no such file")
        self._file(path, STATIC_TYPES[path.suffix])

    def _run(self, query) -> Path:
        run = (query.get("run") or [None])[0]
        if not run:
            raise ValueError("give run=")
        return self.server.directory(run)

    # The sessions.

    def _session(self, identifier) -> dict:
        run = self.server.conversations.resolve(identifier)
        found = self.server.conversations.session_of(run) if run else None
        row = self.server.conversations.describe(found[0]) if found else None
        if row is None:
            raise ValueError(f"this server runs no session {identifier}")
        return {**row, "selected_agent": found[1]}

    def get_sessions(self, query):
        self._json({"sessions": self.server.conversations.sessions()})

    def get_sessions_show(self, query):
        row = self._session((query.get("id") or [""])[0])
        lines = int((query.get("lines") or ["40"])[0])
        for agent in row["agents"]:
            agent["lines"] = []
            if lines <= 0:
                continue
            directory = Path(agent["directory"]) if agent["directory"] else None
            records = runs.read_records(directory) if directory and (directory / "events.jsonl").is_file() else []
            printer = TextTranscript()
            text = [line for record in records for line in printer.lines(record)]
            agent["lines"] = text[-lines:]
        self._json(row)

    def post_sessions_stop(self, body):
        row = self._session(body.get("id"))
        chosen = [agent for agent in row["agents"] if body.get("agent") in (None, agent["id"])]
        if not chosen:
            raise ValueError(f"session {row['id']} has no agent {body.get('agent')}")
        # Sub-agents first, the main agent last.
        for agent in sorted(chosen, key=lambda item: -item["depth"]):
            if live(agent["status"]):
                self.server.conversations[agent["run"]].close()
        self._json({"ok": True, "stopped": [agent["id"] for agent in chosen]})

    def post_sessions_approve(self, body):
        row = self._session(body.get("id"))
        waiting = [agent["id"] for agent in row["agents"] if agent["status"] == "WAITING_FOR_CONFIRMATION"]
        agent = body.get("agent")
        if agent is None:
            if len(waiting) != 1:
                raise ValueError(f"session {row['id']}: " + ("nothing waits for an approval" if not waiting else
                                                              f"several agents wait ({', '.join(waiting)}): name one"))
            agent = waiting[0]
        elif agent not in waiting:
            raise ValueError(f"agent {agent} of session {row['id']} waits for no approval")
        run = next(item["run"] for item in row["agents"] if item["id"] == agent)
        request_id = body.get("request_id")
        accept = body.get("accept", True if request_id is None else None)
        if type(accept) is not bool:
            raise ValueError("accept must be a boolean")
        self.server.conversations[run].confirm(accept, str(body.get("reason") or ""), body.get("remember") or None,
                                               **({"request_id": request_id} if request_id is not None else {}))
        self._json({"ok": True, "agent": agent})

    def get_info(self, query):
        self._json(self.server.info())

    def get_libraries(self, query):
        from ..paths import home
        from harness.runtime.learning import learner

        self._json({"libraries": learner.libraries(), "root": str(home() / "libraries")})

    def get_library(self, query):
        from ..paths import home
        from harness.core import memory as memory_view
        from harness.runtime.learning.library import Library

        if query.get("run"):
            self._json({"columns": list(memory_view.COLUMNS), "entries": memory_view.rows(run=self._run(query))})
            return
        name = (query.get("name") or [""])[0]
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("a library's name under $HARNESS_HOME/libraries")
        directory = home() / "libraries" / name
        self._json({"name": name, "version": Library(directory).version(), "columns": list(memory_view.COLUMNS),
                    "entries": memory_view.rows(library=directory)})

    def get_runs(self, query):
        limit = int((query.get("limit") or ["500"])[0])
        episodes = runs.list_episodes(self.server.root, limit)
        for episode in episodes:
            conversation = self.server.conversations.get(episode["run"])
            episode["controllable"] = conversation is not None and live(conversation.status)
        self._json({"root": str(self.server.root), "episodes": episodes})

    def get_meta(self, query):
        directory = self._run(query)
        summary = runs.summary(directory)
        self._json({"manifest": runs._read_json(directory / "manifest.json"),
                    "summary": summary or None, "ending": runs.ending(summary), "usage": runs.usage(directory),
                    "files": sorted(path.name for path in directory.iterdir()
                                    if path.is_file() and path.suffix in runs.MEDIA_TYPES)})

    def get_events(self, query):
        after = int((query.get("after") or ["-1"])[0])
        names = {}  # filled from the records before `after` too
        self._json([{**record, "view": view} for record in runs.read_records(self._run(query))
                    for view in [items(record, names, True)] if record.get("seq", -1) > after])

    def get_lanes(self, query):
        self._json(lanes_of(self._run(query)))

    def get_file(self, query):
        directory = self._run(query)
        name = (query.get("name") or [""])[0]
        path = (directory / name).resolve()
        if path.parent != directory or not path.is_file() or path.suffix not in runs.MEDIA_TYPES:
            return self._error(HTTPStatus.NOT_FOUND, "no such file")
        self._file(path, runs.MEDIA_TYPES[path.suffix])

    def get_stream(self, query):
        directory = self._run(query)
        after = int(self.headers.get("Last-Event-ID") or (query.get("after") or ["-1"])[0])
        follow, names = runs.Follow(directory), {}  # from the start: the names of the spans before `after`
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        quiet = time.monotonic()
        ended_at = None
        while True:
            self.server.touch()
            records = [{**record, "view": view} for record in follow.next()
                       for view in [items(record, names, True)] if record.get("seq", -1) > after]
            for record in records:
                data = json.dumps(record, ensure_ascii=False, allow_nan=False)
                self.wfile.write(f"id: {record['seq']}\nevent: record\ndata: {data}\n\n".encode())
            if records:
                self.wfile.flush()
                quiet = time.monotonic()
            if follow.ended():
                # The summary is written just before the last records.
                ended_at = ended_at or time.monotonic()
                if time.monotonic() - ended_at > 1.0:
                    self.wfile.write(b"event: end\ndata: {}\n\n")
                    self.wfile.flush()
                    return
            elif time.monotonic() - quiet > KEEPALIVE_SECONDS:
                self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
                quiet = time.monotonic()
            time.sleep(POLL_SECONDS)


class FilesHandler(SimpleHTTPRequestHandler):
    """The files under a directory, read-only and without a key (serve_files), with ranges."""

    def send_head(self):  # a folder's index.html or listing, a redirect, a 404 as the standard handler's
        path = Path(self.translate_path(self.path))
        return self._file(path, self.guess_type(path)) if path.is_file() else super().send_head()

    def log_message(self, *args):
        pass

    _send, _file = Handler._send, Handler._file


class _FilesServer(OwnPort, ThreadingHTTPServer):
    pass


def serve_files(root: Path, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the files under `root` until interrupted (harness view); print where."""
    with _FilesServer((host, port), partial(FilesHandler, directory=str(root))) as server, suppress(KeyboardInterrupt):
        print(f"serving {Path(root).resolve()} on http://{host}:{server.server_address[1]}/", flush=True)
        server.serve_forever()
