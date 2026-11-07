"""The Windows backend (harness_computer.desktop.Backend), on the system's own interfaces:

- windows: the top-level windows (EnumWindows), with their process, frame (DWM's
  extended frame bounds), DPI and UI framework (the window class, else UI Automation's
  framework id).
- tree: UI Automation (comtypes), one cached subtree walk of the control view.
- capture: PrintWindow(PW_RENDERFULLCONTENT), which draws a covered or off-screen window
  as it is (a DPI-unaware window at its own scale, scaled to the screen's here), and
  Windows.Graphics.Capture (pywinrt) when that comes back blank. A minimized window shows
  nothing to either.
- act: UI Automation patterns (Invoke, Toggle, SelectionItem, ExpandCollapse, Value,
  RangeValue, ScrollItem; LegacyIAccessible's default action). UI Automation passes the
  caller's right to the foreground to the application, and Invoke nearly always took the
  foreground in the probe; a window that is not in front therefore gets
  WS_EX_NOACTIVATE for the call (it never did then), and a foreground taken anyway is
  given back.
- input: for a Chromium or Electron app the agent launched, the DevTools protocol;
  otherwise messages posted to the window (PostMessage: mouse, wheel, WM_CHAR, keys),
  which classic Win32, WinForms and Chromium windows take, and WPF, Tk and UWP windows
  ignore (NeedsPhysical). Posted keys carry no modifier state: a combination with ctrl,
  alt, shift or win needs DevTools or the real keyboard. A click on a text field
  activates its window, which would take the foreground where the system lets it: posted
  mouse input is sent under WS_EX_NOACTIVATE too, and the field still gets its thread's
  keyboard focus. Keys go to that focus; a window in the background has none until such a
  click, so keys before it are refused (they would land nowhere).
- launch: the application starts minimized without activation (STARTUPINFO), then is
  restored off the screens with WS_EX_NOACTIVATE (by default): never covered, never in
  the user's way, never taking their focus. A Chromium gets its own profile, a DevTools
  port and its accessibility tree; an Electron app a DevTools port.

The module's functions are what every package that works with this computer's windows
uses (the workers, the app): top_windows() (the one walk of the top-level windows, which
each caller filters), title(), rect() and frame(), processes() and image_path(), foreground() and
bring_to_front(), english_input() (a window's input method in English mode, so injected
keys are not composed), dpi_aware() (per-monitor v2, set once for the process), and
WGCSession (a Windows.Graphics.Capture session on one window, kept open: frames as the
window draws them).

The probe of 2026-11-01 (test windows of tkinter, WinForms, WPF and Chrome --app on a
150 % screen) set these choices; the PR that brought this backend has its table.

ctypes at import; comtypes and pywinrt are imported when first used (the computer
environment installs them on Windows).
"""

import contextlib
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

from . import ROLES, Backend, Delivery, NeedsPhysical
from .cdp import MODIFIERS, DevTools, devtools_url, dispatch, page_session

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    shcore = ctypes.WinDLL("shcore")
    imm32 = ctypes.WinDLL("imm32")
    HWND, LPARAM, WPARAM = wintypes.HWND, wintypes.LPARAM, wintypes.WPARAM
    for _name, _args, _result in (
            ("GetForegroundWindow", [], HWND), ("SetForegroundWindow", [HWND], wintypes.BOOL),
            ("IsWindow", [HWND], wintypes.BOOL), ("IsWindowVisible", [HWND], wintypes.BOOL),
            ("IsIconic", [HWND], wintypes.BOOL), ("GetWindow", [HWND, wintypes.UINT], HWND),
            ("GetAncestor", [HWND, wintypes.UINT], HWND),
            ("GetWindowTextW", [HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            ("GetWindowTextLengthW", [HWND], ctypes.c_int),
            ("GetClassNameW", [HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            ("GetWindowThreadProcessId", [HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            ("GetWindowRect", [HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            ("GetWindowLongPtrW", [HWND, ctypes.c_int], ctypes.c_ssize_t),
            ("SetWindowLongPtrW", [HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            ("ChildWindowFromPointEx", [HWND, wintypes.POINT, wintypes.UINT], HWND),
            ("WindowFromPoint", [wintypes.POINT], HWND),
            ("ScreenToClient", [HWND, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            ("PostMessageW", [HWND, wintypes.UINT, WPARAM, LPARAM], wintypes.BOOL),
            ("MapVirtualKeyW", [wintypes.UINT, wintypes.UINT], wintypes.UINT),
            ("PrintWindow", [HWND, wintypes.HDC, wintypes.UINT], wintypes.BOOL),
            ("GetDC", [HWND], wintypes.HDC), ("ReleaseDC", [HWND, wintypes.HDC], ctypes.c_int),
            ("GetDpiForWindow", [HWND], wintypes.UINT),
            ("MonitorFromWindow", [HWND, wintypes.DWORD], wintypes.HMONITOR),
            ("SetWindowPos", [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT],
             wintypes.BOOL),
            ("GetSystemMetrics", [ctypes.c_int], ctypes.c_int),
            ("SystemParametersInfoW", [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT], wintypes.BOOL),
            ("EnumChildWindows", [HWND, ctypes.c_void_p, LPARAM], wintypes.BOOL),
            ("IsChild", [HWND, HWND], wintypes.BOOL), ("ShowWindow", [HWND, ctypes.c_int], wintypes.BOOL),
            ("BringWindowToTop", [HWND], wintypes.BOOL),
            ("AttachThreadInput", [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
            ("keybd_event", [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t], None),
            ("SendMessageW", [HWND, wintypes.UINT, WPARAM, LPARAM], ctypes.c_ssize_t)):
        _function = getattr(user32, _name)
        _function.argtypes, _function.restype = _args, _result
    user32.GetWindowDpiAwarenessContext.argtypes = [HWND]
    user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                       wintypes.HANDLE, wintypes.DWORD]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes, gdi32.SelectObject.restype = [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    dwmapi.DwmGetWindowAttribute.argtypes = [HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    imm32.ImmGetDefaultIMEWnd.argtypes, imm32.ImmGetDefaultIMEWnd.restype = [HWND], HWND
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, LPARAM)

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x200, 0x201, 0x202, 0x203
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x204, 0x205, 0x20A, 0x20E
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x100, 0x101, 0x102
MK_LBUTTON, MK_RBUTTON, WHEEL_DELTA = 0x1, 0x2, 120
PW_RENDERFULLCONTENT = 0x2
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
SW_SHOWNOACTIVATE, SW_RESTORE = 4, 9
WM_IME_CONTROL, IMC_GETCONVERSIONMODE, IMC_SETCONVERSIONMODE, IMC_GETOPENSTATUS, IMC_SETOPENSTATUS = \
    0x283, 0x1, 0x2, 0x5, 0x6
IME_CMODE_NATIVE = 0x1
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
# Windows of the system every agent shares, never listed.
SHARED_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
SHELL_CLASSES = SHARED_CLASSES | {"Windows.UI.Core.CoreWindow"}
# UI frameworks by window class (prefix), then by UI Automation's framework id.
CLASS_FRAMEWORKS = (("HwndWrapper[", "wpf"), ("WindowsForms10.", "winforms"), ("Chrome_WidgetWin_", "chromium"),
                    ("TkTopLevel", "tk"), ("TkChild", "tk"), ("ApplicationFrameWindow", "uwp"),
                    ("#32770", "win32"), ("Qt", "qt"), ("SunAwt", "java"), ("GLFW", "glfw"), ("SDL_app", "sdl"))
UIA_FRAMEWORKS = {"Win32": "win32", "WinForm": "winforms", "WPF": "wpf", "XAML": "uwp", "Chrome": "chromium",
                  "DirectUI": "win32", "Qt": "qt"}
# Which frameworks take posted input (the probe): yes, no, or not measured (sent, unverified).
POSTED = {"win32": True, "winforms": True, "chromium": True, "wpf": False, "tk": False, "uwp": False}
# Chromium browsers and their install places.
CHROMIUMS = {"chrome": [r"Google\Chrome\Application\chrome.exe"],
             "msedge": [r"Microsoft\Edge\Application\msedge.exe"],
             "brave": [r"BraveSoftware\Brave-Browser\Application\brave.exe"]}
CHROMIUM_FLAGS = ["--no-first-run", "--no-default-browser-check", "--disable-backgrounding-occluded-windows",
                  "--force-renderer-accessibility", "--remote-debugging-port=0"]
ELECTRON_FLAGS = ["--force-renderer-accessibility", "--remote-debugging-port=0"]
# UI Automation: control types (50000 + index of desktop.ROLES), properties, patterns.
PROPERTIES = {"runtime_id": 30000, "rect": 30001, "control_type": 30003, "focused": 30008, "enabled": 30010,
              "automation_id": 30011, "class": 30012, "password": 30019, "offscreen": 30022, "framework": 30024,
              "name": 30005, "invoke": 30031, "range": 30033, "scroll": 30034, "select": 30036, "scroll_item": 30035,
              "expand": 30028, "toggle": 30041, "value": 30043, "value_text": 30045, "readonly": 30046,
              "range_readonly": 30048, "expand_state": 30070, "selected": 30079, "toggle_state": 30086,
              "legacy": 30090, "legacy_action": 30100}
PATTERNS = {"invoke": 10000, "value": 10002, "range": 10003, "expand": 10005, "select": 10010, "toggle": 10015,
            "scroll_item": 10017, "legacy": 10018}
UIA_E_ELEMENTNOTAVAILABLE = -2147220991
# Virtual keys of key names (runtime/safety/shield.py KEY_NAMES) that posted messages press.
VKEYS = {"enter": 0x0D, "return": 0x0D, "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "esc": 0x1B,
         "escape": 0x1B, "space": 0x20, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24,
         "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22, "insert": 0x2D}


def _text(function, hwnd, size=512) -> str:
    buffer = ctypes.create_unicode_buffer(size)
    function(hwnd, buffer, size)
    return buffer.value


def _rect(hwnd) -> tuple:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def frame(hwnd) -> tuple:
    """The visible frame (without the invisible resize borders), physical pixels: left, top,
    right, bottom."""
    rect = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
        return rect.left, rect.top, rect.right, rect.bottom
    return _rect(hwnd)


def rect(hwnd) -> tuple:
    """The window on the screen: x, y, width, height."""
    left, top, right, bottom = _rect(hwnd)
    return left, top, right - left, bottom - top


def title(hwnd) -> str:
    return _text(user32.GetWindowTextW, hwnd, user32.GetWindowTextLengthW(hwnd) + 1)


def top_windows(visible: bool = True) -> list[dict]:
    """The top-level windows, topmost first (with `visible`, the visible ones): {handle,
    title, class, pid, rect (x, y, width, height)}."""
    handles = []

    @WNDENUMPROC
    def each(hwnd, _):
        handles.append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    return [{"handle": int(hwnd), "title": title(hwnd), "class": _text(user32.GetClassNameW, hwnd, 256),
             "pid": _pid(hwnd), "rect": rect(hwnd)}
            for hwnd in handles if not visible or user32.IsWindowVisible(hwnd)]


def _cloaked(hwnd) -> bool:
    value = wintypes.DWORD()
    return dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)) == 0 and \
        bool(value.value)


def _pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def image_path(pid) -> str | None:
    """The executable of process `pid`, or None."""
    process = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return None
    try:
        path = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        return path.value if kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)) else None
    finally:
        kernel32.CloseHandle(process)


def _monitor_dpi(hwnd) -> int:
    monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    x, y = ctypes.c_uint(), ctypes.c_uint()
    if shcore.GetDpiForMonitor(ctypes.c_void_p(monitor), 0, ctypes.byref(x), ctypes.byref(y)) != 0:
        return 96
    return int(x.value) or 96


def processes() -> dict:
    """Every running process: {pid: (parent pid, exe name in lower case)}."""

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    found = {}
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return found
    try:
        entry = Entry(dwSize=ctypes.sizeof(Entry))
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            found[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile.lower())
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def window_at(x=None, y=None) -> dict | None:
    """The top-level window at screen point (x, y), else the one in front: {handle, app,
    title, pid, shared (the desktop or the taskbar, which every agent shares), owner (the
    window that owns it: a dialog's)}."""
    hwnd = user32.GetForegroundWindow() if x is None else user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    hwnd = user32.GetAncestor(hwnd, 2) if hwnd else None  # GA_ROOT
    if not hwnd:
        return None
    pid = _pid(hwnd)
    owner = user32.GetWindow(hwnd, 4)  # GW_OWNER
    return {"handle": int(hwnd), "app": _app(image_path(pid) or ""), "title": _text(user32.GetWindowTextW, hwnd),
            "pid": pid, "shared": _text(user32.GetClassNameW, hwnd, 256) in SHARED_CLASSES,
            "owner": int(owner) if owner else None}


def foreground() -> int | None:
    """The window in front (its handle), or None."""
    return int(user32.GetForegroundWindow() or 0) or None


def bring_to_front(hwnd, seconds: float = 1.0) -> bool:
    """Window `hwnd` in front, restored if minimized; whether it is. Windows lets a process
    set the foreground with its input attached to the thread that has it, else after an
    input of its own (an Alt tap)."""
    hwnd = int(hwnd)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    for attempt in range(2):
        holder = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        current = kernel32.GetCurrentThreadId()
        attached = holder != current and user32.AttachThreadInput(current, holder, True)
        try:
            if attempt:
                user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU
                user32.keybd_event(0x12, 0, 0x2, 0)  # KEYEVENTF_KEYUP
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(current, holder, False)
        deadline = time.monotonic() + seconds / 2
        while time.monotonic() < deadline:
            if foreground() == hwnd:
                return True
            time.sleep(0.05)
    return foreground() == hwnd


def english_input(hwnd) -> dict:
    """Window `hwnd`'s input method in English mode (closed, alphanumeric), so injected keys
    reach the window instead of an input method's composition (Microsoft Pinyin takes W,
    A, S, D); only this window's input context changes, never the user's settings.
    {"was_open", "open"}: whether it composed keys before and does now (open, or in native
    mode: Microsoft Pinyin reports itself closed while in Chinese mode)."""
    ime = imm32.ImmGetDefaultIMEWnd(int(hwnd))
    if not ime:
        return {"was_open": False, "open": False}

    def composing():
        return bool(user32.SendMessageW(ime, WM_IME_CONTROL, IMC_GETOPENSTATUS, 0)) or \
            bool(user32.SendMessageW(ime, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0) & IME_CMODE_NATIVE)

    was = composing()
    if was:
        user32.SendMessageW(ime, WM_IME_CONTROL, IMC_SETCONVERSIONMODE, 0)
        user32.SendMessageW(ime, WM_IME_CONTROL, IMC_SETOPENSTATUS, 0)
    return {"was_open": was, "open": composing()}


class WGCSession:
    """A Windows.Graphics.Capture session on window `hwnd`, kept open (pywinrt, imported
    when one is made): frame() is its latest picture, Pillow RGB. It sees what an OpenGL or
    DirectX window draws, which PrintWindow does not."""

    def __init__(self, hwnd, buffers: int = 2):
        from winrt.windows.graphics.capture import Direct3D11CaptureFramePool
        from winrt.windows.graphics.capture.interop import create_for_window
        from winrt.windows.graphics.directx import DirectXPixelFormat
        from winrt.windows.graphics.directx.direct3d11.interop import create_direct3d11_device

        self._format, self._buffers = DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED, int(buffers)
        self._device = create_direct3d11_device()
        self._item = create_for_window(int(hwnd))
        self._size = self._item.size
        self._pool = Direct3D11CaptureFramePool.create_free_threaded(self._device, self._format, self._buffers,
                                                                     self._size)
        self._session = self._pool.create_capture_session(self._item)
        self._session.is_cursor_capture_enabled = False
        with contextlib.suppress(OSError, AttributeError):
            self._session.is_border_required = False
        self._session.start_capture()
        self._seen = False
        self.lock = threading.Lock()

    def frame(self, frames: int = 2, fresh: float = 0.25, first: float = 5.0):
        """The newest frame after `frames` more were drawn since this call (waiting up to
        `fresh` seconds; up to `first` before the session's first frame), else the newest
        there is; None when the window drew none. The first frame after an input may still
        be the one being drawn when it came, so an observation waits for the second."""
        from PIL import Image
        from winrt.windows.graphics.imaging import SoftwareBitmap

        with self.lock:
            frame = None
            while (newer := self._pool.try_get_next_frame()) is not None:
                if frame is not None:
                    frame.close()
                frame = newer
            deadline = time.monotonic() + (fresh if frame is not None or self._seen else first)
            waited = 0
            while (waited < frames or frame is None) and time.monotonic() < deadline:
                newer = self._pool.try_get_next_frame()
                if newer is None:
                    time.sleep(0.003)
                    continue
                if frame is not None:
                    frame.close()
                frame, waited = newer, waited + 1
            if frame is None:
                return None
            try:
                size = frame.content_size
                if (size.width, size.height) != (self._size.width, self._size.height):
                    # The window changed size: the pool follows (the next frame has it).
                    self._size = size
                    self._pool.recreate(self._device, self._format, self._buffers, size)
                copying = SoftwareBitmap.create_copy_from_surface_async(frame.surface)
                while int(copying.status) == 0:
                    time.sleep(0.001)
                bitmap = copying.get_results()
                width, height = bitmap.pixel_width, bitmap.pixel_height
                data = bytearray(width * height * 4)
                bitmap.copy_to_buffer(data)
            finally:
                frame.close()
            self._seen = True
        return Image.frombuffer("RGBA", (width, height), bytes(data), "raw", "BGRA", 0, 1).convert("RGB")

    def close(self):
        with contextlib.suppress(Exception):
            self._session.close()
        with contextlib.suppress(Exception):
            self._pool.close()


def keyboard_ready(hwnd) -> dict | None:
    """None when injected keys reach window `hwnd` as keys, else the refusal's reason: its
    input method is put in English mode first (english_input), and one that stays open
    would compose them as text."""
    if english_input(hwnd)["open"]:
        return {"check": "input_method", "reason": "the window's input method stays open (it would take the keys "
                "as text to compose); nothing was done"}
    return None


_DPI_AWARE = []


def dpi_aware() -> bool:
    """This process per-monitor DPI aware (v2; physical pixels everywhere), set once and
    before anything makes it system aware (pyautogui, pywebview do); whether it is."""
    if not _DPI_AWARE:
        aware = False
        try:
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            aware = bool(user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))  # PER_MONITOR_AWARE_V2
        except (AttributeError, OSError):
            pass
        if not aware:
            try:
                aware = shcore.SetProcessDpiAwareness(2) == 0  # PROCESS_PER_MONITOR_DPI_AWARE
            except (AttributeError, OSError):
                aware = bool(user32.SetProcessDPIAware())
        _DPI_AWARE.append(aware)
    return _DPI_AWARE[0]


def _descends(pid, root, parents) -> bool:
    seen = set()
    while pid and pid not in seen:
        if pid == root:
            return True
        seen.add(pid)
        pid = parents.get(pid)
    return False


def _lparam(x, y) -> int:
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]


class WindowsBackend(Backend):
    system = "Windows"

    def __init__(self, directory=None):
        if sys.platform != "win32":
            raise RuntimeError("the Windows desktop backend runs on Windows")
        # Physical pixels everywhere (screen points, frames, pictures).
        dpi_aware()
        self.directory = Path(directory) if directory else None
        self._uia = None
        self._frameworks = {}
        # Applications launched here: pid -> {"exe", "devtools", "process", "profile"};
        # windows they showed: handle -> {"pid", "hidden"}.
        self._launched = {}
        self._windows = {}
        self._devtools = {}

    # -- windows ------------------------------------------------------------------------

    def windows(self) -> list[dict]:
        front = user32.GetForegroundWindow()
        rows = (self._row(window["handle"], front) for window in top_windows())
        return [row for row in rows if row is not None]

    def window(self, handle) -> dict | None:
        hwnd = int(handle)
        return self._row(hwnd, user32.GetForegroundWindow()) if user32.IsWindow(hwnd) else None

    def _row(self, hwnd, front) -> dict | None:
        if not user32.IsWindowVisible(hwnd) or _cloaked(hwnd):
            return None
        name = title(hwnd)
        kind = _text(user32.GetClassNameW, hwnd, 256)
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if kind in SHELL_CLASSES or not name or (style & WS_EX_TOOLWINDOW and not self._windows.get(hwnd)):
            return None
        pid = _pid(hwnd)
        if pid == os.getpid():
            return None
        bounds = frame(hwnd)
        owner = user32.GetWindow(hwnd, 4)  # GW_OWNER
        launched = pid in self._launched or hwnd in self._windows
        offscreen = not any(_overlap(bounds, area) for area in _monitors())
        return {"handle": int(hwnd), "pid": pid, "app": _app(image_path(pid)), "title": name, "class": kind,
                "framework": self._framework(hwnd, kind), "rect": list(bounds),
                "minimized": bool(user32.IsIconic(hwnd)), "foreground": hwnd == front, "offscreen": offscreen,
                # DevTools reaches the browser's pages, never a window it owns (its file dialog).
                "owner": int(owner) if owner else None, "cdp": not owner and self._devtools_of(pid) is not None,
                "launched": bool(launched), "dpi": int(user32.GetDpiForWindow(hwnd) or 96)}

    def _framework(self, hwnd, kind) -> str:
        known = self._frameworks.get(hwnd)
        if known:
            return known
        framework = next((name for prefix, name in CLASS_FRAMEWORKS if kind.startswith(prefix)), None)
        if framework is None:
            try:
                automation, _ = self._automation()
                framework = UIA_FRAMEWORKS.get(str(automation.ElementFromHandle(hwnd).CurrentFrameworkId), "unknown")
            except Exception:
                framework = "unknown"
        self._frameworks[hwnd] = framework
        return framework

    # -- the accessibility tree ----------------------------------------------------------

    def _automation(self):
        if self._uia is None:
            # The multithreaded apartment: no message loop is needed, and the capture's
            # asynchronous calls may wait in it.
            if "comtypes" not in sys.modules:
                sys.coinit_flags = 0
            try:
                import comtypes
                import comtypes.client
            except ImportError as error:
                raise RuntimeError("the Windows desktop backend needs comtypes (the computer environment "
                                   "installs it)") from error
            with contextlib.suppress(OSError):
                comtypes.CoInitializeEx(0)
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient

            automation = comtypes.client.CreateObject(UIAutomationClient.CUIAutomation8,
                                                      interface=UIAutomationClient.IUIAutomation)
            self._uia = (automation, UIAutomationClient)
        return self._uia

    def tree(self, window: dict, limit: int = 600) -> list[dict]:
        automation, uia = self._automation()
        request = automation.CreateCacheRequest()
        for prop in PROPERTIES.values():
            request.AddProperty(prop)
        request.TreeScope = 7  # the element and all its descendants
        request.TreeFilter = automation.ControlViewCondition
        root = automation.ElementFromHandle(int(window["handle"])).BuildUpdatedCache(request)
        elements = []

        def walk(element, depth, parent):
            if len(elements) >= limit:
                return
            index = len(elements)
            row = self._element(element, depth, parent, window)
            if not row["stable_identity"]:
                row["key"] = (int(window["handle"]), "unidentified", index)
            elements.append(row)
            children = element.GetCachedChildren()
            if not children:
                return
            for number in range(children.Length):
                walk(children.GetElement(number), depth + 1, index)

        walk(root, 0, None)
        return elements

    def _element(self, element, depth, parent, window) -> dict:
        def value(name):
            try:
                return element.GetCachedPropertyValue(PROPERTIES[name])
            except Exception:
                return None

        control = value("control_type") or 0
        role = ROLES[control - 50000] if 50000 <= control < 50000 + len(ROLES) else "element"
        rect = element.CachedBoundingRectangle
        actions, states = [], []
        if value("invoke") or (value("legacy") and value("legacy_action") and not value("toggle")):
            actions.append("invoke")
        if value("toggle"):
            actions.append("toggle")
            states.append({1: "checked", 2: "mixed"}.get(value("toggle_state"), "unchecked"))
        if value("select"):
            actions.append("select")
            if value("selected"):
                states.append("selected")
        if value("expand"):
            expand = value("expand_state")
            if expand in (0, 2):
                actions.append("expand")
            if expand in (1, 2):
                actions.append("collapse")
            states.append({0: "collapsed", 1: "expanded", 2: "expanded"}.get(expand, "leaf"))
        password = bool(value("password"))
        text = None
        if value("value"):
            text = None if password else value("value_text")
            if value("readonly"):
                states.append("readonly")
            else:
                actions.append("set_value")
        elif value("range") and not value("range_readonly"):
            actions.append("set_value")
        if value("scroll_item"):
            actions.append("scroll_into_view")
        if not value("enabled"):
            states.append("disabled")
        if value("focused"):
            states.append("focused")
        if value("offscreen"):
            states.append("offscreen")
        if password:
            states.append("password")
        key = value("runtime_id")
        return {"key": tuple(key) if key else None, "stable_identity": bool(key),
                "ref": element, "window": int(window["handle"]), "role": role, "name": value("name") or "",
                "value": text if text not in ("",) else None, "automation_id": value("automation_id") or None,
                "rect": [rect.left, rect.top, rect.right, rect.bottom], "actions": actions, "states": states,
                "depth": depth, "parent": parent}

    # -- semantic actions --------------------------------------------------------------

    def act(self, element: dict, action: str, value=None) -> Delivery:
        automation, uia = self._automation()
        live = element["ref"]
        patterns = {"invoke": ("invoke", "IUIAutomationInvokePattern", "Invoke"),
                    "toggle": ("toggle", "IUIAutomationTogglePattern", "Toggle"),
                    "select": ("select", "IUIAutomationSelectionItemPattern", "Select"),
                    "expand": ("expand", "IUIAutomationExpandCollapsePattern", "Expand"),
                    "collapse": ("expand", "IUIAutomationExpandCollapsePattern", "Collapse"),
                    "scroll_into_view": ("scroll_item", "IUIAutomationScrollItemPattern", "ScrollIntoView")}
        if action != "set_value" and action not in patterns:
            raise ValueError(f"an element's action is one of invoke, toggle, select, expand, collapse, set_value, "
                             f"scroll_into_view, not {action!r}")
        with self._quiet(element.get("window")) as quiet:
            try:
                if action == "set_value":
                    method = self._set_value(live, uia, value)
                elif action == "invoke" and not live.GetCurrentPattern(PATTERNS["invoke"]):
                    found = live.GetCurrentPattern(PATTERNS["legacy"])
                    if not found:
                        raise NeedsPhysical("it has no invoke or default action")
                    found.QueryInterface(uia.IUIAutomationLegacyIAccessiblePattern).DoDefaultAction()
                    method = "uia LegacyIAccessible.DoDefaultAction"
                else:
                    method = self._call(live, uia, *patterns[action])
            except NeedsPhysical:
                raise
            except Exception as error:
                if _hresult(error) == UIA_E_ELEMENTNOTAVAILABLE:
                    raise LookupError("the element is gone: read the window's elements again") from None
                raise RuntimeError(f"UI Automation could not {action} it: {_message(error)}") from None
        return Delivery("semantic", "delivered", {"method": method, **quiet})

    @staticmethod
    def _call(live, uia, pattern, interface, method) -> str:
        found = live.GetCurrentPattern(PATTERNS[pattern])
        if not found:
            raise RuntimeError(f"it has no {interface[len('IUIAutomation'):]}")
        getattr(found.QueryInterface(getattr(uia, interface)), method)()
        return f"uia {interface[len('IUIAutomation'):-len('Pattern')]}.{method}"

    @staticmethod
    def _set_value(live, uia, value) -> str:
        found = live.GetCurrentPattern(PATTERNS["value"])
        if found:
            found.QueryInterface(uia.IUIAutomationValuePattern).SetValue(str(value))
            return "uia Value.SetValue"
        found = live.GetCurrentPattern(PATTERNS["range"])
        if found:
            found.QueryInterface(uia.IUIAutomationRangeValuePattern).SetValue(float(value))
            return "uia RangeValue.SetValue"
        raise RuntimeError("it takes no value")

    @contextlib.contextmanager
    def _quiet(self, handle):
        """Keep the foreground where it is while a window gets a semantic action or posted
        mouse input: the window is WS_EX_NOACTIVATE meanwhile (a window in front needs nothing), and a
        foreground taken anyway is given back. Yields what the delivery says of it."""
        detail = {}
        front = user32.GetForegroundWindow()
        top = user32.GetAncestor(int(handle), 2) if handle else None  # GA_ROOT
        changed = None
        if top and top != front:
            style = user32.GetWindowLongPtrW(top, GWL_EXSTYLE)
            if not style & WS_EX_NOACTIVATE:
                user32.SetWindowLongPtrW(top, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
                changed = style
        try:
            yield detail
        finally:
            if changed is not None:
                # An application may activate itself a moment after the call returns.
                time.sleep(0.15)
                if user32.IsWindow(top) and not self._windows.get(int(top), {}).get("hidden"):
                    user32.SetWindowLongPtrW(top, GWL_EXSTYLE, changed)
            now = user32.GetForegroundWindow()
            if front and now != front:
                detail["foreground"] = "given back" if user32.SetForegroundWindow(front) else "taken"

    # -- capture -------------------------------------------------------------------------

    def capture(self, window: dict):
        hwnd = int(window["handle"])
        if user32.IsIconic(hwnd):
            return None
        image = self._print_window(hwnd)
        method = "PrintWindow"
        if image is None or _blank(image):
            wgc = self._graphics_capture(hwnd)
            if wgc is not None:
                image, method = wgc, "Windows.Graphics.Capture"
        if image is None:
            return None
        return {"image": image, "method": method}

    def _print_window(self, hwnd):
        from PIL import Image

        left, top, right, bottom = _rect(hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return None
        # A window of another DPI than its screen's (a DPI-unaware one on a scaled screen)
        # draws at its own scale.
        scale = (user32.GetDpiForWindow(hwnd) or 96) / _monitor_dpi(hwnd)
        drawn = (max(1, round(width * scale)), max(1, round(height * scale)))
        canvas = (max(width, drawn[0]), max(height, drawn[1]))
        screen = user32.GetDC(None)
        dc = gdi32.CreateCompatibleDC(screen)
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), canvas[0], -canvas[1], 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(dc, bitmap)
        try:
            ok = user32.PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT)
            data = ctypes.string_at(bits, canvas[0] * canvas[1] * 4) if ok else None
        finally:
            gdi32.SelectObject(dc, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(dc)
            user32.ReleaseDC(None, screen)
        if data is None:
            return None
        image = Image.frombuffer("RGBA", canvas, data, "raw", "BGRA", 0, 1).convert("RGB")
        if drawn != (width, height):
            image = image.crop((0, 0, *drawn)).resize((width, height), Image.LANCZOS)
        bounds = frame(hwnd)
        return image.crop((bounds[0] - left, bounds[1] - top, bounds[2] - left, bounds[3] - top))

    def _graphics_capture(self, hwnd):
        try:
            session = WGCSession(hwnd, buffers=1)
        except (ImportError, OSError):
            return None
        try:
            return session.frame(frames=1, first=2.0)
        except OSError:
            return None
        finally:
            session.close()

    # -- input sent to a window ----------------------------------------------------------

    def input(self, window: dict, event: dict) -> Delivery:
        hwnd = int(window["handle"])
        devtools = self._devtools_of(window["pid"]) if window.get("cdp") else None
        if devtools is not None:
            try:
                return self._devtools_input(devtools, window, event)
            except (OSError, RuntimeError, ConnectionError) as error:
                tried = [f"DevTools: {error}"]
        else:
            tried = []
        framework = window.get("framework") or "unknown"
        if POSTED.get(framework) is False:
            raise NeedsPhysical(f"{framework} windows ignore input sent to them (posted messages); a click on an "
                                "element with an action, or set_value, works without it", tried)
        if user32.IsIconic(hwnd):
            raise NeedsPhysical("the window is minimized: input sent to it lands nowhere", tried)
        kind = event["type"]
        detail = {"method": "PostMessage"}
        if POSTED.get(framework) is None:
            detail["note"] = f"{framework} windows were not measured: the application may ignore it"
        if kind in ("click", "drag", "scroll"):
            # A control that takes the focus on a click (a text field) activates its window,
            # which then takes the foreground where the system lets it: as for a semantic
            # action, the window is WS_EX_NOACTIVATE while it handles the messages. The
            # field still gets its thread's focus, so typing reaches it.
            with self._quiet(hwnd) as quiet:
                self._post_mouse(hwnd, event, detail)
            detail.update(quiet)
        elif kind == "type":
            target = self._typed_into(hwnd, tried)
            for char in event["text"]:
                if char == "\n":
                    self._post_key(target, VKEYS["enter"])
                elif char == "\t":
                    self._post_key(target, VKEYS["tab"])
                else:
                    for unit in _utf16(char):
                        user32.PostMessageW(target, WM_CHAR, unit, 1)
        elif kind == "key":
            keys = [key.lower() for key in event["keys"]]
            if any(key in MODIFIERS for key in keys) or len(keys) > 1:
                raise NeedsPhysical("a key combination needs the real keyboard here: a window takes ctrl, alt, "
                                    "shift and win from the keyboard's state, which posted keys do not set", tried)
            key = keys[0]
            vk = VKEYS.get(key) or (111 + int(key[1:]) if re.fullmatch(r"f\d{1,2}", key) else None) or \
                (ord(key.upper()) if len(key) == 1 and key.isalnum() else None)
            if vk is None:
                raise NeedsPhysical(f"the key {key!r} cannot be sent to a window", tried)
            self._post_key(self._typed_into(hwnd, tried), vk)
        else:
            raise ValueError(f"an input event is one of click, drag, scroll, type, key, not {kind!r}")
        return Delivery("targeted", "unverified", detail)

    def _post_mouse(self, hwnd, event, detail):
        kind = event["type"]
        if kind == "click":
            x, y = event["x"], event["y"]
            target, point = self._child_at(hwnd, x, y)
            covered = self._covered(hwnd, x, y)
            right = event.get("button") == "right"
            down, up = (WM_RBUTTONDOWN, WM_RBUTTONUP) if right else (WM_LBUTTONDOWN, WM_LBUTTONUP)
            pressed = MK_RBUTTON if right else MK_LBUTTON
            user32.PostMessageW(target, WM_MOUSEMOVE, 0, _lparam(*point))
            for number in range(int(event.get("count", 1))):
                user32.PostMessageW(target, WM_LBUTTONDBLCLK if number and not right else down, pressed,
                                    _lparam(*point))
                user32.PostMessageW(target, up, 0, _lparam(*point))
            if covered:
                detail["note"] = ("another window covers this point; some controls (WinForms buttons) take a click "
                                  "only where their window is on top")
        elif kind == "drag":
            target, start = self._child_at(hwnd, event["x"], event["y"])
            user32.PostMessageW(target, WM_LBUTTONDOWN, MK_LBUTTON, _lparam(*start))
            for number in range(1, 9):
                x = event["x"] + (event["to_x"] - event["x"]) * number / 8
                y = event["y"] + (event["to_y"] - event["y"]) * number / 8
                point = self._client(target, round(x), round(y))
                user32.PostMessageW(target, WM_MOUSEMOVE, MK_LBUTTON, _lparam(*point))
            user32.PostMessageW(target, WM_LBUTTONUP, 0, _lparam(*point))
        elif kind == "scroll":
            x, y = event.get("x"), event.get("y")
            if x is None:
                left, top, right, bottom = frame(hwnd)
                x, y = (left + right) // 2, (top + bottom) // 2
            target, _ = self._child_at(hwnd, x, y)
            direction = event["direction"]
            message = WM_MOUSEWHEEL if direction in ("up", "down") else WM_MOUSEHWHEEL
            delta = WHEEL_DELTA if direction in ("up", "right") else -WHEEL_DELTA
            for _ in range(int(event.get("amount", 5))):
                user32.PostMessageW(target, message, (delta & 0xFFFF) << 16, _lparam(x, y))

    def _child_at(self, hwnd, x, y):
        """The deepest visible child of hwnd at screen point (x, y), and the point in its
        client coordinates (its own DPI: ScreenToClient converts for this aware process)."""
        current = hwnd
        while True:
            point = wintypes.POINT(int(x), int(y))
            user32.ScreenToClient(current, ctypes.byref(point))
            child = user32.ChildWindowFromPointEx(current, point, 0x1 | 0x4)  # skip invisible, transparent
            if not child or child == current:
                return current, (point.x, point.y)
            current = child

    @staticmethod
    def _client(hwnd, x, y):
        point = wintypes.POINT(int(x), int(y))
        user32.ScreenToClient(hwnd, ctypes.byref(point))
        return point.x, point.y

    @staticmethod
    def _covered(hwnd, x, y) -> bool:
        under = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        return not under or user32.GetAncestor(under, 2) != user32.GetAncestor(hwnd, 2)

    @staticmethod
    def _focus(hwnd):
        """Where the window's thread has the keyboard focus (hwnd or a child of it), else
        None: a thread loses its focus when its window goes to the background, and one
        shown without activation never had it."""
        thread = user32.GetWindowThreadProcessId(hwnd, None)
        info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        if user32.GetGUIThreadInfo(thread, ctypes.byref(info)) and info.hwndFocus and \
                (info.hwndFocus == hwnd or user32.IsChild(hwnd, info.hwndFocus)):
            return info.hwndFocus
        return None

    def _typed_into(self, hwnd, tried):
        """The window that takes posted keys: the one with the keyboard focus, or a window
        without child windows (it reads keys itself). Keys posted to a top-level window
        whose controls have no focus land nowhere: refused. A posted click on a field gives
        it the focus (its thread's, not the foreground)."""
        target = self._focus(hwnd)
        if target is not None:
            return target
        if not user32.GetWindow(hwnd, 5):  # GW_CHILD
            return hwnd
        raise NeedsPhysical("nothing in this window has the keyboard focus (a window in the background loses it): "
                            "click the field first, or set its value", tried)

    @staticmethod
    def _post_key(target, vk):
        scan = user32.MapVirtualKeyW(vk, 0)
        user32.PostMessageW(target, WM_KEYDOWN, vk, 1 | scan << 16)
        user32.PostMessageW(target, WM_KEYUP, vk, 1 | scan << 16 | 0xC0000000)

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
        return devtools_url(launched)

    def _page(self, devtools, window):
        return page_session(devtools, window.get("title"))

    def _css(self, devtools, session, window, x, y):
        """Screen point (x, y) in the page's CSS pixels: through the render widget's client
        area, by the page's device pixel ratio."""
        hwnd = int(window["handle"])
        widgets = []

        @WNDENUMPROC
        def each(child, _):
            if _text(user32.GetClassNameW, child, 256) == "Chrome_RenderWidgetHostHWND":
                widgets.append(child)
            return True

        user32.EnumChildWindows(hwnd, each, 0)
        ratio = float(devtools.call("Runtime.evaluate", {"expression": "window.devicePixelRatio",
                                                         "returnByValue": True}, session)["result"]["value"])
        if widgets:
            cx, cy = self._client(widgets[0], x, y)
        else:
            inner = devtools.call("Runtime.evaluate", {"expression": "[window.outerHeight - window.innerHeight]",
                                                       "returnByValue": True}, session)["result"]["value"][0]
            left, top, _, _ = frame(hwnd)
            cx, cy = x - left, y - top - inner * ratio
        return cx / ratio, cy / ratio

    def _devtools_input(self, devtools, window, event) -> Delivery:
        session = self._page(devtools, window)
        left, top, right, bottom = frame(int(window["handle"]))
        dispatch(devtools, session, event, lambda x, y: self._css(devtools, session, window, x, y),
                 ((left + right) // 2, (top + bottom) // 2))
        return Delivery("targeted", "delivered", {"method": "DevTools"})

    # -- launching and placing windows -----------------------------------------------------

    def launch(self, app: str, args=(), directory=None, visible: bool = False, timeout: float = 30.0) -> dict:
        exe = _resolve(app)
        name = Path(exe).stem.lower()
        argv = [exe]
        profile = None
        base = Path(directory) if directory else (self.directory or Path(os.environ.get("TEMP", ".")))
        if name in CHROMIUMS:
            profile = base / f"{name}-profile"
            profile.mkdir(parents=True, exist_ok=True)
            (profile / "DevToolsActivePort").unlink(missing_ok=True)
            # Chromium keeps a window on a screen (a position off them is moved back): the
            # window is placed once it shows.
            argv += [*CHROMIUM_FLAGS, f"--user-data-dir={profile}", "--new-window", "--window-size=1280,860"]
        elif _electron(exe):
            argv += ELECTRON_FLAGS
        argv += [str(arg) for arg in args]
        before = {row["handle"] for row in self.windows()}
        front = user32.GetForegroundWindow()
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        # Shown without activation where the application puts it, then placed.
        startup.wShowWindow = SW_SHOWNOACTIVATE
        electron = name not in CHROMIUMS and _electron(exe)
        process = subprocess.Popen(argv, startupinfo=startup, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE if electron else subprocess.DEVNULL,
                                   cwd=str(Path(exe).parent))
        launched = {"exe": exe, "process": process, "profile": str(profile) if profile else None, "devtools": None}
        self._launched[process.pid] = launched
        if electron:
            threading.Thread(target=_listen, args=(process, launched), daemon=True).start()
        deadline = time.monotonic() + float(timeout)
        found = None
        while found is None and time.monotonic() < deadline:
            parents = {pid: parent for pid, (parent, _) in processes().items()}
            fresh = [row for row in self.windows() if row["handle"] not in before]
            ours = [row for row in fresh if _descends(row["pid"], process.pid, parents)]
            if ours:
                found = ours[0]
            elif process.poll() == 0 and len(fresh) == 1:
                # A launcher that started the app and left.
                found = fresh[0]
            else:
                time.sleep(0.1)
        if found is None:
            raise RuntimeError(f"{app} showed no window within {timeout:g} s")
        if found["pid"] != process.pid:
            self._launched[found["pid"]] = {**launched, "process": None}
        hwnd = found["handle"]
        self._windows[hwnd] = {"pid": found["pid"], "hidden": False}
        self._place(hwnd, visible)
        given = self._settle(hwnd, found["pid"], front, visible)
        row = self.window(hwnd) or found
        return {**row, **({"foreground": False, "foreground_given_back": True} if given else {})}

    def _settle(self, hwnd, pid, front, visible, seconds=2.0) -> bool:
        """For a moment after its start an application may move its window back onto a
        screen or take the foreground: place it again, give the foreground back. Whether
        the foreground was given back."""
        given = False
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and user32.IsWindow(hwnd):
            now = user32.GetForegroundWindow()
            if front and now and now != front and _pid(now) == pid:
                given = bool(user32.SetForegroundWindow(front)) or given
            if not visible and any(_overlap(frame(hwnd), area) for area in _monitors()):
                self._place(hwnd, False)
            time.sleep(0.1)
        return given

    def show(self, window: dict, visible: bool) -> dict:
        hwnd = int(window["handle"])
        if hwnd not in self._windows and window.get("pid") not in self._launched:
            raise PermissionError("only a window the agent launched is moved; the user's windows stay where they are")
        self._windows.setdefault(hwnd, {"pid": window.get("pid"), "hidden": False})
        self._place(hwnd, visible)
        return self.window(hwnd)

    def _place(self, hwnd, visible):
        """Show the window without activating it: on the primary screen's work area
        (visible), else off the screens with WS_EX_NOACTIVATE. (SetWindowPlacement would
        bring a position off the screens back onto one; SetWindowPos does not.)"""
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if user32.IsIconic(hwnd) else 1)  # restore
        left, top, right, bottom = _rect(hwnd)
        if visible:
            area = wintypes.RECT()
            user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
            x, y = area.left + 60, area.top + 60
        else:
            x, y = _offscreen_x(right - left), _virtual()[1] + 40
        user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        if visible:
            time.sleep(0.15)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
        self._windows.setdefault(hwnd, {"pid": _pid(hwnd)})["hidden"] = not visible

    def close(self) -> None:
        for hwnd, about in list(self._windows.items()):
            if about.get("hidden") and user32.IsWindow(hwnd):
                with contextlib.suppress(OSError):
                    self._place(hwnd, True)
        for launched in self._launched.values():
            if launched.get("devtools") is not None:
                launched["devtools"].close()
                launched["devtools"] = None


def _app(path):
    from harness_computer import physical

    return physical.app_name(path)


def _hresult(error) -> int | None:
    value = getattr(error, "hresult", None)
    if value is None and getattr(error, "args", None) and isinstance(error.args[0], int):
        value = error.args[0]
    return value


def _message(error) -> str:
    text = getattr(error, "text", None) or str(error)
    return " ".join(str(text).split())[:200]


def _blank(image) -> bool:
    """A picture of one colour (a window that drew nothing for the capture)."""
    extrema = image.getextrema()
    return all(high - low < 6 for low, high in extrema)


def _utf16(char) -> list:
    data = char.encode("utf-16-le")
    return [int.from_bytes(data[index:index + 2], "little") for index in range(0, len(data), 2)]


def _monitors() -> list:
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), LPARAM)
    def each(monitor, dc, rect, _):
        area = rect.contents
        found.append((area.left, area.top, area.right, area.bottom))
        return True

    user32.EnumDisplayMonitors(None, None, each, 0)
    return found


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _virtual() -> tuple:
    """The virtual screen's left and top (every monitor's union)."""
    return user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)  # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN


def _offscreen_x(width) -> int:
    return _virtual()[0] - int(width) - 400


def _electron(exe) -> bool:
    resources = Path(exe).parent / "resources"
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
    """The executable of `app`: a path, a program on PATH, a Chromium by name, or one the
    system registered (App Paths)."""
    path = Path(os.path.expandvars(str(app)))
    if path.is_file():
        return str(path.resolve())
    name = path.stem.lower()
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        for relative in CHROMIUMS.get(name, ()):
            if root and Path(root, relative).is_file():
                return str(Path(root, relative))
    found = shutil.which(str(app))
    if found:
        return found
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}.exe") as key:
                value = winreg.QueryValue(key, None)
                if value and Path(value.strip('"')).is_file():
                    return value.strip('"')
        except OSError:
            continue
    raise FileNotFoundError(f"no application {app!r} here: give its path or a program name on PATH")


if sys.platform == "win32":
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p, LPARAM]
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.IsZoomed.argtypes = [HWND]
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    shcore.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint),
                                        ctypes.POINTER(ctypes.c_uint)]
