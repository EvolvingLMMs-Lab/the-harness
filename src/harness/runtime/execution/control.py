"""What the host asks of a running program besides its cells.

The kernel process reads the host's requests on a thread of its own, so a request
reaches a program while it runs: a pause (the user paused the conversation) makes the
next step of a bounded execution end it with USER_PAUSED (runtime/execution/session.py). A
message for the model (the user's, or the parent agent's) interrupts the program's own
code, not the entries it started: its execution ends at the next step with USER_MESSAGE,
and a wait of it (an entry's wait(), wait_agents()) raises that event at once
(runtime/execution/entries.py). The flags are cleared when the next cell starts. An answer is the host's reply to a request a
program sent it as a note (the user's answer to a physical-input request,
runtime/safety/input.py): the program waits for it, or for a pause. When a sub-agent the
program started ends, the host says so, and its entry ends (runtime/execution/entries.py).
"""

import sys
import threading
import time
import uuid


_pause = threading.Event()
_message = threading.Event()
_answers = {}
_answered = threading.Condition()
_agent_listeners = []
_thoughts = set()
_physical = set()
_worker_calls = set()
host_thoughts = False


def request_pause() -> None:
    """Ask the running program to stop at its next execution step."""
    with _answered:
        _pause.set()
        _answered.notify_all()


def request_message() -> None:
    """Tell the running program a message for the model came."""
    with _answered:
        _message.set()
        _answered.notify_all()


def clear() -> None:
    """Forget earlier requests (a new cell starts)."""
    _pause.clear()
    _message.clear()


def message_arrived() -> bool:
    """Whether a message for the model came while the program runs."""
    return _message.is_set()


def pause_requested() -> bool:
    """Whether the host asked the running program to pause."""
    return _pause.is_set()


def wake_waiters():
    with _answered:
        _answered.notify_all()


def answer(identifier, value) -> None:
    """The host's answer to the request `identifier`."""
    with _answered:
        identifier = str(identifier)
        if isinstance(value, dict) and value.get("thought") and identifier not in _thoughts:
            return
        if isinstance(value, dict) and value.get("physical") and identifier not in _physical:
            return
        if isinstance(value, dict) and value.get("worker") and identifier not in _worker_calls:
            return
        _answers[identifier] = value
        _answered.notify_all()


def wait_answer(identifier, poll: float | None = None, stop=None, *, deadline: float | None = None,
                interruptible=True):
    """Wait for the host's answer, an interruption or an absolute monotonic deadline."""
    identifier = str(identifier)
    with _answered:
        while identifier not in _answers:
            if poll == 0 or (interruptible and _pause.is_set()) or (stop is not None and stop()):
                return None
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return None
            _answered.wait(poll if remaining is None else remaining if poll is None else min(poll, remaining))
        return _answers.pop(identifier)


def worker_call(send, arguments, timeout):
    """Relay a worker RPC over the kernel connection, with a finite receipt deadline."""
    identifier = uuid.uuid4().hex
    with _answered:
        _worker_calls.add(identifier)
    try:
        deadline = time.monotonic() + timeout + 5
        send({"op": "worker_request", "id": identifier, **arguments})
        answer = wait_answer(identifier, deadline=deadline, interruptible=False)
    finally:
        with _answered:
            _worker_calls.discard(identifier)
            _answers.pop(identifier, None)
    if answer is None:
        raise RuntimeError("Worker receipt timed out; delivery may be unknown")
    if "error" in answer:
        raise RuntimeError(answer["error"])
    return answer["value"]


def think(role, text="", *, images=(), system=None, entry=None, frame=None, stop=None, **detail):
    """Ask the session's host on behalf of a kernel entry."""
    from harness.core import spans
    from harness.runtime.decision.model import ChatReply
    from harness.runtime.execution.entries import Cancelled, current_entry

    sys.audit("harness.model_request", role)
    if not host_thoughts or not spans.connected():
        return None
    if stop is None and threading.current_thread() is threading.main_thread():
        stop = message_arrived
    owner = current_entry()

    def owner_cancelled():
        return owner is not None and any(entry._cancel.is_set() for entry in owner.lineage())

    identifier = uuid.uuid4().hex
    with _answered:
        _thoughts.add(identifier)
    answer = None
    try:
        spans.note("thought", id=identifier, role=role, text=str(text), images=list(images),
                   system=system, entry=entry or spans.current_entry(), frame=frame, **detail)
        answer = wait_answer(identifier, stop=lambda: owner_cancelled() or (stop is not None and stop()))
    finally:
        with _answered:
            _thoughts.discard(identifier)
            _answers.pop(identifier, None)
        if answer is None:
            spans.note("thought_cancel", id=identifier)
    if owner_cancelled():
        raise Cancelled(f"entry {owner.id} was cancelled")
    if answer is None:
        raise stopped(role)
    if answer.get("error"):
        raise RuntimeError(answer["error"])
    value = answer.get("value")
    return None if value is None else ChatReply(text=value["text"], usage=value.get("usage") or {},
                                                seconds=float(value.get("seconds") or 0))


def stopped(skill: str = "program"):
    """The typed escalation for an interrupted program wait."""
    from harness.runtime.events import USER_MESSAGE, USER_PAUSED, Escalation, Event, ExecutionTrace

    event = Event(USER_PAUSED if pause_requested() else USER_MESSAGE, "user")
    return Escalation(ExecutionTrace(skill, {}, 0, 0, event))


def on_agent_ended(listener, remove: bool = False) -> None:
    """Call listener(agent, report) when the host says a sub-agent ended (`remove`: stop)."""
    if remove:
        if listener in _agent_listeners:
            _agent_listeners.remove(listener)
    else:
        _agent_listeners.append(listener)


def agent_ended(agent, report, *, cancelled=False) -> None:
    """The host says the sub-agent `agent` ended, with its report."""
    for listener in list(_agent_listeners):
        try:
            listener(agent, report, cancelled=cancelled)
        except Exception:
            pass
