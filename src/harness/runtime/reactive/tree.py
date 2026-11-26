"""The reactive layer: one behaviour tree.

What acts without the model is one tree, empty at first, judged as a behaviour tree is:
from its top, in order, each time it is judged. A node is a situation with what answers it:
`when` says when the agent comes into it (a condition of the view, or the name of an
event), `do` what answers it (a program, the name of an event to tell, an action that ends
what runs, or nothing), `over` when it is past. Any node may have nodes under it: the
narrower situations within it.

    A node            a sequence: its condition, then its action. The condition decides
                      only whether the action begins. Once begun, the action runs until it
                      has a result, whatever the condition does meanwhile.
    The result        success when the situation is past: `over` holds (then the program is
                      ended there, its work done), or, for a node without `over`, its
                      program returned and `when` no longer holds. Failure when the program
                      returned or failed and the situation is not past.
    A node with       a selector: the nodes under it in order, then what the node does
    nodes under it    itself. The first whose condition holds acts. One that fails is not
                      tried again in this occurrence of the situation: the next acts. When
                      what the node does itself fails too, the node has failed.
    The top           a selector over the top nodes in order, and after them the model's
                      own programs: a node's action takes the environment from them. A top
                      node that failed is told to the model (REFLEX_FAILED), once.
    Order             the earlier in the tree comes first, and takes the environment from
                      the later; a node set later comes later unless it says `before`.
                      There are no priorities and no times: nothing is tried again because
                      time passed. A failed node may act again when its situation was past
                      and has come anew, or when it was set again.
    Channels          where the environment has channels, nodes whose actions use channels
                      of their own act at the same time (runtime/tick.py).
    Events            a node that tells (`do` an event's name) has its turn like any other:
                      it tells when neither a node before it at its place nor one under it
                      is acting, once for each occurrence.

A node's program runs as a unit whose priority is its place in the tree (rank()): that is
how the tick lets the earlier take the environment from the later (the later call is paused
where the environment pauses, else ended, and its node acts again when its turn comes).
Nothing is judged while the agent cannot act (the session's can_act: an environment says
when that is).

A node is started or not. One that is not started is in the tree and is not judged, and
neither are the nodes under it: it answers nothing. The model starts and stops nodes
(start(), stop()); a node it sets is started; a node a library entry puts into the tree
(publish()) is not, unless it takes the place of a node that was.

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

# A node's condition that took longer than the budget this many times in a row is a fault:
# the node goes and the model is told. Once is a moment of the machine, not of the node.
LATE_TIMES = 3

_staging = threading.local()
_UNSEEN = object()
# What a turn is told of a tree with no node in it.
NO_REFLEXES = "Reflex tree: empty (nothing acts without you)"
# The most nodes one reflexes() call gives, and the most changed nodes a turn is told of.
LISTED, TOLD = 50, 10
# What a node says of how the model hears of it (Reflex.tell, Reflex.tell_failed): not at all,
# the first time only, or each time, with the place the notice takes in the model's queue
# (runtime/decision/notices.py: later, next, now).
QUEUE = ("later", "next", "now")
# What a node or a program says of itself (its report function) is a message: its text is at
# most SAID_CHARS, with at most REPORT_PICTURES pictures and REPORT_FILES files of at most
# FILE_CHARS characters each.
SAID_CHARS = 2000
REPORT_PICTURES = 4
REPORT_FILES = 4
FILE_CHARS = 20000
_PICTURES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".webp": "image/webp"}
# A program that asks to be told when a reflex takes the environment from it is told so,
# one by one, this many times; the rest are counted and told with its end.
INTERRUPTIONS_TOLD = 3
TELLS = ("never", "first", *QUEUE)


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
# The line of a node that is not started (Reflexes.digest).
NOT_STARTED = "not started"


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
    # A node that is not started answers nothing.
    waiting = sum(1 for line in nodes.values() if line == NOT_STARTED)
    if waiting:
        count += f", {waiting} not started (start_reflex() starts {'it' if waiting == 1 else 'them'})"
    if not changed:
        if not never and not only and not untried and not failed and not waiting:
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
    the nodes under it answer); `over`: when the situation is past (a condition of the view;
    None: when `when` no longer holds once its program returned); the node it is `under`
    (None: the top); `every` seconds its condition is judged (None: when the state or the
    facts change); `ends`: the unit its
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
    every: float | None = None
    order: float = 0
    over: Callable | None = None
    library_origin: tuple | None = None
    ends: bool = False
    # What the node says when the model is told of it, said when it is set: `about`, one
    # sentence on the situation it answers; `report`, a function of the view and of what its
    # program returned, which returns what the model is to read then.
    about: str = ""
    report: Callable | None = None
    # What the model hears of the node, said when it is set. `tell`: of its program having done
    # its work (one of TELLS), or for a node that tells an event, the place of that event in
    # the queue (one of QUEUE). `tell_failed`: of its program not having done its work with
    # nothing else taking the situation ("never" or one of QUEUE).
    tell: str = "never"
    tell_failed: str = "now"
    # `claims`: the channels of the environment its program uses (None: the whole
    # environment), where the environment has channels; (): none, its program acts on
    # nothing of the environment (it sets facts or rules others read) and runs beside all.
    claims: Any = None
    # Its program was ended because its situation was past (`over`): that is its work done.
    # `retired`: the tree itself ended its program (a node before it took its place).
    # `spent`: it failed in this occurrence of its situation, and is not tried again in it.
    released: bool = field(default=False, repr=False)
    retired: bool = field(default=False, repr=False)
    spent: bool = field(default=False, repr=False)
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
    # Not started: the node is in the tree and is not judged, nor are the nodes under it,
    # until it is started (Reflexes.start).
    stopped: bool = False
    # As it stands: the unit of its program, whether its condition held when last judged,
    # whether it raised its event since that came to hold, when it is next due, how often it
    # acted, the program before it that kept it from acting, and whether the model was told
    # of its failure since it last succeeded.
    unit: Any = field(default=None, repr=False)
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
                **({} if self.stops or self.ends else {"stops": False}),
                **({"tell": self.tell} if self.action is not None and not self.stops and self.tell in QUEUE else {})}


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

    def set(self, name, when, do=None, *, under=None, every=None, ends=False, tell=None, tell_failed="now",
            about=None, report=None, claims=None, over=None, before=None) -> str:
        """Put the node `name` into the tree, in place of a node of that name (see Reflex;
        `when`: a function of the view, or the name of an event; `do`: a program, or the
        name of an event to raise, or an action of the environment that ends what runs
        ("stop"), or None: then only the nodes under it answer). Its name."""
        staging = getattr(_staging, "layers", None)
        if staging is not None and staging[0] is self:
            return staging[1].set(name, when, do, under=under, every=every, ends=ends, tell=tell,
                                  tell_failed=tell_failed, about=about, report=report, claims=claims, over=over,
                                  before=before)
        if not isinstance(name, str) or not name:
            raise ValueError("a reflex's name is a nonempty string")
        event = None
        if isinstance(when, str):
            # An event of the run (LOW_BATTERY), or of a space, named in its vocabulary (qq.message).
            if not all(part.replace("_", "").isalnum() for part in when.split(".")):
                raise ValueError(f"an event's name is an identifier like LOW_BATTERY, or a space's event like "
                                 f"chat.message, got {when!r}")
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
        if action is not None and not stops:
            # A node that tells: where its event goes in the model's queue.
            tell = "now" if tell is None else tell
            if tell not in QUEUE:
                raise ValueError(f"tell, for a node that tells an event, is one of {QUEUE}, got {tell!r}")
        else:
            # A node with a program: whether the model hears that it did its work.
            tell = ("first" if self.tell_first else "never") if tell is None else tell
            if tell not in TELLS:
                raise ValueError(f"tell is one of {TELLS}, got {tell!r}")
        if tell_failed not in ("never", *QUEUE):
            raise ValueError(f"tell_failed is one of {('never', *QUEUE)}, got {tell_failed!r}")
        if over is not None and (not callable(over) or event is not None or do is None):
            raise ValueError("over is a condition of the view (a function) that holds when the situation is past; "
                             "it goes with a node whose `when` is a condition and whose `do` is a program")
        if about is not None and (not isinstance(about, str) or not about.strip()):
            raise ValueError("about is one sentence: the situation the node answers")
        if report is not None and not callable(report):
            raise TypeError("report is a function of the view and of what the node's program returned")
        if not isinstance(ends, bool):
            raise ValueError(f"ends is True or False, got {ends!r}")
        if claims is not None:
            claims = [claims] if isinstance(claims, str) else list(claims)
            if not all(isinstance(one, str) and one for one in claims):
                raise ValueError(f"claims names channels of the environment (none: []), got {claims!r}")
            if do is None or action is not None:
                raise ValueError("claims goes with a program: the channels its program uses")
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
        if before is not None:
            first = known.get(before)
            if first is None or first.under != under or before == name:
                raise ValueError(f"before={before!r}: it names another node at the same place (under {under!r})")
        self._count += 1
        self._retire(self.nodes.get(name))
        self.nodes[name] = Reflex(name=name, when=when, event=event, do=do, action=action, stops=stops, under=under,
                                  every=None if every is None else float(every),
                                  order=old.order if old is not None and old.under == under else self._count,
                                  over=over, library_origin=self.library_origin, ends=ends,
                                  about=(about or "").strip(), report=report, tell=tell, tell_failed=tell_failed,
                                  claims=None if claims is None else tuple(claims))
        if before is not None:
            # Its place among the nodes there: just before the one it names.
            place = [node for node in self.children(under) if node.name != name]
            place.insert(next(index for index, node in enumerate(place) if node.name == before), self.nodes[name])
            for node, order in zip(place, sorted(node.order for node in place)):
                node.order = order
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

    def start(self, names=None) -> list:
        """Start the nodes `names` (a name or a list; None: every node that is not started)
        with the nodes under them: they are judged from now on. The names of the nodes this
        started, in the tree's order. A node under one that is not started is started with
        that one, not without it."""
        if getattr(_staging, "layers", None) is not None and _staging.layers[0] is self:
            raise ValueError("a library entry cannot start a reflex")
        if names is None:
            names = [node.name for node in self._ordered() if node.stopped]
        names = [names] if isinstance(names, str) else list(names)
        missing = next((name for name in names if name not in self.nodes), None)
        if missing is not None:
            raise ValueError(f"no reflex {missing!r}")
        found = {node.name: node for name in names for node in self._below(name)}
        for name in names:
            held = next((above for above in self._above(self.nodes[name]) if above.stopped and above.name not in found), None)
            if held is not None:
                raise ValueError(f"{name!r} is under {held.name!r}, which is not started: start {held.name!r} "
                                 "(the nodes under it start with it)")
        started = [node.name for node in self._ordered() if node.name in found and node.stopped]
        for name in started:
            node = self.nodes[name]
            node.stopped, node.holds, node.raised, node.spent, node.next_at = False, _UNSEEN, False, False, 0.0
        if started:
            self._touched()
        return started

    def stop(self, names=None) -> list:
        """Stop the nodes `names` (a name or a list; None: all) with the nodes under them:
        they stay in the tree and are not judged until they are started again; the programs
        they started are ended. The names of the nodes this stopped, in the tree's order."""
        if getattr(_staging, "layers", None) is not None and _staging.layers[0] is self:
            raise ValueError("a library entry cannot stop a reflex")
        names = [node.name for node in self.children()] if names is None else [names] if isinstance(names, str) else list(names)
        missing = next((name for name in names if name not in self.nodes), None)
        if missing is not None:
            raise ValueError(f"no reflex {missing!r}")
        found = {node.name for name in names for node in self._below(name)}
        stopped = [node.name for node in self._ordered() if node.name in found and not node.stopped]
        for name in stopped:
            node = self.nodes[name]
            self._retire(node)
            node.stopped, node.holds, node.raised, node.spent = True, _UNSEEN, False, False
        if stopped:
            self._touched()
        return stopped

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
            if node.stopped:
                lines[here] = NOT_STARTED
                lines.update(self.digest(node.name, here + "/"))
                continue
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
            node.retired = True
            threading.Thread(target=unit.cancel, name=f"reflex-{node.name}", daemon=True).start()

    def tried(self, staged) -> tuple:
        """For what a library entry set (stage()): how each of its nodes stands in the tree,
        where it is the same node (its trial where it had one, how often it began and did its
        work), and what is in the way of taking the entry as it stands there. ({name: what it
        showed}, [why not, ...]). Nothing is run. The nodes found the same stay in the tree
        when the entry is published."""
        trials, problems = {}, []
        if not staged.nodes:
            problems.append("it sets no node")
        for name, node in staged.nodes.items():
            live = self.nodes.get(name)
            if live is None:
                problems.append(f"{name} is not in the tree: set it there, with its trial, and propose the same lines")
                continue
            differs = [part for part in ("event", "action", "under", "every", "ends",
                                         "tell", "tell_failed", "claims")
                       if getattr(node, part) != getattr(live, part)]
            differs += [part for part in ("when", "do", "over") if not same(getattr(node, part), getattr(live, part))]
            if differs:
                problems.append(f"{name} is not the node of that name in the tree (its {', '.join(differs)} "
                                "differ): propose the lines that set the node as it was tried")
            elif live.trying:
                problems.append(f"{name} is in its trial now")
            elif isinstance(live.trial, dict) and live.trial.get("tried") and _trial_text(live.trial):
                problems.append(f"{name} did not work in its trial")
            else:
                # (A trial is not required: a node that had none is kept as it stands in the tree.)
                trial = live.trial if isinstance(live.trial, dict) else {"tried": False}
                trials[name] = {**{key: trial[key] for key in ("tried", "turn", "seconds", "done") if key in trial},
                                "began": live.triggered, "did": live.did, "did_not": live.did_not}
                staged.kept[name] = live
        return trials, problems

    def publish(self, staged) -> None:
        """Put what a library entry set (stage()) into the tree. A node that takes the
        place of a node of its name stands as that one stood, started or not; one that
        takes no node's place is not started: the model starts it (start())."""
        for name, node in list(self.nodes.items()):
            if node.library_origin and node.library_origin[0] in staged.replacing and name not in staged.nodes:
                for found in self._below(name):
                    self._retire(self.nodes.pop(found.name, None))
        for name, node in staged.nodes.items():
            if name in staged.kept and self.nodes.get(name) is staged.kept[name]:
                # (The node that was tried: it stays as it is, and is the entry's from now on.)
                self.nodes[name].library_origin = node.library_origin
                continue
            old = self.nodes.get(name)
            self._retire(old)
            node.stopped = old.stopped if old is not None else True
            self.nodes[name] = node
        self._count = staged._count
        if staged.nodes:
            self._touched()

    # The tree as it stands.

    def children(self, name=None) -> list:
        """The nodes under `name` (None: at the top), the earlier first."""
        return sorted((node for node in self.nodes.copy().values() if node.under == name),
                      key=lambda node: node.order)

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
        """What a node's program holds the environment with: its place in the tree, between 0
        and 1, the larger the earlier its turn comes among the nodes with a program. That is
        what the tick compares: the earlier has the environment, and every node is above the
        model's programs (0). A program that holds the environment for an action
        (at_priority) holds it with the place of the node it names, or above every node."""
        leaves = [leaf for top in self.children() for leaf in self._leaves(top.name)]
        place = next((index for index, leaf in enumerate(leaves) if leaf is node), 0)
        return (len(leaves) - place) / (len(leaves) + 1)

    def listing(self, name=None) -> list:
        """The nodes at the top of the tree, or the node `name` where it has none under it,
        else the nodes under it; the earlier first, at most LISTED of them (then a last row
        {"omitted": how many}). Each: {"name", "when" ("a condition" or the event
        it answers), "does", "holds" (its condition held when last judged), "running" (its
        program runs now), "began" (how often its program began), "ends" (True: the unit its
        program interrupts is ended, not resumed), "last" (the end report of
        its program's last run: {"ended", "done", "returned", "error", "seconds"}), "under":
        the names of the nodes under it (listing(name) gives them), "started": False for a
        node that is not started}."""
        if name is not None and name not in self.nodes:
            raise ValueError(f"no reflex {name!r}")
        nodes = self.children(name) or ([self.nodes[name]] if name is not None else [])
        rows = [{"name": node.name,
                 "when": f"the event {node.event}" if node.event else "a condition", "does": node.does,
                 **({"about": node.about} if node.about else {}),
                 **({"started": False} if node.stopped else {}),
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
            if node.set_aside or node.stopped:
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

    def _past(self, node, view) -> bool:
        """Whether the node's own `over` holds on `view` (False for a node without one, and
        where it could not be judged or raised: a situation is not past on a guess)."""
        if node.over is None:
            return False
        try:
            return bool(call_reactive(node.name, node.over, view, budget_seconds=self.budget_seconds))
        except NotJudged:
            return False
        except ReactiveFault as found:
            self._faulted(node, f"its `over` raised {found.reason}. It counts as not holding each time it raises")
            return False

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

    def _answered(self, node) -> bool:
        """Whether a node whose turn comes before `node`'s is answering now: one under it, or
        one before it at its place. A node that tells does so only when none of them is."""
        place = self.children(node.under)
        earlier = place[:place.index(node)] if node in place else []
        before = self._below(node.name)[1:] + [leaf for other in earlier for leaf in self._leaves(other.name)]
        return any(found.unit is not None and getattr(found.unit, "running", False) for found in before)

    def evaluate(self, view) -> Reflex | None:
        """The first node that ends what runs and whose turn it is now. One that tells and
        ends what runs has its turn as in the tick: not while a node under it, or before it
        at its place, is answering (what runs then is that node's answer, not something the
        situation is unanswered in)."""
        for node in self._ordered():
            if self._ends_what_runs(node) and self._above_hold(node, view) and self._run(node, view):
                if not node.stops:
                    if node.raised or self._answered(node):
                        continue
                    # (Told by the end of what ran: not told again while its condition holds.)
                    node.raised = True
                node.triggered += 1
                return node
        return None

    def select(self, view, name=None, accept=None) -> Reflex | None:
        """The node that takes over on `view`, judged from the root as a behaviour tree's
        selector is: the nodes at a place in order; the first whose condition holds is gone
        into, its narrower nodes first, then what it does itself; a node that is not started
        answers nothing. None when nothing takes over. `accept(node)`: whether a node's own
        answer may be what takes over this time (its narrower nodes are judged either way).
        (An identity's tree of reactions, judged whenever the world changes or a time comes,
        is judged this way.)"""
        for node in self.children(name):
            if node.stopped or node.set_aside or not self._run(node, view):
                continue
            found = self.select(view, node.name, accept)
            if found is not None:
                return found
            if (node.do is not None or node.action is not None) and (accept is None or accept(node)):
                node.triggered += 1
                return node
        return None

    def path(self, name) -> list:
        """The names from the root down to `name`."""
        names, node = [], self.nodes.get(name)
        while node is not None:
            names.insert(0, node.name)
            node = self.nodes.get(node.under) if node.under is not None else None
        return names

    def _ordered(self, name=None) -> list:
        """Every node, in the tree's order."""
        return [found for node in self.children(name) for found in (node, *self._ordered(node.name))]

    def answer(self, trace, start) -> bool:
        """Offer an event to the first node that answers its kind and whose turn it is:
        its program is started with `start(node, program)` and the event is answered."""
        kind = trace.event.kind
        for node in self._ordered():
            if node.event != kind or node.stopped or (node.unit is not None and node.unit.running):
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
        return any(node.event in kinds and not node.stopped for node in self.nodes.copy().values())

    def next_due(self, now) -> float | None:
        """Seconds until the tree is due on time (0 when it is), None when it never is."""
        due = [node.next_at for node in self.nodes.copy().values()
               if node.every is not None and node.event is None and not node.stops and not node.set_aside
               and not node.stopped]
        if self.wake_at is not None:
            due.append(self.wake_at)
        return max(0.0, min(due) - now) if due else None

    def reads_changes(self) -> bool:
        """Whether a node is judged when the state or the facts change."""
        return any(node.every is None and node.event is None and not node.stops and not node.stopped
                   for node in self.nodes.copy().values())


def fault_event(fault, step, **detail):
    return Event(ev.REACTIVE_FAULT, fault.source, {"reason": fault.reason, **detail}, step)


def message(function, *arguments) -> dict:
    """What a report function (a node's report=, a program's until(report=)) returns, as the
    message the model reads. It returns what a message holds, alone or in a list, in the
    order given: text; plain data (told as JSON); a picture (what look() or get_observation()
    returned, or an RGB array); a file (a pathlib.Path: an image file as its picture, a folder
    as its names, any other file as its text). {"says": the text, "shows": [{"caption",
    "image_url"}], "files": [{"name", "text"}]}, each only where there is something; the text
    at most SAID_CHARS, REPORT_PICTURES pictures, REPORT_FILES files of FILE_CHARS each. What
    went wrong where the function raises is the text."""
    import json
    import os
    from pathlib import Path

    if function is None:
        return {}
    texts, shows, files = [], [], []

    def add(item, depth=0):
        if item is None:
            return
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, os.PathLike):
            path = Path(item)
            if not path.exists():
                texts.append(f"(no file {path})")
            elif path.is_dir():
                names = sorted(child.name + ("/" if child.is_dir() else "") for child in path.iterdir())
                files.append({"name": str(path), "text": "\n".join(names[:500])})
            elif path.suffix.lower() in _PICTURES:
                from harness.core.codec import data_url

                shows.append({"caption": path.name, "image_url": data_url(path.read_bytes(), _PICTURES[path.suffix.lower()])})
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
                files.append({"name": str(path), "text": text if len(text) <= FILE_CHARS
                              else text[:FILE_CHARS] + f" ... [{len(text) - FILE_CHARS} more characters]"})
        elif isinstance(getattr(item, "_urls", None), dict):
            shows.extend({"caption": str(name), "image_url": url} for name, url in item._urls.items())
        elif isinstance(item, (list, tuple)) and depth < 3:
            for each in item:
                add(each, depth + 1)
        elif hasattr(item, "shape") and hasattr(item, "dtype"):
            from harness.core.codec import image_data_url

            shows.append({"caption": "", "image_url": image_data_url(item, "jpeg")})
        else:
            texts.append(json.dumps(item, default=str, ensure_ascii=False))

    try:
        add(function(*arguments))
    except BaseException as error:
        texts.append(f"(its report raised {type(error).__name__}: {error})")
    text = " ".join(part for part in texts if part)
    if len(text) > SAID_CHARS:
        text = text[:SAID_CHARS] + "..."
    return {**({"says": text} if text else {}), **({"shows": shows[:REPORT_PICTURES]} if shows else {}),
            **({"files": files[:REPORT_FILES]} if files else {})}


def message(function, *arguments) -> dict:
    """What a report function (a node's report=, a program's until(report=)) returns, as the
    message the model reads. It returns what a message holds, alone or in a list, in the
    order given: text; plain data (told as JSON); a picture (what look() or get_observation()
    returned, or an RGB array); a file (a pathlib.Path: an image file as its picture, a folder
    as its names, any other file as its text). {"says": the text, "shows": [{"caption",
    "image_url"}], "files": [{"name", "text"}]}, each only where there is something; the text
    at most SAID_CHARS, REPORT_PICTURES pictures, REPORT_FILES files of FILE_CHARS each. What
    went wrong where the function raises is the text."""
    import json
    import os
    from pathlib import Path

    if function is None:
        return {}
    texts, shows, files = [], [], []

    def add(item, depth=0):
        if item is None:
            return
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, os.PathLike):
            path = Path(item)
            if not path.exists():
                texts.append(f"(no file {path})")
            elif path.is_dir():
                names = sorted(child.name + ("/" if child.is_dir() else "") for child in path.iterdir())
                files.append({"name": str(path), "text": "\n".join(names[:500])})
            elif path.suffix.lower() in _PICTURES:
                from harness.core.codec import data_url

                shows.append({"caption": path.name, "image_url": data_url(path.read_bytes(), _PICTURES[path.suffix.lower()])})
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
                files.append({"name": str(path), "text": text if len(text) <= FILE_CHARS
                              else text[:FILE_CHARS] + f" ... [{len(text) - FILE_CHARS} more characters]"})
        elif isinstance(getattr(item, "_urls", None), dict):
            shows.extend({"caption": str(name), "image_url": url} for name, url in item._urls.items())
        elif isinstance(item, (list, tuple)) and depth < 3:
            for each in item:
                add(each, depth + 1)
        elif hasattr(item, "shape") and hasattr(item, "dtype"):
            from harness.core.codec import image_data_url

            shows.append({"caption": "", "image_url": image_data_url(item, "jpeg")})
        else:
            texts.append(json.dumps(item, default=str, ensure_ascii=False))

    try:
        add(function(*arguments))
    except BaseException as error:
        texts.append(f"(its report raised {type(error).__name__}: {error})")
    text = " ".join(part for part in texts if part)
    if len(text) > SAID_CHARS:
        text = text[:SAID_CHARS] + "..."
    return {**({"says": text} if text else {}), **({"shows": shows[:REPORT_PICTURES]} if shows else {}),
            **({"files": files[:REPORT_FILES]} if files else {})}


def said(function, *arguments):
    """The text of what a report function returns (message), or None."""
    return message(function, *arguments).get("says")


def urgent(*places):
    """The most urgent of the places in the model's queue (QUEUE; None: none)."""
    named = [place for place in places if place in QUEUE]
    return max(named, key=QUEUE.index) if named else None


def interrupted_by(session, node, unit, view) -> tuple:
    """The units the program `unit` of `node` took the environment from and that go on: a
    row for each ({"unit", "name", "times" this node took it from that unit, "paused_seconds"
    in all, "seconds" it has run, "done" (its condition now), "says" (its own report),
    "asked" (it asks to be told)}), those of them that ask to be told (until(interrupted="tell")), and the place in the queue
    they ask for ("next" where one was told fewer than INTERRUPTIONS_TOLD times; else None)."""
    rows, asking, now = [], [], time.monotonic()
    entries = getattr(session, "_entries", None)
    for entry in dict.fromkeys(getattr(unit, "took", ())):
        if not entry.running:
            continue
        done = entries._completed(entry) if entries is not None else None
        rows.append({"unit": entry.id, "name": entry.name,
                     "times": sum(1 for pause in entry.pauses if pause["by"] == node.name),
                     "paused_seconds": round(sum((pause.get("until") or now) - pause["at"] for pause in entry.pauses), 1),
                     "seconds": round(time.time() - entry.started, 1),
                     **({"done": done} if done is not None else {}),
                     **(entries.reports(entry) if entries is not None else {})})
        # (A reflex's own program is the tree's: its node says what the model hears of it.)
        if entry.interrupted == "tell" and getattr(entry, "rule", None) is None:
            asking.append(entry)
            rows[-1]["asked"] = True
    place = "next" if any(entry.interruptions_told < INTERRUPTIONS_TOLD for entry in asking) else None
    return rows, asking, place


def counted(asking, told: bool) -> None:
    """The units that asked to be told of this interruption: counted as told where the
    message went out and they were told fewer than INTERRUPTIONS_TOLD times, else as one
    more that is told with their end."""
    for entry in asking:
        if told and entry.interruptions_told < INTERRUPTIONS_TOLD:
            entry.interruptions_told += 1
        else:
            entry.interruptions_untold += 1


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
        released, node.released = node.released, False
        retired, node.retired = node.retired, False
        if _interrupted(unit) and not released:
            # A node before it took the environment, or the tree gave its place to one: it
            # acts again when its turn comes. Ended by anyone else (the model cancelled it), it
            # is not tried again in this occurrence.
            node.spent = unit.status == "cancelled" and not retired
            continue
        node.last = report(unit)
        # What the model reads of this turn of the node: the node's own sentence and report, and
        # the units it took the environment from with theirs.
        rows, asking, theirs = interrupted_by(session, node, unit, view_of())
        with session.reporting():
            own_report = message(node.report, view_of(), unit.result)
        node.reads = {**({"about": node.about} if node.about else {}), **own_report,
                      **({"interrupted": rows} if rows else {})}
        node.asked, node.asking = theirs, asking
        if released or (unit.status == "done" and unit.ok is not False):
            node.did += 1
            node.told, node.spent = False, False
            # The node says whether the model hears that it did its work, and how soon: each
            # time, with its place in the queue, or the first time only (with the model's
            # next call), or never. A program it took the environment from may ask to be told
            # too (until(interrupted="tell")): one message, at the more urgent of the two places.
            own = node.tell if node.tell in QUEUE else "next" if node.tell == "first" and not node.acted else None
            place = urgent(own, theirs)
            counted(asking, not node.trying and place is not None)
            if not node.trying and place is not None:
                node.acted = node.acted or own is not None
                emit(tree, None, "reflex", Event(ev.REFLEX_ACTED, node.name, {
                    "reflex": node.name, "unit": unit.id, "began": node.triggered, **node.last, **node.reads,
                    "tell": place}, state.get("step")))
        else:
            # It failed, or it returned and its situation is not past: a failure. It is not
            # tried again in this occurrence; what comes after it acts.
            node.did_not += 1
            node.spent = True
            spans.note("rule", name=node.name, action="failed", unit=unit.id)
            failures.append((node, unit))
    if not session.can_act(state):
        # The agent cannot act: nothing is judged and nothing begins until it can.
        layer.tell()
        return

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
            if node.do is not None and node.holds != getattr(node, "noted_holds", False):
                # A node with a program: the record says when its situation comes and goes, so that a
                # node that held and did not act can be told from one that never held.
                node.noted_holds = node.holds
                spans.note("rule", name=node.name, action="holds" if node.holds else "over")
                if not node.holds:
                    node.noted_wait = None
            if node.waits:
                # Not judged in this period: again in the next one.
                layer.wake_at = now if layer.wake_at is None else min(layer.wake_at, now)
        return node.holds

    wanting, telling = [], []

    def past(node):
        # What a node's program is for: its situation is past. With `over`, that; without, its
        # condition (or that of a node it is under) no longer holds.
        if node.over is not None:
            return lambda view: layer._past(node, view)
        return lambda view: not (layer._above_hold(node, view) and layer._run(node, view))

    def release(node):
        # Its situation is past while its program runs: the program ends there, its work done.
        if node.unit is not None and node.unit.running and not node.released:
            node.released = True
            spans.note("rule", name=node.name, action="released", unit=node.unit.id)
            layer._retire(node)

    def ended(node):
        # The occurrence is over: what ran under it ends with it, and everything under it is
        # judged anew, a node that failed in it too, when the situation comes again.
        node.raised, node.spent = False, False
        for below in layer._below(node.name)[1:]:
            release(below)
            below.holds, below.raised, below.spent = _UNSEEN, False, False

    def walk(name):
        # The nodes at and under `name` that are in their situation, the earlier first; under a
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
            acting = node.unit is not None and node.unit.running
            if node.over is not None and (held or acting or node.spent) and layer._past(node, view_of()):
                # The situation is past by the node's own word: its program ends, its work done. (A node
                # that failed in it is asked too, whether its condition holds or not: its `over` alone
                # says when that occurrence is past, and the next one is tried anew.)
                release(node)
                ended(node)
                continue
            if not held and not acting and not (node.over is not None and node.spent):
                # Not in the situation. (A node with `over` that failed stays in its occurrence
                # until `over` holds: its condition coming and going does not make it new.) (Whether the model was told that the node failed stays:
                # it is told again only after the node has done its work, else a condition that
                # comes and goes tells the same failure every time.)
                ended(node)
                continue
            # In it: the condition holds, or its action, once begun, has no result yet.
            under = walk(node.name)
            if node.spent:
                # It failed in this occurrence: it does not act again in it. What is under it
                # had its turn before it; what comes after it acts.
                continue
            if node.action is not None:
                telling.append((node, before + under))
            elif node.do is not None:
                wanting.append((node, under))
            before += under + ([node] if node.do is not None else [])
        return before

    walk(None)

    def _waiting(node, why):
        # A node whose situation holds and whose program does not start: why, once for each reason.
        if getattr(node, "noted_wait", None) != why:
            node.noted_wait = why
            spans.note("rule", name=node.name, action="waiting", why=why)

    running = [entry for entry in tree.running() if entry.kind != "agent"]
    startable = set()
    for node, under in wanting:
        if any(found.name in startable for found in under):
            # A narrower situation under it is being answered: what the node does itself
            # gives way, also where it already runs.
            layer._retire(node)
            _waiting(node, "a node under it answers a narrower situation")
            continue
        if node.unit is not None:
            startable.add(node.name)
            continue
        rank = layer.rank(node)
        # (The programs of the nodes it is under give way to it: they do not keep it waiting.)
        giving_way = {above.name for above in layer._above(node)}
        # (Where the environment pauses and has channels, only a unit that uses one of the
        # channels the node's program uses is before it: the others go on beside it.)
        ticker = session.__dict__.get("_tick_loop")
        shares = ticker is not None and ticker.channels and not ticker.merges
        # (A unit that uses no channel is before nobody, and a node that uses none waits for nobody.)
        above = None if node.claims == () else next((
            entry for entry in running if entry.rank > rank and not getattr(entry, "channelless", False)
            and getattr(entry, "rule", None) not in giving_way
            and (not shares or ticker.overlaps(entry, node.claims))), None)
        if above is not None:
            # What is before it has the environment: its turn is judged when that ends. Where
            # that is a program that said so (at_priority), the model is told once.
            if getattr(above, "rule", None) is None:
                if node.kept_by != above.id:
                    node.kept_by = above.id
                    spans.note("held_back", rule=node.name, priority=rank, by=above.id, by_name=above.name)
                layer.changed = True
            else:
                _waiting(node, f"the node {above.rule} runs before it")
            continue
        node.kept_by = None
        node.noted_wait = None
        node.triggered += 1
        node.unit = tree.spawn(node.do, name=node.name, rule=node.name, priority=rank, quiet=True,
                               until=past(node), claims=list(node.claims) if node.claims else None,
                               channelless=node.claims == ())
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
        if not node.raised:
            node.raised = True
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
        place = None if node.told or taken else urgent(node.tell_failed, getattr(node, "asked", None))
        counted(getattr(node, "asking", ()), place is not None)
        if node.told or taken:
            continue
        node.told = True
        if place is None:
            continue
        emit(tree, None, "reflex", Event(ev.REFLEX_FAILED, node.name, {
            "reflex": node.name, "unit": unit.id, "began": node.triggered, **node.last,
            **(getattr(node, "reads", None) or {}), "tell": place}, state.get("step")))
