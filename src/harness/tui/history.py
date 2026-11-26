"""The messages typed before, as Claude Code keeps its command history (interactive-mode page,
"Command history"): one file for every directory (history.jsonl in the data folder, a line
per message with the directory it was typed in), Up and Down walk the messages of this
directory, earlier sessions included, the same message twice in a row is kept once, and
Ctrl+R searches the messages of every directory.

A draft cleared with Ctrl+C or Esc Esc comes back with Up: the ten last ones of this session
are walked with the history and gone when the chat closes ("Bring back a cleared draft").
What a message's chips stood for (a long paste, an image) is kept with it."""

import json
from pathlib import Path
import time

FILE = "history.jsonl"
# The history file of earlier versions (one list for every directory), read into FILE once.
OLD_FILE = "tui-history"
DRAFTS = 10


class History:
    def __init__(self, directory, cwd):
        self.file, self.cwd = Path(directory) / FILE, str(cwd)
        self.entries = self._read(Path(directory))
        self.drafts = []
        self.at = self.walked = self.saved = None

    def _read(self, directory: Path) -> list:
        old = directory / OLD_FILE
        if not self.file.exists() and old.is_file():
            self._convert(old)
        entries = []
        try:
            with self.file.open(encoding="utf-8") as lines:
                for line in lines:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                        entries.append(entry)
        except OSError:
            pass
        return entries

    def _convert(self, old: Path) -> None:
        """prompt_toolkit's history file ("# time" then "+line" for each line of a message)."""
        messages, lines = [], []
        try:
            text = old.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for line in [*text.splitlines(), ""]:
            if line.startswith("+"):
                lines.append(line[1:])
            elif lines:
                messages.append("\n".join(lines))
                lines = []
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with self.file.open("w", encoding="utf-8", newline="\n") as out:
                for message in messages:
                    out.write(json.dumps({"text": message, "time": 0, "cwd": ""}, ensure_ascii=False) + "\n")
            old.unlink()
        except OSError:
            pass

    def here(self) -> list:
        """What Up walks: this directory's messages and this session's cleared drafts, oldest first."""
        return sorted([entry for entry in self.entries if entry.get("cwd") == self.cwd] + self.drafts,
                      key=lambda entry: entry.get("time") or 0)

    def add(self, text: str, kept=None) -> None:
        """A message sent: kept, unless it is the one sent just before it here."""
        self.at = None
        if not text.strip():
            return
        last = next((entry for entry in reversed(self.entries) if entry.get("cwd") == self.cwd), None)
        if last is not None and last["text"] == text:
            return
        entry = {"text": text, "time": time.time(), "cwd": self.cwd, **(kept or {})}
        self.entries.append(entry)
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with self.file.open("a", encoding="utf-8", newline="\n") as out:
                out.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # a history that cannot be written is still walked in this session

    def draft(self, text: str, kept=None) -> None:
        """A draft that was cleared: Up brings it back, in this session."""
        self.at = None
        if text.strip():
            self.drafts = [*self.drafts, {"text": text, "time": time.time(), "cwd": self.cwd, **(kept or {})}][-DRAFTS:]

    # Walking with Up and Down.

    def previous(self, current: str):
        """The entry before the one shown (the newest first), None at the oldest."""
        if self.at is None:
            self.walked, self.saved = self.here(), current
            self.at = len(self.walked)
        if self.at == 0:
            return None
        self.at -= 1
        return self.walked[self.at]

    def next(self):
        """The entry after the one shown; past the newest, what was typed before walking."""
        if self.at is None:
            return None
        self.at += 1
        if self.at >= len(self.walked):
            self.at = None
            return {"text": self.saved or ""}
        return self.walked[self.at]

    def leave(self) -> None:
        self.at = None

    # Ctrl+R.

    def search(self, query: str, skip: int = 0):
        """The (skip+1)th newest different message with `query` in it, from every directory."""
        if not query:
            return None
        wanted, seen = query.lower(), set()
        for entry in sorted(self.entries + self.drafts, key=lambda entry: entry.get("time") or 0, reverse=True):
            text = entry["text"]
            in_paste = any(wanted in str(value).lower() for value in (entry.get("pastes") or {}).values())
            if (wanted in text.lower() or in_paste) and text not in seen:
                seen.add(text)
                if skip == 0:
                    return entry
                skip -= 1
        return None
