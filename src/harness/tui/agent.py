"""The terminal chat on an agent identity's chats (the agent package's /api/agent routes on the
session host), so the terminal shows the same life as the app, the command line and Python:

    AgentChat       one chat of the identity shaped as the chat's conversation: records(stop)
                    follows its record, say() says into the identity's one queue, confirm()
                    answers an approval. Notices about its other chats come as "notice" records:
                    printed as lines starting with "—", never written into this chat's record.
                    What the host's conversation control gives (control.py) comes as records of
                    its own: "live_now" (the reply while it is written), "queue_now" (what waits).
    lines(record)   a record as styled lines (actions, the five outcomes, events, what it learned)
    details(records) the same records in full, for the transcript viewer
    calendar_view, channels_view, library_view, usage_lines
                    /calendar, /channels, /library and /usage (full screen, as views.py's)

Fixed text is English; what was said is shown as it was said."""
import asyncio
import json
import threading
import time
from urllib.parse import urlencode

from ..core import format as formats
from ..problems import Problem, lines as problem_lines
from . import control, views

# Records that are the life's own bookkeeping: not shown.
QUIET = {"queued", "wake_queued", "turn_started", "model_request", "model_reply", "model_cancelled", "compacted",
         "opened", "intention", "action_result", "dreamed", "approval_answer", "queue"}
# The mark of each of the five outcomes (and a request waiting), and its colour.
MARKS = {"done": ("✓", "green"), "refused": ("⊘", "#ff8700"), "failed": ("✗", "red"), "unknown": ("?", "yellow"),
         "cancelled": ("–", "dim"), "waiting": ("●", "#ff8700")}
EVIDENCE = {"builtin": "built in", "owner": "added by owner", "proposed": "proposed", "own_test": "own test",
            "replayed": "replayed", "effective": "effective", "archived": "archived", "undone": "undone"}
# How many records of its history a chat shows when it is opened.
HISTORY = 40
# Seconds between two reads of the chat's record: POLL when nothing happens, FAST while it
# works, so that the reply being written grows as it is written.
POLL = 0.5
FAST = 0.25
LOOK = 2.0


class Client:
    """The identity's /api/agent routes on the host."""

    def __init__(self, host, identity: str):
        self.host, self.identity = host, identity

    def get(self, name, **query):
        given = {key: value for key, value in {"identity": self.identity, **query}.items() if value not in (None, "")}
        return self.host.get(f"/api/agent/{name}?{urlencode(given)}")

    def post(self, name, body=None):
        return self.host.post(f"/api/agent/{name}", {"identity": self.identity, **(body or {})})


class AgentChat:
    """One chat of an identity, as the terminal chat's conversation."""

    run = None
    directory = None

    def __init__(self, host, identity: dict, chat: str = "main", title: str | None = None):
        self.host, self.identity, self.chat = host, identity, chat
        self.client = Client(host, identity["id"])
        self.title = title or ("Main conversation" if chat == "main" else chat)
        self.status = "IDLE"
        self.life = {}
        self.pending = {}  # code: the approval card that waits
        self.agent = {}
        self.live = None  # the reply being written (control.live)
        self.queue = {"held": False, "running": None, "queued": []}
        self.controls = True  # whether the host has the conversation control (control.py)
        self.wake = threading.Event()

    @property
    def session(self):
        return None

    def describe(self):
        self.life = self.client.get("life")
        return self.life

    def records(self, stop):
        """Its record from the last HISTORY shown records on, then as it grows; every LOOK seconds
        the life (working, spending) and the other chats (a notice for what is new there)."""
        rows = self.client.get("chat", chat=self.chat, after=0)["records"]
        try:
            self.client.post("opened", {"chat": self.chat})
        except Exception:
            pass
        after = rows[-1]["seq"] if rows else 0
        for row in rows:
            if row.get("event") == "approval":
                self._approval(row)
        shown = [row for row in rows if row.get("event") not in QUIET][-HISTORY:]
        # With them, the bookkeeping between them (the model's calls): not printed, in the transcript.
        first = shown[0]["seq"] if shown else 0
        shown = [row for row in rows if row["seq"] >= first]
        # What still waits for the owner, however far back it was asked.
        shown = [row for row in self.pending.values() if row not in shown] + shown
        for row in shown:
            yield {**row, "agent_chat": self.chat, "history": True}
        seen, looked = {}, 0.0
        first = True
        while not stop.is_set():
            if time.monotonic() - looked > LOOK:
                looked = time.monotonic()
                yield from self._look(seen, first)
                first = False
            answer = self.client.get("chat", chat=self.chat, after=after)
            for row in answer["records"]:
                after = max(after, int(row.get("seq") or 0))
                if row.get("event") == "approval":
                    self._approval(row)
                if row.get("event") == "turn_started":
                    self.status = "RUNNING"
                yield {**row, "agent_chat": self.chat}
            yield from self._control(answer)
            self.wake.wait(FAST if self.status == "RUNNING" or self.live or self.queue["queued"] else POLL)
            self.wake.clear()

    def _control(self, answer):
        """What the host's conversation control says now, as records when it changed: the
        reply being written, and what waits in the queue."""
        now = control.live(answer)
        if now != self.live:
            self.live = now
            yield {"event": "live_now", "live": now, "agent_chat": self.chat}
        if not self.controls:
            return
        try:
            found = control.queue(self.client, self.chat)
        except Problem as error:
            if not control.missing(error):
                raise
            self.controls = False  # a host from before it had a queue to show
            return
        before, self.queue = self.queue, found
        if found != before:
            yield {"event": "queue_now", "queue": found, "agent_chat": self.chat}
        # A turn runs from when the queue names it until it no longer does (a little after
        # its reply: the turn's own bookkeeping comes last).
        if bool(found["running"]) != bool(before["running"]):
            self.status = "RUNNING" if found["running"] else "IDLE"
            yield {"event": "agent_state", "status": self.status, "agent_chat": self.chat}

    def nudge(self):
        """Read the record again now (something was just said or changed)."""
        self.wake.set()

    def _approval(self, row):
        if row.get("state") == "waiting":
            self.pending[row["code"]] = row
        else:
            self.pending.pop(row.get("code"), None)

    def _look(self, seen, first):
        try:
            self.life = self.client.get("life")
            listed = self.client.get("chats")["chats"]
        except Exception:
            return
        busy = self.chat in (self.life.get("busy") or [])
        status = "RUNNING" if busy else "IDLE"
        if status != self.status:
            self.status = status
            yield {"event": "agent_state", "status": status, "agent_chat": self.chat}
        if first:
            # What waits elsewhere when the chat opens: one line.
            marked = [f"{row['title']} {row['unread']} new" for row in listed
                      if row["chat"] != self.chat and row.get("unread")]
            for row in listed:
                seen[row["chat"]] = (row.get("updated"), None)
            if marked:
                yield {"event": "notice", "agent_chat": self.chat, "text": " · ".join(marked[:4]) + " · /sessions"}
            return
        for row in listed:
            if row["chat"] == self.chat:
                continue
            updated, after = seen.get(row["chat"], (None, None))
            if updated == row.get("updated"):
                continue
            records = self.client.get("chat", chat=row["chat"], after=after or 0)["records"] if after is not None \
                else self.client.get("chat", chat=row["chat"], after=0)["records"][-20:]
            last = records[-1]["seq"] if records else after
            seen[row["chat"]] = (row.get("updated"), last)
            if after is None and updated is not None:
                records = [r for r in records if r.get("time", 0) >= updated]
            text = notice(row["title"], records)
            if text:
                yield {"event": "notice", "agent_chat": self.chat, "text": text[0], "style": text[1]}

    # What the chat does with it (terminal.COMMANDS' methods).

    def say(self, text):
        """The owner's words into the identity's queue ({"queued": id}); the record is read at once."""
        answer = self.client.post("say", {"chat": self.chat, "text": text})
        self.nudge()
        return answer

    def send(self, text, files=()):
        return self.say(message(text, files))

    def confirm(self, accept=True, reason=None, request_id=None, remember=None):
        code = request_id or (next(iter(self.pending)) if len(self.pending) == 1 else None)
        if code is None:
            raise ValueError("nothing waits for your approval here" if not self.pending else
                             "several requests wait: answer the one shown, or say its code (A7 approve)")
        answer = self.client.post("approvals", {"code": code, "accept": bool(accept), "reason": reason or ""})
        self.pending.pop(code, None)
        if answer.get("handled_elsewhere"):
            raise ValueError(f"{code} was handled elsewhere ({answer.get('state')})")
        return answer

    def close(self):
        raise ValueError("an identity's chat does not end: /clear starts another one, /exit leaves")

    def steer(self, text, files=()):
        raise ValueError("an identity's turn is not steered: send the message, it is queued for its next turn")

    terminal_input = steer


def message(text, files=()) -> str:
    """A message with the files that go with it, as the identity's chat is told it."""
    return text + "".join(f"\n(attached: {path})" for path in files)


def _text(value, limit=160) -> str:
    return " ".join(str(value or "").split())[:limit]


def notice(title, records):
    """One "—" line about what is new in another chat, or None: what needs the owner first."""
    shown = [r for r in records if r.get("event") not in QUIET]
    if not shown:
        return None
    for row in reversed(shown):
        if row.get("event") == "approval" and row.get("state") == "waiting":
            return f"— {title}: waits for you · {row['code']} {_text(row.get('what'), 80)}", "#ff8700"
    for row in reversed(shown):
        if row.get("event") == "outcome" and row.get("end") in ("refused", "failed", "unknown"):
            what = _text(row.get("reason") or row.get("summary"), 100)
            return f"— {title}: {row.get('verb')} {row['end']}" + (f" ({what})" if what else ""), MARKS[row["end"]][1]
    for row in reversed(shown):
        if row.get("event") == "learned":
            return f"— {title}: learned {row.get('name')} · {EVIDENCE.get(row.get('evidence'), row.get('evidence'))}", \
                "magenta"
    for row in reversed(shown):
        if row.get("event") == "event" and row.get("addressed"):
            data = row.get("data") or {}
            return f"— {title}: {data.get('name') or data.get('from') or 'someone'} named it: " \
                   f"{_text(data.get('text'), 80)}", "dim"
    messages = sum(1 for r in shown if r.get("event") == "event")
    replies = [r for r in shown if r.get("event") == "reply"]
    if replies:
        return f"— {title}: {_text(replies[-1].get('text'), 100)}", "dim"
    if messages:
        return f"— {title}: {messages} new " + ("event" if messages == 1 else "events"), "dim"
    return None


def lines(record) -> list:
    """A record of a chat as (text, style) lines; ("", "answer", text) for a reply in Markdown."""
    kind = record.get("event")
    if kind in QUIET or kind == "agent_state":
        return []
    if kind == "notice":
        return [(record["text"] if record["text"].startswith("—") else f"— {record['text']}",
                 record.get("style") or "dim")]
    if kind == "user":
        channel = f"  ({record['channel']})" if record.get("channel") else ""
        return [(f"› {record.get('text')}{channel}", "bold")]
    if kind == "reply":
        return [("answer", str(record.get("text") or ""))]
    if kind == "action":
        args = record.get("args") or {}
        what = record.get("goal") or args.get("text") or args.get("command") or ""
        target = f" {record['object']}" if record.get("object") else ""
        return [(f"▸ {record.get('verb')}{target}" + (f" · {_text(what, 100)}" if what else ""), "#5f87ff")]
    if kind == "outcome":
        end = record.get("end") or "unknown"
        mark, colour = MARKS.get(end, ("·", "dim"))
        why = _text(record.get("reason") or record.get("summary"), 120)
        return [(f"  {mark} {record.get('verb')} {end}" + (f" — {why}" if why else ""), colour)]
    if kind == "event":
        data = record.get("data") or {}
        who = data.get("name") or data.get("from")
        said = data.get("text") or data.get("value") or ""
        return [(f"◆ {record.get('place') or 'event'}  {record.get('kind')}"
                 + (f" · {who}" if who else "") + (f": {_text(said, 120)}" if said else ""), "yellow")]
    if kind == "reaction":
        return [(f"↳ tree: {record.get('about') or record.get('node')}" + (f" → {record['answer']}"
                                                                         if isinstance(record.get("answer"), str) else ""),
                 "dim")]
    if kind == "woken":
        return [(f"— woken: {', '.join(map(str, record.get('why') or [])) or 'something to think about'}", "dim")]
    if kind == "learned":
        what = record.get("kind")
        if what == "memory":
            return [(f"＋ noted  {record.get('name')} · {record.get('scope') or 'private'}", "magenta")]
        if what == "reaction":
            return [(f"＋ node  {record.get('under') or 'root'} › {record.get('name')} · "
                     f"{EVIDENCE.get(record.get('evidence'), record.get('evidence'))}", "magenta")]
        level = record.get("evidence")
        if level == "effective":
            return [(f"↑ effective  {record.get('name')}", "green")]
        if level == "undone":
            return [(f"undone  {record.get('name')} · no longer loaded", "#ff8700")]
        return [(f"＋ learned  {record.get('name')} · {EVIDENCE.get(level, level)}", "magenta")]
    if kind == "approval":
        state = record.get("state")
        if state == "waiting":
            where = f" · in {record['in_chat']}" if record.get("in_chat") else ""
            return [(f"● {record.get('what')} · {record.get('code')}{where}", "#ff8700")]
        return [(f"  {record.get('code')} {state}" + (f" · {record['reason']}" if record.get("reason") and
                                                     record.get("reason") != state else ""), "dim")]
    if kind in ("asleep", "spending_limit"):
        return [("— today's limit is reached: you still get answers; everything else waits for 0:00; reactions "
                 "keep running.", "#ff8700"), ("  /usage raise DOLLARS raises today's limit", "dim")]
    if kind == "awake":
        return [(f"— awake: {record.get('reason') or ''}", "dim")]
    if kind == "summary":
        return [("— summary", "dim")] + [(f"  {line}", "dim") for line in str(record.get("text") or "").splitlines()]
    if kind == "life":
        state = record.get("state")
        return [] if state == "started" else [(f"— {state}", "dim")]
    if kind == "calendar":
        entry = record.get("entry") or {}
        return [(f"＋ calendar  {entry.get('title')} · {formats.timestamp(entry.get('at'))}", "magenta")]
    if kind == "channel":
        if record.get("owner_code"):
            return [(f"— bind the owner of {record.get('account')}: from your own account, send "
                     f"{record['owner_code']} to it in a private chat", "#ff8700")]
        return []
    if kind == "error":
        # As every frontend says a failure: the reason, then what to do and where the log is.
        first, *rest = problem_lines(Problem.of(record, str(record.get("error") or "the turn failed")))
        return [(first, "red"), *[(f"  {line}", "dim") for line in rest]]
    if kind == "interrupted":
        why = _text(record.get("reason"), 120)
        return [("⎿  Interrupted" + (f" ({why})" if why and why != "stopped" else "")
                 + " · What should it do instead?", "dim")]
    if kind == "deferred":
        return [(f"— deferred: {_text(record.get('reason'), 120)}", "dim")]
    if kind == "done":
        return [(f"— done: {_text(record.get('note'), 120)}", "dim")] if record.get("note") else []
    return []


def approval_ask(record) -> dict:
    """What the chat asks for an approval card: what it is about to do, why that waits for
    the owner, and the two answers."""
    verb = record.get("verb")
    left = max(0, round((float(record.get("expires") or 0) - time.time()) / 60)) if record.get("expires") else None
    why = (f"It waits for you because it is a step of the kind \"{verb}\"" if verb else "It waits for you") \
        + f" · {record.get('code')}" + (f" · cancelled in {left} min if nobody answers" if left else "")
    return {"what": str(record.get("what") or ""), "why": why, "options": [("once", "Yes"), (None, "No")],
            "request_id": record.get("code")}


def details(records) -> list:
    """The records in full for the transcript viewer, as (starts a turn, lines): each with its
    time; a model call with its model, a reply with its tokens and cost, an action with all
    of its arguments, an outcome with what came back."""
    out = []
    for record in records:
        kind = record.get("event")
        if kind in ("agent_state", "notice", "live_now", "queue_now", "queued", "wake_queued", "opened", "queue"):
            continue
        when = time.strftime("%H:%M:%S", time.localtime(record["time"])) if record.get("time") else "--:--:--"
        rest = []
        if kind == "user":
            first, *rest = str(record.get("text") or "").splitlines() or [""]
            head = f"› {first}"
        elif kind == "turn_started":
            head = f"turn started ({record.get('whose') or 'owner'})"
        elif kind == "model_request":
            head = f"model call ({record.get('role') or 'dialogue'}) · {record.get('model') or 'model'} · " \
                   f"{len(record.get('messages') or ())} messages"
        elif kind == "model_reply":
            usage = record.get("usage") or {}
            cost = usage.get("cost_usd")
            head = f"model reply ({record.get('role') or 'dialogue'}) · {int(usage.get('input_tokens') or 0)} in · " \
                   f"{int(usage.get('output_tokens') or 0)} out tokens" + (f" · ${float(cost):.4f}" if cost else "")
            rest = str(record.get("text") or "").splitlines()
        elif kind == "reply":
            head, rest = "reply", str(record.get("text") or "").splitlines()
        elif kind in ("action", "action_result", "outcome"):
            head = " ".join(str(part) for part in (kind, record.get("verb"), record.get("object"), record.get("end"))
                            if part)
            body = {key: value for key, value in record.items()
                    if key in ("args", "goal", "reason", "summary", "data", "result", "place") and value not in (None, "", {})}
            rest = json.dumps(body, ensure_ascii=False, indent=2).splitlines() if body else []
        else:
            shown = [text for text, _ in lines(record) if text != "answer"]
            if shown:
                head, *rest = shown
            else:
                body = {key: value for key, value in record.items()
                        if key not in ("seq", "event", "time", "agent_chat", "history")}
                head = kind + (" " + json.dumps(body, ensure_ascii=False) if body else "")
        out.append((kind == "user", [f"{when}  {head}", *[f"          {line}" for line in rest]]))
    return out


def spend(life) -> str:
    if not life or life.get("spent_today") is None:
        return ""
    return f"${float(life['spent_today']):.2f} today / ${float(life.get('budget') or 0):.2f}"


# -- /usage -----------------------------------------------------------------------------------

def usage_lines(answer, titles=None) -> list:
    """Today's (and with week this week's) spending, by chat and by task, as /usage shows it."""
    titles = titles or {}
    today = answer.get("today") or {}
    spent, budget = float(today.get("cost_usd") or 0), float(today.get("daily_budget") or 0)
    filled = int(round(30 * min(1.0, spent / budget))) if budget else 0
    out = [("Usage · today " + str(today.get("date") or ""), "bold"), ("─" * 70, "dim"),
           (f"${spent:.2f} / ${budget:.2f}  " + "█" * filled + "░" * (30 - filled), ""),
           (f"on its own ${float(today.get('own_usd') or 0):.2f} · ${float(today.get('reserve') or 0):.2f} kept for "
            f"you · {today.get('unpriced_calls', 0)} of {today.get('daily_calls', 0)} calls without a price", "dim")]
    sources = today.get("by_source") or []
    for kind, label in (("chat", "by chat"), ("task", "by task")):
        rows = [row for row in sources if row.get("kind") == kind]
        if rows:
            out += [("", ""), (label, "dim")]
            top = max(float(row.get("cost_usd") or 0) for row in rows) or 1
            for row in rows:
                name = titles.get(row.get("id")) or row.get("title") or row.get("id") or kind
                cost = float(row.get("cost_usd") or 0)
                out.append((f"{str(name)[:26]:<26} {'█' * max(1, int(round(20 * cost / top))) if cost else '':<20} "
                            f"${cost:.2f}  {row.get('calls', 0)} calls", ""))
    if answer.get("week"):
        out += [("", ""), ("this week", "dim")]
        out += [(f"{day['date']}  ${float(day.get('cost_usd') or 0):.2f}  {day.get('calls', 0)} calls", "")
                for day in answer["week"]]
    return out


# -- /calendar --------------------------------------------------------------------------------

def _clock(seconds) -> str:
    return time.strftime("%H:%M", time.localtime(seconds))


def _day(seconds) -> str:
    return time.strftime("%a %m-%d", time.localtime(seconds))


def calendar_rows(week):
    """(rows, headers, entries): the week's lines as the prototype draws them, a day's name
    over its entries, what is next under "next"."""
    now = time.time()
    rows, headers, entries, day = [], [], [], None
    done = [e for e in week.get("entries") or () if not (e.get("planned") and e["start"] > now)]
    upcoming = [e for e in week.get("entries") or () if e.get("planned") and e["start"] > now]
    for entry in done:
        if _day(entry["start"]) != day:
            day = _day(entry["start"])
            headers.append(len(rows))
            rows.append(day)
            entries.append(None)
        rows.append(_calendar_row(entry))
        entries.append(entry)
    if upcoming:
        headers.append(len(rows))
        rows.append("next")
        entries.append(None)
        for entry in upcoming:
            rows.append(_calendar_row(entry, day=True))
            entries.append(entry)
    return rows, headers, entries


def _calendar_row(entry, day=False) -> str:
    kind, who = entry.get("kind"), entry.get("who")
    if kind == "asleep":
        mark, label, tail = "☾", "asleep", f"until {_clock(entry['end'])}"
    elif kind == "reaction":
        mark, label, tail = MARKS.get(entry.get("outcome") or "", ("·",))[0], "tree", entry.get("note") or ""
    elif entry.get("planned"):
        mark = "✓" if entry.get("outcome") == "done" else "·"
        label = "yours" if entry.get("by") == "owner" else "planned"
        tail = entry.get("kind") if entry.get("kind") not in ("task", None) else ""
    else:
        mark = MARKS["refused"][0] if entry.get("refused") else MARKS.get(entry.get("outcome") or "", ("·",))[0]
        label = {"owner": "yours", "tree": "tree", "own": "own"}.get(who, who or "")
        tail = " · ".join(p for p in (entry.get("outcome") if entry.get("outcome") not in (None, "done", "refused") else "",
                                      "safety refused" if entry.get("refused") else "", entry.get("note") or "") if p)
    when = f"{_day(entry['start'])[:3]} {_clock(entry['start'])}" if day else _clock(entry["start"])
    return f"{when:<9} {mark:<2} {label:<8} {str(entry.get('title') or '')[:48]:<48} {tail}"


async def calendar_view(client, note) -> None:
    """/calendar: the week; a add, x remove (what was planned), p pause or resume on its own,
    ← → the week before and after, Enter an entry's details."""
    offset = 0
    while True:
        start = _monday() + offset * 7 * 86400
        week = await asyncio.to_thread(client.get, "calendar", **{"from": _iso(start), "to": _iso(start + 7 * 86400)})
        usage = await asyncio.to_thread(client.get, "usage")
        today = usage.get("today") or {}
        rows, headers, entries = calendar_rows(week)
        top = (f"on its own ${float(today.get('own_usd') or 0):.2f} / "
               f"${float(today.get('daily_budget') or 0) - float(today.get('reserve') or 0):.2f} · "
               f"${float(today.get('reserve') or 0):.2f} kept for you"
               + (" · on its own: paused" if week.get("paused_own") else ""))
        picked = await views.browse(f"Calendar · {_day(start)} – {_day(start + 6 * 86400)}", rows, top=top,
                                    headers=headers, keys="axpn", back=True,
                                    hint="↑ ↓ move · Enter open · a add · x remove · p pause on its own · "
                                         "← n weeks · esc back")
        if picked is None:
            return
        key, index = picked
        entry = entries[index] if index is not None else None
        if key == "left":
            offset -= 1
        elif key == "n":
            offset += 1
        elif key == "p":
            await asyncio.to_thread(client.post, "calendar", {"action": "resume_own" if week.get("paused_own")
                                                              else "pause_own"})
        elif key == "a":
            title = await views.ask("What goes on the calendar", hint="Enter next · Esc cancel")
            if title:
                at = await views.ask("When (HH:MM, or 2026-11-27T09:00)", hint="Enter add · Esc cancel")
                if at:
                    try:
                        await asyncio.to_thread(client.post, "calendar", {"action": "add", "title": title, "at": at})
                    except Exception as error:
                        await views.read("Not added", str(error))
        elif key == "x" and entry is not None:
            if not entry.get("planned"):
                await views.read("Not removed", "Only what is planned can be removed; what happened stays.")
            else:
                await asyncio.to_thread(client.post, "calendar", {"action": "remove", "id": entry["id"]})
        elif key == "enter" and entry is not None:
            await views.read(str(entry.get("title")), "\n".join(
                f"{name:<9} {value}" for name, value in (
                    ("when", f"{formats.timestamp(entry['start'])} – {_clock(entry['end'])}"),
                    ("kind", entry.get("kind")), ("who", entry.get("who") or entry.get("by")),
                    ("outcome", entry.get("outcome") or "—"), ("refused", "yes" if entry.get("refused") else "no"),
                    ("chat", entry.get("chat") or "—"), ("place", entry.get("place") or "—"),
                    ("note", entry.get("note") or "—"), ("id", entry.get("id"))) if value is not None))


def _iso(seconds) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(seconds))


def _monday() -> float:
    now = time.localtime()
    midnight = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
    return midnight - now.tm_wday * 86400


# -- /channels --------------------------------------------------------------------------------

async def channels_view(client, note) -> None:
    """/channels: the accounts and pairing requests; a add (identity and policies first), Enter
    on a request approves it, g groups, o the owner's code, x remove."""
    while True:
        listed = (await asyncio.to_thread(client.get, "channels"))["channels"]
        rows, headers, items = [], [], []
        if listed:
            headers.append(0)
            rows.append(f"{'account':<10} {'state':<9} {'dm':<10} {'groups':<16} owner")
            items.append(None)
        for row in listed:
            rows.append(f"{row['account']:<10} {('online' if row['online'] else 'offline'):<9} {str(row.get('dm')):<10} "
                        f"{str(len(row.get('entered') or {})) + ' entered':<16} "
                        + (f"bound {row['owner']}" if row.get("owner") else "not bound"))
            items.append(("account", row))
        requests = [(row, request) for row in listed for request in row.get("pending") or ()]
        if requests:
            headers.append(len(rows))
            rows.append("pairing requests (Enter approves)")
            items.append(None)
            for row, request in requests:
                rows.append(f"{request['code']}  {row['account']} · {request.get('user')}"
                            + (f" ({request['name']})" if request.get("name") else "")
                            + f" · until {_clock(float(request.get('expires') or 0))}")
                items.append(("request", row, request))
        picked = await views.browse(f"Channels · {client.identity}", rows, headers=headers, keys="agox",
                                    hint="↑ ↓ move · Enter approve a request · a add · g groups · o owner code · "
                                         "x remove · esc back")
        if picked is None:
            return
        key, index = picked
        item = items[index] if index is not None else None
        try:
            if key == "a":
                await _channel_add(client, note)
            elif item is None:
                continue
            elif key == "enter" and item[0] == "request":
                answer = await asyncio.to_thread(client.post, "channels", {"action": "pair", "account": item[1]["account"],
                                                                           "code": item[2]["code"]})
                note(f"paired {(answer.get('result') or {}).get('user') or item[2].get('user')} · may ask it for "
                     "things in that private chat only")
            elif key == "x" and item[0] == "account":
                sure = await views.choose(f"Remove {item[1]['account']} from {client.identity}?", ["No", "Yes, remove it"])
                if sure == 1:
                    await asyncio.to_thread(client.post, "channels", {"action": "remove", "account": item[1]["account"]})
            elif key == "o" and item[0] == "account":
                answer = await asyncio.to_thread(client.post, "channels", {"action": "owner_code",
                                                                           "account": item[1]["account"]})
                note(f"Bind the owner: from your own account, send {(answer.get('result') or {}).get('code')} to it "
                     "in a private chat")
            elif key == "g" and item[0] == "account":
                await _channel_groups(client, item[1])
        except Exception as error:
            await views.read("Channels", str(error))


async def _channel_add(client, note):
    policies = ["pairing", "allowlist", "open", "off"]
    dm = await views.choose(f"Which identity answers on this account? {client.identity} (harness --identity picks "
                            "another). Private messages from strangers?", policies)
    if dm is None:
        return
    mode = await views.choose("In the groups you let it into, wake it", ["when named (mention)", "on every message (all)"])
    if mode is None:
        return
    onebot = await views.ask("The OneBot 11 implementation's WebSocket (it logs in to the QQ account)",
                             "ws://127.0.0.1:3001", hint="Enter add · Esc cancel")
    if not onebot:
        return
    answer = await asyncio.to_thread(client.post, "channels", {"action": "add", "kind": "qq", "dm": policies[dm],
                                                                "groups": ("mention", "all")[mode], "onebot": onebot})
    note(f"{answer.get('account')} added to {client.identity}: log in to the account in your OneBot 11 implementation "
         f"at {onebot}; then /channels: g groups, o binds the owner")


async def _channel_groups(client, row):
    found = (await asyncio.to_thread(client.get, "channels", account=row["account"]))["channels"]
    groups = (found[0].get("groups") if found else None) or []
    if not groups:
        await views.read("Groups", "The account is not online yet, or it is in no group.")
        return
    while True:
        picked = await views.choose("Let it into a group (none by default; Esc when done)",
                                    [f"{'[x]' if g.get('entered') else '[ ]'} {g.get('name') or g['id']} ({g['id']})"
                                     for g in groups])
        if picked is None:
            return
        await asyncio.to_thread(client.post, "channels", {"action": "groups", "account": row["account"],
                                                          "groups": [groups[picked]["id"]],
                                                          "mode": row.get("group_mode") or "mention"})
        groups[picked]["entered"] = row.get("group_mode") or "mention"


# -- /library ---------------------------------------------------------------------------------

async def library_view(client, note, libraries=None, group=None) -> None:
    """/library: three groups, skills, the tree of reactions (browsed level by level) and memory;
    then the shared libraries and this conversation's memory (views.library_view). `group`
    ("skills", "memory"): the group it opens on (/skills, /memory)."""
    while True:
        learned = await asyncio.to_thread(client.get, "learned")
        level = await asyncio.to_thread(client.get, "tree", path="")
        rows, headers, items = [], [], []
        headers.append(len(rows))
        rows.append("skills")
        items.append(None)
        for skill in learned.get("skills") or ():
            source = skill.get("source") or {}
            where = " · ".join(str(p) for p in (source.get("chat"), _when(source.get("time"))) if p)
            rows.append(f"{skill['name'][:34]:<34} {EVIDENCE.get(skill.get('evidence'), skill.get('evidence') or ''):<14} "
                        f"{str(skill.get('uses') or 0) + ' uses':<9} {where}")
            items.append(("skill", skill))
        total = sum(1 + (node.get("children") or 0) for node in level.get("nodes") or ())
        headers.append(len(rows))
        rows.append("tree of reactions")
        items.append(None)
        rows.append(f"▸ root{'':<28} {total} nodes")
        items.append(("tree",))
        headers.append(len(rows))
        rows.append("memory")
        items.append(None)
        for key, entry in sorted((learned.get("memory") or {}).items(), key=lambda kv: str(kv[1].get("updated") or "")):
            first = (entry.get("text") or key).strip().splitlines()[0] if (entry.get("text") or key).strip() else key
            scope = "this chat" if entry.get("scope") == "chat" else "private"
            where = " · ".join(p for p in (str(entry.get("chat") or entry.get("source") or ""), _when(entry.get("updated"))) if p)
            rows.append(f"{first[:34]:<34} {scope:<14} {where}")
            items.append(("memory", key, entry))
        headers.append(len(rows))
        rows.append("shared libraries (read only)")
        items.append(None)
        rows.append("▸ libraries and this conversation's memory")
        items.append(("libraries",))
        start = next((index + 1 for index in headers if rows[index] == group and index + 1 < len(rows)
                      and index + 1 not in headers), 0)
        group = None  # only where it opens
        picked = await views.browse(f"Library · {client.identity}", rows, headers=headers, keys="ud", current=start,
                                    hint="↑ ↓ move · Enter open · u undo a skill · d forget a memory · esc back")
        if picked is None:
            return
        key, index = picked
        item = items[index] if index is not None else None
        if item is None:
            continue
        try:
            if item[0] == "tree":
                await tree_view(client)
            elif item[0] == "libraries" and libraries is not None:
                await libraries()
            elif item[0] == "skill" and key in ("u", "enter"):
                if key == "enter":
                    again = await skill_view(item[1])
                    if not again:
                        continue
                await asyncio.to_thread(client.post, "learned", {"action": "undo", "name": item[1]["name"]})
                note(f"undone {item[1]['name']}: no longer loaded; the revision stays in history")
            elif item[0] == "memory" and key == "d":
                await asyncio.to_thread(client.post, "learned", {"action": "forget", "name": item[1]})
            elif item[0] == "memory":
                entry = item[2]
                await views.read(item[1], "\n".join([entry.get("text") or "", "",
                                                     f"scope   {'this chat' if entry.get('scope') == 'chat' else 'private'}",
                                                     f"source  {entry.get('source') or ''} {entry.get('chat') or ''}",
                                                     "private: your own places only · this chat: where it was written"]))
        except Exception as error:
            await views.read("Library", str(error))


def _when(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(value)))
    except (TypeError, ValueError):
        return str(value)[:16]


async def skill_view(skill) -> bool:
    """A skill: where it came from, its evidence and uses; True when the owner undoes it (u)."""
    source = skill.get("source") or {}
    text = "\n".join([f"source    {source.get('chat') or source.get('source') or '—'} · {_when(source.get('time'))}",
                      f"evidence  {EVIDENCE.get(skill.get('evidence'), skill.get('evidence'))}"
                      + (f" (history: {' → '.join(map(str, skill['history']))})" if skill.get("history") else ""),
                      f"uses      {skill.get('uses') or 0}" + (f" · success {skill['success_rate']:.0%}"
                                                              if isinstance(skill.get("success_rate"), (int, float)) else ""),
                      "", skill.get("description") or ""])
    picked = await views.browse(skill["name"], text.splitlines(), keys="u", headers=range(len(text.splitlines())),
                                hint="u undo · esc back")
    return bool(picked and picked[0] == "u")


def tree_rows(level):
    rows = []
    for number, node in enumerate(level.get("nodes") or (), 1):
        lit = "•" if node.get("lit") else " "
        label = node.get("about") or node["name"]
        if node.get("children"):
            rows.append(f"{lit}{number:>2}. ▸ {label[:56]:<56} {node['children']} nodes")
        else:
            off = " (disabled)" if not node.get("enabled", True) else ""
            rows.append(f"{lit}{number:>2}.   {label[:56]:<56} "
                        f"{EVIDENCE.get(node.get('evidence') or node.get('source'), node.get('evidence') or '')}{off}")
    return rows


async def tree_view(client) -> None:
    """The tree of reactions like a file manager: one level in order, the path on top; Enter
    opens a node with nodes under it, ← goes up; x disables or enables, m moves under another
    branch, u undoes a node the owner added or it learned (the three built-in ones can only be
    disabled)."""
    path, labels, at = [], [], 0
    while True:
        level = await asyncio.to_thread(client.get, "tree", path="/".join(path))
        nodes = level.get("nodes") or []
        picked = await views.browse("Library", tree_rows(level), top="› tree › " + " › ".join(["root", *labels]),
                                    current=at, keys="xmu", back=True,
                                    hint="↑ ↓ move · Enter open · ← up · m move under another branch · u undo · "
                                         "x disable · esc back")
        if picked is None:
            return
        key, index = picked
        node = nodes[index] if index is not None and index < len(nodes) else None
        at = index or 0
        try:
            if key == "left":
                if not path:
                    return
                path.pop()
                labels.pop()
                at = 0
            elif node is None:
                continue
            elif key == "enter" and node.get("children"):
                path.append(node["name"])
                labels.append(node.get("about") or node["name"])
                at = 0
            elif key == "enter":
                await views.read(node.get("about") or node["name"], "\n".join(
                    f"{name:<9} {value}" for name, value in (
                        ("name", node["name"]), ("when", node.get("when")), ("do", node.get("do")),
                        ("source", node.get("source")), ("evidence", EVIDENCE.get(node.get("evidence"), node.get("evidence"))),
                        ("uses", f"{node.get('uses') or 0} · {node.get('done') or 0} done"),
                        ("enabled", "yes" if node.get("enabled", True) else "no"),
                        ("last", formats.timestamp(node["last"]) if node.get("last") else "never"))))
            elif key == "x":
                await asyncio.to_thread(client.post, "tree", {"action": "disable" if node.get("enabled", True) else "enable",
                                                              "name": node["name"]})
            elif key == "u":
                if node.get("source") == "builtin":
                    await views.read("Not removed", "A built-in reaction can only be disabled (x).")
                else:
                    await asyncio.to_thread(client.post, "tree", {"action": "remove", "name": node["name"]})
            elif key == "m":
                under = await views.ask(f"Move {node['name']} under which node (its name; empty: the root)",
                                        hint="Enter move · Esc cancel")
                if under is not None:
                    await asyncio.to_thread(client.post, "tree", {"action": "move", "name": node["name"],
                                                                  "under": under.strip() or None})
        except Exception as error:
            await views.read("Tree of reactions", str(error))

