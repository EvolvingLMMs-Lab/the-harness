"""Desktop backends: a computer's windows, operated in the background.

A backend serves one operating system with that system's own interfaces (windows.py:
Windows; macos.py: macOS; linux.py: an X display, the user's or a display workspace's own,
display.py). Backend is what each implements:

    windows()                     the top-level windows (Window rows)
    tree(window)                  the window's accessibility tree (Element rows), each element
                                  with the actions it takes
    capture(window)               the window's picture, also while it is covered or off the
                                  screens
    act(element, action, value)   a semantic action on an element: invoke, toggle, select,
                                  expand, collapse, set_value, scroll_into_view
    input(window, event)          an input event sent to one window, never through the
                                  user's mouse and keyboard
    launch(app, args, ...)        start an application for a workspace: without taking the
                                  foreground, and (by default) off the user's screens

An action is tried the background way first, in this order (the ladder): a semantic
action (the accessibility interface), then targeted input (events sent to the window,
or the DevTools protocol of a Chromium the agent launched), and only then physical input
(the user's real mouse and keyboard), which the physical-input policy decides
(harness/physical.py) and the worker does. Every action that reached the backend returns
a Delivery: the mechanism (semantic, targeted, physical) and the status (delivered: the
application took it; unverified: it was sent and the application may ignore it;
not_delivered). A window that takes no background input for an action raises
NeedsPhysical with the reason.

Points are the screen's: physical pixels on Windows, points on macOS (what the pointer
and the screen's picture use there); a window's picture starts at its frame's top-left
corner (Window.rect). Standard library at import: a backend imports its system's
bindings when it is made (comtypes, pywinrt; pyobjc; python-xlib, jeepney: the computer
environment's).
"""

from dataclasses import dataclass, field
import sys

MECHANISMS = ("semantic", "targeted", "physical")
STATUSES = ("delivered", "unverified", "not_delivered")
# Semantic actions on an element.
ACTIONS = ("invoke", "toggle", "select", "expand", "collapse", "set_value", "scroll_into_view")
# What a left click on an element does semantically, in this order.
CLICK_ACTIONS = ("invoke", "toggle", "select", "expand")
# Input events sent to a window: one input step of runtime/safety/shield.py DESKTOP_COMMANDS, its
# points in physical screen pixels.
EVENTS = ("click", "drag", "scroll", "type", "key")
# Short role names of elements, from UI Automation's control types (and their kin on the
# other systems).
ROLES = ("button", "calendar", "checkbox", "combobox", "edit", "link", "image", "listitem", "list", "menu", "menubar",
         "menuitem", "progressbar", "radio", "scrollbar", "slider", "spinner", "statusbar", "tab", "tabitem", "text",
         "toolbar", "tooltip", "tree", "treeitem", "custom", "group", "thumb", "datagrid", "dataitem", "document",
         "splitbutton", "window", "pane", "header", "headeritem", "table", "titlebar", "separator", "semanticzoom",
         "appbar")
# A value in an outline is cut to this many characters.
VALUE_CHARS = 80


class NeedsPhysical(Exception):
    """The window takes no background input for this action: only the user's real mouse
    and keyboard would do it. `reason` says why, `tried` what was tried before."""

    def __init__(self, reason: str, tried=()):
        super().__init__(reason)
        self.reason = reason
        self.tried = list(tried)


@dataclass
class Delivery:
    """How an action reached the computer: its mechanism, its status and what else the
    backend knows (the method, a foreground it took and gave back, why it is unverified)."""

    mechanism: str
    status: str
    detail: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.mechanism not in MECHANISMS:
            raise ValueError(f"a delivery's mechanism is one of {MECHANISMS}")
        if self.status not in STATUSES:
            raise ValueError(f"a delivery's status is one of {STATUSES}")

    def to_dict(self) -> dict:
        return {"mechanism": self.mechanism, "status": self.status, **self.detail}


class Backend:
    """What a desktop backend implements (see the module's text). Rows are dicts:

    Window   handle, pid, app (process name, as physical.app_name gives it), title,
             framework (win32, winforms, wpf, chromium, tk, uwp; appkit, electron, qt, python;
             ... or unknown), rect
             [left, top, right, bottom] of its visible frame, minimized, foreground,
             offscreen (on no screen), owner (the handle of the window it belongs to, a
             dialog's), cdp (driven over the DevTools protocol), launched (by this backend)
    Element  key (what identifies it across trees), ref (the backend's handle on it),
             role, name, value (text, when it has one and is not a password), rect (screen
             pixels), actions (of ACTIONS), states (disabled, focused, checked, mixed,
             expanded, collapsed, selected, offscreen, readonly, password), depth, parent
             (the index of its parent in the list, None at the top)
    """

    system = "unknown"

    def windows(self) -> list[dict]:
        raise NotImplementedError

    def window(self, handle) -> dict | None:
        """The row of one window, or None when it is gone."""
        return next((row for row in self.windows() if row["handle"] == handle), None)

    def tree(self, window: dict, limit: int = 600) -> list[dict]:
        raise NotImplementedError

    def capture(self, window: dict):
        """{"image": a Pillow RGB image of the window's frame, "method": how}, or None when
        the window shows nothing to capture (minimized)."""
        raise NotImplementedError

    def act(self, element: dict, action: str, value=None) -> Delivery:
        raise NotImplementedError

    def input(self, window: dict, event: dict) -> Delivery:
        raise NotImplementedError

    def launch(self, app: str, args=(), directory=None, visible: bool = False, timeout: float = 30.0) -> dict:
        raise NotImplementedError

    def show(self, window: dict, visible: bool) -> dict:
        """Move a window the backend launched onto the user's screens or off them, without
        taking the foreground; its row after."""
        raise NotImplementedError

    def close(self) -> None:
        """The workspace ended: the windows it launched off-screen come back on the
        screens (the user's from now on)."""


def available(system: str | None = None) -> bool:
    """Whether this system has a backend for the user's own desktop: the apps workspace
    and window-scoped steps run on it (Windows; macOS; Linux on an X display: a Wayland
    session gives other programs neither pictures of its windows nor input to them)."""
    system = system or sys.platform
    if system in ("win32", "darwin"):
        return True
    if system.startswith("linux"):
        from .linux import session_type

        return session_type() == "x11"
    return False


def unavailable(system: str | None = None) -> str:
    """Why this system has no backend for the user's desktop (empty when it has one)."""
    system = system or sys.platform
    if available(system):
        return ""
    if system.startswith("linux"):
        from .linux import session_type

        if session_type() == "wayland":
            return ("this is a Wayland session, which gives other programs neither pictures of its windows nor input "
                    "to them: a display workspace runs apps on a display of their own")
        return "no X display here (DISPLAY is not set): a display workspace runs apps on a display of their own"
    return "Windows, macOS and Linux (X11) have them"


def backend(system: str | None = None, **options) -> Backend:
    """This system's backend (imports its bindings, which the computer environment
    installs). On Linux, options of LinuxBackend: display, private, env."""
    system = system or sys.platform
    if system == "win32":
        from .windows import WindowsBackend

        return WindowsBackend(**options)
    if system == "darwin":
        from .macos import MacBackend

        return MacBackend(**options)
    if system.startswith("linux"):
        from .linux import LinuxBackend

        return LinuxBackend(**options)
    raise NotImplementedError(f"no desktop backend for {system} yet: {unavailable(system)}")


def permissions(system: str | None = None) -> dict:
    """What the system must allow this process before its backend works, and whether it
    does: on macOS {"accessibility", "screen_recording": True | False | None, "process":
    who the user allows}; nothing elsewhere. Standard library."""
    if (system or sys.platform) == "darwin":
        from .macos import permissions as mac

        return mac()
    return {}


def click_action(element: dict) -> str | None:
    """The semantic action a left click on `element` stands for, or None (a text field,
    a canvas: a click there places something, which only input does)."""
    return next((action for action in CLICK_ACTIONS if action in element.get("actions", ())), None)


def element_at(elements: list[dict], x, y) -> dict | None:
    """The smallest element whose rect holds screen point (x, y), of those on the screen."""
    best = None
    for element in elements:
        left, top, right, bottom = element.get("rect") or (0, 0, 0, 0)
        if "offscreen" in element.get("states", ()) or not (left <= x < right and top <= y < bottom):
            continue
        area = (right - left) * (bottom - top)
        if best is None or area <= best[0]:
            best = (area, element)
    return best[1] if best else None


class Ids:
    """Short ids for windows (w1, w2, ...) or elements (e1, e2, ...) that stay the same
    for the same key during an episode, so an id the agent read keeps naming its thing."""

    def __init__(self, prefix: str):
        self.prefix = prefix
        self._by_key = {}
        self._rows = {}

    def assign(self, key, row: dict) -> str:
        name = self._by_key.get(key)
        if name is None:
            name = f"{self.prefix}{len(self._by_key) + 1}"
            self._by_key[key] = name
        self._rows[name] = row
        return name

    def get(self, name) -> dict | None:
        return self._rows.get(str(name))

    def key(self, name):
        return next((key for key, value in self._by_key.items() if value == str(name)), None)

    def name(self, key) -> str | None:
        return self._by_key.get(key)

    def forget(self, names) -> None:
        for name in names:
            self._rows.pop(name, None)

    def clear(self) -> None:
        self._by_key.clear()
        self._rows.clear()


def describe_element(element: dict, name: str | None = None) -> dict:
    """An element as the agent sees it: id, role, name, value, rect, actions, states."""
    row = {"id": name, "role": element.get("role"), "name": element.get("name") or ""}
    if element.get("value") is not None:
        row["value"] = element["value"]
    for key in ("rect", "actions", "states"):
        if element.get(key):
            row[key] = list(element[key])
    return row


def outline(elements: list[dict], names: list[str], limit: int = 200) -> str:
    """The tree as lines for the model: `e7 button "Save" [invoke]`, indented by depth,
    with values and states; elements that are neither named, valued nor actionable are
    left out but their children kept. At most `limit` lines."""
    lines = []
    for element, name in zip(elements, names):
        actions = [action for action in element.get("actions", ()) if action != "scroll_into_view"]
        if not (element.get("name") or element.get("value") or actions):
            continue
        if len(lines) >= limit:
            lines.append(f"... {sum(1 for _ in elements) - len(lines)} more elements; filter with elements(role=..., "
                         "text=...)")
            break
        text = f"{'  ' * min(int(element.get('depth', 0)), 8)}{name} {element.get('role') or 'element'}"
        if element.get("name"):
            text += f" {_quote(element['name'])}"
        if element.get("value") is not None and element.get("value") != element.get("name"):
            text += f" = {_quote(element['value'])}"
        states = [state for state in element.get("states", ()) if state != "offscreen"]
        if states:
            text += " (" + ", ".join(states) + ")"
        if actions:
            text += " [" + ", ".join(actions) + "]"
        lines.append(text)
    return "\n".join(lines)


def _quote(text) -> str:
    text = " ".join(str(text).split())
    if len(text) > VALUE_CHARS:
        text = text[:VALUE_CHARS - 1] + "…"
    return '"' + text.replace('"', "'") + '"'
