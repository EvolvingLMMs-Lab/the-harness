"""A fixed, non-learned check on every command before it takes effect.

The shield runs in the environment worker, outside the process that executes
model-written code, so programs cannot modify it, and nothing learned reaches it. Every
embodiment's shield has the same interface, the core's (CommandShield):
it judges one command against the measured state, and the command passes unchanged or is
rejected with the reasons; it never shortens, clamps or otherwise alters a command, since
a program whose command was quietly changed does not learn it was wrong. A tick's
`shield` field is its ShieldResult. Each kind's shield is in its package, which says what it
rejects.

The checks every shield shares are here, one rule each: finite (a finite number, never a
bool), in_screen (a point of the picture: 0 <= x < width, 0 <= y < height), bounded (a
finite number in [low, high], an int where the field counts) and reject."""

from dataclasses import dataclass, field
import math
import re
import time
from typing import Any, Callable, Protocol


PASS = "pass"
REJECTED = "rejected"


@dataclass
class ShieldResult:
    """The verdict on one command: "pass" with the command unchanged, or "rejected" with
    no command and the reason (the failed check and the values it compared). The command
    is the embodiment's."""

    verdict: str
    command: Any
    reasons: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """The result as a plain dict, as a tick's `shield` field."""
        return {"verdict": self.verdict, "command": self.command, "reasons": self.reasons}


class CommandShield(Protocol):
    """The shield of one worker, whatever the embodiment: a fixed check of every command
    against the measured state (`current`) and what else the worker knows (`context`), passing it unchanged or rejecting it with reasons."""

    def reset(self) -> None:
        """Forget what earlier commands of the episode established."""

    def check(self, command, current, **context) -> ShieldResult:
        """The verdict on `command`."""


def finite(*values) -> bool:
    """Whether every value is a finite number (a bool is not one)."""
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def in_screen(x, y, screen=None) -> dict | None:
    """The reason (x, y) is no point of the picture `screen` ([width, height]), or None. A
    point is two finite numbers with 0 <= x < width and 0 <= y < height (pixel x covers
    [x, x + 1)); without `screen` only the numbers are checked (a window's picture, which
    the worker knows)."""
    if not finite(x, y):
        return {"check": "point", "reason": "x and y must be finite numbers (pixels)", "x": x, "y": y}
    if screen is not None:
        width, height = screen
        if not (0 <= x < width and 0 <= y < height):
            return {"check": "screen", "x": x, "y": y, "screen": [width, height]}
    return None


def bounded(name, value, low, high, *, integer=False) -> dict | None:
    """The reason `value` is out of its bounds, or None: the one bounds rule of every shield,
    a finite number (an int when the field counts something: `integer`) with
    low <= value <= high."""
    if not finite(value) or (integer and not isinstance(value, int)) or not low <= value <= high:
        return {"check": name, "got": value, "limit": [low, high]}
    return None


def reject(reason: dict) -> ShieldResult:
    """A rejection for `reason` (no command passes)."""
    return ShieldResult(REJECTED, None, [reason])
