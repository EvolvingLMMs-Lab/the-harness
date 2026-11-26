"""What the terminal sends, as the keys the chat binds.

A keystroke is written as in Claude Code's keybindings file (keybindings page, "Keystroke
syntax"): modifiers joined with +, `ctrl+k`, `shift+tab`, `meta+p`, `ctrl+shift+c`; a
chord is keystrokes separated by spaces, `ctrl+x ctrl+e`. keys(stroke) gives the
prompt_toolkit keys of one keystroke. prompt_toolkit has no name for some of them
(Shift+Enter, Ctrl+Enter, Ctrl+Backspace, anything with Cmd): each of those is carried by
one private-use character (carrier), which is a key like any other single character.

Where the modified keys come from:

    Windows   the console's key records (Reader): every modifier is in the record, in the
              old console host and in Windows Terminal alike. A burst of records with a
              line break in it is a paste, never a message sent.
    elsewhere the terminal is asked to report modified keys when the chat starts (ENABLE:
              xterm's modifyOtherKeys, and the kitty keyboard protocol where the terminal
              answers that it has it) and put back when it ends (restore). What it then
              sends, `CSI code ; modifiers u` or `CSI 27 ; modifiers ; code ~`, is turned
              back into the bytes a terminal without them sends, or into a carrier
              (Translator), before prompt_toolkit reads it.

A carrier nothing is bound to falls back to the plain key (Shift+Enter to Enter), as in a
terminal that does not report the modifier."""

import re
import sys
import time

MODIFIERS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt", "opt": "alt", "option": "alt",
             "meta": "alt", "cmd": "cmd", "command": "cmd", "super": "cmd", "win": "cmd"}
NAMED = {"escape": "escape", "esc": "escape", "enter": "enter", "return": "enter", "tab": "tab", "space": "space",
         "up": "up", "down": "down", "left": "left", "right": "right", "pageup": "pageup", "pagedown": "pagedown",
         "home": "home", "end": "end", "backspace": "backspace", "delete": "delete", "insert": "insert",
         **{f"f{number}": f"f{number}" for number in range(1, 13)}}
ORDER = ("ctrl", "alt", "shift", "cmd")
# Ctrl with one of these is a control character every terminal sends.
CONTROL = "@[\\]^_"
# Keys Claude Code never lets a file rebind (keybindings page, "Reserved shortcuts").
RESERVED = {"ctrl+c": "it always interrupts", "ctrl+d": "it always leaves", "ctrl+m": "a terminal sends it as Enter",
            "ctrl+[": "a terminal sends it as Escape", "ctrl+i": "a terminal sends it as Tab",
            "ctrl+h": "a terminal sends it as Backspace"}


class KeystrokeError(ValueError):
    pass


def split(stroke: str) -> tuple[frozenset, str]:
    """(modifiers, key) of one keystroke; KeystrokeError says what is wrong with it."""
    text = str(stroke).strip().lower()
    if not text:
        raise KeystrokeError("an empty keystroke")
    if text == "+":
        return frozenset(), "+"
    parts = text[:-2].split("+") + ["+"] if text.endswith("++") else text.split("+")
    *modifiers, key = parts
    if key == "":
        raise KeystrokeError(f"{stroke!r} names no key after its modifier (a space next to + makes it a chord)")
    unknown = [word for word in modifiers if word not in MODIFIERS]
    if unknown:
        raise KeystrokeError(f"{unknown[0]!r} in {stroke!r} is not a modifier (ctrl, shift, alt/meta, cmd)")
    if key not in NAMED and len(key) != 1:
        raise KeystrokeError(f"{key!r} in {stroke!r} is not a key")
    return frozenset(MODIFIERS[word] for word in modifiers), NAMED.get(key, key)


def normal(stroke: str) -> str:
    """One keystroke in its one spelling: ctrl+alt+shift+cmd+key, lower case."""
    modifiers, key = split(stroke)
    return "+".join([name for name in ORDER if name in modifiers] + [key])


def chord(text: str) -> tuple:
    """The keystrokes of a binding ("ctrl+x ctrl+e"), each in its one spelling."""
    strokes = tuple(normal(part) for part in str(text).split())
    if not strokes:
        raise KeystrokeError("an empty keystroke")
    return strokes


_carriers = {}
# The carriers something is bound to: only those are sent as carriers.
bound = set()


def carrier(stroke: str) -> str:
    """The private-use character that carries the keystroke `stroke` (in its one spelling)."""
    if stroke not in _carriers:
        # Supplementary private use: clear of the private-use codes terminals give their own keys.
        _carriers[stroke] = chr(0xF0000 + len(_carriers))
    return _carriers[stroke]


def carriers() -> dict:
    return dict(_carriers)


def keys(stroke: str) -> tuple:
    """The prompt_toolkit keys of one keystroke: Alt is Escape first, as terminals send it."""
    modifiers, key = split(stroke)
    name = normal(stroke)
    if "cmd" in modifiers:
        return (carrier(name),)
    if "alt" in modifiers:
        return ("escape", *keys("+".join([m for m in ORDER if m in modifiers and m != "alt"] + [key])))
    ctrl, shift = "ctrl" in modifiers, "shift" in modifiers
    if len(key) == 1:
        if key.isalpha() and key.isascii():
            if ctrl:
                return (carrier(name),) if shift else (f"c-{key}",)
            return (key.upper() if shift else key,)
        if ctrl and key in CONTROL:
            return (f"c-{key}",)
        if ctrl and shift and key == "-":
            return ("c-_",)
        if ctrl:
            return (carrier(name),)
        if shift:
            raise KeystrokeError(f"{stroke!r}: write the character Shift types on your layout instead")
        return (key,)
    if key == "escape":
        return ("escape",)
    if key == "enter":
        return (carrier(name),) if ctrl or shift else ("enter",)
    if key == "tab":
        return (carrier(name),) if ctrl else ("s-tab",) if shift else ("tab",)
    if key == "space":
        return (carrier(name),) if shift else ("c-space",) if ctrl else (" ",)
    if key == "backspace":
        return (carrier(name),) if ctrl else ("backspace",)
    if key.startswith("f") and key[1:].isdigit():
        return (carrier(name),) if shift else (f"c-{key}",) if ctrl else (key,)
    return (("c-s-" if ctrl and shift else "c-" if ctrl else "s-" if shift else "") + key,)


def shown(stroke: str) -> str:
    """A keystroke as hints write it: `shift+tab`, `ctrl+o`, `esc`, `alt+p`."""
    return normal(stroke).replace("escape", "esc")


# -- the terminals that are asked to report modified keys ---------------------------------------

# Bits of the modifier field (its value minus one); the lock keys are not modifiers here.
SHIFT, ALT, CTRL, SUPER = 1, 2, 4, 8
# modifyOtherKeys level 1 (modified keys that have no byte of their own, Shift+Enter among
# them); then whether the kitty keyboard protocol is there, answered before the device
# attributes every terminal answers.
ENABLE = "\x1b[>4;1m\x1b[?u\x1b[c"
KITTY_ON, KITTY_OFF, MODIFY_OFF = "\x1b[>1u", "\x1b[<u", "\x1b[>4;m"
_REPORT = re.compile(r"\x1b\[(?:\?(\d*)u|\?[\d;]*c|(\d+)(?::\d*)*(?:;(\d*)(?::\d+)?)?(?:;[\d:]*)?u|27;(\d+);(\d+)~)")
_PARTIAL = re.compile(r"\x1b(?:\[[\d;:?]*)?$")
_CODES = {13: "enter", 9: "tab", 27: "escape", 127: "backspace", 8: "backspace", 32: "space", 57414: "enter"}
_PLAIN = {"enter": "\r", "tab": "\t", "escape": "\x1b", "backspace": "\x7f", "space": " "}
# The keypad's keys in the kitty protocol's numbers: its characters, and its keys as a
# terminal sends them without the protocol.
_KEYPAD = {**{57399 + digit: str(digit) for digit in range(10)}, 57409: ".", 57410: "/", 57411: "*", 57412: "-",
           57413: "+", 57415: "=", 57417: "\x1b[D", 57418: "\x1b[C", 57419: "\x1b[A", 57420: "\x1b[B",
           57421: "\x1b[5~", 57422: "\x1b[6~", 57423: "\x1b[H", 57424: "\x1b[F", 57425: "\x1b[2~", 57426: "\x1b[3~"}


def encode(code: int, modifiers: int) -> str:
    """What a terminal that reports nothing sends for the key `code` with `modifiers`, or
    the carrier of a keystroke that has a binding."""
    modifiers &= SHIFT | ALT | CTRL | SUPER
    if code in _KEYPAD:
        return _KEYPAD[code]
    key = _CODES.get(code) or (chr(code).lower() if 32 < code < 0xE000 or 0xF8FF < code < 0xF0000 else None)
    if key is None:
        return ""  # a key of the terminal's own (a lock, a media key): nothing to type
    names = [name for name, bit in (("ctrl", CTRL), ("alt", ALT), ("shift", SHIFT), ("cmd", SUPER)) if modifiers & bit]
    name = "+".join(names + [key])
    if name in bound:
        return carrier(name)
    if modifiers & SUPER:
        return encode(code, modifiers & ~SUPER)
    if modifiers & ALT:
        return "\x1b" + encode(code, modifiers & ~ALT)
    if key in _PLAIN:
        if key == "tab" and modifiers & SHIFT:
            return "\x1b[Z"
        if key == "space" and modifiers & CTRL:
            return "\x00"
        return _PLAIN[key]
    if modifiers & CTRL:
        if key.isascii() and (key.isalpha() or key in CONTROL):
            return chr(ord(key.upper()) & 0x1F)
        if key == "-" and modifiers & SHIFT:
            return "\x1f"
        return ""
    return key.upper() if modifiers & SHIFT and key.isalpha() else key


class Translator:
    """The terminal's reports of modified keys, turned into what prompt_toolkit reads.
    `kitty` becomes True when the terminal answers that it has the kitty keyboard protocol
    (the chat then switches it on)."""

    def __init__(self):
        self.kitty = False
        self.on_kitty = None  # called once when the terminal says it has the protocol
        self.kept = ""

    def feed(self, data: str) -> str:
        data, self.kept = self.kept + data, ""
        found = _PARTIAL.search(data)
        if found and len(found.group()) > 1:
            # A report cut in two by the read: its start waits for the rest.
            data, self.kept = data[:found.start()], found.group()
        return _REPORT.sub(self._key, data)

    def flush(self) -> str:
        kept, self.kept = self.kept, ""
        return kept

    def _key(self, match) -> str:
        text = match.group()
        if text.endswith("c"):
            return ""  # the device attributes: only asked so that an answer always comes
        if match.group(1) is not None:
            if not self.kitty:
                self.kitty = True
                if self.on_kitty is not None:
                    self.on_kitty()
            return ""
        if text.endswith("u"):
            return encode(int(match.group(2)), max(int(match.group(3) or 1) - 1, 0))
        return encode(int(match.group(5)), max(int(match.group(4)) - 1, 0))


# -- reading the keys ------------------------------------------------------------------------

# Seconds within which the next burst of console records still belongs to a paste.
PASTE_GAP = 0.05


def console_input():
    """The terminal's keys for the chat. On Windows the console's key records, so that every
    modifier arrives; elsewhere the terminal's bytes through a Translator."""
    if sys.platform != "win32":
        return _posix_input()
    from prompt_toolkit.input.win32 import Win32Input

    found = Win32Input()
    found._use_virtual_terminal_input = False
    found.console_input_reader = _reader()
    return found


def _posix_input():
    from prompt_toolkit.input.vt100 import Vt100Input

    class Input(Vt100Input):
        def __init__(self, stdin):
            super().__init__(stdin)
            self.translator = Translator()

        def read_keys(self):
            self.vt100_parser.feed(self.translator.feed(self.stdin_reader.read()))
            result, self._buffer = self._buffer, []
            return result

        def flush_keys(self):
            rest = self.translator.flush()
            if rest:
                self.vt100_parser.feed(rest)
            return super().flush_keys()

    return Input(sys.stdin)


def record_key(virtual_key: int, ctrl: bool, shift: bool) -> str | None:
    """The keystroke of a console key record that prompt_toolkit's reader does not tell from
    another (Enter with Ctrl or Shift, Ctrl+Backspace, Ctrl+Tab, Ctrl+Shift+letter); None for
    every other record."""
    modifiers = [name for name, held in (("ctrl", ctrl), ("shift", shift)) if held]
    if virtual_key == 13 and modifiers:
        return "+".join(modifiers + ["enter"])
    if virtual_key == 8 and ctrl:  # the record's character is plain Backspace's
        return "+".join(modifiers + ["backspace"])
    if virtual_key == 9 and ctrl:
        return "+".join(modifiers + ["tab"])
    if ctrl and shift and 0x41 <= virtual_key <= 0x5A:
        return f"ctrl+shift+{chr(virtual_key).lower()}"
    return None


def _reader():
    from prompt_toolkit.input.win32 import ConsoleInputReader
    from prompt_toolkit.key_binding.key_processor import KeyPress
    from prompt_toolkit.keys import Keys

    class Reader(ConsoleInputReader):
        pasted = 0.0

        def _event_to_key_presses(self, ev):
            state = ev.ControlKeyState
            ctrl = bool(state & (self.LEFT_CTRL_PRESSED | self.RIGHT_CTRL_PRESSED))
            shift, alt = bool(state & self.SHIFT_PRESSED), bool(state & self.LEFT_ALT_PRESSED)
            found = record_key(ev.VirtualKeyCode, ctrl, shift)
            if found in bound:
                return [KeyPress(Keys.Escape, "")] * alt + [KeyPress(carrier(found), "")]
            if ev.VirtualKeyCode == 13 and ctrl:
                # Unbound: Enter, not the Escape Enter prompt_toolkit makes of Ctrl+Enter.
                return [KeyPress(Keys.ControlM, "\r")]
            if ev.VirtualKeyCode == 0x4A and ctrl and not shift and not alt:
                return [KeyPress(Keys.ControlJ, "\n")]  # Ctrl+J is its own key, not Ctrl+Enter
            return super()._event_to_key_presses(ev)

        def read(self):
            """The keys of the records that wait. A burst with a line break in it is what a
            terminal makes of a paste (each character a record, each line break an Enter):
            one BracketedPaste, so that pasted lines are never sent as messages."""
            from ctypes import pointer, windll
            from ctypes.wintypes import DWORD

            from prompt_toolkit.eventloop.win32 import wait_for_handles
            from prompt_toolkit.win32_types import INPUT_RECORD

            if not wait_for_handles([self.handle], timeout=0):
                return
            count, read = 2048, DWORD(0)
            records = (INPUT_RECORD * count)()
            windll.kernel32.ReadConsoleInputW(self.handle, pointer(records), count, pointer(read))
            yield from self.pasted_keys(list(self._merge_paired_surrogates(
                [self._insert_key_data(key) for key in self._get_keys(read, records)])))

        def pasted_keys(self, found: list, now=None) -> list:
            now = time.monotonic() if now is None else now
            text = {Keys.ControlJ: "\n", Keys.ControlM: "\n", Keys.ControlI: "\t"}

            def typed(key):
                return key.key in text or not isinstance(key.key, Keys) and key.key not in _carriers.values()

            breaks = sum(1 for key in found if key.key in (Keys.ControlJ, Keys.ControlM))
            letters = sum(1 for key in found if typed(key)) - breaks
            going_on = now - self.pasted < PASTE_GAP and any(typed(key) for key in found)
            if not (breaks and (letters or breaks > 1) or going_on):
                return found
            self.pasted = now
            out, run = [], []
            for key in found + [None]:
                if key is not None and typed(key):
                    run.append(text.get(key.key, key.data))
                    continue
                if run:
                    out.append(KeyPress(Keys.BracketedPaste, "".join(run)))
                    run = []
                if key is not None:
                    out.append(key)
            return out

    return Reader()
