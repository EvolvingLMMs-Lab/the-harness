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

After a restart the life carries on from the record: what was queued and not done is queued
again (life-state.json), and events that waited are handled. Events older than
agent.stale_hours reach the model as one summary, so it judges which still deserve an answer
instead of answering old mentions one by one."""
import json
import queue
import threading
import time
import traceback

from harness.sdk import SpendingLimit
from . import places as places_module
from .chats import MAIN, Chats
from .state import Identity, IdentityError, identities, read, save, release

# Seconds between the life's looks at time (what comes due, timeouts).
TICK_SECONDS = 1.0


class Job:
    """One thing for a chat's worker: an owner's message, or a wake."""

    def __init__(self, kind, chat, **data):
        self.kind, self.chat, self.data = kind, chat, data
        self.id = data.pop("id", None) or f"{kind}-{time.time_ns()}"
        self.done = threading.Event()
        self.result = None

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
        self.workers = {}
        self.sessions = {}
        self.busy = set()
        self.bodies = {}                       # single-body place -> lock
        self.closing = threading.Event()
        self.alive = False
        self._lock = threading.RLock()
        self._queued = {row["id"]: row for row in saved.get("queue") or []}
        self.waiting = {chat: list(rows) for chat, rows in (saved.get("waiting") or {}).items()}
        self.reply_to = {}

    # Starting and stopping.

    def start(self) -> None:
        self.identity.live()
        self.alive = True
        self.chats.record(MAIN, "life", state="started", paused=self.paused)
        for row in places_module.load(self.identity):
            self._open_place(row)
        threading.Thread(target=self._loop, name=f"life-{self.identity.id}", daemon=True).start()
        # What was queued and not done before a restart, in its order.
        for row in sorted(self._queued.values(), key=lambda r: r.get("queued", 0)):
            self._submit(Job(row["kind"], row["chat"], **{k: v for k, v in row.items() if k not in ("kind", "chat")}),
                         persist=False)
        for chat in list(self.waiting):
            if self.waiting[chat] and not self.paused:
                self.inbox.put(("route_waiting", chat))

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
        places_module.remove(self.identity, place)

    def close(self, *, quitting=True) -> None:
        """Quit: actions in progress end as cancelled or unknown, then it stops."""
        self.closing.set()
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
                                   "waiting": {chat: rows for chat, rows in self.waiting.items() if rows}})

    def status(self) -> dict:
        return {"identity": self.identity.id, "name": self.identity.name, "alive": self.alive, "paused": self.paused,
                "busy": sorted(self.busy), "places": [place.describe() for place in self.places.values()],
                "queued": len(self._queued)}

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
        with self._lock:
            worker = self.workers.get(job.chat)
            if worker is None or not worker.is_alive():
                jobs = queue.Queue()
                worker = threading.Thread(target=self._work, args=(job.chat, jobs), name=f"chat-{job.chat}",
                                          daemon=True)
                worker.jobs = jobs
                self.workers[job.chat] = worker
                worker.start()
        worker.jobs.put(job)

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
        inside it (a QQ group), or the main conversation for the owner's private chat."""
        data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
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
        if kind == "asp.outcome":
            row = self.chats.record(chat, "outcome", verb=entry.get("verb"), end=entry.get("end"),
                                    reason=entry.get("reason"), place=place, **({"data": data} if data else {}),
                                    **({"own": True} if own else {}))
        else:
            row = self.chats.record(chat, "event", kind=kind, place=place, data=data, source=entry.get("source"),
                                    addressed=bool(data.get("addressed")), **({"own": True} if own else {}))
        if own and kind != "asp.outcome":
            return
        if kind == "qq.message" and data.get("owner") and chat == MAIN:
            # The owner's private chat in a channel joins the main conversation.
            if self._answer_code(data.get("text") or "", place):
                return
            self.say(MAIN, data.get("text") or "", channel=self.places[place].row.get("channel") or "qq")
            self.reply_to[MAIN] = (place, data.get("message"))
            return
        event = {"seq": row["seq"], "time": row["time"], "kind": kind, "place": place, "data": data,
                 "addressed": bool(data.get("addressed")), "end": entry.get("end"), "verb": entry.get("verb"),
                 "own": own, "others": how.get("others")}
        self.waiting.setdefault(chat, []).append(event)
        self._persist()
        if not self.paused:
            self._route(chat, event)

    def _answer_code(self, text, place) -> bool:
        """A short code answering an approval ("A7 approve"); the approvals step reads it."""
        return False

    def _route(self, chat, event) -> None:
        """What answers an event: a node of the tree, a wake of the model, or nothing (it
        stays in the record). Here: an event aimed at it, or an outcome failed or unknown,
        wakes the model."""
        if event.get("addressed") or (event["kind"] == "asp.outcome" and event.get("end") in ("failed", "unknown")):
            self.wake(chat, "named or aimed at it" if event.get("addressed") else "an outcome failed or unknown")

    def _route_waiting(self, chat) -> None:
        for event in list(self.waiting.get(chat) or ()):
            self._route(chat, event)

    def wake(self, chat, why, *, whose="own", **data) -> None:
        """Wake the model for `chat` (once: a wake already queued for it takes this reason too)."""
        with self._lock:
            for row in self._queued.values():
                if row["chat"] == chat and row["kind"] == "wake" and not row.get("started"):
                    if why not in row["why"]:
                        row["why"].append(why)
                    self._persist()
                    return
        self._submit(Job("wake", chat, why=[why], whose=whose, queued=self.clock(), **data))

    def _tick(self) -> None:
        """What comes due with time (the next steps add to it)."""

    # A chat's worker: one job at a time.

    def _session(self, chat):
        session = self.sessions.get(chat)
        if session is None:
            from .session import Session

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
            session = Session(self.identity, self.model_factory(), self.tasks_factory(row), session=chat,
                              chats=self.chats, place=place,
                              actor=(lambda verb, obj, args, chat=chat: self.act(chat, verb, obj, args)))
            self.sessions[chat] = session
        return session

    def _work(self, chat, jobs) -> None:
        while not self.closing.is_set():
            try:
                job = jobs.get(timeout=5)
            except queue.Empty:
                continue
            if self.paused and job.kind == "wake":
                # Paused: the model is not woken; the events wait and are handled on resuming.
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
                with self._lock:
                    if job.id in self._queued:
                        self._queued[job.id]["started"] = True
                job.result = self._run(chat, job)
            except Exception as error:
                self.chats.record(chat, "error", job=job.id, error=f"{type(error).__name__}: {error}")
                job.result = {"error": str(error)}
            finally:
                self.busy.discard(chat)
                if body is not None and body.locked():
                    body.release()
                self._forget(job)
                job.done.set()

    def _body(self, chat):
        place = self.chats.meta(chat).get("place")
        return self.bodies.get(place)

    def _forget(self, job) -> None:
        with self._lock:
            self._queued.pop(job.id, None)
        self._persist()

    def _run(self, chat, job):
        session = self._session(chat)
        session.whose = job.data.get("whose", "owner") if job.kind == "wake" else "owner"
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
        return place.act(verb, args, obj)

    def _deliver(self, chat, answer, *, channel=None, events=()):
        """A reply goes back where it was asked: the place's chat (a reply to the message that
        woke it), or the owner's channel chat."""
        if not answer:
            return
        meta = self.chats.meta(chat)
        if chat == MAIN and channel and chat in self.reply_to:
            place, message = self.reply_to.pop(chat)
            found = self.places.get(place)
            if found is not None and hasattr(found, "act"):
                outcome = found.act("qq.reply", {"text": answer}, message)
                self.chats.record(chat, "outcome", verb="reply", channel=channel, **outcome)
            return
        if meta.get("kind") == "place":
            found = self.places.get(meta.get("place"))
            if found is None or not hasattr(found, "act"):
                return
            message = next((e["data"].get("message") for e in reversed(list(events))
                            if (e.get("data") or {}).get("message") and e.get("addressed")), None)
            if message is None:
                message = next((e["data"].get("message") for e in reversed(list(events))
                                if (e.get("data") or {}).get("message")), None)
            verb, obj = ("qq.reply", message) if message else ("qq.send", meta.get("thing"))
            self.chats.record(chat, "action", verb=verb, object=obj, args={"text": answer})
            outcome = self.act(chat, verb, obj, {"text": answer})
            self.chats.record(chat, "outcome", verb=verb, **outcome)


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
        from .cli import model as chat_model
        from .tasks import Tasks

        connection = self._connection()

        def tasks(row):
            kind = (row or {}).get("kind")
            workspace = {"folder": "workspace", "browser": "browser", "desktop": "desktop"}.get(kind, "none")
            return Tasks(connection, workspace=workspace, folder=(row or {}).get("folder"), identity=identity,
                         model=identity.config.get("model"))

        return Life(identity, connection=connection, model=lambda: chat_model(identity.config.get("model")),
                    tasks=tasks)

    def start(self) -> None:
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
