"""Package API for persistent dialogue. Core tasks never depend on these routes."""
from harness.sdk import Host
from .cli import model
from .state import Identity
from .session import Session
from .tasks import Tasks


def dialogue(server, body):
    identity = Identity(body.get("identity", "default"))
    host, port = server.server_address[:2]
    connection = Host(f"http://127.0.0.1:{port}", server.token)
    tasks = Tasks(connection, model=body.get("model"), workspace=body.get("workspace", "auto"), folder=body.get("folder"))
    session = Session(identity, model(body.get("model")), tasks, session=body.get("session"))
    return {"identity": identity.id, "session": session.id, "answer": session.turn(body["text"])}


def memory(server, body):
    return Identity(body.get("identity", "default")).memory()


api = {"dialogue": dialogue, "memory": memory}
