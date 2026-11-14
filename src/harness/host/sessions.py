"""The sessions a server runs, as a tree: session -> agent -> sub-agent.

A session is what a user started from a frontend (the app, the terminal chat, harness run, the Python
API): its main agent is a conversation (runtime/conversation.py), and an agent may start
agents of its own (sub-agents, runtime/task/delegation.py: each a conversation of its own with its
own trace, under its parent's directory, its spending charged up the tree). Every
agent has a run, the key it is driven by (POST /api/conversations/... {run}); the main
agent's run is also its session's id, and a sub-agent's is "<session>/<agent>".

Sessions is the dict {run: conversation} a GUI server has always kept (host/http.py),
so code that registers a conversation by its run still works: a conversation registered
that way becomes a session of its own. With an `index` (the session host's), every
session is also appended to a JSON-lines file, so the sessions that ended are still
listed after the host exits (history()).
"""

import json
from pathlib import Path
import secrets
import sys
import threading
import time

from ..core import episodes, format as formats
from ..runtime.status import ENDED as ENDED, LIVE as LIVE, live as live


MAIN = "main"


def session_metadata(conversation) -> dict:
    """Public identity of a session. A provider only returns fields safe to expose."""
    return {"kind": "harness", "project": None, "source": "harness",
            **getattr(conversation, "session_metadata", {})}


def word(status) -> str:  # a status in every frontend's words: "waiting for confirmation"
    return str(status or "").lower().replace("_", " ")


def title(text, limit: int = 80) -> str:
    """`text`'s words on one line, at most `limit` characters."""
    return formats.clip(" ".join(str(text or "").split()), limit)


def waiting(status, note=None) -> str | None:
    """What an agent in `status` waits for: an approval, the user's message, a pause to
    end, the computer to be prepared or the input lock (`note`); None while it works or
    once it ended."""
    if note and not str(note).startswith("error"):
        return str(note)
    return {"WAITING_FOR_CONFIRMATION": "approval", "WAITING_FOR_INPUT": "agent question",
            "IDLE": "message", "PAUSED": "resume"}.get(status)


def ended_status(directory: Path) -> str:
    """The status of an agent nothing runs any more, from how its episode ended (none: interrupted)."""
    summary = episodes.summary(directory)
    if summary.get("open"):
        return "INTERRUPTED"
    return {"error": "ERROR", "interrupted": "INTERRUPTED", None: "INTERRUPTED"}.get(episodes.ending(summary), "FINISHED")


def _usage(conversation) -> dict:
    """What an agent spent itself (its sub-agents' spending is theirs): model calls and dollars."""
    return episodes.usage(getattr(conversation, "summary", None) or {})


def spent(usage: dict | None) -> str:
    """Usage as a cell: "12 calls". No dollars: only OpenRouter reports a cost, so a
    total would read $0 on every other provider (usage keeps cost_usd as recorded)."""
    usage = usage or {}
    calls = usage.get("model_calls") or 0
    return f"{calls} call{'s' if calls != 1 else ''}" if usage else ""


def _title(conversation) -> str:
    return title(conversation.instruction or getattr(conversation.config, "task", None) or "")


class Sessions(dict):
    """{run: conversation} with the session tree over them (see the module docstring).
    `default_frontend` names what started a conversation registered by its run alone;
    `notes(run)` may say what an agent waits for before it starts (the app: preparing
    this computer)."""

    def __init__(self, index: Path | None = None, default_frontend: str = "ui"):
        super().__init__()
        self.index = Path(index) if index else None
        self.default_frontend = default_frontend
        self.notes = lambda run: None
        self.registered = lambda run, conversation: None
        # Session id -> {id, title, frontend, created, agents: {agent: {run, parent, created, title}}}.
        self._sessions = {}
        # Run -> (session id, agent id).
        self._runs = {}
        self._lock = threading.RLock()
        # Last session whose user selection was persisted; repeated messages need no new row.
        self._last_interacted = None

    # The dict, as servers use it.

    def __setitem__(self, run, conversation):
        with self._lock:
            super().__setitem__(run, conversation)
            if run not in self._runs:
                self._add(run, conversation, title=None, frontend=None, session=self._new_id(), new=True)

    def pop(self, run, *default):
        with self._lock:
            found = self._runs.pop(run, None)
            if found is not None:
                session, agent = found
                entry = self._sessions.get(session)
                if entry is not None:
                    entry["agents"].pop(agent, None)
                    if agent == MAIN:
                        for other in entry["agents"].values():
                            self._runs.pop(other["run"], None)
                            super().pop(other["run"], None)
                        self._sessions.pop(session, None)
            return super().pop(run, *default)

    # Registering.

    def _new_id(self) -> str:
        while True:
            identifier = secrets.token_hex(3)
            if identifier not in self._sessions and identifier not in self:
                return identifier

    def _add(self, run, conversation, *, title, frontend, session, new=False, agent=None, parent=None, created=None):
        now = created if created is not None else time.time()
        if new:
            entry = {"id": session, "title": title or _title(conversation),
                     "frontend": frontend or self.default_frontend, "created": now,
                     "last_interaction": time.time(), "agents": {}}
            self._sessions[session] = entry
            agent, parent = MAIN, None
        else:
            entry = self._sessions[session]
        entry["agents"][agent] = {"run": run, "parent": parent, "created": now,
                                  "title": title or _title(conversation)}
        self._runs[run] = (session, agent)
        try:
            # Whose steps its worker sends (the physical-input policy, the input lock).
            conversation.identity = {"session": session, "agent": agent}
        except AttributeError:
            pass
        self.save_metadata(run)
        if new:
            self._last_interacted = session
        self.registered(run, conversation)
        return session

    def add(self, run, conversation, *, title=None, frontend=None) -> str:
        """Register `conversation` under `run` (None: the new session's id) as a new
        session's main agent; returns the session's id."""
        with self._lock:
            session = self._new_id()
            run = run or session
            dict.__setitem__(self, run, conversation)
            return self._add(run, conversation, title=title, frontend=frontend, session=session, new=True)

    def reconnect(self, row, conversation):
        with self._lock:
            run, session = row["run"], row["id"]
            active = self.get(run)
            if active is not None and live(active.status):
                raise ValueError("the session already has a live controller")
            if active is not None:
                self.pop(run)
            dict.__setitem__(self, run, conversation)
            self._add(run, conversation, title=row["title"], frontend=row["frontend"], session=session,
                      new=True, created=row.get("created"))

    def add_agent(self, session: str, conversation, *, agent: str | None = None, parent: str = MAIN,
                  title: str | None = None) -> str:
        """Register `conversation` as an agent of `session` started by its agent `parent`;
        returns its run ("<session>/<agent>")."""
        with self._lock:
            entry = self._sessions.get(session)
            if entry is None:
                raise ValueError(f"no session {session}")
            if parent not in entry["agents"]:
                raise ValueError(f"session {session} has no agent {parent}")
            if agent is None:
                agent = f"a{len(entry['agents'])}"
                while agent in entry["agents"]:
                    agent += "x"
            if agent in entry["agents"] or "/" in agent:
                raise ValueError(f"agent {agent} is taken (or has a /)")
            run = f"{session}/{agent}"
            dict.__setitem__(self, run, conversation)
            self._add(run, conversation, title=title, frontend=None, session=session, agent=agent, parent=parent)
            return run

    def rename(self, run, text) -> str:
        """The title `text` for the agent of `run` (its main agent's: the session's), as kept."""
        name = title(text, 120)
        if not name:
            raise ValueError("give it a title")
        with self._lock:
            if run in self._runs:  # else the caller's to keep
                session, agent = self._runs[run]
                entry = self._sessions[session]
                item = entry["agents"][agent]
                item["title"] = name
                if agent == MAIN:
                    entry["title"] = name
                self.save_metadata(run)
        return name

    def _write(self, line: dict) -> None:
        if self.index is None:
            return
        self.index.parent.mkdir(parents=True, exist_ok=True)
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    # Finding.

    def resolve(self, name) -> str | None:
        """The run `name` stands for: a run, a session id (its main agent), "<session>/<agent>",
        or the unique start of a session id (at least 3 characters); None when none."""
        name = str(name or "").strip()
        with self._lock:
            if name in self:
                return name
            session, _, agent = name.partition("/")
            if session not in self._sessions and len(session) >= 3:
                found = [identifier for identifier in self._sessions if identifier.startswith(session)]
                session = found[0] if len(found) == 1 else session
            entry = self._sessions.get(session)
            if entry is None:
                return None
            item = entry["agents"].get(agent or MAIN)
            return item["run"] if item else None

    def session_of(self, run) -> tuple[str, str] | None:
        """(session id, agent id) of a run."""
        return self._runs.get(run)

    def interact(self, run: str) -> None:
        """Keep a successful user message or resume, independently of background events."""
        with self._lock:
            found = self._runs.get(run)
            if found is None:
                return
            session, _ = found
            self._sessions[session]["last_interaction"] = time.time()
            if self._last_interacted == session:
                return
            try:
                self.save_metadata(run)
            except OSError as error:
                # The message/resume already succeeded. Leave the selection dirty for retry.
                try:
                    print(f"harness: could not save session activity: {error}", file=sys.stderr, flush=True)
                except OSError:
                    pass
            else:
                self._last_interacted = session

    def save_metadata(self, run: str) -> None:
        """Persist the public identity once a provider has returned its external ID."""
        with self._lock:
            session, agent = self._runs[run]
            entry = self._sessions[session]
            item = entry["agents"][agent]
            conversation = self[run]
            self._write({"id": session, "agent": agent, "parent": item["parent"], "run": run,
                         "directory": str(Path(conversation.directory).resolve()), "title": item["title"],
                         "frontend": entry["frontend"], "created": item["created"],
                         "last_interaction": entry.get("last_interaction") or entry["created"],
                         "metadata": session_metadata(conversation)})

    # Describing.

    def _agent(self, item: dict, agent: str) -> dict:
        # Its model and reasoning effort are those of its next call (Conversation.set_model).
        conversation = dict.get(self, item["run"])
        status = conversation.status if conversation is not None else None
        approval_id = getattr(conversation, "approval_id", None)
        note = getattr(conversation, "waiting_for", None) or self.notes(item["run"])
        if approval_id != getattr(conversation, "approval_id", None):
            # Do not associate a changed request with the previous request's description.
            approval_id = None
        if not note and status == "RUNNING":
            session = self._runs.get(item["run"], (None,))[0]
            note = _waiting({"session": session, "agent": agent}) if session else None
        main = getattr(getattr(conversation, "config", None), "main", None)
        main = main if isinstance(main, dict) else {}
        return {"id": agent, "parent": item["parent"], "run": item["run"], "title": item["title"],
                "status": status, "waiting": waiting(status, note) if live(status) else None,
                "approval_id": approval_id,
                "metadata": session_metadata(conversation),
                "capabilities": getattr(conversation, "capabilities", None),
                "model": main.get("model"), "reasoning_effort": main.get("reasoning_effort"),
                "workspace": getattr(conversation, "workspace_kind", None),
                "directory": str(Path(conversation.directory).resolve()) if conversation is not None else None,
                "created": item["created"],
                "usage": _usage(conversation) if conversation is not None else None}

    def describe(self, session: str) -> dict | None:
        """One session as it is listed: its id, title, the frontend that started it, its
        status (its main agent's, or WAITING_FOR_CONFIRMATION while any agent waits for an
        approval), what it waits for, what all its agents spent (usage), and its agents in
        tree order (each with its depth and what it spent itself)."""
        with self._lock:
            entry = self._sessions.get(session)
            if entry is None:
                return None
            agents = {name: self._agent(item, name) for name, item in entry["agents"].items()}
        return _session_row(entry, agents)

    def sessions(self) -> list[dict]:
        """Every session registered, newest first."""
        with self._lock:
            identifiers = sorted(self._sessions, key=lambda key: self._sessions[key]["created"], reverse=True)
        return [row for row in map(self.describe, identifiers) if row is not None]

    def running(self) -> bool:
        """Whether any agent still runs (or waits for someone)."""
        with self._lock:
            conversations = list(self.values())
        return any(live(conversation.status) for conversation in conversations)


def _tree(agents: dict) -> list[dict]:
    """The agents in tree order (each after its parent), each with its depth."""
    children = {}
    for name, agent in agents.items():
        children.setdefault(agent["parent"], []).append(name)
    ordered = []

    def visit(name, depth):
        ordered.append({**agents[name], "depth": depth})
        for child in sorted(children.get(name, []), key=lambda key: agents[key]["created"]):
            visit(child, depth + 1)

    for root in sorted(children.get(None, []), key=lambda key: agents[key]["created"]):
        visit(root, 0)
    # Agents whose parent is not known (left out of a history line) come last.
    seen = {agent["id"] for agent in ordered}
    ordered += [{**agent, "depth": 1} for name, agent in agents.items() if name not in seen]
    return ordered


def _session_row(entry: dict, agents: dict) -> dict:
    main = agents.get(MAIN) or {}
    tree = _tree(agents)
    approvals = [agent["id"] for agent in tree if agent["status"] == "WAITING_FOR_CONFIRMATION"]
    status = "WAITING_FOR_CONFIRMATION" if approvals else main.get("status")
    usage = [agent["usage"] for agent in tree if agent.get("usage")]
    total = ({"model_calls": sum(item["model_calls"] for item in usage),
              "cost_usd": round(sum(item["cost_usd"] for item in usage), 6)} if usage else None)
    return {"id": entry["id"], "title": entry["title"], "frontend": entry["frontend"], "created": entry["created"],
            "run": main.get("run", entry["id"]), "directory": main.get("directory"), "status": status,
            "last_interaction": entry.get("last_interaction") or entry["created"],
            "live": any(live(agent["status"]) for agent in tree),
            "waiting": ("approval" if approvals else main.get("waiting")), "approvals": approvals, "usage": total,
            "kind": main.get("metadata", {}).get("kind", "harness"),
            "project": main.get("metadata", {}).get("project"),
            "metadata": main.get("metadata", {}), "capabilities": main.get("capabilities"),
            "agents": tree}


# The columns of a list of sessions (the terminal chat's /sessions).
COLUMNS = ("session", "agent", "kind", "project", "status", "waiting", "spent", "from", "started", "title")


def table_rows(sessions: list[dict]) -> list[dict]:
    """Sessions as listed (rows) as the lines of a table: each agent under its session,
    indented by its depth, with the cells of COLUMNS and, beside them, its `run`,
    `session`, `agent_id`, `directory` and `state` (the status as it is)."""
    lines = []
    for session in sessions:
        for agent in session.get("agents") or []:
            main = agent["depth"] == 0
            lines.append({"session": session["id"] if main else "", "agent": "  " * agent["depth"] + agent["id"],
                          "kind": session.get("kind", "harness") if main else "",
                          "project": session.get("project") if main else "",
                          "status": word(agent["status"]),
                          "waiting": agent.get("waiting") or "", "spent": spent(agent.get("usage")),
                          "from": session["frontend"] if main else "",
                          "started": formats.timestamp(agent.get("created") or 0),
                          "title": session["title"] if main else agent.get("title") or "",
                          "run": agent["run"], "session_id": session["id"], "agent_id": agent["id"],
                          "directory": agent.get("directory"), "state": agent["status"]})
    return lines


def history(index: Path, skip=()) -> list[dict]:
    """The sessions an index lists (newest first), each described from its files: what a
    host that ended left behind. Sessions in `skip` (ids) and those whose directory is gone
    are left out."""
    entries = {}
    try:
        lines = Path(index).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("id") in skip or not item.get("directory"):
            continue
        entry = entries.setdefault(item["id"], {"id": item["id"], "title": item.get("title") or "",
                                                "frontend": item.get("frontend") or "", "created": item.get("created"),
                                                "agents": {}})
        if item.get("last_interaction") is not None:
            entry["last_interaction"] = max(entry.get("last_interaction") or 0, item["last_interaction"])
        if item.get("agent", MAIN) == MAIN:
            entry.update(title=item.get("title") or "", frontend=item.get("frontend") or "", created=item.get("created"))
        entry["agents"][item.get("agent", MAIN)] = item
    rows = []
    for entry in entries.values():
        agents = {}
        for name, item in entry["agents"].items():
            directory = Path(item["directory"])
            if not directory.is_dir():
                continue
            agents[name] = {"id": name, "parent": item.get("parent"), "run": item.get("run"),
                            "title": item.get("title"), "status": ended_status(directory), "waiting": None,
                            "directory": str(directory), "created": item.get("created") or 0,
                            "metadata": item.get("metadata") or {},
                            "usage": episodes.usage(directory)}
        if MAIN in agents:
            rows.append(_session_row(entry, agents))
    rows.sort(key=lambda row: row["created"] or 0, reverse=True)
    return rows


def _waiting(owner: dict) -> str | None:
    """What an agent of a session waits for, as a package says (its input lock;
    harness/extensions.py)."""
    from ..extensions import first

    waiting = first("waiting")
    return waiting(owner) if waiting is not None else None
