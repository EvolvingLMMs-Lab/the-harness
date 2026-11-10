"""The computer worker: the desktop embodiment on the machine this worker runs on.

    harness serve --factory benches.computer.runtime:create_environment --port 8790

Serves the desktop session (runtime/desktop.py) on this computer's screen, pointer and
keyboard, Windows, macOS or Linux:

    profile                 the kind, the screen (scaled), the input-step rate, the shield's bounds
    state                   system, step, step limit, ended, screen, the window in front (as the
                            window-details policy allows), the monitors (with several), and
                            the windows the agent may know (for the rules' window events)
    tick                    one input step (shield.DESKTOP_COMMANDS), checked by the
                            DesktopShield, then done with the pointer and keyboard
    observe                 the screen
    preview                 the screen now, for the user watching (any time, no episode)
    use_screen              show and act on one monitor, or follow the active window again
    hand_back               the user handed the computer back: it is the agent's as it is now
    windows                 the windows, with ids (w1, w2, ...), and the one the agent works in
    use_window              work in a window: claim it, show it in the observations (apps), and
                            move one the agent launched onto the user's screens or off them
    launch                  start an application in the background and work in its window
    elements                a window's elements, with ids (e1, e2, ...) and their actions, and
                            the same as outline lines
    claim_outcome / outcome no evaluator: the user judges the result

Screenshots are of one monitor at a time, scaled down so the long side is at most
`max_side` pixels; commands come in the same scaled pixels and are mapped back. With
several monitors the worker shows the one with the active window (`follow`, on by
default; `monitor` is the one it starts on), and use_screen(index) holds one until
use_screen() follows again. The picture keeps the size of the first: a monitor of
another shape is fitted into it with dark bars, and a point in a bar is refused. The
user's timeline overlay (harness timeline --overlay, harness_computer/overlays.py) is painted over in
the pictures: it is the user's view of the agent, not part of the screen it works on.
On Windows the process is made DPI-aware first, so screenshots and the pointer use the
same physical pixels. Text is pasted through the clipboard (newlines and tabs pressed as
keys), so an input method in the way and text beyond ASCII type as they are; the
clipboard is put back afterwards.

The user stays in charge of the machine:
- moving the pointer to a corner of the screen stops the episode (pyautogui's fail-safe);
- while the user uses the computer (harness_computer/presence.py: on Windows their own
  keyboard and mouse, told from injected input by raw input; on an X display and macOS the
  system's last-input time; everywhere the pointer moved since the agent's last step),
  steps are refused (the shield's reason "user_input") until they leave it alone for
  presence.QUIET_SECONDS, so the agent does not act under the user's hand;
- when the user also brought another window to the front, the refusal says so
  ("took_over"): the conversation then waits for the user to hand the computer back
  (runtime/conversation.py), and the agent does not take the screen back;
- an episode takes at most `step_limit` input steps.

The pointer and keys are the user's real ones (physical input), so every step that uses
them goes through the physical-input policy (harness/physical.py: the user's settings,
the run's rules, what the user granted this session) and the machine-wide coordination
(harness/coordination.py), in this order (physical.PhysicalStep, as Minecraft's are):
- the policy: allowed, or refused with the reason (never; nobody to ask), or refused with
  a request for the user (an asking level: the agent's session asks, and physical(op=
  "answer") brings the answer back as a grant), or allowed once the user has been idle
  (when_idle);
- the input lock, in turn with every other agent on this computer (at most
  physical.LOCK_WAIT_SECONDS), and, once it is held, the checks again: the window the step goes
  to (it may have changed meanwhile), the user's hand, and the window's owner (an agent
  owns a window once its input reached it; another agent's step into it is refused);
- the step, then the lock goes to the next in line. Long text gives the lock up between
  its pieces when another agent waits longer than `max_hold_seconds`.
Input of another agent (input-last.json) is not taken for the user's. Every step's result
says how it was delivered: {"mechanism": "physical", "status": "delivered" |
"not_delivered" | "unverified"}, with the app and window and the time spent waiting for
the lock.

Where the system has a desktop backend (harness/desktop: Windows; macOS; Linux on an X
display), steps also go to one window, in the background: an element's action (act), or
a click, drag, scroll, typed text or keys with a `window`, its points in that window's
picture. Each is tried in turn (the ladder): the element's semantic action (a left click
on an element that has one does that action), then input sent to the window (DevTools
for a Chromium the agent launched, else posted messages; on macOS events posted to the
app's process), and only then the real mouse and keyboard, which the
physical-input policy above decides, and only where the window is in front at the
point; otherwise the step is refused with the check "needs_physical", saying what was
tried. A semantic or targeted step needs no input lock and leaves the user's pointer,
keyboard and foreground window alone; its delivery says {"mechanism": "semantic" |
"targeted", "status": "delivered" | "unverified"}. The `workspace` option "apps" shows the
window the agent works in (use_window, launch) instead of the screen, and its steps go to
that window by default; apps the agent launches start off the user's screens, without
taking the foreground (use_window(visible=True) brings one onto them), and come back onto them when
the episode's worker closes. On macOS an apps workspace needs the Accessibility and
Screen Recording permissions for the process that runs the worker; without them its
episode does not start, and the refusal says where to allow them.

The `workspace` option "display" (Linux) gives the worker a display of its own
(harness/desktop/display.py: Xvfb, or a headless weston with Xwayland, of `display_size`):
the screen it shows is that display, the apps it launches run there, and its steps use
that display's pointer and keyboard (XTest), never the user's: no physical-input policy,
no input lock, deliveries {"mechanism": "targeted", "status": "delivered", "method":
"XTest"}. Its windows' elements and the window steps work there as above. The display ends
with the worker. On Windows and macOS (and on Linux when `display_backend` is "vm") the
display is a virtual machine of the workspace's own instead (harness/desktop/vm.py: QEMU
with the system's hypervisor, or macOS's Virtualization.framework; `vm` takes the
settings computer.vm_*, the app's settings by default), started from its disk image over
a layer of its own: the screen it shows is the machine's, and its steps go to the
machine's own pointer and keyboard ({"method": "QMP"} for QEMU, "VNC" for a
Virtualization.framework guest). Its windows are inside the machine: no window steps,
elements or launch() there. The machine and its layer end with the worker.

There is one task, "free": its instruction is the worker's `instruction` option, or, in an
interactive conversation (harness app --runs, harness chat), the user's own.

What the model learns of windows the agent does not own (the user's) is what the
window-details policy allows (harness/privacy.py: the settings' `privacy` section, a run's
level and rules): by default only that another window is in front (state "front":
"other"), never its app or title; windows() lists only the agent's own; refusals and
approval requests name such a window "another window". The agent owns a display
workspace's windows, the ones it launched (and their dialogs), and the ones window
ownership gives it. The user's own records keep the names: a step's delivery (the trace's
`input` record) and the request put to the user (`approval`).

Runs in any Python 3.11+ with mss, pyautogui, pyperclip and Pillow installed
(`pip install mss pyautogui pyperclip pillow`; a display workspace needs python-xlib instead);
they are imported when the worker starts, not when this module is imported. `screen`
replaces them (tests).
"""

import io
import os
import platform
import sys
import time
import uuid

import harness_computer.desktop as desktop
import harness_computer.physical as physical_policy
import harness_computer.presence as presence
import harness_computer.privacy as privacy
import harness_computer.sensitive as sensitive
from harness.sdk import EpisodeCursor, data_url
from harness.sdk import WORKER_METHODS, BenchWorker
from harness.sdk import Observation
from harness.sdk import fit_into
from harness.sdk import load_embodiment
from harness.sdk import home
from harness_computer.shield import DesktopShield, DesktopShieldProfile
from harness_computer import overlays
from harness_computer.overlays import TITLE as OVERLAY_TITLE

from .apps import JPEG_QUALITY, Desk

METHODS = (*WORKER_METHODS, "preview", "use_screen", "hand_back", "physical", "windows", "elements")
OPTIONS = {"instruction", "monitor", "max_side", "settle_seconds", "step_limit", "image_format", "shield",
           "embodiment", "screen", "follow", "physical", "workspace", "display_size", "display_backend", "vm", "strict_input"}
# What a worker shows and where its steps go: the screen (desktop), one window (apps), or a
# display of its own (display).
WORKSPACES = ("desktop", "apps", "display")
# The size of a display workspace's display.
DISPLAY_SIZE = (1280, 800)
# Why a display workspace in a virtual machine has no windows, elements or launch().
VM_WINDOWS = ("this display is a virtual machine's screen: its windows are inside the machine, out of reach of "
              "windows(), launch() and elements; open apps from its own desktop and work with the screen's steps "
              "(clicks, keys, typing)")
# How often the state reads the windows again for the rules (a window opened or closed).
WINDOW_MARKS_SECONDS = 0.5
# Steps that go to a window in an apps workspace (a wait and a noop go nowhere).
WINDOW_STEPS = ("click", "drag", "scroll", "type", "key")
DEFAULT_INSTRUCTION = ("No task yet: ask the user what to do on this computer (reply in plain text), and wait "
                       "for their answer.")


def create_environment(**options):
    unknown = set(options) - OPTIONS
    if unknown:
        raise ValueError(f"Unknown computer worker options: {sorted(unknown)}")
    return ComputerEnvironment(**options)


class Screen:
    """This computer's screen, pointer, keyboard and clipboard: mss for screenshots,
    pyautogui for the pointer and keys, pyperclip for pasting, Pillow for scaling."""

    def __init__(self, monitor=1):
        # Per-monitor DPI awareness first: importing pyautogui makes the process aware of
        # the primary's DPI only, and a process sets its awareness once. Without it a
        # monitor of another scale is seen enlarged (its pixels and the pointer's off).
        if sys.platform == "win32":
            from harness_computer.desktop import windows

            windows.dpi_aware()
        try:
            import mss  # noqa: F401
            import pyautogui
            import pyperclip  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError as error:
            raise RuntimeError("The computer worker needs mss, pyautogui, pyperclip and Pillow: "
                               "pip install mss pyautogui pyperclip pillow") from error
        self._pyautogui = pyautogui
        # A pointer moved into a screen corner raises FailSafeException at the next step.
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        self._grabber = None
        import mss as _mss

        with _mss.mss() as grabber:
            # mss lists the whole desktop first, then each monitor (1 the primary).
            self.monitors = [{"index": index, "left": area["left"], "top": area["top"], "width": area["width"],
                              "height": area["height"], "primary": bool(area.get("is_primary", index == 1)),
                              "name": str(area.get("name") or f"screen {index}")}
                             for index, area in enumerate(grabber.monitors) if index]
        self.select(int(monitor))

    def select(self, index):
        """Show and act on monitor `index` (1 the primary)."""
        if not 1 <= int(index) <= len(self.monitors):
            raise ValueError(f"monitor must be 1 to {len(self.monitors)}")
        area = self.monitors[int(index) - 1]
        self.index = int(index)
        self.left, self.top, self.width, self.height = area["left"], area["top"], area["width"], area["height"]

    def active_monitor(self):
        """The monitor of the active window (on Windows the foreground window's centre,
        elsewhere the pointer's place), or None."""
        x, y = self.position()
        if sys.platform == "win32":
            from harness_computer.desktop import windows

            front = windows.foreground()
            if front:
                left, top, width, height = windows.rect(front)
                x, y = left + width // 2, top + height // 2
        for area in self.monitors:
            if area["left"] <= x < area["left"] + area["width"] and area["top"] <= y < area["top"] + area["height"]:
                return area["index"]
        return None

    def grab(self, size, image_format, index=None):
        """The picture of monitor `index` (the selected one by default) at `size` (width,
        height), encoded as `image_format`."""
        import mss
        from PIL import Image

        index = int(index or self.index)
        area = self.monitors[index - 1]
        # mss objects belong to the thread that made them; the worker answers on one.
        if self._grabber is None:
            self._grabber = mss.mss()
        shot = self._grabber.grab(self._grabber.monitors[index])
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        # The user's timeline overlay is the user's, not part of the screen the agent works on.
        mask_overlays(image, area, overlays.rects())
        return encoded(fitted(image, size), image_format)

    def position(self):
        return tuple(self._pyautogui.position())

    def click(self, x, y, button, count):
        self._pyautogui.click(x, y, clicks=count, interval=0.08, button=button)

    def drag(self, x, y, to_x, to_y, seconds):
        self._pyautogui.moveTo(x, y)
        self._pyautogui.dragTo(to_x, to_y, duration=seconds, button="left")

    def scroll(self, direction, amount, x=None, y=None):
        if x is not None:
            self._pyautogui.moveTo(x, y)
        # Windows counts wheel clicks in 120ths; the other systems in clicks.
        clicks = amount * (120 if sys.platform == "win32" else 1)
        if direction in ("up", "down"):
            self._pyautogui.scroll(clicks if direction == "up" else -clicks)
        elif sys.platform == "win32":
            with self._pyautogui.hold("shift"):
                self._pyautogui.scroll(clicks if direction == "left" else -clicks)
        else:
            self._pyautogui.hscroll(-clicks if direction == "left" else clicks)

    def keys(self, keys):
        self._pyautogui.hotkey(*keys, interval=0.05)

    def paste(self, text):
        """Type `text` by pasting it, and put the clipboard back."""
        import pyperclip

        try:
            saved = pyperclip.paste()
        except Exception:
            saved = None
        pyperclip.copy(text)
        self._pyautogui.hotkey("command" if sys.platform == "darwin" else "ctrl", "v", interval=0.05)
        time.sleep(0.15)
        if saved is not None:
            pyperclip.copy(saved)

    def active_window(self):
        try:
            return self._pyautogui.getActiveWindowTitle()
        except Exception:
            return None

    def front(self):
        """Which window is in front: its handle on Windows, macOS and an X display (a page
        loading in it keeps it the same window), elsewhere its title."""
        if sys.platform == "win32":
            import ctypes

            return int(ctypes.windll.user32.GetForegroundWindow() or 0) or None
        if sys.platform == "darwin":
            window = _mac_window()
            if window and window.get("handle") is not None:
                return window["handle"]
        x11 = _x11()
        if x11 is not None:
            with x11.lock:
                return x11.active()
        return self.active_window()

    def keyboard_ready(self):
        """None when keys reach the window in front, else why not: on Windows its input method
        is put in English mode first (an open one would compose the keys as text)."""
        if sys.platform != "win32":
            return None
        from harness_computer.desktop import windows

        front = windows.foreground()
        return windows.keyboard_ready(front) if front else None

    def user_watch(self):
        """How the user's input is told (harness_computer/presence.py): raw input on Windows,
        the idle time of macOS and an X display."""
        return presence.watch()

    def failsafe(self):
        """The exception pyautogui raises when the pointer is in a corner."""
        return self._pyautogui.FailSafeException

    def set_failsafe(self, on):
        self._pyautogui.FAILSAFE = bool(on)

    def window_at(self, x=None, y=None):
        """The window at physical point (x, y), or the one in front: {handle, app, title,
        pid, shared} on Windows, macOS and an X display; elsewhere the front app and title
        as the system tells them (no handle), or None."""
        if sys.platform == "win32":
            from harness_computer.desktop import windows

            return windows.window_at(x, y)
        if sys.platform == "darwin":
            return _mac_window(x, y)
        if _x11() is not None:
            import harness_computer.desktop.linux as linux

            try:
                return linux.window_at(x, y)
            except Exception:
                return None
        return _x11_front()


class DisplayScreen:
    """A display workspace's screen: the display of its own (harness/desktop/display.py),
    its picture, and its pointer and keyboard through XTest. Text is typed (the display has
    no clipboard of the user's to borrow)."""

    def __init__(self, name):
        import harness_computer.desktop.linux as linux
        from harness_computer.desktop.inject import XTest

        self.name = name
        self._linux = linux
        self._x11 = linux.X11(name)
        self._input = XTest(self._x11)
        width, height = self._x11.size()
        self.monitors = [{"index": 1, "left": 0, "top": 0, "width": width, "height": height, "primary": True,
                          "name": name}]
        self.index, self.left, self.top, self.width, self.height = 1, 0, 0, width, height

    def select(self, index):
        if int(index) != 1:
            raise ValueError("a display workspace has one screen")

    def active_monitor(self):
        return 1

    def grab(self, size, image_format, index=None):
        with self._x11.lock:
            image = self._x11.screen_picture(0, 0, self.width, self.height)
        return encoded(fitted(image, size), image_format)

    def position(self):
        with self._x11.lock:
            return self._x11.pointer()

    def click(self, x, y, button, count):
        self._input.click(x, y, button, count)

    def drag(self, x, y, to_x, to_y, seconds):
        self._input.drag(x, y, to_x, to_y, seconds)

    def scroll(self, direction, amount, x=None, y=None):
        self._input.wheel(direction, amount, x, y)

    def keys(self, keys):
        self._input.keys(keys)

    def paste(self, text):
        self._input.type(text)

    def active_window(self):
        found = self.window_at()
        return (found or {}).get("title") or None

    def front(self):
        with self._x11.lock:
            return self._x11.active()

    def failsafe(self):
        return _NeverRaised

    def set_failsafe(self, on):
        pass

    def window_at(self, x=None, y=None):
        try:
            return self._linux.window_at(x, y, display=self.name)
        except Exception:
            return None

    def close(self):
        self._x11.close()


class VMScreen:
    """A display workspace's screen in a virtual machine of its own (harness/desktop/vm.py):
    the machine's picture fitted into the workspace's size, and its own pointer and
    keyboard (QEMU's through QMP, a Virtualization.framework guest's through VNC), never
    the user's. The machine may change its resolution (while it boots, or when its user
    does): points map onto the picture it last showed."""

    vm = True

    def __init__(self, machine, size=None):
        self.machine = machine
        self.name = machine.name
        self.method = "QMP" if getattr(machine, "hypervisor", None) == "qemu" else "VNC"
        width, height = size or DISPLAY_SIZE
        self.monitors = [{"index": 1, "left": 0, "top": 0, "width": width, "height": height, "primary": True,
                          "name": self.name}]
        self.index, self.left, self.top, self.width, self.height = 1, 0, 0, width, height
        self._shown = None

    def select(self, index):
        if int(index) != 1:
            raise ValueError("a display workspace has one screen")

    def active_monitor(self):
        return 1

    def grab(self, size, image_format, index=None):
        image = self.machine.screen.picture()
        self._shown = image.size
        # The machine's screen fitted into the workspace's (its points map back in _point),
        # that into the picture.
        return encoded(fitted(fitted(image, (self.width, self.height)), size), image_format)

    def _point(self, x, y):
        """A point of the workspace's screen as the machine's pixel."""
        if self._shown is None:
            self._shown = self.machine.screen.picture().size
        left, top, width, height = fit_into(self._shown, (self.width, self.height))
        return ((float(x) - left) * self._shown[0] / width, (float(y) - top) * self._shown[1] / height)

    def position(self):
        x, y = self.machine.screen.pointer
        if self._shown is None:
            return int(x), int(y)
        left, top, width, height = fit_into(self._shown, (self.width, self.height))
        return int(round(left + x * width / self._shown[0])), int(round(top + y * height / self._shown[1]))

    def click(self, x, y, button, count):
        self.machine.screen.click(*self._point(x, y), button, count)

    def drag(self, x, y, to_x, to_y, seconds):
        self.machine.screen.drag(*self._point(x, y), *self._point(to_x, to_y), seconds)

    def scroll(self, direction, amount, x=None, y=None):
        point = self._point(x, y) if x is not None else (None, None)
        self.machine.screen.scroll(direction, amount, *point)

    def keys(self, keys):
        self.machine.screen.keys(keys)

    def paste(self, text):
        self.machine.screen.type(text)

    def active_window(self):
        return None

    def front(self):
        return None

    def failsafe(self):
        return _NeverRaised

    def set_failsafe(self, on):
        pass

    def window_at(self, x=None, y=None):
        return None

    def close(self):
        pass


def _display_route(choice, vm=None) -> str:
    """Where this worker's display workspace runs: "local" or "vm" (harness/desktop/display.py
    route), from the option, else the app's settings."""
    import harness_computer.desktop.display as display
    import harness_computer.desktop.vm as machines

    settings = machines.options({**(vm or {}), **({"display_backend": choice} if choice else {})})
    return display.route(settings.get("display_backend"))


class _NeverRaised(Exception):
    """A display workspace has no corner fail-safe: its pointer is not the user's."""


def _x11():
    """The user's X display (harness/desktop/linux.py), where this worker runs on one and
    has python-xlib; else None."""
    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        return None
    try:
        import harness_computer.desktop.linux as linux

        return linux.shared()
    except Exception:
        return None


def _display_size(value):
    """A display workspace's size: (width, height) from "WxH", [w, h] or None (DISPLAY_SIZE)."""
    if value is None:
        return DISPLAY_SIZE
    if isinstance(value, str):
        value = value.lower().split("x")
    width, height = (int(part) for part in value)
    if not (320 <= width <= 7680 and 240 <= height <= 4320):
        raise ValueError("display_size is WIDTHxHEIGHT, from 320x240 to 7680x4320")
    return width, height


def mask_overlays(image, area, rects, fill=(16, 16, 16)):
    """Paint the timeline overlays (`rects`: x, y, width, height in the units of `area`,
    the monitor shown) over in the picture `image` of that monitor (harness_computer/overlays.py: the
    agent's pictures leave them out). The picture may have more pixels than `area` has
    units (a Retina screen); returns how many were painted."""
    from PIL import ImageDraw

    sx, sy = image.width / max(area["width"], 1), image.height / max(area["height"], 1)
    draw = ImageDraw.Draw(image)
    painted = 0
    for x, y, width, height in rects:
        left, top = max(x - area["left"], 0), max(y - area["top"], 0)
        right, bottom = min(x + width - area["left"], area["width"]), min(y + height - area["top"], area["height"])
        if right <= left or bottom <= top:
            continue
        draw.rectangle([round(left * sx), round(top * sy), round(right * sx) - 1, round(bottom * sy) - 1], fill=fill)
        painted += 1
    return painted


def fitted(image, size):
    """`image` (Pillow) in a picture of `size`: as large as it fits, centred (fit_into), with
    dark bars where its shape is another."""
    from PIL import Image

    left, top, width, height = fit_into(image.size, size)
    if image.size != (width, height):
        image = image.resize((width, height), Image.LANCZOS)
    if (width, height) != tuple(size):
        canvas = Image.new("RGB", tuple(size), (16, 16, 16))
        canvas.paste(image, (left, top))
        image = canvas
    return image


def encoded(image, image_format) -> bytes:
    buffer = io.BytesIO()
    if image_format == "png":
        image.save(buffer, format="PNG")
    else:
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


# The steps that go where the keyboard is.
KEY_STEPS = ("key", "type")


def harness_window(window) -> bool:
    """Whether `window` ({app, title, ...}) is one of the harness's own on the user's
    screen: the timeline overlay (harness_computer/overlays.py TITLE)."""
    return bool(window) and window.get("title") == OVERLAY_TITLE


def _run(command, seconds=2.0):
    import subprocess

    try:
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=seconds).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _mac_window(x=None, y=None):
    """The window at (x, y), else the one in front, with the desktop backend's handle (the
    window server's number); without pyobjc the front app alone (osascript)."""
    try:
        import harness_computer.desktop.macos as macos

        return macos.window_at(x, y)
    except (ImportError, RuntimeError, OSError):
        return _mac_front()


def _mac_front():
    app = _run(["osascript", "-e", 'tell application "System Events" to get name of first application process '
                                   'whose frontmost is true'])
    return {"app": physical_policy.app_name(app), "title": None} if app else None


def _x11_front():
    import re

    active = re.search(r"window id # (0x[0-9a-f]+)", _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
    if not active:
        return None
    about = _run(["xprop", "-id", active.group(1), "_NET_WM_PID", "_NET_WM_NAME"])
    pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", about)
    title = re.search(r'_NET_WM_NAME\([^)]*\) = "(.*)"', about)
    app = None
    if pid:
        try:
            with open(f"/proc/{pid.group(1)}/comm", encoding="utf-8") as comm:
                app = physical_policy.app_name(comm.read().strip())
        except OSError:
            pass
    return {"app": app, "title": title.group(1) if title else None}


class ComputerEnvironment(BenchWorker):
    name = "this-computer"
    methods = METHODS
    managed_control_calls = frozenset({"tick", "physical", "use_screen", "hand_back"})
    LABEL = "computer worker"
    # Whether every step goes to a screen of the worker's own (the background browser's
    # page), never the user's pointer and keyboard: no physical-input policy, as on a
    # display of its own.
    own_input = False

    def __init__(self, instruction=None, monitor=1, max_side=1920, settle_seconds=0.5, step_limit=300,
                 image_format="jpeg", shield=None, embodiment="computer", screen=None, follow=True, physical=None,
                 workspace="desktop", backend=None, display_size=None, display_backend=None, vm=None,
                 strict_input=True):
        self._strict_input = strict_input
        if image_format not in ("jpeg", "png"):
            raise ValueError("image_format must be jpeg or png")
        if workspace not in WORKSPACES:
            raise ValueError(f"workspace is one of {', '.join(WORKSPACES)}")
        directory = home() / "apps" / f"worker-{os.getpid()}"
        self._display = None
        if workspace == "display" and (getattr(screen, "vm", False) or
                                       (screen is None and _display_route(display_backend, vm) == "vm")):
            # A virtual machine of its own, ended with the worker: its screen is the
            # workspace's, and it has no windows of this computer (a VMScreen given as
            # `screen` brings its machine: tests).
            if screen is None:
                from harness_computer.desktop.vm import VM

                settings = {**(vm or {}), **({"display_backend": display_backend} if display_backend else {})}
                machine = VM(_display_size(display_size), directory=home() / "vms" / f"worker-{os.getpid()}",
                             settings=settings).start()
                try:
                    screen = VMScreen(machine, _display_size(display_size))
                except BaseException:
                    machine.close()
                    raise
            self._display = screen.machine
        elif workspace == "display":
            # A display of its own, ended with the worker (`screen` and `backend` replace
            # it: tests).
            if screen is None or backend is None:
                from harness_computer.desktop.display import Display

                size = _display_size(display_size)
                self._display = Display(size, directory=home() / "displays" / f"worker-{os.getpid()}").start()
            try:
                if backend is None:
                    backend = desktop.backend("linux", directory=str(directory), display=self._display.name,
                                              private=True, env=self._display.env)
                if screen is None:
                    screen = DisplayScreen(self._display.name)
            except BaseException:
                if self._display is not None:
                    self._display.close()
                raise
        elif backend is None and desktop.available():
            # This system's windows, where it has a backend (`backend` replaces it: tests).
            try:
                backend = desktop.backend(directory=str(directory))
            except Exception as error:
                if workspace == "apps":
                    raise ValueError(f"an apps workspace needs this computer's desktop backend: {error}") from error
                backend = None
        if workspace == "apps" and backend is None:
            raise ValueError(f"an apps workspace needs a desktop backend, which this computer ({platform.system()}) "
                             f"does not have: {desktop.unavailable() or 'it could not be made'}")
        self._workspace = workspace
        self._desk = Desk(backend, max_side) if backend is not None else None
        # The windows as the rules last saw them: (when, rows) (_window_marks).
        self._marks = None
        self._instruction = str(instruction or DEFAULT_INSTRUCTION)
        self._embodiment = load_embodiment(embodiment)
        self._shield_options = {**self._embodiment.get("shield", {}), **(shield or {})}
        self._hz = float(self._embodiment["control_hz"])
        self._settle = float(settle_seconds)
        self._step_limit = int(step_limit)
        self._format = image_format
        # The operating system belongs to the worker that sends the inputs, which may
        # run on another machine from the harness or the app's browser.
        self._system = platform.system() or "unknown"
        self._screen = screen or Screen(monitor)
        pixels = (int(self._screen.width), int(self._screen.height))
        scale = min(1.0, float(max_side) / max(pixels))
        self._physical = pixels
        self._size = (max(1, round(pixels[0] * scale)), max(1, round(pixels[1] * scale)))
        self._shield = DesktopShield(DesktopShieldProfile.from_dict(self._shield_options, self._size), workspace=True)
        # With several monitors: show the active window's (follow), unless use_screen
        # holds one.
        self._follow = bool(follow)
        self._held = False
        self._cursor = EpisodeCursor()
        self._stopped = None
        self.new_outcome()
        # The physical-input policy, the user's hand and the input lock (physical.PhysicalStep;
        # `physical` is its options). The user's hand (presence.py): their input since the
        # agent's, the window in front when the computer was handed over, where the agent
        # left the pointer.
        watch = self._screen.user_watch() if hasattr(self._screen, "user_watch") else \
            presence.IdleWatch(getattr(self._screen, "idle_seconds", lambda: None))
        self._step = physical_policy.PhysicalStep(physical, watch, pointer=self._screen.position,
                                                  front=self._screen.front)
        self._gate, self._presence = self._step.gate, self._step.presence
        # What the model learns of the windows the agent does not own: the same settings
        # file's `privacy` section, and the run's level and rules (identify).
        self._privacy = privacy.View(self._gate.settings_file)

    # -- Worker protocol ---------------------------------------------------------

    def reset(self, task, seed):
        if task != "free":
            raise ValueError(f"This computer has one task, \"free\", not {task!r}")
        episode = uuid.uuid4().hex
        self._cursor.start(episode)
        # A new episode is the worker's own until its session identifies itself.
        self._step.reset()
        self._privacy.identify()
        self._presence.hand_back()
        self._approvals = sensitive.Approvals()
        self._approved_receipts = {}
        self._marks = None
        self._closed_windows = []
        if self._desk is not None:
            self._desk.reset()
            if self._workspace == "apps" and hasattr(self._desk.backend, "require"):
                # What the system must allow first (macOS): the refusal says where.
                self._desk.backend.require("accessibility", "screen_recording")
        self._stopped = None
        self.new_outcome()
        # The screenshot first: it picks the screen the state then names.
        images = self._screenshot()
        return Observation(episode, 0, self._instruction, {**self._state(), "task": "free"}, images)

    def close(self):
        self._cursor.invalidate()
        self._gate.windows.release_all(self._gate.owner)
        self._presence.close()
        if self._desk is not None:
            self._desk.backend.close()
        if self._display is not None:
            if hasattr(self._screen, "close"):
                self._screen.close()
            self._display.close()
            self._display = None

    # -- Calls -------------------------------------------------------------------

    def _call_profile(self):
        return {"kind": "desktop", "embodiment": self._embodiment["name"], "control_hz": self._hz,
                "screen": list(self._size), "physical_screen": list(self._physical),
                "shield": dict(self._shield_options), "step_limit": self._step_limit, "task": "free",
                "system": self._system, "benchmark": None,
                "physical": self._workspace != "display" and not self.own_input,
                # The user may take this computer over and hand it back (hand_back).
                "hand_back": self._workspace != "display" and not self.own_input,
                "workspace": self._workspace, "windows": self._workspace != "desktop" and self._desk is not None, "action_ids": True,
                **({"display": self._display.describe()} if self._display is not None else {}), **self._permissions()}

    def _permissions(self):
        """What the system allows the backend (macOS): {"permissions": {...}}, else nothing."""
        if self._desk is None or not hasattr(self._desk.backend, "permissions"):
            return {}
        try:
            return {"permissions": self._desk.backend.permissions()}
        except (OSError, RuntimeError):
            return {}

    _managed_approval = False

    def _call_tick(self, episode_id, step, command, cameras=None, execution_id=None, action_id=None):
        if execution_id is not None and (not isinstance(execution_id, str) or not 0 < len(execution_id) <= 128):
            raise ValueError("Invalid originating execution id")
        if action_id is not None and (not isinstance(action_id, str) or not 0 < len(action_id) <= 128):
            raise ValueError("Invalid action id")
        attempt = sensitive.Attempt(episode_id, step, execution_id, command, tuple(cameras or ()), action_id)
        return self._action_receipt(attempt, cameras)

    def _action_receipt(self, attempt, cameras):
        receipt = self._tick(attempt, cameras)
        if attempt.action_id is not None:
            receipt["action_id"] = attempt.action_id
        return receipt

    def _sensitive_approval(self, op, request_id, episode_id, execution_id, *,
                            step=None, command=None, cameras=None, action_id=None):
        """Only WorkerAPI's authenticated host RPC can reach this path."""
        if op == "receipt":
            return self._approved_receipts.get((episode_id, execution_id, request_id, action_id))
        if op not in ("inspect", "cancel", "retry"):
            raise ValueError("Unknown sensitive approval operation")
        pending = self._approvals.get(request_id, episode_id, execution_id, claim=op == "retry")
        if op == "cancel":
            return {"cancelled": pending is not None and self._approvals.discard(request_id)}
        if pending is None:
            raise PermissionError("No pending sensitive approval for this episode and execution")
        if op == "inspect":
            return pending.request
        if (type(step) is not int or step < pending.request["step"]
                or action_id != pending.request.get("action_id")
                or sensitive.fingerprint((command, tuple(cameras or ()))) != pending.command):
            raise PermissionError("Sensitive retry does not match the refused tick")
        attempt = sensitive.Attempt(episode_id, step, execution_id, command, tuple(cameras or ()), action_id, pending)
        receipt = self._action_receipt(attempt, cameras)
        # Retain control receipts rather than screenshots. The next observation is read
        # separately when the host recovers a timed-out delivery.
        self._approved_receipts[(episode_id, execution_id, request_id, action_id)] = {
            key: value for key, value in receipt.items() if key != "observation"}
        if len(self._approved_receipts) > 64:
            del self._approved_receipts[next(iter(self._approved_receipts))]
        return receipt

    def _tick(self, attempt, cameras):
        episode_id, step, command = attempt.episode_id, attempt.step, attempt.command
        self._cursor.check(episode_id, step)
        if attempt.pending is None:
            self._approvals.supersede(attempt.execution_id)
        if self._ended():
            raise ValueError("The episode has ended; the command was not executed")
        decision = self._shield.check(command)
        if decision.command is None:
            return {"executed": False, "shield": decision.to_dict(), "state": self._state()}
        if self._managed_approval and self._strict_input and decision.command["type"] == "type" and not self.own_input and any(
                char in decision.command["text"] for char in ("\t", "\n")):
            return self._refused({"check": "sensitive", "reason": "separate text from focus-changing keys"})
        if self._workspace == "desktop" and not self.own_input and (
                decision.command["type"] in ("launch", "use_window", "act") or "window" in decision.command):
            return self._refused({"check": "workspace", "reason":
                                  "desktop uses screenshot coordinates and real mouse/keyboard input; "
                                  "background window and element operations require an apps or browser workspace"})
        if decision.command["type"] in ("launch", "use_window"):
            return self._workspace_tick(decision, cameras, attempt)
        if not self.own_input and (decision.command["type"] == "act" or decision.command.get("window") or
                                   (self._workspace == "apps" and decision.command["type"] in WINDOW_STEPS)):
            return self._window_tick(decision, cameras, attempt)
        off = self._off_picture(decision.command)
        if off is not None:
            return self._refused(off)
        if self._workspace == "display" or self.own_input:
            return self._display_tick(decision, cameras, attempt)
        command = decision.command
        actions = physical_policy.actions_of(command)
        if not actions:
            if attempt.pending is not None:
                return self._approval_target_changed()
            # A wait sends no input: nothing physical, no lock.
            used = self._user_input()
            if used is not None:
                return self._refused(used)
            checked = time.monotonic()
            self._do(command)
            self._cursor.advance()
            self._presence.since = checked
            return self._executed(decision, cameras)
        window = self._window_of(command)
        verdict = self._decide(window, actions)
        refusal = self._verdict(verdict, window)
        if refusal is not None:
            return refusal
        # Taken in turn: the window, the user's hand and the window's owner again.
        taken = self._step.take(window, actions, verdict, again=lambda: self._window_of(command), shown=self._shown)
        if isinstance(taken, dict):
            return self._stated(taken)
        held, window, verdict = taken
        conditions = verdict["conditions"]
        began = stopped = None
        try:
            if conditions["yield_on_user_input"]:
                used = self._user_input()
                if used is not None:
                    return self._refused(used, window, waited=held.waited)
            # Before the owner check, which makes a free window the agent's.
            refusal = self._focus(command, window) or self._keys_ready(command)
            if refusal is not None:
                return self._refused(refusal, window, waited=held.waited)
            owned = self._shield.owner(self._gate.windows, window, self._gate.owner, self._named(window))
            if owned is not None:
                return self._refused(owned, window, waited=held.waited)
            refusal = self._screen_sensitive(command, window, attempt, route="physical")
            if refusal is not None:
                return refusal
            if hasattr(self._screen, "set_failsafe"):
                self._screen.set_failsafe(conditions["corner_stop"])
            began = time.time()
            stopped = self._sent(lambda: self._do(command, held, conditions))
        finally:
            # Input up to the end of the agent's own is the agent's.
            delivery = self._step.delivered(held, began, window, self._screen.position(), stopped is not None) \
                if began is not None else held.release()
        self._cursor.advance()
        if stopped is not None:
            # Text that gave the lock up and could not go on: part of it was typed.
            self._settled()
            return {"executed": False, "state": self._state(), "delivery": delivery,
                    "shield": {"verdict": "rejected", "command": None, "reasons": [stopped]}}
        return self._executed(decision, cameras, delivery)

    def _workspace_tick(self, decision, cameras, attempt):
        command = decision.command
        kind = command["type"]
        if attempt.pending is not None or (self._managed_approval and self._strict_input and kind == "launch"):
            return self._refused({"check": "workspace", "reason": "this workspace cannot authorize application launch"})
        if self._desk is None:
            return self._refused({"check": "window", "reason": "this workspace has no desktop window access"})
        arguments = {key: value for key, value in command.items() if key != "type"}
        try:
            if kind == "use_window":
                self._use_window(**arguments)
            else:
                self._launch(**arguments)
        except (LookupError, PermissionError) as error:
            if kind != "use_window":
                self._cursor.invalidate()
                raise RuntimeError("The window action's delivery is unverified") from error
            return self._refused({"check": "window", "reason": str(error)})
        except Exception as error:
            self._cursor.invalidate()
            raise RuntimeError("The window action's delivery is unverified") from error
        self._cursor.advance()
        receipt = self._executed(decision, cameras, {"mechanism": "targeted", "status": "delivered",
                                                    "window": self._desk.current})
        receipt["result"] = {"window": receipt["state"].get("window")}
        return receipt

    def _display_tick(self, decision, cameras, attempt):
        """A step on a screen of the worker's own: a display's pointer and keyboard (XTest on
        a display, QMP or VNC in a virtual machine) or the background browser's page (CDP),
        never the user's, so no policy and no input lock."""
        command = decision.command
        try:
            refusal = self._display_input(command, attempt)
            if refusal is not None:
                return refusal
        except Exception as error:
            self._cursor.invalidate()
            raise RuntimeError(f"{error} (the input may have reached the display: its delivery is unverified)") \
                from error
        self._cursor.advance()
        if command["type"] not in ("act", "navigate") and not physical_policy.actions_of(command):
            return self._executed(decision, cameras)
        name = getattr(self._screen, "name", None) or (self._display.name if self._display else None)
        return self._executed(decision, cameras, {"mechanism": "semantic" if command["type"] == "act" else "targeted",
                                                  "status": "delivered", "method": getattr(self._screen, "method", "XTest"),
                                                  **({"display": name} if name else {})})

    def _display_input(self, command, attempt):
        refusal = self._screen_sensitive(command, self._window_of(command), attempt, route="display")
        if refusal is not None:
            return refusal
        self._do(command)

    def _executed(self, decision, cameras, delivery=None):
        self._settled()
        result = {"executed": True, "shield": decision.to_dict(), "state": self._state()}
        if delivery is not None:
            result["delivery"] = delivery
        if cameras:
            images = self._screenshot()
            result["observation"] = {"state": self._state(), "images": images}
            result["state"] = result["observation"]["state"]
        return result

    def _settled(self):
        time.sleep(self._settle)
        if not self._presence.used_since(self._presence.since):
            # The window in front is the agent's, unless the user used the computer meanwhile.
            self._presence.front = self._screen.front()

    def _refused(self, reason, window=None, waited=None, approval=None, mechanism="physical"):
        """A step that did not reach the computer, with the shield's reason."""
        return self._stated(physical_policy.refused(reason, window, waited, approval, mechanism))

    def _stated(self, result):
        return {**result, "state": self._state()}

    def _verdict(self, verdict, window, idle_wait=True):
        """The refusal a policy verdict makes of a step (None: it may go on; PhysicalStep):
        the request put to the user names the window, the one the model reads names it as
        the window-details policy allows."""
        refusal = self._step.refusal(verdict, window, self._shown(window), idle_wait)
        return self._stated(refusal) if refusal is not None else None

    def _focus(self, command, window):
        """Why a step must not reach the window it would (None: it may). Never the
        harness's own windows (the user's timeline overlay: the agent never sees it, its
        pictures paint it over). Keys and text go where the keyboard is, so only to a window
        the agent works in (it clicked into, launched or chose it, or its own action opened it:
        a dialog of its app, the dialog's popups): typed into another one, they land in the
        user's window. A window the system names no handle for is not judged."""
        if harness_window(window):
            return {"check": "focus", "window": "the harness's timeline overlay",
                    "reason": "the user's timeline overlay is there (you never see it); nothing was done. Click "
                              "into the window you work in first, beside the overlay"}
        if command["type"] not in KEY_STEPS or not window or window.get("handle") is None:
            return None
        if window.get("shared"):
            return {"check": "focus", "window": "the desktop or the taskbar",
                    "reason": "the keyboard is on the desktop or the taskbar, not on a window you work in; nothing "
                              "was typed. Click into the window you want to type in first"}
        owner = self._gate.windows.owner(window["handle"])
        if owner is not None:
            # Another agent's window: the owner check refuses it with its own reason.
            return None
        if self._owns(window):
            # Its app's dialog, or a popup of a window it works in: the owner check claims it.
            return None
        name = self._named(window)
        return {"check": "focus", "window": name,
                "reason": f"the keyboard is on {name!r}, a window you have not clicked into or opened; nothing was "
                          "typed. Click into the window you want to type in first"}

    def _keys_ready(self, command):
        """Why keys or text of a step would not reach the window as keys (None: they
        would): an input method that stays open on it (Screen.keyboard_ready)."""
        if command["type"] not in KEY_STEPS or not hasattr(self._screen, "keyboard_ready"):
            return None
        return self._screen.keyboard_ready()

    def _window_of(self, command):
        """The window a step goes to: the one under its point, else the one in front (keys,
        text, a scroll where the pointer is)."""
        if not hasattr(self._screen, "window_at"):
            return None
        try:
            if command["type"] in ("click", "drag") or (command["type"] == "scroll" and "x" in command):
                return self._screen.window_at(*self._physical_point(command["x"], command["y"]))
            return self._screen.window_at()
        except Exception:
            return None

    def _approval_target_changed(self, window=None):
        return self._refused({"check": "sensitive", "reason": "the approved target is no longer there or changed; "
                              "inspect the current target before trying again"}, window)

    def _sensitive(self, command, element, window, attempt, *, route, retryable=True):
        """The refusal of a sensitive step the user has not approved yet, with its approval
        request (harness_computer/sensitive.py), else None."""
        stable = element is not None and element.get("key") is not None and element.get("stable_identity", True)
        if not stable and self._managed_approval and self._strict_input:
            return self._refused({"check": "sensitive", "reason": "the live input target could not be identified"}, window)
        found = sensitive.kind_of(command, element, (window or {}).get("app"))
        if found is None:
            return self._approval_target_changed(window) if attempt.pending is not None else None
        kind, target = found
        if not retryable:
            return self._refused({"check": "sensitive", "reason": "use an element action for this target"}, window)
        resolved = window or {}
        element_key = (element or {}).get("key")
        binding = sensitive.fingerprint((route, command, kind, target, resolved.get("handle"), resolved.get("pid"),
                                         resolved.get("app"), resolved.get("title"), element_key))
        if attempt.pending is not None:
            if stable and attempt.pending.target == binding and time.monotonic() < attempt.pending.expires:
                return None
            return self._approval_target_changed(window)
        if attempt.execution_id is None or not stable:
            return self._refused({"check": "sensitive", "kind": kind,
                                  "reason": "this action requires a trusted user approval"}, window)
        shown = self._shown(window)
        if not self._seen(window):
            target = "the input target"
        request = self._approvals.request(
            attempt, kind, target, physical_policy.actions_of(command) or [command["type"]],
            binding=binding, app=shown["app"], window=shown["title"])
        return self._refused({"check": "sensitive", "kind": kind, "approval": True,
                              "reason": f"{target} is a sensitive step ({kind}): it waits for the user's approval"},
                             window, approval=request, mechanism="semantic" if command["type"] == "act" else "physical")

    def _screen_sensitive(self, command, window, attempt, *, route):
        if command["type"] not in ("click", "type", "key"):
            return self._approval_target_changed(window) if attempt.pending is not None else None
        if attempt.pending is not None:
            return self._refused({"check": "sensitive", "reason": "use an element action for this target"}, window)
        point = self._physical_point(command["x"], command["y"]) if command["type"] == "click" else None
        element = self._input_element(self._input_tree(window), point)
        return self._sensitive(command, element, window, attempt, route=route, retryable=False)

    def _input_tree(self, window):
        if self._desk is None or not window or window.get("handle") is None:
            return []
        try:
            row = self._desk.backend.window(window["handle"])
            return self._desk.backend.tree(row) if row is not None else []
        except (LookupError, OSError, RuntimeError):
            return []

    @staticmethod
    def _input_element(elements, point):
        if point is not None:
            return desktop.element_at(elements, *point)
        return next((element for element in elements if "focused" in element.get("states", ())), None)

    def _call_physical(self, op, episode_id=None, **arguments):
        """The physical-input policy of this worker's episode (PhysicalStep.call): status
        (with the windows agents own), identify (and privacy: the run's window-details
        policy), check (a step into the window in front, or into `app`), answer."""
        if op == "status":
            mine = physical_policy.owner_name(self._gate.owner)
            return {**self._step.call("status"),
                    "windows": [item if item.get("owner") == mine else
                                {key: value for key, value in item.items() if key not in ("app", "title")}
                                for item in self._gate.windows.listed()]}
        self._cursor.check(episode_id, self._cursor.step)
        if op == "answer":
            if self._approvals.discard(arguments.get("id")):
                return {"kept": None}
        if op == "identify":
            seen = dict(arguments.pop("privacy", None) or {})
            if set(seen) - {"level", "rules"}:
                raise ValueError("privacy is {level, rules}: the run's window-details policy")
            self._privacy.identify(seen.get("level"), seen.get("rules") or ())
        window = self._screen.window_at() if op == "check" and hasattr(self._screen, "window_at") else None
        return self._step.call(op, window, self._shown(window), **arguments)

    def _call_use_screen(self, episode_id, index=None):
        """Show and act on monitor `index` from now on (screenshots and the points of input
        steps), or follow the active window again (None)."""
        self._cursor.check(episode_id, self._cursor.step)
        monitors = getattr(self._screen, "monitors", None) or []
        if index is None:
            self._held = False
            self._track()
        else:
            if not 1 <= int(index) <= max(1, len(monitors)):
                raise ValueError(f"This computer has screens 1 to {max(1, len(monitors))}")
            if monitors:
                self._screen.select(int(index))
                self._physical = (int(self._screen.width), int(self._screen.height))
            self._held = True
        return self._state()

    def _call_hand_back(self, episode_id):
        """The user handed the computer back (after Take over, a pause): it is the agent's
        as it is now."""
        self._cursor.check(episode_id, self._cursor.step)
        self._presence.hand_back()
        return self._state()

    def _call_windows(self, episode_id):
        """The windows (ids, app, title, picture size, minimized, launched...) and the one
        the agent works in."""
        self._cursor.check(episode_id, self._cursor.step)
        desk = self._windows_desk()
        return {"windows": desk.rows(self._listed), "current": desk.current}

    def _use_window(self, window, visible=None):
        """Work in `window` from now on: it becomes the agent's (refused when another agent
        owns it), the observations of an apps workspace show it, and steps go to it. With
        `visible`, a window the agent launched moves onto the user's screens (True) or off
        them (False), without taking the foreground."""
        desk = self._windows_desk()
        name, row = desk.window(window)
        self._claim(row)
        desk.current = name
        if visible is not None:
            row = desk.backend.show(row, bool(visible))
            desk.windows.assign(row["handle"], row)

    def _launch(self, app, args=(), visible=False):
        """Start `app` (a program name or path; a Chromium browser or an Electron app is also
        driven over DevTools) and work in its window: off the user's screens and without
        the foreground unless `visible`."""
        desk = self._windows_desk()
        row = desk.backend.launch(app, [str(arg) for arg in args], visible=bool(visible))
        name = desk.add(row)
        self._claim(row)
        desk.current = name

    def _call_elements(self, episode_id, window=None, role=None, text=None, limit=200):
        """Window `window`'s elements (the current one): each with its id, role, name,
        value, rect (in the window's picture), actions and states; those of `role` and
        with `text` in the name or value, at most `limit` ("more": how many it left out),
        and the same as outline lines."""
        self._cursor.check(episode_id, self._cursor.step)
        desk = self._windows_desk()
        limit = max(1, min(int(limit), 1000))
        # Reading a window's elements is working in it: it becomes the agent's first.
        self._claim(desk.window(window)[1])
        rows, more, outline = desk.listed(window, role, text, limit)
        return {"elements": rows, "more": more, "outline": outline}

    def _windows_desk(self):
        if self._workspace == "desktop" and not self.own_input:
            raise RuntimeError("desktop exposes screenshots and real mouse/keyboard input, not window tools")
        if self._desk is None and getattr(self._screen, "vm", False):
            raise RuntimeError(VM_WINDOWS)
        if self._desk is None:
            raise RuntimeError(f"this computer ({self._system}) has no desktop backend here "
                               f"({desktop.unavailable() or 'it could not be made'}): use the screen's steps")
        return self._desk

    def _claim(self, row):
        owned = self._shield.owner(self._gate.windows, row, self._gate.owner, self._named(row))
        if owned is not None:
            raise PermissionError(owned["reason"])

    # -- What the model learns of windows (harness/privacy.py) -------------------------------

    def _owns(self, window) -> bool:
        """Whether `window` is the agent's: any window of a display workspace's own display,
        one it launched (or a dialog of one), one window ownership gives it."""
        if not window:
            return False
        if self._workspace == "display" or window.get("launched"):
            return True
        if self._desk is not None and self._desk.launched_here(window):
            return True
        handle = window.get("handle")
        if handle is None or window.get("shared"):
            return False
        entry = self._gate.windows.owner(handle)
        if entry is not None and entry.get("owner") == physical_policy.owner_name(self._gate.owner):
            return True
        return window.get("owner") is not None and self._owns({"handle": window["owner"]})

    def _seen(self, window) -> dict | None:
        """What the model may learn of `window`: of the agent's own {"own": True, app,
        title}; of another what the window-details policy allows (None: nothing; {}: that
        it is there; its app; its app and title)."""
        if not window:
            return None
        if self._owns(window):
            return {"own": True, **{key: window[key] for key in ("app", "title") if window.get(key)}}
        return self._privacy.shown(window, session=self._gate.session, agent=self._gate.agent,
                                   workspace=self._workspace)

    def _named(self, window) -> str:
        """A window as the model may name it: its title or app, else "another window"."""
        seen = self._seen(window) or {}
        return seen.get("title") or seen.get("app") or privacy.OTHER

    def _listed(self, row) -> dict | None:
        """A backend row as windows() lists it (None: not listed): the agent's own, and the
        others with what the policy allows of them (an app at least)."""
        seen = self._seen(row)
        if seen is None or not (seen.get("own") or seen.get("app") or seen.get("title")):
            return None
        return {**row, "app": seen.get("app"), "title": seen.get("title")}

    def _decide(self, window, actions) -> dict:
        """The physical-input policy's verdict for a step into `window`: decided on the
        window itself, its reasons naming it as the model may."""
        return self._step.decide(window, actions, self._shown(window))

    def _shown(self, window) -> dict:
        """`window` as the model may learn of it (the window-details policy): app, title."""
        seen = self._seen(window) or {}
        return {"app": seen.get("app"), "title": seen.get("title")}

    # -- Steps into a window (the ladder) --------------------------------------------

    def _window_tick(self, decision, cameras, attempt):
        """A step into one window: semantic, else targeted, else physical as the policy
        allows (see the module's text)."""
        command = dict(decision.command)
        if self._desk is None and getattr(self._screen, "vm", False):
            return self._refused({"check": "window", "reason": VM_WINDOWS}, mechanism="targeted")
        if self._desk is None:
            return self._refused({"check": "window", "reason": f"this computer ({self._system}) has no background "
                                  "access to windows yet; use the screen's steps (no window, no element)"},
                                 mechanism="targeted")
        desk = self._desk
        element = None
        try:
            if command["type"] == "act":
                element = desk.element(command["element"])
                name, window = desk.window(element["window_id"])
                _, _, current = desk.tree(name)
                if command["element"] not in current:
                    if attempt.pending is not None:
                        return self._approval_target_changed(window)
                    return self._refused({"check": "element", "reason":
                                          f"element {command['element']!r} is no longer there; nothing was done"},
                                         window, mechanism="semantic")
                element = desk.element(command["element"])
                if not element.get("stable_identity", True):
                    return self._refused({"check": "element", "reason": "the backend has no stable id for this element"},
                                         window, mechanism="semantic")
            else:
                name, window = desk.window(command.get("window"))
                for x, y in (("x", "y"), ("to_x", "to_y")):
                    if x in command and not desk.inside(name, command[x], command[y]):
                        width, height = desk.size(window["rect"])
                        return self._refused({"check": "bounds", "reason": f"({command[x]}, {command[y]}) is not in "
                                              f"window {name}'s picture ({width} x {height}); nothing was done"},
                                             window, mechanism="targeted")
        except LookupError as error:
            return self._refused({"check": "window", "reason": f"{error}; nothing was done"}, mechanism="targeted")
        owned = self._shield.owner(self._gate.windows, window, self._gate.owner, self._named(window))
        if owned is not None:
            return self._refused(owned, window, mechanism="targeted")
        tried, delivery, event = [], None, None
        # A page driven over DevTools (a Chromium launched here) gets a click as the mouse's:
        # its scripts listen to mouse events, and an accessibility action standing for the
        # click is reported done while a script-built control (a custom dropdown) ignores it.
        devtools = bool(window.get("cdp"))
        try:
            if element is not None:
                refusal = self._sensitive(command, element, window, attempt, route="element")
                if refusal is not None:
                    return refusal
                action = command["action"]
                if action == "click" and devtools:
                    if attempt.pending is not None:
                        return self._refused({"check": "sensitive", "reason": "this backend cannot bind the click"},
                                             window, mechanism="semantic")
                    if "offscreen" in (element.get("states") or ()):
                        self._semantic(element, "scroll_into_view", None, tried)
                        _, _, current = desk.tree(name)
                        if command["element"] not in current:
                            return self._approval_target_changed(window)
                        element = desk.element(command["element"])
                    action = None
                elif action == "click":
                    action = desktop.click_action(element)
                    tried.append("semantic: the element has no action a click stands for") if action is None else None
                if action is not None:
                    delivery = self._semantic(element, action, command.get("value"), tried)
                if delivery is None and command["action"] in ("click", "invoke", "toggle", "select", "expand"):
                    left, top, right, bottom = element["rect"]
                    event = {"type": "click", "x": (left + right) // 2, "y": (top + bottom) // 2}
            else:
                event = self._screen_event(name, command)
                under = None
                if event["type"] in ("click", "type", "key"):
                    point = (event["x"], event["y"]) if event["type"] == "click" else None
                    under = self._input_element(self._input_tree(window), point)
                    refusal = self._sensitive(command, under, window, attempt, route="window")
                    if refusal is not None:
                        return refusal
                elif attempt.pending is not None:
                    return self._approval_target_changed(window)
                if event["type"] == "click" and event.get("button", "left") == "left" and \
                        int(event.get("count", 1)) == 1 and not devtools:
                    action = desktop.click_action(under) if under else None
                    if action is not None:
                        delivery = self._semantic(under, action, None, tried)
        except LookupError as error:
            return self._refused({"check": "element", "reason": f"{error}; nothing was done"}, window,
                                 mechanism="semantic")
        if delivery is None and event is not None and attempt.pending is None:
            _, window = desk.window(name)
            refusal = self._check_window_target(decision.command, event, window, attempt, expected=element)
            if refusal is not None:
                return refusal
            try:
                delivery = desk.backend.input(window, event)
            except desktop.NeedsPhysical as refusal:
                tried += [*refusal.tried, f"targeted: {refusal.reason}"]
            except (OSError, RuntimeError, ValueError) as error:
                self._cursor.invalidate()
                raise RuntimeError("The window input's delivery is unverified") from error
        if delivery is None and event is not None and event["type"] == "type" and attempt.pending is None:
            delivery = self._semantic_text(name, decision.command, tried, attempt)
            if isinstance(delivery, dict):
                return delivery
        if delivery is None:
            if attempt.pending is not None:
                return self._refused({"check": "sensitive", "reason": "use an element action for this target"},
                                     window, mechanism="semantic")
            if event is None:
                return self._refused({"check": "semantic", "tried": tried,
                                      "reason": "; ".join(tried) + "; nothing was done"}, window, mechanism="semantic")
            return self._physical_window_step(decision, cameras, event, name, window, tried, attempt, element)
        self._cursor.advance()
        return self._executed(decision, cameras, {**delivery.to_dict(), **physical_policy.about(window), "window": name})

    def _semantic(self, element, action, value, tried):
        """Fall back only when the backend knows the operation was not sent."""
        if action not in (element.get("actions") or ()):
            tried.append(f"semantic: the element does not support {action}")
            return None
        try:
            return self._desk.backend.act(element, action, value)
        except desktop.NeedsPhysical as refusal:
            tried.append(f"semantic {action}: {refusal.reason}")
            return None
        except (OSError, RuntimeError, ValueError) as error:
            self._cursor.invalidate()
            raise RuntimeError("The semantic input's delivery is unverified") from error

    def _semantic_text(self, name, command, tried, attempt):
        """Text for a window that takes no typed input: appended to the value of the
        element with the keyboard focus, when it takes a value."""
        try:
            _, elements, _ = self._desk.tree(name)
        except (OSError, RuntimeError, LookupError):
            return None
        focused = next((element for element in elements if "focused" in element["states"]
                        and "set_value" in element["actions"]), None)
        if focused is None:
            tried.append("semantic: no element with the keyboard focus takes a value")
            return None
        _, window = self._desk.window(name)
        refusal = self._sensitive(command, focused, window, attempt, route="window")
        if refusal is not None:
            return refusal
        delivery = self._semantic(focused, "set_value", (focused.get("value") or "") + command["text"], tried)
        if delivery is not None:
            delivery.detail["note"] = "appended to the focused element's value (set_value)"
        return delivery

    def _screen_event(self, name, command):
        """A window step as the backend's event: its points on the screen."""
        event = {key: value for key, value in command.items() if key != "window"}
        for x, y in (("x", "y"), ("to_x", "to_y")):
            if x in event:
                event[x], event[y] = self._desk.to_screen(name, event[x], event[y])
        return event

    def _check_window_target(self, command, event, window, attempt, *, expected=None):
        if event["type"] not in ("click", "type", "key"):
            return None
        point = (event["x"], event["y"]) if event["type"] == "click" else None
        element = self._input_element(self._input_tree(window), point)
        if expected is not None and (element is None or element.get("key") != expected.get("key")):
            return self._approval_target_changed(window)
        return self._sensitive(command, element, window, attempt, route="window")

    def _physical_window_step(self, decision, cameras, event, name, window, tried, attempt, element):
        """The last rung: the real mouse and keyboard into a window, as the policy allows,
        and only where the window is in front (at the point)."""
        why = "; ".join(tried)
        point = (event["x"], event["y"]) if "x" in event else None
        if self._workspace == "display":
            return self._refused({"check": "needs_physical", "tried": tried, "reason": f"{why}; a display workspace "
                                  "has no physical input (its display is not the user's). Nothing was done"}, window,
                                 mechanism="targeted")

        def reachable():
            under = self._screen.window_at(*point) if point else self._screen.window_at()
            return bool(under) and under.get("handle") == window["handle"]

        if not reachable():
            where = "at that point" if point else "(keys go to the window in front)"
            return self._refused({"check": "needs_physical", "tried": tried, "reason": f"{why}; the real mouse and "
                                  f"keyboard would not reach it either: the window is not in front {where}. Nothing "
                                  "was done"}, window, mechanism="targeted")
        actions = physical_policy.actions_of(event)
        verdict = self._decide(window, actions)
        refusal = self._verdict(verdict, window)
        if refusal is not None:
            reason = refusal["shield"]["reasons"][0]
            refusal["shield"]["reasons"] = [{**reason, "check": "needs_physical", "policy": reason.get("check"),
                                             "tried": tried, "reason": f"{why}; physical input: {reason['reason']}"}]
            return refusal
        taken = self._step.take(window, actions, verdict)
        if isinstance(taken, dict):
            return self._stated(taken)
        held, window, verdict = taken
        conditions = verdict["conditions"]
        began = stopped = None
        try:
            if conditions["yield_on_user_input"]:
                used = self._user_input()
                if used is not None:
                    return self._refused(used, window, waited=held.waited)
            if not reachable():
                return self._refused({"check": "needs_physical", "tried": tried, "reason": "the window is no longer "
                                      "in front there; nothing was done"}, window, waited=held.waited)
            refusal = self._keys_ready(event)
            if refusal is not None:
                return self._refused(refusal, window, waited=held.waited)
            _, window = self._desk.window(name)
            refusal = self._check_window_target(decision.command, event, window, attempt, expected=element)
            if refusal is not None:
                return refusal
            began = time.time()
            stopped = self._sent(lambda: self._dispatch(event, held, conditions))
        finally:
            delivery = self._step.delivered(held, began, window, self._screen.position(), stopped is not None,
                                            {"window": name}) if began is not None else held.release()
        self._cursor.advance()
        if stopped is not None:
            self._settled()
            return {"executed": False, "state": self._state(), "delivery": delivery,
                    "shield": {"verdict": "rejected", "command": None, "reasons": [stopped]}}
        return self._executed(decision, cameras, delivery)

    def _sent(self, send):
        """`send()` on the real mouse and keyboard: the pointer in a corner (the fail-safe)
        ends the episode; another error may have reached the computer, so the episode cannot
        go on from a state nobody observed, and the step is never sent again."""
        try:
            return send()
        except self._screen.failsafe():
            self._stopped = "fail-safe"
            self._cursor.advance()
            raise RuntimeError("Stopped: the pointer reached a corner of the screen (the fail-safe); "
                               "the episode has ended") from None
        except Exception as error:
            self._cursor.invalidate()
            raise RuntimeError(f"{error} (the input may have reached the computer: its delivery is "
                               "unverified)") from error

    def _dispatch(self, event, held, conditions):
        """One window step with the real mouse and keyboard, its points on the screen."""
        kind, screen = event["type"], self._screen
        if kind == "click":
            screen.click(event["x"], event["y"], event.get("button", "left"), int(event.get("count", 1)))
            self._presence.left = (event["x"], event["y"])
        elif kind == "drag":
            screen.drag(event["x"], event["y"], event["to_x"], event["to_y"],
                        int(event.get("duration_ms", 400)) / 1000.0)
            self._presence.left = (event["to_x"], event["to_y"])
        elif kind == "scroll":
            screen.scroll(event["direction"], int(event.get("amount", 5)), event.get("x"), event.get("y"))
            self._presence.left = screen.position()
        else:
            return self._do(event, held, conditions)
        return None

    def _call_preview(self, max_side=960):
        """The screen for the user watching (the app's live view): smaller, at any time,
        nothing done and nothing counted. With several monitors it is the active window's
        (the one the agent's next screenshot shows), or the one use_screen holds; the
        agent's own screen is left as it is, so the points of its next steps stay on the
        screen it saw."""
        if self._workspace == "apps":
            data, size, _ = self._desk.picture(None, "jpeg", max_side=float(max_side))
            return {"image": data_url(data, "image/jpeg"), "size": size,
                    **({"window": self._desk.current} if self._desk.current else {})}
        scale = min(1.0, float(max_side) / max(self._size))
        size = (max(1, round(self._size[0] * scale)), max(1, round(self._size[1] * scale)))
        index = None
        if self._follow and not self._held and len(getattr(self._screen, "monitors", None) or []) > 1:
            index = self._screen.active_monitor()
        data = self._screen.grab(size, "jpeg", index) if index else self._screen.grab(size, "jpeg")
        result = {"image": data_url(data, "image/jpeg"), "size": list(size)}
        if index or len(getattr(self._screen, "monitors", None) or []) > 1:
            result["screen"] = int(index or self._screen.index)
        return result

    def _evaluate(self):
        steps = int(self._cursor.step or 0)
        self._cursor.invalidate()
        # No evaluator: success and reward are unknown, not failed.
        return {"reward": None, "success": None, "process_score": None, "terminated": False,
                "truncated": steps >= self._step_limit, "steps": steps, "status": "UNSCORED",
                "message": self._stopped or "this computer has no evaluator: the user judges the result"}

    # -- The computer ------------------------------------------------------------

    def _track(self):
        """Show the monitor of the active window, when following it (before a screenshot:
        the points of the next steps are on the screen the agent was shown)."""
        monitors = getattr(self._screen, "monitors", None) or []
        if not self._follow or self._held or len(monitors) < 2:
            return
        index = self._screen.active_monitor()
        if index and index != self._screen.index:
            self._screen.select(index)
            self._physical = (int(self._screen.width), int(self._screen.height))

    def _state(self):
        state = {"step": int(self._cursor.step or 0), "step_limit": self._step_limit, "ended": self._ended(),
                 "screen": list(self._size), "system": "macOS" if self._system == "Darwin" else self._system}
        monitors = getattr(self._screen, "monitors", None) or []
        if len(monitors) > 1:
            state["screens"] = [{"index": area["index"], "name": area["name"], "size": [area["width"], area["height"]],
                                 "primary": area["primary"], "shown": area["index"] == self._screen.index}
                                for area in monitors]
            state["following"] = self._follow and not self._held
        # The window in front: the agent's own ("front": "own", its title and app) or
        # another ("other", and what the window-details policy allows of it).
        front = self._front_window()
        seen = self._seen(front)
        if seen is not None:
            state["front"] = "own" if seen.get("own") else "other"
            if seen.get("title"):
                state["active_window"] = seen["title"]
            if seen.get("app"):
                state["active_app"] = seen["app"]
        if seen and front.get("handle") is not None and self._desk is not None:
            focus = self._desk.add(front) if seen.get("own") else self._desk.windows.name(front["handle"])
            if focus is not None:
                state["focus_id"] = focus
        if self._workspace in ("apps", "display"):
            state["workspace"] = self._workspace
        if self._display is not None:
            state["display"] = self._display.name
        if self._desk is not None and self._desk.current:
            try:
                state["window"] = self._desk.describe(*self._desk.window())
            except LookupError as error:
                state["window"] = {"id": self._desk.current, "closed": str(error)}
        if self._desk is not None and not self.own_input:
            state["windows"] = self._window_marks()
            state["closed_windows"] = list(self._closed_windows)
        return state

    def _window_marks(self):
        """The windows the agent may know, as the rules see them (state "windows", which the
        model is not shown): [{"id", "title", "dialog_of"}] of its own (a new one gets its
        id) and of those it was shown already, read at most every WINDOW_MARKS_SECONDS; the
        session tells window and dialog events from their change."""
        now = time.monotonic()
        if self._marks is None or now - self._marks[0] >= WINDOW_MARKS_SECONDS:
            desk, marks = self._desk, []
            try:
                rows = desk.backend.windows()
                handles = {row["handle"] for row in rows}
                prior = [row["id"] for row in self._marks[1]] if self._marks else []
                closed = [name for name in prior if (handle := desk.windows.key(name)) not in handles
                          and handle is not None and desk.backend.window(handle) is None]
                desk.windows.forget(closed)
                self._closed_windows = (self._closed_windows + closed)[-128:]
                for row in rows:
                    if self._owns(row):
                        desk.add(row)
                for row in rows:
                    name = desk.windows.name(row["handle"])
                    shown = self._listed(row) if name else None
                    if shown is not None:
                        about = desk.describe(name, shown)
                        marks.append({key: about[key] for key in ("id", "title", "dialog_of") if about.get(key)})
            except Exception:
                marks = None
            if marks is not None:
                self._marks = (now, marks)
        return list(self._marks[1]) if self._marks is not None else []

    def _front_window(self):
        """The window in front ({handle, app, title, ...}, or only its title where the
        system names no more), or None."""
        if hasattr(self._screen, "window_at"):
            try:
                return self._screen.window_at()
            except Exception:
                return None
        title = self._screen.active_window()
        return {"title": title} if title else None

    def _ended(self):
        return self._stopped is not None or int(self._cursor.step or 0) >= self._step_limit

    def _physical_point(self, x, y):
        """A command's scaled pixel as the screen's physical one (its centre); None in the
        bars of a monitor fitted into the picture."""
        left, top, width, height = fit_into(self._physical, self._size)
        if not (left <= float(x) < left + width and top <= float(y) < top + height):
            return None
        return (self._screen.left + int((float(x) - left + 0.5) * self._physical[0] / width),
                self._screen.top + int((float(y) - top + 0.5) * self._physical[1] / height))

    def _off_picture(self, command):
        """The shield's reason when a point of the command is in a bar of the picture."""
        points = [("x", "y"), ("to_x", "to_y")] if command["type"] == "drag" else [("x", "y")]
        for name_x, name_y in points:
            if name_x in command and self._physical_point(command[name_x], command[name_y]) is None:
                return {"check": "bounds", "reason": f"({command[name_x]}, {command[name_y]}) is in the dark bars "
                        "around this screen, not on it; nothing was done"}
        return None

    def _user_input(self):
        """The shield's reason when the user is using the computer (presence.UserPresence),
        their window named only as the window-details policy allows."""
        def named():
            seen = self._seen(self._front_window()) or {}
            return seen.get("title") or seen.get("app")

        return self._presence.check(named)

    def _do(self, command, held=None, conditions=None):
        """Send one step; None when all of it was sent, else the reason it stopped part way
        (text that gave the input lock up and could not take it back as it was)."""
        kind = command["type"]
        screen = self._screen
        if kind in ("noop", "wait"):
            time.sleep(1.0 / self._hz if kind == "noop" else int(command.get("ms", 1000)) / 1000.0)
            return None
        if kind == "click":
            x, y = self._physical_point(command["x"], command["y"])
            screen.click(x, y, command.get("button", "left"), int(command.get("count", 1)))
            self._presence.left = (x, y)
        elif kind == "drag":
            x, y = self._physical_point(command["x"], command["y"])
            to_x, to_y = self._physical_point(command["to_x"], command["to_y"])
            screen.drag(x, y, to_x, to_y, int(command.get("duration_ms", 400)) / 1000.0)
            self._presence.left = (to_x, to_y)
        elif kind == "scroll":
            point = self._physical_point(command["x"], command["y"]) if "x" in command else (None, None)
            screen.scroll(command["direction"], int(command.get("amount", 5)), *point)
            self._presence.left = screen.position()
        elif kind == "key":
            screen.keys([key for key in command["keys"]])
        elif kind == "type":
            # Pasted piece by piece; newlines and tabs are keys (a field may not take them pasted).
            pieces, piece = [], ""
            for char in command["text"]:
                if char in "\n\t":
                    if piece:
                        pieces.append(("paste", piece))
                        piece = ""
                    pieces.append(("key", "enter" if char == "\n" else "tab"))
                else:
                    piece += char
            if piece:
                pieces.append(("paste", piece))
            sent = 0
            for number, (how, what) in enumerate(pieces):
                stopped = None
                if number and held is not None and held.held_for() > conditions["max_hold_seconds"] \
                        and held.others_waiting():
                    stopped = self._yield(held, conditions)
                elif number and conditions and conditions["yield_on_user_input"]:
                    # The user takes the mouse or keyboard between two pieces: the rest waits for them.
                    used = self._user_input()
                    if used is not None:
                        stopped = {**used, "reason": "the user used the computer; the rest was not typed"}
                if stopped is not None:
                    return {**stopped, "typed": sent, "of": len(command["text"]),
                            "reason": f"typed {sent} of {len(command['text'])} characters, then "
                                      f"{stopped['reason']}"}
                if how == "paste":
                    screen.paste(what)
                    sent += len(what)
                else:
                    screen.keys([what])
                    sent += 1
                # Input up to the end of this piece is the agent's own.
                self._presence.since = time.monotonic()
        return None

    def _yield(self, held, conditions):
        """Give the input lock to the agent next in line between two pieces of a step, and
        take it back: None when the window in front is still this one and the user left it
        alone, else the reason to stop."""
        front = self._screen.window_at() if hasattr(self._screen, "window_at") else None
        held.record(time.time(), time.time(), self._screen.position(), (front or {}).get("handle"))
        if not held.pass_on(physical_policy.LOCK_WAIT_SECONDS):
            return {"check": "input_lock", "reason": "the input lock did not come back"}
        now = self._screen.window_at() if hasattr(self._screen, "window_at") else None
        if physical_policy.identity(now) != physical_policy.identity(front):
            return {"check": "physical", "reason": "another window came to the front meanwhile; the rest was not "
                                                   "typed"}
        if conditions["yield_on_user_input"]:
            used = self._user_input()
            if used is not None:
                return {**used, "reason": "the user used the computer meanwhile; the rest was not typed"}
        return None

    def _screenshot(self):
        kind = "png" if self._format == "png" else "jpeg"
        if self._workspace == "apps":
            try:
                data, _, _ = self._desk.picture(None, self._format)
            except LookupError:
                self._desk.current = None
                data, _, _ = self._desk.picture(None, self._format)
            return {"screen": data_url(data, f"image/{kind}")}
        self._track()
        data = self._screen.grab(self._size, self._format)
        return {"screen": data_url(data, f"image/{kind}")}
