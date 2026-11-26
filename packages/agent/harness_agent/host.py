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
        raise ValueError("the resident life runs in the session host (harness host)")
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


def identity_change(server, body):
    """POST {action: new | use | rename | delete, id, name?, from?}: what harness agent new,
    use, rename and delete do; the identities after it. A frontend asks before delete."""
    action, name = body.get("action"), body.get("id")
    if action == "new":
        state.create(name, display=body.get("name"), source=body.get("from"))
    elif action == "use":
        state.use(name)
    elif action == "rename":
        Identity(name, create=False).rename(body.get("name"))
    elif action == "delete":
        state.delete(name)
    else:
        raise ValueError("action is new, use, rename or delete")
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
        account.raise_today(float(body["raise_today"]))
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
    text). POST {action: rename | pin | unpin | archive | unarchive | delete | model, chat,
    title, model}: the list after it (model: the chat uses that entry of the model list
    from its next turn on; null: the identity's again)."""
    found = _life(server, body)
    action = _one(body.get("action"))
    if action:
        found.chat_change(_one(body.get("chat")), action, title=body.get("title"), model=body.get("model"),
                          effort=body.get("effort"))
    archived = body.get("archived")
    return {"identity": found.identity.id,
            "chats": found.chats.listing(busy=found.busy, archived=archived is True or _flag(archived),
                                         q=_one(body.get("q")))}


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
    return {key: row[key] for key in ("id", "name", "size", "type")}


# Bytes a request to a route of this package may send (the default is 1 MB): a file in base64.
api_limits = {"attach": 28 * 1024 * 1024}


def opened(server, body):
    _life(server, body).chats.opened(body.get("chat") or "main")
    return {"ok": True}


def new_chat(server, body):
    found = _life(server, body)
    return {"chat": found.chats.new(body.get("title") or "New chat")}


def pause(server, body):
    found = _life(server, body)
    found.pause()
    return found.status()


def resume(server, body):
    found = _life(server, body)
    found.resume()
    return found.status()


def places(server, body):
    """POST {action: connect, kind, ...} or {action: disconnect, place}; else the places."""
    found = _life(server, body)
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
    elif action == "move":
        found.tree.move(name, under=body.get("under"), before=body.get("before"))
    elif action in ("enable", "disable"):
        found.tree.enable(name, action == "enable")
    elif action == "remove":
        found.tree.remove(name)
    elif action:
        raise ValueError("action is add, move, enable, disable or remove")
    path = _one(body.get("path")) or ""
    return found.tree.level([part for part in str(path).split("/") if part])


def own(server, body):
    """POST {on: false}: pause what it does on its own (it still answers the owner and
    mentions); {on: true} resumes it."""
    found = _life(server, body)
    found.pause_own(not bool(body.get("on", True)))
    return found.status()


def approvals(server, body):
    """GET: the requests waiting for the owner; POST {code, accept, reason}: the owner's answer
    (the first answer wins; a later one is "handled elsewhere")."""
    found = _life(server, body)
    if body.get("code") is not None and not isinstance(body.get("code"), list):
        return found.approvals.answer(body["code"], bool(body.get("accept")), str(body.get("reason") or ""), by="app")
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
    """GET {from, to}: the planned and the done entries between two times (this week by
    default; any stretch: a day, a month, a year). POST {action: add | update | move | remove |
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
    week = found.calendar.week(_one(body.get("from")), _one(body.get("to")))
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
        raise ValueError("action is undo, approve, restore, install, diff, delete or forget")
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
    """POST {action: share | card | backup | adopt | retire, ...}: taking it along, as harness agent
    share / adopt / backup / retire do (a frontend shows share's preview first: preview true)."""
    from . import take as taking

    action = _one(body.get("action"))
    if action == "adopt":
        return taking.adopt(body["source"], id=body.get("id"), log=lambda *a, **k: None)
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
    raise ValueError("action is share, card, backup, adopt or retire")


api = {"dialogue": dialogue, "tree": tree, "own": own, "learned": learned, "take": take, "calendar": calendar, "summary": summary,
       "settings": settings, "approvals": approvals, "notifications": notifications, "life": life, "chats": chats, "chat": chat, "say": say, "opened": opened,
       "queue": queue, "stop": stop, "attach": attach, "compact": compact,
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
