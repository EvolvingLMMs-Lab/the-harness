"""Input injected into this computer's input queue, which the window in front reads as the
keyboard and mouse (on the user's display their real ones: physical.py decides). Two
devices with one interface, key(name, down), button(name, down), relative(dx, dy),
move_to(x, y), scroll(steps), text(text):

- SendInput (Windows): keys as set-1 scan codes (what a game's bindings read, whatever the
  layout), raw relative motion, the pointer at a point of the virtual screen, text as
  Unicode key events (no input method composes them).
- XTest (an X display): keys by keysym (a character the map lacks gets a spare keycode
  while it is typed), and the computer worker's click, drag, wheel, keys and text.

KEYSYMS and SCANCODES name the keys (runtime/safety/shield.py KEY_NAMES; single characters too)
for both, and for rfb.py. Standard library at import; python-xlib when an XTest is made.
"""

import contextlib
import ctypes
from ctypes import wintypes
import sys
import time

# Key names as X keysyms.
KEYSYMS = {
    "enter": 0xFF0D, "return": 0xFF0D, "\n": 0xFF0D, "\r": 0xFF0D, "tab": 0xFF09, "\t": 0xFF09,
    "backspace": 0xFF08, "delete": 0xFFFF, "del": 0xFFFF, "esc": 0xFF1B, "escape": 0xFF1B, "space": 0x20,
    "slash": 0x2F, "up": 0xFF52, "down": 0xFF54, "left": 0xFF51, "right": 0xFF53, "home": 0xFF50, "end": 0xFF57,
    "pageup": 0xFF55, "pgup": 0xFF55, "pagedown": 0xFF56, "pgdn": 0xFF56, "insert": 0xFF63,
    "ctrl": 0xFFE3, "ctrlleft": 0xFFE3, "ctrlright": 0xFFE4, "shift": 0xFFE1, "shiftleft": 0xFFE1,
    "shiftright": 0xFFE2, "alt": 0xFFE9, "altleft": 0xFFE9, "altright": 0xFFEA, "option": 0xFFE9,
    "optionleft": 0xFFE9, "optionright": 0xFFEA, "win": 0xFFEB, "winleft": 0xFFEB, "winright": 0xFFEC,
    "command": 0xFFEB, "capslock": 0xFFE5, "numlock": 0xFF7F, "scrolllock": 0xFF14, "pause": 0xFF13,
    "printscreen": 0xFF61, "prtsc": 0xFF61, "prtscr": 0xFF61, "prntscrn": 0xFF61, "print": 0xFF61,
    "apps": 0xFF67, "help": 0xFF6A, "select": 0xFF60, "execute": 0xFF62, "clear": 0xFF0B, "add": 0xFFAB,
    "subtract": 0xFFAD, "multiply": 0xFFAA, "divide": 0xFFAF, "decimal": 0xFFAE, "separator": 0xFFAC,
    "volumemute": 0x1008FF12, "volumedown": 0x1008FF11, "volumeup": 0x1008FF13, "playpause": 0x1008FF14,
    "nexttrack": 0x1008FF17, "prevtrack": 0x1008FF16, "stop": 0x1008FF15, "browserback": 0x1008FF26,
    "browserforward": 0x1008FF27, "browserrefresh": 0x1008FF29, "browserhome": 0x1008FF18,
    "browsersearch": 0x1008FF1B, "browserfavorites": 0x1008FF30, "browserstop": 0x1008FF28, "sleep": 0x1008FF2F,
    **{f"f{n}": 0xFFBE + n - 1 for n in range(1, 25)}, **{f"num{n}": 0xFFB0 + n for n in range(10)}}
# Key names and characters as set-1 scan codes; 0xE0.. marks an extended key.
SCANCODES = {
    **dict(zip("1234567890", range(0x02, 0x0C))), **dict(zip("qwertyuiop", range(0x10, 0x1A))),
    **dict(zip("asdfghjkl", range(0x1E, 0x27))), **dict(zip("zxcvbnm", range(0x2C, 0x33))),
    "-": 0x0C, "=": 0x0D, "[": 0x1A, "]": 0x1B, ";": 0x27, "'": 0x28, "`": 0x29, "\\": 0x2B, ",": 0x33, ".": 0x34,
    "/": 0x35, "slash": 0x35, "escape": 0x01, "esc": 0x01, "backspace": 0x0E, "tab": 0x0F, "enter": 0x1C,
    "return": 0x1C, "ctrl": 0x1D, "ctrlleft": 0x1D, "ctrlright": 0xE01D, "shift": 0x2A, "shiftleft": 0x2A,
    "shiftright": 0x36, "alt": 0x38, "altleft": 0x38, "altright": 0xE038, "space": 0x39, "capslock": 0x3A,
    **{f"f{n}": 0x3A + n for n in range(1, 11)}, "f11": 0x57, "f12": 0x58, "home": 0xE047, "up": 0xE048,
    "pageup": 0xE049, "pgup": 0xE049, "left": 0xE04B, "right": 0xE04D, "end": 0xE04F, "down": 0xE050,
    "pagedown": 0xE051, "pgdn": 0xE051, "insert": 0xE052, "delete": 0xE053, "del": 0xE053, "win": 0xE05B,
    "winleft": 0xE05B, "winright": 0xE05C, "command": 0xE05B}
# Pointer buttons (X numbers); the wheel's up, down, left and right are buttons 4 to 7.
BUTTONS = {"left": 1, "middle": 2, "right": 3}
WHEEL = {"up": 4, "down": 5, "left": 6, "right": 7}


def keysym(name: str) -> int:
    """The keysym of a key name (KEYSYMS) or of one character."""
    lower = str(name).lower()
    if lower in KEYSYMS:
        return KEYSYMS[lower]
    if len(name) == 1:
        return char_keysym(name)
    raise ValueError(f"no keysym for the key {name!r}")


def char_keysym(char: str) -> int:
    """The keysym of one character: Latin-1 directly, the rest as Unicode keysyms."""
    if char in "\n\r\t":
        return KEYSYMS[char]
    point = ord(char)
    if 0x20 <= point <= 0x7E or 0xA0 <= point <= 0xFF:
        return point
    return 0x01000000 + point


# -- SendInput (Windows) ----------------------------------------------------------------------

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x4, 0x8
MOUSEEVENTF_MOVE, MOUSEEVENTF_WHEEL, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x1, 0x800, 0x8000, 0x4000
MOUSE_BUTTONS = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class SendInput:
    """The system's input queue on Windows: what the window in front reads."""

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("SendInput is Windows' input queue")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self._user32.SendInput.restype = wintypes.UINT

    def _send(self, *inputs) -> None:
        array = (INPUT * len(inputs))(*inputs)
        if self._user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)) != len(inputs):
            raise OSError(ctypes.get_last_error(), "SendInput was blocked (another desktop or a higher-integrity "
                                                   "window is in front)")

    @staticmethod
    def _mouse(flags, dx=0, dy=0, data=0) -> INPUT:
        return INPUT(INPUT_MOUSE, _INPUTUNION(mi=MOUSEINPUT(int(dx), int(dy), ctypes.c_ulong(data & 0xFFFFFFFF).value,
                                                             flags, 0, 0)))

    def key(self, name, down):
        code = SCANCODES[name if len(name) == 1 else name.lower()]
        flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if code > 0xFF else 0)
        self._send(INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(0, code & 0xFF, flags, 0, 0))))

    def button(self, name, down):
        press, release = MOUSE_BUTTONS[name]
        self._send(self._mouse(press if down else release))

    def relative(self, dx, dy):
        if dx or dy:
            self._send(self._mouse(MOUSEEVENTF_MOVE, dx, dy))

    def move_to(self, x, y):
        """The pointer at point (x, y) of the virtual screen (physical pixels)."""
        metrics = self._user32.GetSystemMetrics
        vx, vy, vw, vh = (metrics(index) for index in (76, 77, 78, 79))  # SM_[XY]VIRTUALSCREEN, SM_C[XY]VIRTUALSCREEN
        nx, ny = round((float(x) - vx) * 65535 / max(1, vw - 1)), round((float(y) - vy) * 65535 / max(1, vh - 1))
        self._send(self._mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))

    def scroll(self, steps):
        self._send(self._mouse(MOUSEEVENTF_WHEEL, data=120 * int(steps)))

    def text(self, text):
        for char in text:
            code = ord(char)
            self._send(INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0))),
                       INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                                                                      0, 0))))


# -- XTest (an X display) ----------------------------------------------------------------------

class XTest:
    """Input on an X display through XTest (`x11`: desktop/linux.py X11): its pointer and
    keyboard."""

    def __init__(self, x11):
        from Xlib.ext import xtest

        self.x11 = x11
        self.xtest = xtest
        # Keysyms the keyboard map lacks, mapped on spare keycodes while a step types them:
        # keysym -> keycode.
        self._spares = {}

    # The device interface.

    def key(self, name, down):
        X = self.x11.X
        with self.x11.lock:
            code, _ = self._code(_keysym(name))
            self.xtest.fake_input(self.x11.display, X.KeyPress if down else X.KeyRelease, code)
            self.x11.display.sync()

    def button(self, name, down):
        with self.x11.lock:
            self._button(BUTTONS.get(name, 1), down)
            self.x11.display.sync()

    def relative(self, dx, dy):
        if dx or dy:
            with self.x11.lock:
                self.xtest.fake_input(self.x11.display, self.x11.X.MotionNotify, detail=True, x=int(dx), y=int(dy))
                self.x11.display.sync()

    def move_to(self, x, y):
        with self.x11.lock:
            self._move(x, y)

    def scroll(self, steps):
        with self.x11.lock:
            self._wheel("up" if steps > 0 else "down", abs(int(steps)))
            self.x11.display.sync()

    def text(self, text):
        self.type(text)

    # The computer worker's steps.

    def click(self, x, y, button="left", count=1):
        with self.x11.lock:
            self._move(x, y)
            for _ in range(int(count)):
                self._button(BUTTONS.get(button, 1), True)
                self._button(BUTTONS.get(button, 1), False)
            self.x11.display.sync()

    def drag(self, x, y, to_x, to_y, seconds=0.4):
        with self.x11.lock:
            self._move(x, y)
            self._button(1, True)
            steps = 8
            for number in range(1, steps + 1):
                time.sleep(max(0.0, float(seconds)) / steps)
                self._move(x + (to_x - x) * number / steps, y + (to_y - y) * number / steps)
            self._button(1, False)
            self.x11.display.sync()

    def wheel(self, direction, amount=5, x=None, y=None):
        """The wheel `amount` clicks toward `direction`, at (x, y) when given."""
        with self.x11.lock:
            if x is not None:
                self._move(x, y)
            self._wheel(direction, amount)
            self.x11.display.sync()

    def keys(self, names):
        """Press keys together (modifiers first) and release them in reverse."""
        X = self.x11.X
        with self.x11.lock:
            codes = []
            for name in names:
                code, shifted = self._code(_keysym(name))
                if shifted and self._code(_keysym("shift"))[0] not in codes:
                    codes.append(self._code(_keysym("shift"))[0])
                codes.append(code)
            for code in codes:
                self.xtest.fake_input(self.x11.display, X.KeyPress, code)
            for code in reversed(codes):
                self.xtest.fake_input(self.x11.display, X.KeyRelease, code)
            self.x11.display.sync()
            self._restore()

    def type(self, text):
        X = self.x11.X
        with self.x11.lock:
            shift = self._code(_keysym("shift"))[0]
            keysyms = [char_keysym(char) for char in text]
            # The characters the map lacks get their keys first, and the applications a
            # moment to read the new map (MappingNotify).
            if any(self._code(code, spare=False) is None for code in keysyms):
                for code in dict.fromkeys(keysyms):
                    self._code(code)
                time.sleep(0.05)
            for code_keysym in keysyms:
                code, shifted = self._code(code_keysym)
                if shifted:
                    self.xtest.fake_input(self.x11.display, X.KeyPress, shift)
                self.xtest.fake_input(self.x11.display, X.KeyPress, code)
                self.xtest.fake_input(self.x11.display, X.KeyRelease, code)
                if shifted:
                    self.xtest.fake_input(self.x11.display, X.KeyRelease, shift)
                self.x11.display.sync()
            self._restore()

    # Within the display's lock.

    def _move(self, x, y):
        self.xtest.fake_input(self.x11.display, self.x11.X.MotionNotify, x=int(round(x)), y=int(round(y)))
        self.x11.display.sync()

    def _button(self, number, down):
        X = self.x11.X
        self.xtest.fake_input(self.x11.display, X.ButtonPress if down else X.ButtonRelease, int(number))

    def _wheel(self, direction, amount):
        for _ in range(int(amount)):
            self._button(WHEEL[direction], True)
            self._button(WHEEL[direction], False)

    def _code(self, keysym, spare=True):
        """The keycode of `keysym` and whether it needs shift; a keysym the map lacks gets a
        spare keycode (this display's own: put back by _restore), or None when not `spare`."""
        if keysym in self._spares:
            return self._spares[keysym], False
        display = self.x11.display
        for code, index in display.keysym_to_keycodes(keysym):
            if index in (0, 1):
                return code, index == 1
        if not spare:
            return None
        code = self._spare_code()
        display.change_keyboard_mapping(code, [(keysym, keysym)])
        display.sync()
        self._spares[keysym] = code
        return code, False

    def _spare_code(self) -> int:
        display = self.x11.display
        first = display.display.info.min_keycode
        count = display.display.info.max_keycode - first + 1
        mapping = display.get_keyboard_mapping(first, count)
        taken = set(self._spares.values())
        for offset in range(count - 1, -1, -1):
            if not any(mapping[offset]) and first + offset not in taken:
                return first + offset
        raise RuntimeError("no spare key on this display's keyboard map for more characters at once")

    def _restore(self):
        if not self._spares:
            return
        # The applications read the keys with the map as it was when they were typed.
        time.sleep(0.1)
        for code in self._spares.values():
            with contextlib.suppress(Exception):
                self.x11.display.change_keyboard_mapping(code, [(0, 0)])
        with contextlib.suppress(Exception):
            self.x11.display.sync()
        self._spares.clear()


def _keysym(name) -> int:
    """keysym(), else an X keysym's own name ("Prior", "KP_Enter")."""
    try:
        return keysym(name)
    except ValueError:
        from Xlib import XK

        found = XK.string_to_keysym(str(name))
        if not found:
            raise ValueError(f"no X key {name!r}") from None
        return found
