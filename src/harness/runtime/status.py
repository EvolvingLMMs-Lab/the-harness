"""The conversation lifecycle shared by Runtime and its clients."""

IDLE = "IDLE"
RUNNING = "RUNNING"
PAUSED = "PAUSED"
WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
FINISHED = "FINISHED"
ERROR = "ERROR"
# IDLE: between turns (its reason says how the last turn ended): the conversation keeps
# everything and waits for what starts the next turn; FINISHED: the conversation is over
# (its summary says how its last turn ended); ERROR: it ended in an error.
LIVE = (IDLE, RUNNING, PAUSED, WAITING_FOR_CONFIRMATION, WAITING_FOR_INPUT)
ENDED = (FINISHED, ERROR, "INTERRUPTED")
STATUSES = (*LIVE, FINISHED, ERROR)


def live(status) -> bool:
    """Whether an agent in this status still runs or waits."""
    return status not in ENDED


class Closed(Exception):
    """The user closed the conversation while it waited."""


class Interrupted(Exception):
    """The user ended the turn that ran."""
