"""Memory (runtime/task/context.py): what this run saw and where, and the library's memory
entries, through one interface. The run's working memory is the host's (shared with the
sub-agents); without a host (a test, a script) the kernel keeps one of its own."""

import time
import uuid

from harness.sdk import Escalation, control, spans

# A request the host has not answered in this long fails (it never hangs a program).
ANSWER_SECONDS = 60.0


class ReadOnlyMemory:
    def recall(self, query, k=5):
        """Search the same memory while keeping the original read-only call signature."""
        return Memory._memory(self, "recall", query=query, k=k)


class Memory:
    def remember(self, kind, text="", where=None, name=None, confidence=0.5, keep=False):
        """Remember an observation or note. keep=True saves the same entry in a writable library."""
        return self._memory_remember(kind, where, text, confidence, self._memory_writer(),
                                     name=name, wait=True, keep=keep)

    def recall(self, query=None, k=5, kind=None, near=None, radius=None):
        """Entries of this run's memory and the library's memory, best first: those of `kind`
        (a name, or a family: "ore" finds "ore:iron"), nearest to `near` first (default:
        where you are, when the worker says; "distance") within `radius`, else best for
        `query` ("score"), else this run's newest first; entries without a position come
        after the placed ones (none within a `radius`). Each {"id", "scope": "run" or
        "library", "kind", "name", "text", "where", "evidence", ...}."""
        here, space = self._memory_here()
        if near is None and radius is not None:
            near = here
        return self._memory("recall", query=query, k=int(k), kind=kind, radius=radius, space=space,
                            near=None if near is None else [float(v) for v in near])

    def forget(self, ident):
        """Forget a visible memory by ID. A kept entry requires a writable library."""
        return self._memory("forget", id=ident, space=self._memory_here()[1])

    # -- inside --------------------------------------------------------------------------

    def _memory(self, action, wait=True, **request):
        request = {key: value for key, value in request.items() if value is not None}
        if spans.connected():
            # A note's own fields are kind and id: an entry's travel as "of" and "entry".
            identifier = uuid.uuid4().hex[:12]
            spans.note("memory", action=action, id=identifier, wait=wait,
                       **{{"kind": "of", "id": "entry"}.get(key, key): value for key, value in request.items()})
            if not wait:
                return None
            deadline = time.monotonic() + ANSWER_SECONDS
            answer = control.wait_answer(identifier, poll=None, deadline=deadline)
            if answer is None:
                if control.pause_requested():
                    raise control.stopped("memory")
                raise RuntimeError("the host did not answer the memory request within 60 seconds")
            if answer.get("error"):
                raise RuntimeError(answer["error"])
            return answer.get("value")
        own = Memory._memory_own(self)
        given = getattr(self, "library_given", None) or {}
        persist = None
        if given.get("directory") and (given.get("settings") or {}).get("learn") == "on":
            from harness.sdk import Learner

            learner = Learner(given["directory"], given.get("settings"))
            def persist(item, *, forgotten=False):
                changed = learner.store_memory(item, forgotten=forgotten)
                own.library = [entry for entry in own.library if entry["id"] != item["id"]]
                if not forgotten:
                    own.kept(changed)
                return changed
        return own.handle({"action": action, **request}, persist=persist)

    def _memory_own(self):
        """The kernel's own store, without a host (a test, a script): the library's memory
        entries as it starts."""
        own = self.__dict__.get("_memory_own_store")
        if own is None:
            from harness.sdk import Learner, WorkingMemory, memory_entries

            own = self.__dict__["_memory_own_store"] = WorkingMemory()
            given = getattr(self, "library_given", None) or {}
            if given.get("directory"):
                own.library = memory_entries(Learner(given["directory"], given.get("settings")).library)
            elif getattr(self, "memory", None):
                from harness.runtime.task.context import entry

                own.library = [entry({"kind": "memory", "id": item["name"], **item}, "library")
                               for item in self.memory]
        return own

    def _memory_remember(self, kind, where, text="", confidence=0.5, source=None, name=None, wait=False, keep=False):
        """A note from a skill, a service or the tick (no wait for the host by default)."""
        space = self._memory_here()[1]
        return self._memory("remember", wait=wait, kind=str(kind), text=str(text or ""), name=name,
                            where=where if where is None or isinstance(where, str) else [float(v) for v in where],
                            confidence=float(confidence), source=source, space=space, keep=keep)

    def _memory_here(self):
        """(position, space) of the body now, when the worker's state says ("here")."""
        state = getattr(self, "state", None) or {}
        return (state.get("here"), state.get("space")) if isinstance(state, dict) else (None, None)

    def _memory_writer(self):
        """Who writes, when the program does not say: None for the agent's own programs (the
        host puts the agent's name), "<agent>/<entry>" inside an entry."""
        entries = self.__dict__.get("_entries")
        current = entries.current() if entries is not None else None
        if current is None or current is getattr(entries, "root", None):
            return None
        return "program"


def turn_report(session):
    """After each program: recent notes and the nearest fresh places."""
    from harness.embodiments import KINDS

    kind = KINDS.get(getattr(session, "embodiment", None))
    if kind is not None and not kind.memory_report:
        return None
    here, space = session._memory_here()
    try:
        text = session._memory("summary", near=here, space=space)
    except (Escalation, RuntimeError):
        return None                     # paused: the host answers nothing now
    return {"text": "Memory: notes and nearby places (recall() for more):\n" + text} if text else None
