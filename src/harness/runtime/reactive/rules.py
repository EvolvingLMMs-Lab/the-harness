"""Evaluate guards, reflexes and event handlers around the tick's execution phase."""

from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass, field
import itertools
import math
import signal
import sys
import threading
import time
from typing import Any, Callable

from harness.core import spans
from harness.runtime import events as ev
from harness.runtime.events import Event, ExecutionTrace


# Guard actions a session takes itself: every embodiment stops and holds, a robot also opens
# its grippers (RobotSession), a game backs off (GameSession).
STOP, HOLD, OPEN_GRIPPER, BACK_OFF = "stop", "hold", "open_gripper", "back_off"
BUILTIN_ACTIONS = (STOP, HOLD, OPEN_GRIPPER)

_FORBIDDEN_PREFIXES = (
    "open", "os.", "shutil.", "socket.", "subprocess.", "urllib.", "http.", "ftplib.",
    "smtplib.", "ctypes.", "sqlite3.", "webbrowser.", "pty.", "fcntl.", "time.sleep", "harness.model_request", "harness.execution",
)
_restricted = threading.local()
_staging = threading.local()
# Looked up at import, before an isolated kernel refuses ctypes symbol lookups
# (runtime/safety/isolation.py): the watchdog raises overruns with it.
try:
    import ctypes

    _set_async_exc = ctypes.pythonapi.PyThreadState_SetAsyncExc
except (ImportError, AttributeError, PermissionError):
    _set_async_exc = None


class ReactiveFault(Exception):
    """A failed rule, identified by source and reason."""

    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


def _audit(event: str, _args) -> None:
    if getattr(_restricted, "active", False) and event.startswith(_FORBIDDEN_PREFIXES):
        raise PermissionError(f"reactive code may not perform '{event}'")


sys.addaudithook(_audit)


class _Overrun(BaseException):
    """Raised by the timer; a BaseException so broad excepts in user code miss it."""


class _Watchdog:
    """Interrupt Python callbacks at their deadline off the main thread."""

    def __init__(self):
        self._changed = threading.Condition()
        self._calls = {}  # token -> [deadline, thread id, fired]
        self._count = 0
        self._thread = None

    def arm(self, seconds: float) -> int:
        with self._changed:
            self._count += 1
            self._calls[self._count] = [time.monotonic() + seconds, threading.get_ident(), False]
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="harness-reactive-watchdog", daemon=True)
                self._thread.start()
            self._changed.notify()
            return self._count

    def disarm(self, token: int) -> None:
        with self._changed:
            call = self._calls.pop(token)
        if call[2]:
            # It fired as the call returned: take back the overrun not raised yet.
            restricted, _restricted.active = getattr(_restricted, "active", False), False
            try:
                _raise_in(call[1], None)
            finally:
                _restricted.active = restricted

    def _run(self):
        with self._changed:
            while True:
                now = time.monotonic()
                for call in self._calls.values():
                    if not call[2] and call[0] <= now:
                        call[2] = True
                        _raise_in(call[1], _Overrun)
                waiting = [call[0] for call in self._calls.values() if not call[2]]
                self._changed.wait(min(waiting) - now if waiting else None)


def _raise_in(thread_id: int, exception) -> None:
    """Raise `exception` in thread `thread_id` at its next bytecode (None: take one back)."""
    if _set_async_exc is not None:
        _set_async_exc(ctypes.c_ulong(thread_id), ctypes.py_object(exception) if exception is not None else None)


_watchdog = _Watchdog()


@contextmanager
def _deadline(seconds: float):
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        token = _watchdog.arm(seconds)
        try:
            yield
        finally:
            _watchdog.disarm(token)
        return

    def expire(_signum, _frame):
        raise _Overrun()

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def call_reactive(source: str, function: Callable, *args, budget_seconds: float) -> Any:
    """Run one reactive function under the audit restriction and time budget."""
    if getattr(_restricted, "active", False):
        return function(*args)
    allowance = getattr(_restricted, "allowance", None)
    if allowance is not None:
        budget_seconds = min(budget_seconds, allowance[0])
        if budget_seconds <= 0:
            raise ReactiveFault(source, "control period budget exhausted")
    started = time.perf_counter()
    _restricted.active = True
    try:
        # The hard timer is looser than the budget so the soft check reports the overrun.
        with _deadline(max(budget_seconds * 4, 0.001)):
            result = function(*args)
    except _Overrun:
        raise ReactiveFault(source, f"exceeded {budget_seconds * 1000:.1f} ms tick budget") from None
    except ReactiveFault:
        raise
    except Exception as error:
        raise ReactiveFault(source, f"{type(error).__name__}: {error}") from None
    finally:
        _restricted.active = False
        elapsed = time.perf_counter() - started
        if allowance is not None:
            allowance[0] -= elapsed
    if elapsed > budget_seconds:
        raise ReactiveFault(source, f"took {elapsed * 1000:.1f} ms; budget is {budget_seconds * 1000:.1f} ms")
    return result


def read_signal(observation: dict, signal_name: str | Callable, source: str, budget_seconds: float) -> float:
    """Read a finite signal from a dotted key or restricted callback."""
    if callable(signal_name):
        value = call_reactive(source, signal_name, observation, budget_seconds=budget_seconds)
    else:
        value = observation
        for part in signal_name.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif isinstance(value, (list, tuple)) and part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                raise ReactiveFault(source, f"signal '{signal_name}' is not in the observation")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReactiveFault(source, f"signal '{signal_name}' is not a finite number")
    return float(value)


# What a rule's output is (Rule.does), the priorities by name, and what an act may hold.
STOPS, RAISES, ACTS, ANSWERS = "stop", "event", "act", "answer"
PRIORITIES = {"hazard": 400, "combat": 300, "survival": 200, "assist": 100, "guard": 0}


@dataclass
class Rule:
    """A callback, its output kind and the entry whose work it watches."""

    name: str
    decide: Callable
    does: str
    priority: int = 0
    owner: str | None = None
    on: str | None = None
    action: str | None = None
    kind: str = "rule"
    state: dict = field(default_factory=dict, repr=False)
    signal: str | Callable | None = None
    low: float | None = None
    high: float | None = None
    last_value: float | None = field(default=None, repr=False)
    triggered: int = 0
    # An act's trace entry while it acts, its channels and the periods it acted.
    acting: str | None = field(default=None, repr=False)
    channels: tuple = ()
    periods: int = 0
    library_origin: tuple | None = None

    def describe(self) -> dict:
        """What the event it raises (or reflex_state) reports of it."""
        if self.does == ACTS:
            return {"name": self.name, "priority": self.priority, "owner": self.owner,
                    "acting": self.acting is not None, "periods": self.periods}
        data = {"name": self.name, "kind": self.kind, "action": self.action, "triggered": self.triggered,
                **({"stops": False} if self.does == RAISES else {})}
        if self.kind == "watch":
            data.update(signal=self.signal if isinstance(self.signal, str) else "<callable>",
                        low=self.low, high=self.high, value=self.last_value)
        return data


def _unary(callback):
    if not callable(callback):
        raise TypeError("a rule callback must be callable")
    return lambda view, state: callback(view)


_lanes = itertools.count(1)



@contextmanager
def _stage_rules(layer, replacing):
    if layer is None:
        yield None
        return
    staged = copy(layer)
    staged.rules = {}
    staged.wake_observer = None
    staged.library_origin = None
    staged.replacing = replacing
    _staging.layers = (layer, staged)
    try:
        yield staged
    finally:
        _staging.layers = None


class ReactiveLayer:
    def __init__(self, budget_seconds: float, actions=(STOP, HOLD)):
        if not budget_seconds > 0:
            raise ValueError("Reactive budget must be positive")
        self.budget_seconds = budget_seconds
        self.actions = tuple(actions)
        self.rules: dict[str, Rule] = {}
        self._count = 0
        self.owner = None
        self.taken = {}
        self.wake_observer = None
        self.library_boundary = threading.RLock()

    def _observes(self, stopping, events=()) -> bool:
        kinds = (STOPS, RAISES) if stopping else (RAISES,)
        return any(rule.does in kinds or (rule.does == ANSWERS and rule.on in events)
                   for rule in self.rules.copy().values())

    @property
    def guards(self) -> dict[str, Rule]:
        return {name: rule for name, rule in self.rules.copy().items() if rule.does in (STOPS, RAISES)}

    @property
    def reflexes(self) -> dict[str, Rule]:
        return {name: rule for name, rule in self.rules.copy().items() if rule.does == ACTS}

    def _ordered(self, does) -> list[Rule]:
        return sorted((rule for rule in self.rules.copy().values() if rule.does in does),
                      key=lambda rule: -rule.priority)

    def rule(self, decide: Callable, does: str, name: str | None = None, priority=0, action: str | None = None,
             on: str | None = None, kind: str = "rule", **detail) -> Rule:
        """Register a rule, replacing a rule of the same name in place."""
        staging = getattr(_staging, "layers", None)
        if staging is not None and staging[0] is self:
            return staging[1].rule(decide, does, name, priority, action, on, kind,
                                   library_origin=staging[1].library_origin, **detail)
        if not callable(decide):
            raise TypeError("a rule decides with a function of (view, state)")
        if does not in (STOPS, RAISES, ACTS, ANSWERS):
            raise ValueError(f"a rule does one of stop, event, act, answer, not {does!r}")
        if isinstance(priority, str):
            if priority not in PRIORITIES:
                raise ValueError(f"priority is a number or one of {sorted(PRIORITIES)}, got {priority!r}")
            priority = PRIORITIES[priority]
        if name is None:
            self._count += 1
            name = f"{kind}_{self._count}"
        if not isinstance(name, str) or not name:
            raise ValueError("A rule's name must be a nonempty string")
        _end_lane(self.rules.get(name), "removed")
        owner = detail.pop("owner") if "owner" in detail else self._owner()
        rule = self.rules[name] = Rule(name, decide, does, int(priority), owner, on, action, kind, **detail)
        if does in (RAISES, ANSWERS) and self.wake_observer is not None:
            self.wake_observer()
        return rule

    def when(self, predicate: Callable, action: str, name: str | None = None, stops: bool = True) -> Rule:
        """Register a guard that stops or raises an event when the predicate holds."""
        decide = _unary(predicate)
        _check_action(action, self.actions, stops)
        return self.rule(decide, STOPS if stops else RAISES, name, action=action,
                         kind="when")

    def watch(self, signal_name, low=None, high=None, event=None, name=None, stops=True) -> Rule:
        """Register a guard on a numeric signal, with an optional event name."""
        if low is None and high is None:
            raise ValueError("watch needs low, high, or both")
        if not (callable(signal_name) or isinstance(signal_name, str)):
            raise TypeError("watch signal must be a dotted observation key or a callable")
        action = event or f"{signal_name.upper().replace('.', '_') if isinstance(signal_name, str) else 'SIGNAL'}_OUT_OF_RANGE"
        _check_action(action, self.actions, stops)

        def outside(view, state):
            rule.last_value = value = read_signal(view, signal_name, rule.name, self.budget_seconds)
            return (low is not None and value < low) or (high is not None and value > high)
        rule = self.rule(outside, STOPS if stops else RAISES, name, action=action, kind="watch",
                         signal=signal_name, low=low, high=high)
        return rule

    def reflex(self, name, control, priority="survival") -> Rule:
        """A rule that acts: `control(view)` -> an act or None every period."""
        decide = _unary(control)
        if name in self.reflexes:
            raise ValueError(f"there is a reflex called {name!r} already")
        return self.rule(decide, ACTS, name, priority, kind="reflex")

    def on(self, event, handler) -> Rule:
        """Handle an event for this entry, passing it up on False."""
        owner = self._owner()
        return self.rule(_unary(handler), ANSWERS, f"on {event} @{owner or 'e0'}",
                         on=str(event), kind="on", owner=owner)

    def _owner(self):
        return self.owner() if self.owner is not None else None

    def _publish_rules(self, staged):
        previous = self.rules
        self.rules = {**{name: rule for name, rule in previous.items()
                         if not rule.library_origin or rule.library_origin[0] not in staged.replacing},
                      **staged.rules}
        self._count = staged._count
        for name, rule in previous.items():
            if self.rules.get(name) is not rule:
                _end_lane(rule, "removed")
        if self.wake_observer is not None and any(rule.does in (RAISES, ANSWERS) for rule in staged.rules.values()):
            self.wake_observer()

    def remove(self, name) -> None:
        staging = getattr(_staging, "layers", None)
        if staging is not None and staging[0] is self:
            raise ValueError("library initialization cannot remove a live rule")
        _end_lane(self.rules.pop(name, None), "removed")

    def clear_owner(self, owner: str) -> None:
        """The entry `owner` ended: its rules go, but its acts."""
        for name in [name for name, rule in list(self.rules.items()) if rule.owner == owner and rule.does != ACTS]:
            self.remove(name)

    def clear(self, names=None, does=(STOPS, RAISES)) -> None:
        """Clear matching rules by name, or all matching rules."""
        names = list(self.rules) if names is None else [names] if isinstance(names, str) else names
        for name in names:
            if (rule := self.rules.get(name)) is not None and rule.does in does:
                self.remove(name)

    def _run(self, rule: Rule, view):
        with self.library_boundary:
            if self.rules.get(rule.name) is not rule:
                return None
            result = call_reactive(rule.name, rule.decide, view, rule.state, budget_seconds=self.budget_seconds)
        if result and rule.library_origin:
            spans.note("library_use", key=rule.library_origin[0], revision=rule.library_origin[2],
                       ok=True, rule=rule.name, testing=spans.in_test())
        return result

    def evaluate(self, observation: dict, scope=None) -> Rule | None:
        for rule in self._ordered((STOPS,)):
            if (scope is None or rule.owner is None or rule.owner in scope) and self._run(rule, observation):
                rule.triggered += 1
                return rule
        return None

    def firing(self, observation: dict, stopping=True, *, outputs=False):
        fired = [(rule, result) for rule in self._ordered((STOPS, RAISES) if stopping else (RAISES,))
                 if (result := self._run(rule, observation))]
        for rule, _ in fired:
            rule.triggered += 1
        return fired if outputs else [rule for rule, _ in fired]

    def decide(self, view, session):
        """Resolve reflex contributions and faults in priority order."""
        acts, taken, faults = [], {}, []
        goal = view.get("goal") or {}
        for rule in self._ordered((ACTS,)):
            view["out"] = session._merge([session._mask(goal, set(taken)), *(part for _, part in acts)], ())
            try:
                output = self._run(rule, view)
                part, take = session._part(rule.name, output, taken)
                channels = session._channels_of(part) | take if part is not None else set()
            except (ReactiveFault, ValueError) as error:
                faults.append((rule, error if isinstance(error, ReactiveFault) else ReactiveFault(rule.name, str(error))))
                continue
            if part is None or not channels or (take and channels & set(taken)):
                _end_lane(rule, "done")
                continue
            taken.update({name: rule.name for name in take})
            acts.append((rule, part))
            rule.periods += 1
            if rule.acting is None or set(rule.channels) != channels:
                _end_lane(rule, "done")
                rule.channels, rule.acting = tuple(sorted(channels)), f"r{next(_lanes)}"
                spans.record("entry_start", id=rule.acting, parent="e0", name=rule.name, kind="reflex",
                             claims=list(rule.channels), why=(output or {}).get("why"))
        for rule, _ in faults:
            self.remove(rule.name)
        self.taken = dict(taken)
        return acts, taken, faults

    def answer(self, lineage, trace, acting, faulted=None) -> bool:
        """Offer an event to the nearest handler first."""
        for owner in lineage:
            rule = self.answers(owner).get(trace.event.kind)
            if rule is None:
                continue
            try:
                with acting(owner):
                    answer = self._run(rule, trace)
                    if answer is False:
                        continue
            except ReactiveFault as fault:
                if faulted is None:
                    raise
                if self.rules.get(rule.name) is rule:
                    self.remove(rule.name)
                faulted(owner, fault)
            else:
                rule.triggered += 1
            return True
        return False

    def answers(self, owner) -> dict:
        """The entry `owner`'s answers: {event kind: rule}."""
        return {rule.on: rule for rule in list(self.rules.values())
                if rule.does == ANSWERS and (rule.owner or "e0") == owner}


def _end_lane(rule, status):
    if rule is not None and rule.acting is not None:
        spans.record("entry_end", id=rule.acting, status=status)
        rule.acting, rule.channels = None, ()


def _check_action(action, actions=(STOP, HOLD), stops=True) -> None:
    if not isinstance(action, str) or not action:
        raise ValueError(f"Guard action must be {', '.join(repr(a) for a in actions)}, or an event name")
    if not stops and action in actions:
        raise ValueError(f"A guard that only watches raises an event; {action!r} is an action that stops")
    if action not in actions and not action.replace("_", "").isalnum():
        raise ValueError(f"Event names must be identifiers like EMPTY_GRASP, got {action!r}")


@contextmanager
def period(budget_seconds):
    previous = getattr(_restricted, "allowance", None)
    _restricted.allowance = [budget_seconds]
    try:
        yield
    finally:
        _restricted.allowance = previous


def fault_event(fault, step, **detail):
    return Event(ev.REACTIVE_FAULT, fault.source, {"reason": fault.reason, **detail}, step)


def emit(tree, owner, skill, event, *, notice=False):
    if tree is not None:
        tree.raise_event(tree.get(owner), ExecutionTrace(skill, {}, event.tick, event.tick, event), notice=notice)


def apply(session, tree, *, busy=False, goal=None, channels=()):
    """Apply the outcomes of the observation or merged-input phase."""
    layer = getattr(session, "reactive", None)
    if layer is None:
        return [], {}
    state = session.state
    acts, taken = [], {}
    if goal is None:
        skill, outcomes = "idle", _observed(session, tree, layer, state, busy)
    elif layer.reflexes:
        view = session._reactive_view(state, 0)
        view["goal"] = {**goal, "channels": list(channels)}
        acts, taken, faults = layer.decide(view, session)
        skill = "reflex"
        outcomes = [(rule.owner, False, session._rule_event(fault, state)) for rule, fault in faults]
    else:
        layer.taken.clear()
        return acts, taken
    for owner, release, event in outcomes:
        if release:
            session._let_go_under(owner)
        needs_model = isinstance(event.detail, dict) and event.detail.get("needs_model") is True
        emit(tree, owner, skill, event, notice=not (release or needs_model or event.kind == ev.REACTIVE_FAULT))
    return acts, taken


def _observed(session, tree, layer, state, busy):
    before, guards = session.__dict__.get("_idle_fired") or set(), layer.guards
    try:
        fired = layer.firing(session._reactive_view(state, 0), not busy, outputs=True) if guards else []
    except Exception as error:
        fault = error if isinstance(error, ReactiveFault) else ReactiveFault("view", f"{type(error).__name__}: {error}")
        names = {fault.source}
        stop = guards.get(fault.source)
        outcomes = [] if fault.source in before else [(None, stop is not None and stop.does == STOPS,
                                                        session._rule_event(fault, state))]
    else:
        names = {rule.name for rule, _ in fired}
        outcomes = [(rule.owner, rule.does == STOPS, event) for rule, output in fired
                    if rule.name not in before and (event := _output(session, tree, rule, output, state)) is not None]
    session._idle_fired = names | {name for name in before if busy and name in guards and guards[name].does == STOPS}
    return outcomes


def _output(session, tree, rule, output, state):
    if rule.action is not None:
        return session._rule_event(rule, state)
    step = state.get("step")
    if isinstance(output, Event):
        return Event(output.kind, output.source, output.detail, step if output.tick is None else output.tick)
    identifier = output.get("stop_entry") if isinstance(output, dict) else None
    target = tree.entries.get(identifier) if isinstance(identifier, str) else None
    if target is None or target.kind != "program" or tree.get(rule.owner) not in target.lineage():
        return Event(ev.REACTIVE_FAULT, rule.name, {"reason": "expected an Event or a stop_entry in scope"}, step)
    target._cancel.set()
    session._let_go_under(target.id)
    threading.Thread(target=target.cancel, daemon=True).start()
