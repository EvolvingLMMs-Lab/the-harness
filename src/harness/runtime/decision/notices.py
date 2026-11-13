"""What reaches the model: one queue of notices.

Everything that reaches the model by itself is a notice in one queue: a message (of the
user, of the agent that started this one, of the environment), an event, the end of a
unit, a note of the host. A notice has a priority, given by what puts it there:

    now     the model's call in flight is set aside and made again with the notice; a
            reply that did not know of it does nothing
    next    the call in flight goes on; the notice is told with the model's next call
    later   told with the first call made after a wait of the model, or with the call
            that begins its next turn

Every notice ends a wait of the model and, between turns, begins one; but one that does
not wake (the end of a unit that was cancelled) is only told along with the next call.
Those told with one call come the more urgent first, each priority in order of arrival.
What a reply of the model itself comes to (its program's handle, the end of its wait, a
format error) is not a notice: it is the first thing the next call is told
(runtime/task/run.py _deliver).
"""

from dataclasses import dataclass

NOW, NEXT, LATER = "now", "next", "later"
PRIORITIES = (NOW, NEXT, LATER)


@dataclass
class Notice:
    """`kind`: "message", "event", "unit" or "note"; `data`: what its kind tells (the
    message's sender, text and parts; the event's record; the unit's result; the note's
    text)."""
    kind: str
    priority: str
    data: object
    wakes: bool = True


class Notices:
    """The queue. Not locked: whoever owns it holds its lock."""

    def __init__(self):
        self._items = []

    def put(self, notice: Notice) -> None:
        if notice.priority not in PRIORITIES:
            raise ValueError(f"a notice's priority is one of {PRIORITIES}, got {notice.priority!r}")
        self._items.append(notice)

    def _found(self, upto, kinds, waking):
        level = PRIORITIES.index(upto)
        return [notice for notice in self._items
                if PRIORITIES.index(notice.priority) <= level and (kinds is None or notice.kind in kinds)
                and (not waking or notice.wakes)]

    def pending(self, upto: str = LATER, kinds=None, waking: bool = False) -> list:
        """The notices of priority `upto` or more urgent (of `kinds`; `waking`: those that
        wake), in the order they are told."""
        found = self._found(upto, kinds, waking)
        return sorted(found, key=lambda notice: PRIORITIES.index(notice.priority))

    def take(self, upto: str = LATER, kinds=None) -> list:
        """Remove and return them."""
        found = self.pending(upto, kinds)
        taken = {id(notice) for notice in found}
        self._items = [notice for notice in self._items if id(notice) not in taken]
        return found
