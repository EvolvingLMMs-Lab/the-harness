"""The host side of a managed kernel: trusted admission of an isolated kernel's proposals.

A managed kernel runs the model's programs in an isolated process that holds nothing but
the names of the operations it may propose. Its programs are units like those of any
kernel (runtime/execution/kernel.py: side by side, the reply within the grace, unit_end).
The session that acts lives here, in the host, and every program of the isolated kernel
has a unit in this session's tree (runtime/execution/entries.py): a proposal runs as that
unit, so its executions, events, pictures and priority are the unit's own and are kept by
the host. Of the isolated process a result takes only the output text and how the code
ended; everything else is what the host kept.
"""

import math
import threading
import time

from harness.runtime import events as ev
from harness.runtime.events import EpisodeEnded, Escalation, Event, ExecutionTrace
from harness.runtime.execution.entries import Cancelled


# What a program's result may say of how its code ended, on the isolated kernel's word.
STATUSES = ("ok", "error", "finished")
INTERRUPTED = "The managed program was interrupted"


class Admission:
    """The units of one managed kernel and the admission of their proposals onto
    `session`, for `conversation` (runtime/task/run.py). `operations`: the session's calls a
    program may propose. The kernel handle (runtime/execution/kernel.py Kernel) calls
    begin, running, submit, accept_result and result as the isolated process's messages
    come; stop, resume and cancel are the host's own."""

    def __init__(self, conversation, session, operations):
        self._conversation, self.session, self.operations = conversation, session, tuple(operations)
        self._condition = threading.Condition()
        # The programs whose result has not come: {cell: {"entry", "last", "thread", "began", "running"}};
        # those whose result came (a late message of theirs is left out).
        self._cells = {}
        self._settled = set()
        self._stopped = False

    def options(self) -> dict:
        """What the isolated kernel is started with."""
        return {"operations": self.operations}

    # The host's controls.

    def stopped(self) -> bool:
        """Whether nothing may act now: the host stopped the units, or its conversation is
        paused or closing."""
        return self._stopped or self._conversation._pause or self._conversation._closing

    def stop(self) -> None:
        """Stop the units: every proposal is refused until resume()."""
        with self._condition:
            self._stopped = True

    def resume(self) -> None:
        with self._condition:
            self._stopped = False

    def cancel(self, unit=None) -> list:
        """Cancel the unit `unit` (None: all): its execution ends and its proposals are
        refused. The cells cancelled."""
        with self._condition:
            cells = [cell for cell, record in self._cells.items() if unit is None or record["entry"].id == unit]
            for cell in cells:
                self._cells[cell]["entry"]._cancel.set()
        return cells

    def close(self) -> None:
        self.stop()
        self.session.close()

    # What the kernel handle calls.

    def begin(self, cell, name=None) -> str:
        """A program is sent to the isolated kernel as `cell`: its unit here. The unit's id."""
        tree = self.session._entries
        entry = tree._add(str(name or f"cell {cell}"), "program", tree.root, (), cell=cell)
        with self._condition:
            self._cells[cell] = {"entry": entry, "last": 0, "thread": None, "began": time.time(), "running": False}
        self._record({"op": "entry_start", "id": entry.id, "parent": tree.root.id, "name": entry.name,
                      "kind": "program", "cell": cell})
        return entry.id

    def unit(self, cell):
        """The id of the unit of `cell`, or None when its result has come."""
        with self._condition:
            record = self._cells.get(cell)
            return record["entry"].id if record is not None else None

    def running(self, cell):
        """The isolated kernel says `cell` still runs after its grace: the unit's id, or
        None when it may not say so (no such program, or said before)."""
        with self._condition:
            record = self._cells.get(cell) if type(cell) is int else None
            if record is None or record["running"]:
                return None
            record["running"] = True
            return record["entry"].id

    def settled(self, cell) -> bool:
        """Whether the result of `cell` has come (a later message of it is left out)."""
        with self._condition:
            return type(cell) is int and cell in self._settled

    def accept_result(self, cell) -> bool:
        """Whether a result for `cell` is taken: once for each program."""
        with self._condition:
            if type(cell) is not int or cell not in self._cells or cell in self._settled:
                return False
            self._settled.add(cell)
            return True

    def submit(self, message, reply) -> bool:
        """Admit a proposal of a unit: run it as that unit on a thread of its own and
        answer with `reply`. False for a message that breaks the protocol (no such
        program, an answer still due, an id out of order): the kernel handle ends the
        isolated process. A proposal of a unit that is stopped, cancelled or over is
        refused with an answer."""
        with self._condition:
            identifier, cell = message.get("id"), message.get("cell")
            if type(identifier) is not int or type(cell) is not int:
                return False
            record = self._cells.get(cell)
            if record is None:
                return False
            refused = cell in self._settled or record["entry"]._cancel.is_set() or self.stopped()
            if record["thread"] is not None or identifier <= record["last"]:
                return False
            record["last"] = identifier
            if not refused:
                record["thread"] = threading.Thread(target=self._run, args=(record, message, reply), daemon=True,
                                                    name="managed-proposal")
                record["thread"].start()
                return True
        try:
            reply({"error": INTERRUPTED})
        except OSError:
            pass
        return True

    def _run(self, record, message, reply):
        response = {"error": "The managed proposal ended"}
        try:
            with self.session._entries.acting(record["entry"]):
                response = {"value": self._perform(message.get("name"), message.get("args"), message.get("kwargs"))}
        except (Escalation, EpisodeEnded) as error:
            response = {"error": f"{error.trace.event.kind}: {error.trace.event.detail}"}
        except Cancelled:
            response = {"error": INTERRUPTED}
        except Exception as error:
            response = {"error": str(error)[:500] or type(error).__name__}
        finally:
            with self._condition:
                record["thread"] = None
                self._condition.notify_all()
        try:
            reply(response)
        except OSError:
            pass

    def _perform(self, name, args, kwargs):
        if (not isinstance(name, str) or name not in self.operations or type(args) is not list
                or type(kwargs) is not dict or len(args) + len(kwargs) > 12
                or any(type(value) not in (str, int, float, bool, type(None)) or
                       (isinstance(value, str) and len(value) > 8192)
                       or (type(value) is float and not math.isfinite(value))
                       for value in [*args, *kwargs.values()])):
            raise ValueError("Unsupported managed workspace proposal")
        with self._conversation._condition:
            if self.stopped():
                raise RuntimeError(INTERRUPTED)
        session = self.session
        if name == "show":
            if args or set(kwargs) - {"caption"}:
                raise ValueError("Managed show() takes only an optional caption")
            session.show(session.get_observation(), kwargs.get("caption"))
            return None
        result = getattr(session, name)(*args, **kwargs)
        if name == "get_observation":
            return {"state": result.state, "images": result._urls}
        if isinstance(result, ExecutionTrace):
            return result.to_dict()
        return result

    def result(self, message, cell) -> dict:
        """The result of the program `cell` (accept_result took it): of the isolated
        kernel's `message` only the output text and how the code ended; the state, the
        events, the pictures and the views are what this session kept for the unit."""
        with self._condition:
            record = self._cells.pop(cell)
            # (A proposal still at work ends first: what it does is the unit's.)
            entry = record["entry"]
            self._condition.wait_for(lambda: record["thread"] is None, timeout=125)
        out = {name: message[name][:8000] for name in ("stdout", "error", "finish") if isinstance(message.get(name), str)}
        status = message.get("status")
        if status not in STATUSES:
            if entry._cancel.is_set():
                status = "cancelled"
            elif self.stopped():
                # The host stopped it: the pause's event, in the host's own words.
                status, out["escalation"] = "escalated", ExecutionTrace(
                    "program", {}, 0, 0, Event(ev.USER_PAUSED, "user")).to_dict()
            else:
                status = "error"
                out.setdefault("error", "The program did not end normally")
        out.update(status=status, unit=entry.id, name=entry.name, kind="program", cell=cell,
                   seconds=time.time() - record["began"])
        tree = self.session._entries
        try:
            with tree.acting(entry):
                out.update(self.session.drain())
        except Exception as error:
            out["drain_error"] = f"{type(error).__name__}: {error}"
        ended = "done" if status in ("ok", "finished") else "cancelled" if status in ("cancelled", "escalated") else "failed"
        tree._end(entry, ended, error=out.get("error") if ended == "failed" else None)
        self._record({"op": "entry_end", "id": entry.id, "status": ended})
        return out

    def _record(self, record) -> None:
        """A unit's start or end, as the conversation hears it of any kernel."""
        hear = getattr(self._conversation, "_kernel_span", None)
        if hear is not None:
            hear({**record, "time": time.time()})
