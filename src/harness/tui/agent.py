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

Its full-screen views are modules of their own: calendar.py, usage.py, connectors.py,
library.py, settings.py.

Fixed text is English; what was said is shown as it was said."""
import base64
import json
import mimetypes
from pathlib import Path
import threading
import time
from urllib.parse import urlencode

from ..core import format as formats
from ..problems import Problem, lines as problem_lines
from . import control

# Records that are the life's own bookkeeping: not shown.
QUIET = {"queued", "wake_queued", "turn_started", "model_request", "model_reply", "model_cancelled",
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
        self.mode = None
        self.meta = {}
        self.status = "IDLE"
        self.life = {}
        self.pending = {}  # code: the approval card that waits
        self.agent = {}
        self.live = None  # the reply being written (control.live)
        self.context = None  # the context in use at the last call (control.context)
        self.queue = {"held": False, "running": None, "queued": []}
        self.controls = True  # whether the host has the conversation control (control.py)
        self.wake = threading.Event()

    @property
    def session(self):
        return None

    def describe(self):
        self.life = self.client.get("life")
        return self.life

    def _sync_meta(self, meta) -> bool:
        if not isinstance(meta, dict):
            return False
        changed = False
        new_title = meta.get("title")
        if new_title and new_title != self.title and self.chat != "main":
            self.title = str(new_title)
            changed = True
        new_mode = meta.get("mode")
        if new_mode != self.mode:
            self.mode = new_mode
            changed = True
        if meta != self.meta:
            self.meta = dict(meta)
        return changed

    def records(self, stop):
        """Its record from the last HISTORY shown records on, then as it grows; every LOOK seconds
        the life (working, spending) and the other chats (a notice for what is new there)."""
        initial = self.client.get("chat", chat=self.chat, after=0)
        self._sync_meta(initial.get("meta"))
        rows = initial["records"]
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
        if self._sync_meta(answer.get("meta")):
            yield {"event": "meta_now", "meta": dict(self.meta), "title": self.title, "mode": self.mode,
                   "agent_chat": self.chat}
        now = control.live(answer)
        if now != self.live:
            self.live = now
            yield {"event": "live_now", "live": now, "agent_chat": self.chat}
        used = control.context(answer)
        if used is not None and used != self.context:
            self.context = used
            yield {"event": "context_now", "context": used, "agent_chat": self.chat}
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

    def say(self, text, files=()):
        """The owner's words into the identity's queue ({"queued": id}); the record is read at once."""
        body = {"chat": self.chat, "text": text}
        if files:
            body["files"] = list(files)
        answer = self.client.post("say", body)
        self.nudge()
        return answer

    def send(self, text, files=()):
        uploaded, fallback = [], []
        for raw in files or ():
            path = Path(str(raw)).expanduser()
            if not path.is_file():
                fallback.append(str(raw))
                continue
            try:
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                res = self.client.post("attach", {"chat": self.chat, "name": path.name, "type": mime, "data": encoded})
                if isinstance(res, dict) and res.get("id"):
                    uploaded.append(res["id"])
                else:
                    fallback.append(str(raw))
            except Exception:
                fallback.append(str(raw))
        return self.say(message(text, fallback), files=uploaded)

    def confirm(self, accept=True, reason=None, request_id=None, remember=None):
        code = request_id or (next(iter(self.pending)) if len(self.pending) == 1 else None)
        if code is None:
            raise ValueError("nothing waits for your approval here" if not self.pending else
                             "several requests wait: answer the one shown, or say its code (A7 approve)")
        scope = "session" if remember == "session" else "once"
        answer = self.client.post("approvals", {"code": code, "accept": bool(accept), "reason": reason or "",
                                                "scope": scope})
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
                 "keep running.", "#ff8700"), (f"  {record.get('fix') or '/usage raise DOLLARS raises today' + chr(39) + 's limit'}", "dim")]
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
        # What its channel's package says to do with the code (the package's own words).
        said = record.get("text")
        said = said.get("en") if isinstance(said, dict) else said
        if record.get("owner_code"):
            return [(f"— bind the owner of {record.get('account')}: {said or 'send it this code from your own account'} · "
                     f"{record['owner_code']}", "#ff8700")]
        pairing = record.get("pairing")
        if isinstance(pairing, dict):
            return [(f"— {pairing.get('name') or pairing.get('user')} asks to talk to {record.get('account')} · code "
                     f"{pairing.get('code')} · /channels answers", "#ff8700")]
        return []
    if kind == "error":
        # As every frontend says a failure: the reason, then what to do and where the log is.
        first, *rest = problem_lines(Problem.of(record, str(record.get("error") or "the turn failed")))
        return [(first, "red"), *[(f"  {line}", "dim") for line in rest]]
    if kind == "artifact":
        name = str(record.get("name") or "artifact.md")
        title = str(record.get("title") or name)
        summary = _text(record.get("summary"), 120)
        suffix = " · awaiting approval" if record.get("request_approval") else ""
        out = [(f"📄 artifact  {title} ({name}){suffix}", "cyan")]
        if summary:
            out.append((f"  {summary}", "dim"))
        out.append((f"  /artifacts {name} to read", "dim"))
        return out
    if kind == "task_step":
        step_kind = record.get("kind") or "status"
        if step_kind == "think":
            return []
        if step_kind == "cell":
            num = f"#{record['number']} " if record.get("number") is not None else ""
            code = _text(record.get("code") or "run cell", 90)
            ok = record.get("status") in (None, "ok", "finished")
            return [(f"  {'✓' if ok else '✗'} {num}{code}", "dim" if ok else "red")]
        if step_kind == "skill":
            ok = record.get("ok") is not False
            return [(f"  {'✓' if ok else '✗'} {_text(record.get('label') or 'skill', 90)}", "dim" if ok else "red")]
        if step_kind == "error":
            return [(f"  ✗ {_text(record.get('label') or 'error', 100)}", "red")]
        label = _text(record.get("label"), 90)
        return [(f"  · {label}", "dim")] if label else []
    if kind == "interrupted":
        # What it had written when it was stopped stays on the screen (it is not what the model is told).
        why = _text(record.get("reason"), 120)
        written = [("answer", str(record["text"]))] if record.get("text") else []
        tail = " · Send \"Continue\" to resume from checkpoint" if record.get("resumable_run") else " · What should it do instead?"
        return [*written, ("⎿  Interrupted" + (f" ({why})" if why and why != "stopped" else "") + tail, "dim")]
    if kind == "compacted" and not record.get("history"):
        count = record.get("messages")
        return [("— compacted: " + (f"{count} earlier messages are" if count else "the earlier part is") + " now a summary", "dim")]
    if kind == "deferred":
        return [(f"— deferred: {_text(record.get('reason'), 120)}", "dim")]
    if kind == "done":
        return [(f"— done: {_text(record.get('note'), 120)}", "dim")] if record.get("note") else []
    return []


def approval_ask(record) -> dict:
    """What the chat asks for an approval card: what it is about to do, why that waits for
    the owner, and the three Claude Code / Desktop-aligned answers."""
    verb = record.get("verb")
    left = max(0, round((float(record.get("expires") or 0) - time.time()) / 60)) if record.get("expires") else None
    why = (f"It waits for you because it is a step of the kind \"{verb}\"" if verb else "It waits for you") \
        + f" · {record.get('code')}" + (f" · cancelled in {left} min if nobody answers" if left else "")
    return {"what": str(record.get("what") or ""), "why": why,
            "options": [("once", "Allow once"), ("session", "Allow for this session"), (None, "Deny")],
            "request_id": record.get("code")}


def details(records) -> list:
    """The records in full for the transcript viewer, as (starts a turn, lines): each with its
    time; a model call with its model, a reply with its tokens and cost, an action with all
    of its arguments, an outcome with what came back."""
    out = []
    for record in records:
        kind = record.get("event")
        if kind in ("agent_state", "notice", "live_now", "queue_now", "context_now", "queued", "wake_queued", "opened",
                    "queue"):
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
