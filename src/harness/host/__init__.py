"""The session host: one local process per user that runs the conversations of every
frontend, so a session outlives the window or terminal that started it.

The terminal chat (`harness`, its /sessions and /host), `harness run`, the app and the
Python API are its clients: they find it through DATA/host/host.json (its port, process and
session key; readable by the user only), start it when it does not run (`python -m
harness.host.server`, in a process of its own that no terminal owns) and drive its
sessions with its HTTP API (host/http.py) through RemoteConversation (host/client.py). The
host is the assistant's server (host/tasks.py) with the sessions as a tree
(host/sessions.py) and these routes:

  GET  /api/host                         its process, version, how long it has been idle
  POST /api/host/stop                    {force}: exit (force: end the open sessions first)
  GET  /api/sessions?all=1&limit=N       the open sessions; all: also those that ended

It listens on 127.0.0.1 only, with a new session key each time it starts, and exits
once no session is open and no client has asked for anything for HARNESS_HOST_IDLE
seconds (30 minutes). Every session it starts is appended to DATA/host/sessions.jsonl,
so the sessions that ended are listed after it exits.

    from harness.host import Host
    host = Host.connect()
    for session in host.sessions():
        print(session.id, session.status, [agent["id"] for agent in session.agents()])
    host.sessions()[0].overlay()        # its timeline on top of the screen
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import URLError
from urllib.parse import quote

from ..core.procs import file_lock, start_detached
from ..core.wait import wait_until
from ..paths import PACKAGE, data, python_path
from .client import RemoteConversation, RemoteError, _call, _fetch, _get

IDLE_ENV = "HARNESS_HOST_IDLE"
PORT_ENV = "HARNESS_HOST_PORT"
# Seconds without an open session or a client's request before the host exits.
IDLE_SECONDS = 30 * 60
# The port it takes when it is free (the app's), else any free one.
PORT = 8780
# Seconds a client waits for a host it started.
START_SECONDS = 60.0


def folder(base: Path | None = None) -> Path:
    """DATA/host: the host's address file, its index of sessions and the start lock."""
    return Path(base or data()) / "host"


def address_file(base: Path | None = None) -> Path:
    return folder(base) / "host.json"


def index_file(base: Path | None = None) -> Path:
    return folder(base) / "sessions.jsonl"


def idle_seconds() -> float:
    return float(os.environ.get(IDLE_ENV) or IDLE_SECONDS)


def identity() -> dict:
    """What tells this harness's code from another's: a host started by other code (another
    version, another checkout) is replaced when nothing runs in it."""
    from .. import __version__

    return {"version": __version__, "source": str(PACKAGE)}


def read_address(base: Path | None = None) -> dict | None:
    try:
        return json.loads(address_file(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Session:
    """A session as the host listed it: its row's fields as attributes (id, title,
    frontend, status, waiting, live, directory) and the calls on it."""

    def __init__(self, host: "Host", row: dict):
        self.host = host
        self.row = row
        for key in ("id", "title", "frontend", "status", "waiting", "live", "directory", "created", "kind",
                    "project", "metadata", "capabilities"):
            setattr(self, key, row.get(key))

    def agents(self) -> list[dict]:
        """Its agents in tree order: id, parent, depth, run, status, waiting, directory."""
        return list(self.row.get("agents") or [])

    def conversation(self, agent: str = "main") -> RemoteConversation:
        """One of its agents, to drive and follow (host/client.py)."""
        return self.host.conversation(self.id if agent == "main" else f"{self.id}/{agent}")

    def stop(self, agent: str | None = None) -> None:
        self.host.stop_session(self.id, agent)

    def diff(self) -> dict:
        """Read the project's current diff through the main agent."""
        return self.conversation().diff()

    def merge(self) -> dict:
        """Fast-forward the original branch to the closed managed worktree."""
        return self.conversation().merge()

    def handoff(self, agent: str, context: str, **options) -> RemoteConversation:
        """Start the next agent with the context selected by the caller."""
        return self.conversation().handoff(agent, context, **options)

    def overlay(self, agent: str | None = None, **options):
        """Its timeline (or one agent's) in a window on top of the screen (the app package's overlay;
        options: corner, width, height, seconds, alpha, click_through, hide, hotkey);
        returns the window's process."""
        return self.host.overlay(self.id if agent in (None, "main") else f"{self.id}/{agent}", **options)

    def approve(self, accept: bool = True, reason: str = "", agent: str | None = None,
                remember: str | None = None, *, request_id: str | None = None) -> str:
        return self.host.approve(self.id, accept, reason, agent, remember, request_id=request_id)

    def __repr__(self):
        return f"Session({self.id!r}, {self.status!r}, {self.title!r})"


class Host:
    """A client of the session host at `url` with its session key `token`."""

    def __init__(self, url: str, token: str, timeout: float = 60.0, pid: int | None = None):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.pid = pid
        # Its answer to GET /api/host when it was found.
        self.state = None

    @classmethod
    def connect(cls, start: bool = True, *, port: int | None = None, log=None) -> "Host | None":
        """The host of this user, started first when none runs (with `start`; else None).
        A host of other code is replaced only when idle. New work cannot silently run
        under older code. start=False observes an existing host without replacing it."""
        log = log or (lambda message: None)
        host = _reachable(read_address())
        if not start:
            return host
        if host is not None:
            host = _same_code(host, log)
        if host is not None or not start:
            return host
        with _start_lock():
            host = _reachable(read_address())
            if host is not None:
                host = _same_code(host, log)
                if host is not None:
                    return host
            return _spawn(port, log)

    def page(self) -> str:
        """The app's address, with the session key."""
        return f"{self.url}/?token={self.token}"

    def get(self, path: str) -> dict:
        """GET one of the host's routes (host/http.py, host/tasks.py): its JSON answer."""
        return _get(self.url, self.token, path, self.timeout)

    def post(self, path: str, body: dict, timeout: float | None = None) -> dict:
        """POST `body` to one of the host's routes: its JSON answer."""
        return _call(self.url, self.token, path, body, timeout or self.timeout)

    def fetch(self, path: str) -> bytes:
        """GET one of the host's routes that answers with bytes (a session's screen, a file)."""
        return _fetch(self.url, self.token, path, self.timeout)


    def info(self) -> dict:
        """Its process, version, idle time and whether a session is open."""
        return self.get("/api/host")

    def sessions(self, all: bool = False, limit: int = 50) -> list[Session]:
        """The open sessions, newest first; with `all`, those that ended too (at most `limit`)."""
        answer = self.get(f"/api/sessions?all={int(bool(all))}&limit={int(limit)}")
        return [Session(self, row) for row in answer["sessions"]]

    def session(self, identifier: str, lines: int = 40) -> Session:
        """One session by its id (or the unique start of it), with the last `lines` lines
        of each agent's trace (row["agents"][i]["lines"])."""
        return Session(self, self.get(f"/api/sessions/show?id={quote(str(identifier))}&lines={int(lines)}"))

    def start(self, **request) -> RemoteConversation:
        """Start a session: an interactive conversation of an experiment (experiment, task,
        seed, model, endpoint, instruction, confirmation, sets, deploy; directory: where it
        is written; title; frontend)."""
        request.setdefault("frontend", "python")
        return RemoteConversation.start(self.url, self.token, **request)

    def task(self, text: str, workspace: str | None = "auto", confirmation: str | None = None,
                         runtime: dict | None = None, timeout: float = 600, files=(), *, learn=None,
                         agent: str | None = None, folder=None, isolation: str | None = None,
                         mcp_tools=(), model_entry=None, reasoning_effort=None, library=None, budget=None) -> RemoteConversation:
        """Start a conversation of the app's agent with the first message `text`. `workspace`:
        where it works: "none" (no environment: the conversation, the model and the connected
        tools only), "project" (with `folder`), "browser", "desktop", "apps", "display"; with
        "auto" (and no `folder`) the setting session.environment decides, and its default
        `ask` raises ChoiceRequired here, where nobody can be asked: name the workspace.
        `confirmation`: else approvals.ask;
        `files`: paths the message attaches; `learn`: True for the default minutes, or a number)."""
        if learn is not None:
            runtime = {**(runtime or {}), "learn": learn}
        given = {"confirmation": confirmation, "workspace": workspace, "runtime": runtime,
                 "files": [str(path) for path in files], "agent": agent, "folder": str(folder) if folder else None,
                 "library": library, "budget": budget, "isolation": isolation, "frontend": "python" if agent else None, "mcp_tools": list(mcp_tools)}
        answer = self.post("/api/tasks", {"text": text, "model_entry": model_entry,
                           "reasoning_effort": reasoning_effort, **{key: value for key, value in given.items() if value}},
                           timeout=timeout)
        return RemoteConversation(self.url, self.token, answer["run"])

    def learning(self, run: str) -> dict:
        """Where a conversation that learns its environment (task(..., runtime=
        {"learn": minutes})) stands: live time, tested entries, open situations
        (runtime/learning/active.py progress()); {"active": False} for any other."""
        from urllib.parse import quote

        return self.get(f"/api/app/learning?run={quote(run)}")

    def agents(self) -> list[dict]:
        """The external agent adapters this host can discover or start."""
        return self.get("/api/app/agents")["agents"]

    def import_session(self, file, provider: str, *, follow: bool = False) -> RemoteConversation:
        """Observe one user-selected native JSONL transcript."""
        result = self.post("/api/sessions/import", {"file": str(file), "provider": provider, "follow": follow})
        return RemoteConversation(self.url, self.token, result["run"], session=result["id"])

    def discover_sessions(self, agent: str, folder=None, cursor: str | None = None) -> dict:
        """List sessions the selected ACP agent exposes for the project directory."""
        return self.post("/api/sessions/discover", {"agent": agent, "folder": str(folder) if folder else None,
                                                    "cursor": cursor})

    def observe_cloud(self, agent: str, external_id: str) -> RemoteConversation:
        """Follow a cloud session created outside the host in read-only mode."""
        return self.observe_external(agent, external_id)

    def observe_external(self, agent: str, external_id: str, *, folder=None) -> RemoteConversation:
        """Index a discovered ACP session or follow an existing cloud session in read-only mode."""
        result = self.post("/api/sessions/observe", {"agent": agent, "external_id": external_id, "frontend": "python",
                                                      "folder": str(folder) if folder else None})
        return RemoteConversation(self.url, self.token, result["run"])

    def reconnect_session(self, identifier: str, *, released: bool, agent: str | None = None) -> RemoteConversation:
        """Recover the original native ID after the user has released its old controller."""
        result = self.post("/api/conversations/reconnect", {"run": identifier, "released": released, "agent": agent})
        return RemoteConversation(self.url, self.token, result["run"], session=result["id"])

    def conversation(self, identifier: str) -> RemoteConversation:
        """A session's main agent ("<session>") or one of its agents ("<session>/<agent>")."""
        conversation = RemoteConversation(self.url, self.token, str(identifier), self.timeout)
        conversation.describe()
        return conversation

    def stop_session(self, identifier: str, agent: str | None = None) -> list[str]:
        """End a session's agents (or one of them); returns the agents told to end."""
        return self.post("/api/sessions/stop", {"id": identifier, "agent": agent})["stopped"]

    def approve(self, identifier: str, accept: bool = True, reason: str = "", agent: str | None = None,
                remember: str | None = None, *, request_id: str | None = None) -> str:
        """Approve (or reject) what an agent of the session waits for; returns that agent. For
        physical input `remember` keeps the answer: once, app, session or always."""
        return self.post("/api/sessions/approve", {"id": identifier, "agent": agent, "accept": bool(accept),
                                                    "reason": reason, "remember": remember,
                                                    **({"request_id": request_id} if request_id else {})})["agent"]

    def overlay(self, session: str | None = None, **options):
        """The timeline overlay following `session` (None: the newest session that runs, and
        the next one that starts); returns the window's process (the app package's overlay,
        installed first when no package gives it)."""
        from ..extensions import overlay

        window = overlay()
        return window.for_session(session, window.Options(**options), host=self)

    def stop(self, force: bool = False) -> None:
        """Make the host exit; with `force` it ends the open sessions first."""
        self.post("/api/host/stop", {"force": bool(force)})


def connect(start: bool = True, **options) -> Host | None:
    return Host.connect(start, **options)


def _reachable(address: dict | None) -> Host | None:
    """The host at `address` when it answers (which counts as a client's activity, so it
    does not exit right after); its answer is kept as `state`."""
    if not address or not address.get("url") or not address.get("token"):
        return None
    host = Host(address["url"], address["token"], pid=address.get("pid"))
    try:
        host.timeout = 5.0
        host.state = host.info()
    except (RemoteError, URLError, OSError, ValueError):
        return None
    host.timeout = 60.0
    return host


def _same_code(host: Host, log) -> Host | None:
    info = host.state
    mine = identity()
    if all(info.get(key) == value for key, value in mine.items()):
        return host
    if info.get("running"):
        raise RuntimeError(f"The session host runs different code ({info.get('version')} from {info.get('source')}) "
                           "and still has open sessions. New tasks were not submitted. "
                           "Use harness sessions ls and harness sessions stop SESSION to end the old sessions, "
                           "then retry; the idle host will be replaced automatically.")
    log(f"harness: replacing the session host of other code ({info.get('version')} from {info.get('source')})")
    try:
        host.stop()
    except (RemoteError, URLError, OSError):
        pass
    if not wait_until(lambda: _reachable(read_address()) is None, 15, 0.2):
        raise RuntimeError("The previous session host did not stop; no replacement was started. Retry after it exits.")
    return None


@contextmanager
def _start_lock(seconds: float = 90.0):
    """One client at a time starts the host (a file lock, which a client that died no longer
    holds); TimeoutError after `seconds`."""
    path = folder() / "start.lock"
    lock = file_lock(path, timeout=seconds)
    try:
        lock.__enter__()
    except TimeoutError:
        raise TimeoutError(f"another client is starting the session host ({path})") from None
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _spawn(port: int | None, log) -> Host:
    """Start the host in a process of its own: no terminal owns it (a new session on
    POSIX; a new process group with a console of its own and no window on Windows, so
    the processes it starts open no windows either) and it logs to DATA/logs/host.log."""
    logs = data() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "harness.host.server"]
    if port is not None:
        command += ["--port", str(port)]
    env = {**os.environ, "PYTHONPATH": python_path(), "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    log(f"harness: starting the session host (log: {logs / 'host.log'})")
    began = time.time()
    process = start_detached(command, log=logs / "host.log", env=env)

    def answers():
        address = read_address()
        # Its address, written after it began (a venv's python.exe on Windows is a launcher:
        # the host's process id is not the one started here).
        if address and (address.get("started") or 0) >= began - 1 and (host := _reachable(address)):
            return host
        if process.poll() is not None:
            raise RuntimeError(f"the session host exited ({process.returncode}); see {logs / 'host.log'}")

    if host := wait_until(answers, START_SECONDS):
        return host
    raise TimeoutError(f"the session host did not answer within {START_SECONDS:.0f} s; see {logs / 'host.log'}")


def resolve_run(name, sessions: bool = True) -> Path:
    """The episode directory `name` names: an episode's directory, a conversation of the app
    (its folder or name), or with `sessions` SESSION or SESSION/AGENT of this computer's host."""
    from ..paths import data

    name = str(name or "").strip()
    if not name:
        raise ValueError("give a run: an episode directory, a conversation or a session")
    for path in (Path(name), data() / "conversations" / name):
        if (path / "events.jsonl").is_file():
            return path
    if not sessions:
        raise ValueError(f"no run {name}: give an episode directory or a conversation")
    host, (session, _, agent) = Host.connect(start=False), name.partition("/")
    try:
        agents = host.session(session, lines=0).row.get("agents") or []
    except Exception as error:  # no host runs (None), or it has no such session
        raise ValueError(f"no run {name}: no episode, conversation or session by that name "
                         f"({error if host else 'no session host runs'})") from None
    for each in agents:
        if (each["id"] == agent if agent else not each["depth"]) and each.get("directory"):
            return Path(each["directory"])
    raise ValueError(f"Session {session} has no agent {agent or 'main'} with a trace")
