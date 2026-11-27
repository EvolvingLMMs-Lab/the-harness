"""/calendar: the identity's calendar in the terminal. What it holds is The Harness's own
(who did each thing: you, it on its own, its tree of reactions; how it ended; what the
safety layer refused; when it was asleep); the way it is used follows Google Calendar's
keyboard where a terminal can: d, w and m for the day, the week and the month, t for today,
n or j for the next stretch and p or k for the one before, c to create, Enter to open an
entry (and e to edit it), Delete or x to remove it, z to undo, / to search. o pauses and
resumes what it does on its own. An entry put at a time already past is "missed": it was
never due, so it is told apart from what was done, refused or failed.

Everything goes through the host's calendar route (add, update, remove, restore), the same
entries the app's page and `harness calendar` show."""

import asyncio
import time

from ..core import format as formats
from . import views
from .agent import MARKS

DAY = 86400
KINDS = ("task", "goal", "reminder", "plan")
REPEATS = ("", "daily", "weekdays", "weekly", "monthly")
KEYS = ["d", "w", "m", "t", "n", "j", "p", "k", "left", "right", "c", "a", "e", "x", "delete", "z", "o", "/"]
HINT = "d w m view · t today · n p next/before · c create · Enter open · e edit · x remove · z undo · / search · o its own work · esc"
MISSED = "◌"


def midnight(seconds: float) -> float:
    now = time.localtime(seconds)
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))


def span(mode: str, anchor: float) -> tuple[float, float]:
    """The stretch shown: the day of `anchor`, its week from Monday, or its month."""
    day = midnight(anchor)
    if mode == "day":
        return day, midnight(day + DAY + 7200)
    if mode == "week":
        start = midnight(day - time.localtime(day).tm_wday * DAY + 7200)
        return start, midnight(start + 7 * DAY + 7200)
    now = time.localtime(day)
    start = time.mktime((now.tm_year, now.tm_mon, 1, 0, 0, 0, 0, 0, -1))
    return start, time.mktime((now.tm_year + (now.tm_mon == 12), now.tm_mon % 12 + 1, 1, 0, 0, 0, 0, 0, -1))


def moved(mode: str, anchor: float, step: int) -> float:
    """The anchor of the stretch `step` after (or before) the one of `anchor`."""
    start, end = span(mode, anchor)
    return end + 7200 if step > 0 else start - 7200


def iso(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(seconds))


def clock(seconds: float) -> str:
    return time.strftime("%H:%M", time.localtime(seconds))


def day_name(seconds: float, now=None) -> str:
    name = time.strftime("%a %m-%d", time.localtime(seconds))
    return name + (" · today" if midnight(seconds) == midnight(time.time() if now is None else now) else "")


def entry_row(entry: dict) -> str:
    """One entry: when, how it ended, who put or did it, what, and what else to know."""
    kind, who = entry.get("kind"), entry.get("who")
    if kind == "asleep":
        mark, label, tail = "☾", "asleep", f"until {clock(entry['end'])}"
    elif kind == "reaction":
        mark, label, tail = MARKS.get(entry.get("outcome") or "", ("·",))[0], "tree", entry.get("note") or ""
    elif entry.get("planned"):
        missed = entry.get("missed") or entry.get("outcome") == "missed"
        mark = MISSED if missed else "✓" if entry.get("outcome") == "done" else "·"
        label = "yours" if entry.get("by") == "owner" else "its own"
        tail = " · ".join(part for part in ("missed: put at a time already past" if missed else "",
                                           kind if kind not in ("task", None) else "", entry.get("repeat") or "") if part)
    else:
        mark = MARKS["refused"][0] if entry.get("refused") else MARKS.get(entry.get("outcome") or "", ("·",))[0]
        label = {"owner": "yours", "tree": "tree", "own": "its own"}.get(who, who or "")
        tail = " · ".join(part for part in (entry.get("outcome") if entry.get("outcome") not in (None, "done", "refused") else "",
                                           "safety refused" if entry.get("refused") else "", entry.get("note") or "") if part)
    when = clock(entry["start"]) + (f"–{clock(entry['end'])}" if entry.get("has_end") or kind == "asleep" else "")
    title = " ".join(str(entry.get("title") or "").split())  # one line, whatever it was given as
    return f"{when:<12} {mark:<2} {label:<8} {title[:46]:<46} {tail}"


def rows(entries, mode: str, start: float, end: float, now=None):
    """(rows, headers, items) of a stretch: for a day or a week each day's name over its
    entries in the order of their time; for a month a row for every day with what is on it
    (items: the entry of a row, or ("day", its midnight))."""
    out, headers, items = [], [], []
    by_day = {}
    for entry in sorted(entries or (), key=lambda entry: entry["start"]):
        by_day.setdefault(midnight(max(entry["start"], start)), []).append(entry)
    if mode == "month":
        day = start
        while day < end:
            found = by_day.get(day, [])
            done = sum(1 for e in found if not e.get("planned") and e.get("kind") not in ("asleep",) and not e.get("refused"))
            missed = sum(1 for e in found if e.get("missed") or e.get("outcome") == "missed")
            planned = sum(1 for e in found if e.get("planned")) - missed
            parts = [f"{done} done" if done else "", f"{sum(1 for e in found if e.get('refused'))} refused"
                     if any(e.get("refused") for e in found) else "",
                     f"{planned} planned" if planned > 0 else "", f"{missed} missed" if missed else "",
                     "asleep a while" if any(e.get("kind") == "asleep" for e in found) else ""]
            first = next((str(e.get("title")) for e in found if e.get("planned")), "")
            out.append(f"{day_name(day, now):<20} {' · '.join(part for part in parts if part):<44} {first[:30]}")
            items.append(("day", day))
            day = midnight(day + DAY + 7200)
        return out, headers, items
    for day in sorted(by_day):
        headers.append(len(out))
        out.append(day_name(day, now))
        items.append(None)
        for entry in by_day[day]:
            out.append(entry_row(entry))
            items.append(entry)
    return out, headers, items


def details(entry: dict) -> str:
    return "\n".join(f"{name:<9} {value}" for name, value in (
        ("when", f"{formats.timestamp(entry['start'])} – {clock(entry['end'])}"), ("kind", entry.get("kind")),
        ("who", {"owner": "you", "tree": "its tree of reactions", "own": "it, on its own"}.get(
            entry.get("who") or entry.get("by"), entry.get("who") or entry.get("by"))),
        ("outcome", "missed: it was put at a time already past, so it was never due" if entry.get("missed")
         or entry.get("outcome") == "missed" else entry.get("outcome") or "—"),
        ("refused", "by the safety layer" if entry.get("refused") else "no"),
        ("repeats", entry.get("repeat") or "no"), ("chat", entry.get("chat") or "—"), ("place", entry.get("place") or "—"),
        ("note", entry.get("note") or "—"), ("id", entry.get("id"))) if value is not None)


async def _search(client):
    """/ in the calendar: entries whose title or note has the text (the host looks a year
    each way); the entry picked, to show its day, or None."""
    text = await views.ask("Search the calendar", hint="Enter search · Esc cancel")
    if not text or not text.strip():
        return None
    try:
        found = await asyncio.to_thread(client.get, "calendar", q=text.strip())
    except Exception as error:  # noqa: BLE001
        await views.failed("The calendar could not be searched", error)
        return None
    entries = sorted(found.get("entries") or (), key=lambda entry: entry["start"])
    listed = [f"{time.strftime('%Y-%m-%d', time.localtime(entry['start']))}  {entry_row(entry)}" for entry in entries]
    picked = await views.browse(f"Calendar · search · {text.strip()}", listed, hint="↑ ↓ move · Enter show its day · esc back",
                                empty=f"Nothing on the calendar has \"{text.strip()}\" in its title or note.")
    return entries[picked[1]] if picked and picked[1] is not None else None


async def calendar_view(client, note) -> None:
    mode, anchor, at, undo = "week", time.time(), None, []

    async def post(body):
        """A change of the calendar; what went wrong is shown, and False returned."""
        try:
            return await asyncio.to_thread(client.post, "calendar", body)
        except Exception as error:  # noqa: BLE001 - said in the view; the calendar is as it was
            await views.failed("The calendar was not changed", error)
            return None

    while True:
        start, end = span(mode, anchor)
        try:
            found = await asyncio.to_thread(client.get, "calendar", **{"from": iso(start), "to": iso(end)})
            today = (await asyncio.to_thread(client.get, "usage")).get("today") or {}
        except Exception as error:  # noqa: BLE001
            await views.failed("The calendar could not be read", error)
            return
        listed, headers, items = rows(found.get("entries"), mode, start, end)
        if at is None:  # today's row, where the stretch has one
            today_ = ("day", midnight(time.time()))
            at = next((index for index, item in enumerate(items) if item == today_ or isinstance(item, dict)
                       and midnight(item["start"]) == today_[1]), 0)
        budget = float(today.get("daily_budget") or 0)
        if budget > 0:
            own = budget - float(today.get("reserve") or 0)
            top = (f"on its own ${float(today.get('own_usd') or 0):.2f} of ${max(own, 0):.2f} · "
                   f"${float(today.get('reserve') or 0):.2f} kept for you")
        else:
            top = f"on its own ${float(today.get('own_usd') or 0):.2f} · no daily limit"
        if found.get("paused_own"):
            top += " · its own work is paused (o resumes it)"
        title = {"day": day_name(start), "week": f"{day_name(start)[:9]} – {day_name(end - DAY)[:9]}",
                 "month": time.strftime("%B %Y", time.localtime(start))}[mode]
        picked = await views.browse(f"Calendar · {mode} · {title}", listed, top=top, headers=headers, keys=KEYS,
                                    current=at, hint=HINT,
                                    empty=f"Nothing on the calendar this {mode}. c puts something on it.")
        if picked is None:
            return
        key, index = picked
        item = items[index] if index is not None else None
        entry = item if isinstance(item, dict) else None
        at = index or 0
        if key in ("d", "w", "m"):
            mode, at = {"d": "day", "w": "week", "m": "month"}[key], None
            if isinstance(item, tuple):
                anchor = item[1] + 7200
            elif entry is not None:
                anchor = entry["start"]
        elif key == "t":
            anchor, at = time.time(), None
        elif key in ("n", "j", "right"):
            anchor, at = moved(mode, anchor, 1), 0
        elif key in ("p", "k", "left"):
            anchor, at = moved(mode, anchor, -1), 0
        elif key == "o":
            await post({"action": "resume_own" if found.get("paused_own") else "pause_own"})
        elif key == "/":
            hit = await _search(client)
            if hit is not None:
                mode, anchor, at = "day", hit["start"], None
        elif key in ("c", "a"):
            day = item[1] if isinstance(item, tuple) else entry["start"] if entry else max(start, time.time())
            title_ = await views.ask("What goes on the calendar", hint="Enter next · Esc cancel")
            if not title_:
                continue
            when = await views.ask("When (2026-11-27T09:00, or HH:MM for the next such time)",
                                   time.strftime("%Y-%m-%dT%H:00", time.localtime(max(day, time.time()) + 3600)),
                                   hint="Enter next · Esc cancel")
            if not when:
                continue
            kind = await views.choose("What kind of thing", list(KINDS), hint="↑↓ move · Enter add · Esc cancel")
            if kind is None:
                continue
            answer = await post({"action": "add", "title": title_, "at": when.strip(), "kind": KINDS[kind]})
            if answer and answer.get("result"):
                undo.append(("remove", answer["result"]["id"], None))
        elif key == "enter" and isinstance(item, tuple):
            mode, anchor, at = "day", item[1] + 7200, 0
        elif entry is None:
            continue
        elif key == "enter" and not entry.get("planned"):
            await views.read(str(entry.get("title")), details(entry))
        elif key in ("enter", "e"):
            if not entry.get("planned") or str(entry.get("id", "")).startswith("log-"):
                await views.read("Not changed", "What happened stays as it is; only what is planned can be edited.")
                continue
            fields = [("title", "Title", str(entry.get("title") or "")), ("at", "Starts", iso(entry["start"])[:16]),
                      ("until", "Ends (empty: no end)", iso(entry["end"])[:16] if entry.get("has_end") else ""),
                      ("kind", "Kind", str(entry.get("kind") or "task")), ("repeat", "Repeats", str(entry.get("repeat") or "")),
                      ("note", "Note", str(entry.get("note") or ""))]
            which = await views.choose(str(entry.get("title")), [f"{label:<22} {value or '—'}" for _, label, value in fields],
                                       text=details(entry), hint="↑↓ move · Enter change · Esc back")
            if which is None:
                continue
            name, label, value = fields[which]
            if name in ("kind", "repeat"):
                options = KINDS if name == "kind" else REPEATS
                chosen = await views.choose(label, [option or "does not repeat" for option in options])
                new = None if chosen is None else options[chosen]
            else:
                new = await views.ask(label, value, hint="Enter save · Esc cancel")
            if new is None or new == value:
                continue
            answer = await post({"action": "update", "id": entry["id"], name: (new.strip() or None) if name == "until"
                                 else new.strip() if isinstance(new, str) else new})
            if answer:
                undo.append(("update", entry["id"], {name: value or None}))
        elif key in ("x", "delete"):
            if not entry.get("planned") or str(entry.get("id", "")).startswith("log-"):
                await views.read("Not removed", "Only what is planned can be removed; what happened stays.")
            elif await post({"action": "remove", "id": entry["id"]}):
                undo.append(("restore", entry["id"], None))
                note(f"removed {entry.get('title')} from the calendar · z in /calendar puts it back")
        elif key == "z":
            if not undo:
                await views.read("Nothing to undo", "Nothing was changed in this calendar view yet.")
                continue
            action, identifier, fields_ = undo.pop()
            await post({"action": action, "id": identifier, **(fields_ or {})})
