"""An identity's calendar: an ordinary calendar, mainly for seeing when it did what.

Two kinds of entries, shown together on a week:

    planned   what the owner or it put on it (calendar.json): goals, tasks, reminders, what
              it arranged for itself; `at` (and `until`), `repeat` "daily" or "weekly" or
              none, `by` owner or agent. When one comes due, the model is woken for it (the
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

from harness.sdk import atomic_write
from .chats import MAIN
from .state import read, save

KINDS = ("goal", "task", "reminder", "plan")
REPEATS = (None, "daily", "weekly")
MORNING = 6


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

    def move(self, entry, at, *, until=None, by="owner") -> dict:
        with self._lock:
            row = self._find(entry)
            before = row["at"]
            row["at"], row["done"] = _time(at), None
            if until:
                row["until"] = _time(until)
            self._save()
        if by == "owner" and row["by"] == "agent":
            self._remember(f"calendar: {row['title']}", f"My owner moved \"{row['title']}\", which I had planned for "
                           f"{iso(before)}, to {iso(row['at'])}. Plan such things for times like that.")
        return row

    def remove(self, entry, *, by="owner") -> None:
        with self._lock:
            row = self._find(entry)
            self.entries.remove(row)
            self._save()
        if by == "owner" and row["by"] == "agent":
            self._remember(f"calendar: {row['title']}", f"My owner removed \"{row['title']}\", which I had put on my "
                           f"calendar for {iso(row['at'])}. Do not plan this kind of thing on my own again unless asked.")

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
            times = [row["at"]]
            if step:
                first = row["at"] + max(0, int((start - row["at"]) // step)) * step
                times = [t for t in (first + i * step for i in range(int((end - start) // step) + 2)) if t >= row["at"]]
            for at in times:
                if start <= at < end:
                    planned.append({"id": row["id"], "title": row["title"], "start": at,
                                    "end": row["until"] if row.get("until") and not step else at + 1800,
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
