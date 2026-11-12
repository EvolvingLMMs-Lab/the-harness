"""Observe, judge the rules and deliver one worker command per control period.

The tick exists while an execution or a rule on time needs it, and not otherwise: nothing
is driven by time unless a unit asks for it. Single-resource executions take turns and
receive the receipts for their own commands. With channels, executions advance
concurrently, merging their inputs with what units hold before local admission. Delayed
actions retain their admission and attribution until delivery. The worker shield judges
every delivered command.
"""

import collections
import contextlib
import math
import sys
import threading
import time
import uuid

from harness.core import spans
from harness.runtime.safety.approval import WORKER_APPROVAL_SECONDS
from harness.runtime.execution import control
from harness.runtime import events as ev
from harness.runtime.reactive import rules as reactive


def driving(profile) -> tuple:
    """How an environment says it can be driven: (the most commands a second it takes, None:
    as fast as it answers; the time one step of it lasts, None: its time is the wall's).
    From the profile's `max_hz` and `step_seconds`; a profile that still names a `clock`
    is read as what that mode meant: steps (or none), each step lasts 1 / control_hz;
    wall, at most control_hz commands a second; events, neither."""
    profile = profile or {}
    hz = float(profile.get("control_hz", 1))
    named = "max_hz" in profile or "step_seconds" in profile
    clock = None if named else str(profile.get("clock") or "steps")
    bound = profile.get("max_hz") or (hz if clock == "wall" else None)
    step = profile.get("step_seconds") or (1.0 / hz if clock == "steps" else None)
    return (float(bound) if bound else None, float(step) if step else None)


def delay_ticks(reaction_delay_ms, hz) -> int:
    """The control periods a decision waits before it is sent: `reaction_delay_ms`
    rounded up to whole periods of `hz`."""
    delay = float(reaction_delay_ms or 0.0)
    if not math.isfinite(delay) or delay < 0:
        raise ValueError(f"reaction_delay_ms must be a number of milliseconds >= 0, got {reaction_delay_ms!r}")
    return math.ceil(delay * float(hz) / 1000.0 - 1e-9) if delay else 0


# How often the code waiting for its execution looks for a reason to stop waiting.
POLL = 0.05
# How often an environment driven at a rate tells the host how its periods went (a tick_periods note).
PERIODS_NOTE_SECONDS = 10.0


class _Periods:
    """The periods of an environment driven at a rate since the last tick_periods note: their lengths and parts
    (observe, decide, send), in ms."""

    PARTS = ("observe", "decide", "send")

    def __init__(self, period):
        self.period = period
        self.since = time.monotonic()
        self.last = None
        self.lengths, self.parts = [], {name: [] for name in self.PARTS}

    def begin(self):
        now = time.monotonic()
        if self.last is not None:
            self.lengths.append(now - self.last)
        self.last = self.marked = now

    def mark(self, name):
        now = time.monotonic()
        self.parts[name].append(now - self.marked)
        self.marked = now

    def flush(self):
        """The note, when PERIODS_NOTE_SECONDS passed since the last one."""
        if time.monotonic() - self.since < PERIODS_NOTE_SECONDS or not self.lengths:
            return
        lengths = sorted(self.lengths)

        def ms(values, q=0.5):
            values = sorted(values)
            return round(1000 * values[min(len(values) - 1, int(len(values) * q))], 1) if values else None
        spans.note("tick_periods", periods=len(lengths), target_ms=round(1000 * self.period, 1),
                   period_ms={"p50": ms(lengths), "p90": ms(lengths, 0.9), "max": round(1000 * lengths[-1], 1)},
                   late=sum(length > 1.5 * self.period for length in lengths),
                   **{f"{name}_ms": {"p50": ms(values), "p90": ms(values, 0.9)} for name, values in self.parts.items()})
        self.since = time.monotonic()
        self.lengths, self.parts = [], {name: [] for name in self.PARTS}


class Preempted(Exception):
    """Raised in an execution's steps where they wait for a step's reply: the unit `by`, of
    `priority`, takes the embodiment."""

    def __init__(self, by=None, priority=0):
        super().__init__(f"preempted by {by}")
        self.by, self.priority = by, priority


def _rank(unit) -> float:
    """What a unit holds the embodiment with: its priority, or above every priority when it
    said it is uninterruptible."""
    if getattr(unit, "uninterruptible", False):
        return float("inf")
    return getattr(unit, "priority", 0) or 0


class _Entry:
    def __init__(self, steps, parent, owner=None):
        # `steps`: the execution's generator, or what makes one (then, where its unit asked
        # to be started again, it is made anew after a unit of higher priority took the
        # embodiment from it).
        self.make = steps if callable(steps) else None
        self.steps = None if callable(steps) else steps
        self.parent = parent
        self.owner = owner
        self.priority = _rank(owner)
        self.restart = getattr(owner, "restart", False)
        self.restarts = 0
        self.picked = False
        self.started = False
        self.trace = None
        self.error = None
        self.cancelled = False
        self.done = threading.Event()
        self.queued = 0
        self.generation = 0
        self.suspended = None
        # What the environment gave when it paused this execution for a unit of higher
        # priority (Tick._pause); None while it is not paused.
        self.paused = None
        self.execution_id = uuid.uuid4().hex
        self.plan = []
        self.uses = frozenset()
        self.cameras = self.check = None
        self.fresh = None
        self.change = None


class Tick:
    """The tick of one kernel session (see the module docstring): `run(steps)` runs an
    execution on it, `judge()` has the rules judged, `stop()` ends it. `ticks` counts the
    steps it sent. `bound`: the most commands a second the environment takes (its periods
    are paced then), `step_seconds`: the time one step of it lasts (driving())."""

    def __init__(self, session):
        self.session = session
        self.bound, self.step_seconds = driving(getattr(session, "profile", None))
        self.period = 1.0 / self.bound if self.bound else POLL
        self.delay_ticks = delay_ticks(session.__dict__.get("reaction_delay_ms", 0.0), session.hz)
        self.ticks = self._period = 0
        self._line = collections.deque()
        self._entries = []
        # The units that took the embodiment from a lower one: each holds it until it ends.
        self._holders = []
        self._changed = threading.Condition()
        self._thread = None
        self._judge = False
        # A judgement that came due while the units were paused: made when they go on.
        self._held_judgement = False
        self._stopped = False
        self._due = None
        # Channels (see the module docstring): {name: channel}, empty when the embodiment
        # is one resource; who claims each, the execution that drives each, what each
        # entry holds down, and whether that changed since the last command went out.
        self._listened = 0.0
        self.channels = dict(getattr(session, "channels", None) or {})
        self._claimed = {}
        self._driving = {}
        self._held = {}
        self._dirty = False
        self._sent_held = None
        self._periods = _Periods(self.period) if self.bound else None

    # What the session calls.

    def judge(self):
        """Have the rules judged: one was set, what they read changed, or a rule's program
        ended. Nothing where no rule is judged (no rule, no tick)."""
        layer = getattr(self.session, "reactive", None)
        if layer is None or not (layer.reads_changes() or layer.next_due(0.0) is not None or self._listens()):
            return
        with self._changed:
            if not self._stopped:
                self._judge = True
                self._ensure_thread()
                self._changed.notify_all()

    def stop(self, timeout=5.0):
        """Stop ticking; a program entry still running ends with an error."""
        with self._changed:
            self._stopped = True
            self._changed.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        for entry in list(self._entries):
            entry.error = RuntimeError("the session closed while the execution ran")
            self._end(entry)

    def on_thread(self) -> bool:
        """Whether the caller runs on the tick (a controller, a guard)."""
        return self._thread is not None and threading.current_thread() is self._thread

    def run(self, steps):
        """Run the execution on the tick and return its trace, or raise its error.
        `steps`: its generator, or a function that makes it. Without channels the
        embodiment is held by priority: the execution of the unit of highest priority
        advances (the oldest among equals), and it ends a lower unit's execution where
        that is: with PREEMPTED and what it had done, and the model is told at once
        (_preempt). The unit that took the embodiment holds it until it ends: what lower
        units start meanwhile waits, and goes on then. A unit that said restart=True has
        its execution started again then instead (its trace counts the `restarts`).
        Where the environment pauses (its profile says "pauses"), the lower execution
        does not end: the environment holds what it was doing, and it goes on from there
        when the higher unit has ended (_pause, _resume)."""
        sys.audit("harness.execution")
        tree = self._tree()
        entry = _Entry(steps, spans.current(), tree.current() if tree is not None else None)
        inline = self.on_thread()
        with self._changed:
            if self._stopped:
                raise RuntimeError("the session's tick has stopped")
            self._entries.append(entry)
            if not inline:
                self._ensure_thread()
                self._changed.notify_all()
        if inline:
            entry.picked = True
            while not entry.done.is_set() and not self._stopped:
                self._wait_turn(idle=entry.suspended is not None)
                self._step([entry])
            if not entry.done.is_set():
                self._fail(entry, RuntimeError("the session closed while the execution ran"))
        else:
            self._wait_entry(entry, tree)
        if entry.error is not None:
            raise entry.error
        return entry.trace

    def _wait_entry(self, entry, tree):
        try:
            while not entry.done.wait(POLL):
                if tree is None:
                    continue
                with self._changed:
                    if (entry.picked and entry.paused is None) or tree.interruption(entry.owner, take=False) is None:
                        continue
                    self._entries.remove(entry)
                    entry.done.set()
                if entry.steps is not None:
                    entry.steps.close()
                tree.check(entry.owner)
        except BaseException:
            entry.cancelled = True
            raise

    # The loop.

    def _tree(self):
        """The session's tree of entries (runtime/execution/entries.py), if it has one."""
        return self.session.__dict__.get("_entry_tree")

    def _ensure_thread(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="harness-tick", daemon=True)
            self._thread.start()

    def _listens(self) -> bool:
        """Whether a handler waits for an event the environment itself reports (those are
        read on time, at the environment's rate)."""
        kinds = getattr(self.session, "observation_event_kinds", ())
        layer = getattr(self.session, "reactive", None)
        return bool(kinds) and layer is not None and any(
            rule.on in kinds for rule in layer.rules.copy().values())

    def _timed(self, now):
        """Seconds until the rules need the tick on time (a rule with a period, a handler
        of the environment's own events), None when none does or the episode has ended."""
        layer = getattr(self.session, "reactive", None)
        if layer is None or (self.session.state or {}).get("ended") or control.pause_requested():
            return None
        due = layer.next_due(now)
        if self._listens():
            listen = max(0.0, self._listened + layer.period - now)
            due = listen if due is None else min(due, listen)
        return due

    def _loop(self):
        while True:
            with self._changed:
                while not self._stopped:
                    if self._held_judgement and not control.pause_requested():
                        self._held_judgement, self._judge = False, True
                    if self._entries or self._dirty or self._line or self._judge:
                        break
                    due = self._timed(time.monotonic())
                    if due is not None and due <= 0:
                        break
                    # (While paused the rules are held: the pause is looked at again shortly.)
                    self._changed.wait(POLL if due is None and control.pause_requested() else due)
                if self._stopped:
                    return
                entries, lower = list(self._entries), []
                if not self.channels:
                    suspended = next((entry for entry in entries if entry.suspended is not None), None)
                    if suspended is not None:
                        # (An action that waits for its receipt keeps the embodiment.)
                        entries = [suspended]
                    elif entries:
                        top = max(entries, key=lambda entry: entry.priority)
                        if top.priority < self._held_at():
                            # A unit that took the embodiment still runs: lower ones wait for its end.
                            entries = []
                            self._changed.wait(POLL)
                        else:
                            lower = [entry for entry in entries if entry.priority < top.priority and entry.started
                                     and entry.trace is None and not entry.done.is_set()]
                            entries = [top]
                for entry in entries:
                    entry.picked = True
            for entry in lower:
                self._preempt(entry, entries[0])
            for entry in entries:
                if entry.paused is not None:
                    self._resume(entry)
            idle = bool(entries) and all(entry.suspended for entry in entries)
            if entries or self._line or self._dirty:
                self._wait_turn(idle=idle)
            self._step(entries)

    def _wait_turn(self, idle=False):
        if not self.bound and not idle:
            return
        now = time.monotonic()
        if self._due is not None and now < self._due:
            time.sleep(self._due - now)
            now = time.monotonic()
        self._due = self._due + self.period if self._due is not None and self._due + self.period > now \
            else now + self.period

    def _held_at(self) -> float:
        """The priority the embodiment is held with: the highest of the units that took it
        from a lower one and have not ended (nothing below it starts an execution)."""
        self._holders = [unit for unit in self._holders if getattr(unit, "running", False)]
        return max((_rank(unit) for unit in self._holders), default=float("-inf"))

    def hold(self, unit) -> None:
        """`unit` said it is uninterruptible: it holds the embodiment above every priority
        from now until it ends, between its executions too."""
        with self._changed:
            if unit not in self._holders:
                self._holders.append(unit)
            self._changed.notify_all()

    def holder(self):
        """The uninterruptible unit that holds the embodiment now (the oldest), or None."""
        with self._changed:
            return next((unit for unit in self._holders
                         if getattr(unit, "uninterruptible", False) and getattr(unit, "running", False)), None)

    def _preempt(self, lower, higher):
        """The unit of `higher` takes the embodiment: the execution `lower` ends where it
        is, with PREEMPTED and what it had done, and the unit of `higher` holds the
        embodiment until it ends. The `preempted` note tells the conversation at once,
        which tells the model: which unit (and rule) took it, from which unit and
        execution, and the state. An execution whose unit said restart=True is made anew
        when its turn comes again instead."""
        tree, trace = self._tree(), None
        by = getattr(higher.owner, "id", None)
        if higher.owner is not None and higher.owner not in self._holders:
            self._holders.append(higher.owner)
        if lower.paused is not None:
            return
        if getattr(self.session, "pauses", False) and not (lower.restart and lower.make is not None):
            self._pause(lower, higher)
            return
        try:
            with spans.under(lower.parent), _acting(tree, lower.owner):
                try:
                    lower.steps.throw(Preempted(by, higher.priority))
                except StopIteration as returned:
                    trace = returned.value
                else:
                    lower.steps.close()
        except BaseException as error:
            self._fail(lower, error)
            return
        self._discard_plan(lower)
        lower.fresh = lower.check = None
        if trace is not None and trace.event.kind != ev.PREEMPTED:
            # It ended by itself at that moment (a rule had just ended it): that is its end.
            lower.trace = trace
            self._end(lower)
            return
        spans.note("preempted", unit=getattr(lower.owner, "id", None), name=getattr(lower.owner, "name", None),
                   execution=getattr(trace, "skill", None), by=by, by_name=getattr(higher.owner, "name", None),
                   rule=getattr(higher.owner, "rule", None), priority=getattr(higher.owner, "priority", 0) or 0,
                   **({"uninterruptible": True} if getattr(higher.owner, "uninterruptible", False) else {}),
                   restart=bool(lower.restart and lower.make is not None), state=dict(self.session.state or {}))
        if lower.restart and lower.make is not None:
            lower.steps, lower.started = None, False
            lower.restarts += 1
            return
        if trace is None:
            self._fail(lower, RuntimeError("the execution was preempted and gave no trace"))
            return
        lower.trace = trace
        self._end(lower)

    def _pause(self, lower, higher):
        """The environment pauses: the unit of `higher` takes the embodiment and the
        execution `lower` stays where it is. The environment holds what it was doing
        (session._pause_execution); nothing of it is advanced until the higher unit has
        ended, and the model is not asked. The `call_paused` note records it."""
        try:
            lower.paused = {"held": self.session._pause_execution()}
        except BaseException as error:
            self._fail(lower, error)
            return
        spans.note("call_paused", unit=getattr(lower.owner, "id", None), name=getattr(lower.owner, "name", None),
                   by=getattr(higher.owner, "id", None), by_name=getattr(higher.owner, "name", None),
                   rule=getattr(higher.owner, "rule", None), priority=getattr(higher.owner, "priority", 0) or 0)

    def _resume(self, entry):
        """The unit that took the embodiment has ended: the paused execution goes on."""
        held, entry.paused = entry.paused["held"], None
        try:
            self.session._resume_execution(held)
        except BaseException as error:
            self._fail(entry, error)
            return
        spans.note("call_resumed", unit=getattr(entry.owner, "id", None), name=getattr(entry.owner, "name", None))

    def _end(self, entry):
        with self._changed:
            self._undrive(entry)
            if entry in self._entries:
                self._entries.remove(entry)
            self._cancel_receipt(entry, "execution ended")
            entry.done.set()
            self._changed.notify_all()

    def _cancel_receipt(self, entry, reason):
        action, entry.suspended = entry.suspended, None
        if action is None:
            return
        if action.refusal is None:
            action.pending.cancel(reason)
        else:
            identifier = action.refusal["approval"]["id"]
            with control._answered:
                control._physical.discard(identifier)
                control._answers.pop(identifier, None)
            spans.note("physical_cancel", id=identifier, reason=reason)

    # Channels (see the module docstring).

    def known(self, names) -> list:
        """`names` (a name or a list) as channel names of the embodiment (ValueError for
        one it does not declare)."""
        names = [names] if isinstance(names, str) else list(names or [])
        unknown = [name for name in names if name not in self.channels]
        if unknown:
            raise ValueError(f"no channel {unknown[0]!r}: the channels are {sorted(self.channels)}")
        return names

    def conflicts(self, entry, names, *, claiming=False) -> dict:
        """{channel: id of the entry that has it} for the channels of `names` that `entry`
        cannot use now: another entry drives or holds it, or claimed it (a claim of an
        entry above `entry` leaves it to the entries below)."""
        above = set(entry.lineage()) if entry is not None and not claiming else set()
        found = {}
        with self._changed:
            for name in names:
                claimed = self._claimed.get(name)
                if claimed is not None and claimed is not entry and claimed not in above:
                    found[name] = claimed.id
                    continue
                driving = self._driving.get(name)
                if driving is not None and driving.owner is not entry:
                    found[name] = getattr(driving.owner, "id", None)
                    continue
                for owner, held in self._held.items():
                    if owner is not entry and name in self.session._channels_of(held):
                        found[name] = owner.id
                        break
        return found

    def claim(self, entry, names) -> dict:
        """`entry` claims the channels `names` until it releases them or ends: {channel:
        holder id} of those it cannot have (then it claims none), else {}."""
        names = self.known(names)
        with self._changed:
            found = self.conflicts(entry, names, claiming=True)
            if not found:
                self._claimed.update({name: entry for name in names})
            return found

    def release(self, entry, names=None) -> None:
        """`entry` lets go of the channels `names` (None: all it has): its claims, and the
        keys and buttons it holds down on them, which go up at the next period."""
        with self._changed:
            names = set(self.channels if names is None else self.known(names))
            for name in names:
                if self._claimed.get(name) is entry:
                    del self._claimed[name]
            self._let_go(entry, names)
            self._changed.notify_all()

    def let_go(self, entries) -> None:
        """The keys and buttons `entries` hold down go up at the next period; their claims
        stay (a guard stopped what they do, runtime/execution/session.py)."""
        with self._changed:
            for entry in entries:
                self._let_go(entry, set(self.channels))
            self._changed.notify_all()

    def _let_go(self, entry, names) -> None:
        """The keys and buttons `entry` holds on the channels `names` go up."""
        held = self._held.get(entry, {})
        self._invalidate_release(entry, lambda fragment: self.session._mask(fragment, names))
        if (kept := self.session._mask(held, names)) != held:
            self._set_held(entry, kept)

    def board(self) -> dict:
        """Who has each channel now: {channel: {"entry", "how": claimed, driving or
        holding}}, None where nobody does (it is at its default)."""
        with self._changed:
            board = {name: None for name in self.channels}
            for owner, held in self._held.items():
                for name in self.session._channels_of(held):
                    board[name] = {"entry": owner.id, "how": "holding"}
            for name, execution in self._driving.items():
                board[name] = {"entry": getattr(execution.owner, "id", None), "how": "driving"}
            for name, owner in self._claimed.items():
                board[name] = {"entry": owner.id, "how": "claimed"}
            return board

    def _undrive(self, execution):
        for name in [name for name, driving in self._driving.items() if driving is execution]:
            del self._driving[name]

    def _step(self, entries):
        tree, session = self._tree(), self.session
        layer = getattr(session, "reactive", None)
        due = None
        deliver = False
        try:
            if self._periods is not None:
                self._periods.begin()
            waiting = any(entry.suspended for entry in entries)
            now = time.monotonic()
            timed = self._timed(now)
            timed = timed is not None and timed <= 0
            with self._changed:
                judged, self._judge = self._judge or timed, False
            if (self.bound and (entries or self._line)) or waiting or timed or (
                    self._line and layer is not None and layer._ordered((reactive.STOPS,))):
                session._observe()
            if session.state.get("ended"):
                self._line.clear()
                with self._changed:
                    for entry in self._entries:
                        entry.queued = 0
                        entry.plan.clear()
                        self._cancel_receipt(entry, "episode ended")
            budget = reactive.period(layer.budget_seconds) if layer is not None else contextlib.nullcontext()
            with budget:
                if tree is not None and getattr(session, "observation_event_kinds", ()):
                    self._listened = now
                    owner = getattr(entries[0].owner, "id", None) if entries else None
                    for observed in session._take_observation_events(session.state):
                        reactive.emit(tree, owner, "observe", observed, notice=True)
                if judged and control.pause_requested():
                    self._held_judgement = True
                elif judged and tree is not None and not session.state.get("ended"):
                    reactive.judge(session, tree)
                self._mark("observe")
                parts = []
                for entry in entries:
                    try:
                        if self._advance(entry, tree):
                            break
                    except BaseException as error:
                        self._fail(entry, error)
                    if entry.plan:
                        parts.append(_Part(entry, entry.plan.pop(0), last=not entry.plan))
                else:
                    action = self._decide(parts, entries, tree)
                    if action is not None:
                        self._line.append(action)
                        for part in action.parts:
                            if part.execution is not None:
                                part.execution.queued += 1
                    if self._line and not any(entry.suspended for entry in entries):
                        due = self._line[0] if self._line[0].due <= self._period else None
                        if due is not None and self.delay_ticks:
                            self._check_delayed(due, tree)
                        self._period += 1
                        deliver = True
            if deliver:
                if due is not None:
                    self._line.popleft()
                self._deliver(due)
        except BaseException as error:
            self._failed_period(entries, error)
            return
        for entry in entries:
            if entry.trace is not None and not entry.queued and entry.suspended is None:
                self._end(entry)
            elif not entry.plan:
                with self._changed:
                    self._undrive(entry)
        if self._periods is not None:
            self._periods.flush()

    def _decide(self, parts, entries, tree):
        if self.session.state.get("ended"):
            self._dirty = False
            return None
        if self.channels:
            command, parts, idle = self._admit(parts, entries, tree)
        else:
            command, idle = (parts[0].part if parts else None), None
        with self._changed:
            dirty, self._dirty = self._dirty, False
        if not (dirty or any(part.execution for part in parts)):
            return None
        cameras = self._cameras(parts) if self.channels else parts[0].cameras if parts else None
        return _Action(command, parts, cameras, self._period + self.delay_ticks, idle)

    @staticmethod
    def _cameras(parts):
        return sorted({camera for part in parts if part.last for camera in (part.cameras or ())}) or None

    def _admit(self, parts, entries, tree):
        session = self.session
        while True:
            held = self._holds()
            idle = self._idle()
            command = session._merge([part.sent for part in parts + held], idle)
            verdict = session._admit(command, commit=False)
            if verdict.command is not None:
                command = verdict.command
                break
            blamed = self._blame(parts, held, verdict.reasons[0])
            if blamed is None:
                break
            reply = {"executed": False, "shield": verdict.to_dict(), "state": dict(session.state)}
            self._settle(blamed, reply, tree)
            if blamed.execution is not None:
                parts.remove(blamed)
                with self._changed:
                    self._undrive(blamed.execution)
        return command, parts + held, idle

    def _check_delayed(self, action, tree):
        for part in action.parts:
            entry = part.execution
            if entry is None or part.generation != entry.generation or entry.check is None:
                continue
            if not self._execution_live(entry):
                continue
            try:
                with spans.under(entry.parent), _acting(tree, entry.owner):
                    stop = entry.check()
                if stop is not None:
                    self._discard_plan(entry)
                    entry.fresh = (stop, self.session.state)
            except BaseException as error:
                self._fail(entry, error)

    def _deliver(self, due):
        session = self.session
        if self._stopped:
            return
        parts = due.parts if due is not None else []
        with self._changed:
            live, inputs = self._delivery_inputs(parts)
        if parts and not live and not self.channels:
            return
        command = due.command if due is not None else None
        cameras = due.cameras if due is not None else None
        if self.channels:
            if due is None:
                command = session._still(self._sent_held or None)
            elif inputs != [part.sent for part in parts if part.sent]:
                command = session._merge(inputs, due.idle)
            if live != parts:
                cameras = self._cameras(live)
        elif not live or command is None:
            command = session._base_command(session.state)
        self._mark("decide")
        source = live[0].execution if len(parts) == len(live) == 1 and not self.channels else None
        attributable = source is not None and source.check is not None
        if self.channels and due is not None and session.profile.get("action_ids"):
            attributable = bool(live)
        action = due if attributable else None
        try:
            with spans.under(source.parent if source is not None else None), _acting(
                    self._tree(), source.owner if source is not None else None):
                reply = self._send(action, command, cameras)
                if isinstance(reply, dict):
                    reply = self._receipt(action, reply)
        except BaseException as error:
            self._failed_period([part.execution for part in live if part.execution is not None], error)
            return
        self.ticks += 1
        self._mark("send")
        if (action is not None and source is not None and isinstance(reply, dict)
                and not reply["executed"] and (request := reply.get("approval"))
                and (request.get("retry") is None or request.get("retry") == "host_tick"
                     and "sensitive_approval" in getattr(session.env, "host_controls", ())) and spans.connected()):
            with control._answered:
                control._physical.add(request["id"])
            action.refusal = reply
            action.deadline = time.monotonic() + WORKER_APPROVAL_SECONDS
            source.suspended = action
            spans.note("physical_request", request=request)
            return
        if not isinstance(reply, dict):
            if action is None or source is None:
                reply.cancel("the action has no attributable source")
                raise RuntimeError("Only an attributable action may wait for a receipt")
            action.pending = reply
            source.suspended = action
            return
        if self.channels and reply.get("executed"):
            session._admit(command, commit=True)
            self._sent_held = command
        for part in live:
            if part.execution is not None:
                try:
                    self._receive(part, reply)
                except BaseException as error:
                    self._fail(part.execution, error)

    def _send(self, action, command, cameras, *, approval_id=None):
        """Return a receipt, or on a trusted scheduler a deferred receipt for `action`.

        The continuation has nonblocking ready() and cancel(reason). finish(episode, step)
        applies and returns the final receipt (the original refusal on denial) or raises
        on unknown delivery. The host owns the payload, cursor validation and assent.
        """
        dispatch = getattr(self.session, "_dispatch_action", None)
        if action is not None and dispatch is not None:
            if approval_id is not None:
                return dispatch(action.id, command, cameras, approval_id=approval_id)
            return dispatch(action.id, command, cameras)
        return self.session._tick(command, cameras=cameras)

    def _receipt(self, action, reply):
        if action is None:
            return reply
        expected = None if self.channels and self.session.profile.get("action_ids") else action.id
        if reply.get("action_id", expected) != action.id:
            raise RuntimeError("The worker's receipt belongs to a different action; delivery is unverified")
        return {**reply, "action_id": action.id}

    def _delivery_inputs(self, parts):
        live, inputs = [], []
        for part in parts:
            sent, entry = part.sent, part.execution
            if entry is not None:
                entry.queued -= 1
                if part.generation != entry.generation or not self._execution_live(entry):
                    continue
            elif self._withdrawn(part.owner):
                continue
            else:
                sent = self._surviving_holds(part.owner, sent)
            live.append(part)
            if sent:
                inputs.append(sent)
        return live, inputs

    def _execution_live(self, entry):
        return not (entry.done.is_set() or self._interruption(entry, self._tree()))

    @staticmethod
    def _withdrawn(owner):
        return owner is not None and any(entry._cancel.is_set() for entry in owner.lineage())

    def _receive(self, part, reply):
        entry = part.execution
        if self._execution_live(entry) and not self._stopped:
            if "action_id" in reply and (record := getattr(self.session, "_record_receipt", None)):
                with spans.under(entry.parent):
                    record(part.part, reply)
            self._settle(part, reply)
        else:
            # A late receipt belongs to its original entry and is recorded once.
            detail = {"entry": getattr(entry.owner, "id", None), "span": entry.parent,
                      "action_id": reply.get("action_id"), "step": reply["state"]["step"],
                      "executed": reply["executed"], "verdict": reply["shield"]["verdict"],
                      "delivery": reply.get("delivery")}
            if record := getattr(self.session, "_record_late_receipt", None):
                record(detail)
            else:
                spans.note("late_receipt", **detail)

    def _settle(self, part, reply, tree=None):
        entry = part.execution
        if entry is None:
            with self._changed:
                self._let_go(part.owner, {part.channel} if part.channel is not None else set(self.channels))
            reactive.emit(tree, getattr(part.owner, "id", None), "hold", ev.input_refusal(
                reply, self.session.state.get("step")))
            return
        accepted = reply.get("executed")
        if not accepted:
            self._discard_plan(entry, refused=True)
        elif self.channels and part.last and any(part.part.get(field) for field in self.session.hold_fields):
            self._dirty = True
        if not accepted or part.last:
            entry.fresh = reply

    def _mark(self, part):
        if self._periods is not None:
            self._periods.mark(part)

    def _failed_period(self, entries, error):
        if not entries:
            print(f"harness tick: a period without an execution failed: {type(error).__name__}: {error}",
                  file=sys.stderr)
        for entry in entries:
            self._fail(entry, error)

    def _interruption(self, entry, tree, take=False):
        if entry.cancelled:
            return RuntimeError("the program that ran this execution was interrupted")
        if tree is not None and entry.owner is not None:
            return tree.interruption(entry.owner, take=take)

    def _advance(self, execution, tree):
        """Advance a generator, or take this period's delivery slot to finish a suspension."""
        if execution.done.is_set():
            return
        if execution.cancelled or execution.trace is None:
            if stop := self._interruption(execution, tree, take=True):
                raise stop
        if waiting := execution.suspended:
            session = self.session
            if self._stopped or session.state.get("ended") or control.pause_requested():
                raise RuntimeError("the suspended action was interrupted")
            with spans.under(execution.parent), _acting(tree, execution.owner):
                stop = execution.check()
            if stop is not None:
                self._cancel_receipt(execution, "stop guard vetoed the action")
                execution.fresh = (stop, session.state)
                return
            answer = None
            if waiting.refusal is not None:
                identifier = waiting.refusal["approval"]["id"]
                answer = control.wait_answer(identifier, poll=0)
                if answer is None and time.monotonic() < waiting.deadline:
                    return
            elif not waiting.pending.ready():
                return
            if self._stopped or control.pause_requested():
                raise RuntimeError("the suspended action was interrupted")
            if stop := self._interruption(execution, tree, take=True):
                raise stop
            try:
                with spans.under(execution.parent), _acting(tree, execution.owner):
                    if waiting.refusal is None:
                        reply = waiting.pending.finish(session.episode_id, session.state["step"])
                    else:
                        reply = waiting.refusal
                        sensitive = reply["approval"].get("retry") == "host_tick"
                        current = session.state["step"]
                        if answer is not None and not sensitive and current == reply["state"]["step"]:
                            session.env.call("physical", op="answer", episode_id=session.episode_id,
                                             id=identifier, accept=bool(answer.get("accept")),
                                             remember=answer.get("remember") or "once")
                        if answer and answer.get("accept") and (sensitive or current == reply["state"]["step"]):
                            if record := getattr(session, "_record_receipt", None):
                                record(waiting.command, reply)
                            reply = self._send(waiting, waiting.command, waiting.cameras,
                                               approval_id=identifier if sensitive else None)
                        else:
                            reason = (f"the user said no: {answer['reason']}" if answer and answer.get("reason")
                                      else "the user said no" if answer and not answer.get("accept")
                                      else "the input approval expired or the observation changed")
                            for check in reply["shield"]["reasons"]:
                                if check.get("approval"):
                                    check["reason"] += f" ({reason})"
                        self._cancel_receipt(execution, "input approval settled")
                    reply = self._receipt(waiting, reply)
                execution.suspended = None
                self._receive(waiting.parts[0], reply)
            except BaseException as error:
                self._fail(execution, error)
            return True
        if execution.trace is not None or execution.plan or execution.queued:
            return
        with self._changed:
            self._undrive(execution)
        for _ in range(4 if self.channels else 1):
            reply, execution.fresh = execution.fresh, None
            try:
                with spans.under(execution.parent), _acting(tree, execution.owner):
                    if execution.steps is None:
                        execution.steps = execution.make()
                    decided = execution.steps.send(reply) if execution.started else next(execution.steps)
            except StopIteration as returned:
                execution.trace = returned.value
                if execution.restarts and execution.trace is not None:
                    execution.trace.restarts = execution.restarts
                return
            execution.started = True
            command, cameras, *checks = decided
            execution.check = checks[0] if checks else None
            refused = self._plan(execution, command) if self.channels else None
            if not self.channels:
                execution.plan.append(command)
            if refused is None:
                execution.cameras = cameras
                return
            execution.fresh = refused

    def _plan(self, execution, command):
        """Take on an execution's command: its periods, the channels it drives, and a
        change of what its entry holds down. The reply that refuses it (a channel another
        entry has, an input of no channel), or None."""
        state = dict(self.session.state)
        try:
            uses, periods, change = self.session._plan(command)
        except Refused as refused:
            return _rejected(state, refused.reason)
        with self._changed:
            if found := self.conflicts(execution.owner, uses):
                return _rejected(state, {"check": "channel_conflict", "channels": found}, conflict={"channels": found})
            self._driving.update({name: execution for name in uses})
            execution.uses = frozenset(uses)
            execution.plan = list(periods)
            execution.change = self._apply(execution.owner, change) if change else None
        return None

    def _set_held(self, owner, held):
        previous = self._held.pop(owner, {})
        current = {kind: {item: previous.get(kind, {}).get(item) or object() for item in items}
                   for kind, items in held.items()}
        if any(current.values()):
            self._held[owner] = current
        self._dirty = True
        return current

    def _surviving_holds(self, owner, snapshot):
        current = self._held.get(owner, {})
        return {kind: {item: token for item, token in tokens.items() if token is current.get(kind, {}).get(item)}
                for kind, tokens in snapshot.items()}

    def _invalidate_release(self, owner, keep):
        for entry in self._entries:
            if entry.owner is owner and entry.change is not None:
                added, released = entry.change
                if released:
                    entry.change = added, keep(released)

    def _apply(self, owner, change):
        before = self._held.get(owner, {})
        requested = {kind: set(change.get(kind, ())) for kind in before.keys() | (change.keys() - {"op"})}
        down = change["op"] == "down"
        all_up = not down and not any(requested.values())

        def keep(fragment):
            return {} if all_up else {kind: set(items) - requested.get(kind, set()) for kind, items in fragment.items()}

        self._invalidate_release(owner, keep)
        if not down:
            after = self._set_held(owner, keep(before))
            return {}, {kind: tokens.keys() - after.get(kind, {}).keys() for kind, tokens in before.items()}
        after = self._set_held(owner, {kind: items | before.get(kind, {}).keys() for kind, items in requested.items()})
        return {kind: {item: token for item, token in tokens.items() if item not in before.get(kind, ())}
                for kind, tokens in after.items()}, {}

    def _discard_plan(self, entry, *, refused=False):
        entry.plan.clear()
        entry.generation += 1
        with self._changed:
            change, entry.change = entry.change, None
            if change is None:
                return
            added, released = change
            owner = entry.owner
            held = self._held.get(owner, {})
            remove = self._surviving_holds(owner, added)
            restore = released if refused and self._execution_live(entry) else {}
            # Undo restores an input with a fresh lifetime, never with the released token.
            self._set_held(owner, {kind: held.get(kind, {}).keys() - remove.get(kind, {}).keys() | restore.get(kind, set())
                                   for kind in held.keys() | restore.keys()})

    def _idle(self) -> set:
        """The channels nobody claims, drives or holds: at their default."""
        with self._changed:
            busy = set(self._claimed) | set(self._driving)
            for held in self._held.values():
                busy |= self.session._channels_of(held)
        return set(self.channels) - busy

    def _blame(self, parts, held, reason):
        """The part of a period's command a shield's reason is about: the newest
        execution's, else a hold, on the channel it names; the newest execution's, else the
        last hold, when it names none."""
        channel = reason.get("channel") or self.session._channel_of_reason(reason)
        for part in reversed(held + parts):
            uses = part.execution.uses if part.execution is not None else set()
            if channel is None or channel in self.session._channels_of(part.part) | uses:
                part.channel = channel
                return part
        return None

    def _holds(self):
        with self._changed:
            return [_Part(None, held, owner=owner) for owner, held in self._held.items()]

    def _fail(self, execution, error):
        if execution.done.is_set():
            return
        execution.error = error
        try:
            with _acting(self._tree(), execution.owner):
                if execution.steps is not None:
                    execution.steps.close()
        except BaseException as closing:
            if closing is not error:
                error.add_note(f"Closing the execution raised {type(closing).__name__}: {closing}")
        finally:
            self._discard_plan(execution)
            self._end(execution)


class _Action:
    """A sealed period, with its contributing sources and optional trusted completion."""

    def __init__(self, command, parts, cameras, due, idle):
        self.command, self.parts, self.cameras = command, parts, cameras
        self.due, self.idle = due, idle
        self.id = uuid.uuid4().hex
        self.pending = self.refusal = None


class Refused(Exception):
    """A command the session cannot take apart into its channels' periods (an input of no
    channel, a command it does not know): its `reason`, as a shield's."""

    def __init__(self, reason: dict):
        super().__init__(reason.get("reason") or reason.get("check"))
        self.reason = reason


class _Part:
    """One period's part of an execution's command (`last` when it is the command's last),
    or what a unit (`owner`) holds down."""

    def __init__(self, execution, part, last=False, owner=None):
        self.execution = execution
        self.generation = execution.generation if execution is not None else None
        self.part = part
        self.last = last
        self.owner = owner
        self.channel = None
        self.sent = part
        self.cameras = execution.cameras if execution is not None else None



def _rejected(state, reason, **detail):
    return {"executed": False, "state": state, **detail,
            "shield": {"verdict": "rejected", "command": None, "reasons": [reason]}}


def _acting(tree, owner):
    """Code inside runs as `owner`, the tree's entry an execution belongs to."""
    return tree.acting(owner) if tree is not None and owner is not None else contextlib.nullcontext()
