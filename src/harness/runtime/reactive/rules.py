"""Rules: what begins, raises or ends on a condition, and the handlers of events."""

from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass, field
import inspect
import math
import signal
import sys
import threading
import time
from typing import Any, Callable

from harness.core import spans
from harness.runtime import events as ev
from harness.runtime.events import Event, ExecutionTrace


# Guard actions a session takes itself: every embodiment stops and holds; an embodiment
# may add its own (opening a gripper, backing off).
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


# What a rule does when its condition comes to hold (Rule.does): it starts its program,
# raises an event, ends the executions in its scope, or it is the handler of an event.
STARTS, RAISES, STOPS, ANSWERS = "start", "event", "stop", "answer"
_UNSEEN = object()


@dataclass
class Rule:
    """A rule: the condition for when it begins (`begin(view, state)`), optionally the
    condition for when it ends (`end`), its priority, and the program it starts
    (`program`), which runs as a unit of that priority; optionally the shortest time it
    keeps going once begun (`min_seconds`) and the time before it may begin again
    (`again_seconds`). Without a program it raises an event (`action`: the event's name,
    or the Event its condition returns), ends a unit (its condition returns {"stop_entry":
    id}) or, with `stops`, ends the executions in its scope. It is judged when the parts of
    the view it reads (`reads`: dotted keys; None: any) change, or every `every` seconds.
    `on`: it is the handler of that event kind instead. `owner`: the unit it lives with
    (the model, or the program of the rule that set it)."""

    name: str
    begin: Callable
    end: Callable | None = None
    priority: int = 0
    program: Callable | None = None
    owner: str | None = None
    on: str | None = None
    action: str | None = None
    stops: bool = False
    kind: str = "rule"
    min_seconds: float = 0.0
    again_seconds: float = 0.0
    while_holds: bool = False
    reads: tuple | None = None
    every: float | None = None
    state: dict = field(default_factory=dict, repr=False)
    signal: str | Callable | None = None
    low: float | None = None
    high: float | None = None
    last_value: float | None = field(default=None, repr=False)
    triggered: int = 0
    library_origin: tuple | None = None
    # While it runs: the unit of its program, when it began, when it may begin again,
    # whether its condition held when last judged, what it read then, when it is next due.
    unit: Any = field(default=None, repr=False)
    began: float = field(default=0.0, repr=False)
    ready_at: float = field(default=0.0, repr=False)
    held: bool = field(default=False, repr=False)
    seen: Any = field(default=_UNSEEN, repr=False)
    next_at: float = field(default=0.0, repr=False)

    @property
    def does(self) -> str:
        return ANSWERS if self.on is not None else STOPS if self.stops else STARTS if self.program is not None else RAISES

    def describe(self) -> dict:
        """What the event it raises reports of it."""
        data = {"name": self.name, "kind": self.kind, "action": self.action, "triggered": self.triggered,
                **({"stops": False} if self.does == RAISES else {}),
                **({"priority": self.priority, "running": self.unit is not None} if self.does == STARTS else {})}
        if self.kind == "watch":
            data.update(signal=self.signal if isinstance(self.signal, str) else "<callable>",
                        low=self.low, high=self.high, value=self.last_value)
        return data


def _condition(callback, what="a rule's condition"):
    """`callback` as a condition of (view, state): one of (view) gets the view alone."""
    if not callable(callback):
        raise TypeError(f"{what} must be callable")
    try:
        parameters = [item for item in inspect.signature(callback).parameters.values()
                      if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD) and item.default is item.empty]
        binary = len(parameters) >= 2 or any(
            item.kind is item.VAR_POSITIONAL for item in inspect.signature(callback).parameters.values())
    except (TypeError, ValueError):
        binary = False
    return callback if binary else (lambda view, state: callback(view))


def _unary(callback):
    if not callable(callback):
        raise TypeError("a rule callback must be callable")
    return lambda view, state: callback(view)


def _read(view, path):
    value = view
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, (list, tuple)) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


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
    """The rules of one kernel session (see Rule). `min_period`: the shortest period a
    rule on time may ask for, `period` the one it gets when it names none (the
    environment's upper bound and default); `owner()` the unit a new rule lives with."""

    def __init__(self, budget_seconds: float, actions=(STOP, HOLD)):
        if not budget_seconds > 0:
            raise ValueError("Reactive budget must be positive")
        self.budget_seconds = budget_seconds
        self.actions = tuple(actions)
        self.rules: dict[str, Rule] = {}
        self._count = 0
        self.owner = None
        self.wake_observer = None
        self.library_boundary = threading.RLock()
        self.period = self.min_period = 1.0

    @property
    def guards(self) -> dict[str, Rule]:
        return {name: rule for name, rule in self.rules.copy().items() if rule.does in (STOPS, RAISES)}

    def _ordered(self, does) -> list[Rule]:
        return sorted((rule for rule in self.rules.copy().values() if rule.does in does),
                      key=lambda rule: -rule.priority)

    def rule(self, begin: Callable, program: Callable | None = None, *, name: str | None = None, priority=0,
             ends: Callable | None = None, min_seconds=0.0, again_seconds=0.0, while_holds=False, reads=None,
             every=None, raises: str | None = None, stops=False, action: str | None = None, on: str | None = None,
             kind: str = "rule", **detail) -> Rule:
        """Register a rule (see Rule), replacing a rule of the same name in place."""
        staging = getattr(_staging, "layers", None)
        if staging is not None and staging[0] is self:
            return staging[1].rule(begin, program, name=name, priority=priority, ends=ends, min_seconds=min_seconds,
                                   again_seconds=again_seconds, while_holds=while_holds, reads=reads, every=every,
                                   raises=raises, stops=stops, action=action, on=on, kind=kind,
                                   library_origin=staging[1].library_origin, **detail)
        if not callable(begin):
            raise TypeError("a rule begins on a condition: a function of (view) or (view, state)")
        if program is not None and not callable(program):
            raise TypeError("a rule's program is a function it starts")
        if program is not None and (raises or stops or on):
            raise ValueError("a rule with a program starts it; raising an event or stopping is a rule without one")
        if isinstance(priority, bool) or not isinstance(priority, (int, float)):
            raise ValueError(f"priority is a number, got {priority!r}")
        if raises is not None:
            _check_action(raises, self.actions, stops=False)
            action = raises
        for label, seconds in (("min_seconds", min_seconds), ("again_seconds", again_seconds)):
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
                raise ValueError(f"{label} is a number of seconds >= 0, got {seconds!r}")
        if every is not None:
            every = self.period if every is True else every
            if isinstance(every, bool) or not isinstance(every, (int, float)) or every < self.min_period - 1e-9:
                raise ValueError(f"every is a period in seconds, at least {self.min_period:g} here, got {every!r}")
        if reads is not None:
            reads = (reads,) if isinstance(reads, str) else tuple(str(item) for item in reads)
        if name is None:
            self._count += 1
            name = f"{kind}_{self._count}"
        if not isinstance(name, str) or not name:
            raise ValueError("A rule's name must be a nonempty string")
        owner = detail.pop("owner") if "owner" in detail else self._owner()
        self._retire(self.rules.get(name))
        rule = self.rules[name] = Rule(
            name, _condition(begin), _condition(ends, "a rule's end condition") if ends is not None else None,
            int(priority), program, owner, on, action, bool(stops), kind, float(min_seconds), float(again_seconds),
            bool(while_holds), reads, None if every is None else float(every), **detail)
        if self.wake_observer is not None:
            self.wake_observer()
        return rule

    def when(self, predicate: Callable, action: str, name: str | None = None, stops: bool = True) -> Rule:
        """A rule without a program: it ends the executions in its scope (`stops`), or
        raises the event `action` and lets them go on, when the predicate holds."""
        _check_action(action, self.actions, stops)
        return self.rule(_unary(predicate), name=name, action=action, stops=stops, kind="when")

    def watch(self, signal_name, low=None, high=None, event=None, name=None, stops=True) -> Rule:
        """The same for a number of the view that leaves [low, high]."""
        if low is None and high is None:
            raise ValueError("watch needs low, high, or both")
        if not (callable(signal_name) or isinstance(signal_name, str)):
            raise TypeError("watch signal must be a dotted observation key or a callable")
        action = event or f"{signal_name.upper().replace('.', '_') if isinstance(signal_name, str) else 'SIGNAL'}_OUT_OF_RANGE"
        _check_action(action, self.actions, stops)

        def outside(view, state):
            rule.last_value = value = read_signal(view, signal_name, rule.name, self.budget_seconds)
            return (low is not None and value < low) or (high is not None and value > high)
        rule = self.rule(outside, name=name, action=action, stops=stops, kind="watch",
                         signal=signal_name, low=low, high=high)
        return rule

    def on(self, event, handler) -> Rule:
        """Handle an event with handler(trace), passing it on with False."""
        owner = self._owner()
        return self.rule(_unary(handler), name=f"on {event} @{owner or 'e0'}", on=str(event), kind="on", owner=owner)

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
                self._retire(rule)
        if self.wake_observer is not None and staged.rules:
            self.wake_observer()

    @staticmethod
    def _retire(rule) -> None:
        """A rule that goes ends the program it started."""
        unit = getattr(rule, "unit", None)
        if unit is not None and unit.running:
            threading.Thread(target=unit.cancel, name=f"rule-{rule.name}", daemon=True).start()

    def remove(self, name) -> None:
        staging = getattr(_staging, "layers", None)
        if staging is not None and staging[0] is self:
            raise ValueError("library initialization cannot remove a live rule")
        self._retire(self.rules.pop(name, None))

    def clear_owner(self, owner: str) -> None:
        """The unit `owner` ended: the rules that lived with it go."""
        for name in [name for name, rule in list(self.rules.items()) if rule.owner == owner]:
            self.remove(name)

    def clear(self, names=None, does=(STOPS, RAISES, STARTS)) -> None:
        """Clear matching rules by name, or all matching rules."""
        names = list(self.rules) if names is None else [names] if isinstance(names, str) else names
        for name in names:
            if (rule := self.rules.get(name)) is not None and rule.does in does:
                self.remove(name)

    def _run(self, rule: Rule, view, condition=None):
        with self.library_boundary:
            if self.rules.get(rule.name) is not rule:
                return None
            result = call_reactive(rule.name, condition or rule.begin, view, rule.state,
                                   budget_seconds=self.budget_seconds)
        if result and rule.library_origin:
            spans.note("library_use", key=rule.library_origin[0], revision=rule.library_origin[2],
                       ok=True, rule=rule.name, testing=spans.in_test())
        return result

    def evaluate(self, observation: dict, scope=None) -> Rule | None:
        """The first rule that ends the executions of `scope` (the units whose rules watch
        it) and whose condition holds now: judged at every step of an execution."""
        for rule in self._ordered((STOPS,)):
            if (scope is None or rule.owner is None or rule.owner in scope) and self._run(rule, observation):
                rule.triggered += 1
                return rule
        return None

    # Rules that start a program or raise an event: judged when what they read changes, or on time.

    def next_due(self, now) -> float | None:
        """Seconds until a rule on time is due (0 when one is), None when there is none."""
        due = [rule.next_at for rule in self.rules.copy().values() if rule.every is not None and rule.on is None
               and not rule.stops]
        return max(0.0, min(due) - now) if due else None

    def reads_changes(self) -> bool:
        """Whether a rule is judged when the state changes."""
        return any(rule.every is None and rule.on is None and not rule.stops for rule in self.rules.copy().values())

    def due(self, view_of, now, stamp) -> list:
        """The rules to judge now, highest priority first: those on time whose period is
        over, those whose reading changed (`stamp` names the state and facts as they are
        now; `view_of()` gives the view), and those whose program ended."""
        found = []
        for rule in self._ordered((STARTS, RAISES)):
            if rule.every is not None:
                ready = now >= rule.next_at
                if ready:
                    rule.next_at = max(rule.next_at + rule.every, now + rule.every / 2)
            else:
                seen = stamp if rule.reads is None else tuple(_read(view_of(), path) for path in rule.reads)
                ready, rule.seen = seen != rule.seen, seen
            if ready or (rule.unit is not None and not rule.unit.running):
                found.append(rule)
        return found

    def advance(self, rule, view, now, start):
        """Judge `rule` on `view`: what its condition returned when it begins without a
        program (the caller raises the event or ends the unit), else None. Its program is
        started with `start(rule)`; its end condition (or, with while_holds, its begin
        condition no longer holding) ends the program once the shortest time is over."""
        if rule.unit is not None:
            if rule.unit.running:
                if now - rule.began < rule.min_seconds:
                    return None
                over = (self._run(rule, view, rule.end) if rule.end is not None
                        else rule.while_holds and not self._run(rule, view))
                if over:
                    spans.note("rule", name=rule.name, action="ended", unit=rule.unit.id)
                    self._retire(rule)
                return None
            rule.unit, rule.ready_at = None, now + rule.again_seconds
        holds = self._run(rule, view)
        if not holds:
            rule.held = False
            return None
        if (rule.held and rule.program is None) or now < rule.ready_at:
            return None
        rule.held = True
        rule.triggered += 1
        if rule.program is None:
            rule.ready_at = now + rule.again_seconds
            return holds
        rule.began = now
        rule.unit = start(rule)
        spans.note("rule", name=rule.name, action="began", unit=rule.unit.id, priority=rule.priority)
        return None

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
        """The unit `owner`'s handlers: {event kind: rule}."""
        return {rule.on: rule for rule in list(self.rules.values())
                if rule.does == ANSWERS and (rule.owner or "e0") == owner}


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


def judge(session, tree):
    """Judge the session's rules that are due (ReactiveLayer.due) on its view now: a rule
    that begins starts its program as a unit of its priority, or raises its event, or ends
    the unit its condition names; one whose end condition holds ends its program."""
    layer = getattr(session, "reactive", None)
    if layer is None or tree is None:
        return
    state = session.state
    made = {}

    def view_of():
        if "view" not in made:
            made["view"] = session._view(state, 0)
        return made["view"]

    now = time.monotonic()
    try:
        rules = layer.due(view_of, now, (id(state), session.facts.version))
    except Exception as error:
        fault = error if isinstance(error, ReactiveFault) else ReactiveFault("view", f"{type(error).__name__}: {error}")
        emit(tree, None, "rule", session._rule_event(fault, state))
        return
    for rule in rules:
        try:
            output = layer.advance(rule, view_of(), now, lambda rule: tree.spawn(
                rule.program, name=rule.name, rule=rule.name, priority=rule.priority))
        except ReactiveFault as fault:
            layer.remove(rule.name)
            emit(tree, rule.owner, "rule", session._rule_event(fault, state))
            continue
        except Exception as error:
            layer.remove(rule.name)
            emit(tree, rule.owner, "rule", session._rule_event(
                ReactiveFault(rule.name, f"{type(error).__name__}: {error}"), state))
            continue
        if output is None:
            continue
        event = _output(session, tree, rule, output, state)
        if event is not None:
            needs_model = isinstance(event.detail, dict) and event.detail.get("needs_model") is True
            emit(tree, rule.owner, "rule", event, notice=not (needs_model or event.kind == ev.REACTIVE_FAULT))


def _output(session, tree, rule, output, state):
    """What a rule without a program does when it begins: the event to raise (its action,
    or the Event its condition returned), or None once it ended the unit its condition named."""
    if rule.action is not None:
        return session._rule_event(rule, state)
    step = state.get("step")
    if isinstance(output, Event):
        return Event(output.kind, output.source, output.detail, step if output.tick is None else output.tick)
    identifier = output.get("stop_entry") if isinstance(output, dict) else None
    target = tree.entries.get(identifier) if isinstance(identifier, str) else None
    if target is None or target.kind != "program":
        return Event(ev.REACTIVE_FAULT, rule.name, {"reason": "expected an Event or a stop_entry of a program unit"}, step)
    target._cancel.set()
    session._let_go_under(target.id)
    threading.Thread(target=target.cancel, daemon=True).start()
