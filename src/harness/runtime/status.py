"""The conversation lifecycle shared by Runtime and its clients."""

IDLE = "IDLE"
RUNNING = "RUNNING"
PAUSED = "PAUSED"
WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
FINISHED = "FINISHED"
ERROR = "ERROR"
# IDLE: waiting for the user's next message (interactive only); FINISHED: the episode is
# over (its summary says why); ERROR: it ended in an error.
LIVE = (IDLE, RUNNING, PAUSED, WAITING_FOR_CONFIRMATION, WAITING_FOR_INPUT)
ENDED = (FINISHED, ERROR, "INTERRUPTED")
STATUSES = (*LIVE, FINISHED, ERROR)


def live(status) -> bool:
    """Whether an agent in this status still runs or waits."""
    return status not in ENDED


class Closed(Exception):
    """The user closed the conversation while it waited."""
