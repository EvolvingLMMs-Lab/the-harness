"""The macOS backend (harness_computer.desktop.Backend), on the system's own interfaces:

- windows: the window server's list (CGWindowListCopyWindowInfo), front to back, with
  each window's app, its title (the Accessibility API's when the list gives none, as it
  does without Screen Recording), whether it is minimized, and its UI framework (from the
  app's bundle).
- tree: the Accessibility API (AXUIElement): the window's elements with their roles,
  values, frames and AX actions.
- capture: ScreenCaptureKit (SCScreenshotManager, one window, also while it is covered
  or off the screens); CGWindowListCreateImage when that gives nothing (before macOS 14,
  or a blank picture). A minimized window shows nothing.
- act: AX actions and attributes: AXPress (invoke; toggle a checkbox; select a radio
  button or tab), AXPick and AXConfirm (invoke where there is no AXPress), AXShowMenu
  (expand a pop-up, menu button or combo box), AXValue (set_value), AXIncrement /
  AXDecrement (a number whose value cannot be set), AXSelected, AXExpanded and AXDisclosing
  (expand, collapse), AXScrollToVisible. A foreground the app takes anyway is given back.
- input: for a Chromium or Electron app the agent launched, the DevTools protocol;
  otherwise events posted to the window's process (CGEventPostToPid), mouse events
  addressed to the window: the pointer does not move. Unlike posted messages on Windows,
  these events carry their own modifier flags, so key combinations are sent too.
- launch: NSWorkspace opens the app without activating it (a new instance), and its
  window is moved past the right edge of the screens through the Accessibility API (by
  default): never in the user's way, never taking their focus. A Chromium gets its own
  profile, a DevTools port and its accessibility tree; an Electron app a DevTools port.

Points are global display coordinates in points, with (0, 0) at the main screen's
top-left corner: what the pointer and the screen's picture use on macOS. A window's
picture is in pixels (twice its points on a Retina screen); the worker scales it.

Two permissions belong to the process that runs the worker (or the terminal or app that
started it): Accessibility (the tree, the actions, posted input, placing windows) and
Screen Recording (pictures, and other apps' window titles). Without one, the calls that
need it raise PermissionError naming the System Settings pane; permissions() checks both
with the standard library.

What the probe on a Mac measures (scripts/probe_macos_desktop.py) decides which UI
frameworks take posted events (POSTED: until then every one is sent and reported
unverified), whether a window moved past the screens stays there, and whether an AX
action takes the foreground.

Standard library at import; pyobjc (AppKit, ApplicationServices, Quartz, ScreenCaptureKit)
is imported when the backend is made (the computer environment installs it on macOS).
MacSystem holds every call into the system, so the backend's logic runs on any system
with a fake one (tests).
"""

import contextlib
import ctypes
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

from . import ACTIONS, Backend, Delivery, NeedsPhysical
from .cdp import DevTools, devtools_url, dispatch, page_session
from harness.sdk import free_port

# Windows of the system every agent shares, by owner (the menu bar, the Dock, ...).
SHARED_OWNERS = {"Window Server", "Dock", "SystemUIServer", "Control Center", "Notification Center", "Spotlight",
                 "WindowManager", "Wallpaper", "loginwindow", "TextInputMenuAgent", "Screenshot"}
# Smaller windows are a process's helpers, not windows a person works in.
MIN_SIZE = (40, 20)
# Which UI frameworks take events posted to their process: not measured on a Mac yet (the
# probe decides). Unlisted ones are sent, and the delivery says unverified.
POSTED = {}
# AX roles (and subroles) as desktop.ROLES names them.
AX_ROLES = {"AXButton": "button", "AXMenuButton": "button", "AXDisclosureTriangle": "button", "AXColorWell": "button",
            "AXCheckBox": "checkbox", "AXRadioButton": "radio", "AXTextField": "edit", "AXTextArea": "edit",
            "AXSearchField": "edit", "AXDateField": "edit", "AXComboBox": "combobox", "AXPopUpButton": "combobox",
            "AXLink": "link", "AXImage": "image", "AXStaticText": "text", "AXHeading": "text", "AXList": "list",
            "AXTable": "table", "AXOutline": "tree", "AXBrowser": "tree", "AXGrid": "datagrid", "AXRow": "dataitem",
            "AXCell": "dataitem", "AXColumn": "header", "AXMenuBar": "menubar", "AXMenu": "menu",
            "AXMenuItem": "menuitem", "AXMenuBarItem": "menuitem", "AXTabGroup": "tab", "AXSlider": "slider",
            "AXIncrementor": "spinner", "AXStepper": "spinner", "AXProgressIndicator": "progressbar",
            "AXBusyIndicator": "progressbar", "AXLevelIndicator": "progressbar", "AXScrollBar": "scrollbar",
            "AXScrollArea": "pane", "AXSplitGroup": "pane", "AXLayoutArea": "pane", "AXMatte": "pane",
            "AXDrawer": "pane", "AXGroup": "group", "AXRadioGroup": "group", "AXToolbar": "toolbar",
            "AXWindow": "window", "AXSheet": "window", "AXDialog": "window", "AXWebArea": "document",
            "AXValueIndicator": "thumb", "AXSplitter": "separator", "AXHelpTag": "tooltip",
            "AXApplication": "window", "AXCalendar": "calendar"}
AX_SUBROLES = {"AXTabButton": "tabitem", "AXSwitch": "checkbox", "AXToggle": "checkbox", "AXOutlineRow": "treeitem",
               "AXTableRow": "dataitem", "AXSecureTextField": "edit", "AXSearchField": "edit",
               "AXContentList": "list", "AXDefinitionList": "list", "AXSortButton": "headeritem"}
# The attributes read for each element (one request per element).
ATTRIBUTES = ("AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXValue", "AXPlaceholderValue", "AXPosition",
              "AXSize", "AXEnabled", "AXFocused", "AXSelected", "AXExpanded", "AXDisclosing", "AXIdentifier",
              "AXChildren")
NUMERIC_ROLES = {"slider", "spinner", "progressbar", "scrollbar"}
# AX errors (AXError.h).
AX_INVALID_ELEMENT, AX_CANNOT_COMPLETE, AX_API_DISABLED, AX_NOT_IMPLEMENTED = -25202, -25204, -25211, -25208
AX_ERRORS = {-25200: "failure", -25201: "illegal argument", -25202: "invalid element", -25203: "invalid observer",
             -25204: "cannot complete (the app did not answer)", -25205: "attribute unsupported",
             -25206: "action unsupported", -25207: "notification unsupported", -25208: "not implemented",
             -25209: "notification already registered", -25210: "notification not registered",
             -25211: "the Accessibility API is disabled for this process", -25212: "no value",
             -25213: "parameterized attribute unsupported", -25214: "not enough precision"}
# Seconds an app has to answer one AX request before it is given up.
AX_TIMEOUT = 1.0
# The most AXIncrement / AXDecrement steps one set_value takes.
MAX_STEPS = 200
# Virtual key codes (Carbon's kVK_ANSI_* and kVK_*) of key names (runtime/safety/shield.py
# KEY_NAMES), and the flags of the modifier keys.
KEY_CODES = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
             "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
             "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34,
             "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
             ".": 47, "`": 50, " ": 49, "enter": 36, "return": 36, "\n": 36, "\r": 36, "tab": 48, "\t": 48,
             "space": 49, "backspace": 51, "delete": 117, "del": 117, "esc": 53, "escape": 53, "left": 123,
             "right": 124, "down": 125, "up": 126, "home": 115, "end": 119, "pageup": 116, "pgup": 116,
             "pagedown": 121, "pgdn": 121, "insert": 114, "help": 114, "f1": 122, "f2": 120, "f3": 99, "f4": 118,
             "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111, "f13": 105,
             "f14": 107, "f15": 113, "f16": 106, "f17": 64, "f18": 79, "f19": 80, "f20": 90}
MODIFIER_KEYS = {"command": (55, 0x100000), "win": (55, 0x100000), "winleft": (55, 0x100000),
                 "winright": (54, 0x100000), "shift": (56, 0x20000), "shiftleft": (56, 0x20000),
                 "shiftright": (60, 0x20000), "alt": (58, 0x80000), "altleft": (58, 0x80000),
                 "altright": (61, 0x80000), "option": (58, 0x80000), "optionleft": (58, 0x80000),
                 "optionright": (61, 0x80000), "ctrl": (59, 0x40000), "ctrlleft": (59, 0x40000),
                 "ctrlright": (62, 0x40000), "fn": (63, 0x800000)}
# Text goes in pieces of at most this many UTF-16 units per key event.
TEXT_PIECE = 20
# Chromium browsers by the names an agent gives them: the app's name.
CHROMIUMS = {"chrome": "Google Chrome", "google chrome": "Google Chrome", "chromium": "Chromium",
             "msedge": "Microsoft Edge", "edge": "Microsoft Edge", "microsoft edge": "Microsoft Edge",
             "brave": "Brave Browser", "brave browser": "Brave Browser"}
CHROMIUM_FLAGS = ["--no-first-run", "--no-default-browser-check", "--disable-backgrounding-occluded-windows",
                  "--force-renderer-accessibility", "--remote-debugging-port=0"]
APP_DIRECTORIES = ("/Applications", "/Applications/Utilities", "/System/Applications",
                   "/System/Applications/Utilities", "~/Applications")
# Where the user allows the two permissions.
SETTINGS = {"accessibility": ("Accessibility", "System Settings > Privacy & Security > Accessibility",
                              "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
            "screen_recording": ("Screen Recording", "System Settings > Privacy & Security > Screen & System Audio "
                                 "Recording (Screen Recording before macOS 15)",
                                 "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")}
# Terminal apps by TERM_PROGRAM: the app macOS asks the user to allow for a process it started.
TERMINALS = {"Apple_Terminal": "Terminal", "iTerm.app": "iTerm", "vscode": "Visual Studio Code",
             "WezTerm": "WezTerm", "ghostty": "Ghostty", "WarpTerminal": "Warp", "Hyper": "Hyper"}


# -- permissions (standard library) --------------------------------------------------------


def _library(name):
    try:
        return ctypes.cdll.LoadLibrary(f"/System/Library/Frameworks/{name}.framework/{name}")
    except OSError:
        return None


def responsible() -> str:
    """What the user allows in System Settings for this process: the terminal app that
    started it, else this Python."""
    return TERMINALS.get(os.environ.get("TERM_PROGRAM", "")) or os.path.realpath(sys.executable)


def permissions() -> dict:
    """Whether this process may use the Accessibility API and record the screen (None where
    the system does not say, and off macOS), and who the user allows."""
    found = {"accessibility": None, "screen_recording": None, "process": responsible()}
    if sys.platform != "darwin":
        return found
    services, graphics = _library("ApplicationServices"), _library("CoreGraphics")
    with contextlib.suppress(AttributeError):
        services.AXIsProcessTrusted.restype = ctypes.c_bool
        found["accessibility"] = bool(services.AXIsProcessTrusted())
    with contextlib.suppress(AttributeError):
        graphics.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        found["screen_recording"] = bool(graphics.CGPreflightScreenCaptureAccess())
    return found


def refusal(missing, process=None) -> str:
    """What the user does to allow the `missing` permissions."""
    process = process or responsible()
    names = " and ".join(SETTINGS[need][0] for need in missing)
    places = "; ".join(f"{SETTINGS[need][0]}: {SETTINGS[need][1]}" for need in missing)
    restart = " (Screen Recording takes effect when it starts again)" if "screen_recording" in missing else ""
    return (f"macOS has not allowed {names} for {process}: allow it in System Settings ({places}), then try again"
            f"{restart}")


def idle_seconds():
    """Seconds since anyone's last key, click or pointer move (the HID system's), else None."""
    graphics = _library("CoreGraphics") if sys.platform == "darwin" else None
    if graphics is None:
        return None
    try:
        function = graphics.CGEventSourceSecondsSinceLastEventType
    except AttributeError:
        return None
    function.argtypes, function.restype = [ctypes.c_int32, ctypes.c_uint32], ctypes.c_double
    # kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType
    return float(function(0, 0xFFFFFFFF))


# -- the system's calls (pyobjc) -------------------------------------------------------------


class MacSystem:
    """Every call the backend makes into macOS, with Python values in and out: windows
    (dicts), screens, apps, AX elements (opaque), pictures (Pillow), events (dicts)."""

    def __init__(self):
        try:
            import AppKit
            import ApplicationServices
            import CoreFoundation
            import Quartz
        except ImportError as error:
            raise RuntimeError("the macOS desktop backend needs pyobjc (AppKit, ApplicationServices, Quartz): the "
                               "computer environment installs it") from error
        self.appkit, self.ax, self.cf, self.quartz = AppKit, ApplicationServices, CoreFoundation, Quartz
        self._shareable = (0.0, None)
        # _AXUIElementGetWindow: an AX window's window-server number (the system's own,
        # long stable; without it windows are matched by frame and title).
        self._window_of = None
        services = _library("ApplicationServices")
        with contextlib.suppress(AttributeError):
            function = services._AXUIElementGetWindow
            function.argtypes, function.restype = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_int32
            self._window_of = function

    # windows, screens, apps

    def window_list(self, on_screen=False) -> list[dict]:
        """The window server's windows, front to back: id, pid, owner, title, layer,
        onscreen, alpha, rect [left, top, right, bottom] in points."""
        q = self.quartz
        option = (q.kCGWindowListOptionOnScreenOnly if on_screen else q.kCGWindowListOptionAll) | \
            q.kCGWindowListExcludeDesktopElements
        rows = []
        for info in q.CGWindowListCopyWindowInfo(option, q.kCGNullWindowID) or ():
            bounds = info.get("kCGWindowBounds") or {}
            x, y = float(bounds.get("X", 0)), float(bounds.get("Y", 0))
            rows.append({"id": int(info["kCGWindowNumber"]), "pid": int(info.get("kCGWindowOwnerPID", 0)),
                         "owner": str(info.get("kCGWindowOwnerName") or ""),
                         "title": str(info.get("kCGWindowName") or ""), "layer": int(info.get("kCGWindowLayer", 0)),
                         "onscreen": bool(info.get("kCGWindowIsOnscreen", False)),
                         "alpha": float(info.get("kCGWindowAlpha", 1.0)),
                         "rect": [round(x), round(y), round(x + float(bounds.get("Width", 0))),
                                  round(y + float(bounds.get("Height", 0)))]})
        return rows

    def screens(self) -> list[dict]:
        """Each screen (the main one first): rect and visible (without the menu bar and
        the Dock) in global points with the top-left origin, and its scale."""
        screens = list(self.appkit.NSScreen.screens() or ())
        if not screens:
            return []
        height = screens[0].frame().size.height

        def box(frame):
            left, bottom = frame.origin.x, frame.origin.y
            return [round(left), round(height - bottom - frame.size.height), round(left + frame.size.width),
                    round(height - bottom)]

        return [{"rect": box(screen.frame()), "visible": box(screen.visibleFrame()),
                 "scale": float(screen.backingScaleFactor())} for screen in screens]

    def front_pid(self) -> int | None:
        app = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else None

    def app_info(self, pid) -> dict:
        """The app of process `pid`: name, bundle (its .app path), id (bundle id), exe."""
        app = self.appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        if app is None:
            return {}
        url, exe = app.bundleURL(), app.executableURL()
        return {"name": str(app.localizedName() or ""), "bundle": str(url.path()) if url is not None else None,
                "id": str(app.bundleIdentifier() or "") or None, "exe": str(exe.path()) if exe is not None else None}

    def activate(self, pid) -> bool:
        """Bring app `pid` to the front again (the user's app, after another took it)."""
        app = self.appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        return bool(app is not None and app.activateWithOptions_(0))

    def open_app(self, bundle, args, timeout=30.0) -> int:
        """Open the app at `bundle` as a new instance, without activating it: its pid."""
        appkit = self.appkit
        config = appkit.NSWorkspaceOpenConfiguration.configuration()
        config.setActivates_(False)
        config.setCreatesNewApplicationInstance_(True)
        config.setAddsToRecentItems_(False)
        config.setArguments_([str(arg) for arg in args])
        done, box = threading.Event(), {}

        def opened(app, error):
            box.update(app=app, error=error)
            done.set()

        appkit.NSWorkspace.sharedWorkspace().openApplicationAtURL_configuration_completionHandler_(
            appkit.NSURL.fileURLWithPath_(str(bundle)), config, opened)
        if not done.wait(timeout):
            raise RuntimeError(f"macOS did not open {bundle} within {timeout:g} s")
        if box.get("app") is None:
            error = box.get("error")
            raise RuntimeError(f"macOS could not open {bundle}: "
                               f"{error.localizedDescription() if error is not None else 'no reason given'}")
        return int(box["app"].processIdentifier())

    # the Accessibility API

    def trusted(self, prompt=False) -> bool:
        if prompt:
            return bool(self.ax.AXIsProcessTrustedWithOptions({self.ax.kAXTrustedCheckOptionPrompt: True}))
        return bool(self.ax.AXIsProcessTrusted())

    def ax_application(self, pid):
        element = self.ax.AXUIElementCreateApplication(int(pid))
        self.ax.AXUIElementSetMessagingTimeout(element, AX_TIMEOUT)
        return element

    def ax_get(self, element, attribute):
        error, value = self.ax.AXUIElementCopyAttributeValue(element, attribute, None)
        return self._native(value) if error == 0 else None

    def ax_values(self, element, attributes) -> dict:
        error, values = self.ax.AXUIElementCopyMultipleAttributeValues(element, list(attributes), 0, None)
        if error != 0 or values is None or len(values) != len(attributes):
            return {name: self.ax_get(element, name) for name in attributes}
        return {name: self._native(value) for name, value in zip(attributes, values)}

    def ax_actions(self, element) -> list[str]:
        error, names = self.ax.AXUIElementCopyActionNames(element, None)
        return [str(name) for name in names] if error == 0 and names else []

    def ax_settable(self, element, attribute) -> bool:
        error, settable = self.ax.AXUIElementIsAttributeSettable(element, attribute, None)
        return error == 0 and bool(settable)

    def ax_perform(self, element, action) -> int:
        return int(self.ax.AXUIElementPerformAction(element, action))

    def ax_set(self, element, attribute, value) -> int:
        if attribute == "AXPosition":
            value = self.ax.AXValueCreate(1, self.quartz.CGPoint(*value))  # kAXValueCGPointType
        elif attribute == "AXSize":
            value = self.ax.AXValueCreate(2, self.quartz.CGSize(*value))  # kAXValueCGSizeType
        return int(self.ax.AXUIElementSetAttributeValue(element, attribute, value))

    def ax_key(self, element):
        """What identifies an element across reads (its CFHash)."""
        return int(self.cf.CFHash(element))

    def ax_window_id(self, element) -> int | None:
        if self._window_of is None:
            return None
        import objc

        number = ctypes.c_uint32()
        if self._window_of(ctypes.c_void_p(objc.pyobjc_id(element)), ctypes.byref(number)) != 0:
            return None
        return int(number.value) or None

    def _native(self, value):
        """An AX value as Python: a point, size or rect as a tuple; an error value as None."""
        if value is None:
            return None
        try:
            if self.cf.CFGetTypeID(value) != self.ax.AXValueGetTypeID():
                return value
            kind = int(self.ax.AXValueGetType(value))
        except (TypeError, ValueError):
            return value
        if kind not in (1, 2, 3, 4):  # an AXError value: no such attribute here
            return None
        ok, data = self.ax.AXValueGetValue(value, kind, None)
        if not ok:
            return None
        if kind == 1:
            return float(data.x), float(data.y)
        if kind == 2:
            return float(data.width), float(data.height)
        if kind == 3:
            return float(data.origin.x), float(data.origin.y), float(data.size.width), float(data.size.height)
        return int(data.location), int(data.length)

    # pictures

    def screen_recording(self) -> bool:
        return bool(self.quartz.CGPreflightScreenCaptureAccess())

    def capture_sck(self, window_id, timeout=3.0):
        """Window `window_id`'s picture from ScreenCaptureKit (macOS 14 and later), or None."""
        try:
            import ScreenCaptureKit as sck
        except ImportError:
            return None
        if not hasattr(sck, "SCScreenshotManager"):
            return None
        content = self._content(sck, timeout)
        window = next((item for item in (content.windows() if content is not None else ())
                       if int(item.windowID()) == int(window_id)), None)
        if window is None:
            # A window that showed since the content was read.
            content = self._content(sck, timeout, fresh=True)
            window = next((item for item in (content.windows() if content is not None else ())
                           if int(item.windowID()) == int(window_id)), None)
        if window is None:
            return None
        chosen = sck.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)
        scale = float(chosen.pointPixelScale()) if hasattr(chosen, "pointPixelScale") else 2.0
        config = sck.SCStreamConfiguration.alloc().init()
        config.setWidth_(max(1, round(window.frame().size.width * scale)))
        config.setHeight_(max(1, round(window.frame().size.height * scale)))
        config.setShowsCursor_(False)
        if hasattr(config, "setIgnoreShadowsSingleWindow_"):
            config.setIgnoreShadowsSingleWindow_(True)
        done, box = threading.Event(), {}

        def captured(image, error):
            box.update(image=image, error=error)
            done.set()

        sck.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(chosen, config, captured)
        if not done.wait(timeout) or box.get("image") is None:
            return None
        return self._pil(box["image"])

    def _content(self, sck, timeout, fresh=False):
        """The shareable windows (every window, on the screens or not), read at most once
        a second."""
        when, content = self._shareable
        if content is not None and not fresh and time.monotonic() - when < 1.0:
            return content
        done, box = threading.Event(), {}

        def listed(found, error):
            box.update(content=found, error=error)
            done.set()

        sck.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            True, False, listed)
        if not done.wait(timeout):
            return None
        self._shareable = (time.monotonic(), box.get("content"))
        return box.get("content")

    def capture_cg(self, window_id):
        """Window `window_id`'s picture from CGWindowListCreateImage (obsolete from macOS 15),
        or None."""
        q = self.quartz
        try:
            image = q.CGWindowListCreateImage(q.CGRectNull, q.kCGWindowListOptionIncludingWindow, int(window_id),
                                              q.kCGWindowImageBoundsIgnoreFraming | q.kCGWindowImageBestResolution)
        except (AttributeError, TypeError, ValueError):
            return None
        return self._pil(image) if image is not None else None

    def _pil(self, image):
        from PIL import Image

        q = self.quartz
        width, height = int(q.CGImageGetWidth(image)), int(q.CGImageGetHeight(image))
        if width <= 0 or height <= 0:
            return None
        data = bytes(q.CGDataProviderCopyData(q.CGImageGetDataProvider(image)))
        return Image.frombuffer("RGBA", (width, height), data, "raw", "BGRA", int(q.CGImageGetBytesPerRow(image)),
                                1).convert("RGB")

    # events

    def post(self, pid, events) -> None:
        """Post `events` to process `pid` (CGEventPostToPid): {"type": "mouse", "phase":
        down | up | drag, "button", "x", "y", "clicks", "window"}, {"type": "scroll", "x",
        "y", "dx", "dy", "window"}, {"type": "key", "code", "down", "flags"}, {"type": "text",
        "text"} (one key press that types it)."""
        q = self.quartz
        mouse = {("down", "left"): q.kCGEventLeftMouseDown, ("up", "left"): q.kCGEventLeftMouseUp,
                 ("down", "right"): q.kCGEventRightMouseDown, ("up", "right"): q.kCGEventRightMouseUp,
                 ("drag", "left"): q.kCGEventLeftMouseDragged, ("move", "left"): q.kCGEventMouseMoved}
        for item in events:
            kind = item["type"]
            if kind == "mouse":
                button = item.get("button", "left")
                made = q.CGEventCreateMouseEvent(None, mouse[(item["phase"], button)], (item["x"], item["y"]),
                                                 q.kCGMouseButtonRight if button == "right" else q.kCGMouseButtonLeft)
                q.CGEventSetIntegerValueField(made, q.kCGMouseEventClickState, int(item.get("clicks", 1)))
                self._address(made, item)
                q.CGEventPostToPid(int(pid), made)
            elif kind == "scroll":
                try:
                    made = q.CGEventCreateScrollWheelEvent(None, q.kCGScrollEventUnitLine, 2, int(item["dy"]),
                                                           int(item["dx"]))
                except TypeError:
                    made = q.CGEventCreateScrollWheelEvent2(None, q.kCGScrollEventUnitLine, 2, int(item["dy"]),
                                                            int(item["dx"]), 0)
                q.CGEventSetLocation(made, (item["x"], item["y"]))
                self._address(made, item)
                q.CGEventPostToPid(int(pid), made)
            elif kind == "key":
                made = q.CGEventCreateKeyboardEvent(None, int(item["code"]), bool(item["down"]))
                q.CGEventSetFlags(made, int(item.get("flags", 0)))
                q.CGEventPostToPid(int(pid), made)
            elif kind == "text":
                text = item["text"]
                for down in (True, False):
                    made = q.CGEventCreateKeyboardEvent(None, 0, down)
                    q.CGEventKeyboardSetUnicodeString(made, len(text.encode("utf-16-le")) // 2, text)
                    q.CGEventPostToPid(int(pid), made)
            else:
                raise ValueError(f"no event {kind!r}")

    def _address(self, event, item):
        """Mouse events name the window they are for (under the pointer, and the one that
        handles them), so the app routes them there wherever the real pointer is."""
        if item.get("window"):
            self.quartz.CGEventSetIntegerValueField(event, 91, int(item["window"]))
            self.quartz.CGEventSetIntegerValueField(event, 92, int(item["window"]))

    def cursor(self) -> tuple:
        location = self.quartz.CGEventGetLocation(self.quartz.CGEventCreate(None))
        return float(location.x), float(location.y)


_SYSTEM = None
_SYSTEM_LOCK = threading.Lock()


def system() -> MacSystem:
    """The process's MacSystem (made once)."""
    global _SYSTEM
    with _SYSTEM_LOCK:
        if _SYSTEM is None:
            _SYSTEM = MacSystem()
        return _SYSTEM


def window_at(x=None, y=None, mac=None) -> dict | None:
    """The window at global point (x, y), the topmost there, or the front app's front
    window: {handle, app, title, pid, shared} (the computer worker's Screen.window_at on
    macOS; handles are the backend's)."""
    mac = mac or system()
    rows = [row for row in mac.window_list(on_screen=True) if row["alpha"] > 0]
    if x is None:
        front = mac.front_pid()
        hit = next((row for row in rows if row["pid"] == front and row["layer"] == 0), None)
    else:
        hit = next((row for row in rows if _inside(row["rect"], x, y)), None)
    if hit is None:
        return None
    return {"handle": hit["id"], "app": _app(hit["owner"]), "title": hit["title"] or None, "pid": hit["pid"],
            "shared": hit["layer"] != 0 or hit["owner"] in SHARED_OWNERS}


# -- the backend --------------------------------------------------------------------------------


class MacBackend(Backend):
    system = "macOS"

    def __init__(self, directory=None, mac=None):
        if mac is None and sys.platform != "darwin":
            raise RuntimeError("the macOS desktop backend runs on macOS")
        # The system's calls, made when first used (pyobjc is imported then).
        self._mac = mac
        self.directory = Path(directory) if directory else None
        self._frameworks = {}
        # Applications launched here: pid -> {"exe", "process", "profile", "port", "url",
        # "devtools"}; windows they showed: id -> {"pid", "hidden"}.
        self._launched = {}
        self._windows = {}
        # Permissions found granted (one not granted is asked again: the user may allow it).
        self._granted = set()

    @property
    def mac(self) -> MacSystem:
        if self._mac is None:
            self._mac = system()
        return self._mac

    # -- permissions -----------------------------------------------------------------------

    def permissions(self) -> dict:
        return {"accessibility": self._allowed("accessibility"), "screen_recording": self._allowed("screen_recording"),
                "process": responsible()}

    def require(self, *needs) -> None:
        """PermissionError, saying where to allow them, unless every one of `needs` is
        allowed for this process."""
        missing = [need for need in needs if not self._allowed(need)]
        if missing:
            raise PermissionError(refusal(missing))

    def _allowed(self, need) -> bool:
        if need not in self._granted:
            if (self.mac.trusted() if need == "accessibility" else self.mac.screen_recording()):
                self._granted.add(need)
        return need in self._granted

    # -- windows ---------------------------------------------------------------------------

    def windows(self) -> list[dict]:
        return self._rows()

    def window(self, handle) -> dict | None:
        rows = self._rows(only=int(handle))
        return rows[0] if rows else None

    def _rows(self, only=None) -> list[dict]:
        listed = self.mac.window_list()
        own = os.getpid()
        candidates = [item for item in listed if self._candidate(item, own) and (only is None or item["id"] == only)]
        if not candidates:
            return []
        ax = self._ax_windows({item["pid"] for item in candidates}, candidates)
        front = self.mac.front_pid()
        areas = [screen["rect"] for screen in self.mac.screens()]
        # The front app's frontmost window is the one in front (the list is front to back).
        in_front = next((item["id"] for item in listed if item["pid"] == front and item["layer"] == 0
                         and item["onscreen"]), None)
        rows = []
        for item in candidates:
            about = ax.get(item["id"], {})
            if not (item["onscreen"] or about or item["pid"] in self._launched or item["id"] in self._windows):
                continue
            info = self._app_info(item["pid"])
            rect = list(item["rect"])
            rows.append({"handle": item["id"], "pid": item["pid"], "app": _app(info.get("name") or item["owner"]),
                         "title": item["title"] or about.get("title") or "",
                         "framework": self._framework(item["pid"], info), "rect": rect,
                         "minimized": bool(about.get("minimized")), "foreground": item["id"] == in_front,
                         "offscreen": not any(_overlap(rect, area) for area in areas), "owner": None,
                         "cdp": _debuggable(self._launched.get(item["pid"])),
                         "launched": item["pid"] in self._launched or item["id"] in self._windows,
                         "layer": item["layer"]})
        return rows

    @staticmethod
    def _candidate(item, own) -> bool:
        left, top, right, bottom = item["rect"]
        return (item["layer"] == 0 and item["pid"] != own and item["owner"] not in SHARED_OWNERS
                and item["alpha"] > 0 and right - left >= MIN_SIZE[0] and bottom - top >= MIN_SIZE[1])

    def _ax_windows(self, pids, items) -> dict:
        """The AX windows of apps `pids` matched to the window server's `items`: {id:
        {"element", "title", "minimized"}} (empty without the Accessibility permission)."""
        if not self._allowed("accessibility"):
            return {}
        found = {}
        for pid in pids:
            mine = [item for item in items if item["pid"] == pid]
            try:
                elements = self.mac.ax_get(self.mac.ax_application(pid), "AXWindows") or ()
            except (OSError, RuntimeError, ValueError):
                continue
            for element in elements:
                values = self.mac.ax_values(element, ("AXTitle", "AXMinimized", "AXPosition", "AXSize"))
                number = self.mac.ax_window_id(element)
                if number is None:
                    number = _match(values, mine, found)
                if number is not None:
                    found[number] = {"element": element, "title": str(values.get("AXTitle") or ""),
                                     "minimized": bool(values.get("AXMinimized"))}
        return found

    def _ax_window(self, window):
        """The AX element of `window` (LookupError when it has none)."""
        self.require("accessibility")
        items = [item for item in self.mac.window_list() if item["id"] == int(window["handle"])]
        if not items:
            raise LookupError("the window is closed")
        about = self._ax_windows({items[0]["pid"]}, items).get(items[0]["id"])
        if about is None:
            raise LookupError("the app gives this window no accessibility element")
        return about["element"]

    def _app_info(self, pid) -> dict:
        try:
            return self.mac.app_info(pid) or {}
        except (OSError, RuntimeError, ValueError):
            return {}

    def _framework(self, pid, info) -> str:
        if pid not in self._frameworks:
            self._frameworks[pid] = framework_of(info.get("bundle"), info.get("exe"))
        return self._frameworks[pid]

    # -- the accessibility tree ------------------------------------------------------------

    def tree(self, window: dict, limit: int = 600) -> list[dict]:
        root = self._ax_window(window)
        elements = []
        frame = window["rect"]

        def walk(node, depth, parent):
            if len(elements) >= limit:
                return
            values = self.mac.ax_values(node, ATTRIBUTES)
            index = len(elements)
            elements.append(self._element(node, values, depth, parent, window, frame))
            for child in values.get("AXChildren") or ():
                walk(child, depth + 1, index)

        walk(root, 0, None)
        return elements

    def _element(self, node, values, depth, parent, window, frame) -> dict:
        ax_role, subrole = str(values.get("AXRole") or ""), str(values.get("AXSubrole") or "")
        role = AX_SUBROLES.get(subrole) or AX_ROLES.get(ax_role) or "custom"
        ax_actions = self.mac.ax_actions(node)
        actions, states = [], []
        name = str(values.get("AXTitle") or values.get("AXDescription") or "")
        value = values.get("AXValue")
        password = subrole == "AXSecureTextField"
        if role == "checkbox" or (ax_role == "AXDisclosureTriangle"):
            mark = _number(value)
            if ax_role == "AXDisclosureTriangle":
                actions.append("collapse" if mark else "expand")
                states.append("expanded" if mark else "collapsed")
            else:
                states.append({1: "checked", 2: "mixed"}.get(mark, "unchecked"))
                if "AXPress" in ax_actions:
                    actions.append("toggle")
            value = None
        elif role in ("radio", "tabitem"):
            if _number(value):
                states.append("selected")
            if "AXPress" in ax_actions:
                actions.append("select")
            value = None
        else:
            if role in ("combobox",) and ("AXShowMenu" in ax_actions or "AXPress" in ax_actions):
                actions.append("expand")
            elif "AXPress" in ax_actions and role != "edit":
                actions.append("invoke")
            elif role == "menuitem" and "AXPick" in ax_actions:
                actions.append("invoke")
            elif role not in ("edit", "text") and "AXConfirm" in ax_actions:
                actions.append("invoke")
            if role in ("dataitem", "treeitem", "listitem", "tabitem", "menuitem") and values.get("AXSelected") is not None \
                    and self.mac.ax_settable(node, "AXSelected"):
                actions.append("select")
            for attribute in ("AXDisclosing", "AXExpanded"):
                if values.get(attribute) is not None and self.mac.ax_settable(node, attribute):
                    actions.append("collapse" if values[attribute] else "expand")
                    states.append("expanded" if values[attribute] else "collapsed")
                    break
            if role in ("edit", "combobox") or role in NUMERIC_ROLES or value is not None:
                if role in ("edit", "combobox", "slider", "spinner") and self.mac.ax_settable(node, "AXValue"):
                    actions.append("set_value")
                elif "AXIncrement" in ax_actions and role in NUMERIC_ROLES:
                    actions.append("set_value")
                elif role in ("edit", "combobox"):
                    states.append("readonly")
            if role == "text" and not name and isinstance(value, str):
                name, value = value, None
        if values.get("AXSelected") and "selected" not in states:
            states.append("selected")
        if "AXScrollToVisible" in ax_actions:
            actions.append("scroll_into_view")
        if values.get("AXEnabled") is False:
            states.append("disabled")
        if values.get("AXFocused"):
            states.append("focused")
        position, size = values.get("AXPosition"), values.get("AXSize")
        rect = [round(position[0]), round(position[1]), round(position[0] + size[0]), round(position[1] + size[1])] \
            if position and size else [frame[0], frame[1], frame[0], frame[1]]
        if depth and (rect[2] <= rect[0] or rect[3] <= rect[1] or not _overlap(rect, frame)):
            states.append("offscreen")
        if password:
            states.append("password")
            value = None
        try:
            key = ("ax", int(window["pid"]), self.mac.ax_key(node))
        except (TypeError, ValueError, AttributeError):
            key = (int(window["handle"]), depth, parent, role, name)
        text = None if value is None or isinstance(value, (list, tuple)) else _text(value)
        return {"key": key, "ref": node, "window": int(window["handle"]), "pid": int(window["pid"]), "role": role,
                "name": name, "value": text if text != "" else None,
                "automation_id": str(values.get("AXIdentifier") or "") or None, "rect": rect,
                "actions": list(dict.fromkeys(actions)), "states": list(dict.fromkeys(states)), "depth": depth,
                "parent": parent, "ax_role": ax_role, "ax_actions": ax_actions}

    # -- semantic actions --------------------------------------------------------------

    def act(self, element: dict, action: str, value=None) -> Delivery:
        if action not in ACTIONS:
            raise ValueError(f"an element's action is one of {', '.join(ACTIONS)}, not {action!r}")
        self.require("accessibility")
        node = element["ref"]
        ax_actions = element.get("ax_actions") or self.mac.ax_actions(node)
        with self._quiet(element.get("pid")) as quiet:
            method = self._do(node, element, action, value, ax_actions)
        return Delivery("semantic", "delivered", {"method": method, **quiet})

    def _do(self, node, element, action, value, ax_actions) -> str:
        def first(*names):
            name = next((name for name in names if name in ax_actions), None)
            if name is None:
                raise RuntimeError(f"it has no {' or '.join(names)} action")
            self._check(self.mac.ax_perform(node, name), name)
            return f"ax {name}"

        def setting(attribute, setting_value):
            self._check(self.mac.ax_set(node, attribute, setting_value), attribute)
            return f"ax {attribute}"

        if action == "invoke":
            return first("AXPress", "AXPick", "AXConfirm")
        if action == "toggle":
            return first("AXPress")
        if action == "select":
            if self.mac.ax_settable(node, "AXSelected"):
                return setting("AXSelected", True)
            return first("AXPress", "AXPick")
        if action in ("expand", "collapse"):
            for attribute in ("AXDisclosing", "AXExpanded"):
                if self.mac.ax_settable(node, attribute):
                    return setting(attribute, action == "expand")
            if element.get("ax_role") == "AXDisclosureTriangle":
                return first("AXPress")
            return first("AXShowMenu", "AXPress") if action == "expand" else first("AXCancel")
        if action == "scroll_into_view":
            return first("AXScrollToVisible")
        # set_value
        numeric = element.get("role") in NUMERIC_ROLES
        if self.mac.ax_settable(node, "AXValue"):
            return setting("AXValue", float(value) if numeric else str(value))
        if numeric and "AXIncrement" in ax_actions:
            return self._step_to(node, float(value))
        raise RuntimeError("it takes no value")

    def _step_to(self, node, target) -> str:
        """A number that cannot be set: AXIncrement / AXDecrement until it reaches `target`."""
        for _ in range(MAX_STEPS):
            now = _number(self.mac.ax_get(node, "AXValue"), None)
            if now is None:
                raise RuntimeError("its value is not a number")
            if abs(now - target) < 1e-9:
                return "ax AXIncrement/AXDecrement"
            name = "AXIncrement" if now < target else "AXDecrement"
            self._check(self.mac.ax_perform(node, name), name)
            after = _number(self.mac.ax_get(node, "AXValue"), None)
            if after is None or after == now or (after - target) * (now - target) < 0:
                # No change, or past the target: the steps are coarser than the value asked.
                return "ax AXIncrement/AXDecrement (to the nearest step)"
        raise RuntimeError(f"it did not reach {target:g} in {MAX_STEPS} steps")

    @staticmethod
    def _check(error, what):
        if error == 0:
            return
        if error == AX_INVALID_ELEMENT:
            raise LookupError("the element is gone: read the window's elements again")
        if error == AX_API_DISABLED:
            raise PermissionError(refusal(["accessibility"]))
        raise RuntimeError(f"{what} failed: {AX_ERRORS.get(error, error)}")

    @contextlib.contextmanager
    def _quiet(self, pid):
        """Keep the front app in front while another app gets an action: a foreground the
        app takes anyway is given back. Yields what the delivery says of it."""
        detail = {}
        front = self.mac.front_pid()
        try:
            yield detail
        finally:
            if front and pid and pid != front:
                # An application may activate itself a moment after the call returns.
                time.sleep(0.15)
                now = self.mac.front_pid()
                if now and now != front:
                    detail["foreground"] = "given back" if self.mac.activate(front) else "taken"

    # -- capture -------------------------------------------------------------------------

    def capture(self, window: dict):
        if window.get("minimized"):
            return None
        self.require("screen_recording")
        image, method = self.mac.capture_sck(window["handle"]), "ScreenCaptureKit"
        if image is None or _blank(image):
            other = self.mac.capture_cg(window["handle"])
            if other is not None and (image is None or not _blank(other)):
                image, method = other, "CGWindowListCreateImage"
        if image is None:
            return None
        return {"image": image, "method": method}

    # -- input sent to a window ----------------------------------------------------------

    def input(self, window: dict, event: dict) -> Delivery:
        devtools = self._devtools_of(window["pid"])
        tried = []
        if devtools is not None:
            try:
                return self._devtools_input(devtools, window, event)
            except (OSError, RuntimeError, ConnectionError) as error:
                tried.append(f"DevTools: {error}")
        framework = window.get("framework") or "unknown"
        if POSTED.get(framework) is False:
            raise NeedsPhysical(f"{framework} apps ignore events posted to them; a click on an element with an "
                                "action, or set_value, works without them", tried)
        if window.get("minimized"):
            raise NeedsPhysical("the window is minimized: events posted to it land nowhere", tried)
        self.require("accessibility")
        events = self._events(window, event, tried)
        self.mac.post(window["pid"], events)
        detail = {"method": "CGEventPostToPid"}
        if POSTED.get(framework) is None:
            detail["note"] = f"{framework} apps were not measured: the app may ignore it"
        if event["type"] in ("type", "key") and not window.get("foreground"):
            detail["note"] = ("keys go to the app's key window; an app that is not in front may drop them: look "
                              "before depending on it")
        return Delivery("targeted", "unverified", detail)

    def _events(self, window, event, tried) -> list[dict]:
        kind, number = event["type"], int(window["handle"])
        if kind == "click":
            button = event.get("button", "left")
            events = []
            for count in range(1, int(event.get("count", 1)) + 1):
                for phase in ("down", "up"):
                    events.append({"type": "mouse", "phase": phase, "button": button, "x": event["x"],
                                   "y": event["y"], "clicks": count, "window": number})
            return events
        if kind == "drag":
            events = [{"type": "mouse", "phase": "down", "x": event["x"], "y": event["y"], "window": number}]
            for step in range(1, 9):
                events.append({"type": "mouse", "phase": "drag", "window": number,
                               "x": event["x"] + (event["to_x"] - event["x"]) * step / 8,
                               "y": event["y"] + (event["to_y"] - event["y"]) * step / 8})
            return events + [{"type": "mouse", "phase": "up", "x": event["to_x"], "y": event["to_y"],
                              "window": number}]
        if kind == "scroll":
            x, y = event.get("x"), event.get("y")
            if x is None:
                x, y = self._middle(window)
            amount = int(event.get("amount", 5))
            dx, dy = {"up": (0, amount), "down": (0, -amount), "left": (-amount, 0),
                      "right": (amount, 0)}[event["direction"]]
            return [{"type": "scroll", "x": x, "y": y, "dx": dx, "dy": dy, "window": number}]
        if kind == "type":
            events, piece = [], ""
            for char in event["text"] + "\0":
                if char in "\n\t\0" or len((piece + char).encode("utf-16-le")) // 2 > TEXT_PIECE:
                    if piece:
                        events.append({"type": "text", "text": piece})
                        piece = ""
                if char in "\n\t":
                    events += _press([], KEY_CODES[char])
                elif char != "\0":
                    piece += char
            return events
        if kind == "key":
            keys = [key.lower() for key in event["keys"]]
            modifiers = [key for key in keys if key in MODIFIER_KEYS]
            main = [key for key in keys if key not in MODIFIER_KEYS]
            if len(main) > 1:
                raise NeedsPhysical("one key at a time with its modifiers (" + "+".join(keys) + ")", tried)
            if main and main[0] not in KEY_CODES:
                raise NeedsPhysical(f"the key {main[0]!r} has no macOS key code here", tried)
            if not main:
                return _press(modifiers[:-1], MODIFIER_KEYS[modifiers[-1]][0])
            return _press(modifiers, KEY_CODES[main[0]])
        raise ValueError(f"an input event is one of click, drag, scroll, type, key, not {kind!r}")

    # -- DevTools (Chromium and Electron apps launched here) ---------------------------

    def _devtools_of(self, pid):
        launched = self._launched.get(pid)
        if not launched:
            return None
        if launched.get("devtools") is None:
            url = self._devtools_url(launched)
            if url is None:
                return None
            try:
                launched["devtools"] = DevTools(url)
            except (OSError, ValueError, ConnectionError):
                return None
        return launched["devtools"]

    @staticmethod
    def _devtools_url(launched) -> str | None:
        """A Chromium's endpoint from its profile (cdp.devtools_url); an Electron app's from
        the debugging port it was given (its /json/version: NSWorkspace keeps no output)."""
        if launched.get("port") and not launched.get("url") and not launched.get("profile"):
            try:
                with urlopen(f"http://127.0.0.1:{int(launched['port'])}/json/version", timeout=2.0) as answer:
                    launched["url"] = json.loads(answer.read().decode("utf-8"))["webSocketDebuggerUrl"]
            except (OSError, ValueError, KeyError):
                return None
        return devtools_url(launched)

    def _page(self, devtools, window):
        return page_session(devtools, window.get("title"))

    def _devtools_input(self, devtools, window, event) -> Delivery:
        session = self._page(devtools, window)
        dispatch(devtools, session, event, lambda x, y: self._css(devtools, session, window, x, y),
                 self._middle(window))
        return Delivery("targeted", "delivered", {"method": "DevTools"})

    def _css(self, devtools, session, window, x, y):
        """Screen point (x, y) in the page's CSS pixels: from the window's frame, past its
        title bar and toolbars, by the page's zoom (device pixels per CSS pixel over the
        screen's pixels per point)."""
        left, top, _, _ = window["rect"]
        sides, bars, ratio = devtools.call("Runtime.evaluate", {
            "expression": "[window.outerWidth - window.innerWidth, window.outerHeight - window.innerHeight, "
                          "window.devicePixelRatio]", "returnByValue": True}, session)["result"]["value"]
        zoom = float(ratio) / self._scale(window) or 1.0
        return (x - left) / zoom - float(sides) / 2, (y - top) / zoom - float(bars)

    def _middle(self, window):
        left, top, right, bottom = window["rect"]
        return (left + right) // 2, (top + bottom) // 2

    def _scale(self, window) -> float:
        """Pixels per point of the screen the window is on (the nearest one when it is off
        them)."""
        screens = self.mac.screens()
        if not screens:
            return 1.0
        x, y = self._middle(window)
        on = next((screen for screen in screens if _inside(screen["rect"], x, y)), None)
        if on is None:
            on = min(screens, key=lambda screen: _distance(screen["rect"], x, y))
        return float(on.get("scale") or 1.0)

    # -- launching and placing windows -----------------------------------------------------

    def launch(self, app: str, args=(), directory=None, visible: bool = False, timeout: float = 30.0) -> dict:
        self.require("accessibility")
        target = resolve(app)
        kind = framework_of(target.get("bundle"), target.get("exe"))
        base = Path(directory) if directory else (self.directory or Path(tempfile.gettempdir()))
        extra, profile, port = [], None, None
        if kind == "chromium":
            profile = base / f"{_slug(target['name'])}-profile"
            profile.mkdir(parents=True, exist_ok=True)
            (profile / "DevToolsActivePort").unlink(missing_ok=True)
            extra = [*CHROMIUM_FLAGS, f"--user-data-dir={profile}", "--new-window", "--window-size=1280,860"]
        elif kind == "electron":
            port = free_port()
            extra = ["--force-renderer-accessibility", f"--remote-debugging-port={port}"]
        argv = [*extra, *[str(arg) for arg in args]]
        before = {row["handle"] for row in self.windows()}
        front = self.mac.front_pid()
        process = None
        if target.get("bundle"):
            pid = self.mac.open_app(target["bundle"], argv, timeout)
        else:
            process = subprocess.Popen([target["exe"], *argv], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, cwd=str(Path(target["exe"]).parent))
            pid = process.pid
        launched = {"exe": target["exe"], "process": process, "profile": str(profile) if profile else None,
                    "port": port, "url": None, "devtools": None}
        self._launched[pid] = launched
        deadline = time.monotonic() + float(timeout)
        found = None
        while found is None and time.monotonic() < deadline:
            parents = _parents()
            fresh = [row for row in self.windows() if row["handle"] not in before]
            ours = [row for row in fresh if _descends(row["pid"], pid, parents)]
            if ours:
                found = ours[0]
            else:
                time.sleep(0.1)
        if found is None:
            raise RuntimeError(f"{app} showed no window within {timeout:g} s")
        if found["pid"] != pid:
            self._launched[found["pid"]] = {**launched, "process": None}
        self._windows[found["handle"]] = {"pid": found["pid"], "hidden": False}
        self._place(found, visible)
        given = self._settle(found, front, visible)
        row = self.window(found["handle"]) or found
        return {**row, **({"foreground": False, "foreground_given_back": True} if given else {})}

    def _settle(self, row, front, visible, seconds=2.0) -> bool:
        """For a moment after its start an app may activate itself or move its window back
        onto a screen: give the foreground back, place it again. Whether the foreground was
        given back."""
        given = False
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            now = self.mac.front_pid()
            if front and now == row["pid"] and now != front:
                given = self.mac.activate(front) or given
            current = self.window(row["handle"])
            if current is None:
                break
            if not visible and not current["offscreen"]:
                self._place(current, False)
            time.sleep(0.1)
        return given

    def show(self, window: dict, visible: bool) -> dict:
        handle = int(window["handle"])
        if handle not in self._windows and window.get("pid") not in self._launched:
            raise PermissionError("only a window the agent launched is moved; the user's windows stay where they are")
        self._windows.setdefault(handle, {"pid": window.get("pid"), "hidden": False})
        self._place(window, visible)
        return self.window(handle)

    def _place(self, window, visible):
        """Move the window (through the Accessibility API, which does not activate it) onto
        the main screen's visible area, or past the right edge of every screen."""
        element = self._ax_window(window)
        if self.mac.ax_get(element, "AXMinimized"):
            self.mac.ax_set(element, "AXMinimized", False)
        screens = self.mac.screens()
        if visible and screens:
            left, top, _, _ = screens[0]["visible"]
            x, y = left + 60, top + 40
        else:
            x = max((screen["rect"][2] for screen in screens), default=0) + 400
            y = screens[0]["visible"][1] + 40 if screens else 40
        self._check(self.mac.ax_set(element, "AXPosition", (x, y)), "AXPosition")
        self._windows.setdefault(int(window["handle"]), {"pid": window.get("pid")})["hidden"] = not visible

    def close(self) -> None:
        for handle, about in list(self._windows.items()):
            if about.get("hidden"):
                row = self.window(handle)
                if row is not None:
                    with contextlib.suppress(OSError, RuntimeError, LookupError):
                        self._place(row, True)
        for launched in self._launched.values():
            if launched.get("devtools") is not None:
                launched["devtools"].close()
                launched["devtools"] = None


# -- helpers ------------------------------------------------------------------------------------


def framework_of(bundle, exe) -> str:
    """An app's UI framework, from what its bundle holds: chromium, electron, qt, java,
    python (a Python process: Tk or PyObjC), else appkit."""
    if bundle:
        frameworks = Path(bundle) / "Contents" / "Frameworks"
        try:
            names = set(os.listdir(frameworks))
        except OSError:
            names = set()
        if "Electron Framework.framework" in names:
            return "electron"
        if any(name.endswith(" Framework.framework") and any(word in name for word in ("Chrom", "Edge", "Brave"))
               for name in names):
            return "chromium"
        if "QtCore.framework" in names:
            return "qt"
        if (Path(bundle) / "Contents" / "Java").is_dir() or any("jdk" in name or "jre" in name for name in names):
            return "java"
    name = Path(exe or bundle or "").name.lower()
    if name.startswith("python") or name == "wish":
        return "python"
    return "appkit"


def resolve(app: str) -> dict:
    """The app `app` names: {"name", "bundle" (an .app path, or None), "exe"}: an .app
    path, an executable's path, an app's name ("TextEdit", "Google Chrome", "chrome"), or a
    program on PATH."""
    text = os.path.expanduser(os.path.expandvars(str(app)))
    path = Path(text)
    if path.suffix == ".app" and path.is_dir():
        return _bundle(path)
    if path.is_file():
        return {"name": path.stem, "bundle": None, "exe": str(path.resolve())}
    wanted = CHROMIUMS.get(text.lower(), text).lower()
    for root in APP_DIRECTORIES:
        try:
            for candidate in Path(os.path.expanduser(root)).iterdir():
                if candidate.suffix == ".app" and candidate.stem.lower() == wanted:
                    return _bundle(candidate)
        except OSError:
            continue
    found = shutil.which(text)
    if found:
        return {"name": Path(found).name, "bundle": None, "exe": found}
    raise FileNotFoundError(f"no application {app!r} here: give its name (as in /Applications), its path or a "
                            "program on PATH")


def _bundle(path) -> dict:
    path = Path(path).resolve()
    try:
        with open(path / "Contents" / "Info.plist", "rb") as plist:
            info = plistlib.load(plist)
    except (OSError, plistlib.InvalidFileException):
        info = {}
    exe = path / "Contents" / "MacOS" / str(info.get("CFBundleExecutable") or path.stem)
    return {"name": path.stem, "bundle": str(path), "exe": str(exe), "id": info.get("CFBundleIdentifier")}


def _press(modifiers, code) -> list[dict]:
    """Key events for `code` held with `modifiers`: each modifier down, the key down and
    up with their flags, the modifiers up."""
    flags, events = 0, []
    for name in modifiers:
        modifier, mask = MODIFIER_KEYS[name]
        flags |= mask
        events.append({"type": "key", "code": modifier, "down": True, "flags": flags})
    events += [{"type": "key", "code": code, "down": True, "flags": flags},
               {"type": "key", "code": code, "down": False, "flags": flags}]
    for name in reversed(modifiers):
        modifier, mask = MODIFIER_KEYS[name]
        flags &= ~mask
        events.append({"type": "key", "code": modifier, "down": False, "flags": flags})
    return events


def _match(values, items, taken) -> int | None:
    """The window-server window an AX window is, by frame (and title), when the system does
    not say: one not matched yet."""
    position, size = values.get("AXPosition"), values.get("AXSize")
    if not position or not size:
        return None
    rect = [round(position[0]), round(position[1]), round(position[0] + size[0]), round(position[1] + size[1])]
    close = [item for item in items if item["id"] not in taken
             and all(abs(a - b) <= 2 for a, b in zip(item["rect"], rect))]
    titled = [item for item in close if item["title"] and item["title"] == values.get("AXTitle")]
    chosen = titled or close
    return chosen[0]["id"] if chosen else None


def _debuggable(launched) -> bool:
    """Whether an app launched here is driven over DevTools (its endpoint is found when
    first used)."""
    return bool(launched and (launched.get("profile") or launched.get("port") or launched.get("url")))


def _app(name):
    from harness_computer import physical

    return physical.app_name(name)


def _number(value, default=0):
    try:
        return float(value) if not isinstance(value, bool) else float(int(value))
    except (TypeError, ValueError):
        return default


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _blank(image) -> bool:
    """A picture of one colour (a window that drew nothing for the capture)."""
    return all(high - low < 6 for low, high in image.getextrema())


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _inside(rect, x, y) -> bool:
    return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


def _distance(rect, x, y) -> float:
    dx = max(rect[0] - x, 0, x - rect[2])
    dy = max(rect[1] - y, 0, y - rect[3])
    return (dx * dx + dy * dy) ** 0.5


def _slug(name) -> str:
    return "".join(char if char.isalnum() else "-" for char in str(name).lower()).strip("-") or "app"


def _parents() -> dict:
    """Each running process's parent: {pid: parent pid}."""
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, encoding="utf-8",
                                 timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    parents = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            parents[int(parts[0])] = int(parts[1])
    return parents


def _descends(pid, root, parents) -> bool:
    seen = set()
    while pid and pid not in seen:
        if pid == root:
            return True
        seen.add(pid)
        pid = parents.get(pid)
    return False
