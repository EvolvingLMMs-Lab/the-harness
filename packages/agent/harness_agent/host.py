"""What the agent package gives the session host and the core's frontends (the core calls
these by name, harness/extensions.py, and imports nothing of this package):

    api        /api/agent/dialogue, /api/agent/memory, /api/agent/identities,
               /api/agent/identity (new, use, rename, delete)
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
    return Identity(state.resolve(body.get("identity")), create=False)


def dialogue(server, body):
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


api = {"dialogue": dialogue, "memory": memory, "identities": identities, "identity": identity_change}


def identity(name=None, ask=None) -> dict:
    """The identity a terminal chat runs as: `name` (--identity), else the current or only
    one, else `ask(ids)` (None: an error). Its life is claimed for the calling process.
    {id, name, runtime, release}: runtime is what its conversations carry, release() lets go
    of the life when the chat closes."""
    chosen = Identity(state.resolve(name, ask=ask), create=False)
    claimed = chosen.live()
    return {"id": chosen.id, "name": chosen.name, "runtime": Tasks(identity=chosen).runtime(),
            "release": (lambda: None) if claimed["attached"] else (lambda: state.release(chosen))}
