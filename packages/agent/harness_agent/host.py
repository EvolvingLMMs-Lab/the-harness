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
    """What an identity spent today ({identity, today}; week: the last seven days too)."""
    identity = _identity(body)
    account = identity.account()
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
    return found.say(body.get("chat") or "main", body["text"], wait=bool(body.get("wait")))


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


api = {"dialogue": dialogue, "life": life, "chats": chats, "chat": chat, "say": say, "opened": opened,
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
