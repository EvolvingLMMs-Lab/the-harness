"""The reactive layer as a behavior tree.

A tree is judged like a rule: when the state or the facts change, when one of the programs
it started ends, or on time (`every`). Judging it walks it from the root, and every node
answers RUNNING, SUCCESS or FAILURE:

    select(children...)     the first child that does not fail has the environment; when a
                            child before the one that runs stops failing, it takes over and
                            the one that ran is ended
    sequence(children...)   the children one after the other; it fails when one does; ended
                            from outside it begins again at its first child
    branch(begins, child)   the child while a condition says so: it begins when begins(view)
                            holds, is ended when ends(view) comes to hold (not before
                            min_seconds) or, with while_holds, when begins(view) no longer
                            holds, and may begin again again_seconds after it was over
    do(program)             a leaf: start the program as a unit; SUCCESS when it ended well
    check(condition)        a leaf: SUCCESS while the condition holds
    raise_event(name)       a leaf: raise an event to the model, once each time its branch
                            begins
    ref(name, **arguments)  the subtree of that name (ReactiveLayer.subtree), wherever it is
                            used; defining the subtree again changes every place

A node's place is its priority: nothing is numbered inside a tree. A condition placed above
a part of the tree holds for everything below it, and a subtree used by many behaviours is
one thing to repair.

Only one branch of a tree runs at a time, so what a node ends is the leaf that runs below
it: its program is cancelled, and the tree goes back into that branch by itself when it is
judged again. When a node has just completed, the tree is judged again at once, and a node
that waits for its time (again_seconds, a leaf that just ran) has the tree judged when that
time comes: a tree goes on by itself. The units a tree starts are its own business: their ends are recorded and
start no call of the model; the model is told when a leaf's program fails and nothing else
in the tree takes it (the event BRANCH_FAILED).
"""

from copy import deepcopy
import threading

RUNNING, SUCCESS, FAILURE = "running", "success", "failure"
# A leaf whose program failed is not started again before this many seconds, and no leaf is
# started more often than once in RESTART_SECONDS: a tree does not spin on a program.
FAILED_AGAIN_SECONDS = 2.0
RESTART_SECONDS = 0.2


class Node:
    kind = "node"
    name = None
    status = None

    def tick(self, ctx) -> str:
        raise NotImplementedError

    def judge(self, ctx) -> str:
        self.status = self.tick(ctx)
        return self.status

    def abort(self, ctx) -> None:
        """End what runs below this node (it was taken over or its branch is over)."""
        for child in self.children():
            child.abort(ctx)
        self.status = None

    def reset(self) -> None:
        """Its branch's condition stopped holding: what happens once per beginning may happen again."""
        for child in self.children():
            child.reset()

    def children(self) -> tuple:
        return ()

    def units(self) -> list:
        return [unit for child in self.children() for unit in child.units()]

    def describe(self) -> dict:
        data = {"kind": self.kind, **({"name": self.name} if self.name else {}),
                **({"status": self.status} if self.status else {})}
        inside = [child.describe() for child in self.children()]
        return {**data, "children": inside} if inside else data


def as_node(given) -> Node:
    """A child as it may be written: a node, or a program (do(program))."""
    if isinstance(given, Node):
        return given
    if callable(given):
        return Do(given)
    raise TypeError(f"a tree is made of nodes and programs, not {given!r:.60}")


class Do(Node):
    kind = "do"

    def __init__(self, program, name=None):
        if not callable(program):
            raise TypeError("do() starts a program: a function")
        self.program = program
        named = getattr(program, "__name__", None)
        self.name = name or (named if named and named != "<lambda>" else "program")
        self.unit, self.again_at, self.told = None, 0.0, False

    def tick(self, ctx):
        if self.unit is None:
            if ctx.now < self.again_at:
                ctx.wake(self.again_at)
                return FAILURE
            self.unit = ctx.start(self)
            return RUNNING
        if self.unit.running:
            return RUNNING
        unit, self.unit = self.unit, None
        if unit.status == "done":
            self.again_at, self.told = ctx.now + RESTART_SECONDS, False
            return SUCCESS
        self.again_at = ctx.now + FAILED_AGAIN_SECONDS
        ctx.failed(self, unit)
        return FAILURE

    def abort(self, ctx):
        unit, self.unit = self.unit, None
        if unit is not None and unit.running:
            ctx.end(unit)
        self.status = None

    def units(self):
        return [self.unit] if self.unit is not None else []


class Check(Node):
    kind = "check"

    def __init__(self, condition, name=None):
        if not callable(condition):
            raise TypeError("check() takes a condition: a function of the view")
        self.condition, self.name = condition, name

    def tick(self, ctx):
        return SUCCESS if ctx.holds(self, self.condition) else FAILURE


class Raise(Node):
    kind = "raise_event"

    def __init__(self, event, name=None):
        if not isinstance(event, str) or not event.replace("_", "").isalnum():
            raise ValueError(f"an event's name is an identifier like LOW_BATTERY, got {event!r}")
        self.event, self.name, self.armed = event, name or event, True

    def tick(self, ctx):
        if self.armed:
            self.armed = False
            ctx.raise_event(self)
        return SUCCESS

    def reset(self):
        self.armed = True


class Select(Node):
    kind = "select"

    def __init__(self, *children, name=None):
        if not children:
            raise ValueError("select() takes its children, the first before the others")
        self.nodes, self.name, self.running = tuple(as_node(child) for child in children), name, None

    def children(self):
        return self.nodes

    def tick(self, ctx):
        for index, child in enumerate(self.nodes):
            status = child.judge(ctx)
            if status == FAILURE:
                continue
            if self.running is not None and self.running != index:
                # A child before the one that ran has the environment now (or the one that ran is over).
                self.nodes[self.running].abort(ctx)
            self.running = index if status == RUNNING else None
            return status
        if self.running is not None:
            self.nodes[self.running].abort(ctx)
            self.running = None
        return FAILURE

    def abort(self, ctx):
        super().abort(ctx)
        self.running = None


class Sequence(Node):
    kind = "sequence"

    def __init__(self, *children, name=None):
        if not children:
            raise ValueError("sequence() takes its children in their order")
        self.nodes, self.name, self.at = tuple(as_node(child) for child in children), name, 0

    def children(self):
        return self.nodes

    def tick(self, ctx):
        while True:
            status = self.nodes[self.at].judge(ctx)
            if status == RUNNING:
                return RUNNING
            if status == FAILURE:
                self.at = 0
                return FAILURE
            self.at += 1
            if self.at == len(self.nodes):
                self.at = 0
                return SUCCESS

    def abort(self, ctx):
        super().abort(ctx)
        self.at = 0

    def describe(self):
        return {**super().describe(), "at": self.at + 1}


class Branch(Node):
    kind = "branch"

    def __init__(self, begins, child, ends=None, min_seconds=0.0, again_seconds=0.0, while_holds=False, name=None):
        if not callable(begins) or (ends is not None and not callable(ends)):
            raise TypeError("a branch begins (and ends) on a condition: a function of the view")
        for label, seconds in (("min_seconds", min_seconds), ("again_seconds", again_seconds)):
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
                raise ValueError(f"{label} is a number of seconds >= 0, got {seconds!r}")
        self.begins, self.ends, self.child, self.name = begins, ends, as_node(child), name
        self.min_seconds, self.again_seconds, self.while_holds = float(min_seconds), float(again_seconds), bool(while_holds)
        self.active, self.began, self.ready_at = False, 0.0, 0.0

    def children(self):
        return (self.child,)

    def tick(self, ctx):
        if not self.active:
            if ctx.now < self.ready_at:
                ctx.wake(self.ready_at)
                return FAILURE
            if not ctx.holds(self, self.begins):
                self.child.reset()
                return FAILURE
            self.active, self.began = True, ctx.now
        elif ctx.now - self.began >= self.min_seconds:
            if self.ends is not None and ctx.holds(self, self.ends):
                return self._over(ctx, SUCCESS)
            if self.while_holds and not ctx.holds(self, self.begins):
                self.child.reset()
                return self._over(ctx, FAILURE)
        status = self.child.judge(ctx)
        if status != RUNNING:
            self.active, self.ready_at = False, ctx.now + self.again_seconds
        return status

    def _over(self, ctx, status):
        self.child.abort(ctx)
        self.active, self.ready_at = False, ctx.now + self.again_seconds
        return status

    def abort(self, ctx):
        super().abort(ctx)
        if self.active:
            self.active, self.ready_at = False, ctx.now + self.again_seconds

    def describe(self):
        return {**super().describe(), "active": self.active}


class Ref(Node):
    kind = "ref"

    def __init__(self, name, arguments=None):
        if not isinstance(name, str) or not name:
            raise ValueError("ref() names a subtree")
        self.name, self.arguments, self.node, self.version = name, dict(arguments or {}), None, None

    def children(self):
        return (self.node,) if self.node is not None else ()

    def tick(self, ctx):
        made, version = ctx.subtree(self.name)
        if version != self.version:
            # The subtree was defined (again): what ran of the old one is ended.
            if self.node is not None:
                self.node.abort(ctx)
            self.node = as_node(made(**self.arguments)) if callable(made) and not isinstance(made, Node) \
                else deepcopy(made)
            self.version = version
        return self.node.judge(ctx)


class Tree:
    """A tree set in a session: its root, the priority its programs hold the environment
    with, and when it is judged (`every` seconds; None: at every change and whenever one of
    its programs ends)."""

    def __init__(self, name, root, priority=1, every=None, owner=None):
        self.name, self.root, self.priority, self.every, self.owner = name, as_node(root), priority, every, owner
        self.next_at, self.kept_by, self.library_origin = 0.0, None, None
        self.wake_at = None   # when a node that waits for its time wants the tree judged again

    def due(self, now) -> bool:
        if self.every is None or any(not unit.running for unit in self.root.units()):
            return True
        if self.wake_at is not None and now >= self.wake_at:
            return True
        if now >= self.next_at:
            self.next_at = max(self.next_at + self.every, now + self.every / 2)
            return True
        return False

    def end(self, ctx=None) -> None:
        """The tree goes: what it started is ended."""
        for unit in self.root.units():
            if unit.running:
                threading.Thread(target=unit.cancel, name=f"tree-{self.name}", daemon=True).start()

    def describe(self) -> dict:
        return {"name": self.name, "priority": self.priority, "does": "a tree",
                "running": bool(self.root.units()), "tree": self.root.describe()}


class Judgement:
    """One judgement of a tree: the view, the time, and what its nodes may do."""

    def __init__(self, tree, view, now, start, holds, raise_event, subtree):
        self.tree, self.view, self.now = tree, view, now
        self._start, self._holds, self._raise, self._subtree = start, holds, raise_event, subtree
        self.failures, self.wake_at = [], None

    def wake(self, at) -> None:
        self.wake_at = at if self.wake_at is None else min(self.wake_at, at)

    def start(self, node):
        return self._start(self.tree, node)

    def end(self, unit) -> None:
        threading.Thread(target=unit.cancel, name=f"tree-{self.tree.name}", daemon=True).start()

    def holds(self, node, condition) -> bool:
        return bool(self._holds(node.name or node.kind, condition, self.view))

    def raise_event(self, node) -> None:
        self._raise(self.tree, node)

    def subtree(self, name):
        return self._subtree(name)

    def failed(self, node, unit) -> None:
        self.failures.append((node, unit))


def judge(tree: Tree, ctx: Judgement) -> list:
    """Walk the tree once. The leaves whose programs failed without anything else in the
    tree taking it, and that the model was not told of since they last succeeded:
    [(node, unit)]."""
    status = tree.root.judge(ctx)
    tree.wake_at = ctx.wake_at
    if status != FAILURE:
        return []
    news = [(node, unit) for node, unit in ctx.failures if not node.told]
    for node, _ in news:
        node.told = True
    return news

