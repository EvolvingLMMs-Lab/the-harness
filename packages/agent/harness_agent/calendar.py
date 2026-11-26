"""An identity's calendar: an ordinary calendar, mainly for seeing when it did what.

Two kinds of entries, shown together on a week:

    planned   what the owner or it put on it (calendar.json): goals, tasks, reminders, what
              it arranged for itself; `at` (and `until`), `repeat` "daily" or "weekly" or
              none, `by` owner or agent. An entry can be changed (update: its title, times,
              kind) and removed; a removed one is kept for a while and can be put back. When one comes due, the model is woken for it (the
              owner's on the reserve); one missed while the computer was off is taken up once
              after startup, for its latest time only.
    done      what happened (calendar-log.jsonl, one line each): every turn of a chat (who
              started it: the owner, the tree, or it on its own; what came of it: the last
              outcome; whether the safety layer refused something), each reaction of the tree,
              and when it was asleep.

When the owner changes or removes something it put there, it is remembered as a private
memory that shapes later decisions; so is "don't do this kind of thing" (said in a chat).
The first thing in the morning (after MORNING o'clock, once a day) is a summary of the
stretch: what it did, what it learned, what it spent and what waits for approval, recorded in
the main conversation and in DREAMS.md, the summary written for people to read."""
import json
import threading
import time
import uuid
from datetime import datetime, timedelta

from harness.sdk import Problem, atomic_write
from .chats import MAIN
from .state import read, save

KINDS = ("goal", "task", "reminder", "plan")
REPEATS = (None, "daily", "weekly")
MORNING = 6
# How many removed entries are kept to be put back.
REMOVED_KEPT = 50


def _time(value, now=None) -> float:
    """Seconds from a number, an ISO time, or HH:MM (today, or tomorrow when it has passed)."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    text = str(value).strip()
    if len(text) <= 5 and ":" in text:
        hour, minute = map(int, text.split(":"))
        now = now or time.time()
        moment = datetime.fromtimestamp(now).replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
        return moment if moment > now else moment + 86400
    return datetime.fromisoformat(text).timestamp()


def iso(seconds) -> str:
    return datetime.fromtimestamp(seconds).isoformat(timespec="minutes")


class Calendar:
    def __init__(self, life):
        self.life = life
        self.identity = life.identity
        self.path = self.identity.directory / "calendar.json"
        self.log_path = self.identity.directory / "calendar-log.jsonl"
        self.removed_path = self.identity.directory / "calendar-removed.json"
        self.entries = read(self.path, [])
        self._lock = threading.RLock()
        self.state = read(self.identity.directory / "calendar-state.json", {})
        if "morning" not in self.state:
            # The first summary is the next morning's.
            now = life.clock()
            self.state.update(morning=datetime.fromtimestamp(now).date().isoformat(), summarized=now)
            self._save_state()

    def _save(self) -> None:
        save(self.path, self.entries)

    def _save_state(self) -> None:
        save(self.identity.directory / "calendar-state.json", self.state)

    # Planned entries.

    def add(self, title, at, *, until=None, kind="task", repeat=None, by="owner", chat=None, note="") -> dict:
        if kind not in KINDS:
            raise ValueError(f"an entry's kind is one of {', '.join(KINDS)}")
        if repeat not in REPEATS:
            raise ValueError("repeat is daily, weekly or nothing")
        if not str(title or "").strip():
            raise ValueError("an entry needs a title")
        start = _time(at, self.life.clock())
        row = {"id": "c" + uuid.uuid4().hex[:8], "title": str(title).strip()[:200], "at": start,
               "until": _time(until) if until else None, "kind": kind, "repeat": repeat, "by": by,
               "chat": chat or MAIN, "note": str(note or "")[:500], "created": self.life.clock(), "done": None}
        with self._lock:
            self.entries.append(row)
            self._save()
        self.life.chats.record(chat or MAIN, "calendar", action="added", entry=row)
        return row

    def update(self, entry, *, by="owner", **changes) -> dict:
        """Change a planned entry: any of title, at, until (None: no end), kind, repeat, note.
        A new time makes it due again. When the owner moves something it planned itself, it
        remembers that."""
        unknown = set(changes) - {"title", "at", "until", "kind", "repeat", "note"}
        if unknown:
            raise Problem(f"an entry has no {sorted(unknown)[0]}", "what can change is title, at, until, kind, repeat "
                          "and note", code="calendar_field")
        with self._lock:
            kept = self._find(entry)
            before = kept["at"]
            row = dict(kept)   # nothing changes unless all of it checks
            if "title" in changes:
                if not str(changes["title"] or "").strip():
                    raise Problem("an entry needs a title", "give the new title", code="calendar_title")
                row["title"] = str(changes["title"]).strip()[:200]
            if "kind" in changes:
                if changes["kind"] not in KINDS:
                    raise Problem(f"an entry's kind is one of {', '.join(KINDS)}", f"not {changes['kind']!r}",
                                  code="calendar_kind")
                row["kind"] = changes["kind"]
            if "repeat" in changes:
                if changes["repeat"] not in REPEATS:
                    raise Problem("repeat is daily, weekly or nothing", f"not {changes['repeat']!r}", code="calendar_repeat")
                row["repeat"] = changes["repeat"]
            try:
                if changes.get("at") not in (None, ""):
                    row["at"], row["done"] = _time(changes["at"], self.life.clock()), None
                if "until" in changes:
                    row["until"] = _time(changes["until"]) if changes["until"] not in (None, "") else None
            except (ValueError, TypeError):
                raise Problem("a time is an ISO time (2026-11-26T15:00), HH:MM, or seconds",
                              f"not {changes.get('at') or changes.get('until')!r}", code="calendar_time") from None
            if row.get("until") is not None and row["until"] <= row["at"]:
                raise Problem("an entry ends after it starts", "give an end later than its start, or none",
                              code="calendar_time")
            if "note" in changes:
                row["note"] = str(changes["note"] or "")[:500]
            kept.update(row)
            row = kept
            self._save()
        if by == "owner" and row["by"] == "agent" and row["at"] != before:
            self._remember(f"calendar: {row['title']}", f"My owner moved \"{row['title']}\", which I had planned for "
                           f"{iso(before)}, to {iso(row['at'])}. Plan such things for times like that.")
        self.life.chats.record(row.get("chat") or MAIN, "calendar", action="changed", entry=row)
        return row

    def move(self, entry, at, *, until=None, by="owner") -> dict:
        return self.update(entry, by=by, at=at, **({"until": until} if until else {}))

    def remove(self, entry, *, by="owner") -> dict:
        """Take a planned entry off the calendar. It can be put back (restore)."""
        with self._lock:
            row = self._find(entry)
            self.entries.remove(row)
            self._save()
            removed = [*read(self.removed_path, []), {**row, "removed": self.life.clock(), "removed_by": by}]
            save(self.removed_path, removed[-REMOVED_KEPT:])
        if by == "owner" and row["by"] == "agent":
            self._remember(f"calendar: {row['title']}", f"My owner removed \"{row['title']}\", which I had put on my "
                           f"calendar for {iso(row['at'])}. Do not plan this kind of thing on my own again unless asked.")
        self.life.chats.record(row.get("chat") or MAIN, "calendar", action="removed", entry=row)
        return row

    def restore(self, entry=None) -> dict:
        """Put back an entry that was removed (`entry`: its id; None: the one removed last),
        as it was; what was remembered of its removal is forgotten."""
        with self._lock:
            removed = read(self.removed_path, [])
            row = next((r for r in reversed(removed) if entry in (None, r["id"])), None)
            if row is None:
                raise Problem("nothing was removed that can be put back" if entry is None else
                              f"no removed entry {entry!r}", "only the entries removed lately are kept", code="calendar_gone")
            save(self.removed_path, [r for r in removed if r is not row])
            by = row.pop("removed_by", None)
            row.pop("removed", None)
            self.entries.append(row)
            self._save()
        if by == "owner" and row["by"] == "agent":
            self._forget(f"calendar: {row['title']}")
        self.life.chats.record(row.get("chat") or MAIN, "calendar", action="restored", entry=row)
        return row

    def _find(self, entry) -> dict:
        row = next((r for r in self.entries if r["id"] == entry), None)
        if row is None:
            raise ValueError(f"no calendar entry {entry!r}")
        return row

    def _remember(self, key, text) -> None:
        identity = self.identity
        for _ in range(3):
            try:
                identity.remember(key[:160], text[:1200], source="calendar", expected=identity.memory()["revision"])
                return
            except ValueError:
                continue

    def _forget(self, key) -> None:
        identity = self.identity
        for _ in range(3):
            try:
                if key[:160] in identity.memory()["entries"]:
                    identity.remember(key[:160], None, source="calendar", expected=identity.memory()["revision"])
                return
            except ValueError:
                continue

    def due(self, now) -> list:
        """The planned entries due now: each once; a repeating one at its latest time."""
        found = []
        with self._lock:
            for row in self.entries:
                if row["at"] > now or (row.get("done") and not row.get("repeat")):
                    continue
                step = {"daily": 86400, "weekly": 7 * 86400}.get(row.get("repeat"))
                latest = row["at"]
                if step:
                    latest = row["at"] + int((now - row["at"]) // step) * step
                    if row.get("done") and row["done"] >= latest:
                        continue
                row["done"] = now
                found.append({**row, "due_at": latest})
            if found:
                self._save()
        return found

    # What happened.

    def log(self, **row) -> None:
        row = {"time": self.life.clock(), **row}
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def happened(self, start, end) -> list:
        rows = []
        if self.log_path.exists():
            for line in self.log_path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if start <= row.get("end", row["time"]) and row.get("start", row["time"]) <= end:
                    rows.append(row)
        return rows

    def week(self, start=None, end=None) -> dict:
        """Planned and done entries between start and end (default: this week, Monday first)."""
        now = self.life.clock()
        if start is None:
            day = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
            start = (day - timedelta(days=day.weekday())).timestamp()
        start = _time(start)
        end = _time(end) if end is not None else start + 7 * 86400
        planned = []
        for row in self.entries:
            step = {"daily": 86400, "weekly": 7 * 86400}.get(row.get("repeat"))
            # How long it lasts: to its end when it has one, else shown as half an hour.
            lasts = row["until"] - row["at"] if row.get("until") and row["until"] > row["at"] else 1800
            times = [row["at"]]
            if step:
                first = row["at"] + max(0, int((start - lasts - row["at"]) // step)) * step
                times = [t for t in (first + i * step for i in range(int((end - start + lasts) // step) + 2))
                         if t >= row["at"]]
            for at in times:
                if at < end and at + lasts > start:   # any part of it is in the stretch
                    planned.append({"id": row["id"], "title": row["title"], "start": at, "end": at + lasts,
                                    "has_end": bool(row.get("until")), "repeat": row.get("repeat"),
                                    "note": row.get("note") or "",
                                    "kind": row["kind"], "by": row["by"], "who": row["by"], "chat": row["chat"],
                                    "planned": True, "outcome": "done" if row.get("done") and row["done"] >= at else None})
        done = [{"id": f"log-{i}", "title": row.get("title") or row.get("what") or row.get("kind"),
                 "start": row.get("start", row["time"]), "end": row.get("end", row["time"] + 300),
                 "kind": row.get("kind", "record"), "by": "owner" if row.get("who") == "owner" else "agent",
                 "who": row.get("who"), "outcome": row.get("outcome"), "chat": row.get("chat"),
                 "place": row.get("place"), "refused": bool(row.get("refused")), "note": row.get("note")}
                for i, row in enumerate(self.happened(start, end))]
        return {"start": start, "end": end, "entries": sorted(planned + done, key=lambda r: r["start"]),
                "paused_own": self.life.paused_own}

    # The morning summary.

    def summary(self, since=None) -> dict:
        now = self.life.clock()
        since = since or self.state.get("summarized") or now - 86400
        rows = self.happened(since, now)
        did = [r for r in rows if r.get("kind") == "turn" and r.get("who") in ("own", "tree")]
        asked = [r for r in rows if r.get("kind") == "turn" and r.get("who") == "owner"]
        tree = [r for r in rows if r.get("kind") == "reaction"]
        refused = [r for r in rows if r.get("refused")]
        asleep = [r for r in rows if r.get("kind") == "asleep"]
        learned = []
        for chat in self.life.chats.ids():
            learned += [r for r in self.life.chats.read(chat) if r["event"] == "learned" and r["time"] >= since]
        spent = self.identity.account()
        days = {datetime.fromtimestamp(t).date().isoformat() for t in (since, now)}
        cost = sum(spent.day(day)["cost_usd"] for day in days)
        waiting = self.life.approvals.pending()
        lines = [f"Since {iso(since)}:"]
        lines.append(f"- On its own: {len(did)} " + ("thing" if len(did) == 1 else "things")
                     + (": " + "; ".join(f"{r.get('title')} ({r.get('outcome') or 'no outcome'})" for r in did[:8])
                        if did else ""))
        if asked:
            lines.append(f"- For you: {len(asked)} " + ("turn" if len(asked) == 1 else "turns"))
        if tree:
            lines.append(f"- The tree answered {len(tree)} " + ("time" if len(tree) == 1 else "times") + " without the model")
        if refused:
            lines.append(f"- Refused by the safety layer: {len(refused)}")
        if asleep:
            lines.append(f"- Asleep: " + ", ".join(f"{iso(r['start'])}–{iso(r['end'])}" for r in asleep))
        lines.append(f"- Learned: " + (", ".join(str(r.get("name")) for r in learned) if learned else "nothing new"))
        lines.append(f"- Spent: ${cost:.2f}")
        lines.append(f"- Waiting for your approval: " + (", ".join(f"{r['code']} {r['what']}" for r in waiting)
                                                         if waiting else "nothing"))
        unfinished = [r for r in did if r.get("outcome") in ("failed", "unknown", "cancelled", None)]
        if unfinished:
            lines.append("- Left unfinished: " + "; ".join(str(r.get("title")) for r in unfinished[:5]))
        return {"since": since, "text": "\n".join(lines), "did": did, "learned": [r.get("name") for r in learned],
                "spent": round(cost, 4), "waiting_approval": waiting}

    def morning(self, now) -> None:
        """Once a day, after MORNING o'clock: the summary into the main conversation and DREAMS.md."""
        today = datetime.fromtimestamp(now).date().isoformat()
        if datetime.fromtimestamp(now).hour < MORNING or self.state.get("morning") == today:
            return
        summary = self.summary()
        self.state.update(morning=today, summarized=now)
        self._save_state()
        self.life.chats.record(MAIN, "summary", text=summary["text"], since=summary["since"])
        dreams = self.identity.directory / "DREAMS.md"
        old = dreams.read_text(encoding="utf-8") if dreams.exists() else "# Dreams\n\n<!-- What it did and learned, " \
            "day by day, written for people to read. -->\n"
        atomic_write(dreams, old.rstrip("\n") + f"\n\n## {today}\n\n{summary['text']}\n")
