"""Physical input receipts and the legacy host approval flow.

Host-bound refusals pass through to Tick for attribution.
"""

from harness.core import spans
from harness.runtime.execution import control


# What a user's answer keeps: this step, this app or every app for the session, or a rule.
REMEMBER = ("once", "app", "session", "always")

class PhysicalInput:
    """Worker input and the explicit request_physical() operation."""

    def ask_physical(self, request):
        """Put a physical-input request of the worker to the user, through the host, and
        give the worker their answer: {"accept", "remember", "reason"}, or None when nobody
        answered (no host to ask; the program was paused)."""
        if not spans.connected():
            return None
        identifier = request["id"]
        with control._answered:
            control._physical.add(identifier)
        spans.note("physical_request", request=request)
        try:
            answer = control.wait_answer(identifier)
        finally:
            with control._answered:
                control._physical.discard(identifier)
                control._answers.pop(identifier, None)
        if answer is None:
            return None
        self.env.call("physical", op="answer", episode_id=self.episode_id, id=request["id"],
                      accept=bool(answer.get("accept")), remember=answer.get("remember") or "once")
        return answer

    def _note_input(self, command, result):
        """The host's `input` note of a delivered step: how it went (the worker's delivery)
        and what it sent (input_sent)."""
        detail = result["delivery"]
        if "action_id" in result:
            detail = {**detail, "action_id": result["action_id"]}
        spans.note("input", command=command.get("type"), executed=bool(result["executed"]),
                   sent=input_sent(command), **detail)


def input_sent(command) -> dict:
    """What a step sent, for its `input` note: the command's fields but its type (the keys
    and buttons a state input holds down, its pointer motion), a typed text by its
    length only."""
    sent = {}
    for name, value in command.items():
        if name == "type":
            continue
        if name in ("text", "value") and isinstance(value, str):
            sent[f"{name}_chars"] = len(value)
        elif isinstance(value, (set, frozenset, tuple, list)):
            sent[name] = sorted(value) if isinstance(value, (set, frozenset)) else list(value)
        else:
            sent[name] = value
    return sent
