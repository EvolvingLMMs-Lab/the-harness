"""Whether the user is using this computer, for every worker that sends their real input
(the computer worker, Minecraft): their own keyboard and mouse told from injected input
(watch(): raw input on Windows, which gives injected input no device; the idle time of
an X display and macOS, the worker's own input and another agent's dispatch left out;
the pointer moved), the quiet time after it, took_over and hand_back (UserPresence).
Standard library only.
"""

import ctypes
import sys
import threading
import time

# How long the user leaves the computer alone before the agent's steps run again.
QUIET_SECONDS = 2.0
# Input this long after the agent's own counts as the agent's (the system's idle clock is
# coarse).
USER_INPUT_SLACK = 0.25
# How far (physical pixels) the pointer may be from where the agent left it before the move
# counts as the user's.
USER_MOVE_PIXELS = 6


class RawInputWatch:
    """When the user last used a real keyboard or mouse (Windows raw input, received in the
    background on a thread of its own): injected input comes with no device."""

    exact = True

    def __init__(self):
        from ctypes import wintypes

        self.at = None   # time.monotonic() of the user's last input
        self.kind = None
        self._wintypes = wintypes
        self._ready = threading.Event()
        self._hwnd = None
        self._thread = threading.Thread(target=self._run, name="user-input-watch", daemon=True)
        self._thread.start()
        self._ready.wait(5.0)

    def last(self):
        """(time.monotonic() of the user's last input, "keyboard" | "mouse"), or None."""
        return (self.at, self.kind) if self.at is not None else None

    def sent(self):
        """The worker's own input needs no note here: it has no device."""

    def _run(self):
        wintypes = self._wintypes
        user32, kernel32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32")

        class RAWINPUTDEVICE(ctypes.Structure):
            _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT), ("dwFlags", wintypes.DWORD),
                        ("hwndTarget", wintypes.HWND)]

        class RAWINPUTHEADER(ctypes.Structure):
            _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD), ("hDevice", wintypes.HANDLE),
                        ("wParam", wintypes.WPARAM)]

        procedure_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                            wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", procedure_type), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.GetRawInputData.argtypes = (wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                           ctypes.POINTER(wintypes.UINT), wintypes.UINT)
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                           wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)

        def procedure(hwnd, message, wparam, lparam):
            if message == 0x00FF:  # WM_INPUT
                header = RAWINPUTHEADER()
                size = wintypes.UINT(ctypes.sizeof(header))
                if user32.GetRawInputData(lparam, 0x10000005, ctypes.byref(header), ctypes.byref(size),
                                          ctypes.sizeof(RAWINPUTHEADER)) != 0xFFFFFFFF and header.hDevice:
                    self.at = time.monotonic()
                    self.kind = "mouse" if header.dwType == 0 else "keyboard"
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._procedure = procedure_type(procedure)
        handle = kernel32.GetModuleHandleW(None)
        name = f"HarnessUserWatch{id(self)}"
        user32.RegisterClassW(ctypes.byref(WNDCLASSW(0, self._procedure, 0, 0, handle, None, None, None, None, name)))
        self._hwnd = user32.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0, wintypes.HWND(-3), None, handle,
                                            None)  # HWND_MESSAGE
        # The mouse and the keyboard, RIDEV_INPUTSINK: also while another window is in front.
        devices = (RAWINPUTDEVICE * 2)(RAWINPUTDEVICE(1, 2, 0x100, self._hwnd), RAWINPUTDEVICE(1, 6, 0x100, self._hwnd))
        user32.RegisterRawInputDevices(devices, 2, ctypes.sizeof(RAWINPUTDEVICE))
        self._user32 = user32
        self._ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def close(self):
        if self._hwnd:
            self._user32.PostMessageW(self._hwnd, 0x0012, 0, 0)  # WM_QUIT


class IdleWatch:
    """When anyone last used the keyboard or mouse, from the system's idle time (`idle`:
    seconds, or None where the system does not say), injected input included: the
    worker's own (sent) is left out by UserPresence."""

    exact = False

    def __init__(self, idle):
        self._idle = idle
        self.own = None   # time.monotonic() of the worker's last injected input

    def last(self):
        idle = self._idle()
        return (time.monotonic() - idle, None) if idle is not None else None

    def sent(self):
        self.own = time.monotonic()

    def close(self):
        pass


def watch(idle=None):
    """This system's watch: raw input on Windows, else the idle time `idle` gives (an X
    display's, macOS's; None where there is none)."""
    if sys.platform == "win32":
        return RawInputWatch()
    return IdleWatch(idle or idle_seconds)


def idle_seconds():
    """Seconds since anyone's last key, click or pointer move on this computer's display
    (macOS; an X display with MIT-SCREEN-SAVER), else None."""
    if sys.platform == "darwin":
        from harness_computer.desktop import macos

        return macos.idle_seconds()
    import os

    if not os.environ.get("DISPLAY"):
        return None
    try:
        from harness_computer.desktop import linux

        x11 = linux.shared()
        with x11.lock:
            return x11.idle_seconds()
    except Exception:
        return None


class UserPresence:
    """The user's hand, for one worker: `watch`, `pointer` (where the pointer is, or None),
    `front` (what tells the window in front apart) and the input `lock` (its records name
    another agent's dispatches). The worker calls mark() as each of its inputs ends,
    sent() as it injects, check() before a step, touched() while one lasts, hand_back()
    when the computer is the agent's as it is now."""

    def __init__(self, watch=None, pointer=None, front=None, lock=None, owner=None):
        # `owner`: () -> this worker's owner of the lock (it changes as sessions identify).
        self.watch = watch if watch is not None else IdleWatch(lambda: None)
        self._pointer = pointer
        self._front_of = front
        self._lock = lock
        self._owner = owner
        self.since = None      # time.monotonic() the agent's last input ended
        self.user_at = None    # time.monotonic() of the user's last input seen
        self.front = None      # the window in front when the computer was handed over
        self.left = None       # where the agent left the pointer
        self._mine = 0.0       # time.time() the worker's last input ended

    def mark(self, pointer=None):
        """The agent's own input up to now (and where it left the pointer, if it moved it)."""
        self.since = time.monotonic()
        self._mine = time.time()
        if pointer is not None:
            self.left = tuple(pointer)

    def sent(self):
        self.watch.sent()

    def hand_back(self):
        """The computer is the agent's as it is now: what the user did before does not count,
        and the window in front is the one to keep."""
        self.since = time.monotonic()
        self.user_at = None
        self.front = self._front_of() if self._front_of else None
        self.left = tuple(self._pointer()) if self._pointer else None

    def used_since(self, since):
        """(When, which device) the user last used the keyboard or mouse, if after `since`
        (time.monotonic()), else None."""
        last = self.watch.last()
        if last is None or since is None:
            return None
        at, kind = last
        if not self.watch.exact:
            own = self.watch.own
            if at <= max(since, own or since) + USER_INPUT_SLACK or self._others_input(time.time() - (
                    time.monotonic() - at)):
                return None
        elif at <= since:
            return None
        return at, kind

    def touched(self):
        """The device the user touched since the agent's last input ("keyboard", "mouse",
        "computer"), else None; a step that lasts asks it as it goes."""
        found = self._moved()
        used = self.used_since(self.since)
        if used is not None:
            self.user_at = used[0]
            return used[1] or "computer"
        return found

    def check(self, named=None) -> dict | None:
        """The refusal reason ("user_input") while the user uses the computer: since the
        agent's last input or the hand-back, or less than QUIET_SECONDS ago; "took_over"
        when the window in front changed too (`named`: what the refusal may call it)."""
        now = time.monotonic()
        kind = self.touched()
        if kind is None and (self.user_at is None or now - self.user_at >= QUIET_SECONDS):
            return None
        reason = {"check": "user_input", "wait_seconds": QUIET_SECONDS,
                  "reason": f"the user is using the {kind or 'computer'}; nothing was done. Steps run again once "
                            f"they leave it alone for {QUIET_SECONDS:g} s"}
        if self.left is not None:
            reason["pointer"] = list(self.left)
        front = self._front_of() if self._front_of else None
        if self.front is not None and front is not None and front != self.front:
            reason["took_over"] = True
            name = named() if named else None
            if name:
                reason["front"] = name
            reason["reason"] = (f"the user brought another window to the front{f' ({name})' if name else ''} and "
                                "is using the computer; nothing was done. Wait until they hand it back")
        # What happened up to now is known; only later input counts again.
        self.since = now
        return reason

    def idle_for(self, seconds, limit) -> bool:
        """Whether the user leaves the computer alone for `seconds` within `limit` seconds:
        the watch's last input where it tells (another agent's is not theirs), else the
        pointer kept still."""
        deadline = time.monotonic() + limit + seconds
        still_since = time.monotonic()
        where = self._pointer() if self._pointer else None
        while True:
            last = self.watch.last()
            if self.watch.exact:
                # Raw input: no input of theirs since the watch began is idle too.
                if last is None or time.monotonic() - last[0] >= seconds:
                    return True
            elif last is not None:
                at = last[0]
                if time.monotonic() - at >= seconds or self._others_input(time.time() - (time.monotonic() - at)):
                    return True
            elif where is not None:
                now = self._pointer()
                if _far(now, where) and not self._others_pointer(now):
                    still_since, where = time.monotonic(), now
                if time.monotonic() - still_since >= seconds:
                    return True
            elif self.user_at is None or time.monotonic() - self.user_at >= seconds:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def close(self):
        self.watch.close()

    def _moved(self):
        """"mouse" when the pointer moved away from where the agent left it (not to where
        another agent left it), else None."""
        if self._pointer is None or self.left is None:
            return None
        where = tuple(self._pointer())
        if not _far(where, self.left):
            return None
        self.left = where
        if self._others_pointer(where):
            return None
        self.user_at = time.monotonic()
        return "mouse"

    def _others(self):
        """Another agent's last dispatch on this computer (the input lock's record), if
        after this worker's own."""
        if self._lock is None:
            return None
        from harness_computer.coordination import owner_name

        last = self._lock.last()
        if not last or (self._owner is not None and last.get("owner") == owner_name(self._owner())):
            return None
        return last if last.get("ended", 0) >= self._mine else None

    def _others_input(self, at) -> bool:
        last = self._others()
        return bool(last) and last["began"] - USER_INPUT_SLACK <= at <= last["ended"] + USER_INPUT_SLACK

    def _others_pointer(self, where) -> bool:
        pointer = (self._others() or {}).get("pointer")
        return bool(pointer) and not _far(where, pointer)


def _far(a, b) -> bool:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) > USER_MOVE_PIXELS
