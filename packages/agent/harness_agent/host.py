"""What the agent package gives the session host and the core's frontends (the core calls
these by name, harness/extensions.py, and imports nothing of this package):

    api        /api/agent/dialogue, /api/agent/memory, /api/agent/identities,
               /api/agent/identity (new, use, rename, delete); the life of each identity:
               /api/agent/life (status), /api/agent/chats (the list), /api/agent/chat
               (its record after a number), /api/agent/say (into the one queue),
               /api/agent/opened, /api/agent/new_chat, /api/agent/pause, /api/agent/resume,
               /api/agent/places (connect, disconnect)
    background the resident life of every identity (life.Service): keeps the host up
    identity   the identity a terminal chat runs as (harness --identity)
    Agent      harness.sdk.Agent"""
from harness.sdk import Host
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
        return {"identity": life.identity.id, "session": chat, "answer": result.get("answer")}
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
    """What an identity spent today ({identity, today}; week: the last seven days too); POST
    {raise_today: dollars} raises today's limit only."""
    identity = _identity(body)
    account = identity.account()
    if body.get("raise_today") is not None and not isinstance(body.get("raise_today"), list):
        account.raise_today(float(body["raise_today"]))
    return {"identity": identity.id, "today": account.day(), **({"week": account.week()} if body.get("week") else {})}


def life(server, body):
    """The identity's life: alive, paused, busy chats, places."""
    return _life(server, body).status()


def chats(server, body):
    found = _life(server, body)
    return {"identity": found.identity.id, "chats": found.chats.listing(busy=found.busy)}


def chat(server, body):
    """GET {chat, after}: the chat's record after that number (every frontend polls the same)."""
    found = _life(server, body)
    name = body.get("chat") or "main"
    name = name[0] if isinstance(name, list) else name
    after = body.get("after") or 0
    after = int(after[0] if isinstance(after, list) else after)
    return {"chat": name, "meta": found.chats.meta(name), "records": found.chats.read(name, after=after)}


def say(server, body):
    """POST {chat, text}: the owner's words join the identity's one queue; answered in the record."""
    found = _life(server, body)
    text = body["text"]
    if body.get("place"):
        # The composer's choice of where the work is done (the main conversation's picker).
        text = f"{text}\n\n(Work in the place {body['place']}.)"
    return found.say(body.get("chat") or "main", text, wait=bool(body.get("wait")))


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
    | move | enable | disable | remove, name, when, do, under, before}."""
    found = _life(server, body)
    action = _one(body.get("action"))
    name = _one(body.get("name"))
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
    """GET {from, to}: the planned and the done entries (a week by default); POST {action:
    add | move | remove | pause_own | resume_own, ...}."""
    found = _life(server, body)
    action = _one(body.get("action"))
    if action == "add":
        found.calendar.add(body["title"], body["at"], until=body.get("until"), kind=body.get("kind") or "task",
                           repeat=body.get("repeat"), by="owner", note=body.get("note") or "")
    elif action == "move":
        found.calendar.move(body["id"], body["at"], until=body.get("until"))
    elif action == "remove":
        found.calendar.remove(body["id"])
    elif action in ("pause_own", "resume_own"):
        found.pause_own(action == "pause_own")
    elif action:
        raise ValueError("action is add, move, remove, pause_own or resume_own")
    return found.calendar.week(_one(body.get("from")), _one(body.get("to")))


def summary(server, body):
    """The summary of the stretch since the last one: what it did, learned, spent, and what
    waits for approval."""
    return _life(server, body).calendar.summary()


def settings(server, body):
    """GET: the identity's own settings (agent.*, spaces.<place>.proactive); POST {section, key,
    value}: change one (value null: back to the global one)."""
    found = _life(server, body)
    identity = found.identity
    if body.get("key") and not isinstance(body.get("key"), list):
        section = body.get("section") or "agent"
        if section == "learning":
            from .learning import MODES

            own = identity.settings_section("learning")
            value = body.get("value")
            if body["key"] == "mode" and value not in (None, *MODES):
                raise ValueError(f"learning.mode is one of {', '.join(MODES)}")
            if body["key"] == "admission" and value not in (None, "off", "fixture", "own_test", "by_environment"):
                raise ValueError("learning.admission is off, fixture, own_test or by_environment")
            if body["key"] not in ("mode", "admission", "review_model"):
                raise ValueError("learning has mode, admission and review_model")
            if value is None:
                own.pop(body["key"], None)
            else:
                own[body["key"]] = value
            identity.set_section("learning", own)
        elif section == "spaces":
            spaces = identity.settings_section("spaces")
            value = body.get("value")
            if value not in (None, "off", "learn", "do"):
                raise ValueError("spaces.<place>.proactive is off, learn or do")
            spaces.setdefault(body["key"], {})
            if value is None:
                spaces[body["key"]].pop("proactive", None)
            else:
                spaces[body["key"]]["proactive"] = value
            identity.set_section("spaces", spaces)
        else:
            identity.set_setting(body["key"], body.get("value"), section)
    from . import places as places_module

    return {"agent": identity.settings(), "learning": {"mode": found.learning.mode(),
                                                        **identity.settings_section("learning")}, "spaces": {row["id"]: places_module.proactive(identity, row)
                                                     for row in places_module.load(identity)}}


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
        shared = [{"name": row.get("name"), "path": str(row.get("path")), "read_only": True} for row in libraries()]
    except Exception:
        shared = []
    return {"skills": found.learning.skills(), "memory": found.identity.memory()["entries"],
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
from .frontends import channels as _channels, library_main as library_command  # noqa: E402

api["channels"] = _channels
