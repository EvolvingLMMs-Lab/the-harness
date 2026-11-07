"""Spans: when each part of an episode worked, for the timeline of a run.

A span is a stretch of wall-clock time one part spent on one thing: the main model
answering, a program running, a skill's bounded execution, one call to a service. It
starts with a `span_start` record and ends with a `span_end` record of the same id. A
span of code an entry runs (runtime/execution/entries.py) names that entry (`entry`); the entries
themselves start and end with `entry_start` and `entry_end` records.
Parts of the host (the conversation) write them to the trace themselves; code in the
kernel process writes them through the sink the kernel installs (runtime/execution/kernel.py),
and the host adds them to the trace as they arrive. Without a sink a span costs
nothing and records nothing.

A span's `lane` names the kind of part that worked (PARTS). The timeline does not draw
one lane per kind: core/lanes.py reads the lanes from the records, one per entry (and
the model, the verifier, the environment), as they start and end.
"""

from contextlib import contextmanager
import threading
import time
import uuid


# The kinds of part a span is of (its `lane` field).
PARTS = ("model", "verifier", "program", "skill", "service", "env")

_sink = None
_local = threading.local()


def _emit(record) -> None:
    try:
        _sink(record)
    except Exception:
        # A span that cannot be sent is lost; the code it records goes on.
        pass


def note(kind: str, **detail) -> None:
    """Send the host a note of `kind` (a plan the user sees) now, while the program runs;
    nothing without a sink."""
    if _sink is not None:
        _emit({"op": "note", "kind": kind, "time": time.time(), **detail})


def step(skill: str, number: int, what: str, ok: bool, seconds: float | None = None, reason: str | None = None,
         of: int | None = None, library=None) -> None:
    """Say a step of a skill's plan ended (step `number` of `of`, what it did, whether it
    did it, in how many seconds, why not): a skill_step record, news for the model's next
    look while the program runs (runtime/conversation.py); nothing without a sink. A step
    of a library entry's test or replay says so (`testing`, set by testing())."""
    note("skill_step", skill=skill, step=int(number), what=str(what)[:200], ok=bool(ok),
         **({"seconds": round(float(seconds), 1)} if seconds is not None else {}),
         **({"reason": str(reason)[:300]} if reason else {}), **({"of": int(of)} if of else {}),
         **({"library_key": library[0], "library_sha256": library[1]} if library else {}),
         **({"library_revision": library[2]} if library and len(library) > 2 else {}),
         **({"testing": True} if in_test() else {}))


def in_test():
    return getattr(_local, "testing", False)


@contextmanager
def testing(active=True):
    """Keep proposal and replay steps out of practice use counts."""
    previous = in_test()
    _local.testing = active
    try:
        yield
    finally:
        _local.testing = previous


def record(op: str, **detail) -> None:
    """Send the host a record `op` other than a span's (an entry's start or end, with
    `detail`) now; nothing without a sink."""
    if _sink is not None:
        _emit({"op": op, "time": time.time(), **{key: _short(value) for key, value in detail.items()}})


def set_entry(entry):
    """The spans this thread records from now on name `entry` (an entry id; None: none);
    the one they named before."""
    saved = _local.__dict__.get("entry")
    _local.entry = entry
    return saved


def current_entry():
    return getattr(_local, "entry", None)


def connected() -> bool:
    """Whether notes reach a host (a kernel installed the sink)."""
    return _sink is not None


def set_sink(sink) -> None:
    """Send every span record from now on to `sink(record)` (None: record nothing)."""
    global _sink
    _sink = sink


def current():
    """The id of the span this thread is in (None outside every span)."""
    stack = _local.__dict__.get("stack")
    return stack[-1] if stack else None


@contextmanager
def under(parent):
    """Spans recorded inside have `parent` (a span id from current(), or None) as their
    parent: code another thread runs for a span (the tick runs a skill's steps)."""
    saved = _local.__dict__.get("stack")
    _local.stack = [parent] if parent is not None else []
    try:
        yield
    finally:
        _local.stack = saved if saved is not None else []


def _short(value, limit=200):
    """A value as a span detail keeps it: JSON scalars as they are, anything else as a
    clipped repr (parameters may hold arrays or callables)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "..."
    if isinstance(value, (list, tuple)) and len(value) <= 16 and all(
            item is None or isinstance(item, (bool, int, float, str)) for item in value):
        return [_short(item, limit) for item in value]
    if isinstance(value, dict) and len(value) <= 16:
        return {str(key): _short(item, limit) for key, item in value.items()}
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


@contextmanager
def span(lane: str, name: str, **detail):
    """Record the code inside as a span of the part `lane` (PARTS) named `name` with `detail`. Yields a
    dict whose items end up in the span's end record (an event kind, a status); an
    exception leaving the block is recorded as the span's error and raised on."""
    if _sink is None:
        yield {}
        return
    stack = _local.__dict__.setdefault("stack", [])
    identifier = uuid.uuid4().hex[:12]
    record = {"op": "span_start", "id": identifier, "lane": lane, "name": name, "time": time.time(),
              "parent": stack[-1] if stack else None, **{key: _short(value) for key, value in detail.items()}}
    if _local.__dict__.get("entry") is not None:
        record["entry"] = _local.entry
    _emit(record)
    stack.append(identifier)
    end = {}
    try:
        yield end
    except BaseException as error:
        # An execution's event raised as an escalation is its end, not an error.
        if "event_kind" not in end:
            end.setdefault("error", f"{type(error).__name__}: {_short(str(error))}")
        raise
    finally:
        stack.pop()
        _emit({"op": "span_end", "id": identifier, "time": time.time(),
               **{key: _short(value) for key, value in end.items()}})
