"""Events: the signals of a run, in one catalog.

An execution's event (Event) ends every bounded execution and goes to the rules that answer
it (on()); one nobody answers ends the unit that ran it and reaches the model (Escalation).
A trace record (EVENTS) is what the run writes to its trace (core/trace.py), which the
timeline, the overlay, replay and the exported video all draw. A family of records is one
kind with an `action` (library), which record_kind() reads.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


# The kinds of an execution's event (Event.kind; a guard may raise one of its own name):
# nominal ends (NOMINAL), a time bound, the execution's scope, a guard, the shield, reactive
# code that broke its rules, a skill's error, the arm held back short of its target (contact
# or a load), the episode's end, the user's pause (it stops every unit of the model), a unit
# that failed, a channel another unit has, and a unit of higher priority that took the
# embodiment from an execution that is not to be started again.
BUILTIN = ("COMPLETED", "PREDICATE_SATISFIED", "TIMEOUT", "REGION_EXIT", "GUARD_TRIGGERED", "SHIELD_REJECTED",
           "REACTIVE_FAULT", "SKILL_ERROR", "BLOCKED", "EPISODE_ENDED", "USER_PAUSED",
           "ENTRY_FAILED", "CHANNEL_CONFLICT", "PREEMPTED")
(COMPLETED, PREDICATE_SATISFIED, TIMEOUT, REGION_EXIT, GUARD_TRIGGERED, SHIELD_REJECTED, REACTIVE_FAULT, SKILL_ERROR,
 BLOCKED, EPISODE_ENDED, USER_PAUSED, ENTRY_FAILED, CHANNEL_CONFLICT, PREEMPTED) = BUILTIN
# A program may continue after these without consulting a handler.
NOMINAL = frozenset({COMPLETED, PREDICATE_SATISFIED})


@dataclass
class Event:
    """Why an execution ended: its kind (a built-in kind above or a guard's own action),
    the source that raised it (a skill, a guard, "shield", "environment"), details, and
    the robot step it happened at."""

    kind: str
    source: str
    detail: dict[str, Any] = field(default_factory=dict)
    tick: int | None = None

    def to_dict(self) -> dict:
        """The event as a plain dict."""
        return asdict(self)


def input_refusal(receipt, step):
    if conflict := receipt.get("conflict"):
        return Event(CHANNEL_CONFLICT, "channels", conflict, step)
    if not receipt["executed"]:
        return Event(SHIELD_REJECTED, "shield", {"reasons": receipt["shield"]["reasons"]}, step)


@dataclass
class ExecutionTrace:
    """What one bounded execution did, and why it ended."""

    skill: str
    parameters: dict[str, Any]
    start_tick: int
    end_tick: int
    event: Event
    samples: list[dict] = field(default_factory=list)
    # A value for the calling program, never part of an event or serialized trace.
    result: Any = field(default=None, repr=False)
    # How often a unit of higher priority took the embodiment and the harness started
    # this execution again.
    restarts: int = 0

    @property
    def ok(self) -> bool:
        """Whether the execution ended nominally (COMPLETED or PREDICATE_SATISFIED)."""
        return self.event.kind in NOMINAL

    @property
    def ticks(self) -> int:
        """Robot steps the execution took."""
        return self.end_tick - self.start_tick

    def to_dict(self) -> dict:
        """The trace as a plain dict, with `ok`."""
        data = {"skill": self.skill, "parameters": self.parameters, "start_tick": self.start_tick,
                "end_tick": self.end_tick, "event": self.event.to_dict(), "samples": self.samples}
        data["ok"] = self.ok
        if self.restarts:
            data["restarts"] = self.restarts
        return data

    def __repr__(self) -> str:
        return (f"Trace({self.skill}, {self.event.kind} from {self.event.source}, "
                f"ticks={self.ticks})")


class Escalation(Exception):
    """An event no handler resolved. It ends the current program."""

    def __init__(self, trace: ExecutionTrace):
        super().__init__(f"{trace.event.kind} in {trace.skill}")
        self.trace = trace


class ProgramFinished(Exception):
    """A program called finish(): its own checks say the task is done. The episode
    ends without another model call."""

    def __init__(self, summary: str = ""):
        super().__init__(summary)
        self.summary = str(summary)


class EpisodeEnded(Exception):
    """The environment terminated or truncated the episode during a program."""

    def __init__(self, trace: ExecutionTrace):
        super().__init__("episode ended")
        self.trace = trace


# Every kind of trace record: its source (the user; the agent, i.e. the main model; the program
# running in the kernel; the environment; the harness itself) and whether what it holds is part
# of what the model is shown. What each record holds is in the traces reference.
EVENTS = {
    "execution_event": {"source": "program", "shown": False},
    "program_output": {"source": "program", "shown": False},
    "state": {"source": "harness", "shown": False},
    "reset": {"source": "environment", "shown": True},
    "screen_recording": {"source": "harness", "shown": False},
    "library": {"source": "harness", "shown": True},
    "user_message": {"source": "user", "shown": True},
    "model_request": {"source": "harness", "shown": True},
    "model_changed": {"source": "user", "shown": False},
    "context_shortened": {"source": "harness", "shown": False},
    "model_preempted": {"source": "harness", "shown": False},
    "model_reply": {"source": "agent", "shown": True},
    "agent_message": {"source": "agent", "shown": True},
    "empty_reply": {"source": "harness", "shown": False},
    "protocol_error": {"source": "harness", "shown": True},
    "malformed_dropped": {"source": "harness", "shown": False},
    "verify": {"source": "environment", "shown": True},
    "confirmation_request": {"source": "harness", "shown": False},
    "confirmation": {"source": "user", "shown": True},
    "physical_request": {"source": "harness", "shown": False},
    "physical_answer": {"source": "user", "shown": False},
    "worker_approval_result": {"source": "harness", "shown": False},
    "input": {"source": "environment", "shown": False},
    "cell": {"source": "program", "shown": True},
    "unit_end": {"source": "program", "shown": True},
    "wait": {"source": "agent", "shown": False},
    "wait_end": {"source": "harness", "shown": True},
    "private_paths": {"source": "harness", "shown": False},
    "file_access": {"source": "program", "shown": False},
    "modules": {"source": "harness", "shown": False},
    "experience": {"source": "program", "shown": False},
    "experience_folded": {"source": "harness", "shown": False},
    "tick_periods": {"source": "program", "shown": False},
    "guard": {"source": "program", "shown": False},
    "rule": {"source": "program", "shown": False},
    "preempted": {"source": "program", "shown": False},
    "held_back": {"source": "program", "shown": False},
    "fact": {"source": "program", "shown": False},
    "program_held": {"source": "harness", "shown": False},
    "program_dropped": {"source": "harness", "shown": False},
    "user_took_over": {"source": "harness", "shown": False},
    "stuck": {"source": "harness", "shown": False},
    "policy_to_end": {"source": "program", "shown": False},
    "finish": {"source": "agent", "shown": False},
    "turn_result": {"source": "harness", "shown": False},
    "resumed": {"source": "harness", "shown": True},
    "finish_refused": {"source": "harness", "shown": True},
    "wrap_up": {"source": "program", "shown": False},
    "kernel_died": {"source": "harness", "shown": False},
    "interrupted": {"source": "harness", "shown": False},
    "error": {"source": "harness", "shown": False},
    "cleanup_error": {"source": "harness", "shown": False},
    "outcome": {"source": "environment", "shown": False},
    "episode_video": {"source": "environment", "shown": False},
    "late_receipt": {"source": "environment", "shown": False},
    "plan": {"source": "program", "shown": False},
    "stay_on_screen": {"source": "program", "shown": False},
    "decision": {"source": "program", "shown": False},
    "page_read": {"source": "environment", "shown": False},
    "workspace_reclaimed": {"source": "harness", "shown": False},
    "environment_attached": {"source": "harness", "shown": True},
    "environment_refused": {"source": "harness", "shown": True},
    "environment_released": {"source": "harness", "shown": True},
    "agents_enabled": {"source": "harness", "shown": True},
    "views": {"source": "program", "shown": False},
    "agent_delegated": {"source": "program", "shown": False},
    "agent_waited": {"source": "program", "shown": False},
    "agent_sent": {"source": "program", "shown": False},
    "agent_cancelled": {"source": "program", "shown": False},
    "agent_report": {"source": "harness", "shown": False},
    "span_start": {"source": "harness", "shown": False},
    "span_end": {"source": "harness", "shown": False},
    "model_text": {"source": "agent", "shown": False},
    "mcp_submitted": {"source": "agent", "shown": False},
    "mcp_dispatched": {"source": "agent", "shown": False},
    "mcp_receipt": {"source": "agent", "shown": False},
    "thought_queued": {"source": "agent", "shown": False},
    "thought_started": {"source": "agent", "shown": False},
    "thought_failed": {"source": "agent", "shown": False},
    "thought_exited": {"source": "agent", "shown": False},
    "thought_cancelled": {"source": "agent", "shown": False},
    "escalation": {"source": "program", "shown": False},
    "entry_start": {"source": "program", "shown": False},
    "entry_claims": {"source": "program", "shown": False},
    "entry_end": {"source": "program", "shown": False},
    "skill_step": {"source": "program", "shown": False},
    "world": {"source": "program", "shown": False},
}


def record_kind(record: dict) -> tuple[str, str | None]:
    """A trace record's kind and, for a family (library), its action."""
    kind = record.get("event") or ""
    return kind, record.get("action") if kind == "library" else None


def step_of(start: dict, end: dict, call: str | None = None) -> dict:
    """An execution's span_start and span_end (lane "skill") as a step of its skill, in the
    shape of a skill_step record (core/spans.py step), so a reader takes both alike."""
    event = end.get("event_kind") or ("error" if end.get("error") else COMPLETED)
    return {"skill": start.get("name"), "call": call, "ok": event in NOMINAL, "event": event,
            "seconds": float(end.get("time") or 0.0) - float(start.get("time") or 0.0),
            "reason": end.get("reason") or end.get("error")}
