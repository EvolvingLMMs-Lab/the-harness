"""What the agent package gives the session host and the core's frontends (the core calls
these by name, harness/extensions.py, and imports nothing of this package):

    api        /api/agent/dialogue, /api/agent/memory, /api/agent/identities,
               /api/agent/identity (new, use, rename, delete); the life of each identity:
               /api/agent/life (status), /api/agent/chats (the list; rename, pin, archive,
               delete), /api/agent/chat (its record after a number, and the reply being
               written), /api/agent/say (into the one queue), /api/agent/queue (what waits
               in a chat: edit, remove, clear, send_now, resume), /api/agent/stop (the turn
               in progress), /api/agent/opened, /api/agent/new_chat, /api/agent/pause,
               /api/agent/resume, /api/agent/places (connect, disconnect)
    background the resident life of every identity (life.Service): keeps the host up
    identity   the identity a terminal chat runs as (harness --identity)
    Agent      harness.sdk.Agent"""
from harness.sdk import Host, Problem
from . import state
from .cli import model
from .sdk import Agent  # noqa: F401  (harness.sdk.Agent)
from .state import Identity
from .session import Session
from .tasks import Tasks


def _identity(body):
    # Nobody to ask over HTTP: with several identities a frontend names one.
    name = body.get("identity")
    return Identity(state.resolve(name[0] if isinstance(name, list) else name), create=False)


def elsewhere() -> list:
    """The agents of other products on this computer that can be brought over (take.py)."""
    from .take import found_elsewhere

    return found_elsewhere()


def bring_over(kind: str) -> dict:
    """A new identity from one of them: persona, memory and skills, never its tokens or keys."""
    from .take import import_from

    return import_from(str(kind))


def background(server):
    from .life import Service

    return Service(server)


def _life(server, body):
    service = (getattr(server, "background", None) or {}).get("agent")
    if service is None:
        raise Problem("the agent's life does not run in this session host", "harness host restart starts it; "
                      "harness doctor says what is missing", code="no_life")
    return service.life(_identity(body).id)


def dialogue(server, body):
    """One turn in a chat of the identity (the main conversation by default): through its life
    when the host runs it, so every frontend shares one queue."""
    if (getattr(server, "background", None) or {}).get("agent") is not None:
        life = _life(server, body)
        chat = body.get("session") or body.get("chat") or "main"
        result = life.say(chat, body["text"], wait=True, timeout=float(body.get("timeout") or 900)) or {}
        if result.get("error") or result.get("asleep"):
            raise ValueError(result.get("error") or result.get("asleep"))
        return {"identity": life.identity.id, "session": chat, "answer": result.get("answer"),
                **({"interrupted": result["interrupted"]} if result.get("interrupted") else {}),
                **({"removed": True} if result.get("removed") else {})}
    identity = _identity(body)
    identity.live()
    host, port = server.server_address[:2]
    connection = Host(f"http://127.0.0.1:{port}", server.token)
    tasks = Tasks(connection, model=body.get("model"), workspace=body.get("workspace", "auto"),
                  folder=body.get("folder"), identity=identity)
    session = Session(identity, model(body.get("model")), tasks, session=body.get("session"))
    return {"identity": identity.id, "session": session.id, "answer": session.turn(body["text"])}


def memory(server, body):
    return _identity(body).memory()


def identities(server, body):
    state.first()
    return Agent.list()


def _close_life(server, ident_id: str) -> None:
    service = (getattr(server, "background", None) or {}).get("agent")
    if service is None:
        return
    live = service.lives.pop(ident_id, None)
    if live is not None and live.alive:
        live.close()


def _is_untouched_default(ident_id: str) -> bool:
    import json as _json

    if ident_id != "default":
        return False
    folder = state.agents_root() / "default"
    if not folder.is_dir():
        return False
    places_file = folder / "places.json"
    if places_file.is_file():
        places = state.read(places_file, [])
        if places:
            return False
    mem_dir = folder / "memory"
    if mem_dir.is_dir() and any(mem_dir.glob("*.md")):
        return False
    sessions_dir = folder / "sessions"
    if sessions_dir.is_dir():
        for ev in sessions_dir.glob("*/events.jsonl"):
            try:
                for line in ev.read_text(encoding="utf-8", errors="replace").splitlines():
                    row = _json.loads(line)
                    if row.get("event") in ("user", "reply", "task", "act"):
                        return False
            except (OSError, ValueError):
                continue
    return True


def identity_change(server, body):
    """POST {action: new | use | rename | delete | setup, id, name?, from?, new_id?, soul?, user?}:
    what harness agent new, use, rename, delete and first-run setup do; returns the identities after it."""
    import time as _time
    from harness.sdk import atomic_write

    action, name = body.get("action"), body.get("id")
    if action == "new":
        state.create(name, display=body.get("name"), source=body.get("from"))
    elif action == "use":
        state.use(name)
    elif action == "rename":
        target = Identity(name, create=False)
        target.rename(body.get("name"))
        state.save(target.directory / "named.json", {"at": _time.time(), "source": "rename"})
    elif action == "delete":
        _close_life(server, name)
        state.delete(name)
    elif action == "setup":
        cur_id = str(name or state.resolve()).strip()
        display = str(body.get("name") or "").strip()
        new_id = str(body.get("new_id") or "").strip()
        soul = str(body.get("soul") or "").strip()
        user = str(body.get("user") or "").strip()
        if new_id and new_id != cur_id:
            state.identifier(new_id)
            target = state.create(new_id, display=display or new_id)
            state.use(new_id)
            if _is_untouched_default(cur_id):
                _close_life(server, cur_id)
                state.delete(cur_id)
            service = (getattr(server, "background", None) or {}).get("agent")
            if service is not None:
                service.life(new_id)
        else:
            target = Identity(cur_id, create=False)
            if display:
                target.rename(display)
        if soul:
            atomic_write(target.directory / "SOUL.md", state.TEMPLATES["SOUL.md"] + f"\n{soul}\n")
        if user:
            atomic_write(target.directory / "USER.md", state.TEMPLATES["USER.md"] + f"\n{user}\n")
        if display or new_id or soul or user:
            state.save(target.directory / "named.json", {"at": _time.time(), "source": "onboarding"})
    else:
        raise Problem(f"no action {action!r} for identities",
                      "the actions are new, use, rename, delete and setup", code="no_action")
    return Agent.list()


def usage(server, body):
    """GET {range: today | week | month} (or {from, to}: days YYYY-MM-DD): what an identity
    spent over that stretch (spending.Account.span), split by conversation (`by_chat`) and by
    what else it was for (`by_task`: tasks, learning), with `today`: today's budget and what
    is left of it. POST {raise_today: dollars} raises today's limit only."""
    from .chats import Chats

    identity = _identity(body)
    account = identity.account()
    if body.get("raise_today") is not None and not isinstance(body.get("raise_today"), list):
        try:
            account.raise_today(float(body["raise_today"]))
        except (ValueError, TypeError) as error:
            limit = account.limits()["daily_budget"]
            raise Problem(str(error) if isinstance(error, ValueError) and "budget" in str(error)
                          else "today's limit is a number of dollars",
                          f"give an amount above ${limit:.2f}; the limit of every day is the setting agent.daily_budget",
                          code="budget_not_raised") from None
    start, end = _one(body.get("from")), _one(body.get("to"))
    span = account.span(_one(body.get("range")) or "today", start=start, end=end)
    chats = Chats(identity)
    known = set(chats.ids())
    by_chat, by_task = [], []
    for source in span.pop("by_source"):
        if source["kind"] == "chat":
            by_chat.append({"chat": source["id"], "there": source["id"] in known,
                            "title": chats.meta(source["id"]).get("title") if source["id"] in known else source["id"],
                            **{key: source[key] for key in ("cost_usd", "plan_usd", "calls", "seconds", "last")}})
        else:
            if not source.get("title") and source["id"] in known:
                source["title"] = chats.meta(source["id"]).get("title")  # learning from that chat
            by_task.append({key: source[key] for key in ("kind", "id", "title", "whose", "cost_usd", "plan_usd", "calls",
                                                         "seconds", "last")})
    return {"identity": identity.id, **span, "by_chat": by_chat, "by_task": by_task, "today": account.day(),
            **({"week": account.week()} if _one(body.get("week")) else {})}


def life(server, body):
    """The identity's life: alive, paused, busy chats, places."""
    return _life(server, body).status()


def _flag(value) -> bool:
    return str(_one(value) or "").strip().lower() in ("1", "true", "yes", "on")


def chats(server, body):
    """GET {archived: 0 | 1, q}: the list (the main conversation, the pinned, then the newest
    first; `archived` 1: the archived ones instead; `q`: those whose title or words hold that
    text). POST {action: rename | pin | unpin | archive | unarchive | delete | model | place,
    chat, title, model, place, isolation}: the list after it (model: the chat uses that entry
    of the model list from its next turn on; null: the identity's again. place: a chat the
    owner started works in that connected place, `isolation` "worktree" in an isolated copy
    of the project; null: nowhere in particular)."""
    found = _life(server, body)
    action = _one(body.get("action"))
    rewound = None
    if action:
        rewound = found.chat_change(_one(body.get("chat")), action, title=body.get("title"), model=body.get("model"),
                                    effort=body.get("effort"), place=body.get("place"), isolation=body.get("isolation"),
                                    mode=body.get("mode"), seq=body.get("seq"),
                                    restore_files=bool(body.get("restore_files")))
    archived = body.get("archived")
    return {"identity": found.identity.id,
            "chats": found.chats.listing(busy=found.busy, archived=archived is True or _flag(archived),
                                         q=_one(body.get("q"))),
            **({"rewound": rewound} if rewound is not None else {})}


def chat(server, body):
    """GET {chat, after}: the chat's record after that number (every frontend polls the same),
    and `live`: the reply the model is writing there now ({job, text, reasoning, since}; null
    when none is being written; text stays empty for a model that does not stream)."""
    found = _life(server, body)
    name = _one(body.get("chat")) or "main"
    after = int(_one(body.get("after")) or 0)
    with found.chats.together():
        # Together: a reply is either still being written or in the records, never both or neither.
        records = found.chats.read(name, after=after)
        live = dict(found.live[name]) if name in found.live else None
    return {"chat": name, "meta": found.chats.meta(name), "records": records, "live": live,
            "context": found.context(name)}


def stream(server, body):
    """GET {identity, chat, after}: Server-Sent Events stream pushing chat records and live reply chunks."""
    import json
    import time

    found = _life(server, body)
    name = _one(body.get("chat")) or "main"
    cursor = int(_one(body.get("after")) or 0)

    def _serve(handler):
        nonlocal cursor
        handler.answered = True
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()
        last_live = None
        last_meta = None
        last_ping = time.monotonic()
        seen = -1
        try:
            while found.alive:
                with found.chats.together():
                    records = found.chats.read(name, after=cursor)
                    live = dict(found.live[name]) if name in found.live else None
                    meta = found.chats.meta(name)
                live_sig = (live.get("text"), live.get("reasoning"), live.get("job")) if live else None
                meta_sig = (meta.get("title"), meta.get("title_source"), meta.get("mode"), meta.get("model"))
                if records or live_sig != last_live or meta_sig != last_meta or seen < 0:
                    if records:
                        cursor = records[-1]["seq"]
                    last_live = live_sig
                    last_meta = meta_sig
                    payload = {"chat": name, "meta": meta, "records": records,
                               "live": live, "context": found.context(name), "queue": found.queue(name)}
                    handler.wfile.write(f"event: chat\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
                    handler.wfile.flush()
                    last_ping = time.monotonic()
                seen = found.chats.wait_change(max(0, seen), timeout=5.0)
                if time.monotonic() - last_ping >= 15.0:
                    handler.wfile.write(b": keepalive\n\n")
                    handler.wfile.flush()
                    last_ping = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    return _serve


def compact(server, body):
    """POST {chat, instructions, wait}: compact the chat's context now (the summary follows
    `instructions`): {compacted, messages, summary, chat}; `wait` false: {queued, chat}."""
    found = _life(server, body)
    return found.compact(_one(body.get("chat")) or "main", str(body.get("instructions") or ""),
                         wait=body.get("wait", True) is not False)


def queue(server, body):
    """GET {chat}: the owner's messages that wait in the chat, what runs there and whether the
    queue is held; POST {chat, action: edit | remove | clear | send_now | resume, id, text}:
    the queue after it."""
    found = _life(server, body)
    name = _one(body.get("chat")) or "main"
    action = _one(body.get("action"))
    if action:
        return found.queue_change(name, action, id=body.get("id"), text=body.get("text"))
    return found.queue(name)


def stop(server, body):
    """POST {chat, hold}: stop the turn in progress there ({stopped, queued, held}); with
    `hold` the messages that wait stay until the queue is resumed."""
    found = _life(server, body)
    return found.stop(_one(body.get("chat")) or "main", hold=body.get("hold") is True or _flag(body.get("hold")))


def say(server, body):
    """POST {chat, text, files}: the owner's words join the identity's one queue; answered in
    the record. `files`: ids of attachments of that chat (attach), given to the model with
    the message."""
    found = _life(server, body)
    text = body["text"]
    if body.get("place"):
        # The composer's choice of where the work is done (the main conversation's picker).
        text = f"{text}\n\n(Work in the place {body['place']}.)"
    return found.say(body.get("chat") or "main", text, wait=bool(body.get("wait")), files=body.get("files") or ())


def attach(server, body):
    """POST {chat, name, type, data}: keep a file (`data`: its content in base64) for a message
    of the chat: {id, name, size, type}. say's `files` names it."""
    import base64
    import binascii

    found = _life(server, body)
    try:
        content = base64.b64decode(str(body.get("data") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise Problem("the file did not arrive whole", "attach it again", code="attachment_data") from None
    row = found.chats.attach(body.get("chat") or "main", body.get("name"), content, body.get("type"))
    return {key: row[key] for key in ("id", "name", "mime", "type", "size", "url")}


# Bytes a request to a route of this package may send (the default is 1 MB): a file in base64.
api_limits = {"attach": 28 * 1024 * 1024, "take": 64 * 1024 * 1024}


def opened(server, body):
    _life(server, body).chats.opened(body.get("chat") or "main")
    return {"ok": True}


def new_chat(server, body):
    """POST {title, place, isolation, mode}: a new chat; with `place` it works there from the start
    (Life.work_in: a connected folder, browser or desktop; `isolation` "worktree": in an
    isolated copy of the project); `mode` is auto, plan or ask."""
    found = _life(server, body)
    chat = found.chats.new(body.get("title") or "New chat", title_source=body.get("title_source"))
    if body.get("mode") in ("plan", "ask", "auto", "full"):
        found.chats.update(chat, mode=body["mode"])
    if body.get("place"):
        try:
            found.work_in(chat, body["place"], body.get("isolation"))
        except Problem:
            found.chats.delete(chat)
            raise
    return {"chat": chat}


def pause(server, body):
    found = _life(server, body)
    found.pause()
    return found.status()


def resume(server, body):
    found = _life(server, body)
    found.resume()
    return found.status()


def places(server, body):
    """POST {action: connect, kind, ...}, {action: disconnect, place} or {action: project,
    folder} (the place of that project folder, connected now when it was not: `place` is its
    id); else the places."""
    found = _life(server, body)
    if body.get("action") == "project":
        row = found.project(body.get("folder"))
        return {"places": [place.describe() for place in found.places.values()], "place": row["id"]}
    if body.get("action") == "ssh":
        row = found.ssh_project(body.get("host"), body.get("folder") or body.get("path") or "~",
                                user=body.get("user"), port=body.get("port"), title=body.get("title"))
        return {"places": [place.describe() for place in found.places.values()], "place": row["id"]}
    if body.get("action") == "connect":
        fields = {key: value for key, value in body.items() if key not in ("action", "identity", "kind")}
        found.connect(body["kind"], **fields)
    elif body.get("action") == "disconnect":
        found.disconnect(body["place"])
    return {"places": [place.describe() for place in found.places.values()]}


def _one(value):
    return value[0] if isinstance(value, list) else value


def tree(server, body):
    """GET {path: "a/b"}: one level of the tree of reactions, like a folder; POST {action: add
    | move | enable | disable | remove, name, when, do, under, before}: the level `path`
    after it. The node an action is for is `name`; or, as a page that browses the tree has
    it, the `path` to the node itself (its last part is the node, and the level answered is
    the one it is in)."""
    found = _life(server, body)
    action = _one(body.get("action"))
    name = _one(body.get("name"))
    if action and action != "add" and not name and _one(body.get("path")):
        # The node by its path: the level shown afterwards is its parent's.
        parts = [part for part in str(_one(body.get("path"))).split("/") if part]
        name, body = parts[-1], {**body, "path": "/".join(parts[:-1])}
    if action == "add":
        found.tree.add(name, body.get("when"), body.get("do"), under=body.get("under"), before=body.get("before"),
                       about=body.get("about") or "", source="owner")
    elif action == "edit":
        found.tree.edit(name, about=body.get("about"), when=body.get("when"), do=body.get("do"))
    elif action == "move":
        found.tree.move(name, under=body.get("under"), before=body.get("before"))
    elif action in ("enable", "disable"):
        found.tree.enable(name, action == "enable")
    elif action == "remove":
        found.tree.remove(name)
    elif action:
        raise Problem(f"no action {action!r} for the tree", "the actions are add, edit, move, enable, disable and remove",
                      code="no_action")
    if body.get("all") is True or _flag(body.get("all")):
        return found.tree.full()
    path = _one(body.get("path")) or ""
    return found.tree.level([part for part in str(path).split("/") if part])


def own(server, body):
    """POST {on: false}: pause what it does on its own (it still answers the owner and
    mentions); {on: true} resumes it."""
    found = _life(server, body)
    found.pause_own(not bool(body.get("on", True)))
    return found.status()


def approvals(server, body):
    """GET: the requests waiting for the owner; POST {code, accept, reason, scope}: the owner's answer
    (the first answer wins; a later one is "handled elsewhere")."""
    found = _life(server, body)
    if body.get("code") is not None and not isinstance(body.get("code"), list):
        return found.approvals.answer(body["code"], bool(body.get("accept")), str(body.get("reason") or ""),
                                      by="app", scope=str(body.get("scope") or "once"))
    return {"pending": found.approvals.pending()}


def notifications(server, body):
    """GET {after}: the system notifications of every identity after that id (approval, limit,
    failed, login only); a desktop shell raises them."""
    service = (getattr(server, "background", None) or {}).get("agent")
    after = int(_one(body.get("after")) or 0)
    rows = []
    for life in (service.lives.values() if service else ()):
        rows += [{**row, "name": life.identity.name} for row in life.approvals.notifications(after)]
    return {"notifications": sorted(rows, key=lambda row: row["time"])}


def calendar(server, body):
    """GET {from, to, q}: the planned and the done entries between two times (this week by
    default; any stretch: a day, a month, a year); `q`: only those whose title or note holds
    that text (without from and to: a year back to a year ahead). POST {action: add | update | move | remove |
    restore | pause_own | resume_own, ...}: the same stretch after it, and `result`: the
    entry it made, changed, removed or put back.

        add      {title, at, until, kind, repeat, note}
        update   {id, and any of title, at, until, kind, repeat, note}: what is given
                 changes (until: null takes the end away); dragging and resizing an entry
        move     {id, at, until}: update of its times
        remove   {id}
        restore  {id}: put back an entry that was removed (no id: the last one removed)"""
    found = _life(server, body)
    action = _one(body.get("action"))
    result = None
    if action == "add":
        result = found.calendar.add(body["title"], body["at"], until=body.get("until"), kind=body.get("kind") or "task",
                                    repeat=body.get("repeat"), by="owner", note=body.get("note") or "")
    elif action in ("update", "move"):
        result = found.calendar.update(body["id"], **{key: body[key] for key in ("title", "at", "until", "kind", "repeat",
                                                                               "note") if key in body})
    elif action == "remove":
        result = found.calendar.remove(body["id"])
    elif action == "restore":
        result = found.calendar.restore(body.get("id"))
    elif action in ("pause_own", "resume_own"):
        found.pause_own(action == "pause_own")
    elif action:
        raise Problem(f"no calendar action {action!r}", "the actions are add, update, move, remove, restore, "
                      "pause_own and resume_own", code="no_action")
    week = found.calendar.week(_one(body.get("from")), _one(body.get("to")), q=_one(body.get("q")) if not action else None)
    return {**week, **({"result": result} if result is not None else {})}


def summary(server, body):
    """The summary of the stretch since the last one: what it did, learned, spent, and what
    waits for approval."""
    return _life(server, body).calendar.summary()


def setting_name(body) -> tuple:
    """(section, key) of the setting a request names. A setting has one name everywhere,
    section.key (agent.daily_budget; spaces.<place>.proactive for a place): given whole as
    `key`, or as `section` and `key`."""
    key, section = str(_one(body.get("key")) or ""), _one(body.get("section"))
    if section:
        key = key.removeprefix(f"{section}.")   # the section given twice is the same setting
    else:
        section, _, key = key.partition(".")
    if not section or not key:
        raise Problem("name the setting as section.key", "for example agent.daily_budget", code="no_setting")
    return str(section), key


def settings(server, body):
    """GET: what holds for this identity of every setting an identity may have its own value
    of. POST {key: "section.key", value}: its own value (null: the global one again);
    spaces.<place>.proactive is a place's. Both answer:

        values   {"section.key": value}: what holds for it (its own, else the global one)
        own      {"section.key": value}: the ones it has a value of its own for
        schema   {"section.key": the setting as a frontend draws it (settings.describe)}
        spaces   {place: off | learn | do}
        agent, learning   the same values by section, as before"""
    from harness.sdk import describe_setting, settings_schema
    from . import places as places_module

    found = _life(server, body)
    identity = found.identity
    if _one(body.get("key")):
        section, key = setting_name(body)
        value = body.get("value")
        if section == "spaces":
            place = key.removesuffix(".proactive")
            if place not in {row["id"] for row in places_module.load(identity)}:
                raise Problem(f"no place {place!r} is connected to {identity.id}", "its places are listed by "
                              "harness agent about", code="no_place")
            if value not in (None, *places_module.PROACTIVE):
                raise Problem(f"spaces.{place}.proactive is one of {', '.join(places_module.PROACTIVE)}",
                              f"not {value!r}", code="setting_value")
            spaces = identity.settings_section("spaces")
            spaces.setdefault(place, {})
            if value is None:
                spaces[place].pop("proactive", None)
            else:
                spaces[place]["proactive"] = value
            identity.set_section("spaces", {name: row for name, row in spaces.items() if row})
        else:
            try:
                identity.set_setting(key, value, section)
            except ValueError as error:
                spec = (settings_schema.get(section) or {}).get(key)
                raise Problem(str(error), "" if spec is None else
                              ("it is set for the whole computer (Settings, or harness config set without --identity)"
                               if spec.scope != "identity" else "give a value of its kind, or null for the global one"),
                              code="no_setting" if spec is None else "global_setting" if spec.scope != "identity"
                              else "setting_value") from None
    values = identity.effective()
    values["learning.mode"] = found.learning.mode()
    schema = {f"{section}.{key}": describe_setting(section, key, spec) for section, keys in settings_schema.items()
              for key, spec in keys.items() if spec.scope == "identity"}
    return {"identity": identity.id, "values": values, "own": identity.own(), "schema": schema,
            "agent": identity.settings(), "learning": {"mode": found.learning.mode(),
                                                        **identity.settings_section("learning")},
            "spaces": {row["id"]: places_module.proactive(identity, row) for row in places_module.load(identity)}}


def learned(server, body):
    """GET: its skills (evidence, uses, where each came from), its memory and the shared
    libraries; POST {action: undo | approve | restore | install | review, name | path}."""
    found = _life(server, body)
    action = _one(body.get("action"))
    result = None
    if action == "undo":
        result = found.learning.undo(body["name"])
    elif action == "approve":
        result = found.learning.approve(body["name"])
    elif action == "restore":
        result = found.learning.restore(body["name"])
    elif action == "install":
        result = found.learning.install(body["path"])
    elif action == "diff":
        result = found.learning.diff(body["name"])
    elif action == "delete":
        result = found.learning.delete(body["name"])
    elif action == "forget":
        identity = found.identity
        identity.remember(body["name"], None, source="owner", expected=identity.memory()["revision"])
    elif action:
        raise Problem(f"no action {action!r} for what it learned", "the actions are undo, approve, restore, install, "
                      "diff, delete and forget", code="no_action")
    from harness.runtime.learning.learner import libraries

    try:
        shared = [{"name": row.get("name"), "path": str(row.get("directory")), "read_only": True} for row in libraries()]
    except Exception:
        shared = []
    skills = found.learning.skills()
    for row in skills:
        # Where it came from: gone once that chat's record was dropped for its age (or the chat removed).
        source = row.get("source") or {}
        if source.get("chat") and source.get("time"):
            source["expired"] = found.chats.expired(source["chat"], source["time"])
    return {"skills": skills, "memory": found.identity.memory()["entries"],
            "mode": found.learning.mode(), "shared_libraries": shared, **({"result": result} if result else {})}


def take(server, body):
    """POST {action: share | card | backup | restore | adopt | retire, ...}: taking it along, as
    harness agent share / adopt / backup / restore / retire do (a frontend shows share's preview
    first: preview true). restore takes the backup's file as the page read it ({name, data: its
    content in base64, passphrase, replace}), as harness agent restore FILE takes the file."""
    from . import take as taking

    action = _one(body.get("action"))
    if action == "adopt":
        return taking.adopt(body["source"], id=body.get("id"), log=lambda *a, **k: None)
    if action == "restore":
        return _restore(server, body, taking)
    found = _life(server, body)
    identity = found.identity
    if action == "share":
        if body.get("preview"):
            return taking.preview_of(identity.id, taking.collect(identity, with_memory=bool(body.get("with_memory"))))
        return taking.share(identity, body["to"], with_memory=bool(body.get("with_memory")), confirm=lambda *_: True)
    if action == "card":
        return taking.share_card(identity, body["path"], confirm=lambda *_: True)
    if action == "backup":
        return taking.backup(identity, body["path"], body["passphrase"], with_keys=bool(body.get("with_keys")))
    if action == "retire":
        return taking.retire(identity)
    raise Problem(f"no action {action!r} for taking an identity along", "the actions are share, card, backup, "
                  "restore, adopt and retire", code="no_action")


def _restore(server, body, taking):
    """The identity of a backup the page sent, restored here: {identity, name, fingerprint,
    channels: the ones to log in to again, model_keys}. Refused, with what to do, for a wrong
    passphrase, a file that is no backup, and an identity of that id here without `replace`."""
    import base64
    import binascii
    import tempfile
    from pathlib import Path

    from .state import IdentityError

    try:
        blob = base64.b64decode(str(body.get("data") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise Problem("the backup did not arrive whole", "choose the file again", code="backup_data") from None
    try:
        name = state.identifier(taking.header_of(blob).get("identity") or "")
    except (ValueError, AttributeError) as error:
        raise taking.refusal(ValueError("not a backup of harness agent backup")) from None
    service = (getattr(server, "background", None) or {}).get("agent")
    living = service.lives.get(name) if service is not None and body.get("replace") else None
    with tempfile.TemporaryDirectory(prefix="harness-restore-") as folder:
        path = Path(folder) / (Path(str(body.get("name") or "backup")).name or "backup")
        path.write_bytes(blob)
        try:
            # Checked before anything here is touched: a wrong passphrase leaves the life it would replace.
            taking.decrypt(blob, str(body.get("passphrase") or ""))
            if living is not None and living.alive:
                living.close()   # the one that lives here gives way to the one restored
                service.lives.pop(name, None)
            result = taking.restore(path, str(body.get("passphrase") or ""), replace=bool(body.get("replace")))
        except (IdentityError, ValueError) as error:
            raise taking.refusal(error) from None
    if service is not None:
        try:
            service.life(result["identity"])   # it lives here from now on
        except Exception:  # noqa: BLE001 - restored; why it does not start is said when it is opened
            pass
    return result


def worktree(server, body):
    """GET/POST {identity, chat, action: status | merge | discard}: manage a chat's isolated git worktree."""
    from . import places as places_module

    found = _life(server, body)
    name = _one(body.get("chat")) or "main"
    action = str(_one(body.get("action")) or "status")
    meta = found.chats.meta(name)
    if action == "status":
        return places_module.worktree_status(meta)
    if action == "merge":
        return places_module.merge_copy(meta)
    if action == "discard":
        res = places_module.discard_copy(meta)
        found.chats.update(name, isolation=None, copy=None)
        found.sessions.pop(name, None)
        return res
    raise Problem(f"no worktree action {action!r}", "the actions are status, merge and discard", code="no_action")


api = {"dialogue": dialogue, "tree": tree, "own": own, "learned": learned, "take": take, "calendar": calendar, "summary": summary,
       "settings": settings, "approvals": approvals, "notifications": notifications, "life": life, "chats": chats, "chat": chat, "stream": stream, "say": say, "opened": opened,
       "queue": queue, "stop": stop, "attach": attach, "compact": compact, "worktree": worktree,
       "new_chat": new_chat, "pause": pause, "resume": resume, "places": places, "memory": memory, "identities": identities, "identity": identity_change, "usage": usage}


def identity(name=None, ask=None) -> dict:
    """The identity a terminal chat runs as: `name` (--identity), else the current or only
    one, else `ask(ids)` (None: an error). Its life is claimed for the calling process.
    {id, name, runtime, account, release}: runtime is what its conversations carry, account the
    folder of its spending account (harness.sdk.spending), release() lets go of the life when
    the chat closes."""
    chosen = Identity(state.resolve(name, ask=ask), create=False)
    claimed = chosen.live()
    runtime = Tasks(identity=chosen).runtime()
    return {"id": chosen.id, "name": chosen.name, "runtime": runtime, "account": runtime["account"],
            "release": (lambda: None) if claimed["attached"] else (lambda: state.release(chosen))}


# The channels (harness channels, /channels, Settings › Connectors) and harness library's
# skills, tree and memory (the core's harness library calls library_command).
from .channels import channels as _channels  # noqa: E402
from .frontends import library_main as library_command  # noqa: E402
from .sources import skill_sources as _skill_sources  # noqa: E402

api["channels"] = _channels
api["skill_sources"] = _skill_sources
