"""harness agent: identities and persistent dialogue, independent of the core task CLI.

    harness agent                      chat with the identity in this terminal
    harness agent say "TEXT"           say it in the main conversation (--chat CHAT) and print the
                                       answer; --no-wait: only queue it
    harness agent chats [-q TEXT] [--archived]      its chats; chats new | rename | pin | unpin |
                                       archive | unarchive | delete CHAT
    harness agent queue [--chat CHAT]  what waits there; queue edit | remove | send-now ID, clear, resume
    harness agent stop [--chat CHAT] [--hold]       stop the turn in progress (as Esc does)
    harness agent compact ["WHAT TO KEEP"] [--chat CHAT]   compact a chat's context now
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

COMMANDS = ("say", "new", "use", "list", "about", "rename", "delete", "memory", "chats", "queue", "stop", "compact")
# Taking it with you (take.py).
TAKE = ("share", "adopt", "backup", "restore", "retire", "import")
COMMANDS += TAKE


def model_config(identifier=None) -> dict:
    """The model role (ChatModel's configuration) of the model list's entry `identifier`
    (None: the default model), as the settings stand now."""
    directory = data()
    Credentials(directory).load()
    chosen = model_list.select(directory, identifier, native=True) or providers.load(directory)
    # A provider's model, or an agent signed in here that answers as the model (acp:<id>).
    if chosen.get("provider") not in providers.PROVIDERS and not providers.is_agent(chosen.get("provider")):
        raise ValueError("the persistent agent requires an enabled language model")
    advanced = dict(Settings(directory).get()["model"])
    # The default effort is a level of the default model: a model that does not have it (an
    # agent's model with other levels or none; a provider's whose levels are known) reasons
    # at its own default instead of being asked for a level it would refuse.
    effort, levels = advanced.get("reasoning_effort"), list(chosen.get("efforts") or ())
    if effort and effort != "default" and effort not in levels and (levels or providers.is_agent(chosen.get("provider"))):
        advanced["reasoning_effort"] = "default"
    path = providers.model_file(chosen, directory, advanced)
    with path.open("rb") as stream:
        return tomllib.load(stream)["main"]


def model(identifier=None):
    return ChatModel(model_config(identifier))


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
    parser = argparse.ArgumentParser(prog="the-harness agent", parents=[top],
                                     description="Identities that live on and talk with you, over Harness tasks")
    commands = parser.add_subparsers(dest="command")
    dialogue = argparse.ArgumentParser(add_help=False)
    dialogue.add_argument("--session", help="continue a session of this identity")
    dialogue.add_argument("--model")
    dialogue.add_argument("--workspace", default="auto")
    dialogue.add_argument("--folder", type=Path)
    say = commands.add_parser("say", parents=[common, dialogue], help="say it in a chat of the identity and "
                              "print the answer",
                              description="Say TEXT to the identity: it joins the queue of its life in the session "
                                          "host, behind what the app and the terminal chat said, and the answer is "
                                          "printed when its turn is over. With --session, --model, --workspace or "
                                          "--folder: one turn of a dialogue of its own in this process instead.")
    say.add_argument("text")
    say.add_argument("--chat", default="main", help="the chat (default: the main conversation)")
    say.add_argument("--no-wait", action="store_true", help="queue it and return at once")
    chats = commands.add_parser("chats", parents=[common], help="its chats: list, new, rename, pin, archive, delete, "
                                                               "place (where a chat works)")
    chats.add_argument("action", nargs="?", default="list",
                       choices=["list", "new", "rename", "pin", "unpin", "archive", "unarchive", "delete", "place"])
    chats.add_argument("chat", nargs="?", help="the chat's id (new: its title)")
    chats.add_argument("title", nargs="?", help="rename: the new title")
    chats.add_argument("--in", dest="folder", metavar="FOLDER",
                       help="new, place: the project folder the chat works in (connected when it was not), as a "
                            "session of Claude Code is opened on a project; place without it: nowhere in particular")
    chats.add_argument("--place", help="new, place: a connected place's id instead of a folder (a browser, the desktop)")
    chats.add_argument("--worktree", action="store_true",
                       help="new, place: work in an isolated copy of the project (a git worktree on the chat's own "
                            "branch) instead of the folder itself")
    chats.add_argument("--archived", action="store_true", help="list the archived chats instead")
    chats.add_argument("-q", "--query", help="list the chats whose title or words hold this text")
    chats.add_argument("--yes", action="store_true", help="delete without asking")
    queue = commands.add_parser("queue", parents=[common], help="the messages that wait in a chat: list, edit, "
                                "remove, clear, send-now, resume")
    queue.add_argument("action", nargs="?", default="list",
                       choices=["list", "edit", "remove", "clear", "send-now", "resume"])
    queue.add_argument("id", nargs="?", help="the message: its id, or its number in the list")
    queue.add_argument("text", nargs="?", help="edit: the new text")
    queue.add_argument("--chat", default="main", help="the chat (default: the main conversation)")
    compact = commands.add_parser("compact", parents=[common], help="compact a chat's context into a summary now")
    compact.add_argument("instructions", nargs="?", default="", help="what the summary should keep")
    compact.add_argument("--chat", default="main", help="the chat (default: the main conversation)")
    stop = commands.add_parser("stop", parents=[common], help="stop the turn in progress in a chat")
    stop.add_argument("--chat", default="main", help="the chat (default: the main conversation)")
    stop.add_argument("--hold", action="store_true", help="also hold the messages that wait there until "
                                                          "harness agent queue resume")
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
    chat = argparse.ArgumentParser(prog="the-harness agent", parents=[top, dialogue])
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
        state.first()   # a new user has the identity `default`, here as everywhere
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
    if command in ("chats", "queue", "stop", "compact") or (command == "say" and _through_host(args)):
        return _life_command(args)
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


def _through_host(args) -> bool:
    """Whether say goes into the identity's life (no option of the earlier in-process form)."""
    return args.session is None and args.model is None and args.folder is None and args.workspace == "auto"


def _life_command(args):
    """say, chats, queue and stop: what the terminal chat and the app do too, over the session host."""
    from .frontends import Client, clock

    client = Client(open_identity(args.identity).id)
    if args.command == "say":
        answer = client.say(args.text, args.chat, wait=not args.no_wait)
        if args.json:
            print(json.dumps(answer, ensure_ascii=False))
        elif args.no_wait:
            print(f"queued in {answer['chat']} ({client.identity}): harness agent queue shows what waits")
        else:
            print(f"[{client.identity}]", file=sys.stderr)
            if answer.get("interrupted"):
                print(f"(stopped: {answer['interrupted']})", file=sys.stderr)
            print(answer.get("answer") or "")
        return 0
    if args.command == "compact":
        answer = client.compact(args.chat, args.instructions)
        _print(args, answer, f"compacted {answer['messages']} messages of {answer['chat']} into a summary"
               if answer.get("compacted") else "nothing to compact yet")
        return 0
    if args.command == "stop":
        answer = client.stop(args.chat, args.hold)
        text = "stopped" if answer["stopped"] else "nothing was running"
        if answer["queued"]:
            text += f"; {answer['queued']} waiting" + (", held (harness agent queue resume)" if answer["held"] else
                                                       ", the next one starts")
        _print(args, answer, text)
        return 0
    if args.command == "queue":
        return _queue(args, client, clock)
    action = args.action
    where = None
    if action in ("new", "place"):
        where = client.project(args.folder) if args.folder else args.place
    if action == "new":
        chat = client.new_chat(args.chat, where, "worktree" if args.worktree else None)
        _print(args, {"chat": chat, "place": where}, f"new chat {chat}" + (f" in {where}" if where else "")
               + (" (an isolated copy)" if args.worktree else ""))
        return 0
    if action == "place":
        if not args.chat:
            raise ValueError("harness agent chats place CHAT [--in FOLDER | --place ID] [--worktree]")
        rows = client.chat_change("place", args.chat, place=where, isolation="worktree" if args.worktree else None)
        row = next((item for item in rows if item["chat"] == args.chat), {})
        _print(args, rows, f"{args.chat} works in {where}" + (f", in an isolated copy at {row.get('folder')} (branch "
                                                             f"{row.get('branch')})" if row.get("folder") else "")
               if where else f"{args.chat} works nowhere in particular: it decides per task")
        return 0
    if action != "list":
        if not args.chat or (action == "rename" and not args.title):
            raise ValueError(f"harness agent chats {action} CHAT" + (" TITLE" if action == "rename" else ""))
        if action == "delete" and not args.yes:
            if not interactive():
                print("harness agent: give --yes to delete without a terminal to ask", file=sys.stderr)
                return 2
            print(f"Delete the chat {args.chat} and its record? [y/N] ", end="", file=sys.stderr, flush=True)
            if input().strip().lower() not in ("y", "yes"):
                print("not deleted", file=sys.stderr)
                return 1
        rows = client.chat_change(action, args.chat, args.title)
        _print(args, rows, {"rename": f"{args.chat} is now {args.title}", "pin": f"pinned {args.chat}",
                            "unpin": f"unpinned {args.chat}", "archive": f"archived {args.chat}",
                            "unarchive": f"{args.chat} is back in the list",
                            "delete": f"deleted {args.chat}"}[action])
        return 0
    rows = client.chats(args.archived, args.query)
    lines = []
    for row in rows:
        marks = [word for word, on in (("working", row.get("busy")), ("pinned", row.get("pinned")),
                                       ("archived", row.get("archived")),
                                       (f"waits for {row.get('waiting')}", row.get("waiting")),
                                       (f"{row.get('unread')} new", row.get("unread"))) if on]
        lines.append(f"  {row['chat']:<20} {str(row['title'])[:44]:<44} {' · '.join(marks)}".rstrip())
        if row.get("match") and row["match"] != row["title"]:
            lines.append(f"  {'':<20} {row['match'][:100]}")
    empty = "no archived chats" if args.archived else "no chats match" if args.query else "no chats yet"
    _print(args, rows, "\n".join(lines) or empty)
    return 0


def _queue(args, client, clock):
    action = args.action.replace("-", "_")
    if action == "list":
        queue = client.queue(args.chat)
    else:
        given = args.id
        if action in ("edit", "remove", "send_now"):
            if not given or (action == "edit" and args.text is None):
                raise ValueError(f"harness agent queue {args.action} ID" + (" TEXT" if action == "edit" else ""))
            waiting = client.queue(args.chat)["queued"]
            if given.isdigit() and 1 <= int(given) <= len(waiting):
                given = waiting[int(given) - 1]["id"]  # its number in the list
        queue = client.queue_change(action, args.chat, given if action in ("edit", "remove", "send_now") else None,
                                    args.text if action == "edit" else None)
    lines = [f"{queue['chat']}" + (" · held (harness agent queue resume)" if queue["held"] else "")]
    running = queue.get("running")
    if running:
        lines.append(f"  now  {str(running.get('text') or '')[:70]}  (since {clock(running['since'])})")
    for number, row in enumerate(queue["queued"], 1):
        lines.append(f"  {number:>2}.  {str(row['text'])[:70]}  [{row['id']}]")
    if not running and not queue["queued"]:
        lines.append("  nothing waits and nothing runs")
    _print(args, queue, "\n".join(lines))
    return 0


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
    parser = argparse.ArgumentParser(prog="the-harness usage", description="What an agent identity spent on model calls "
                                     "today (reset at 0:00), by conversation and task, and its daily limits")
    parser.add_argument("--identity", help="the identity (default: the current one, harness agent use)")
    parser.add_argument("--range", choices=["today", "week", "month"], help="the stretch: today (default), week "
                        "(the last 7 days) or month (the last 30)")
    parser.add_argument("--from", dest="start", metavar="DAY", help="from this day (YYYY-MM-DD) instead of a range")
    parser.add_argument("--to", dest="end", metavar="DAY", help="to this day (default: today)")
    parser.add_argument("--week", action="store_true", help="the same as --range week")
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
    stretch = args.range or ("week" if args.week else "today")
    try:
        span = account.span(stretch, start=args.start, end=args.end)
    except ValueError as error:
        print(f"harness usage: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"identity": identity.id, **span, "today": account.day(),
                          **({"week": account.week()} if args.week else {})}, ensure_ascii=False, indent=2))
        return 0
    print(f"{identity.id} ({identity.name})")
    print("\n".join(spending.report(account)))
    if span["range"] != "today":
        from .chats import Chats

        chats = Chats(identity)
        titles = {chat: chats.meta(chat).get("title") for chat in chats.ids()}
        print("\n".join(spending.span_lines(span, titles)))
    return 0
