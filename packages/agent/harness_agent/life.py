"""The resident life of every identity, held by the session host (the agent package's
background service): an identity is not an app that opens and closes but a life that goes
on, which the terminal, the command line, the Python API, the app and chat channels all
attach to.

    Service      background(server): starts a Life for each identity, keeps the host up
                 while one is alive (keep_alive), closes them when the host stops.
    Life         one identity's life: its chats, the places it is connected to, one queue
                 of what comes in, one worker per chat. Every frontend's input joins the
                 same queue in arrival order.

What comes in goes into the record of its chat first. The owner's words are a turn of that
chat; what happens in a place is an event of the place's chat, and wakes the model only when
something there calls for thinking. Chats run their turns in parallel; within a chat one
turn at a time, the next waiting in the chat's queue. A place with one body (the desktop)
serves one chat at a time; the others wait for it, shown as waiting.

Pausing an identity: the model is not woken and no actions run; places stay connected and
events are recorded, handled after resuming. Quitting: actions in progress end as cancelled
where they can be cancelled and unknown where their outcome cannot be confirmed.

What answers an event is not fixed: the identity's tree of reactions (reactions.py) is judged
from its root whenever the world changes or a time comes, at no cost; a node answers at once
(a skill, stop, remind the owner, nothing) or wakes the model. The tree also wakes it, on
objective conditions, for what it wants to do itself coming due: an intention it left (at a
time, or once an event happens), something on the calendar, practice review noted, events
piling up in a place. Awake, it decides whether to do something and what; done thinking, it
leaves intentions and the conditions to wake for, and only the tree runs again.

The budget bounds this. agent.reserve of the daily budget is kept for the owner's matters;
its own work spends the rest, spread over the money and hours left today: with less left it
is woken less often. When the rest is gone it is asleep: only the tree runs, events are
recorded, the owner can still wake it on the reserve, and everything else waits for the
reset at 0:00, itself an event that wakes it for what piled up.

After a restart the life carries on from the record: what was queued and not done is queued
again (life-state.json), and events that waited are handled. Events older than
agent.stale_hours reach the model as one summary, so it judges which still deserve an answer
instead of answering old mentions one by one.

What waits in a chat is the owner's to change until its turn begins (queue, queue_change):
a message can be edited, removed, or sent now, ahead of the others. The turn in progress
can be stopped (stop): its model call is cut off and its task cancelled, what was done
stands, and the record says "interrupted". Stopped with `hold`, the owner's messages that
wait stay where they are until the queue is resumed. While the model writes a reply, what
it has written so far is in `live` for the frontends to show."""
import inspect
import json
import queue
import re
import threading
import time
import traceback

from harness.sdk import Problem, SpendingLimit
from datetime import date as Date, datetime
from . import channels as channels_module
from . import places as places_module
from .chats import MAIN, Chats
from .reactions import Tree
from . import safety
from .approvals import Approvals, parse as parse_code
from .calendar import Calendar
from .learning import Learning
from .session import Interrupted, Session
from .state import Identity, IdentityError, first, identities, read, save, release

# Seconds between the life's looks at time (what comes due, timeouts).
TICK_SECONDS = 1.0
# Events piling up in a place wake it for its own look once there are this many, or the
# oldest is this old.
PILE_COUNT, PILE_HOURS = 20, 4.0
# How many intentions it keeps.
INTENTIONS = 50


class Job:
    """One thing for a chat's worker: an owner's message, or a wake."""

    def __init__(self, kind, chat, **data):
        self.kind, self.chat, self.data = kind, chat, data
        self.id = data.pop("id", None) or f"{kind}-{time.time_ns()}"
        self.done = threading.Event()
        self.result = None
        self.started = None   # when its turn began

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "chat": self.chat, **self.data}


class Life:
    """One identity's life (see the module)."""

    def __init__(self, identity: Identity, *, connection=None, model=None, tasks=None, clock=time.time):
        self.identity = identity
        self.connection = connection          # the host (harness.sdk.Host) its tasks go to
        self.model_factory = model            # () -> ChatModel of this identity
        self.tasks_factory = tasks            # (place row or None) -> Tasks
        self.clock = clock
        self.chats = Chats(identity)
        self.state_path = identity.directory / "life-state.json"
        saved = read(self.state_path, {})
        self.paused = bool(saved.get("paused"))
        self.inbox = queue.Queue()
        self.places = {}
        self.channel_kinds = {}                # place -> what its channel declares (channels.py)
        self.logged_in = {}                    # channel account -> whether its login stands
        self.workers = {}
        self.sessions = {}
        self.busy = set()
        self.bodies = {}                       # single-body place -> lock
        self.closing = threading.Event()
        self.alive = False
        self._lock = threading.RLock()
        self._ready = threading.Condition(self._lock)   # a job may start, or the life closes
        self.queues = {}                       # chat -> the jobs that wait there, in order
        self.current = {}                      # chat -> the job whose turn runs there
        self.holding = set(saved.get("held") or ())   # chats whose queue the owner holds
        self.live = {}                         # chat -> the reply being written there
        # What was started when the host went down starts again: nothing of it is running.
        self._queued = {row["id"]: {key: value for key, value in row.items() if key != "started"}
                        for row in saved.get("queue") or []}
        self.waiting = {chat: list(rows) for chat, rows in (saved.get("waiting") or {}).items()}
        self.reply_to = {}
        self.tree = Tree(identity)
        self.intentions = read(identity.directory / "intentions.json", [])
        self.facts = {"owner_active": False}
        self.held = set()                      # situation nodes that hold now
        self.day = saved.get("day") or Date.fromtimestamp(self.clock()).isoformat()
        self.paused_own = bool(saved.get("paused_own"))
        self.asleep_since = saved.get("asleep_since")
        self.running = {}                      # chat -> the node whose answer runs there
        self.hooks = {}                        # what later parts add: skill, calendar...
        self.levels = {}                       # chat -> the authority of the turn running there
        self.approvals = Approvals(self)
        self.hooks["notify"] = lambda kind, title, body, **k: self.approvals.notify(kind, title, body, **k)
        self.calendar = Calendar(self)
        self.hooks["tick:calendar"] = self._calendar_due
        self.hooks["asleep"] = lambda since, until: self.calendar.log(kind="asleep", title="asleep", start=since,
                                                                      end=until, who="tree")
        self.hooks["action:calendar"] = self._calendar_action
        self.hooks["notes:calendar"] = self._calendar_notes
        self.review_model = None               # a ChatModel factory for review and dreaming (tests)
        self.learning = Learning(self)
        self.hooks["tick:learning"] = self.learning.tick
        self.hooks["notes:learning"] = self.learning.notes
        self.hooks["action:read_skill"] = lambda chat, request: {"skill": self.learning.read_skill(request.get("name"))}
        self.hooks["skill"] = self.run_skill

    # Starting and stopping.

    def start(self) -> None:
        self.identity.live()
        self.alive = True
        self.chats.record(MAIN, "life", state="started", paused=self.paused)
        for row in places_module.load(self.identity):
            self._open_place(row)
        threading.Thread(target=self._loop, name=f"life-{self.identity.id}", daemon=True).start()
        # What was queued and not done before a restart, in its order.
        for row in list(self._queued.values()):
            self._submit(Job(row["kind"], row["chat"], **{k: v for k, v in row.items() if k not in ("kind", "chat")}),
                         persist=False)
        for chat in list(self.waiting):
            if self.waiting[chat] and not self.paused:
                self.inbox.put(("route_waiting", chat))
        self._prune()

    def _prune(self) -> None:
        """Drop the raw records older than agent.keep_days (0: kept for good). What it learned
        and its summaries stay; an item whose record is gone shows it as expired."""
        try:
            days = float(self.identity.effective().get("agent.keep_days") or 0)
        except (ValueError, OSError):
            return
        if days <= 0:
            return
        for chat in self.chats.ids():
            if chat not in self.busy:
                self.chats.prune(chat, self.clock() - days * 86400)

    def _model(self, chat):
        """The model of a turn in `chat`: the chat's own (its `model`: an entry of the model
        list) when it has one, else the identity's as its settings stand now."""
        wanted = self.chats.meta(chat).get("model")
        if wanted and inspect.signature(self.model_factory).parameters:
            return self.model_factory(wanted)
        return self.model_factory()

    def _open_place(self, row) -> None:
        key = None
        try:
            from agent_space.identity import KeyPair  # the identity signs in a space as itself
            import base64

            stored = read(self.identity.root / ".keys" / f"{self.identity.id}.json", None)
            key = KeyPair(base64.b64decode(stored["seed"])) if stored else None
        except Exception:
            key = None
        place = places_module.open_place(row, self.tell, key=key, folder=str(self.identity.directory))
        self.places[row["id"]] = place
        if row.get("channel"):
            # The verbs and events of its channel, as the package that provides it declares them.
            self.channel_kinds[row["id"]] = channels_module.declared(row["channel"])
        if place.single_body:
            self.bodies[row["id"]] = threading.Lock()
        if row["kind"] != "space":
            self.chats.ensure(f"place-{row['id']}", kind="place", title=row.get("title") or row["id"], place=row["id"])
        place.start()

    def connect(self, kind, **fields) -> dict:
        """Connect a new place now (and from now on)."""
        row = places_module.add(self.identity, kind, **fields)
        self._open_place(row)
        return row

    def disconnect(self, place) -> None:
        found = self.places.pop(place, None)
        if found is not None:
            found.close()
        self.channel_kinds.pop(place, None)
        self.logged_in.pop(place, None)
        places_module.remove(self.identity, place)

    def reconnect(self, place, **changes) -> dict:
        """Connect a place again with `changes` to what is kept of it (a channel account
        whose settings changed: its space starts again and reads them)."""
        rows = places_module.load(self.identity)
        row = next((row for row in rows if row["id"] == place), None)
        if row is None:
            raise ValueError(f"no place {place!r}")
        row.update(changes)
        places_module.store(self.identity, rows)
        found = self.places.pop(place, None)
        if found is not None:
            found.close()
        self.logged_in.pop(place, None)
        self._open_place(row)
        return row

    def close(self, *, quitting=True) -> None:
        """Quit: actions in progress end as cancelled or unknown, then it stops."""
        self.closing.set()
        with self._ready:
            self._ready.notify_all()
        for chat, session in list(self.sessions.items()):
            pending = (getattr(session, "state", None) or {}).get("pending")
            if pending and pending.get("run") and chat in self.busy:
                try:
                    session.tasks.cancel(pending["run"])
                    self.chats.record(chat, "outcome", verb="task", run=pending["run"], end="cancelled",
                                      reason="the host quit")
                except Exception as error:
                    self.chats.record(chat, "outcome", verb="task", run=pending["run"], end="unknown",
                                      reason=f"the host quit and the task could not be confirmed stopped: {error}")
        for chat in list(self.busy):
            self.chats.record(chat, "interrupted", reason="the host quit")
        for place in self.places.values():
            place.close()
        self.chats.record(MAIN, "life", state="stopped")
        self.alive = False
        self._persist()
        release(self.identity)

    def pause(self) -> None:
        self.paused = True
        self._persist()
        self.chats.record(MAIN, "life", state="paused")

    def resume(self) -> None:
        self.paused = False
        self._persist()
        self.chats.record(MAIN, "life", state="resumed")
        for chat in list(self.waiting):
            self.inbox.put(("route_waiting", chat))

    def _persist(self) -> None:
        with self._lock:
            save(self.state_path, {"paused": self.paused, "queue": list(self._queued.values()),
                                   "held": sorted(self.holding),
                                   "waiting": {chat: rows for chat, rows in self.waiting.items() if rows},
                                   "day": self.day, "paused_own": self.paused_own,
                                   "asleep_since": self.asleep_since})

    def status(self) -> dict:
        spent = self.identity.account().day()
        return {"identity": self.identity.id, "name": self.identity.name, "alive": self.alive, "paused": self.paused,
                "paused_own": self.paused_own, "asleep": bool(self.asleep_since),
                "busy": sorted(self.busy), "places": [place.describe() for place in self.places.values()],
                "queued": len(self._queued), "held": sorted(self.holding),
                "spent_today": spent["cost_usd"], "budget": spent["daily_budget"],
                "intentions": len(self.intentions)}

    # What comes in.

    def say(self, chat, text, *, channel=None, wait=False, timeout=600):
        """The owner said `text` in `chat` (any frontend, or their private chat in a channel)."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("say something to the agent")
        if chat not in self.chats.ids():
            raise ValueError(f"no chat {chat!r}")
        job = Job("owner", chat, text=text, channel=channel, queued=self.clock())
        self._submit(job)
        if wait:
            job.done.wait(timeout)
            return job.result
        return {"queued": job.id, "chat": chat}

    def tell(self, place, entry) -> None:
        """What a place pushed (a space's record entry, a folder's change, an outcome)."""
        self.inbox.put(("event", place, entry))

    def _submit(self, job, persist=True) -> None:
        if persist:
            with self._lock:
                self._queued[job.id] = {**job.to_dict(), "queued": job.data.get("queued", self.clock())}
            self._persist()
        self.chats.record(job.chat, "wake_queued" if job.kind == "wake" else "queued", job=job.id)
        with self._ready:
            self.queues.setdefault(job.chat, []).append(job)
            worker = self.workers.get(job.chat)
            if worker is None or not worker.is_alive():
                worker = threading.Thread(target=self._work, args=(job.chat,), name=f"chat-{job.chat}", daemon=True)
                self.workers[job.chat] = worker
                worker.start()
            self._ready.notify_all()

    # What waits in a chat, and stopping what runs there.

    def _waiting_owner(self, chat) -> list:
        return [job for job in self.queues.get(chat) or () if job.kind == "owner"]

    def queue(self, chat) -> dict:
        """The owner's messages that wait in `chat`, in order, what runs there, and whether
        the queue is held."""
        self._chat(chat)
        with self._lock:
            job = self.current.get(chat)
            running = None
            if job is not None:
                text = job.data.get("text") if job.kind == "owner" else "; ".join(job.data.get("why") or [])
                running = {"id": job.id, "kind": job.kind, "text": text, "since": job.started}
            return {"chat": chat, "held": chat in self.holding, "running": running,
                    "queued": [{"id": job.id, "text": job.data.get("text"), "queued": job.data.get("queued")}
                               for job in self._waiting_owner(chat)]}

    def queue_change(self, chat, action, *, id=None, text=None) -> dict:
        """Change what waits in `chat`: edit (the text of `id`), remove (`id`), clear (all
        of them), send_now (stop the turn in progress and do `id` next), resume (a held
        queue goes on). The queue after it. A message whose turn began is no longer changed."""
        self._chat(chat)
        if action not in ("edit", "remove", "clear", "send_now", "resume"):
            raise Problem(f"no queue action {action!r}", "the actions are edit, remove, clear, send_now and resume",
                          code="no_action")
        stop = False
        with self._ready:
            waiting = self.queues.setdefault(chat, [])
            job = None
            if action in ("edit", "remove", "send_now"):
                job = next((found for found in waiting if found.id == id and found.kind == "owner"), None)
                if job is None:
                    running = self.current.get(chat)
                    if running is not None and running.id == id:
                        raise Problem("that message has already started", "stop the turn to interrupt it, then say "
                                      "what you want instead", code="started")
                    raise Problem(f"no message {id!r} waits in this chat", "the queue lists the ones that do",
                                  code="no_message")
            if action == "edit":
                if not isinstance(text, str) or not text.strip():
                    raise Problem("a message needs some text", "give the new text, or remove the message",
                                  code="no_text")
                job.data["text"] = text
                self._queued[job.id]["text"] = text
            elif action in ("remove", "clear"):
                for gone in ([job] if action == "remove" else self._waiting_owner(chat)):
                    waiting.remove(gone)
                    self._queued.pop(gone.id, None)
                    gone.result = {"removed": True, "chat": chat}
                    gone.done.set()
            elif action == "send_now":
                waiting.remove(job)
                waiting.insert(0, job)
                # The order is kept across a restart too.
                self._queued = {job.id: self._queued[job.id],
                                **{key: row for key, row in self._queued.items() if key != job.id}}
                self.holding.discard(chat)
                stop = True
            else:
                self.holding.discard(chat)
            if not self._waiting_owner(chat):
                self.holding.discard(chat)   # nothing left to hold
            self._ready.notify_all()
        self._persist()
        self.chats.record(chat, "queue", action=action, **({"job": id} if id else {}))
        if stop:
            self.stop(chat, "the owner sent another message now")
        return self.queue(chat)

    def stop(self, chat, why="the owner stopped it", *, hold=False) -> dict:
        """Stop the turn in progress in `chat`: the model call is cut off, a running task
        cancelled, an approval it waits for ends as cancelled; what was done stands and the
        record says "interrupted". With `hold`, the owner's messages that wait there stay
        until the queue is resumed (or one is sent now); without, the next one starts.
        {stopped: whether a turn was running, queued, held}."""
        self._chat(chat)
        with self._ready:
            job = self.current.get(chat)
            session = self.sessions.get(chat)
            waiting = len(self._waiting_owner(chat))
            if hold and waiting:
                self.holding.add(chat)
            held = chat in self.holding
        if hold and waiting:
            self._persist()
        if job is not None and session is not None:
            session.interrupt(why)
        return {"stopped": job is not None, "queued": waiting, "held": held}

    def stopping(self, chat):
        """Why the turn in `chat` is being stopped, or None."""
        return getattr(self.sessions.get(chat), "stopping", None) if chat in self.current else None

    def _chat(self, chat) -> str:
        if chat not in self.chats.ids():
            raise Problem(f"no chat {chat!r}", "the chats are listed by harness sessions", code="no_chat")
        return chat

    def chat_change(self, chat, action, *, title=None, model=None) -> None:
        """What the owner does to a chat in the list: rename (to `title`), pin, unpin,
        archive, unarchive, delete, and model (this chat uses the model list's entry `model`
        from its next turn on; None: the identity's again). The main conversation is neither
        archived nor deleted; the chat of a place goes when its place is disconnected, not
        before; nothing is deleted while a turn runs in it."""
        if action == "rename":
            self.chats.rename(chat, title)
        elif action == "model":
            if model:
                from harness.sdk import data, model_list

                try:
                    entry = model_list.select(data(), str(model), native=True)
                except ValueError as error:
                    raise Problem(str(error), "the model list has the entries (harness model, Settings > Model)",
                                  code="no_model") from None
                model = entry["id"] if entry else None
            self.chats.update(self._chat(chat), model=model or None)
        elif action in ("pin", "unpin"):
            self.chats.pin(chat, action == "pin")
        elif action in ("archive", "unarchive"):
            self.chats.archive(chat, action == "archive")
        elif action == "delete":
            meta = self.chats.meta(self._chat(chat))
            if meta.get("kind") == "place" and meta.get("place") in self.places:
                raise Problem(f"this chat is the place {meta.get('place')}, which is still connected",
                              "archive it, or disconnect the place first", code="place_chat")
            with self._ready:
                if chat in self.current or chat in self.busy:
                    raise Problem("a turn is running in this chat", "stop it first, then delete the chat",
                                  code="busy")
                for job in self.queues.pop(chat, []):
                    self._queued.pop(job.id, None)
                    job.result = {"removed": True, "chat": chat}
                    job.done.set()
                self.holding.discard(chat)
                self.sessions.pop(chat, None)
                self.waiting.pop(chat, None)
                self.live.pop(chat, None)
                self._ready.notify_all()
            self.chats.delete(chat)
            self._persist()
        else:
            raise Problem(f"no chat action {action!r}", "the actions are rename, pin, unpin, archive, unarchive, "
                          "delete and model", code="no_action")

    # The life's loop: events in order, and time.

    def _loop(self) -> None:
        while not self.closing.is_set():
            try:
                item = self.inbox.get(timeout=TICK_SECONDS)
            except queue.Empty:
                item = ("tick",)
            try:
                if item[0] == "event":
                    self._event(item[1], item[2])
                elif item[0] == "route_waiting":
                    self._route_waiting(item[1])
                else:
                    self._tick()
            except Exception:
                traceback.print_exc()

    def _chat_of(self, place, entry):
        """The chat an event of `place` belongs to: its place chat, the chat of the thing
        inside it (a group of a channel), or the main conversation for the owner's private chat."""
        data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        if place is None:
            return MAIN, {"others": False}   # the life's own events (an approval waiting)
        thing = data.get("chat")
        row = next((p.row for p in [self.places.get(place)] if p is not None), {"id": place, "title": place})
        if thing and str(thing).startswith("private:"):
            if data.get("owner"):
                return MAIN, {"channel": row.get("channel") or place, "others": False}
            title = f"{row.get('title') or place} · {data.get('name') or thing.split(':', 1)[1]}"
        elif thing:
            title = f"{row.get('title') or place} · {data.get('group_name') or thing.split(':', 1)[1]}"
        else:
            title = row.get("title") or place
        chat = self.chats.find(place, thing)
        if chat is None:
            chat = f"place-{place}" + (f"-{str(thing).replace(':', '-')}" if thing else "")
            self.chats.ensure(chat, kind="place", title=title, place=place, thing=thing)
        return chat, {"others": bool(thing and not str(thing).startswith("private:")) or bool(data.get("others"))}

    def _own(self, place, entry) -> bool:
        """Its own messages and what its own actions caused never trigger its reactions."""
        found = self.places.get(place)
        presence = getattr(found, "presence", None)
        return presence is not None and entry.get("source") == f"presence/{presence}"

    def _event(self, place, entry) -> None:
        kind = entry.get("type") or ""
        if kind.startswith("asp.") and kind != "asp.outcome":
            return
        data = entry.get("data") if isinstance(entry.get("data"), dict) else {"value": entry.get("data")}
        chat, how = self._chat_of(place, entry)
        own = self._own(place, entry)
        channel = self.channel_kinds.get(place) or {}
        if channel.get("owner") and kind == channel["owner"]["bound"] and place in self.places:
            # The owner's account in this channel: approvals reach their private chat there.
            rows = places_module.load(self.identity)
            for row in rows:
                if row["id"] == place:
                    row["owner"] = str(data.get("user"))
                    self.places[place].row["owner"] = row["owner"]
            places_module.store(self.identity, rows)
        expired = kind == "place.offline" and "login" in str(data.get("reason") or "").lower()
        if channel and kind == channel["login"]["online"]:
            expired = bool(self.logged_in.get(place)) and not data.get("online")
            self.logged_in[place] = bool(data.get("online"))
        if expired:
            self.approvals.notify("login", "A channel login expired", f"{place}: log in to it again", chat=chat)
        if channel.get("pairing") and kind == channel["pairing"]["requested"]:
            # A stranger asks to talk to it: the request is the owner's, in the main conversation.
            self.chats.record(MAIN, "channel", account=place, pairing={key: data.get(key) for key in
                                                                      ("user", "name", "code", "expires")})
        if kind == "asp.outcome" and entry.get("end") in ("failed", "unknown") and not own:
            self.approvals.notify("failed", f"{entry.get('verb')} ended {entry.get('end')}",
                                  str((data or {}).get("output") or entry.get("reason") or "")[-300:], chat=chat)
        if kind == "asp.outcome":
            row = self.chats.record(chat, "outcome", verb=entry.get("verb"), end=entry.get("end"),
                                    reason=entry.get("reason"), place=place, **({"data": data} if data else {}),
                                    **({"own": True} if own else {}))
        else:
            row = self.chats.record(chat, "event", kind=kind, place=place, data=data, source=entry.get("source"),
                                    addressed=bool(data.get("addressed")), **({"own": True} if own else {}))
        if own and kind != "asp.outcome":
            return
        if channel and kind == channel["messages"]["event"] and data.get("owner") and chat == MAIN:
            # The owner's private chat in a channel joins the main conversation.
            if self._answer_code(data.get("text") or "", place):
                return
            self.say(MAIN, data.get("text") or "", channel=self.places[place].row.get("channel"))
            self.reply_to[MAIN] = (place, data.get("message"))
            return
        event = {"seq": row["seq"], "time": row["time"], "kind": kind, "place": place, "data": data,
                 "addressed": bool(data.get("addressed")), "end": entry.get("end"), "verb": entry.get("verb"),
                 "own": own, "others": how.get("others")}
        self.waiting.setdefault(chat, []).append(event)
        self._persist()
        if not self.paused:
            self._route(chat, event)
            self._intentions_on(event)

    def _answer_code(self, text, place) -> bool:
        """A short code answering an approval ("A7 approve"): the channel side answers it
        through the approval interface; the model never judges it."""
        found = parse_code(text)
        if found is None:
            return False
        try:
            result = self.approvals.answer(found[0], found[1], by=f"channel {place}")
        except ValueError:
            return False
        self.chats.record(MAIN, "approval_answer", code=found[0], accept=found[1], channel=place,
                          handled_elsewhere=result["handled_elsewhere"])
        return True

    def _view(self, event=None) -> dict:
        busy = {self.chats.meta(chat).get("place") for chat in list(self.busy)}
        facts = {**self.facts, "asleep": bool(self.asleep_since), "paused": self.paused,
                 "hour": time.localtime(self.clock()).tm_hour,
                 "working_in": sorted({self.places[p].kind for p in busy if p in self.places})}
        return {"event": event, "facts": facts, "now": self.clock()}

    def _route(self, chat, event) -> None:
        """The tree, judged from its root on this event: the node that takes over answers it;
        when none does, it stays in the record (and counts toward a pile)."""
        if event.get("own"):
            return
        self._facts_from(event)
        taken = self.tree.judge(self._view(event))
        if taken is not None:
            self._answer(chat, taken, event)

    def _facts_from(self, event) -> None:
        """Facts a place tells by its events: the owner at the desktop, the battery."""
        data = event.get("data") or {}
        kind = event.get("kind") or ""
        if kind.endswith(("owner_input", "owner_active")):
            self.facts["owner_active"] = bool(data.get("active", True))
            self.facts["owner_seen"] = self.clock()
        if isinstance(data.get("battery"), (int, float)):
            self.facts["battery"] = data["battery"]

    def _answer(self, chat, taken, event=None) -> None:
        answer = taken.get("answer") or {}
        self.calendar.log(kind="reaction", title=taken.get("about") or taken["node"], who="tree", chat=chat,
                          node=taken["node"], outcome="done" if "wake" not in answer else None,
                          place=self.chats.meta(chat).get("place"))
        self.chats.record(chat, "reaction", node=taken["node"], about=taken.get("about"), answer=answer,
                          path=taken["path"], **({"event_seq": event["seq"]} if event and event.get("seq") else {}))
        # A node higher up interrupts what a lower one is doing.
        running = self.running.get(chat)
        if running is not None and taken["rank"] < running["rank"] and running.get("stop"):
            running["stop"]()
        if "wake" in answer:
            whose = "owner" if event and (event.get("data") or {}).get("owner") else "own"
            self.wake(chat, taken.get("about") or taken["node"], whose=whose, node=taken["node"])
        elif "stop" in answer:
            for busy in [chat] if chat != MAIN else list(self.busy):
                self.stop(busy, f"the reaction {taken['node']}")
            if "remind" in answer:
                self.remind(answer["remind"], chat=chat, node=taken["node"])
            self.tree.counted(taken["node"], True)
        elif "remind" in answer:
            self.remind(answer["remind"], chat=chat, node=taken["node"])
            self.tree.counted(taken["node"], True)
        elif "skill" in answer:
            runner = self.hooks.get("skill")
            if runner is None:
                self.chats.record(chat, "outcome", verb="skill", end="refused", reason=f"no skill {answer['skill']!r}")
            else:
                outcome = runner(chat, answer["skill"], answer.get("args") or {}, event, taken)
                self.tree.counted(taken["node"], (outcome or {}).get("end") == "done")
        else:
            self.tree.counted(taken["node"], True)

    def remind(self, text, *, chat=None, node=None, kind="reminder") -> None:
        """Remind the owner: in the main conversation (the list marks it)."""
        self.chats.record(MAIN, kind, text=text, **({"in_chat": chat} if chat else {}), **({"node": node} if node else {}))

    def _route_waiting(self, chat) -> None:
        for event in list(self.waiting.get(chat) or ()):
            self._route(chat, event)

    def wake(self, chat, why, *, whose="own", **data) -> None:
        """Wake the model for `chat` (once: a wake already queued for it takes this reason too).
        A chat that is gone (deleted since) is woken for in the main conversation."""
        if chat not in self.chats.ids():
            chat = MAIN
        with self._lock:
            for row in self._queued.values():
                if row["chat"] == chat and row["kind"] == "wake" and not row.get("started"):
                    if why not in row["why"]:
                        row["why"].append(why)
                    if whose == "owner":
                        row["whose"] = "owner"
                    self._persist()
                    return
        self._submit(Job("wake", chat, why=[why], whose=whose, queued=self.clock(), **data))

    # Time: what comes due.

    def _tick(self) -> None:
        now = self.clock()
        today = Date.fromtimestamp(now).isoformat()
        if today != self.day:
            self._reset(today)
        if self.paused:
            return
        self._sleep_check()
        # A situation node takes over when its situation comes, once each time it comes.
        taken = self.tree.judge_situation(self._view(), self.held)
        if taken is not None:
            self._answer(MAIN, taken)
        self._intentions_due(now)
        for name, hook in list(self.hooks.items()):
            if name.startswith("tick:"):
                hook(now)
        self._piles(now)

    def _reset(self, today) -> None:
        """0:00: the budget is new; asleep ends; what piled up wakes it."""
        self.day = today
        if self.asleep_since:
            self.chats.record(MAIN, "awake", since=self.asleep_since, reason="the daily budget was reset at 0:00")
            hook = self.hooks.get("asleep")
            if hook:
                hook(self.asleep_since, self.clock())
            self.asleep_since = None
        self.chats.record(MAIN, "event", kind="agent.reset", place=None, data={"date": today}, addressed=False)
        self._persist()
        for chat, events in list(self.waiting.items()):
            if events and any(e.get("deferred") for e in events):
                self.wake(chat, "what piled up while it was asleep", whose="own")
        hook = self.hooks.get("reset")
        if hook:
            hook(today)
        self._prune()

    def _sleep_check(self) -> None:
        """Asleep when the part of today's budget for its own work is gone."""
        spent = self.identity.account().day()
        gone = spent["cost_usd"] >= spent["daily_budget"] - spent.get("reserve", 0)
        if gone and not self.asleep_since:
            self.asleep_since = self.clock()
            self.chats.record(MAIN, "asleep", reason=f"${spent['cost_usd']:.2f} of ${spent['daily_budget']:.2f} spent; "
                              "only the tree runs until 0:00, and you can still wake it")
            notify = self.hooks.get("notify")
            if notify:
                notify("limit", "The daily limit is reached",
                       f"{self.identity.name} is asleep until 0:00; it still answers you.")
            self._persist()

    def may_wake(self, whose) -> str | None:
        """Why a wake for `whose` may not run now (it waits), or None. The owner's: on the
        reserve. Its own: not asleep, and within the pace of the money and hours left today."""
        if whose == "owner":
            return None
        spent = self.identity.account().day()
        left = spent["daily_budget"] - spent.get("reserve", 0) - spent["cost_usd"]
        if left <= 0:
            return "asleep"
        now = self.clock()
        midnight = datetime.combine(Date.fromtimestamp(now), datetime.min.time()).timestamp() + 86400
        pace = left / max(1.0, (midnight - now) / 3600)
        recent = sum(float(row.get("cost_usd") or 0) for row in self.identity.account().calls()
                     if row.get("time", 0) >= now - 3600 and (row.get("source") or {}).get("whose") == "own")
        return "pace" if recent >= pace else None

    def proactive_allows(self, purpose="act") -> bool:
        """Whether it may act on its own now (agent.proactive, pause on its own)."""
        mode = self.identity.settings().get("proactive", "on")
        if self.paused_own or mode == "off":
            return False
        return mode == "on" or purpose == "learn"

    def pause_own(self, on=True) -> None:
        self.paused_own = bool(on)
        self._persist()
        self.chats.record(MAIN, "life", state="own paused" if on else "own resumed")

    def intend(self, chat, request) -> dict:
        """What it wants to do later and when to be woken for it: at a time, after some
        minutes, or once an event of a kind happens."""
        what = str(request.get("what") or "").strip()
        if not what:
            return {"error": "intend needs what it wants to do"}
        when = {}
        if request.get("in_minutes") is not None:
            when["at"] = self.clock() + float(request["in_minutes"]) * 60
        elif request.get("at"):
            text = str(request["at"])
            try:
                if len(text) <= 5 and ":" in text:
                    hour, minute = map(int, text.split(":"))
                    moment = datetime.fromtimestamp(self.clock()).replace(hour=hour, minute=minute, second=0).timestamp()
                    when["at"] = moment if moment > self.clock() else moment + 86400
                else:
                    when["at"] = datetime.fromisoformat(text).timestamp()
            except ValueError:
                return {"error": "at is HH:MM or an ISO time"}
        if request.get("after_event"):
            when["after_event"] = str(request["after_event"])
        if not when:
            return {"error": "intend needs at, in_minutes or after_event"}
        row = {"id": f"i{time.time_ns() % 10**10}", "what": what, "chat": chat, **when, "created": self.clock()}
        self.intentions = [*self.intentions, row][-INTENTIONS:]
        save(self.identity.directory / "intentions.json", self.intentions)
        self.chats.record(chat, "intention", **row)
        hook = self.hooks.get("intended")
        if hook:
            hook(row)
        return {"intended": row}

    def _due(self, rows, reason) -> None:
        self.intentions = [row for row in self.intentions if row not in rows]
        save(self.identity.directory / "intentions.json", self.intentions)
        for row in rows:
            self.wake(row.get("chat") or MAIN, f"{reason}: {row['what']}", whose="own", intention=row["id"])

    def _intentions_due(self, now) -> None:
        due = [row for row in self.intentions if row.get("at") and row["at"] <= now]
        if due and self.proactive_allows():
            self._due(due, "intention due")

    def _intentions_on(self, event) -> None:
        """An intention that waits for an event of this kind comes due."""
        due = [row for row in self.intentions if row.get("after_event") in (event.get("kind"), event.get("verb"))]
        if due and self.proactive_allows():
            self._due(due, "intention due")

    def _piles(self, now) -> None:
        """Events piling up in a place it may look at on its own wake it."""
        if not self.proactive_allows():
            return
        for chat, events in list(self.waiting.items()):
            fresh = [e for e in events if not e.get("own") and not e.get("deferred") and not e.get("piled")]
            if not fresh:
                continue
            meta = self.chats.meta(chat)
            place = self.places.get(meta.get("place"))
            if place is None or places_module.proactive(self.identity, place.row) == "off":
                continue
            if len(fresh) >= PILE_COUNT or now - min(e["time"] for e in fresh) >= PILE_HOURS * 3600:
                for e in fresh:
                    e["piled"] = True
                self.wake(chat, f"{len(fresh)} new events piled up here", whose="own")

    # A chat's worker: one job at a time.

    def _session(self, chat):
        session = self.sessions.get(chat)
        if session is None:
            meta = self.chats.meta(chat)
            row = self.places.get(meta.get("place")).row if meta.get("place") in self.places else None
            place = None
            if meta.get("kind") == "place":
                found = self.places.get(meta.get("place"))
                verbs = {}
                if found is not None and hasattr(found, "vocabulary"):
                    try:
                        verbs = {name: verb.get("line") for name, verb in
                                 (found.vocabulary().get("verbs") or {}).items()}
                    except Exception:
                        verbs = {}
                place = {"id": meta.get("place"), "title": meta.get("title"), "thing": meta.get("thing"),
                         "verbs": verbs, "others": bool(meta.get("thing") and not str(meta["thing"]).startswith("private:"))}
            tasks = self.tasks_factory(row)
            if hasattr(tasks, "approval"):
                tasks.guard, tasks.approval = self.task_guard(chat, row)
                tasks.on_event = self.task_rows(chat)
            session = Session(self.identity, self._model(chat), tasks, session=chat,
                              chats=self.chats, place=place,
                              actor=(lambda verb, obj, args, chat=chat: self.act(chat, verb, obj, args)))
            session.notes = lambda chat=chat: self.notes(chat)
            session.on_live = lambda text, reasoning, chat=chat: self._live(chat, text, reasoning)
            if meta.get("kind") in ("main", "new"):
                session.tasks_for = lambda place, chat=chat: self._tasks_in(chat, place)
            session.extras = {"intend": lambda request, chat=chat: self.intend(chat, request),
                              "approve_send": lambda request, chat=chat: self.approve_send(chat, request),
                              "persona": lambda request, chat=chat: self.persona(chat, request),
                              "reaction": lambda request, chat=chat: self.owner_reaction(chat, request)}
            for name, hook in self.hooks.items():
                if name.startswith("action:"):
                    session.extras[name[7:]] = (lambda request, chat=chat, hook=hook: hook(chat, request))
            self.sessions[chat] = session
        return session

    def notes(self, chat) -> str:
        """What the model is told when woken, beside the chat: its budget and time today, its
        tree, its intentions, and how its thinking ends."""
        spent = self.identity.account().day()
        now = time.localtime(self.clock())
        lines = [WAKE.format(left=spent.get("own_left_usd", spent["left_usd"]), reserve=spent.get("reserve", 0),
                             hours=24 - now.tm_hour - now.tm_min / 60,
                             proactive=self.identity.settings().get("proactive", "on")
                             + (" (paused on its own)" if self.paused_own else "")),
                 "Your tree of reactions:\n" + self.tree.describe()]
        mine = [row for row in self.intentions if row.get("chat") == chat]
        if mine:
            lines.append("Intentions you left here: " + json.dumps(mine, ensure_ascii=False))
        for name, hook in list(self.hooks.items()):
            if name.startswith("notes:"):
                text = hook(chat)
                if text:
                    lines.append(text)
        if chat == MAIN and not (self.identity.directory / "named.json").exists():
            lines.append(FIRST_CHAT)
        if chat == MAIN or self.chats.meta(chat).get("kind") == "new":
            lines.append(OWNER_REACTION)
            lines.append("Places your owner connected (a task names one with \"place\"): " + json.dumps(
                [{"id": p.id, "kind": p.kind, "title": p.row.get("title"), "online": p.online}
                 for p in self.places.values()], ensure_ascii=False))
        return "\n\n".join(lines)

    def _tasks_in(self, chat, place):
        found = self.places.get(place)
        if found is None:
            raise ValueError(f"no place {place!r}; the places are {', '.join(self.places) or 'none'}")
        tasks = self.tasks_factory(found.row)
        if hasattr(tasks, "approval"):
            tasks.guard, tasks.approval = self.task_guard(chat, found.row)
            tasks.on_event = self.task_rows(chat)
        return tasks

    def persona(self, chat, request) -> dict:
        """What the owner said it should be called and be like: into IDENTITY.md and SOUL.md."""
        from harness.sdk import atomic_write

        if chat != MAIN or self.levels.get(chat) != "owner":
            return {"error": "only your owner, in the main conversation, decides your name and persona"}
        done = {}
        if str(request.get("name") or "").strip():
            self.identity.rename(str(request["name"]).strip())
            done["name"] = self.identity.name
        if str(request.get("soul") or "").strip():
            path = self.identity.directory / "SOUL.md"
            text = path.read_text(encoding="utf-8") if path.exists() else "# Soul\n"
            atomic_write(path, text.rstrip("\n") + "\n\n" + str(request["soul"]).strip()[:4000] + "\n")
            done["soul"] = True
        save(self.identity.directory / "named.json", {"time": self.clock(), **done})
        return {"persona": done}

    def owner_reaction(self, chat, request) -> dict:
        """What the owner said, when it fits the tree: a node, added by the owner, at once."""
        try:
            row = self.tree.add(str(request.get("name") or ""), request.get("when"), request.get("do"),
                                under=request.get("under"), about=str(request.get("about") or ""), source="owner",
                                origin={"chat": chat, "time": self.clock()})
        except (ValueError, TypeError) as error:
            return {"error": f"{error}; if it is not an objective reaction needed even when you are passive, "
                             "remember it as a preference instead"}
        self.chats.record(chat, "learned", kind="reaction", name=row["name"], evidence="owner", under=row["under"])
        return {"added": row}

    def _live(self, chat, text, reasoning) -> None:
        """What the model has written of its reply in `chat` so far (None: nothing is being
        written any more)."""
        with self.chats.together():
            if text is None:
                self.live.pop(chat, None)
                return
            job = self.current.get(chat)
            row = self.live.get(chat)
            if row is None:
                row = self.live[chat] = {"job": job.id if job else None, "text": "", "reasoning": "",
                                         "since": self.clock()}
            row["text"], row["reasoning"] = text, reasoning

    def _next(self, chat):
        """The next job of `chat` that may start (waited for), or None when the life closes
        or the chat is gone. A held queue keeps the owner's messages; a wake still starts."""
        with self._ready:
            while not self.closing.is_set():
                waiting = self.queues.get(chat)
                if waiting is None:
                    return None
                held = chat in self.holding
                job = next((found for found in waiting if not (held and found.kind == "owner")), None)
                if job is not None:
                    waiting.remove(job)
                    return job
                self._ready.wait(5)
        return None

    def _work(self, chat) -> None:
        while True:
            job = self._next(chat)
            if job is None:
                return
            if self.paused and job.kind == "wake":
                # Paused: the model is not woken; the events wait and are handled on resuming.
                self._forget(job)
                job.done.set()
                continue
            why = self.may_wake(job.data.get("whose", "own")) if job.kind == "wake" else None
            if why:
                # Its own matter while asleep or past its pace: it waits, its events kept.
                for event in self.waiting.get(chat) or ():
                    event["deferred"] = True
                self.waiting.setdefault(chat, [])
                self._persist()
                self.chats.record(chat, "deferred", job=job.id, reason=why, why=job.data.get("why"))
                self._forget(job)
                job.done.set()
                continue
            body = self._body(chat)
            try:
                if body is not None and not body.acquire(blocking=False):
                    self.chats.update(chat, waiting="desktop")
                    body.acquire()
                self.chats.update(chat, waiting=None)
                self.busy.add(chat)
                session = self._session(chat)
                # The model as it is chosen now: the identity's, or this chat's own.
                session.chat = self._model(chat)
                if hasattr(session.tasks, "model") and hasattr(self.identity, "model_entry"):
                    session.tasks.model = self.chats.meta(chat).get("model") or self.identity.model_entry()
                started = self.clock()
                with self._ready:
                    # From here on the turn can be stopped: a stop finds the job and its session.
                    session.stopping = None
                    job.started = started
                    self.current[chat] = job
                    if job.id in self._queued:
                        self._queued[job.id]["started"] = True
                job.result = self._run(chat, job)
                if not (job.result or {}).get("asleep"):
                    self._logged(chat, job, started, job.result)
                    self.learning.turn_ended(chat)
            except Exception as error:
                self.chats.record(chat, "error", job=job.id, error=f"{type(error).__name__}: {error}")
                job.result = {"error": str(error)}
            finally:
                with self._ready:
                    self.current.pop(chat, None)
                self._live(chat, None, None)
                self.busy.discard(chat)
                if body is not None and body.locked():
                    body.release()
                self._forget(job)
                job.done.set()

    def _body(self, chat):
        place = self.chats.meta(chat).get("place")
        return self.bodies.get(place)

    def run_skill(self, chat, name, args, event, taken) -> dict:
        """The tree calls a skill: its program's main(event, args), in the place's folder, without
        the model. Where the environment has outside consequences, only an effective skill."""
        meta = self.chats.meta(chat)
        place = self.places.get(meta.get("place"))
        kind = place.kind if place is not None else None
        row = next((r for r in self.learning.skills() if r["name"] == name), None)
        if row is None or row.get("archived") or not (self.learning.skills_root / name / "program.py").exists():
            outcome = {"end": "refused", "reason": f"no skill {name!r} with a program"}
        elif kind not in ("folder", None) and row["evidence"] != "effective":
            outcome = {"end": "refused", "reason": f"the tree calls a skill here only once it is effective "
                                                   f"({name} is {row['evidence']}); the model may call it by hand"}
        else:
            import subprocess
            import sys as _sys

            folder = getattr(place, "folder", None) or self.identity.directory
            runner = ("import json, sys, runpy\nspace = runpy.run_path(sys.argv[1])\n"
                      "data = json.load(sys.stdin)\nresult = space['main'](data['event'], **data['args'])\n"
                      "print(json.dumps(result, default=str))")
            try:
                done = subprocess.run([_sys.executable, "-c", runner, str(self.learning.skills_root / name / "program.py")],
                                      input=json.dumps({"event": event or {}, "args": args or {}}), text=True,
                                      capture_output=True, cwd=str(folder), timeout=600, encoding="utf-8")
                outcome = {"end": "done" if done.returncode == 0 else "failed",
                           "result": done.stdout[-1000:], **({"reason": done.stderr[-500:]} if done.returncode else {})}
            except subprocess.TimeoutExpired:
                outcome = {"end": "unknown", "reason": "the skill ran out of time"}
        self.chats.record(chat, "outcome", verb=f"skill {name}", node=taken.get("node"), **outcome)
        return outcome

    def _calendar_due(self, now) -> None:
        for row in self.calendar.due(now):
            if row["by"] == "agent" and not self.proactive_allows("learn" if row["kind"] == "plan" else "act"):
                continue
            self.wake(row.get("chat") or MAIN, f"on the calendar: {row['title']}",
                      whose="owner" if row["by"] == "owner" else "own", entry=row["id"])
        self.calendar.morning(now)

    def _calendar_action(self, chat, request) -> dict:
        """Put something on the calendar: for the owner when the owner asked, else its own plan."""
        mine = bool(request.get("mine")) or self.levels.get(chat) != "owner"
        try:
            row = self.calendar.add(request.get("title"), request.get("at"), until=request.get("until"),
                                    kind=request.get("kind") or ("plan" if mine else "reminder"),
                                    repeat=request.get("repeat"), by="agent" if mine else "owner", chat=chat,
                                    note=request.get("note") or "")
        except (ValueError, TypeError) as error:
            return {"error": str(error)}
        return {"added": row}

    def _calendar_notes(self, chat) -> str:
        now = self.clock()
        soon = [r for r in self.calendar.week(now - 3600, now + 86400)["entries"] if r.get("planned")]
        lines = [CALENDAR]
        if soon:
            lines.append("On the calendar in the next day: " + json.dumps(
                [{"title": r["title"], "at": datetime.fromtimestamp(r["start"]).isoformat(timespec="minutes"),
                  "by": r["by"]} for r in soon[:20]], ensure_ascii=False))
        return "\n".join(lines)

    def _logged(self, chat, job, started, result) -> None:
        """One line on the calendar for a turn: who began it, what came of it, refusals."""
        rows = [r for r in self.chats.read(chat) if r["time"] >= started]
        outcomes = [r for r in rows if r["event"] == "outcome"]
        if job.kind == "owner":
            who, title = "owner", job.data.get("text")
        else:
            who, title = "own", "; ".join(job.data.get("why") or [])
        if not outcomes and not [r for r in rows if r["event"] in ("reply", "done")]:
            return
        self.calendar.log(kind="turn", who=who, title=str(title)[:160], start=started, end=self.clock(), chat=chat,
                          place=self.chats.meta(chat).get("place"),
                          outcome=outcomes[-1].get("end") if outcomes else ("done" if (result or {}).get("answer")
                                                                           else None),
                          refused=any(r.get("end") == "refused" for r in outcomes),
                          note=next((r.get("note") for r in reversed(rows) if r["event"] == "done"), None)
                          or (result or {}).get("asleep"))

    def _forget(self, job) -> None:
        with self._lock:
            self._queued.pop(job.id, None)
        self._persist()

    def _run(self, chat, job):
        session = self._session(chat)
        session.whose = job.data.get("whose", "owner") if job.kind == "wake" else "owner"
        if job.kind == "owner":
            self.levels[chat] = "owner"
        else:
            # The lowest of the sources that triggered it: someone else's words, else its own.
            sources = []
            for event in self.waiting.get(chat) or ():
                data = event.get("data") or {}
                if data.get("owner"):
                    sources.append("owner")
                elif event.get("others") and event.get("kind") != "asp.outcome":
                    sources.append("other")
                else:
                    sources.append("own")
            self.levels[chat] = safety.turn_level(sources or ["owner" if session.whose == "owner" else "own"])
        self.chats.record(chat, "turn_started", job=job.id, whose=session.whose)
        try:
            if job.kind == "owner":
                answer = session.turn(job.data["text"], channel=job.data.get("channel"))
                self._deliver(chat, answer, channel=job.data.get("channel"))
                return {"answer": answer, "chat": chat}
            events = self.waiting.pop(chat, [])
            self._persist()
            recent, summary = self._split(events)
            answer = session.wake(job.data.get("why") or [], recent, summary=summary)
            if answer:
                self._deliver(chat, answer, events=events)
            return {"answer": answer, "chat": chat}
        except Interrupted as stopped:
            # What was done until then stands; the record says where it stopped and why.
            self.chats.record(chat, "interrupted", reason=str(stopped), job=job.id)
            return {"interrupted": str(stopped), "chat": chat}
        except SpendingLimit as error:
            self.chats.record(chat, "asleep", reason=str(error), job=job.id)
            if job.kind == "wake":
                # What woke it waits for the model, after the reset.
                self.waiting.setdefault(chat, [])
            return {"asleep": str(error), "chat": chat}

    def _split(self, events):
        """Events older than agent.stale_hours become one summary text."""
        hours = float(self.identity.settings().get("stale_hours", 6))
        edge = self.clock() - hours * 3600
        old = [event for event in events if event["time"] < edge]
        recent = [event for event in events if event["time"] >= edge]
        if not old:
            return recent, None
        lines = []
        for event in old:
            data = event.get("data") or {}
            what = data.get("text") or event.get("end") or event["kind"]
            who = data.get("name") or data.get("from") or event.get("place")
            lines.append(f"- {time.strftime('%m-%d %H:%M', time.localtime(event['time']))} {who}: {str(what)[:200]}"
                         + (" (named it)" if event.get("addressed") else ""))
        summary = (f"{len(old)} events older than {hours:g} hours, while you were not woken. Judge which still "
                   "deserve an answer; do not answer old messages one by one:\n" + "\n".join(lines[-200:]))
        return recent, summary

    # Doing something in a place.

    def act(self, chat, verb, obj, args):
        """One action of the model in `chat`'s place: its outcome (the safety layer first)."""
        meta = self.chats.meta(chat)
        place = self.places.get(meta.get("place")) or (self.places.get(self.reply_to.get(chat, (None,))[0])
                                                       if chat == MAIN else None)
        if place is None or not hasattr(place, "act"):
            return {"end": "refused", "reason": "this chat's place has no verbs to act with"}
        if self.paused:
            return {"end": "refused", "reason": "the identity is paused"}
        verdict, reason = self.check(chat, verb, place=place, obj=obj)
        if verdict == "refuse":
            return {"end": "refused", "reason": reason}
        if verdict == "approve":
            state, why = self.approvals.ask(chat, f"{verb} {json.dumps(args, ensure_ascii=False)[:200]}"
                                            + (f" ({obj})" if obj else ""), verb=verb, place=place.id)
            if state != "approved":
                return {"end": "cancelled" if state == "cancelled" else "refused",
                        "reason": f"approval {state}: {why}"}
        return place.act(verb, args, obj)

    def check(self, chat, verb, *, place=None, obj=None, effect=None) -> tuple:
        """The safety layer's verdict on one action of the turn running in `chat`."""
        meta = self.chats.meta(chat)
        place = place or self.places.get(meta.get("place"))
        if effect is None:
            try:
                verbs = place.vocabulary().get("verbs") or {} if hasattr(place, "vocabulary") else {}
                effect = (verbs.get(verb) or {}).get("effect")
            except Exception:
                effect = None
        recent = self.clock() - float(self.facts.get("owner_seen") or 0) < safety.OWNER_SECONDS
        row = getattr(place, "row", {}) or {}
        thing = meta.get("thing")
        in_chat = obj is None or thing is None or str(obj).startswith("msg:") or obj == thing
        proactive = places_module.proactive(self.identity, row) if row else "do"
        own_place = meta.get("place") == getattr(place, "id", None) or chat == MAIN
        return safety.check(level=self.levels.get(chat, "own"), effect=effect or "change", place_kind=row.get("kind"),
                            proactive=proactive, own_place=own_place,
                            owner_active=bool(self.facts.get("owner_active")) and recent, verb=verb, in_chat=in_chat)

    def approve_send(self, chat, request) -> tuple:
        """A command that sends (a push): the safety layer's rule for sending, then the owner."""
        place = self.places.get(self.chats.meta(chat).get("place"))
        verdict, reason = self.check(chat, "task", place=place, effect="send")
        if verdict == "refuse":
            return "refused", reason
        return self.approvals.ask(chat, f"run {request['send']!r} for: {str(request.get('goal'))[:200]}",
                                  verb="send", place=getattr(place, "id", None), effect="send")

    def task_rows(self, chat):
        """What a task's records tell the chat: an input the safety layer refused (the owner at
        the desktop) is an outcome "refused" with its reason, for the record and the calendar."""
        def seen(row):
            happened = ((row.get("execution") or {}).get("event") or {}) if row.get("event") == "execution_event" else {}
            if happened.get("kind") != "SHIELD_REJECTED":
                return
            reasons = (happened.get("detail") or {}).get("reasons") or [{}]
            owner = any(reason.get("check") == "user_input" for reason in reasons)
            self.chats.record(chat, "outcome", verb=f"input ({(row.get('execution') or {}).get('skill') or 'step'})",
                              end="refused", run_seq=row.get("seq"), owner_input=owner,
                              reason=str(reasons[0].get("reason") or "the safety layer refused the input")[:300])
        return seen

    def task_guard(self, chat, row):
        """What a task in `chat`'s place passes first, and where its approvals go."""
        def submit_check():
            verdict, reason = self.check(chat, "task", place=self.places.get((row or {}).get("id")), effect="change")
            return reason if verdict == "refuse" else None

        def approval(request):
            what = request.get("description") or request.get("what") or request.get("target") \
                or json.dumps(request, ensure_ascii=False)[:200]
            state, why = self.approvals.ask(chat, str(what), verb=request.get("kind") or "task step",
                                            place=(row or {}).get("id"))
            if state == "cancelled":
                self.chats.record(chat, "outcome", verb="approval", end="cancelled", reason=why)
            return state == "approved", f"approval {state}" + (f": {why}" if why else "")
        return submit_check, approval

    def _deliver(self, chat, answer, *, channel=None, events=()):
        """A reply goes back where it was asked: the place's chat (a reply to the message that
        woke it), or the owner's channel chat."""
        if not answer:
            return
        meta = self.chats.meta(chat)
        if chat == MAIN and channel and chat in self.reply_to:
            place, message = self.reply_to.pop(chat)
            found = self.places.get(place)
            verb = ((self.channel_kinds.get(place) or {}).get("messages") or {}).get("reply")
            if found is not None and hasattr(found, "act") and verb:
                outcome = found.act(verb, {"text": answer}, message)
                self.chats.record(chat, "outcome", verb="reply", channel=channel, **outcome)
            return
        if meta.get("kind") == "place":
            found = self.places.get(meta.get("place"))
            # How a reply is said there is what the place's channel declares; a place that
            # declares none keeps the reply in its record.
            names = (self.channel_kinds.get(meta.get("place")) or {}).get("messages") or {}
            if found is None or not hasattr(found, "act") or not (names.get("reply") or names.get("send")):
                return
            message = next((e["data"].get("message") for e in reversed(list(events))
                            if (e.get("data") or {}).get("message") and e.get("addressed")), None)
            if message is None:
                message = next((e["data"].get("message") for e in reversed(list(events))
                                if (e.get("data") or {}).get("message")), None)
            verb, obj = (names["reply"], message) if message and names.get("reply") else (names.get("send"),
                                                                                              meta.get("thing"))
            if not verb:
                return
            self.chats.record(chat, "action", verb=verb, object=obj, args={"text": answer})
            outcome = self.act(chat, verb, obj, {"text": answer})
            self.chats.record(chat, "outcome", verb=verb, **outcome)


WAKE = """You were woken because there is something worth thinking about. Decide whether to do something and
what: a piece of work, learning something, following something up, replying, or nothing. Budget for your own
work today: ${left:.2f} left over about {hours:.0f} hours (${reserve:.2f} more is kept for your owner); with less
left, think less often and pick cheaper things. Acting on your own: {proactive}.
Before you end with done or reply, leave what you still want to do later and when to be woken for it:
{{"action":"intend","what":"what you will do","at":"HH:MM or ISO time"}}, or with "in_minutes":N, or
"after_event":"an event kind or verb" (e.g. folder.check). Then only your tree of reactions runs until then."""

FIRST_CHAT = """This is your first conversation with your owner. In your first reply, also ask what you should be
called and what personality you should have. When they answer, write it down with
{"action":"persona","name":"the name they gave","soul":"the personality, tone and limits they described"};
if they do not want to choose, use {"action":"persona"} and keep the defaults."""

CALENDAR = """Your calendar is an ordinary calendar you and your owner both use. Put something on it with
{"action":"calendar","title":"...","at":"ISO time or HH:MM","until":null,"kind":"goal|task|reminder|plan",
"repeat":null|"daily"|"weekly","mine":true for your own plans}; you are woken when it comes due. When your owner
says not to do some kind of thing, remember it as a private memory and do not do that kind of thing on your own."""

OWNER_REACTION = """When your owner tells you how to react to something and it is an objective condition needed even when
you are passive (an event, an outcome, a fact such as the battery below 20%), add it to your tree:
{"action":"reaction","name":"short name","about":"condition -> answer","when":CONDITION,"do":ANSWER,"under":"the
node it fits under best, or null for the root"}. CONDITION is {"event":KIND,"match":{...}}, {"outcome":["failed"]},
{"fact":"battery|owner_active|working_in|asleep","below|above|is|has":VALUE}, or all/any/not of these. ANSWER is
one of {"wake":true}, {"stop":true}, {"remind":"text"}, {"skill":"name"}, {"nothing":true}. Anything else your
owner prefers (whom to answer, when to keep quiet) is a memory, not a node."""


class Service:
    """The agent package's background service in the session host (extensions.background)."""

    def __init__(self, server):
        self.server = server
        self.lives = {}

    def _connection(self):
        from harness.sdk import Host

        host, port = self.server.server_address[:2]
        return Host(f"http://127.0.0.1:{port}", self.server.token)

    def make(self, identity) -> Life:
        from .cli import model_config
        from .tasks import Tasks

        connection = self._connection()
        models = {}

        def chat_model(name=None):
            """The model of the entry `name` (None: the identity's choice now). One is kept for
            each configuration, so an agent that answers as the model keeps its session."""
            from harness.sdk import ChatModel

            config = model_config(name or identity.model_entry())
            key = json.dumps(config, sort_keys=True, default=str)
            if key not in models:
                models[key] = ChatModel(config)
            return models[key]

        def tasks(row):
            kind = (row or {}).get("kind")
            workspace = {"folder": "project", "browser": "browser", "desktop": "desktop"}.get(kind, "none")
            return Tasks(connection, workspace=workspace, folder=(row or {}).get("folder"), identity=identity,
                         model=identity.model_entry(),
                         # The owner connected the desktop: its input needs no asking, and is
                         # refused while the owner uses it (the safety layer's rule).
                         runtime=({"physical": {"level": "when_idle", "yield_on_user_input": True},
                                   "privacy": {"level": "presence"}} if kind == "desktop" else None))

        return Life(identity, connection=connection, model=chat_model, tasks=tasks)

    def start(self) -> None:
        first()  # a new user has the identity `default` from the first start on
        for name in identities():
            identity = Identity(name, create=False)
            if (identity.directory / "retired.json").exists():
                continue
            try:
                life = self.make(identity)
                life.start()
                self.lives[name] = life
            except IdentityError as error:
                print(json.dumps({"agent": name, "not_started": str(error)}), flush=True)

    def life(self, name) -> Life:
        life = self.lives.get(name)
        if life is None or not life.alive:
            identity = Identity(name, create=False)
            life = self.make(identity)
            life.start()
            self.lives[name] = life
        return life

    def keep_alive(self) -> bool:
        return any(life.alive for life in self.lives.values())

    def close(self) -> None:
        for life in self.lives.values():
            if life.alive:
                life.close()
