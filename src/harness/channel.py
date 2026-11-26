"""The channel of this install: stable, or dev.

The dev channel is an app of its own beside the stable one, as VS Code Insiders is beside
VS Code: its own name (The Harness Dev), command (harness-dev), data (~/.harness-dev), what
it installs (~/.cache/harness-dev), login item, port and updates, so both can be installed
and run at once and neither touches the other's.

The channel is decided when an installer is built (tools/installers/build.py --channel) and
written into the installer's runtime as runtime/channel: the channel's name on the first
line, the build's version on the second. It is read here and nowhere guessed: everything
that differs between channels asks this module. A pip install and a source checkout have no
such file and are stable.

Standard library only.
"""

from functools import lru_cache
from pathlib import Path
import re
import sys

STABLE = "stable"
NAME = re.compile(r"[a-z][a-z0-9]{0,15}")


@lru_cache(maxsize=1)
def _marker() -> tuple[str, str]:
    """(channel, version) of an installer's runtime (this Python is its runtime/python);
    ("stable", "") without one."""
    prefix = Path(sys.prefix)
    if prefix.name != "python" or prefix.parent.name != "runtime":
        return STABLE, ""
    try:
        lines = (prefix.parent / "channel").read_text(encoding="utf-8").split()
    except OSError:
        return STABLE, ""
    if not lines or not NAME.fullmatch(lines[0]):
        return STABLE, ""
    return lines[0], lines[1] if len(lines) > 1 else ""


def name() -> str:
    """stable or dev."""
    return _marker()[0]


def tag(base: str, separator: str = "-") -> str:
    """`base` as this channel has it: itself on the stable channel, else with the channel's
    name after it ("harness" is "harness-dev", "~/.harness" is "~/.harness-dev")."""
    return base if name() == STABLE else f"{base}{separator}{name()}"


def product() -> str:
    """The app's name: The Harness, The Harness Dev."""
    return "The Harness" if name() == STABLE else f"The Harness {name().capitalize()}"


def version() -> str:
    """This install's version as people see it: the core's, or the build's own
    ("0.87.0-dev.412") on a channel that numbers its builds. What packages are checked
    against stays the core's (harness.__version__)."""
    from . import __version__

    return _marker()[1] or __version__


def port(base: int) -> int:
    """The port the session host takes when it is free: `base` on the stable channel, the
    next one on another, so that both hosts keep a port of their own."""
    return base if name() == STABLE else base + 1
