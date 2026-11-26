"""Editing the input box as Claude Code's does (interactive-mode page, "Text editing" and
"Word boundaries in editing shortcuts"; terminal-config page, "Paste large content").

Words: Alt+B, Alt+F, Alt+D, Alt+Backspace and Ctrl+Backspace take a word to be a run of
letters and digits, so `_`, `.` and `/` separate words; Ctrl+W deletes back to the previous
whitespace. In text written without spaces a run ends where the script changes (kanji to
kana, either to Latin); there is no dictionary here to cut such a run into its words.
What a word or line key deletes goes to the kill ring (the application's clipboard), which
Ctrl+Y pastes and Alt+Y cycles.

Rows: Up and Down move between the rows the input shows (a long line wraps into several)
before they walk the history; rows() cuts the text as the window does.

Chips: a paste of more than PASTE_LINES lines or PASTE_CHARACTERS characters shows as
`[Pasted text #1 +120 lines]`, an image from the clipboard as `[Image #1]`; the message
sent carries the whole text and the image's file (Attachments)."""

import re
import unicodedata

from prompt_toolkit.document import Document
from prompt_toolkit.utils import get_cwidth

PASTE_LINES, PASTE_CHARACTERS = 3, 800
CHIP = re.compile(r"\[(?:Pasted text #(\d+)(?: \+\d+ lines)?|Image #(\d+))\]")


def _kind(character: str) -> int:
    """0 between words; else which run of a word the character belongs to."""
    if not character.isalnum():
        return 0
    code = ord(character)
    if 0x3040 <= code <= 0x309F:
        return 2  # hiragana
    if 0x30A0 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF:
        return 3  # katakana
    if code >= 0x2E80 and unicodedata.east_asian_width(character) in "WF":
        return 4  # ideographs
    return 1


def word_start(text: str, position: int) -> int:
    """Where the word before `position` starts (Alt+B)."""
    while position > 0 and not _kind(text[position - 1]):
        position -= 1
    if position > 0:
        kind = _kind(text[position - 1])
        while position > 0 and _kind(text[position - 1]) == kind:
            position -= 1
    return position


def word_end(text: str, position: int) -> int:
    """Where the word at `position` ends, or the next one when between words (Alt+F)."""
    while position < len(text) and not _kind(text[position]):
        position += 1
    if position < len(text):
        kind = _kind(text[position])
        while position < len(text) and _kind(text[position]) == kind:
            position += 1
    return position


def _whole_chips(text: str, start: int, end: int) -> tuple[int, int]:
    """The range widened so that a chip it cuts into goes whole."""
    for chip in CHIP.finditer(text):
        if chip.start() < end and start < chip.end():
            start, end = min(start, chip.start()), max(end, chip.end())
    return start, end


def kill(buffer, clipboard, start: int, end: int) -> None:
    """Delete text[start:end] of the buffer (with every chip it cuts into) into the kill ring."""
    start, end = _whole_chips(buffer.text, *sorted((start, end)))
    if start == end:
        return
    text = buffer.text
    buffer.save_to_undo_stack()
    clipboard.set_text(text[start:end])
    buffer.set_document(Document(text[:start] + text[end:], start))


def backspace(buffer) -> None:
    """Backspace: one character, or the whole chip the cursor is right after."""
    text, at = buffer.text, buffer.cursor_position
    chip = next((found for found in CHIP.finditer(text) if found.start() < at <= found.end()), None)
    if chip is None:
        buffer.delete_before_cursor(1)
        return
    buffer.save_to_undo_stack()
    buffer.set_document(Document(text[:chip.start()] + text[chip.end():], chip.start()))


def rows(text: str, width: int) -> list[tuple[int, int]]:
    """The rows `text` shows in a box `width` cells wide: (start, end) of each in the text,
    a line break after a row that ends a line (it is not part of the row)."""
    out, start = [], 0
    for line in text.split("\n"):
        row, used = start, 0
        for index, character in enumerate(line, start):
            cells = get_cwidth(character)
            if used + cells > width and index > row:
                out.append((row, index))
                row, used = index, 0
            used += cells
        out.append((row, start + len(line)))
        start += len(line) + 1
    return out


def row_of(found: list, position: int) -> int:
    """Which of rows() the cursor is on (at a wrap it is on the row it starts)."""
    for index in range(len(found) - 1, -1, -1):
        if found[index][0] <= position:
            return index
    return 0


def vertical(buffer, width: int, step: int) -> bool:
    """Move the cursor one row up (step -1) or down (1) in the same column; False when it is
    on the first or the last row already."""
    text = buffer.text
    found = rows(text, max(width, 1))
    at = row_of(found, buffer.cursor_position)
    if not 0 <= at + step < len(found):
        return False
    column = get_cwidth(text[found[at][0]:buffer.cursor_position])
    start, end = found[at + step]
    position, used = start, 0
    while position < end and used + get_cwidth(text[position]) <= column:
        used += get_cwidth(text[position])
        position += 1
    buffer.cursor_position = position
    return True


class Attachments:
    """What the chips of a draft stand for: pasted texts and image files, by number."""

    def __init__(self):
        self.pastes, self.images = {}, {}

    def paste(self, text: str) -> str:
        """What a paste puts into the input: the text, or its chip when it is long."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.count("\n")
        if lines + 1 <= PASTE_LINES and len(text) <= PASTE_CHARACTERS:
            return text
        number = max(self.pastes, default=0) + 1
        self.pastes[number] = text
        return f"[Pasted text #{number} +{lines} lines]" if lines else f"[Pasted text #{number}]"

    def image(self, path) -> str:
        number = max(self.images, default=0) + 1
        self.images[number] = str(path)
        return f"[Image #{number}]"

    def kept(self, text: str) -> dict:
        """What the chips in `text` stand for, to keep with it (the history, a stash)."""
        pastes = {int(chip.group(1)): self.pastes[int(chip.group(1))] for chip in CHIP.finditer(text)
                  if chip.group(1) and int(chip.group(1)) in self.pastes}
        images = {int(chip.group(2)): self.images[int(chip.group(2))] for chip in CHIP.finditer(text)
                  if chip.group(2) and int(chip.group(2)) in self.images}
        return {**({"pastes": pastes} if pastes else {}), **({"images": images} if images else {})}

    def restore(self, kept: dict) -> None:
        """Know again what the chips of a recalled draft stand for."""
        self.pastes.update({int(number): text for number, text in (kept.get("pastes") or {}).items()})
        self.images.update({int(number): path for number, path in (kept.get("images") or {}).items()})

    def expand(self, text: str) -> tuple[str, list[str]]:
        """The message as it is sent: each paste chip replaced by its text, and the image
        files of the image chips (which stay in the text, as the places they were put)."""
        files = []

        def full(chip):
            if chip.group(1):
                return self.pastes.get(int(chip.group(1)), chip.group())
            path = self.images.get(int(chip.group(2)))
            if path and path not in files:
                files.append(path)
            return chip.group()

        return CHIP.sub(full, text), files
