"""The Linux backend (harness_computer.desktop.Backend) on an X display, on the system's own
interfaces:

- windows: the managed windows (the window manager's _NET_CLIENT_LIST; with none, the
  mapped top-level windows of the display), each with its process (_NET_WM_PID, else the
  X-Resource extension), its frame and its UI toolkit (the window class, else the
  libraries its process loaded).
- tree and act: AT-SPI over D-Bus (atspi.py): GTK, Qt, Chromium (its accessibility on),
  LibreOffice; Tk and plain X applications have no tree.
- capture: the Composite extension keeps every top-level window's own picture (the
  display's subwindows are redirected, automatically: the screen looks the same), so a
  covered window is captured as it is; without Composite, what the screen shows of it.
- input: for a Chromium or Electron app the agent launched, the DevTools protocol. On a
  display of the agent's own (a display workspace, `private`: nobody else sees or uses
  it) XTest, after raising and focusing the window there: the display's own pointer and
  keyboard, never the user's. On the user's display, events sent to the window
  (XSendEvent), with the pointer entering the widget and the window getting the focus
  sent around them (Tk needs both): Tk, Qt, Motif, Xaw and plain Xlib windows take them,
  GTK and xterm do not (NeedsPhysical); others are sent, unverified. A character the
  keyboard map lacks is typed on a private display by mapping a spare key for it; on the
  user's display it needs the real keyboard (the user's keyboard map is left alone).
- launch: the application starts on this display with its accessibility on (and a
  DevTools port for a Chromium or Electron app); on the user's display it is moved off
  the screens and the window that had the focus gets it back.

The probe of 2026-11-01 (Xvfb 21.1 with GTK 3.24, Tk 8.6, xterm and Chromium 156; weston
9 headless with Xwayland) set these choices, and that of 2026-11-02 (Qt 5.15, Motif 2.3,
Xaw, xev) the events sent around input; the PRs that brought them have their tables.

python-xlib and jeepney (the computer environment's, on Linux) are imported when a
backend is made.
"""

import contextlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from . import Backend, Delivery, NeedsPhysical
from . import atspi as accessibility
from . import cdp
from .cdp import MODIFIERS, DevTools, devtools_url, dispatch, page_session
from .inject import BUTTONS, WHEEL, XTest, _keysym

# UI toolkits by window class (WM_CLASS, its class part, lower case), then by the
# libraries the process loaded (/proc/PID/maps).
CLASS_FRAMEWORKS = {"tk": "tk", "chromium": "chromium", "chromium-browser": "chromium", "google-chrome": "chromium",
                    "google-chrome-for-testing": "chromium", "microsoft-edge": "chromium", "brave-browser": "chromium",
                    "xterm": "xt", "uxterm": "xt", "xclock": "xt", "xeyes": "xt"}
LIBRARY_FRAMEWORKS = (("libgtk-4.so", "gtk"), ("libgtk-3.so", "gtk"), ("libgtk-x11-2.0.so", "gtk"),
                      ("libQt6Gui.so", "qt"), ("libQt5Gui.so", "qt"), ("libelectron", "electron"),
                      ("libjvm.so", "java"), ("libwx_", "wx"), ("libfltk", "fltk"), ("libSDL2", "sdl"),
                      ("libglfw", "glfw"), ("libXm.so", "motif"), ("libXaw", "xt"), ("libXt.so", "xt"))
# Which windows take events sent to them (XSendEvent, with the pointer entering and the
# window's focus sent around them), by window class, then by toolkit: True, why not, or
# not measured (sent, unverified). The probe of 2026-11-02: Tk 8.6, Qt 5.15, Motif 2.3, Xaw
# (xmessage) and plain Xlib (xev) take clicks and keys; GTK 3 and xterm take neither.
SENT = {"tk": True, "qt": True, "motif": True, "xt": True, "x11": True,
        "gtk": "GTK windows drop pointer and key events sent to them",
        "xterm": "xterm drops events sent to it (its allowSendEvents resource is off by default)",
        "uxterm": "xterm drops events sent to it (its allowSendEvents resource is off by default)"}
# Chromium browsers by program name, and their flags (the window off the screens is
# drawn: occluded windows are not backgrounded).
CHROMIUMS = ("chrome", "google-chrome", "google-chrome-stable", "google-chrome-beta", "chromium", "chromium-browser",
             "microsoft-edge", "microsoft-edge-stable", "brave-browser")
CHROMIUM_FLAGS = ["--no-first-run", "--no-default-browser-check", "--disable-backgrounding-occluded-windows",
                  "--force-renderer-accessibility", "--remote-debugging-port=0", "--ozone-platform=x11"]
ELECTRON_FLAGS = ["--force-renderer-accessibility", "--remote-debugging-port=0", "--ozone-platform=x11"]
# The environment an application is launched with: an X client of this display, with its
# accessibility on (GTK 2 modules, Qt, Chromium, GNOME's switch).
ACCESSIBILITY_ENV = {"GDK_BACKEND": "x11", "QT_QPA_PLATFORM": "xcb", "NO_AT_BRIDGE": "0", "GNOME_ACCESSIBILITY": "1",
                     "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1", "QT_ACCESSIBILITY": "1", "ACCESSIBILITY_ENABLED": "1",
                     "GTK_MODULES": "gail:atk-bridge", "MOZ_ENABLE_WAYLAND": "0", "SDL_VIDEODRIVER": "x11"}
# Window types every agent shares, never listed.
SHARED_TYPES = ("_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_DOCK")
# X modifier masks of the modifier key names (ShiftMask, ControlMask, Mod1Mask, Mod4Mask).
MASKS = {"shift": 1, "shiftleft": 1, "shiftright": 1, "ctrl": 4, "ctrlleft": 4, "ctrlright": 4, "alt": 8,
         "altleft": 8, "altright": 8, "win": 64, "winleft": 64, "winright": 64, "command": 64}


def session_type() -> str:
    """"x11", "wayland" or "none": what this process's graphical session is."""
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    return "x11" if os.environ.get("DISPLAY") else "none"


def _pid_parent(pid) -> int | None:
    try:
        text = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8", errors="replace")
        return int(text.rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def processes() -> dict:
    """Every running process, from /proc: {pid: (parent pid, its command line's arguments)}."""
    found = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            parent = int(Path(f"/proc/{entry}/stat").read_text(encoding="utf-8", errors="replace")
                         .rsplit(")", 1)[1].split()[1])
            arguments = Path(f"/proc/{entry}/cmdline").read_bytes().split(b"\0")
        except (OSError, ValueError, IndexError):
            continue
        found[int(entry)] = (parent, [part.decode(errors="replace") for part in arguments if part])
    return found


def _descends(pid, root) -> bool:
    seen = set()
    while pid and pid not in seen:
        if pid == root:
            return True
        seen.add(pid)
        pid = _pid_parent(pid)
    return False


def image_path(pid) -> str | None:
    """The executable of process `pid` (else its name), or None."""
    try:
        return os.readlink(f"/proc/{int(pid)}/exe")
    except OSError:
        try:
            return Path(f"/proc/{int(pid)}/comm").read_text(encoding="utf-8").strip() or None
        except OSError:
            return None


def _app(path):
    from harness_computer import physical

    return physical.app_name(path)


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _blank(image) -> bool:
    extrema = image.getextrema()
    return all(high - low < 6 for low, high in extrema)


class X11:
    """One connection to an X display, and what the backend and the worker ask of it:
    windows, frames, pictures, the window at a point, the user's idle time, XTest input.
    Calls are serialized (python-xlib's display is used by one thread at a time)."""

    def __init__(self, name: str | None = None):
        try:
            from Xlib import X, Xatom, display
        except ImportError as error:
            raise RuntimeError("the Linux desktop backend needs python-xlib (the computer environment installs it)") \
                from error
        self.X, self.Xatom = X, Xatom
        self.name = name or os.environ.get("DISPLAY")
        if not self.name:
            raise RuntimeError("no X display: DISPLAY is not set")
        self.display = display.Display(self.name)
        self.root = self.display.screen().root
        self.lock = threading.RLock()
        self._atoms = {}
        self._composite = False
        extensions = set(self.display.list_extensions())
        self.extensions = extensions
        if "Composite" in extensions:
            from Xlib.ext import composite

            # Automatic redirection: the server keeps each top-level window's picture and
            # still draws the screen as before (no compositing manager needed).
            with contextlib.suppress(Exception):
                self.root.composite_redirect_subwindows(composite.RedirectAutomatic)
                self.display.sync()
                self._composite = True

    def atom(self, name):
        if name not in self._atoms:
            self._atoms[name] = self.display.intern_atom(name)
        return self._atoms[name]

    def close(self):
        with contextlib.suppress(Exception):
            self.display.close()

    def window(self, handle):
        return self.display.create_resource_object("window", int(handle))

    def prop(self, window, name, kind=0):
        try:
            found = window.get_full_property(self.atom(name), kind)
        except Exception:
            return None
        return None if found is None else found.value

    def size(self) -> tuple[int, int]:
        geometry = self.root.get_geometry()
        return int(geometry.width), int(geometry.height)

    def monitors(self) -> list:
        """The monitors' rects [l, t, r, b] (RandR), else the whole root window."""
        with self.lock:
            try:
                found = self.root.xrandr_get_monitors().monitors
                areas = [(m.x, m.y, m.x + m.width_in_pixels, m.y + m.height_in_pixels) for m in found]
                if areas:
                    return areas
            except Exception:
                pass
            width, height = self.size()
            return [(0, 0, width, height)]

    def title(self, window) -> str:
        value = self.prop(window, "_NET_WM_NAME")
        if value:
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
        try:
            name = window.get_wm_name()
        except Exception:
            name = None
        if isinstance(name, bytes):
            name = name.decode("latin-1")
        return name or ""

    def pid(self, window) -> int | None:
        value = self.prop(window, "_NET_WM_PID", self.Xatom.CARDINAL)
        if value:
            return int(value[0])
        if "X-Resource" in self.extensions:
            try:
                from Xlib.ext import res

                found = self.display.res_query_client_ids([{"client": window.id, "mask": res.LocalClientPIDMask}])
                for client in found.ids:
                    if client.value:
                        return int(client.value[0])
            except Exception:
                return None
        return None

    def toplevel(self, window):
        """The window's ancestor that is a child of the root (its frame, with a window
        manager that reparents)."""
        current = window
        for _ in range(16):
            tree = current.query_tree()
            if tree.parent is None or tree.parent.id == self.root.id or tree.parent.id == 0:
                return current
            current = tree.parent
        return current

    def rect(self, window) -> list[int]:
        geometry = window.get_geometry()
        origin = window.translate_coords(self.root, 0, 0)
        left, top = -origin.x, -origin.y
        return [left, top, left + geometry.width, top + geometry.height]

    def clients(self) -> list:
        """The managed windows (the window manager's list), else the mapped top-level
        windows that have a title."""
        X = self.X
        listed = self.prop(self.root, "_NET_CLIENT_LIST", self.Xatom.WINDOW)
        if listed:
            return [self.window(handle) for handle in listed]
        found = []
        for child in self.root.query_tree().children:
            try:
                attributes = child.get_attributes()
            except Exception:
                continue
            if attributes.map_state != X.IsViewable or attributes.override_redirect:
                continue
            if self.title(child):
                found.append(child)
                continue
            # A reparenting window manager without the list: the client inside the frame.
            for inner in child.query_tree().children:
                if self.prop(inner, "WM_STATE"):
                    found.append(inner)
                    break
        return found

    def active(self):
        """The window with the input focus: _NET_ACTIVE_WINDOW, else the focus's top."""
        value = self.prop(self.root, "_NET_ACTIVE_WINDOW", self.Xatom.WINDOW)
        if value and value[0]:
            return int(value[0])
        try:
            focus = self.display.get_input_focus().focus
            if isinstance(focus, int) or focus is None:
                return None
            return int(self.toplevel(focus).id)
        except Exception:
            return None

    def at(self, x, y):
        """The top-level window at root point (x, y), the topmost first; None over the
        root window."""
        X = self.X
        for child in reversed(self.root.query_tree().children):
            try:
                attributes = child.get_attributes()
                if attributes.map_state != X.IsViewable:
                    continue
                left, top, right, bottom = self.rect(child)
            except Exception:
                continue
            if left <= x < right and top <= y < bottom:
                return child
        return None

    def client_of(self, top):
        """The client window of a top-level window (itself, or the child with WM_STATE)."""
        if self.prop(top, "WM_STATE") or self.title(top):
            return top
        for inner in top.query_tree().children:
            if self.prop(inner, "WM_STATE"):
                return inner
        return top

    def picture(self, window):
        """A Pillow RGB image of `window` (its own picture under Composite), or None when
        it is not mapped."""
        from PIL import Image

        X = self.X
        if window.get_attributes().map_state != X.IsViewable:
            return None
        geometry = window.get_geometry()
        if geometry.width <= 0 or geometry.height <= 0:
            return None
        raw = window.get_image(0, 0, geometry.width, geometry.height, X.ZPixmap, 0xFFFFFFFF)
        return Image.frombytes("RGB", (geometry.width, geometry.height), raw.data, "raw", "BGRX")

    def screen_picture(self, left, top, width, height):
        from PIL import Image

        raw = self.root.get_image(int(left), int(top), int(width), int(height), self.X.ZPixmap, 0xFFFFFFFF)
        return Image.frombytes("RGB", (int(width), int(height)), raw.data, "raw", "BGRX")

    def idle_seconds(self) -> float | None:
        """Seconds since the last input of anyone (MIT-SCREEN-SAVER), else None."""
        if "MIT-SCREEN-SAVER" not in self.extensions:
            return None
        try:
            return float(self.root.screensaver_query_info().idle) / 1000.0
        except Exception:
            return None

    def pointer(self) -> tuple[int, int]:
        found = self.root.query_pointer()
        return int(found.root_x), int(found.root_y)


class LinuxBackend(Backend):
    system = "Linux"

    def __init__(self, directory=None, display: str | None = None, private: bool = False, env: dict | None = None,
                 accessibility_address: str | None = None):
        """`display`: the X display (default $DISPLAY); `private`: it is a display of
        the agent's own (a display workspace), where XTest is targeted input; `env`: what
        launched applications get besides (the display workspace's D-Bus session)."""
        self.directory = Path(directory) if directory else None
        self.x11 = X11(display)
        self.private = bool(private)
        self.env = {**(env or {}), "DISPLAY": self.x11.name}
        self._accessibility_address = accessibility_address or (env or {}).get("AT_SPI_BUS_ADDRESS")
        self._accessibility = None
        self._accessibility_error = None
        self._frameworks = {}
        self._launched = {}
        self._windows = {}
        self._xtest = None
        self._lock = threading.RLock()

    @property
    def display(self) -> str:
        return self.x11.name

    # -- windows ------------------------------------------------------------------------

    def windows(self) -> list[dict]:
        with self._lock, self.x11.lock:
            front = self.x11.active()
            monitors = self.x11.monitors()
            rows = []
            for client in self.x11.clients():
                row = self._row(client, front, monitors)
                if row is not None:
                    rows.append(row)
            return rows

    def window(self, handle) -> dict | None:
        with self._lock, self.x11.lock:
            try:
                client = self.x11.window(int(handle))
                client.get_attributes()
            except Exception:
                return None
            return self._row(client, self.x11.active(), self.x11.monitors(), listed=False)

    def _row(self, client, front, monitors, listed=True) -> dict | None:
        X11_ = self.x11
        try:
            attributes = client.get_attributes()
            title = X11_.title(client)
            types = X11_.prop(client, "_NET_WM_WINDOW_TYPE", X11_.Xatom.ATOM) or []
            if any(kind in (X11_.atom(name) for name in SHARED_TYPES) for kind in types):
                return None
            if not title or attributes.override_redirect:
                return None
            pid = X11_.pid(client)
            if pid == os.getpid():
                return None
            top = X11_.toplevel(client)
            top_attributes = top.get_attributes()
            rect = X11_.rect(top)
            state = X11_.prop(client, "WM_STATE", X11_.atom("WM_STATE"))
            net_state = X11_.prop(client, "_NET_WM_STATE", X11_.Xatom.ATOM) or []
            minimized = top_attributes.map_state != X11_.X.IsViewable or bool(state and state[0] == 3) or \
                X11_.atom("_NET_WM_STATE_HIDDEN") in net_state
            if not listed and top_attributes.map_state != X11_.X.IsViewable and not state:
                return None
            transient = X11_.prop(client, "WM_TRANSIENT_FOR", X11_.Xatom.WINDOW)
            klass = client.get_wm_class() or (None, None)
        except Exception:
            return None
        launched = pid in self._launched or client.id in self._windows
        dialog = bool(transient and transient[0]) or X11_.atom("_NET_WM_WINDOW_TYPE_DIALOG") in types
        framework = self._framework(pid, klass)
        if dialog and framework in ("chromium", "electron"):
            # Its own dialogs (the file chooser) are GTK windows: they drop events sent to them.
            framework = "gtk"
        return {"handle": int(client.id), "pid": pid, "app": _app(image_path(pid)) if pid else None, "title": title,
                "class": klass[1] or "", "framework": framework, "rect": rect,
                "minimized": bool(minimized), "foreground": front in (client.id, top.id),
                "offscreen": not any(_overlap(rect, area) for area in monitors),
                "owner": int(transient[0]) if transient and transient[0] else None,
                # DevTools reaches the browser's pages, never a dialog of its own (its file
                # chooser: transient for its window, a dialog by type).
                "cdp": not dialog and self._devtools_of(pid) is not None, "launched": bool(launched),
                "display": self.display}

    def _framework(self, pid, klass) -> str:
        launched = self._launched.get(pid) or {}
        if launched.get("framework"):
            return launched["framework"]
        name = str(klass[1] or "").lower()
        if name in CLASS_FRAMEWORKS:
            return CLASS_FRAMEWORKS[name]
        if pid is None:
            return "unknown"
        if pid not in self._frameworks:
            framework = "x11"
            try:
                maps = Path(f"/proc/{int(pid)}/maps").read_text(encoding="utf-8", errors="replace")
                framework = next((found for library, found in LIBRARY_FRAMEWORKS if library in maps), "x11")
            except OSError:
                pass
            self._frameworks[pid] = framework
        return self._frameworks[pid]

    # -- the accessibility tree ----------------------------------------------------------

    def _client(self):
        if self._accessibility is None:
            address = self._accessibility_address
            if address is None:
                with self.x11.lock:
                    address = accessibility.bus_address(self.x11.prop(self.x11.root, "AT_SPI_BUS"))
            if not address:
                raise RuntimeError("no accessibility bus on this display (AT-SPI: at-spi2-core is not running)")
            self._accessibility = accessibility.Client(address)
        return self._accessibility

    def tree(self, window: dict, limit: int = 600) -> list[dict]:
        client = self._client()
        if not window.get("pid"):
            return []
        try:
            top = client.frame(window["pid"], window.get("title"), window["rect"])
        except accessibility.Gone:
            return []
        if top is None:
            return []
        try:
            rows = client.tree(top, int(window["handle"]), limit)
        except accessibility.Gone:
            raise LookupError("the window's accessible is gone: read its elements again") from None
        devtools = self._page_devtools(window)
        if devtools is not None:
            # A Chromium's fields have no EditableText: their text is typed over DevTools (act).
            for row in rows:
                if row["role"] == "edit" and "readonly" not in row["states"] and "set_value" not in row["actions"]:
                    row["actions"].append("set_value")
            # Its file inputs (buttons named "<label>: <what they hold>", never a button of the
            # label alone, such as the page's own Attach) take a file the same way, and their
            # value is the files they hold.
            try:
                inputs = cdp.file_inputs(devtools, page_session(devtools, window.get("title")))
            except (OSError, RuntimeError, KeyError):
                inputs = []
            buttons = iter(row for row in rows if row["role"] == "button")
            for name, held in inputs:
                row = next((row for row in buttons if name and row["name"].startswith(name + ": ")), None)
                if row is None:
                    break
                row["actions"].append("set_value")
                row["value"] = held or None
        return rows

    def act(self, element: dict, action: str, value=None) -> Delivery:
        tried = ""
        if action in ("scroll_into_view", "set_value") and element.get("name"):
            # A Chromium launched here: over AT-SPI it answers ScrollTo for an element out of
            # sight and nothing moves, and it has no EditableText. DevTools does both.
            window = self.window(element["window"])
            devtools = self._page_devtools(window)
            if devtools is not None:
                try:
                    return self._devtools_act(devtools, window, element, action, value)
                except (OSError, RuntimeError, KeyError) as error:
                    tried = f"DevTools: {error}; "
        try:
            method = self._client().act(element, action, value)
        except accessibility.Gone:
            raise LookupError("the element is gone: read the window's elements again") from None
        except TimeoutError:
            raise RuntimeError(f"{tried}the application did not answer (AT-SPI timed out)") from None
        except RuntimeError as error:
            raise RuntimeError(f"{tried}{error}") from None
        return Delivery("semantic", "delivered", {"method": method})

    # -- capture -------------------------------------------------------------------------

    def capture(self, window: dict):
        with self._lock, self.x11.lock:
            try:
                client = self.x11.window(int(window["handle"]))
                top = self.x11.toplevel(client)
                if self.x11._composite:
                    image = self.x11.picture(top)
                    method = "XComposite"
                else:
                    if top.get_attributes().map_state != self.x11.X.IsViewable:
                        return None
                    left, top_, right, bottom = self.x11.rect(top)
                    width, height = self.x11.size()
                    left, top_, right, bottom = max(0, left), max(0, top_), min(width, right), min(height, bottom)
                    if right <= left or bottom <= top_:
                        return None
                    image = self.x11.screen_picture(left, top_, right - left, bottom - top_)
                    method = "XGetImage (the screen: no Composite, a covered part shows what covers it)"
            except Exception:
                return None
        if image is None:
            return None
        return {"image": image, "method": method}

    # -- input sent to a window ----------------------------------------------------------

    def input(self, window: dict, event: dict) -> Delivery:
        devtools = self._page_devtools(window)
        tried = []
        if devtools is not None:
            try:
                return self._devtools_input(devtools, window, event)
            except (OSError, RuntimeError, ConnectionError) as error:
                tried.append(f"DevTools: {error}")
        if event["type"] not in ("click", "drag", "scroll", "type", "key"):
            raise ValueError(f"an input event is one of click, drag, scroll, type, key, not {event['type']!r}")
        if window.get("minimized"):
            raise NeedsPhysical("the window is minimized: input sent to it lands nowhere", tried)
        if self.private:
            return self._xtest_input(window, event)
        return self._sent_input(window, event, tried)

    def _xtest_input(self, window, event) -> Delivery:
        """XTest on the agent's own display: the window raised and focused there first."""
        if self._xtest is None:
            self._xtest = XTest(self.x11)
        X = self.x11.X
        with self._lock, self.x11.lock:
            client = self.x11.window(int(window["handle"]))
            top = self.x11.toplevel(client)
            top.configure(stack_mode=X.Above)
            with contextlib.suppress(Exception):
                client.set_input_focus(X.RevertToParent, X.CurrentTime)
            self.x11.display.sync()
        kind, xtest = event["type"], self._xtest
        if kind == "click":
            xtest.click(event["x"], event["y"], event.get("button", "left"), int(event.get("count", 1)))
        elif kind == "drag":
            xtest.drag(event["x"], event["y"], event["to_x"], event["to_y"], int(event.get("duration_ms", 400)) / 1000)
        elif kind == "scroll":
            x, y = event.get("x"), event.get("y")
            if x is None:
                left, top_, right, bottom = window["rect"]
                x, y = (left + right) // 2, (top_ + bottom) // 2
            xtest.wheel(event["direction"], int(event.get("amount", 5)), x, y)
        elif kind == "type":
            xtest.type(event["text"])
        else:
            xtest.keys(event["keys"])
        return Delivery("targeted", "delivered", {"method": "XTest", "display": self.display})

    def _sent_input(self, window, event, tried) -> Delivery:
        """Events sent to the window (XSendEvent): the user's pointer, keyboard and focus
        stay as they are. A toolkit reads more than the button or the key: Tk acts on a
        button's release only when the pointer entered the button, and gives keys to its
        focus widget only while its window has the focus; Qt takes the real keyboard focus
        when a window it does not think focused is clicked. So the window gets the focus
        first and loses it again after (when it does not really have it), the pointer
        enters the window under the point and leaves it, and a press's motion and release
        go to the window pressed (as the server's implicit grab does)."""
        framework = window.get("framework") or "unknown"
        taken = SENT.get(str(window.get("class") or "").lower(), SENT.get(framework))
        if isinstance(taken, str):
            raise NeedsPhysical(f"{taken}; XTest would move the user's real pointer and keyboard: a click on an "
                                "element with an action, or set_value, works without either", tried)
        from Xlib import X, error
        from Xlib.protocol import event as xevent

        kind = event["type"]
        sent = []
        with self._lock, self.x11.lock:
            client = self.x11.window(int(window["handle"]))
            top = self.x11.toplevel(client)
            root = self.x11.root
            focused = self._focused(top)
            # Every key is looked up before anything is sent: none or all of them go.
            codes = []
            if kind == "type":
                for char in event["text"]:
                    name = {"\n": "enter", "\t": "tab"}.get(char)
                    codes.append(self._sent_code(_keysym(name or char), repr(char), tried))
            elif kind == "key":
                names = [name.lower() for name in event["keys"]]
                state = 0
                for name in names:
                    state |= MASKS.get(name, 0)
                for name in [name for name in names if name not in MASKS] or names[-1:]:
                    code, shift = self._sent_code(_keysym(name), repr(name), tried)
                    codes.append((code, state | shift))
            # A window the events close (a dialog's button) is gone for the rest of them.
            gone = error.CatchError(error.BadWindow)

            def send(cls, target, x, y, mask, **fields):
                try:
                    local = target.translate_coords(root, int(x), int(y))
                except error.BadWindow:
                    return
                target.send_event(cls(time=X.CurrentTime, root=root, window=target, child=X.NONE, root_x=int(x),
                                      root_y=int(y), event_x=local.x, event_y=local.y, **fields),
                                  event_mask=mask, propagate=True, onerror=gone)
                if cls.__name__ not in sent:
                    sent.append(cls.__name__)

            def crossing(cls, target, x, y):
                send(cls, target, x, y, X.EnterWindowMask if cls is xevent.EnterNotify else X.LeaveWindowMask,
                     state=0, mode=X.NotifyNormal, detail=X.NotifyAncestor, flags=2)  # flags: same screen

            def press(x, y, number, count=1, path=(), to=None):
                """The pointer entering the window under (x, y), `count` presses and releases
                of button `number` there (moving along `path` while held, released at `to`),
                and leaving it."""
                target = self._deepest(client, x, y)[0]
                held = {1: X.Button1Mask, 2: X.Button2Mask, 3: X.Button3Mask}.get(number, 0)
                buttons = X.ButtonPressMask | X.ButtonReleaseMask
                crossing(xevent.EnterNotify, target, x, y)
                send(xevent.MotionNotify, target, x, y, X.PointerMotionMask, same_screen=1, state=0, detail=0)
                end = to or (x, y)
                for _ in range(count):
                    send(xevent.ButtonPress, target, x, y, buttons, same_screen=1, state=0, detail=number)
                    for px, py in path:
                        send(xevent.MotionNotify, target, px, py,
                             X.PointerMotionMask | X.ButtonMotionMask | X.Button1MotionMask, same_screen=1,
                             state=held, detail=0)
                    send(xevent.ButtonRelease, target, *end, buttons, same_screen=1, state=held, detail=number)
                crossing(xevent.LeaveNotify, target, *end)
                # The real pointer over the window: the window under it is entered again.
                found = root.query_pointer()
                if getattr(found.child, "id", found.child) == top.id:
                    crossing(xevent.EnterNotify, self._deepest(client, found.root_x, found.root_y)[0],
                             found.root_x, found.root_y)

            def keys(codes):
                """Key presses and releases ((keycode, modifier state) each) to the window's
                focus."""
                target = self._focus_in(client)
                for code, state in codes:
                    for cls in (xevent.KeyPress, xevent.KeyRelease):
                        send(cls, target, 0, 0, X.KeyPressMask | X.KeyReleaseMask, same_screen=1, state=state,
                             detail=code)

            def focus(cls):
                if not focused:
                    client.send_event(cls(window=client, mode=X.NotifyNormal, detail=X.NotifyNonlinear),
                                      event_mask=X.FocusChangeMask, onerror=gone)
                    sent.append(cls.__name__)

            focus(xevent.FocusIn)
            if kind == "click":
                press(event["x"], event["y"], BUTTONS.get(event.get("button", "left"), 1), int(event.get("count", 1)))
            elif kind == "drag":
                path = [(event["x"] + (event["to_x"] - event["x"]) * step / 8,
                         event["y"] + (event["to_y"] - event["y"]) * step / 8) for step in range(1, 9)]
                press(event["x"], event["y"], 1, path=path, to=(event["to_x"], event["to_y"]))
            elif kind == "scroll":
                x, y = event.get("x"), event.get("y")
                if x is None:
                    left, top_, right, bottom = window["rect"]
                    x, y = (left + right) // 2, (top_ + bottom) // 2
                press(x, y, WHEEL[event["direction"]], int(event.get("amount", 5)))
            else:
                keys(codes)
            focus(xevent.FocusOut)
            self.x11.display.sync()
        detail = {"method": "XSendEvent", "events": sent}
        if taken is None:
            detail["note"] = f"{framework} windows were not measured: the application may ignore it"
        return Delivery("targeted", "unverified", detail)

    def _sent_code(self, keysym, label, tried) -> tuple[int, int]:
        """The keycode of `keysym` on the keyboard's map, and the shift it needs."""
        for code, index in self.x11.display.keysym_to_keycodes(keysym):
            if index in (0, 1):
                return code, index
        raise NeedsPhysical(f"{label} is not on this keyboard's map, and the user's map is left alone: set_value on "
                            "the field types it", tried)

    def _deepest(self, window, x, y):
        """The deepest mapped child of `window` at root point (x, y), and the point in it."""
        X = self.x11.X
        current = window
        origin = current.translate_coords(self.x11.root, 0, 0)
        local = (int(x) + origin.x, int(y) + origin.y)
        for _ in range(32):
            hit = None
            for child in reversed(current.query_tree().children):
                try:
                    if child.get_attributes().map_state != X.IsViewable:
                        continue
                    geometry = child.get_geometry()
                except Exception:
                    continue
                if geometry.x <= local[0] < geometry.x + geometry.width and \
                        geometry.y <= local[1] < geometry.y + geometry.height:
                    hit = (child, (local[0] - geometry.x, local[1] - geometry.y))
                    break
            if hit is None:
                break
            current, local = hit
        return current, int(local[0]), int(local[1])

    def _focus_in(self, client):
        """Where the window's keyboard focus is, when the X focus is inside it; else the
        window."""
        try:
            focus = self.x11.display.get_input_focus().focus
            if not isinstance(focus, int) and focus is not None and \
                    self.x11.toplevel(focus).id == self.x11.toplevel(client).id:
                return focus
        except Exception:
            pass
        return client

    def _focused(self, top) -> bool:
        """Whether the window really has the keyboard focus: the X focus is in it, or the
        focus follows the pointer (PointerRoot) and the pointer is over it."""
        try:
            focus = self.x11.display.get_input_focus().focus
            value = getattr(focus, "id", focus)
            if value == self.x11.X.PointerRoot:
                found = self.x11.root.query_pointer()
                return getattr(found.child, "id", found.child) == top.id
            return bool(value) and self.x11.toplevel(focus).id == top.id
        except Exception:
            return False

    # -- DevTools (Chromium and Electron apps launched here) ---------------------------

    def _page_devtools(self, window):
        """The DevTools connection that reaches `window`: one of the pages of a Chromium
        launched here (its row's `cdp`), else None."""
        return self._devtools_of(window.get("pid")) if window and window.get("cdp") else None

    def _devtools_of(self, pid):
        launched = self._launched.get(pid)
        if not launched:
            return None
        if launched.get("devtools") is None:
            url = devtools_url(launched)
            if url is None:
                return None
            try:
                launched["devtools"] = DevTools(url)
            except (OSError, ValueError, ConnectionError):
                return None
        return launched["devtools"]

    def _page(self, devtools, window):
        """The session on `window`'s page and how a screen point maps to its CSS pixels."""
        session = page_session(devtools, window.get("title"))
        left, top, right, bottom = window["rect"]
        sizes = devtools.call("Runtime.evaluate", {"expression": "[window.devicePixelRatio, window.outerWidth, "
                                                                 "window.innerWidth, window.innerHeight]",
                                                   "returnByValue": True}, session)["result"]["value"]
        ratio, outer_width, inner_width, inner_height = (float(value) for value in sizes)
        # The page sits at the bottom of the window, with equal borders at its sides.
        border = max(0.0, (outer_width - inner_width) * ratio / 2)
        origin = (left + border, bottom - border - inner_height * ratio)
        return session, lambda x, y: ((x - origin[0]) / ratio, (y - origin[1]) / ratio)

    def _devtools_input(self, devtools, window, event) -> Delivery:
        session, css = self._page(devtools, window)
        left, top, right, bottom = window["rect"]
        dispatch(devtools, session, event, css, ((left + right) // 2, (top + bottom) // 2))
        return Delivery("targeted", "delivered", {"method": "DevTools"})

    def _devtools_act(self, devtools, window, element, action, value) -> Delivery:
        """scroll_into_view or set_value on `element` of a page, over DevTools: the page's
        element of that name nearest to where the accessibility tree has it now."""
        session, css = self._page(devtools, window)
        left, top, right, bottom = element["rect"]
        ref = element.get("ref") or {}
        try:
            x, y, width, height = self._client().call(ref["bus"], ref["path"], "org.a11y.atspi.Component",
                                                      "GetExtents", "u", (0,))[0]
            left, top, right, bottom = x, y, x + width, y + height
        except (RuntimeError, LookupError, TimeoutError):
            pass
        node = cdp.node_of(devtools, session, element["name"], css((left + right) / 2, (top + bottom) / 2),
                           typed=action == "set_value")
        if action == "set_value":
            return Delivery("semantic", "delivered", {"method": cdp.set_value(devtools, session, node, value,
                                                                              home=_home(window.get("pid")))})
        cdp.scroll_into_view(devtools, session, node)
        return Delivery("semantic", "delivered", {"method": "DevTools DOM.scrollIntoViewIfNeeded"})

    # -- launching and placing windows -----------------------------------------------------

    def launch(self, app: str, args=(), directory=None, visible: bool = False, timeout: float = 30.0) -> dict:
        exe = _resolve(app)
        name = Path(exe).name.lower()
        argv = [exe]
        profile = None
        base = Path(directory) if directory else (self.directory or Path(os.environ.get("TMPDIR", "/tmp")))
        framework = None
        if name in CHROMIUMS or name.startswith("chrom"):
            profile = base / f"{name}-profile"
            profile.mkdir(parents=True, exist_ok=True)
            (profile / "DevToolsActivePort").unlink(missing_ok=True)
            argv += [*CHROMIUM_FLAGS, f"--user-data-dir={profile}", "--new-window", "--window-size=1280,860"]
            if self.private:
                argv.append("--window-position=0,0")
            if os.geteuid() == 0:
                argv.append("--no-sandbox")
            framework = "chromium"
        elif _electron(exe):
            argv += ELECTRON_FLAGS
            framework = "electron"
        argv += [str(arg) for arg in args]
        env = {**os.environ, **ACCESSIBILITY_ENV, **self.env}
        env.pop("WAYLAND_DISPLAY", None)
        if env.get("GTK_MODULES") and os.environ.get("GTK_MODULES"):
            env["GTK_MODULES"] = f"{os.environ['GTK_MODULES']}:{ACCESSIBILITY_ENV['GTK_MODULES']}"
        before = {row["handle"] for row in self.windows()}
        with self.x11.lock:
            front = self.x11.active()
        base.mkdir(parents=True, exist_ok=True)
        # It starts where a person's would, in the home folder (its file dialogs open there);
        # its own folder (`base`) only holds its state.
        process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE if framework == "electron" else subprocess.DEVNULL,
                                   cwd=str(Path.home()), start_new_session=True)
        launched = {"exe": exe, "process": process, "profile": str(profile) if profile else None, "devtools": None,
                    "framework": framework}
        self._launched[process.pid] = launched
        if framework == "electron":
            threading.Thread(target=_listen, args=(process, launched), daemon=True).start()
        deadline = time.monotonic() + float(timeout)
        found = None
        while found is None and time.monotonic() < deadline:
            fresh = [row for row in self.windows() if row["handle"] not in before]
            ours = [row for row in fresh if row["pid"] and _descends(row["pid"], process.pid)]
            if ours:
                found = ours[0]
            elif process.poll() is not None and len(fresh) == 1:
                # A launcher that started the app and left.
                found = fresh[0]
            else:
                time.sleep(0.1)
        if found is None:
            raise RuntimeError(f"{app} showed no window within {timeout:g} s")
        if found["pid"] and found["pid"] != process.pid:
            self._launched[found["pid"]] = {**launched, "process": None}
        handle = found["handle"]
        self._windows[handle] = {"pid": found["pid"], "hidden": False}
        given = False
        if not self.private:
            self._place(handle, visible)
            given = self._settle(handle, front, visible)
        row = self.window(handle) or found
        return {**row, **({"foreground": False, "foreground_given_back": True} if given else {})}

    def _settle(self, handle, front, visible, seconds=2.0) -> bool:
        """For a moment after its start an application may move its window back onto a
        screen or take the focus: place it again, give the focus back."""
        given = False
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with self._lock, self.x11.lock:
                now = self.x11.active()
            if front and now == handle:
                self._activate(front)
                given = True
            row = self.window(handle)
            if row is None:
                break
            if not visible and not row["offscreen"]:
                self._place(handle, False)
            time.sleep(0.1)
        return given

    def _activate(self, handle):
        with self._lock:
            bring_to_front(self.x11, handle, wait=0.0)

    def show(self, window: dict, visible: bool) -> dict:
        handle = int(window["handle"])
        if handle not in self._windows and window.get("pid") not in self._launched:
            raise PermissionError("only a window the agent launched is moved; the user's windows stay where they are")
        self._windows.setdefault(handle, {"pid": window.get("pid"), "hidden": False})
        if self.private:
            # The agent's own display: every window is on it; this one comes to the top.
            with self._lock, self.x11.lock:
                self.x11.toplevel(self.x11.window(handle)).configure(stack_mode=self.x11.X.Above)
                self.x11.display.sync()
        else:
            self._place(handle, visible)
        return self.window(handle)

    def _place(self, handle, visible):
        """Move the window onto the first monitor (visible) or off every monitor, without
        raising it."""
        with self._lock, self.x11.lock:
            client = self.x11.window(handle)
            top = self.x11.toplevel(client)
            left, top_, right, bottom = self.x11.rect(top)
            areas = self.x11.monitors()
            if visible:
                x, y = areas[0][0] + 60, areas[0][1] + 60
            else:
                x, y = min(area[0] for area in areas) - (right - left) - 400, min(area[1] for area in areas) + 40
            # The client asks (a window manager places its frame); without one it moves.
            client.configure(x=int(x), y=int(y))
            self.x11.display.sync()
        self._windows.setdefault(handle, {"pid": None})["hidden"] = not visible

    def close(self) -> None:
        if not self.private:
            for handle, about in list(self._windows.items()):
                if about.get("hidden"):
                    with contextlib.suppress(Exception):
                        self._place(handle, True)
        for launched in self._launched.values():
            if launched.get("devtools") is not None:
                launched["devtools"].close()
                launched["devtools"] = None
            # On the agent's own display its apps end with it; on the user's they stay.
            process = launched.get("process")
            if self.private and process is not None and process.poll() is None:
                with contextlib.suppress(OSError):
                    os.killpg(process.pid, 15)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(3)
        if self._accessibility is not None:
            self._accessibility.close()
            self._accessibility = None
        self.x11.close()


def _electron(exe) -> bool:
    resources = Path(exe).resolve().parent / "resources"
    return (resources / "app.asar").is_file() or (resources / "app").is_dir()


def _listen(process, launched):
    """An Electron app prints its DevTools endpoint to stderr; keep reading so it never
    blocks on a full pipe."""
    for raw in process.stderr:
        line = raw.decode("utf-8", "replace")
        found = re.search(r"DevTools listening on (ws://\S+)", line)
        if found and not launched.get("url"):
            launched["url"] = found.group(1)


def _resolve(app: str) -> str:
    """The executable of `app`: a path, a program on PATH (a Chromium also by the names
    its packages give it), or an application by the name its menu shows ("Google Chrome",
    "Text Editor": its .desktop entry, else the name as a program, google-chrome)."""
    path = Path(os.path.expandvars(os.path.expanduser(str(app))))
    if path.is_file():
        return str(path.resolve())
    found = shutil.which(str(app))
    if found:
        return found
    named = str(app).strip().lower()
    if named in ("chrome", "chromium", "google chrome"):
        for name in CHROMIUMS:
            found = shutil.which(name)
            if found:
                return found
    found = _desktop_entry(named) or shutil.which(named.replace(" ", "-"))
    if found:
        return found
    raise FileNotFoundError(f"no application {app!r} here: give its path, a program name on PATH or the name "
                            "its menu entry shows")


def _desktop_entry(name: str) -> str | None:
    """The program of the application whose menu entry (a .desktop file in the XDG data
    directories) is called `name` (lower case), or None."""
    homes = [os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
             *(os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(os.pathsep)]
    for home in homes:
        for entry in sorted(Path(home, "applications").glob("*.desktop")) if home else ():
            fields = {}
            try:
                for line in entry.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("[") and fields:
                        break  # only the [Desktop Entry] group
                    key, _, value = line.partition("=")
                    fields.setdefault(key.strip(), value.strip())
            except OSError:
                continue
            if fields.get("Name", "").lower() != name or fields.get("Hidden") == "true":
                continue
            words = [word for word in fields.get("Exec", "").split() if not word.startswith("%")]
            program = words and (shutil.which(words[0]) or (words[0] if Path(words[0]).is_file() else None))
            if program:
                return program
    return None


def bring_to_front(x11: X11, handle, wait: float = 1.0) -> bool:
    """Ask the window manager to give the focus to window `handle` (as a pager would), and
    wait up to `wait` seconds for it; whether it has it."""
    from Xlib import X
    from Xlib.protocol import event as xevent

    with x11.lock:
        message = xevent.ClientMessage(window=x11.window(handle), client_type=x11.atom("_NET_ACTIVE_WINDOW"),
                                       data=(32, [2, X.CurrentTime, 0, 0, 0]))
        x11.root.send_event(message, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        x11.display.sync()
    deadline = time.monotonic() + wait
    while True:
        with x11.lock:
            if x11.active() == int(handle):
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


# X11 helpers the worker uses on the user's display (benches/computer/runtime.py Screen):
# one connection per display, opened when first asked.
_SHARED = {}


def shared(display: str | None = None) -> X11:
    name = display or os.environ.get("DISPLAY")
    if name not in _SHARED:
        _SHARED[name] = X11(name)
    return _SHARED[name]


def window_at(x=None, y=None, display: str | None = None) -> dict | None:
    """The window at root point (x, y), or the one with the focus: {handle (the client
    window, as LinuxBackend's rows), app, title, pid, shared, owner (the window it is
    transient for: a dialog's, a popup's)}."""
    x11 = shared(display)
    with x11.lock:
        if x is None:
            handle = x11.active()
            if not handle:
                return None
            top = x11.toplevel(x11.window(handle))
        else:
            top = x11.at(int(x), int(y))
            if top is None:
                return {"handle": int(x11.root.id), "app": None, "title": "", "pid": None, "shared": True}
        client = x11.client_of(top)
        pid = x11.pid(client)
        types = x11.prop(client, "_NET_WM_WINDOW_TYPE", x11.Xatom.ATOM) or []
        shared_ = any(kind in (x11.atom(name) for name in SHARED_TYPES) for kind in types)
        transient = x11.prop(client, "WM_TRANSIENT_FOR", x11.Xatom.WINDOW)
        return {"handle": int(client.id), "app": _app(image_path(pid)) if pid else None, "title": x11.title(client),
                "pid": pid, "shared": shared_, "owner": int(transient[0]) if transient and transient[0] else None}


def _home(pid) -> str | None:
    """The home folder of process `pid` (its HOME), or None."""
    try:
        environ = Path(f"/proc/{int(pid)}/environ").read_bytes().split(b"\0")
    except (OSError, TypeError, ValueError):
        return None
    return next((item[5:].decode(errors="replace") for item in environ if item.startswith(b"HOME=")), None)
