"""harness agent: persistent dialogue, independent of the core task CLI."""
import argparse
import json
from pathlib import Path
import tomllib
from harness.sdk import providers, model_list
from harness.sdk import data
from harness.sdk import ChatModel
from harness.sdk import Credentials, Settings
from .state import Identity
from .session import Session
from .tasks import Tasks


def model(identifier=None):
    directory = data()
    Credentials(directory).load()
    chosen = model_list.select(directory, identifier, native=True) or providers.load(directory)
    if chosen.get("provider") not in providers.PROVIDERS:
        raise ValueError("the persistent agent requires an enabled language model")
    path = providers.model_file(chosen, directory, Settings(directory).get()["model"])
    with path.open("rb") as stream:
        return ChatModel(tomllib.load(stream)["main"])


def main(arguments=None):
    parser = argparse.ArgumentParser(prog="harness agent", description="An optional persistent assistant over Harness tasks")
    parser.add_argument("text", nargs="?", help="one dialogue turn; omit for interactive chat")
    parser.add_argument("--identity", default="default")
    parser.add_argument("--session", help="continue a session of this identity")
    parser.add_argument("--model")
    parser.add_argument("--workspace", default="auto")
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--show-memory", action="store_true")
    args = parser.parse_args(arguments)
    identity = Identity(args.identity)
    if args.show_memory:
        print(json.dumps(identity.memory(), ensure_ascii=False, indent=2))
        return 0
    def approval(request):
        print(json.dumps(request, ensure_ascii=False, indent=2))
        try:
            accepted = input("Allow this task action? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            accepted = False
        return accepted, "user approved" if accepted else "user declined"
    tasks = Tasks(model=args.model, workspace=args.workspace,
                  folder=str(args.folder.resolve()) if args.folder else None, approval=approval)
    session = Session(identity, model(args.model), tasks, session=args.session)
    try:
        if args.text is not None:
            answer = session.turn(args.text)
            print(json.dumps({"identity": identity.id, "session": session.id, "answer": answer}, ensure_ascii=False)
                  if args.json else answer)
            return 0
        print(f"Agent {identity.id}; session {session.id}. /exit ends chat; task runs remain separately recorded.")
        while True:
            text = input("You: ").strip()
            if text == "/exit":
                return 0
            if text:
                print(session.turn(text))
    except EOFError:
        return 0
    except KeyboardInterrupt:
        pending = getattr(session, "state", {}).get("pending")
        if pending and pending.get("run"):
            tasks.cancel(pending["run"])
        return 130
