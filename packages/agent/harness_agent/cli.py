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
    harness agent share ID --to PLACE  as a package (after showing what becomes public); --card
    harness agent adopt SOURCE         a new identity from a shared one or a character card
    harness agent backup ID            encrypted with a passphrase; restore FILE on another computer
    harness agent retire ID            stop it here after it moved
    harness agent import openclaw|hermes   bring one over: persona, memory, skills
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
# Taking it with you (take.py).
TAKE = ("share", "adopt", "backup", "restore", "retire", "import")
COMMANDS += TAKE


def model(identifier=None):
    directory = data()
    Credentials(directory).load()
    chosen = model_list.select(directory, identifier, native=True) or providers.load(directory)
    # A provider's model, or an agent signed in here that answers as the model (acp:<id>).
    if chosen.get("provider") not in providers.PROVIDERS and not providers.is_agent(chosen.get("provider")):
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
    _take_parsers(commands, common)
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
    if command in TAKE:
        return _take(args)
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


def _take_parsers(commands, common):
    """harness agent share, adopt, backup, restore, retire and import (take.py)."""
    share = commands.add_parser("share", parents=[common], help="share it as a package: persona, avatar, skills, "
                                "reactions; never its key or credentials",
                                epilog="harness agent share default --to github:you/yu-agent; harness agent share "
                                       "default --to ./shared; harness agent share default --card --to yu.png")
    share.add_argument("id", help="the identity to share")
    share.add_argument("--to", required=True, help="github:OWNER/REPO[#FOLDER], git:URL[#FOLDER], USER@HOST:FOLDER, "
                       "a folder or .tar.gz file here; with --card a .png or .json file")
    share.add_argument("--with-memory", action="store_true", help="also its memory and USER.md")
    share.add_argument("--public", action="store_true", help="a GitHub repository it creates is public "
                       "(default: private)")
    share.add_argument("--card", action="store_true", help="a Character Card V3 with only its name, persona and avatar")
    share.add_argument("--name", help="the package's name (default: the id)")
    share.add_argument("--version", dest="package_version", metavar="VERSION", help="the package's version")
    share.add_argument("--url", help="the web address of the folder an archive goes to")
    share.add_argument("--yes", "-y", action="store_true", help="publish without asking (after printing what goes)")
    adopt = commands.add_parser("adopt", parents=[common], help="a new identity from a shared one or a character card")
    adopt.add_argument("source", nargs="?", help="its link (github:OWNER/REPO, a git or archive URL), folder, "
                       "archive, or character card (.png, .json)")
    adopt.add_argument("--id", dest="new_id", help="the new identity's id (default: from its name)")
    adopt.add_argument("--test", action="store_true", help="run the own test of each adopted skill that waits for it "
                       "(of the adopted identity, or of --identity without a source)")
    backup = commands.add_parser("backup", parents=[common], help="a full backup encrypted with a passphrase")
    backup.add_argument("id", help="the identity to back up")
    backup.add_argument("-o", "--output", type=Path, help="the file (default: ID.harness-backup)")
    backup.add_argument("--with-keys", action="store_true", help="also the model keys (they are global)")
    restore = commands.add_parser("restore", parents=[common], help="restore a backup on this computer")
    restore.add_argument("file", type=Path)
    restore.add_argument("--replace", action="store_true", help="restore over an identity of that id here (the one "
                         "here is kept aside)")
    retire = commands.add_parser("retire", parents=[common], help="stop it on this computer after it moved")
    retire.add_argument("id")
    retire.add_argument("--yes", action="store_true", help="do not ask")
    bring = commands.add_parser("import", parents=[common], help="bring an OpenClaw or Hermes agent over: persona, "
                                "memory and skills, never its channel tokens")
    bring.add_argument("kind", choices=("openclaw", "hermes"))
    bring.add_argument("folder", nargs="?", type=Path, help="its workspace or profile (default: where it keeps it)")
    bring.add_argument("--id", dest="new_id", help="the new identity's id")


def _passphrase(prompt, *, twice=False):
    import getpass
    import os

    given = os.environ.get("HARNESS_BACKUP_PASSPHRASE")
    if given:
        return given
    if not interactive():
        raise ValueError("a passphrase is asked in a terminal; a script sets HARNESS_BACKUP_PASSPHRASE")
    first = getpass.getpass(prompt)
    if twice and getpass.getpass("again: ") != first:
        raise ValueError("the two passphrases differ")
    return first


def _show_preview(preview, *, destination, private=None):
    """Everything that becomes public, before the owner says yes."""
    print(f"  to {destination}" + (f" ({preview['creates']} repository, created)" if preview.get("creates") else "")
          + ("" if private is None else f" · {'private' if private else 'public'} if created"), file=sys.stderr)
    print("  public:", file=sys.stderr)
    for row in preview["texts"]:
        print(f"  ── {row['file']}", file=sys.stderr)
        for line in row["text"].rstrip("\n").splitlines() or [""]:
            print(f"     {line}", file=sys.stderr)
    for name in preview.get("other_files") or ():
        print(f"  ── {name}", file=sys.stderr)
    if preview.get("replaced"):
        print(f"  replaced: {', '.join(f'{k} for {v}' for k, v in preview['replaced'].items())}", file=sys.stderr)
    print(f"  not included: {' · '.join(preview['left_out'])}", file=sys.stderr)


def _take(args):
    from . import take

    try:
        return _take_run(args, take)
    except ValueError as error:
        print(f"harness agent {args.command}: {error}", file=sys.stderr)
        return 2


def _take_run(args, take):
    command = args.command

    def confirm(preview):
        _show_preview(preview, destination=args.to, private=None if args.card else not args.public)
        if args.yes:
            return True
        if not interactive():
            print("harness agent share --yes publishes it", file=sys.stderr)
            return False
        return input("Publish? [y/N] ").strip().lower() in ("y", "yes")

    if command == "share":
        identity = Identity(state.resolve(args.id), create=False)
        if args.card:
            result = take.share_card(identity, args.to, confirm=confirm)
        else:
            result = take.share(identity, args.to, name=args.name, version=args.package_version,
                                with_memory=args.with_memory, public=args.public, url=args.url or "", confirm=confirm,
                                log=lambda text: print(text, file=sys.stderr))
        if result.get("needs_consent"):
            return 1
        _print(args, result, f"✓ {result['sent']}" + (f"\nOthers adopt it with:\n  {result['install']}"
                                                       if result.get("install") else ""))
        return 0
    if command == "adopt":
        if not args.source:
            if not args.test:
                raise ValueError("give what to adopt: a link, a folder, an archive or a character card")
            results = take.test_adopted(open_identity(args.identity))
            _print(args, results, "\n".join(f"{'✓' if r['ok'] else '✗'} {r['skill']}: {r['evidence']}" for r in results)
                   or "no adopted skill waits for its test")
            return 0
        result = take.adopt(args.source, id=args.new_id, log=lambda text: print(text, file=sys.stderr))
        if args.test:
            result["tested"] = take.test_adopted(Identity(result["identity"], create=False))
        _print(args, result, f"✓ new identity {result['identity']} ({result['name']}) · new key · "
               f"{len(result['skills'])} skills → proposed · {len(result['reactions'])} reactions off until you "
               "enable them" + ("" if args.test or not result["skills"] else
                                f"\n  each skill runs after its own test passes here: harness agent adopt --test "
                                f"--identity {result['identity']}"))
        return 0
    if command == "backup":
        identity = Identity(state.resolve(args.id), create=False)
        output = args.output or Path(f"{identity.id}.harness-backup")
        print("The backup holds the private key, memory and this identity's channel credentials"
              + (" and the model keys" if args.with_keys else "") + "; keep it private.", file=sys.stderr)
        result = take.backup(identity, output, _passphrase("passphrase: ", twice=True), with_keys=args.with_keys)
        _print(args, result, f"✓ {output} · encrypted · model keys "
               + ("included" if args.with_keys else "not included (--with-keys)"))
        return 0
    if command == "restore":
        result = take.restore(args.file, _passphrase("passphrase: "), replace=args.replace)
        _print(args, result, f"✓ {result['identity']} {result['name']}"
               + (f" · log in to channels again: {', '.join(result['channels'])}" if result["channels"] else "")
               + (f" · model keys: {', '.join(result['model_keys'])}" if result["model_keys"] else ""))
        return 0
    if command == "retire":
        identity = Identity(args.id, create=False)
        state.check_here(identity.directory)
        if not args.yes and interactive():
            print(f"Retire {identity.id} ({identity.name}) on this computer? It stops here, and opening it here "
                  "says it has moved. [y/N] ", end="", file=sys.stderr, flush=True)
            if input().strip().lower() not in ("y", "yes"):
                return 1
        result = take.retire(identity)
        _print(args, result, "✓ stopped · opening it here says it has moved")
        return 0
    result = take.import_from(args.kind, args.folder, id=args.new_id)
    _print(args, result, f"✓ new identity {result['identity']} ({result['name']}) from {args.kind}: "
           f"{result['memory_entries']} memory entries, {len(result['skills'])} skills (proposed); "
           f"no channel tokens or keys\n  {result['suggest']}")
    return 0


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
