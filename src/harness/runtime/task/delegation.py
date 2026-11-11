"""Sub-agents: an agent hands parts of its task to agents of its own.

An agent's program calls delegate(task, workspace, budget, model) (skills/agents); the
call reaches the conversation that runs the program as a note (runtime/execution/control.py), and
the session's Agents (this module) starts a sub-agent: a conversation of its own
(runtime/conversation.py) with the task as its instruction, written under its parent's
directory (agents/<id>/: the trace is a tree of directories), registered in the session's
tree (host/sessions.py) and run in a workspace the session's Place gives it:

  new      a workspace of its own, of the parent's kind (or "browser", "desktop", "apps",
           "display": a new one of that kind)
  share    the windows the parent holds now are handed over (the session's window
           ownership, `windows`: the computer package's WindowOwners.transfer): the
           sub-agent owns them while it runs, the parent cannot use them meanwhile, and
           they come back to the parent when the sub-agent ends.
           It still runs in a worker of its own (a worker serves one episode); its
           instruction names the windows it was handed.

A sub-agent may also be another harness's agent (delegate(..., agent="claude-code")): a kind
a package declares ([provides] agents of its package.toml, installed on first use as
packages.auto_install says). Its class runs that agent on the task in its own directory,
writes what it does to its own trace (so the timeline shows it as the sub-agent's lane) and
charges what it spends with `charge(calls, cost)`; it needs no workspace, and answers what
Agents asks of a sub-agent (status, summary, result, question, directory, trace,
agents_usage, start, send_message, close, charge_up).

Budgets are charged up the tree: a sub-agent's budget (model calls, cost, seconds) is
at most what its parent has left, and every call and dollar it spends counts against
its parent's budget, and its parent's, as it is spent. An agent at the session's
nesting depth (`max_depth`, default 1: the main agent's sub-agents start none) cannot
delegate.

A sub-agent works on its task alone: its <finish> (or a used-up budget) ends it, and its
report (status, result, usage, files) goes back to its parent, which wait_agents() gives
it and whose trace keeps it (agent_report). A plain reply is a question to its parent:
it waits, and wait_agents() returns, until the parent answers with send_agent(). The
user may talk to any agent of the session from any frontend; what an agent asks the user
(an approval, physical input) is listed with its session, where every frontend answers it.
"""

from copy import copy
from pathlib import Path
import threading
import time

from harness.runtime.status import live



# The main agent's sub-agents start none of their own.
DEFAULT_DEPTH = 1
# What a sub-agent's workspace is (or a workspace kind: a new one of that kind).
WORKSPACES = ("new", "share")
# A budget's keys, and the names they may be given by.
BUDGET_KEYS = {"calls": "calls", "model_calls": "calls", "cost": "cost", "cost_usd": "cost",
               "seconds": "seconds", "time": "seconds"}
# Files of an agent's directory that are the harness's, not results.
OWN_FILES = {"events.jsonl", "manifest.json", "summary.json", "kernel.log", "meta.json"}

# Added to a sub-agent's system prompt in place of the interactive one.
SUB_AGENT_PROMPT = (
    "\n\nYou are a sub-agent: another agent (the one that started you) gave you this task, and it waits for "
    "your result. When the task is done, <finish> with what it needs to know (what you found or did, and where "
    "any files are); that ends your work and your result goes back to it. To ask it something, reply in plain "
    "text without any block: you wait for its answer, which reaches you as \"Message from the agent that "
    "started you: ...\". The user may also write to you (\"Message from the user: ...\")."
)
NO_DEEPER = " You cannot start sub-agents of your own."


class Place:
    """Where a session's sub-agents run: what the server that runs the session gives them.
    This one has no workspaces to give (a conversation run in a process of its own, or by
    a server without a workspace pool); the app and the session host give workspaces from
    their pool (app.py)."""

    # The workspace kinds it can start.
    kinds = ()
    why_not = ("this conversation has no workspace pool to start sub-agents in: run it from the app or the "
               "session host")

    def config(self, parent, kind: str, model: str | None):
        """A sub-agent's configuration in a workspace of `kind` with `model`: None for its
        parent's (copied)."""
        return None

    def begin(self, child, kind: str, cancelled) -> callable:
        """Give `child` a workspace of `kind` (its endpoint in child.config.environment; may
        wait for one) and return what gives it back."""
        raise ValueError(self.why_not)


class Child:
    """A sub-agent as its session's Agents keeps it."""

    def __init__(self, agent: str, conversation, parent, *, task, workspace, kind, budget, windows):
        self.id = agent
        self.conversation = conversation
        self.parent = parent
        self.task = task
        self.workspace = workspace
        self.kind = kind
        self.budget = budget
        self.windows = windows
        self.run = None
        self.started = time.time()
        self.report = None
        self.cancel_requested = False
        self.error = None


def _clean_budget(budget) -> dict:
    if budget is None:
        return {}
    if isinstance(budget, (int, float)) and not isinstance(budget, bool):
        budget = {"calls": budget}
    if not isinstance(budget, dict):
        raise ValueError("budget is {\"calls\", \"cost\", \"seconds\"} (or a number of calls)")
    clean = {}
    for key, value in budget.items():
        name = BUDGET_KEYS.get(str(key))
        if name is None:
            raise ValueError(f"a budget has calls, cost and seconds, not {key!r}")
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"budget {key} is a positive number")
        clean[name] = int(value) if name == "calls" else float(value)
    return clean


def left(conversation) -> dict:
    """What `conversation` has left of its budget: model calls (in its turn), dollars (None:
    no limit) and seconds, its sub-agents' spending counted."""
    config = conversation.config
    calls = int(config.max_model_calls) - int(getattr(conversation, "_iterations", 0) or 0)
    cost = None
    if config.max_cost_usd is not None:
        spent = (conversation.summary or {}).get("cost_usd", 0.0) + conversation.agents_usage["cost_usd"]
        cost = float(config.max_cost_usd) - spent
    return {"calls": calls, "cost": cost, "seconds": conversation.seconds_left()}


def external_agent(name: str):
    """The class of the kind of sub-agent `name` a package declares ([provides] agents), its
    package installed first when none provides it (packages.auto_install); ValueError says
    why there is none."""
    import importlib

    from harness.packages import MissingPackage, ensure

    try:
        package = ensure("agents", name, log=lambda message: None)
    except MissingPackage as error:
        raise ValueError(f"no agent {name!r}: {error}") from None
    module, _, attribute = package.agents[name].partition(":")
    return getattr(importlib.import_module(module), attribute)


class Agents:
    """The sub-agents of one session (one Agents is shared by all its agents). `place`
    gives them workspaces (Place); `sessions` (host/sessions.py) lists them in the session's
    tree; `windows` is who owns which window of the computer, which `share` hands windows
    over in (held(owner), transfer(window, owner, to): the computer package's WindowOwners;
    None: no windows to share); `max_depth` how deep agents nest."""

    def __init__(self, place: Place | None = None, *, sessions=None, windows=None, max_depth: int = DEFAULT_DEPTH):
        self.place = place or Place()
        self.sessions = sessions
        self.windows = windows
        self.max_depth = int(max_depth)
        self._children = {}
        self._changed = threading.Condition(threading.RLock())
        self._count = 0

    # What a running program asks (skills/agents), through its conversation.

    def handle(self, conversation, request: dict) -> dict:
        """Do what a program of `conversation` asked: {"value": ...} or {"error": ...}."""
        operation = request.get("action")
        try:
            if operation == "delegate":
                value = self.delegate(conversation, request.get("task"), workspace=request.get("workspace") or "new",
                                      budget=request.get("budget"), model=request.get("model"),
                                      agent=request.get("agent"), multi_turn=request.get("multi_turn", False))
            elif operation == "wait":
                value = self.wait(conversation, request.get("ids"), timeout=request.get("timeout"))
            elif operation == "send":
                value = self.send(conversation, request.get("agent"), request.get("text"))
            elif operation == "cancel":
                value = self.cancel(conversation, request.get("agent"))
            elif operation == "list":
                value = {child.id: self.state(child) for child in self.children(conversation)}
            else:
                raise ValueError(f"no operation {operation!r}")
        except (ValueError, RuntimeError, OSError) as error:
            return {"error": str(error)}
        return {"value": value}

    def children(self, conversation) -> list[Child]:
        """The sub-agents `conversation` started, oldest first."""
        with self._changed:
            return [child for child in self._children.values() if child.parent is conversation]

    def _mine(self, conversation, agent) -> Child:
        child = self._children.get(str(agent))
        if child is None or child.parent is not conversation:
            raise ValueError(f"you started no sub-agent {agent!r}")
        return child

    def delegate(self, parent, task, *, workspace="new", budget=None, model=None, agent=None, multi_turn=False) -> str:
        """Start a sub-agent of `parent` on `task` (see the module docstring); its id. `agent`:
        another harness's agent (a kind a package declares) in place of a conversation."""
        from harness.runtime.task.run import TaskRun

        task = " ".join(str(task or "").split()) if task is not None else ""
        if not task:
            raise ValueError("say what the sub-agent is to do")
        depth = parent.depth + 1
        if depth > self.max_depth:
            raise ValueError(f"agents at depth {parent.depth} cannot start sub-agents (the nesting depth setting is "
                             f"{self.max_depth})")
        external = external_agent(str(agent)) if agent is not None else None
        if type(multi_turn) is not bool or (multi_turn and not getattr(external, "followups", False)):
            raise ValueError("multi_turn requires a supported external delegate")
        kind = None if external is not None else parent.workspace_kind if workspace in WORKSPACES else str(workspace)
        if external is not None:
            workspace = str(agent)
        elif workspace not in WORKSPACES and kind not in self.place.kinds:
            raise ValueError(f"workspace is new, share or a kind ({', '.join(self.place.kinds) or 'none here'}), "
                             f"not {workspace!r}")
        elif kind is None or kind not in self.place.kinds:
            raise ValueError(self.place.why_not if not self.place.kinds else
                             f"this session's workspace ({kind or 'its own worker'}) is not one sub-agents can get "
                             f"here ({', '.join(self.place.kinds)})")
        budget = self._budget(parent, _clean_budget(budget))
        session = (parent.identity or {}).get("session")
        windows = []
        with self._changed:
            self._count += 1
            agent = f"a{self._count}"
            while self.sessions is not None and session and self.sessions.resolve(f"{session}/{agent}"):
                self._count += 1
                agent = f"a{self._count}"
            instruction = task
            if workspace == "share":
                windows = self._held(parent)
                instruction += "\n\nResources lent to you until you finish: " + ", ".join(item["label"] for item in windows)
            if external is not None:
                conversation = external(task, Path(parent.directory) / "agents" / agent, budget=budget,
                                        model=None if model is None else str(model), charge=parent._charge,
                                        interactive=bool(getattr(parent, "interactive", False)),
                                        confirmation=getattr(parent, "confirmation", "never"),
                                        **({"multi_turn": True} if multi_turn else {}))
            else:
                config = self.place.config(parent, kind, model)
                if config is None:
                    config = copy(parent.base_config)
                    config.main = dict(config.main)
                    if model:
                        config.main["model"] = str(model)
                config.runtime = dict(config.runtime)
                approvals = parent.config.runtime.get("approvals")
                if approvals:
                    config.runtime["approvals"] = dict(approvals)
                config.environment = dict(config.environment)
                config.max_model_calls = budget["calls"]
                config.max_cost_usd = budget["cost"]
                config.max_wall_seconds = budget["seconds"]
                conversation = TaskRun(config, parent.seed, Path(parent.directory) / "agents" / agent,
                                            chat=parent.agent_chat, verifier=parent.agent_verifier,
                                            interactive=bool(getattr(parent, "interactive", False)),
                                            confirmation=parent.confirmation, instruction=instruction,
                                            parent=parent, agents=self)
            conversation.workspace_kind = kind
            child = Child(agent, conversation, parent, task=task, workspace=workspace, kind=kind, budget=budget,
                          windows=[item["id"] for item in windows])
            self._children[agent] = child
            if self.sessions is not None and session:
                child.run = self.sessions.add_agent(session, conversation, agent=agent,
                                                    parent=(parent.identity or {}).get("agent") or "main",
                                                    title=task[:80])
            else:
                child.run = agent
                conversation.identity = {"session": session or "local", "agent": agent,
                                         "parent": (parent.identity or {}).get("agent") or "main"}
            # The windows are the sub-agent's from now until it ends.
            for item in windows:
                self.windows.transfer(item["id"], parent.identity, conversation.identity)
            conversation.trace.subscribe(lambda record: self._watch(record, child))
        parent.agents_usage["started"] += 1
        parent.trace.emit("agent_delegated", agent=agent, run=child.run, task=task, workspace=workspace, kind=kind,
                          budget=budget, model=str(model) if model else None, windows=child.windows,
                          directory=str(Path(conversation.directory).resolve()))
        threading.Thread(target=self._run, args=(child,), name=f"agent-{agent}", daemon=True).start()
        return agent

    def _budget(self, parent, wanted: dict) -> dict:
        have = left(parent)
        if have["calls"] < 1:
            raise ValueError("you have no model calls left to give a sub-agent")
        if have["cost"] is not None and have["cost"] <= 0:
            raise ValueError("you have no budget left to give a sub-agent")
        if have["seconds"] < 1:
            raise ValueError("you have no time left to give a sub-agent")
        return {"calls": min(wanted.get("calls", have["calls"]), have["calls"]),
                "cost": (wanted.get("cost") if have["cost"] is None else min(wanted.get("cost", have["cost"]),
                                                                             have["cost"])),
                "seconds": round(min(wanted.get("seconds", have["seconds"]), have["seconds"]), 1)}

    def _held(self, parent) -> list[dict]:
        """The windows `parent` owns now (share hands them over)."""
        if not parent.identity:
            raise ValueError("share hands over the windows of an agent of a session; this conversation is in none")
        held = self.windows.held(parent.identity) if self.windows is not None else []
        if not held:
            raise ValueError("you hold no resources to share now: use workspace=\"new\"")
        return held

    def _run(self, child: Child) -> None:
        conversation = child.conversation
        release = None
        try:
            if child.kind is not None:
                release = self.place.begin(conversation, child.kind, cancelled=lambda: conversation._closing)
            if conversation._closing:
                conversation._set_status("FINISHED", reason="ended before it began")
            else:
                conversation.start().join()
        except Exception as error:
            child.error = f"{type(error).__name__}: {error}"
            conversation.trace.emit("error", message=f"The sub-agent's workspace could not be prepared: {error}")
            conversation._set_status("ERROR", reason="error")
        finally:
            if release is not None:
                try:
                    release()
                except Exception:
                    pass
            self._ended(child)

    def _ended(self, child: Child) -> None:
        """A sub-agent ended: its windows go back, its last spending is charged, and its report
        goes to its parent."""
        conversation, parent = child.conversation, child.parent
        if child.windows and conversation.identity and parent.identity:
            for window in child.windows:
                try:
                    self.windows.transfer(window, conversation.identity, parent.identity)
                except ValueError:
                    pass  # it gave the window up (or its worker's process ended): it is free
        conversation.charge_up()
        report = self.state(child, ended=True)
        parent.trace.emit("agent_report", **report)
        with self._changed:
            child.report = report
            self._changed.notify_all()
        # Its entry in the parent's program ends (runtime/execution/entries.py).
        kernel = getattr(parent, "kernel", None)
        if kernel is not None:
            kernel.agent_ended(child.id, report, cancelled=child.cancel_requested)

    def state(self, child: Child, ended: bool = False) -> dict:
        """A sub-agent as its parent sees it: its status (running, waiting for approval, asks
        you (question), finished, closed, error, ...), its result or question, what it spent
        and its files."""
        if child.report is not None:
            return child.report
        conversation = child.conversation
        summary = conversation.summary or {}
        status = conversation.status
        if ended or not live(status):
            word = summary.get("status") or ("error" if status == "ERROR" else "finished")
        elif status == "IDLE" and conversation.question:
            word = "asks"
        elif status == "IDLE" and getattr(conversation, "multi_turn", False) and conversation.result is not None:
            word = "ready"
        else:
            word = {"WAITING_FOR_CONFIRMATION": "waiting for approval", "PAUSED": "paused"}.get(status, "running")
        directory = Path(conversation.directory)
        files = sorted(path.relative_to(directory).as_posix() for path in directory.rglob("*")
                       if path.is_file() and path.name not in OWN_FILES and "agents" not in
                       path.relative_to(directory).parts[:1]) if directory.is_dir() and word != "running" else []
        error = summary.get("error") or child.error
        return {"agent": child.id, "run": child.run, "status": word, "result": conversation.result,
                "question": conversation.question if word == "asks" else None,
                **({"error": error} if error and word == "error" else {}),
                "model_calls": summary.get("model_calls", 0) + conversation.agents_usage["model_calls"],
                "cost_usd": round(summary.get("cost_usd", 0.0) + conversation.agents_usage["cost_usd"], 6),
                "seconds": round(time.time() - child.started, 1), "directory": str(directory.resolve()),
                "files": files[:50]}

    def _watch(self, record: dict, child: Child) -> None:
        if record.get("event") == "state":
            with self._changed:
                self._changed.notify_all()
            if record.get("reason") == "external_turn":
                child.parent.trace.emit("agent_report", **self.state(child))

    def wake(self):
        with self._changed:
            self._changed.notify_all()

    def wait(self, parent, ids=None, timeout=None) -> dict:
        """Wait until each of `parent`'s sub-agents `ids` (default: all it started) has ended
        or asks it something, at most `timeout` seconds (None: as long as it takes), or until
        `parent` is paused or closed; their states."""
        children = self.children(parent) if not ids else [self._mine(parent, agent) for agent in
                                                          ([ids] if isinstance(ids, str) else ids)]
        if not children:
            raise ValueError("you started no sub-agents")
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0):
            raise ValueError("timeout is a number of seconds (or None)")
        began = time.monotonic()
        deadline = None if timeout is None else began + float(timeout)

        def settled(child):
            return child.report is not None or self.state(child)["status"] in ("asks", "ready")

        with self._changed:
            while not all(settled(child) for child in children):
                if parent._closing or parent._pause or (deadline is not None and time.monotonic() >= deadline):
                    break
                self._changed.wait(None if deadline is None else max(0, deadline - time.monotonic()))
            states = {child.id: self.state(child) for child in children}
        parent.trace.emit("agent_waited", agents=list(states), timeout=timeout,
                          seconds=round(time.monotonic() - began, 1),
                          states={agent: item["status"] for agent, item in states.items()})
        return states

    def send(self, parent, agent, text) -> dict:
        """A message from `parent` to its sub-agent `agent`, for its next model call."""
        child = self._mine(parent, agent)
        text = str(text or "").strip()
        if not text:
            raise ValueError("say something")
        if child.report is not None:
            raise ValueError(f"sub-agent {agent} has ended ({child.report['status']})")
        child.conversation.send_message(text, sender="parent")
        parent.trace.emit("agent_sent", agent=child.id, text=text)
        return {"ok": True}

    def cancel(self, parent, agent, wait: float = 30.0) -> dict:
        """End `parent`'s sub-agent `agent` (and its own); its report."""
        child = self._mine(parent, agent)
        parent.trace.emit("agent_cancelled", agent=child.id)
        child.cancel_requested = True
        child.conversation.close()
        with self._changed:
            self._changed.wait_for(lambda: child.report is not None, wait)
        return self.state(child)

    def end_all(self, parent, wait: float = 30.0) -> None:
        """`parent` ends: so do its sub-agents (theirs first)."""
        children = [child for child in self.children(parent) if child.report is None]
        for child in children:
            child.cancel_requested = True
            child.conversation.close()
        with self._changed:
            self._changed.wait_for(lambda: all(child.report is not None for child in children), wait)
