"""Units of a kernel session, and bounded ClosedLoop executions.

A session has one model (the root entry) and the units it started: every program the model
writes, every function a program spawns, every sub-agent. A unit has its own output, events
and pictures (its box) and its own result. What a unit starts belongs to the model, not to
the unit: it outlives the program that started it and ends with the model. An event goes
through the handlers; one nobody answers reaches the model, and so does every unit's end.
"""

import collections
import sys
import threading
import time
import uuid

from harness.core import spans
from harness.runtime.execution import control
from harness.runtime import events as ev
from harness.runtime.reactive import rules as reactive
from harness.runtime.events import EpisodeEnded, Escalation, Event, ExecutionTrace, ProgramFinished


# The root entry: the model, to which every unit of the session belongs.
ROOT = "e0"
# How long a cancelled entry has to stop by itself before it is interrupted where it is.
GRACE = 0.5
# An entry's status.
STATUSES = ("running", "done", "failed", "cancelled")
# A sub-agent's report status that is a normal end (runtime/task/delegation.py state()).
AGENT_DONE = ("finished", "episode_ended")

_local = threading.local()


def current_entry():
    """The entry executing on this thread, or None outside every unit."""
    return getattr(_local, "entry", None)


class Box:
    """What one unit gathered for the model: its output (a writer the kernel gives it, whose
    recent(chars) is what was printed last), the pictures it showed and looked at, and the
    events of its executions."""

    def __init__(self):
        self.output = None
        self.attachments, self.events, self.looks = [], [], []
        self.event_counts = {}


class Cancelled(BaseException):
    """Raised in an entry's code when the entry was cancelled; a BaseException so that the
    broad excepts of a program do not keep it running."""


def _short(value, limit=200) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


class Entry:
    """One unit of a session (see the module docstring): its `id`, `name`, `kind` ("root"
    for the model, "program" for code, "agent" for a sub-agent), the model it belongs to
    (`parent`), its `claims`, its `status` (running, done, failed, cancelled) and, once
    ended, what its function returned (`result`) or why it failed (`error`). `cell` is the
    number of the model's program it is (None for spawned code), `rule` the name of the rule
    whose program it is (the rules that program sets live with it), `priority` what it holds
    the embodiment with and `restart` whether an execution of it that a higher unit ended
    is started again (runtime/tick.py; default: it ends with PREEMPTED), `box` what it gathered,
    `outcome` how its code ended ({"status": ok, error, escalated, episode_ended, finished
    or cancelled, ...}), `raised` the exception of an error."""

    def __init__(self, tree, identifier, name, kind, parent, claims=(), agent=None):
        self.tree = tree
        self.id = identifier
        self.name = name
        self.kind = kind
        self.parent = parent
        self.claims = tuple(claims)
        self.agent = agent
        self.children = []
        self.cell = None
        self.rule = None
        self.priority = 0
        self.restart = False
        # It keeps the embodiment until it ends: no other unit takes it (uninterruptible()).
        self.uninterruptible = False
        self.box = Box()
        self.outcome = None
        self.raised = None
        self.status = "running"
        self.result = None
        self.error = None
        # The Escalation of its failure: what wait() raises.
        self.failure = None
        self.started = time.time()
        self.ended = None
        self.thread = None
        self._inbox = collections.deque()
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._waiters = 0

    def __repr__(self) -> str:
        return f"<entry {self.id} {self.name!r} {self.kind} {self.status}>"

    @property
    def running(self) -> bool:
        """Whether it has not ended yet."""
        return self.status == "running"

    def lineage(self) -> list:
        """This entry and the entries above it, up to the root."""
        chain, entry = [], self
        while entry is not None:
            chain.append(entry)
            entry = entry.parent
        return chain

    def state(self) -> dict:
        """The entry as a program and the model see it."""
        data = {"entry": self.id, "name": self.name, "kind": self.kind,
                "parent": self.parent.id if self.parent is not None else None, "status": self.status,
                "seconds": round((self.ended or time.time()) - self.started, 1)}
        if self.claims:
            data["claims"] = list(self.claims)
        if self.agent is not None:
            data["agent"] = self.agent
        if self.status == "done" and self.result is not None:
            data["result"] = _short(self.result)
        if self.error is not None:
            data["error"] = self.error
        return data

    # What a program calls on the handle.

    def wait(self, timeout=None):
        """Wait until this entry has ended, at most `timeout` seconds (None: as long as it
        takes). Returns what its
        function returned (a sub-agent: its report); raises its failure (an Escalation
        with an ENTRY_FAILED event), which this wait then handles; returns None when it
        was cancelled or is still running at the timeout (`status` says which)."""
        caller = self.tree.current()
        if caller is self:
            raise ValueError("an entry cannot wait for itself")
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        with self.tree._changed:
            self._waiters += 1
            try:
                while not self._done.is_set():
                    self.tree.check(caller)
                    left = None if deadline is None else deadline - time.monotonic()
                    if left is not None and left <= 0:
                        break
                    self.tree._changed.wait(left)
            finally:
                self._waiters -= 1
        if self.status == "failed":
            raise self.failure
        return self.result if self.status == "done" else None

    def output(self, chars=2000) -> str:
        """What this unit has printed so far: the last `chars` characters (at most 4000),
        while it runs or after it ended. Reading takes nothing away: its result still has
        the whole output when it ends. "" for a unit that printed nothing (a sub-agent
        prints nothing here: its report is its result)."""
        writer = self.box.output
        return writer.recent(chars) if writer is not None else ""

    def send(self, message):
        """Send this entry a message, which its code reads with receive() (a sub-agent: the
        answer to its question, or more to do)."""
        if not self.running:
            raise ValueError(f"entry {self.id} ({self.name}) has ended ({self.status})")
        if self.kind == "agent":
            self.tree.session.send_agent(self.agent, message)
            return
        with self.tree._changed:
            self._inbox.append(message)
            self.tree._changed.notify_all()

    def cancel(self, timeout=5.0):
        """Stop this unit: the execution it runs ends at its next step, a wait or receive it
        is in raises, and code that does not reach the harness is interrupted where it is
        after a moment. What it started goes on (it is the model's). Returns its state."""
        if self.kind == "root":
            raise ValueError("the root entry is the model; finish() ends the run")
        if not self.running:
            return self.state()
        self._cancel.set()
        control.wake_waiters()
        with self.tree._changed:
            self.tree._changed.notify_all()
        if self.kind == "agent":
            try:
                self.tree.session.cancel_agent(self.agent)
            finally:
                self.tree._end(self, "cancelled")
            return self.state()
        if self.thread is threading.current_thread():
            raise Cancelled(f"entry {self.id} cancelled itself")
        if not self._done.wait(min(GRACE, timeout)):
            if self.thread is not None and self.thread.ident is not None:
                reactive._raise_in(self.thread.ident, Cancelled)
            self._done.wait(max(0.0, timeout - GRACE))
        return self.state()

    def receive(self, timeout=None):
        """The oldest message sent to this entry, waiting at most `timeout` seconds for one
        (None: as long as it takes); None when none came."""
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        with self.tree._changed:
            while not self._inbox:
                self.tree.check(self)
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return None
                self.tree._changed.wait(left)
            return self._inbox.popleft()


class Tree:
    """The units of one kernel session (see the module docstring). `on_end(entry, handled)`
    is called once for every unit that ended (the kernel tells the model,
    runtime/execution/kernel.py); `new_output(entry)` gives a new unit the writer of its output."""

    def __init__(self, session):
        self.session = session
        self._changed = threading.Condition(threading.RLock())
        self._count = 0
        self.root = Entry(self, ROOT, "model", "root", None)
        self.entries = {ROOT: self.root}
        self._closed = False
        self.on_end = None
        self.new_output = None
        control.on_agent_ended(self.agent_ended)

    # Where code runs.

    def current(self) -> Entry:
        """The entry the calling code belongs to (the root outside every other)."""
        entry = getattr(_local, "entry", None)
        return entry if entry is not None and entry.tree is self else self.root

    def acting(self, entry):
        """Code inside belongs to `entry` (the tick steps an entry's execution, a handler
        of an entry runs)."""
        return _Acting(entry)

    def get(self, identifier) -> Entry:
        """The entry `identifier` (the root when there is none)."""
        return self.entries.get(identifier) or self.root

    def under(self, entry) -> list:
        """`entry` and every entry below it (those it started, those they started, ...)."""
        with self._changed:
            return [each for each in self.entries.values() if entry in each.lineage()]

    def check(self, entry=None) -> None:
        """Raise in the code of `entry` (default: the caller's) what it must stop for: its
        cancellation, or the user's pause."""
        stop = self.interruption(entry or self.current())
        if stop is not None:
            raise stop

    def interruption(self, entry, take=True):
        """What `entry`'s code must stop for now (see check), or None: every unit of the
        model stops while the user has paused it (runtime/execution/control.py)."""
        if entry._cancel.is_set():
            return Cancelled(f"entry {entry.id} ({entry.name}) was cancelled")
        if entry is not self.root and control.pause_requested():
            return Escalation(ExecutionTrace("program", {}, 0, 0, Event(ev.USER_PAUSED, "user")))
        return None

    # Starting entries.

    def spawn(self, fn, name=None, claims=None, *, cell=None, rule=None, priority=None, restart=False) -> Entry:
        """Run fn() as a new unit of the model (see the module docstring); `cell`: it is the
        model's program of that number; `rule`: it is the program of that rule; `priority`:
        its own (default: that of the unit that starts it); `restart` True: an execution of
        it that a unit of higher priority ends is started again when that unit is over
        (default: it ends there with PREEMPTED)."""
        sys.audit("harness.execution")
        if not callable(fn):
            raise TypeError("spawn(fn, name, claims): fn must be callable")
        self.check(self.current())
        claims = [claims] if isinstance(claims, str) else list(claims or [])
        tick = self._channels()
        if tick is not None:
            tick.known(claims)
        if priority is not None and (isinstance(priority, bool) or not isinstance(priority, (int, float))):
            raise ValueError(f"priority is a number, got {priority!r}")
        entry = self._add(str(name or getattr(fn, "__name__", "entry")), "program", self.root, claims, cell=cell,
                          rule=rule, priority=self.current().priority if priority is None else priority)
        entry.restart = bool(restart)
        conflict = tick.claim(entry, claims) if tick is not None and claims else {}
        span = spans.current()
        testing = spans.in_test()

        def run():
            _local.entry = entry
            spans.set_entry(entry.id)
            status, result, error, failure = "done", None, None, None
            entry.outcome = {"status": "ok"}
            try:
                with spans.under(span), spans.testing(testing):
                    self.check(entry)
                    if conflict:
                        raise Escalation(self._conflict(entry, conflict))
                    result = fn()
            except Cancelled:
                status, entry.outcome = "cancelled", {"status": "cancelled"}
            except Escalation as escalation:
                status, failure = "failed", escalation.trace.event
                error = f"{failure.kind} from {failure.source}"
                entry.outcome = {"status": "escalated", "escalation": escalation.trace.to_dict()}
            except EpisodeEnded as stop:
                # The episode ended: the model hears of it with this unit's end, and the
                # unit is no event of its own.
                status, error = "cancelled", "the episode ended"
                entry.outcome = {"status": "episode_ended", "episode_ended": stop.trace.to_dict()}
            except ProgramFinished as stop:
                entry.outcome = {"status": "finished", "finish": stop.summary}
            except BaseException as raised:
                status, error = "failed", f"{type(raised).__name__}: {_short(str(raised), 300)}"
                entry.outcome, entry.raised = {"status": "error", "error": error}, raised
            finally:
                self._end(entry, status, result=result, error=error, failure=failure)
        entry.thread = threading.Thread(target=run, name=f"entry-{entry.id}", daemon=True)
        entry.thread.start()
        return entry

    def uninterruptible(self) -> None:
        """The unit this code runs in keeps the embodiment from now until it ends: no rule's
        program and no other unit takes it, whatever their priority (runtime/tick.py hold).
        Its own ends stay: it is cancelled, its calls reach their time, a rule that ends
        executions holds, the episode ends."""
        entry = self.current()
        if entry is self.root:
            raise RuntimeError("uninterruptible() is called by a program: it says that this program keeps the environment")
        if entry.uninterruptible:
            return
        entry.uninterruptible = True
        spans.note("uninterruptible", unit=entry.id)
        self.session._ticker.hold(entry)

    def claim(self, names) -> bool:
        """The caller's entry claims the channels `names` (see the module docstring): True;
        False when one is another entry's and a handler took the CHANNEL_CONFLICT event,
        which otherwise escalates."""
        tick = self._channels()
        if tick is None:
            raise ValueError("this embodiment declares no channels to claim")
        entry = self.current()
        names = tick.known(names)
        found = tick.claim(entry, names)
        if not found:
            entry.claims = tuple(dict.fromkeys([*entry.claims, *names]))
            spans.record("entry_claims", id=entry.id, claims=list(entry.claims))
            return True
        self.session._finish(self._conflict(entry, found))
        return False

    def release(self, names=None) -> None:
        """The caller's entry lets go of the channels `names` (None: all it has): its
        claims, and the keys and buttons it holds down on them."""
        tick = self._channels()
        if tick is None:
            raise ValueError("this embodiment declares no channels to release")
        entry = self.current()
        names = None if names is None else tick.known(names)
        tick.release(entry, names)
        entry.claims = () if names is None else tuple(name for name in entry.claims if name not in names)
        spans.record("entry_claims", id=entry.id, claims=list(entry.claims))

    def channels(self) -> dict:
        """Who has each channel now ({channel: {"entry", "how"}}, None: nobody); {} when
        the embodiment declares none."""
        tick = self._channels()
        return tick.board() if tick is not None else {}

    def _channels(self):
        """The session's tick when its embodiment declares channels, else None."""
        tick = self.session._ticker
        return tick if tick.channels else None

    def _conflict(self, entry, found) -> ExecutionTrace:
        step = (self.session.state or {}).get("step")
        return ExecutionTrace("claim", {"channels": sorted(found)}, step, step,
                              Event(ev.CHANNEL_CONFLICT, "channels", {"channels": found, "entry": entry.id}, step))

    def adopt_agent(self, agent, task) -> Entry:
        """The unit of a sub-agent the model's code started (delegate)."""
        return self._add(_short(" ".join(str(task).split()), 80), "agent", self.root, (), agent=str(agent))

    def agent_runs(self, agent) -> bool:
        """Whether a unit of sub-agent `agent` has not ended."""
        return any(item.kind == "agent" and item.agent == str(agent) and item.running
                   for item in list(self.entries.values()))

    def agent_ended(self, agent, report, *, cancelled=False) -> None:
        """A turn of a sub-agent ended (the conversation tells the kernel, runtime/execution/kernel.py):
        so does its entry, failed unless the turn ended with an answer."""
        entry = next((item for item in list(self.entries.values()) if item.kind == "agent" and item.agent == str(agent)
                      and item.running), None)
        if entry is None:
            return
        report = dict(report or {})
        status = report.get("status")
        if cancelled or entry._cancel.is_set():
            self._end(entry, "cancelled", result=report)
        elif status in AGENT_DONE:
            self._end(entry, "done", result=report)
        else:
            self._end(entry, "failed", result=report, error=f"the sub-agent ended: {status}"
                      + (f" ({report['error']})" if report.get("error") else ""))

    def _add(self, name, kind, parent, claims, agent=None, cell=None, rule=None, priority=0) -> Entry:
        with self._changed:
            if self._closed:
                raise RuntimeError("the session has closed")
            self._count += 1
            entry = Entry(self, f"e{self._count}", name, kind, parent, claims, agent=agent)
            entry.cell, entry.rule, entry.priority = cell, rule, priority
            if self.new_output is not None:
                entry.box.output = self.new_output(entry)
            self.entries[entry.id] = entry
            parent.children.append(entry)
        spans.record("entry_start", id=entry.id, parent=parent.id, name=entry.name, kind=kind,
                     **({"cell": cell} if cell is not None else {}), **({"rule": rule} if rule else {}),
                     **({"priority": priority} if priority else {}),
                     **({"claims": entry.claims} if entry.claims else {}), **({"agent": agent} if agent else {}),
                     span=spans.current())
        return entry

    # Ending entries, and their events.

    def _end(self, entry, status, result=None, error=None, failure=None) -> None:
        """`entry` ended: its waiters wake, its channels go, and the model hears of it
        (on_end); the failure of a unit nobody waited for goes to the handlers first, as an
        ENTRY_FAILED event. What it started (units, rules, handlers) is the model's and stays."""
        with self._changed:
            if not entry.running:
                return
            entry.status, entry.result, entry.error = status, result, error
            entry.ended = time.time()
            if entry.outcome is None:
                entry.outcome = {"status": {"done": "ok", "failed": "error"}.get(status, status),
                                 **({"error": error} if error else {})}
            if status == "failed":
                step = (self.session.state or {}).get("step")
                detail = {"entry": entry.id, "kind": entry.kind}
                detail.update({"event": failure.to_dict()} if failure is not None else {"error": error})
                if entry.agent is not None:
                    detail["agent"] = entry.agent
                entry.failure = Escalation(ExecutionTrace(entry.name, {}, step, step,
                                                          Event(ev.ENTRY_FAILED, entry.name, detail, step)))
            waited = entry._waiters > 0
            entry._done.set()
            self._changed.notify_all()
        reactive = getattr(self.session, "reactive", None)
        if reactive is not None and entry.rule is not None:
            # The rules a rule's program set lived with it.
            reactive.clear_owner(entry.id)
        tick = self.session.__dict__.get("_tick_loop")
        if tick is not None:
            # A rule waits for its program's end (runtime/reactive/rules.py).
            tick.judge()
        if tick is not None and tick.channels:
            # Its claims go, and what it held down goes up at the next period.
            tick.release(entry)
        spans.record("entry_end", id=entry.id, status=status,
                     **({"error": _short(error, 300)} if error else {}),
                     **({"event_kind": failure.kind} if failure is not None else {}))
        if threading.current_thread() is entry.thread:
            # Its thread ends after this: the handlers and the report run on it.
            self._ended(entry, waited)
        else:
            threading.Thread(target=self._ended, args=(entry, waited), name=f"end-{entry.id}", daemon=True).start()

    def _ended(self, entry, waited) -> None:
        handled = waited
        if entry.failure is not None and not waited and entry.cell is None:
            # A program of the model reports its failure with its result; another unit's
            # failure is an event for the handlers first.
            handled = self.handle(self.root, entry.failure.trace)
        if self.on_end is not None:
            try:
                with self.acting(entry):
                    self.on_end(entry, handled)
            except BaseException as error:
                print(f"harness kernel: the end of {entry.id} was not reported: {type(error).__name__}: {error}",
                      file=sys.stderr)

    def record_event(self, trace, entry=None):
        record = {"skill": trace.skill, "event": trace.event.to_dict(), "ticks": trace.ticks}
        if entry is not None:
            record["entry"] = entry.id
        # Events still pass through the same handlers. History streams to the host;
        # the next decision gets bounded feedback rather than every operation again.
        spans.note("execution_event", execution=record)
        # Kept by the unit whose execution it was (the model's own box outside every unit).
        box = (entry if entry is not None else self.current()).box
        box.event_counts[trace.event.kind] = box.event_counts.get(trace.event.kind, 0) + 1
        if not trace.ok:
            box.events.append(record)
            if len(box.events) > 32:
                del box.events[0]
        return record

    def raise_event(self, entry, trace, *, notice=False) -> None:
        """Deliver an independent event without waiting for its handlers on the tick."""
        record = self.record_event(trace, entry)

        def deliver():
            _local.entry = entry
            if self.handle(entry, trace):
                record["handled"] = True
            elif not notice:
                self._for_model(Escalation(trace), entry)
        threading.Thread(target=deliver, name=f"event-{trace.event.kind}", daemon=True).start()

    def handle(self, entry, trace) -> bool:
        """Offer `trace`'s event to the answer for its kind of `entry`, then of each entry
        above it (runtime/reactive/rules.py answer): the first that does not return False
        resolves it."""
        layer = getattr(self.session, "reactive", None)
        if layer is None:
            return False
        return layer.answer([level.id for level in entry.lineage()], trace, lambda owner: self.acting(self.get(owner)),
                            lambda owner, fault: reactive.emit(
                                self, owner, trace.skill, reactive.fault_event(fault, trace.end_tick)))

    def _for_model(self, stop, entry) -> None:
        """An event nobody handled reaches the model: a note to the conversation that runs
        this kernel (runtime/task/run.py)."""
        trace = stop.trace
        spans.note("escalation", id=uuid.uuid4().hex, entry=entry.id, skill=trace.skill,
                   event=trace.event.to_dict())

    def running(self) -> list:
        """The units that have not ended, oldest first (the model aside)."""
        with self._changed:
            return [entry for entry in self.entries.values() if entry.running and entry is not self.root]

    def close(self, timeout=2.0) -> None:
        """The session closes: the model ends, and every unit with it."""
        with self._changed:
            self._closed = True
        for entry in list(self.root.children):
            if entry.running and entry.kind != "agent":
                try:
                    entry.cancel(timeout)
                except BaseException:
                    pass
        control.on_agent_ended(self.agent_ended, remove=True)


def _tag(entry):
    """What an entry's spans carry as their `entry`: none for the root's."""
    return None if entry.kind == "root" else entry.id


class _Acting:
    def __init__(self, entry):
        self.entry = entry

    def __enter__(self):
        self.saved = getattr(_local, "entry", None), spans.set_entry(_tag(self.entry))
        _local.entry = self.entry
        return self.entry

    def __exit__(self, *_):
        _local.entry = self.saved[0]
        spans.set_entry(self.saved[1])
        return False


# -- The closed loop every execution runs as ----------------------------------------------

# Escalations that end the program whatever a loop does: the episode's end, a pause.
PASS_ON = frozenset({ev.EPISODE_ENDED, ev.USER_PAUSED})


class Result(dict):
    """What a closed loop did: {"ok", "reason", "tries", "seconds", "detail"}; true when ok."""

    def __bool__(self):
        return bool(self.get("ok"))

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


class Stop(Exception):
    """Raised in a step: the loop ends here with this reason (no more tries)."""


class ClosedLoop:
    """Confirm, do, check, retry, give the reason: one bounded execution, in any action
    scenario; a skill the model writes is one, and so is every execution of the session's
    skills (runtime/execution/session.py Execution). A subclass fills in confirm() (before each try:
    True, or the reason not to act), do(), check() (after it: True, or why not) and
    recover(reason) (between tries); a step may raise Stop(reason). Called with the skill's
    parameters (on self), it runs at most `tries` times and `max_seconds` long and returns a
    Result; an exception of `catches` in a step is its reason (the episode's end, finish()
    and PASS_ON always end the program). A step may fill in `detail`. Each try's end is
    report()ed: a skill_step record, news for the model while the program runs."""

    tries = 3
    max_seconds = 30.0
    catches = Exception

    def __new__(cls, *args, **kwargs):
        from harness.runtime.learning.library import assert_active

        assert_active(cls)
        loop = super().__new__(cls)
        loop.__init__(*args, **kwargs)
        return loop.run()

    def __init__(self, *args, **kwargs):
        self.args = args
        self.__dict__.update(kwargs)
        self.detail = {}

    def confirm(self):
        return True

    def do(self):
        raise NotImplementedError("a closed loop's do() is the action")

    def check(self):
        return True

    def recover(self, reason):
        pass

    def report(self, number: int, what: str, ok: bool, seconds: float, reason) -> None:
        from harness.runtime.learning.library import code_origin

        spans.step(type(self).__name__, number, what, ok, seconds, reason, of=int(self.tries),
                   library=code_origin(type(self)))

    def run(self) -> Result:
        start = time.monotonic()
        reason, tries = None, 0
        try:
            for tries in range(1, max(1, int(self.tries)) + 1):
                if time.monotonic() - start > self.max_seconds:
                    reason = f"out of time ({self.max_seconds:g} s)"
                    break
                begun = time.monotonic()
                confirmed = self.confirm()
                if confirmed is not True:
                    reason = _why(confirmed, "not confirmed")
                    break
                wait = 0.0
                try:
                    self.do()
                    checked = self.check()
                except Escalation as escalation:
                    # An event of a step (a rejected command, a guard) is this try's failure:
                    # the next try comes after the wait the event asks for, if any.
                    if escalation.trace.event.kind in PASS_ON or not isinstance(escalation, self.catches):
                        raise
                    checked, wait = str(escalation), _wait_asked(escalation)
                if checked is True:
                    return self._result(True, None, tries, start)
                reason = _why(checked, "the check failed")
                if tries < self.tries:
                    self.report(tries, "try", False, time.monotonic() - begun, reason)
                    left = self.max_seconds - (time.monotonic() - start)
                    if wait > left:
                        break
                    time.sleep(wait)
                    self.recover(reason)
        except Stop as stop:
            reason = str(stop) or "stopped"
        except (ProgramFinished, EpisodeEnded):
            raise
        except Escalation as escalation:
            if escalation.trace.event.kind in PASS_ON or not isinstance(escalation, self.catches):
                raise
            reason = str(escalation)
        except Exception as error:
            if not isinstance(error, self.catches):
                raise
            reason = f"{type(error).__name__}: {error}"
        return self._result(False, reason, tries, start)

    def _result(self, ok, reason, tries, start) -> Result:
        result = Result(ok=ok, reason=reason, tries=tries, seconds=round(time.monotonic() - start, 2),
                        detail=dict(getattr(self, "detail", None) or {}))
        self.report(tries, "done" if ok else "gave up", ok, result["seconds"], reason)
        return result


def _why(value, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _wait_asked(escalation) -> float:
    """The seconds an event asks to wait before acting again (a shield's reason with
    `wait_seconds`, such as the user using the computer), else 0."""
    detail = escalation.trace.event.detail or {}
    reasons = detail.get("reasons") or (detail.get("shield") or {}).get("reasons") or []
    waits = [float(reason.get("wait_seconds", 0) or 0) for reason in reasons if isinstance(reason, dict)]
    return max(waits, default=0.0)
