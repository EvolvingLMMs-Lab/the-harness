"""The reactive layer: one tree of reflexes.

What acts without the model is one tree, empty at first. A node is a situation: it says
when the agent is in it (`when`: a condition of the view, or the name of an event) and what
answers it (`do`: a program, the name of an event to raise, an action that ends what runs,
or nothing). Any node may have nodes under it: the narrower situations within it. Four
statements are the whole of it:

    1. A node under another has its turn only while that one's condition holds, and before
       it: while a node under it is answering, the node itself does not act. What the node
       does itself answers what is in its situation and in none of those under it. So a
       node is complete when it is set, and the tree grows by putting nodes under nodes,
       which changes none of them.
    2. Among the nodes at one place the earlier (the higher priority, then the older) takes
       the environment from the later, and gives it back when it is done.
    3. A node has done its work when the situation it answers is over: its program is a
       unit whose completion condition is that the node's condition no longer holds
       (runtime/execution/entries.py: how a unit ended and whether its work is done are two
       things, for every unit). When its program ends and the situation is not over, or
       the program fails, what comes after it has the environment: a later node at that
       place whose condition holds, then what the node above does itself; when nothing
       has, the model is told what the program did (the event REFLEX_FAILED), once until
       the node has done its work again.
    4. A node that tells the model (`do` an event's name) has its turn like any other: it
       tells when neither a node before it at its place nor one under it is answering.

A node's program runs as a unit whose priority is the node's own priority (rank()):
the units' priorities are how the tick lets the earlier take the environment from the later
(runtime/tick.py: the later call is paused where the environment pauses, else ended, and
its node begins again). Every node's place is above the model's own programs: a reflex
takes the environment from them.

The tree is judged when the state or the facts change, when one of its programs ends, and
on time for the nodes that ask (`every`). The units it starts are its own business: their
ends are recorded and start no call of the model.
"""

from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass, field
import inspect
import threading
import time
from types import CodeType, FunctionType
from typing import Any, Callable

from harness.core import spans
from harness.runtime import events as ev
from harness.runtime.events import Event, ExecutionTrace
from harness.runtime.reactive.rules import HOLD, STOP, NotJudged, ReactiveFault, call_reactive

# A node whose program failed does not begin again before this many seconds, and no node
# begins more often than once in RESTART_SECONDS: the tree does not spin on a program.
FAILED_AGAIN_SECONDS = 2.0
RESTART_SECONDS = 0.2
# A node's condition that took longer than the budget this many times in a row is a fault:
# the node goes and the model is told. Once is a moment of the machine, not of the node.
LATE_TIMES = 3

_staging = threading.local()
_UNSEEN = object()
# What a turn is told of a tree with no node in it.
NO_REFLEXES = "Reflex tree: empty (nothing acts without you)"
# The most nodes one reflexes() call gives, and the most changed nodes a turn is told of.
LISTED, TOLD = 50, 10


def _trial_text(trial) -> str:
    """How a node's line says what its trial showed: nothing where it worked or where the
    node was set without one."""
    if not isinstance(trial, dict):
        return ""
    if not trial.get("tried"):
        return ", not tried"
    worked = trial.get("turn") and trial.get("done") is not False and not trial.get("error")
    return "" if worked else ", did not work in its trial"


_ABSENT = object()


def _same_code(a, b) -> bool:
    """Whether two code objects are the same program: what they execute, the names they use
    and their constants, wherever in a source they stand."""
    if (a.co_code != b.co_code or a.co_names != b.co_names or a.co_varnames != b.co_varnames
            or a.co_freevars != b.co_freevars or a.co_argcount != b.co_argcount
            or a.co_kwonlyargcount != b.co_kwonlyargcount or len(a.co_consts) != len(b.co_consts)):
        return False
    for x, y in zip(a.co_consts, b.co_consts):
        if isinstance(x, CodeType) or isinstance(y, CodeType):
            if not (isinstance(x, CodeType) and isinstance(y, CodeType) and _same_code(x, y)):
                return False
        elif type(x) is not type(y) or x != y:
            return False
    return True


def _names(code):
    yield from code.co_names
    for value in code.co_consts:
        if isinstance(value, CodeType):
            yield from _names(value)


def same(a, b, seen=None) -> bool:
    """Whether two values a node is made of (its condition, its program, what those use) are
    the same: for functions the same code, with the same defaults and the same things behind
    the names they use, each compared in this way; for data, equal."""
    seen = set() if seen is None else seen
    if a is b:
        return True
    a = inspect.unwrap(a) if callable(a) else a
    b = inspect.unwrap(b) if callable(b) else b
    if a is b:
        return True
    if isinstance(a, FunctionType) and isinstance(b, FunctionType):
        if (id(a), id(b)) in seen:
            return True
        seen.add((id(a), id(b)))
        if not _same_code(a.__code__, b.__code__):
            return False
        if not same(a.__defaults__, b.__defaults__, seen) or not same(a.__kwdefaults__, b.__kwdefaults__, seen):
            return False
        for x, y in zip(a.__closure__ or (), b.__closure__ or ()):
            try:
                if not same(x.cell_contents, y.cell_contents, seen):
                    return False
            except ValueError:  # (An empty cell on either side.)
                return False
        for name in set(_names(a.__code__)):
            x, y = a.__globals__.get(name, _ABSENT), b.__globals__.get(name, _ABSENT)
            # (A name neither or only one has is an attribute or a builtin, not something of theirs.)
            if x is not _ABSENT and y is not _ABSENT and not same(x, y, seen):
                return False
        return True
    if isinstance(a, FunctionType) or isinstance(b, FunctionType) or type(a) is not type(b):
        return False
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(same(x, y, seen) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[key], b[key], seen) for key in a)
    try:
        return bool(a == b)
    except Exception:
        return False


def told(nodes: dict, before: dict) -> str:
    """What a turn of the model is told of the tree: how many nodes act in it, and the
    lines (Reflexes.digest) that differ from `before`, what it was told last. Nothing when
    no line differs and every node has had its turn and acts itself: a line that says only
    that nothing changed tells nothing."""
    if not nodes:
        return NO_REFLEXES
    changed = [f"  {name}: {line}" for name, line in nodes.items() if before.get(name) != line]
    count = f"{len(nodes)} node" + ("" if len(nodes) == 1 else "s")
    # A node that has never had its turn has not been seen to work.
    never = sum(1 for line in nodes.values() if line.startswith("began 0,") or line.endswith(("; 0 times", "; began 0")))
    if never:
        count += f", {never} of them never had {'its' if never == 1 else 'their'} turn"
    # A node that only tells acts on nothing itself: what it sees waits for the model's reply.
    only = sum(1 for line in nodes.values() if line.startswith("tells you") and " and ends what runs" not in line)
    if only:
        count += f", {only} of them only tell{'s' if only == 1 else ''} you"
    # What the trials showed (set_reflex test=).
    untried = sum(1 for line in nodes.values() if line.endswith(", not tried"))
    failed = sum(1 for line in nodes.values() if line.endswith(", did not work in its trial"))
    if untried:
        count += f", {untried} not tried"
    if failed:
        count += f", {failed} did not work in {'its' if failed == 1 else 'their'} trial"
    if not changed:
        if not never and not only and not untried and not failed:
            return ""
        return f"Reflex tree: {count}, as you were last told (reflexes() lists them)"
    more = f"\n  ... {len(changed) - TOLD} more changed: reflexes()" if len(changed) > TOLD else ""
    return (f"Reflex tree: {count}; changed since you were last told:\n"
            + "\n".join(changed[:TOLD]) + more)


@dataclass
class Reflex:
    """A node of the tree: its `name`; `when` it has its turn (a condition of the view) or
    the `event` it answers; what it does itself: `do` (a program), or `action` (an event to
    raise, or one of the environment's actions that end what runs), or neither (then only
    the nodes under it answer); the node it is `under` (None: the top); its own `priority`; `every`
    seconds its condition is judged (None: when the state or the facts change);
    `again_seconds` before it may begin again after its program ended; `ends`: the unit its
    program takes the environment from is ended there (and the model told), where it would
    otherwise be resumed when the program is over; of a node that tells, what runs is ended
    with the event it tells."""

    name: str
    when: Callable | None = None
    event: str | None = None
    do: Callable | None = None
    action: str | None = None
    stops: bool = False
    under: str | None = None
    priority: int = 0
    every: float | None = None
    again_seconds: float = 0.0
    order: int = 0
    library_origin: tuple | None = None
    ends: bool = False
    # What its trial showed (session.set_reflex test=): {"tried": True, "turn", "seconds", "done",
    # "error"} or {"tried": False, "why"}; None for a node set without one. While the trial
    # runs, `trying`; `acted`: the model was told of the first time its program did its work
    # by itself.
    trial: Any = field(default=None, repr=False)
    trying: bool = field(default=False, repr=False)
    acted: bool = field(default=False, repr=False)
    # What went wrong with its condition (Reflexes._faulted): the reason of the last time,
    # how often, the reasons the model was told, and the one it is to be told next. A node
    # whose condition was too slow time after time is `set_aside`: it stays in the tree and
    # is not judged until it is set again.
    fault: Any = field(default=None, repr=False)
    faults: int = 0
    fault_told: set = field(default_factory=set, repr=False)
    fault_tell: Any = field(default=None, repr=False)
    set_aside: bool = False
    # As it stands: the unit of its program, when it may begin again, whether its condition
    # held when last judged, whether it raised its event since that came to hold, when it
    # is next due, how often it acted, the program of higher priority that kept it from acting,
    # and whether the model was told of its failure since it last succeeded.
    unit: Any = field(default=None, repr=False)
    ready_at: float = field(default=0.0, repr=False)
    holds: Any = field(default=_UNSEEN, repr=False)
    raised: bool = field(default=False, repr=False)
    next_at: float = field(default=0.0, repr=False)
    triggered: int = 0
    kept_by: Any = field(default=None, repr=False)
    told: bool = field(default=False, repr=False)
    # The end report of its program's last run, and how often a run did its work and did not.
    last: Any = field(default=None, repr=False)
    did: int = 0
    did_not: int = 0
    # How often in a row its condition took longer than the budget, and whether it waits to
    # be judged (the period's budget was used up before its turn).
    late: int = field(default=0, repr=False)
    waits: bool = field(default=False, repr=False)

    @property
    def does(self) -> str:
        if self.do is not None:
            return "answers an event with its program" if self.event else "starts its program"
        if self.action is not None:
            return ("ends what runs" if self.stops else
                    "raises an event and ends what runs" if self.ends else "raises an event")
        return "holds the nodes under it"

    def describe(self) -> dict:
        """What the event it raises reports of it."""
        return {"name": self.name, "action": self.action, "triggered": self.triggered,
                **({} if self.stops or self.ends else {"stops": False})}


def _takes_argument(function) -> bool:
    try:
        return any(item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD, item.VAR_POSITIONAL)
                   and item.default is item.empty for item in inspect.signature(function).parameters.values())
    except (TypeError, ValueError):
        return False


@contextmanager
def stage(layer, replacing):
    """While a library entry is loaded: the nodes it sets are gathered in a copy of the
    layer (given), and publish() puts them into the tree, in place of the nodes the entries
    `replacing` had set."""
    if layer is None:
        yield None
        return
    staged = copy(layer)
    staged.nodes = {}
    staged.wake_observer = None
    staged.library_origin = None
    staged.replacing = replacing
    staged.live = layer
    staged.kept = {}
    _staging.layers = (layer, staged)
    try:
        yield staged
    finally:
        _staging.layers = None


class Reflexes:
    """The tree of one kernel session (see the module docstring). `min_period`: the shortest
    period a node may ask for, `period` the one `every=True` gets (the environment's upper
    bound and default); `view()`: the session's view now, for a node that answers an event."""

    def __init__(self, budget_seconds: float, actions=(STOP, HOLD)):
        if not budget_seconds > 0:
            raise ValueError("Reactive budget must be positive")
        self.budget_seconds = budget_seconds
        self.actions = tuple(actions)
        self.nodes: dict[str, Reflex] = {}
        self._count = 0
        self.wake_observer = None
        self.view = None
        self.library_boundary = threading.RLock()
        self.library_origin = None
        # Whether the model is told of the first time a node's program does its work by itself
        # (where nodes are set with their trials: session.set_reflex).
        self.tell_first = False
        self.period = self.min_period = 1.0
        # What the last judgement left: the state and facts it saw, whether the tree changed
        # since, and when a node that waits for its time wants the tree judged again.
        self.stamp, self.changed, self.wake_at = None, True, None

    # Setting and removing nodes.

    def set(self, name, when, do=None, *, under=None, priority=0, every=None, again_seconds=0.0,
            ends=False) -> str:
        """Put the node `name` into the tree, in place of a node of that name (see Reflex;
        `when`: a function of the view, or the name of an event; `do`: a program, or the
        name of an event to raise, or an action of the environment that ends what runs
        ("stop"), or None: then only the nodes under it answer). Its name."""
        staging = getattr(_staging, "layers", None)
        if staging is not None and staging[0] is self:
            return staging[1].set(name, when, do, under=under, priority=priority, every=every,
                                  again_seconds=again_seconds, ends=ends)
        if not isinstance(name, str) or not name:
            raise ValueError("a reflex's name is a nonempty string")
        event = None
        if isinstance(when, str):
            if not when.replace("_", "").isalnum():
                raise ValueError(f"an event's name is an identifier like LOW_BATTERY, got {when!r}")
            event, when = when, None
            if not callable(do):
                raise ValueError("a reflex that answers an event does it with a program: do=function")
        elif not callable(when):
            raise TypeError("set_reflex(name, when, do): `when` is a function of the view, or the name of an event")
        action, stops = None, False
        if isinstance(do, str):
            if do not in self.actions and not do.replace("_", "").isalnum():
                raise ValueError(f"`do` as text is {', '.join(repr(a) for a in self.actions)} or the name of an "
                                 f"event like EMPTY_GRASP, got {do!r}")
            action, stops, do = do, do in self.actions, None
        elif do is not None and not callable(do):
            raise TypeError("`do` is a program (a function), the name of an event, an action that ends what runs, "
                            "or None (then only the nodes under it answer)")
        if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0:
            raise ValueError(f"priority is a whole number, 0 or more, got {priority!r}")
        if isinstance(again_seconds, bool) or not isinstance(again_seconds, (int, float)) or again_seconds < 0:
            raise ValueError(f"again_seconds is a number of seconds >= 0, got {again_seconds!r}")
        if not isinstance(ends, bool):
            raise ValueError(f"ends is True or False, got {ends!r}")
        if ends and ((do is None and action is None) or stops):
            raise ValueError("ends=True goes with a program or with the name of an event to tell: it says that "
                             "what runs is ended when the node's turn comes")
        if every is not None:
            every = self.period if every is True else every
            if isinstance(every, bool) or not isinstance(every, (int, float)) or every < self.min_period - 1e-9:
                raise ValueError(f"every is a period in seconds, at least {self.min_period:g} here, got {every!r}")
        known = {**getattr(getattr(self, "live", None), "nodes", {}), **self.nodes}
        if under is not None:
            above = known.get(under)
            if above is None:
                raise ValueError(f"no reflex is named {under!r}: the node a reflex is under is set first")
            if above.event is not None or above.stops:
                # (Neither is a situation the agent is in for a while, which others could narrow.)
                raise ValueError(f"{under!r} answers an event or ends what runs: nodes go under a node whose "
                                 "`when` is a condition")
            while above is not None:
                if above.name == name:
                    raise ValueError(f"{name!r} cannot be under itself")
                above = known.get(above.under) if above.under is not None else None
        old = known.get(name)
        if (event is not None or stops) and any(node.under == name for node in known.values()):
            raise ValueError(f"{name!r} has nodes under it: its `when` stays a condition, and it does not end what runs")
        self._count += 1
        self._retire(self.nodes.get(name))
        self.nodes[name] = Reflex(name, when, event, do, action, stops, under, priority,
                                  None if every is None else float(every), float(again_seconds),
                                  old.order if old is not None else self._count, self.library_origin, ends)
        self._touched()
        return name

    def drop(self, names=None) -> None:
        """Remove the nodes `names` (a name or a list; None: all) with the nodes under them;
        the programs they started are ended."""
        staging = getattr(_staging, "layers", None)
        if staging is not None and staging[0] is self:
            raise ValueError("a library entry cannot remove a reflex that is set")
        names = list(self.nodes) if names is None else [names] if isinstance(names, str) else list(names)
        for name in names:
            for node in self._below(name):
                self._retire(self.nodes.pop(node.name, None))
        self._touched()

    def _below(self, name) -> list:
        """The node `name` and the nodes under it."""
        node = self.nodes.get(name)
        if node is None:
            return []
        return [node] + [found for child in self.children(name) for found in self._below(child.name)]

    def _touched(self) -> None:
        self.changed = True
        self.tell()
        if self.wake_observer is not None:
            self.wake_observer()

    def digest(self, name=None, path="") -> dict:
        """How each node that acts stands, in one line, by its path in the tree. The host
        tells the model the lines that changed since it was last told (told()), so what a
        turn carries of the tree does not grow with the tree."""
        lines = {}
        for node in self.children(name):
            here = path + node.name
            if node.event is not None:
                lines[here] = f"answers the event {node.event}; began {node.triggered}"
            elif node.action is not None:
                lines[here] = (("ends what runs" if node.stops else f"tells you {node.action}"
                                + (" and ends what runs" if node.ends else "")) + f"; {node.triggered} times")
            elif node.do is not None:
                running = node.unit is not None and bool(getattr(node.unit, "running", False))
                lines[here] = (f"began {node.triggered}, did its work {node.did}, did not {node.did_not}"
                               + (", runs now" if running else "")
                               + (", ends what it interrupts" if node.ends else ""))
            if here in lines:
                lines[here] += _trial_text(node.trial)
            # What is wrong with its condition, also of a node that does nothing itself.
            wrong = ("not judged, its condition is too slow: set it again" if node.set_aside
                     else f"its condition raised {node.faults} time{'' if node.faults == 1 else 's'}" if node.fault else "")
            if wrong:
                lines[here] = f"{lines[here]}, {wrong}" if here in lines else wrong
            lines.update(self.digest(node.name, here + "/"))
        return lines

    def tell(self) -> None:
        """Send the host how the tree stands, when that changed (the `reflexes` note)."""
        if getattr(_staging, "layers", None) is not None and getattr(self, "live", None) is not None:
            return
        lines = self.digest()
        if lines != getattr(self, "_told", None):
            self._told = lines
            spans.note("reflexes", nodes=lines)

    @staticmethod
    def _retire(node) -> None:
        """A node that goes ends the program it started."""
        unit = getattr(node, "unit", None)
        if unit is not None and unit.running:
            threading.Thread(target=unit.cancel, name=f"reflex-{node.name}", daemon=True).start()

    def tried(self, staged) -> tuple:
        """For what a library entry set (stage()): the trial each of its nodes had in the
        tree, where it is the same node, and what is in the way of taking the entry on those
        trials. ({name: trial}, [why not, ...]). Nothing is run: a node is tried when it is
        set (session.set_reflex), and an entry that sets the same nodes needs no second
        trial. The nodes found the same stay in the tree when the entry is published."""
        trials, problems = {}, []
        if not staged.nodes:
            problems.append("it sets no node")
        for name, node in staged.nodes.items():
            live = self.nodes.get(name)
            if live is None:
                problems.append(f"{name} is not in the tree: set it there, with its trial, and propose the same lines")
                continue
            differs = [part for part in ("event", "action", "under", "priority", "every", "again_seconds", "ends")
                       if getattr(node, part) != getattr(live, part)]
            differs += [part for part in ("when", "do") if not same(getattr(node, part), getattr(live, part))]
            if differs:
                problems.append(f"{name} is not the node of that name in the tree (its {', '.join(differs)} "
                                "differ): propose the lines that set the node as it was tried")
            elif not isinstance(live.trial, dict) or live.trying:
                problems.append(f"{name} has had no trial in the tree")
            elif live.trial.get("tried") and _trial_text(live.trial):
                problems.append(f"{name} did not work in its trial")
            else:
                trials[name] = {key: live.trial[key] for key in ("tried", "turn", "seconds", "done", "why")
                                if key in live.trial}
                staged.kept[name] = live
        return trials, problems

    def publish(self, staged) -> None:
        """Put what a library entry set (stage()) into the tree."""
        for name, node in list(self.nodes.items()):
            if node.library_origin and node.library_origin[0] in staged.replacing and name not in staged.nodes:
                for found in self._below(name):
                    self._retire(self.nodes.pop(found.name, None))
        for name, node in staged.nodes.items():
            if name in staged.kept and self.nodes.get(name) is staged.kept[name]:
                # (The node that was tried: it stays as it is, and is the entry's from now on.)
                self.nodes[name].library_origin = node.library_origin
                continue
            self._retire(self.nodes.get(name))
            self.nodes[name] = node
        self._count = staged._count
        if staged.nodes:
            self._touched()

    # The tree as it stands.

    def children(self, name=None) -> list:
        """The nodes under `name` (None: at the top), the earlier first."""
        return sorted((node for node in self.nodes.copy().values() if node.under == name),
                      key=lambda node: (-node.priority, node.order))

    def _leaves(self, name) -> list:
        """The nodes with a program at and under `name`, in the order their turn comes: those
        under a node before the node itself."""
        node = self.nodes.get(name)
        if node is None:
            return []
        return [leaf for child in self.children(name) for leaf in self._leaves(child.name)] + (
            [node] if node.do is not None else [])

    def _above(self, node) -> list:
        """The nodes `node` is under, the nearest first."""
        found, above = [], self.nodes.get(node.under) if node.under is not None else None
        while above is not None and above not in found:
            found.append(above)
            above = self.nodes.get(above.under) if above.under is not None else None
        return found

    def rank(self, node) -> float:
        """What a node's program holds the environment with: the node's own priority,
        wherever it is in the tree, and above it a part of 1, the larger the earlier the
        node comes in the tree's order among the nodes with a program. So the node that
        runs is what a program's priority (at_priority) and every other node's is compared
        with: the higher has the environment, among equals the earlier in the tree; and
        every node is above the model's programs (0)."""
        leaves = [leaf for top in self.children() for leaf in self._leaves(top.name)]
        place = next((index for index, leaf in enumerate(leaves) if leaf is node), 0)
        return node.priority + (len(leaves) - place) / (len(leaves) + 1)

    def listing(self, name=None) -> list:
        """The nodes at the top of the tree, or the node `name` where it has none under it,
        else the nodes under it; the earlier first, at most LISTED of them (then a last row
        {"omitted": how many}). Each: {"name", "priority", "when" ("a condition" or the event
        it answers), "does", "holds" (its condition held when last judged), "running" (its
        program runs now), "began" (how often its program began), "ends" (True: the unit its
        program interrupts is ended, not resumed), "last" (the end report of
        its program's last run: {"ended", "done", "returned", "error", "seconds"}), "under":
        the names of the nodes under it (listing(name) gives them)}."""
        if name is not None and name not in self.nodes:
            raise ValueError(f"no reflex {name!r}")
        nodes = self.children(name) or ([self.nodes[name]] if name is not None else [])
        rows = [{"name": node.name, "priority": node.priority,
                 "when": f"the event {node.event}" if node.event else "a condition", "does": node.does,
                 **({"holds": bool(node.holds)} if node.event is None and node.holds is not _UNSEEN else {}),
                 **({"running": node.unit is not None and bool(getattr(node.unit, "running", False)),
                     "began": node.triggered, **({"ends": True} if node.ends else {})}
                    if node.do is not None else {}),
                 **({"trial": dict(node.trial)} if isinstance(node.trial, dict) else {}),
                 **({"last": node.last} if node.last is not None else {}),
                 **({"under": [child.name for child in self.children(node.name)]}
                    if self.children(node.name) else {})}
                for node in nodes[:LISTED]]
        return rows + ([{"omitted": len(nodes) - LISTED}] if len(nodes) > LISTED else [])

    # Judging.

    def _run(self, node, view):
        """Whether the node's condition holds on `view`. Where it was not judged (the
        period's budget was used up before its turn, or it was ended at the hard limit), what
        it was: it is judged in the next period. A fault of the condition never removes the
        node (_faulted): one that raises does not hold this once and is judged again the
        next time; one slower than the budget LATE_TIMES in a row, ended or not, is set
        aside, because it would use up every period the nodes after it share: it does not
        hold, and is not judged, until the node is set again."""
        with self.library_boundary:
            if self.nodes.get(node.name) is not node:
                return None
            if node.set_aside:
                return False
            over, judged = [], True
            try:
                result = call_reactive(node.name, node.when, view, budget_seconds=self.budget_seconds, late=over.append)
            except NotJudged:
                judged = False
            except ReactiveFault as found:
                node.late, node.waits = 0, False
                self._faulted(node, f"its condition raised {found.reason}. The node stays in the tree: its "
                                    "condition counts as not holding each time it raises")
                return False
        if over:
            node.late += 1
        elif judged:
            node.late = 0
        if node.late >= LATE_TIMES:
            node.set_aside, node.waits = True, False
            self._faulted(node, f"its condition took {over[0] * 1000:.1f} ms, longer than its budget of "
                                f"{self.budget_seconds * 1000:.1f} ms {LATE_TIMES} times in a row. The node stays in "
                                "the tree and is not judged, nor are the nodes under it, until it is set again")
            return False
        node.waits = not judged
        if not judged:
            return None if node.holds is _UNSEEN else node.holds
        if result and node.library_origin:
            spans.note("library_use", key=node.library_origin[0], revision=node.library_origin[2],
                       ok=True, rule=node.name, testing=spans.in_test())
        return result

    def _faulted(self, node, reason) -> None:
        """Note what went wrong with the node's condition. The model is told each reason
        once (the tick tells `fault_tell`); how often it happened is in the node's line."""
        node.fault, node.faults = reason, node.faults + 1
        key = reason[:200]
        if key not in node.fault_told:
            node.fault_told.add(key)
            node.fault_tell = reason
        self.changed = True

    def _above_hold(self, node, view) -> bool:
        """Whether the conditions of the nodes above `node` hold on `view`."""
        above = self.nodes.get(node.under) if node.under is not None else None
        while above is not None:
            if not self._run(above, view):
                return False
            above = self.nodes.get(above.under) if above.under is not None else None
        return True

    def stops(self) -> bool:
        """Whether a node ends what runs (those are judged at every step of an execution)."""
        return any(self._ends_what_runs(node) for node in self.nodes.copy().values())

    @staticmethod
    def _ends_what_runs(node) -> bool:
        """A node whose turn ends the execution that runs: one that does an action of the
        environment that ends it ("stop"), or one that tells an event and says ends=True (the
        execution then ends with that event, which is how the model is told)."""
        return node.stops or (node.ends and node.action is not None and node.do is None)

    def evaluate(self, view) -> Reflex | None:
        """The first node that ends what runs and whose turn it is now."""
        for node in self._ordered():
            if self._ends_what_runs(node) and self._above_hold(node, view) and self._run(node, view):
                if not node.stops:
                    if node.raised or time.monotonic() < node.ready_at:
                        continue
                    # (Told by the end of what ran: not told again while its condition holds.)
                    node.raised, node.ready_at = True, time.monotonic() + node.again_seconds
                node.triggered += 1
                return node
        return None

    def _ordered(self, name=None) -> list:
        """Every node, in the tree's order."""
        return [found for node in self.children(name) for found in (node, *self._ordered(node.name))]

    def answer(self, trace, start) -> bool:
        """Offer an event to the first node that answers its kind and whose turn it is:
        its program is started with `start(node, program)` and the event is answered."""
        kind = trace.event.kind
        for node in self._ordered():
            if node.event != kind or (node.unit is not None and node.unit.running):
                continue
            if node.under is not None and self.view is not None and not self._above_hold(node, self.view()):
                continue
            program = (lambda: node.do(trace.event)) if _takes_argument(node.do) else node.do
            node.triggered += 1
            node.unit = start(node, program)
            return True
        return False

    def listens(self, kinds) -> bool:
        """Whether a node answers one of the event `kinds`."""
        return any(node.event in kinds for node in self.nodes.copy().values())

    def next_due(self, now) -> float | None:
        """Seconds until the tree is due on time (0 when it is), None when it never is."""
        due = [node.next_at for node in self.nodes.copy().values()
               if node.every is not None and node.event is None and not node.stops and not node.set_aside]
        if self.wake_at is not None:
            due.append(self.wake_at)
        return max(0.0, min(due) - now) if due else None

    def reads_changes(self) -> bool:
        """Whether a node is judged when the state or the facts change."""
        return any(node.every is None and node.event is None and not node.stops for node in self.nodes.copy().values())


def fault_event(fault, step, **detail):
    return Event(ev.REACTIVE_FAULT, fault.source, {"reason": fault.reason, **detail}, step)


def emit(tree, owner, skill, event, *, notice=False):
    if tree is not None:
        tree.raise_event(tree.get(owner), ExecutionTrace(skill, {}, event.tick, event.tick, event), notice=notice)


def report(unit) -> dict:
    """The end report of a unit (the one every unit gives): how it ended, whether what it
    was for is the case, what it returned or why it failed, its seconds."""
    how = "by itself" if unit.status == "done" else "an error" if unit.failure is None or unit.raised is not None else \
        f"the event {(unit.failure.trace.event.detail.get('event') or {}).get('kind', unit.failure.trace.event.kind)}"
    returned = unit.result
    if returned is not None and not isinstance(returned, (bool, int, float)):
        text = returned if isinstance(returned, str) else repr(returned)
        returned = text if len(text) <= 400 else text[:400] + "..."
    return {"ended": how, "done": unit.ok, **({"returned": returned} if returned is not None else {}),
            **({"error": str(unit.error)[-600:]} if unit.error else {}),
            "seconds": round((unit.ended or time.time()) - unit.started, 1)}


def _interrupted(unit) -> bool:
    """Whether a unit ended because another took the environment from it, or was cancelled."""
    if unit.status == "cancelled":
        return True
    failure = getattr(unit, "failure", None)
    detail = failure.trace.event.detail if failure is not None else None
    return isinstance(detail, dict) and (detail.get("event") or {}).get("kind") == ev.PREEMPTED


def judge(session, tree):
    """Judge the session's tree on its view now (see the module docstring)."""
    layer = getattr(session, "reactive", None)
    if layer is None or tree is None or not layer.nodes:
        return
    state = session.state
    made = {}

    def view_of():
        if "view" not in made:
            made["view"] = session._view(state, 0)
        return made["view"]

    now = time.monotonic()
    stamp = (id(state), session.facts.version)
    changed, layer.stamp = stamp != layer.stamp, stamp
    forced, layer.changed = layer.changed, False
    layer.wake_at = None
    failures = []
    # The programs that ended since the last judgement.
    for node in list(layer.nodes.values()):
        unit = node.unit
        if unit is None or unit.running:
            continue
        node.unit, forced = None, True
        if _interrupted(unit):
            node.ready_at = now + RESTART_SECONDS
            continue
        node.last = report(unit)
        if unit.status == "done" and unit.ok is not False:
            node.did += 1
            node.ready_at, node.told = now + max(node.again_seconds, RESTART_SECONDS), False
            if layer.tell_first and not node.acted and not node.trying:
                # The first time its program did its work by itself: the one time the model
                # sees it in the real situation (told with its next call).
                node.acted = True
                emit(tree, None, "reflex", Event(ev.REFLEX_ACTED, node.name, {
                    "reflex": node.name, "unit": unit.id, "began": node.triggered, **node.last}, state.get("step")))
        else:
            node.did_not += 1
            # It failed, or it ended and the situation it answers is not over.
            node.ready_at = now + max(node.again_seconds, FAILED_AGAIN_SECONDS if unit.status != "done" else RESTART_SECONDS)
            failures.append((node, unit))

    def fault(node, error):
        # (What went wrong while the node was judged, other than in its condition itself.)
        layer._faulted(node, f"{type(error).__name__}: {error}. The node stays in the tree")

    def holds(node) -> bool:
        if node.every is not None:
            due = now >= node.next_at
            if due:
                node.next_at = max(node.next_at + node.every, now + node.every / 2)
        else:
            due = changed
        if due or forced or node.waits or node.holds is _UNSEEN:
            node.holds = bool(layer._run(node, view_of()))
            if node.waits:
                # Not judged in this period: again in the next one.
                layer.wake_at = now if layer.wake_at is None else min(layer.wake_at, now)
        return node.holds

    wanting, telling = [], []

    def over(node):
        # What a node's program is for: the situation the node answers is over.
        return lambda view: not layer._run(node, view)

    def walk(name):
        # The nodes at and under `name` whose condition holds, the earlier first; under a
        # node before the node itself, which answers only what none of them does. Those with
        # a program are returned; each node that acts is kept with the ones whose turn comes
        # before its own: those under it, and for one that tells, those before it at its place.
        before = []
        for node in layer.children(name):
            if node.event is not None or node.stops or layer.nodes.get(node.name) is not node:
                continue
            try:
                held = holds(node)
            except Exception as error:
                fault(node, error)
                continue
            if not held:
                # The situation is over. (Whether the model was told that the node failed
                # stays: it is told again only after the node has done its work, else a
                # condition that comes and goes tells the same failure every time.)
                node.raised = False
                # (What is under it is judged anew when its turn comes again.)
                for below in layer._below(node.name)[1:]:
                    below.holds, below.raised = _UNSEEN, False
                continue
            under = walk(node.name)
            if node.action is not None:
                telling.append((node, before + under))
            elif node.do is not None:
                wanting.append((node, under))
            before += under + ([node] if node.do is not None else [])
        return before

    walk(None)
    running = [entry for entry in tree.running() if entry.kind != "agent"]
    startable = set()
    for node, under in wanting:
        if any(found.name in startable for found in under):
            # A narrower situation under it is being answered: what the node does itself
            # gives way, also where it already runs.
            layer._retire(node)
            continue
        if node.unit is not None:
            startable.add(node.name)
            continue
        if now < node.ready_at:
            layer.wake_at = node.ready_at if layer.wake_at is None else min(layer.wake_at, node.ready_at)
            continue
        rank = layer.rank(node)
        # (The programs of the nodes it is under give way to it: they do not keep it waiting.)
        giving_way = {above.name for above in layer._above(node)}
        above = next((entry for entry in running if entry.rank > rank
                      and getattr(entry, "rule", None) not in giving_way), None)
        if above is not None:
            # What is before it has the environment: its turn is judged when that ends. Where
            # that is a program that said so (at_priority), the model is told once.
            if getattr(above, "rule", None) is None:
                if node.kept_by != above.id:
                    node.kept_by = above.id
                    spans.note("held_back", rule=node.name, priority=node.priority, by=above.id, by_name=above.name)
                layer.changed = True
            continue
        node.kept_by = None
        node.triggered += 1
        node.unit = tree.spawn(node.do, name=node.name, rule=node.name, priority=rank, quiet=True,
                               until=over(node))
        running.append(node.unit)
        startable.add(node.name)
        spans.note("rule", name=node.name, action="began", unit=node.unit.id, priority=rank)
    # A node that tells the model has its turn like any other: when none of those whose
    # turn comes before its own (under it, and before it at its place) is acting. So it
    # tells what nothing answered, and no more.
    # (While an execution runs, a node that tells and ends what runs does both at that
    # execution's next step, where it is judged with the nodes that end what runs: the
    # execution ends with the node's event. Here it tells only when nothing runs.)
    ticker = session.__dict__.get("_tick_loop")
    executing = ticker is not None and any(
        getattr(entry, "steps", None) is not None and getattr(entry, "paused", None) is None
        for entry in list(getattr(ticker, "_entries", ())))
    for node, before in telling:
        if any(found.name in startable for found in before):
            continue
        if node.ends and executing:
            continue
        if not node.raised and now >= node.ready_at:
            node.raised, node.ready_at = True, now + node.again_seconds
            node.triggered += 1
            # (The event is offered to the nodes that answer its kind; one that none answers
            # reaches the model: that is what telling is.)
            emit(tree, None, "reflex", session._rule_event(node, state))
    for node in list(layer.nodes.values()):
        if node.fault_tell is not None:
            reason, node.fault_tell = node.fault_tell, None
            emit(tree, None, "reflex", Event(ev.REACTIVE_FAULT, node.name, {
                "reason": reason, "times": node.faults, "set_aside": node.set_aside}, state.get("step")))
    layer.tell()
    for node, unit in failures:
        # What comes after a node whose program did not do its work: a later node at its
        # place, then what the nodes above it do themselves (a program that is acting, or
        # their telling the model).
        later = layer.children(node.under)
        later = later[later.index(node) + 1:] if node in later else []
        taken = any(found.name in startable for other in later for found in layer._leaves(other.name)) or any(
            above.name in startable or (above.action is not None and not above.stops and above.raised)
            for above in layer._above(node))
        if node.told or taken:
            continue
        node.told = True
        emit(tree, None, "reflex", Event(ev.REFLEX_FAILED, node.name, {
            "reflex": node.name, "unit": unit.id, "began": node.triggered, **node.last}, state.get("step")))
