"""Concurrent entries and bounded ClosedLoop executions.

Entry events go through handlers from their source to the root. An unanswered event
reaches the running program at its next harness call, or at the end of the program.
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


def user_message(skill: str, parameters: dict | None = None) -> ExecutionTrace:
    """The trace of what a message for the model stopped (runtime/execution/control.py)."""
    return ExecutionTrace(skill, dict(parameters or {}), 0, 0, Event(ev.USER_MESSAGE, "user"))


# The root entry: the agent's own programs.
ROOT = "e0"
# How long a cancelled entry has to stop by itself before it is interrupted where it is.
GRACE = 0.5
# An entry's status.
STATUSES = ("running", "done", "failed", "cancelled")
# A sub-agent's report status that is a normal end (runtime/task/delegation.py state()).
AGENT_DONE = ("finished", "episode_ended")

_local = threading.local()


def current_entry():
    """The entry executing on this thread, or None for the main program."""
    return getattr(_local, "entry", None)


class Cancelled(BaseException):
    """Raised in an entry's code when the entry was cancelled; a BaseException so that the
    broad excepts of a program do not keep it running."""


def _short(value, limit=200) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


class Entry:
    """One entry of a session's tree (see the module docstring): its `id`, `name`, `kind`
    ("root", "program" for spawned code, "agent" for a sub-agent), the entry that started
    it (`parent`), its `claims`, its `status` (running, done, failed, cancelled) and, once
    ended, what its function returned (`result`) or why it failed (`error`)."""

    def __init__(self, tree, identifier, name, kind, parent, claims=(), agent=None):
        self.tree = tree
        self.id = identifier
        self.name = name
        self.kind = kind
        self.parent = parent
        self.claims = tuple(claims)
        self.agent = agent
        self.children = []
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
        # The root only: what nobody handled, for the model (an Escalation, EpisodeEnded or
        # ProgramFinished to raise in the program that runs).
        self.pending = collections.deque()

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
        """Stop this entry and the entries it started (theirs first): the execution it runs
        ends at its next step, a wait or receive it is in raises, and code that does not
        reach the harness is interrupted where it is after a moment. Returns its state."""
        if self.kind == "root":
            raise ValueError("the root entry is the agent's own program; finish() ends it")
        for child in list(self.children):
            if child.running:
                child.cancel(timeout)
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
    """The entries of one kernel session (see the module docstring)."""

    def __init__(self, session):
        self.session = session
        self._changed = threading.Condition(threading.RLock())
        self._count = 0
        self.root = Entry(self, ROOT, "main", "root", None)
        self.entries = {ROOT: self.root}
        self._ended = []
        self._closed = False
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
        cancellation, or, for the root, an event that reaches the model."""
        stop = self.interruption(entry or self.current())
        if stop is not None:
            raise stop

    def interruption(self, entry, take=True):
        """What `entry`'s code must stop for now (see check), or None; `take` False leaves
        the root's event waiting. The root's code also stops for a message for the model
        (runtime/execution/control.py), with a USER_MESSAGE event."""
        for above in entry.lineage():
            if above._cancel.is_set():
                return Cancelled(f"entry {above.id} ({above.name}) was cancelled")
        if entry is self.root and control.message_arrived():
            return Escalation(user_message("program"))
        if entry is self.root and self.root.pending:
            with self._changed:
                if self.root.pending:
                    return self.root.pending.popleft() if take else self.root.pending[0]
        return None

    # Starting entries.

    def spawn(self, fn, name=None, claims=None) -> Entry:
        """Run fn() as a new entry under the caller's (see the module docstring)."""
        sys.audit("harness.execution")
        if not callable(fn):
            raise TypeError("spawn(fn, name, claims): fn must be callable")
        parent = self.current()
        self.check(parent)
        claims = [claims] if isinstance(claims, str) else list(claims or [])
        tick = self._channels()
        if tick is not None:
            tick.known(claims)
        entry = self._add(str(name or getattr(fn, "__name__", "entry")), "program", parent, claims)
        conflict = tick.claim(entry, claims) if tick is not None and claims else {}
        span = spans.current()
        testing = spans.in_test()

        def run():
            _local.entry = entry
            spans.set_entry(entry.id)
            status, result, error, failure = "done", None, None, None
            try:
                with spans.under(span), spans.testing(testing):
                    self.check(entry)
                    if conflict:
                        raise Escalation(self._conflict(entry, conflict))
                    result = fn()
            except Cancelled:
                status = "cancelled"
            except Escalation as escalation:
                status, failure = "failed", escalation.trace.event
                error = f"{failure.kind} from {failure.source}"
            except (EpisodeEnded, ProgramFinished) as stop:
                # The episode ended, or the task is done: the agent's program hears of it,
                # and the entry is no event of its own.
                status, error = ("cancelled", "the episode ended") if isinstance(stop, EpisodeEnded) else ("done", None)
                self._for_model(stop, entry)
            except BaseException as raised:
                status, error = "failed", f"{type(raised).__name__}: {_short(str(raised), 300)}"
            finally:
                self._end(entry, status, result=result, error=error, failure=failure)
        entry.thread = threading.Thread(target=run, name=f"entry-{entry.id}", daemon=True)
        entry.thread.start()
        return entry

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
        """The entry of a sub-agent the caller started (delegate)."""
        return self._add(_short(" ".join(str(task).split()), 80), "agent", self.current(), (), agent=str(agent))

    def agent_ended(self, agent, report, *, cancelled=False) -> None:
        """A sub-agent ended (the conversation tells the kernel, runtime/execution/kernel.py): so does
        its entry, failed unless it finished."""
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

    def _add(self, name, kind, parent, claims, agent=None) -> Entry:
        with self._changed:
            if self._closed:
                raise RuntimeError("the session has closed")
            self._count += 1
            entry = Entry(self, f"e{self._count}", name, kind, parent, claims, agent=agent)
            self.entries[entry.id] = entry
            parent.children.append(entry)
        spans.record("entry_start", id=entry.id, parent=parent.id, name=entry.name, kind=kind,
                     **({"claims": entry.claims} if entry.claims else {}), **({"agent": agent} if agent else {}),
                     span=spans.current())
        return entry

    # Ending entries, and their events.

    def _end(self, entry, status, result=None, error=None, failure=None) -> None:
        """`entry` ended: its own entries end with it, its guards and handlers go, its
        waiters wake, and a failure goes up as an ENTRY_FAILED event."""
        for child in list(entry.children):
            if child.running:
                try:
                    child.cancel()
                except BaseException:
                    pass
        with self._changed:
            if not entry.running:
                return
            entry.status, entry.result, entry.error = status, result, error
            entry.ended = time.time()
            self._ended.append(entry)
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
        if reactive is not None:
            reactive.clear_owner(entry.id)
        tick = self.session.__dict__.get("_tick_loop")
        if tick is not None and tick.channels:
            # Its claims go, and what it held down goes up at the next period.
            tick.release(entry)
        spans.record("entry_end", id=entry.id, status=status,
                     **({"error": _short(error, 300)} if error else {}),
                     **({"event_kind": failure.kind} if failure is not None else {}))
        if entry.failure is not None and not waited:
            if threading.current_thread() is entry.thread:
                # Its thread ends after this: the parent's handlers run on it.
                self.deliver(entry.parent, entry.failure.trace)
            else:
                threading.Thread(target=self.deliver, args=(entry.parent, entry.failure.trace),
                                 name=f"event-{ev.ENTRY_FAILED}", daemon=True).start()

    def deliver(self, entry, trace) -> bool:
        """Offer the event of `trace` to the handlers of `entry` and up; one nobody
        handles reaches the model. Whether a handler resolved it."""
        if self.handle(entry, trace):
            return True
        self._for_model(Escalation(trace), entry)
        return False

    def record_event(self, trace, entry=None):
        record = {"skill": trace.skill, "event": trace.event.to_dict(), "ticks": trace.ticks}
        if entry is not None:
            record["entry"] = entry.id
        # Events still pass through the same handlers. History streams to the host;
        # the next decision gets bounded feedback rather than every operation again.
        spans.note("execution_event", execution=record)
        counts = self.session.__dict__.setdefault("_event_counts", {})
        counts[trace.event.kind] = counts.get(trace.event.kind, 0) + 1
        if not trace.ok:
            self.session._events.append(record)
            if len(self.session._events) > 32:
                del self.session._events[0]
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
        if control.host_thoughts:
            trace = stop.trace
            spans.note("escalation", id=uuid.uuid4().hex, entry=entry.id, skill=trace.skill,
                       event=trace.event.to_dict())
            return
        with self._changed:
            self.root.pending.append(stop)
            self._changed.notify_all()

    # What the kernel does around a program.

    def begin_program(self) -> None:
        """A program starts: an event that reached the model while none ran ends it at
        once (it was written without knowing)."""
        self.check(self.root)

    def end_program(self) -> None:
        """A program ended: an event that reached the model while it ran and that it did not
        meet is its end."""
        self.check(self.root)

    def drain(self) -> list[dict]:
        """The entries the model hears of after a program: those running, and those that
        ended since the last drain (the root aside)."""
        with self._changed:
            ended, self._ended = self._ended, []
            running = [entry for entry in self.entries.values() if entry.running and entry is not self.root]
        return [entry.state() for entry in ended + running]

    def close(self, timeout=2.0) -> None:
        """The session closes: every entry is cancelled."""
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

# Escalations that end the program whatever a loop does: the episode's end, a pause, a message.
PASS_ON = frozenset({ev.EPISODE_ENDED, ev.USER_PAUSED, ev.USER_MESSAGE})


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
