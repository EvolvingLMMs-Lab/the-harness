"""harness agent: identities and persistent dialogue, independent of the core task CLI.

    harness agent                      chat with the identity in this terminal
    harness agent say "TEXT"           one turn
    harness agent new ID [--name NAME] [--from ID] [--card FILE]
    harness agent use ID               the current identity
    harness agent list [-v]            the identities (-v: key fingerprints)
    harness agent about [-v]           this identity
    harness agent rename NAME          its display name (the id stays)
    harness agent delete ID            after listing what goes, and asking
    harness agent memory               its memory entries
    harness usage [--week]             what an identity spent today (and this week)

Each acts on --identity, else the current identity, else the only one; with several and
none chosen a terminal asks and a script fails. `harness agent "TEXT"` is the earlier form
of say and keeps working for one release."""
import argparse
import json
from pathlib import Path
import sys
import tomllib
from harness.sdk import providers, model_list
from harness.sdk import data
from harness.sdk import ChatModel
from harness.sdk import Credentials, Settings
from harness.sdk import SpendingLimit, spending
from . import state
from .state import Identity, IdentityError
from .session import Session
from .tasks import Tasks

COMMANDS = ("say", "new", "use", "list", "about", "rename", "delete", "memory")


def model(identifier=None):
    directory = data()
    Credentials(directory).load()
    chosen = model_list.select(directory, identifier, native=True) or providers.load(directory)
    if chosen.get("provider") not in providers.PROVIDERS:
        raise ValueError("the persistent agent requires an enabled language model")
    path = providers.model_file(chosen, directory, Settings(directory).get()["model"])
    with path.open("rb") as stream:
        return ChatModel(tomllib.load(stream)["main"])


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def open_identity(name=None) -> Identity:
    """The identity a command acts on (state.resolve): a terminal is asked, a script fails."""
    return Identity(state.resolve(name, ask=state.terminal_choice if interactive() else None), create=False)


def _parser():
    def options(default):
        given = argparse.ArgumentParser(add_help=False)
        given.add_argument("--identity", default=default,
                           help="the identity (default: the current one, harness agent use)")
        given.add_argument("--json", action="store_true", default=default or False, help="print JSON")
        return given
    # Given before the command or after it: the command's parser keeps what came before.
    top, common = options(None), options(argparse.SUPPRESS)
    parser = argparse.ArgumentParser(prog="harness agent", parents=[top],
                                     description="Identities that live on and talk with you, over Harness tasks")
    commands = parser.add_subparsers(dest="command")
    dialogue = argparse.ArgumentParser(add_help=False)
    dialogue.add_argument("--session", help="continue a session of this identity")
    dialogue.add_argument("--model")
    dialogue.add_argument("--workspace", default="auto")
    dialogue.add_argument("--folder", type=Path)
    say = commands.add_parser("say", parents=[common, dialogue], help="one dialogue turn")
    say.add_argument("text")
    new = commands.add_parser("new", parents=[common], help="a new identity")
    new.add_argument("id", help="its id: letters, digits, _ and -; it never changes")
    new.add_argument("--name", help="its display name, in any language (default: the id)")
    new.add_argument("--from", dest="source", help="clone persona, skills and reactions of this identity (no memory)")
    new.add_argument("--card", type=Path, help="a character card (.png or .json): name, persona, avatar")
    use = commands.add_parser("use", parents=[common], help="choose the current identity")
    use.add_argument("id")
    listed = commands.add_parser("list", parents=[common], help="the identities")
    listed.add_argument("-v", "--verbose", action="store_true", help="also key fingerprints")
    about = commands.add_parser("about", parents=[common], help="this identity")
    about.add_argument("-v", "--verbose", action="store_true", help="also its key fingerprint")
    rename = commands.add_parser("rename", parents=[common], help="change the display name (the id stays)")
    rename.add_argument("name")
    delete = commands.add_parser("delete", parents=[common], help="delete an identity")
    delete.add_argument("id")
    delete.add_argument("--yes", action="store_true", help="do not ask")
    commands.add_parser("memory", parents=[common], help="its memory entries")
    chat = argparse.ArgumentParser(prog="harness agent", parents=[top, dialogue])
    chat.add_argument("--show-memory", action="store_true", help=argparse.SUPPRESS)
    return parser, chat


def main(arguments=None):
    words = list(sys.argv[1:] if arguments is None else arguments)
    parser, chat = _parser()
    at = _first_positional(words)
    if at is not None and words[at] not in COMMANDS:
        # harness agent "TEXT": the form before say.
        print('harness agent "TEXT" is now harness agent say "TEXT"; the earlier form goes away in the next '
              "release", file=sys.stderr)
        words.insert(at, "say")
    try:
        if at is not None or any(word in ("-h", "--help") for word in words):
            args = parser.parse_args(words)
        else:
            args = chat.parse_args(words)
            args.command = None
        return _run(args)
    except IdentityError as error:
        print(f"harness agent: {error}", file=sys.stderr)
        return 2
    except SpendingLimit as error:
        print(f"harness agent: {error} ({_raise_hint(error)})", file=sys.stderr)
        return 3


def _first_positional(words):
    """The index of the first word that is no option or option value, or None."""
    takes = {"--identity", "--session", "--model", "--workspace", "--folder"}
    skip = False
    for index, word in enumerate(words):
        if skip:
            skip = False
            continue
        if word in takes:
            skip = True
            continue
        if not word.startswith("-"):
            return index
    return None


def _raise_hint(error) -> str:
    return ("harness usage --raise-today DOLLARS" if "budget" in str(error)
            else "harness usage --calls N")


def _print(args, value, text):
    print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else text)


def _run(args):
    command = args.command
    if command == "new":
        identity = state.create(args.id, display=args.name, source=args.source, card=args.card)
        _print(args, identity.to_dict(), f"new identity {identity.id} ({identity.name}): {identity.directory}"
               + ("" if state.current() else f"\nharness agent use {identity.id} makes it the current one"))
        return 0
    if command == "use":
        state.use(args.id)
        identity = Identity(args.id, create=False)
        _print(args, identity.to_dict(), f"current identity: {identity.id} ({identity.name})")
        return 0
    if command == "list":
        chosen = state.current()
        rows = [{**Identity(name, create=False).to_dict(verbose=args.verbose), "current": name == chosen}
                for name in state.identities()]
        lines = []
        for row in rows:
            mark = "*" if row["current"] else " "
            lines.append(f"{mark} {row['id']:<20} {row['name']}" + (f"  {row['fingerprint']}" if args.verbose else ""))
        _print(args, rows, "\n".join(lines) or "no identities yet")
        return 0
    if command == "delete":
        return _delete(args)
    identity = open_identity(args.identity)
    if command == "about":
        row = {**identity.to_dict(verbose=args.verbose), "current": identity.id == state.current(),
               "sessions": len(identity.sessions()), "memory_entries": len(identity.memory()["entries"])}
        _print(args, row, "\n".join(f"{key}: {value}" for key, value in row.items()))
        return 0
    if command == "rename":
        identity.rename(args.name)
        _print(args, identity.to_dict(), f"{identity.id} is now called {identity.name}")
        return 0
    if command == "memory" or getattr(args, "show_memory", False):
        print(json.dumps(identity.memory(), ensure_ascii=False, indent=2))
        return 0
    return _dialogue(args, identity)


def _delete(args):
    identity = Identity(args.id, create=False)
    sessions = identity.sessions()
    spent = identity.account().day()
    print(f"Delete identity {identity.id} ({identity.name}): {len(sessions)} conversations, "
          f"{len(identity.memory()['entries'])} memory entries, its learning library, its key pair and its "
          f"spending record (today {spending.usd(spent['cost_usd'])}, {spent['calls']} calls). "
          "Its channels: none bound. This cannot be undone.", file=sys.stderr)
    if not args.yes:
        if not interactive():
            print("harness agent: give --yes to delete without a terminal to ask", file=sys.stderr)
            return 2
        print(f"Type the id ({identity.id}) to delete it: ", end="", file=sys.stderr, flush=True)
        try:
            if input().strip() != identity.id:
                print("not deleted", file=sys.stderr)
                return 1
        except EOFError:
            return 1
    state.delete(identity.id)
    _print(args, {"deleted": identity.id}, f"deleted {identity.id}")
    return 0


def _dialogue(args, identity):
    def approval(request):
        print(json.dumps(request, ensure_ascii=False, indent=2))
        try:
            accepted = input("Allow this task action? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            accepted = False
        return accepted, "user approved" if accepted else "user declined"
    identity.live()
    tasks = Tasks(model=args.model, workspace=args.workspace,
                  folder=str(args.folder.resolve()) if args.folder else None, approval=approval, identity=identity)
    session = Session(identity, model(args.model), tasks, session=args.session)
    try:
        if args.command == "say":
            answer = session.turn(args.text)
            if args.json:
                print(json.dumps({"identity": identity.id, "session": session.id, "answer": answer}, ensure_ascii=False))
            else:
                print(f"[{identity.id} · {identity.name}]", file=sys.stderr)
                print(answer)
            return 0
        print(f"Agent {identity.id} ({identity.name}); session {session.id}. /exit ends chat; task runs remain "
              "separately recorded.")
        while True:
            text = input("You: ").strip()
            if text == "/exit":
                return 0
            if text:
                try:
                    print(session.turn(text))
                except SpendingLimit as error:
                    print(f"({error}; {_raise_hint(error)})")
    except EOFError:
        return 0
    except KeyboardInterrupt:
        pending = getattr(session, "state", {}).get("pending")
        if pending and pending.get("run"):
            tasks.cancel(pending["run"])
        return 130


def usage(arguments=None):
    """harness usage: what an identity's model calls cost today and this week, and its limits."""
    parser = argparse.ArgumentParser(prog="harness usage", description="What an agent identity spent on model calls "
                                     "today (reset at 0:00), by conversation and task, and its daily limits")
    parser.add_argument("--identity", help="the identity (default: the current one, harness agent use)")
    parser.add_argument("--week", action="store_true", help="also the last seven days")
    parser.add_argument("--raise-today", type=float, metavar="DOLLARS", help="today's budget becomes DOLLARS; "
                        "tomorrow it is the setting again")
    parser.add_argument("--budget", type=float, metavar="DOLLARS", help="this identity's daily budget from now on "
                        "(agent.daily_budget for this identity)")
    parser.add_argument("--calls", type=int, metavar="N", help="this identity's daily calls without a price "
                        "(agent.daily_calls for this identity)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(arguments)
    try:
        identity = open_identity(args.identity)
        if args.budget is not None:
            identity.set_setting("daily_budget", args.budget)
        if args.calls is not None:
            identity.set_setting("daily_calls", args.calls)
        account = identity.account()
        if args.raise_today is not None:
            account.raise_today(args.raise_today)
    except IdentityError as error:
        print(f"harness usage: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"harness usage: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"identity": identity.id, "today": account.day(),
                          **({"week": account.week()} if args.week else {})}, ensure_ascii=False, indent=2))
        return 0
    print(f"{identity.id} ({identity.name})")
    print("\n".join(spending.report(account, week=args.week)))
    return 0
