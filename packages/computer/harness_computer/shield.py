"""A computer's command shield (a CommandShield, harness.sdk): every input step checked
before it reaches the screen. What it rejects is in the core's runtime/safety/shield.py
description of shields."""

from dataclasses import dataclass, field
import re

from harness.sdk import PASS, ShieldResult, bounded, in_screen, reject


# A computer's input commands (DesktopShield), in screen pixels from the top-left corner:
#   {"type": "noop"}                                     leave everything as it is (one step)
#   {"type": "click", "x", "y", "button": "left"|"right", "count": 1|2}
#   {"type": "drag", "x", "y", "to_x", "to_y", "duration_ms"}
#   {"type": "scroll", "x", "y", "direction": "up"|"down"|"left"|"right", "amount"}
#   {"type": "type", "text"}                             typed key by key
#   {"type": "key", "keys": [...]}                       pressed together, released in reverse
#   {"type": "wait", "ms"}
#   {"type": "act", "element", "action", "value"}       an element's action (harness/desktop
#                                                        ACTIONS, or "click": what a click on it does)
# click, drag, scroll, type and key may name a window ("window": "w2"): the step goes to
# that window, its points in the window's picture, in the background where it takes them.
DESKTOP_COMMANDS = ("noop", "click", "drag", "scroll", "type", "key", "wait")
# The actions of an act step: harness/desktop ACTIONS, and click.
ELEMENT_ACTIONS = ("click", "invoke", "toggle", "select", "expand", "collapse", "set_value", "scroll_into_view")
# The key names an input step can press: pyautogui's (KEYBOARD_KEYS), which the guests
# type with.
KEY_NAMES = frozenset(
    [chr(c) for c in range(0x20, 0x7f) if not chr(c).isupper()]
    + [f"f{n}" for n in range(1, 25)] + [f"num{n}" for n in range(10)]
    + ["\t", "\n", "\r", "accept", "add", "alt", "altleft", "altright", "apps", "backspace", "browserback",
       "browserfavorites", "browserforward", "browserhome", "browserrefresh", "browsersearch", "browserstop",
       "capslock", "clear", "convert", "ctrl", "ctrlleft", "ctrlright", "decimal", "del", "delete", "divide",
       "down", "end", "enter", "esc", "escape", "execute", "final", "fn", "help", "home", "insert", "left",
       "modechange", "multiply", "nexttrack", "nonconvert", "numlock", "pagedown", "pageup", "pause", "pgdn",
       "pgup", "playpause", "prevtrack", "print", "printscreen", "prntscrn", "prtsc", "prtscr", "return",
       "right", "scrolllock", "select", "separator", "shift", "shiftleft", "shiftright", "sleep", "space",
       "stop", "subtract", "tab", "up", "volumedown", "volumemute", "volumeup", "win", "winleft", "winright",
       "command", "option", "optionleft", "optionright"])
# What `type` can type: printable ASCII, newline and tab (pyautogui.write drops the rest).
TYPEABLE = frozenset(chr(c) for c in range(0x20, 0x7f)) | {"\n", "\t"}


def _unicode_typeable(char: str) -> bool:
    """What a worker that pastes text can type: anything printable, newline and tab."""
    return char in "\n\t" or char.isprintable()


@dataclass
class DesktopShieldProfile:
    """The limits the desktop shield checks: the screen and the bounds of one step."""

    screen: tuple[int, int]
    max_text_chars: int = 2000
    max_keys: int = 4
    max_scroll: int = 50
    max_wait_ms: int = 10000
    max_drag_ms: int = 5000
    # Text beyond ASCII, for a worker that pastes text (this computer's): any printable
    # character, newline and tab.
    unicode_text: bool = False

    @classmethod
    def from_dict(cls, data: dict, screen) -> "DesktopShieldProfile":
        """A validated profile from a worker's shield settings (any of the bounds above,
        and unicode_text) and the screen size [width, height]."""
        unknown = set(data) - {"max_text_chars", "max_keys", "max_scroll", "max_wait_ms", "max_drag_ms",
                               "unicode_text"}
        if unknown:
            raise ValueError(f"Unknown desktop shield settings: {sorted(unknown)}")
        width, height = (int(v) for v in screen)
        if width < 1 or height < 1:
            raise ValueError("screen must be [width, height] in pixels")
        data = dict(data)
        unicode_text = data.pop("unicode_text", False)
        if not isinstance(unicode_text, bool):
            raise ValueError("unicode_text must be true or false")
        bounds = {key: int(value) for key, value in data.items()}
        if any(value < 1 for value in bounds.values()):
            raise ValueError("Desktop shield bounds must be positive integers")
        return cls((width, height), **bounds, unicode_text=unicode_text)


class DesktopShield:
    """A computer's command check (a CommandShield). It catches input steps that are bugs:
    an unknown command or key, a point off the screen, text the keyboard cannot type, a
    step out of its bounds. It judges each command by itself, so `current` (the measured
    state) is not consulted, and it keeps nothing between commands."""

    def __init__(self, profile: DesktopShieldProfile, *, elements=True, workspace=False):
        self.profile = profile
        self.commands = DESKTOP_COMMANDS + (("act",) if elements else ()) + (("use_window", "launch") if workspace else ())

    def reset(self) -> None:
        """Nothing to forget: no check depends on an earlier command."""

    @staticmethod
    def owner(owners, window: dict | None, owner, name: str | None = None) -> dict | None:
        """The reason a step into `window` ({handle, app, title, shared}) is rejected: another
        agent owns it (`owners`, coordination.WindowOwners). Otherwise the window is claimed
        for `owner` and None is returned. A window the system names no handle for, and one
        every agent shares (the desktop, the taskbar), is nobody's. `name`: how the reason
        names the window (default its title or app; the worker passes what the model may
        learn of it, harness/privacy.py)."""
        if not window or window.get("handle") is None or window.get("shared"):
            return None
        other = owners.claim(window["handle"], owner, app=window.get("app"), title=window.get("title"))
        if other is None:
            return None
        name = name or window.get("title") or window.get("app")
        return {"check": "window", "owner": other.get("owner"), "window": name,
                "reason": f"the window {name!r} belongs to agent {other.get('owner')} now; nothing was done. Work "
                          "in another window, or wait until it is done there"}

    def check(self, command, current=None, **context) -> ShieldResult:
        """Judge one input command (DESKTOP_COMMANDS); the first failed check rejects it."""
        if not isinstance(command, dict) or command.get("type") not in self.commands:
            kind = command.get("type") if isinstance(command, dict) else type(command).__name__
            return reject({"check": "command", "got": kind, "known": list(self.commands)})
        kind = command["type"]
        allowed = {"noop": (), "click": ("x", "y", "button", "count", "window"),
                   "drag": ("x", "y", "to_x", "to_y", "duration_ms", "window"),
                   "scroll": ("x", "y", "direction", "amount", "window"), "type": ("text", "window"),
                   "key": ("keys", "window"), "wait": ("ms",), "act": ("element", "action", "value"),
                   "use_window": ("window", "visible"), "launch": ("app", "args", "visible")}[kind]
        extra = set(command) - {"type", *allowed}
        if extra:
            return reject({"check": "fields", "command": kind, "unknown": sorted(extra)})
        window = command.get("window")
        if window is not None and not (isinstance(window, str) and re.fullmatch(r"w\d{1,6}", window)):
            return reject({"check": "window", "got": window, "reason": 'a window is an id such as "w2"'})
        if kind in ("use_window", "launch"):
            if "visible" in command and type(command["visible"]) is not bool:
                return reject({"check": "visible", "reason": "visible must be true or false"})
            if kind == "use_window" and window is None:
                return reject({"check": "window", "reason": "use_window requires a window id"})
            if kind == "launch":
                app, args = command.get("app"), command.get("args", [])
                if not isinstance(app, str) or not app.strip() or "\x00" in app:
                    return reject({"check": "app", "reason": "launch requires an application name or path"})
                if not isinstance(args, (list, tuple)) or not all(
                        isinstance(arg, (str, int, float)) and "\x00" not in str(arg) for arg in args):
                    return reject({"check": "args", "reason": "launch arguments must be strings or numbers"})
            return ShieldResult(PASS, dict(command))
        points = {"click": (("x", "y"),), "drag": (("x", "y"), ("to_x", "to_y")),
                  "scroll": (("x", "y"),)}.get(kind, ())
        for x, y in points:
            if kind == "scroll" and x not in command and y not in command:
                continue
            # A window's points are in its picture, which the worker knows.
            reason = in_screen(command.get(x), command.get(y), None if window else self.profile.screen)
            if reason:
                return reject({**reason, "command": kind})
        profile = self.profile
        if kind == "act":
            return self._act(command)
        if kind == "click":
            button, count = command.get("button", "left"), command.get("count", 1)
            if button not in ("left", "right") or count not in (1, 2) or (button == "right" and count == 2):
                return reject({"check": "click", "button": button, "count": count,
                                     "allowed": "left x1 or x2, right x1"})
        elif kind == "drag":
            reason = bounded("duration_ms", command.get("duration_ms", 400), 100, profile.max_drag_ms, integer=True)
            if reason:
                return reject(reason)
        elif kind == "scroll":
            if command.get("direction") not in ("up", "down", "left", "right"):
                return reject({"check": "scroll", "direction": command.get("direction")})
            reason = bounded("amount", command.get("amount", 5), 1, profile.max_scroll, integer=True)
            if reason:
                return reject(reason)
        elif kind == "type":
            text = command.get("text")
            if not isinstance(text, str) or not text:
                return reject({"check": "text", "reason": "text must be a non-empty string"})
            if len(text) > profile.max_text_chars:
                return reject({"check": "text", "length": len(text), "limit": profile.max_text_chars})
            untypeable = sorted(char for char in set(text) if not (
                _unicode_typeable(char) if profile.unicode_text else char in TYPEABLE))
            if untypeable:
                return reject({"check": "untypeable", "chars": untypeable[:10]})
        elif kind == "key":
            keys = command.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= profile.max_keys:
                return reject({"check": "keys", "reason": f"keys must be a list of 1 to {profile.max_keys}"})
            unknown = [key for key in keys if not isinstance(key, str) or key.lower() not in KEY_NAMES]
            if unknown:
                return reject({"check": "keys", "unknown": unknown})
            command = {**command, "keys": [key.lower() for key in keys]}
        elif kind == "wait":
            reason = bounded("ms", command.get("ms", 1000), 0, profile.max_wait_ms, integer=True)
            if reason:
                return reject(reason)
        return ShieldResult(PASS, dict(command))

    def _act(self, command) -> ShieldResult:
        element, action = command.get("element"), command.get("action", "click")
        if not (isinstance(element, str) and re.fullmatch(r"e\d{1,7}(?:_\d{1,7}_\d{1,8})?", element)):
            return reject({"check": "element", "got": element,
                                 "reason": 'an element is an id such as "e12" from the window\'s elements'})
        if action not in ELEMENT_ACTIONS:
            return reject({"check": "action", "got": action, "known": list(ELEMENT_ACTIONS)})
        value = command.get("value")
        if action == "set_value":
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                return reject({"check": "value", "reason": "set_value takes text or a number"})
            if isinstance(value, str) and len(value) > self.profile.max_text_chars:
                return reject({"check": "value", "length": len(value), "limit": self.profile.max_text_chars})
        elif value is not None:
            return reject({"check": "value", "reason": f"{action} takes no value"})
        return ShieldResult(PASS, {**command, "action": action})

