"""A fixed, non-learned check on every command before it takes effect.

The shield runs in the environment worker, outside the process that executes
model-written code, so programs cannot modify it, and nothing learned reaches it. Every
embodiment's shield has the same interface, the core's (CommandShield):
it judges one command against the measured state, and the command passes unchanged or is
rejected with the reasons; it never shortens, clamps or otherwise alters a command, since
a program whose command was quietly changed does not learn it was wrong. A tick's
`shield` field is its ShieldResult. The shields of the robot, a computer and a game are
described here; each is in the package of its embodiment.

Shield (the robot package, harness_robot/shield.py) is the robot's. It sees absolute
joint position commands and, when the worker supplies forward kinematics, the
end-effector positions those commands imply. It catches commands that are bugs, and
nothing else. Rejected are:

- a malformed command (wrong length, a value that is not finite);
- a joint outside its limits, or an end effector outside the workspace box,
  further than the robot already is (contact can push a measured joint or hand
  slightly out; holding there or moving back in is not a bug);
- a jump: an arm's joints more than max_joint_jump_rad, or its end effector more
  than max_cartesian_jump_m, from both the previous accepted command and the
  measured state. One control tick of a real motion moves far less; a jump is an
  IK solution on another branch, a target in the wrong frame, a controller that
  diverged. A smooth sequence is never rejected for running ahead of an arm that
  lags behind it, and a command from where the arm is (a hold, the next skill's
  first waypoint, a retreat) is never rejected for where the last one went.

Speed and acceleration are not the shield's: the skills time their own motions,
and a physical robot's controller enforces its own rate limits.

DesktopShield (the computer package, harness_computer/shield.py) is a computer's. It
sees one input step (DESKTOP_COMMANDS) and rejects an unknown command, field or key, a
point off the screen, text the keyboard cannot type, and a scroll, wait or drag out of
its bounds. A step into one window (its `window` field) has its points in that window's
picture, which the worker checks; an element action (act) names an element id and one of
its actions. Where several agents share a computer it also rejects a step into a window
another agent owns (owner(): the machine-wide ownership of the computer package's
coordination.py), and claims an unowned one for the agent.

GameShield (the game package, harness_game/shield.py) is a game's. It sees one generic
input (GAME_COMMANDS: those of GameScientist's action protocol, in screen pixels) and
rejects what that protocol would: an unknown command, field, key or button, a point off
the screen, a duration, wait, relative motion or scroll out of its bounds, too many or
repeated keys. An embodiment may also block keys a game's rules forbid (its `blocked`
table: the key and the rule, such as Minecraft's chat and pause keys during a speedrun).
A game that declares channels (its [channels]: who holds which keys, buttons, pointer
use and wheel at a time) also takes a state input, the one its kernel's tick merges
every period from what each entry holds (runtime/tick.py), checked channel by channel.
The fairness caps ([shield.fairness], graded: FAIRNESS) bound what a person could match:
button presses a second, the view's turn a period, keys down together. Text typed into a
text field (a text input, or a state's `text` on the channel that types) passes only
with the game's [shield.text]: its characters, its length, the screen read now among its
screens (Minecraft: the recipe book's search, where a letter is the field's, never a key
such as the blocked T), and alone: no key pressed, or let go, in the same input.

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
    is the embodiment's: a robot's joint vector."""

    verdict: str
    command: Any
    reasons: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """The result as a plain dict, as a tick's `shield` field."""
        return {"verdict": self.verdict, "command": self.command, "reasons": self.reasons}


class CommandShield(Protocol):
    """The shield of one worker, whatever the embodiment: a fixed check of every command
    against the measured state (`current`) and what else the worker knows (`context`, such
    as a robot's forward kinematics), passing it unchanged or rejecting it with reasons."""

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
