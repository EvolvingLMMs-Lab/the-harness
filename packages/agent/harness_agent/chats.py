"""An identity's chats: the main conversation, one chat per place it is connected to, and
the chats started with "New chat". Each is a folder of sessions/ with the record of what
happened there (events.jsonl, one JSON object a line, numbered) and meta.json:

    kind      main (the owner's private chat with it, whatever the channel), place (one
              environment: a QQ group, a project folder, a browser, ...), new (one piece of
              work), earlier (a conversation of an earlier version: read only, continued
              as a new chat)
    place     the place a place chat belongs to, and `thing` inside it (a QQ group)
    title     what the list shows
    unread    records since the owner last opened it (the list marks it)
    waiting   what it waits for ("desktop": a single-body environment another chat uses;
              "approval"), or null

The record is the chat's whole history: what was said, events of its place, the tree's
reactions, actions and their outcomes, model calls. Frontends read it by number
(read(after=N)) and all see the same life."""
import json
import threading
import time
import uuid
from pathlib import Path

from harness.sdk import atomic_write
from .state import identifier, read, save

MAIN = "main"
KINDS = ("main", "place", "new", "earlier")
# Records the list does not count as new for the owner: the model's own bookkeeping.
QUIET = {"model_request", "model_reply", "wake_queued", "compacted", "opened", "intention", "turn_started"}


class Chats:
    """The chats of one identity (its sessions/ folder)."""

    def __init__(self, identity):
        self.identity = identity
        self.root = identity.directory / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._seq = {}
        self.ensure(MAIN, kind="main", title="Main conversation")

    # Which chats there are.

    def folder(self, chat) -> Path:
        return self.root / identifier(chat)

    def meta(self, chat) -> dict:
        folder = self.folder(chat)
        meta = read(folder / "meta.json", None)
        if meta is None:
            # A conversation of an earlier version (state.json, no meta): read only.
            state = read(folder / "state.json", {}) if (folder / "state.json").exists() else {}
            first = next((m.get("content") for m in state.get("messages") or () if m.get("role") == "user"), "")
            meta = {"kind": "earlier", "title": (str(first)[:60] or chat), "created": folder.stat().st_mtime,
                    "unread": 0, "waiting": None}
        return meta

    def ensure(self, chat, *, kind, title, place=None, thing=None) -> dict:
        """The chat `chat`, made with this kind, title and place when it is not there yet."""
        if kind not in KINDS:
            raise ValueError(f"a chat's kind is one of {', '.join(KINDS)}")
        with self._lock:
            folder = self.folder(chat)
            path = folder / "meta.json"
            if path.exists():
                return read(path, {})
            folder.mkdir(parents=True, exist_ok=True)
            meta = {"kind": kind, "title": title, "place": place, "thing": thing, "created": time.time(),
                    "unread": 0, "waiting": None}
            save(path, meta)
            return meta

    def new(self, title="New chat") -> str:
        """A chat for one piece of work, kept in the list afterwards."""
        chat = "chat-" + uuid.uuid4().hex[:10]
        self.ensure(chat, kind="new", title=title)
        return chat

    def update(self, chat, **values) -> dict:
        with self._lock:
            meta = self.meta(chat)
            meta.update(values)
            save(self.folder(chat) / "meta.json", meta)
            return meta

    def ids(self) -> list:
        return sorted(path.name for path in self.root.iterdir() if path.is_dir()
                      and ((path / "meta.json").exists() or (path / "state.json").exists()))

    def listing(self, busy=()) -> list:
        """The list: the main conversation first, then by the last record, newest first."""
        rows = []
        for chat in self.ids():
            meta = self.meta(chat)
            events = self.folder(chat) / "events.jsonl"
            updated = events.stat().st_mtime if events.exists() else meta.get("created", 0)
            rows.append({"chat": chat, "kind": meta.get("kind"), "title": meta.get("title") or chat,
                         "place": meta.get("place"), "thing": meta.get("thing"), "updated": updated,
                         "unread": int(meta.get("unread") or 0), "waiting": meta.get("waiting"),
                         "busy": chat in busy})
        rows.sort(key=lambda row: (row["chat"] != MAIN, -row["updated"]))
        return rows

    def find(self, place, thing=None):
        """The chat of `place` (and `thing` inside it), or None."""
        for chat in self.ids():
            meta = self.meta(chat)
            if meta.get("kind") == "place" and meta.get("place") == place and meta.get("thing") == thing:
                return chat
        return None

    # The record.

    def _next(self, chat) -> int:
        if chat not in self._seq:
            path = self.folder(chat) / "events.jsonl"
            last = 0
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        last = max(last, int(json.loads(line).get("seq") or 0))
                    except ValueError:
                        last += 1
            self._seq[chat] = last
        self._seq[chat] += 1
        return self._seq[chat]

    def record(self, chat, event, **data) -> dict:
        """Append one record to the chat (numbered) and mark it for the list."""
        with self._lock:
            row = {"seq": self._next(chat), "event": event, "time": time.time(), **data}
            folder = self.folder(chat)
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            if event not in QUIET and not data.get("from_owner"):
                meta = self.meta(chat)
                save(folder / "meta.json", {**meta, "unread": int(meta.get("unread") or 0) + 1})
            return row

    def read(self, chat, after=0, limit=500) -> list:
        path = self.folder(chat) / "events.jsonl"
        if not path.exists():
            return []
        rows = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a line cut off by a crash
            row.setdefault("seq", number)
            if row["seq"] > after:
                rows.append(row)
        return rows[-limit:]

    def opened(self, chat) -> None:
        """The owner looked at it: no longer marked."""
        self.update(chat, unread=0)


def write_meta(path, meta) -> None:
    atomic_write(path, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
