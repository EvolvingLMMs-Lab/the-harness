"""The agent's entries in the command line and in Python, over the session host: what the app,
the terminal chat (/calendar, /channels, /library, /usage) and these show is one life, read
and changed through the host's /api/agent routes, never through the files the life owns.

    harness calendar [list] [--from ISO] [--to ISO]     a week: what it did, who, the outcome
    harness calendar add TITLE --at TIME [--until TIME] [--kind KIND] [--repeat daily|weekly]
    harness calendar update ID [--title T] [--at TIME] [--until TIME | --no-until] [--kind KIND]
    harness calendar move ID --at TIME [--until TIME]
    harness calendar remove ID
    harness calendar restore [ID]                       put back what was removed (default: the last)
    harness calendar pause [--off]                      pause (or resume) what it does on its own
    harness channels [list]                             the channel accounts and pairing requests
    harness channels kinds                              the kinds the installed packages provide
    harness channels add KIND [--FIELD VALUE ...] [--group ID ...] [--mode MODE]
    harness channels set ACCOUNT --FIELD VALUE ...      change an account's settings
    harness channels groups ACCOUNT [--enter ID ...] [--leave ID] [--mode MODE]
    harness channels owner-code ACCOUNT                 a new code that binds the owner
    harness channels remove ACCOUNT
    harness channels pair [approve ACCOUNT CODE | revoke ACCOUNT USER]
    harness channels test ACCOUNT                       whether the account works now
    harness skills [list]                               its skills: evidence, uses, where from
    harness skills sources                              where its skills are taken from
    harness skills add SOURCE | test SOURCE | update [ID] | remove ID [--keep]
    harness library skills | tree [PATH] | memory | undo NAME   (the core's harness library)

Each acts on --identity, else the current identity, else the only one; a terminal is asked
when several are left, a script fails. The same calls are harness.sdk.Agent's methods
(sdk.py). A channel is whatever an installed package declares (channels.py): its kinds, the
fields each asks for and the steps of connecting an account are read from the declarations,
and no channel is named here."""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from . import state
from .channels import channels  # noqa: F401  (the host route /api/agent/channels)
from .state import IdentityError

# What an evidence level is called wherever it is shown.
EVIDENCE = {"builtin": "built in", "owner": "added by owner", "proposed": "proposed", "own_test": "own test",
            "replayed": "replayed", "effective": "effective", "archived": "archived", "undone": "undone",
            "failed own test": "failed own test"}
# The mark of an outcome, as the terminal chat draws it.
MARKS = {"done": "✓", "refused": "⊘", "failed": "✗", "unknown": "?", "cancelled": "–", "waiting": "●"}


# -- the client: one identity's routes on the session host ------------------------------------

def connect():
    """The session host of this user, started when none runs (harness.sdk.Host)."""
    from harness.sdk import Host

    return Host.connect()


class Client:
    """The /api/agent routes for one identity."""

    def __init__(self, identity: str, host=None):
        self.identity = identity
        self.host = host or connect()

    def get(self, name, **query) -> dict:
        given = {key: value for key, value in {"identity": self.identity, **query}.items() if value not in (None, "")}
        return self.host.get(f"/api/agent/{name}?{urlencode(given)}")

    def post(self, name, body=None, timeout=None) -> dict:
        return self.host.post(f"/api/agent/{name}", {"identity": self.identity, **(body or {})}, timeout)

    # One to one with the commands (and harness.sdk.Agent).

    def chats(self, archived=False, q=None) -> list:
        return self.get("chats", archived=1 if archived else None, q=q)["chats"]

    def chat_change(self, action, chat, title=None, **more) -> list:
        return self.post("chats", {"action": action, "chat": chat, **({"title": title} if title is not None else {}),
                                   **more})["chats"]

    def chat(self, chat="main", after=0) -> dict:
        return self.get("chat", chat=chat, after=after or None)

    def attach(self, path, chat="main") -> dict:
        import base64
        import mimetypes

        file = Path(path).expanduser()
        return self.post("attach", {"chat": chat, "name": file.name,
                                    "type": mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                                    "data": base64.b64encode(file.read_bytes()).decode("ascii")}, timeout=120)

    def say(self, text, chat="main", wait=False, timeout=None, files=()) -> dict:
        if files:
            # Files of this computer go with the message: attached first, then named by their ids.
            ids = [self.attach(path, chat)["id"] for path in files]
            sent = self.post("say", {"chat": chat, "text": text, "files": ids})
            if not wait:
                return sent
            raise ValueError("a message with files is sent without waiting (wait=False); its answer is in the chat")
        if not wait:
            return self.post("say", {"chat": chat, "text": text})
        seconds = float(timeout or 900)
        return self.post("dialogue", {"chat": chat, "text": text, "timeout": seconds}, timeout=seconds + 30)

    def new_chat(self, title=None, place=None, isolation=None) -> str:
        return self.post("new_chat", {**({"title": title} if title else {}), **({"place": place} if place else {}),
                                      **({"isolation": isolation} if isolation else {})})["chat"]

    def project(self, folder) -> str:
        """The id of the place of the project `folder`, connected now when it was not."""
        return self.post("places", {"action": "project", "folder": str(folder)})["place"]

    def queue(self, chat="main") -> dict:
        return self.get("queue", chat=chat)

    def compact(self, chat="main", instructions="") -> dict:
        return self.post("compact", {"chat": chat, "instructions": instructions}, timeout=660)

    def queue_change(self, action, chat="main", id=None, text=None) -> dict:
        return self.post("queue", {"chat": chat, "action": action, **({"id": id} if id is not None else {}),
                                   **({"text": text} if text is not None else {})})

    def stop(self, chat="main", hold=False) -> dict:
        return self.post("stop", {"chat": chat, "hold": bool(hold)})

    def memory(self) -> dict:
        return self.get("memory")

    def reactions(self, path="") -> dict:
        return self.get("tree", path="/".join(path) if isinstance(path, (list, tuple)) else path)

    def learned(self) -> dict:
        return self.get("learned")

    def undo(self, name) -> dict:
        return self.post("learned", {"action": "undo", "name": name})

    def usage(self, week=False, range=None, start=None, end=None) -> dict:
        return self.get("usage", week=1 if week else None, range=range, **{"from": start, "to": end})

    def calendar(self, start=None, end=None, q=None) -> dict:
        return self.get("calendar", **{"from": _iso(start), "to": _iso(end)}, q=q)

    def calendar_change(self, action, **fields) -> dict:
        return self.post("calendar", {"action": action, **{k: v for k, v in fields.items() if v is not None}})

    def life(self) -> dict:
        return self.get("life")

    def settings(self) -> dict:
        return self.get("settings")

    def set_setting(self, key, value) -> dict:
        return self.post("settings", {"key": key, "value": value})

    def channels(self, account=None) -> list:
        return self.get("channels", account=account)["channels"]

    def channel_kinds(self) -> dict:
        """{kinds: [declaration], problems, from}: what the installed packages provide."""
        found = self.get("channels")
        return {key: found.get(key) for key in ("kinds", "problems", "from")}

    def channel(self, action, **fields) -> dict:
        return self.post("channels", {"action": action, **{k: v for k, v in fields.items() if v is not None}})

    def skill_sources(self) -> dict:
        return self.get("skill_sources")

    def skill_source(self, action, **fields) -> dict:
        given = {key: value for key, value in fields.items() if value is not None}
        if given.get("from"):
            # A folder or file named from here is the host's by its whole path.
            local = Path(str(given["from"])).expanduser()
            if local.exists():
                given["from"] = str(local.resolve())
        # Reading a repository can take a while.
        return self.post("skill_sources", {"action": action, **given}, timeout=330)


def _iso(value):
    """A time for the host: ISO as given, seconds or a datetime turned into ISO."""
    from datetime import datetime

    if value is None or isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return datetime.fromtimestamp(float(value)).isoformat()


# -- the command line ------------------------------------------------------------------------

def _common():
    given = argparse.ArgumentParser(add_help=False)
    given.add_argument("--identity", help="the identity (default: the current one, harness agent use)")
    given.add_argument("--json", action="store_true", help="print JSON")
    return given


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def _client(args) -> Client:
    name = state.resolve(args.identity, ask=state.terminal_choice if _interactive() else None)
    return Client(name)


def _print(args, value, lines):
    if args.json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines))


def _guard(command, run):
    from harness.sdk import UsageError

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # a console whose code page lacks ✓ or ›
    from harness.sdk import problems

    try:
        return run()
    except (IdentityError, UsageError, ValueError, KeyError) as error:
        # What was asked for cannot be done as given: exit status 2, as a usage error.
        print(problems.said(error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # the host's answer (a Problem with its fix) or the connection
        print(problems.said(error), file=sys.stderr)
        return 1


def clock(seconds) -> str:
    return time.strftime("%H:%M", time.localtime(seconds))


def day_name(seconds) -> str:
    return time.strftime("%a %m-%d", time.localtime(seconds))


def calendar_rows(week: dict) -> list:
    """The week as rows the terminal shows: {day, time, mark, kind, title, tail, id, planned}."""
    rows = []
    now = time.time()
    for entry in week.get("entries") or ():
        planned = bool(entry.get("planned"))
        kind = entry.get("kind")
        who = entry.get("who")
        if kind == "asleep":
            label, mark = "asleep", "☾"
            tail = f"until {clock(entry['end'])}"
        elif kind == "reaction":
            label, mark, tail = "tree", MARKS.get(entry.get("outcome") or "", "·"), entry.get("note") or ""
        elif planned:
            label = "yours" if entry.get("by") == "owner" else "planned"
            mark = MARKS["done"] if entry.get("outcome") == "done" else "·"
            tail = entry.get("kind") if entry.get("kind") not in ("task", None) else ""
            if entry.get("missed"):
                # Put at a time that had passed: it never came due, and nothing was done for it.
                tail = " · ".join(part for part in (tail, "missed") if part)
        else:
            label = {"owner": "owner", "tree": "tree", "own": "own"}.get(who, who or kind or "")
            outcome = entry.get("outcome")
            mark = MARKS["refused"] if entry.get("refused") else MARKS.get(outcome or "", "·")
            tail = " · ".join(part for part in (outcome if outcome not in (None, "done", "refused") else "",
                                                 "safety refused" if entry.get("refused") else "",
                                                 entry.get("note") or "") if part)
        rows.append({"day": day_name(entry["start"]), "time": clock(entry["start"]), "mark": mark, "kind": label,
                     "title": str(entry.get("title") or ""), "tail": str(tail or ""), "id": entry.get("id"),
                     "planned": planned, "upcoming": planned and entry["start"] > now, "start": entry["start"]})
    return rows


def calendar_lines(week, usage=None, name="") -> list:
    start, end = week.get("start"), week.get("end")
    head = f"Calendar · {day_name(start)} – {day_name(end - 1)}" if start and end else "Calendar"
    lines = [head + (f" · {name}" if name else "")]
    if usage:
        today = usage.get("today") or usage
        budget = float(today.get("daily_budget") or 0)
        if budget > 0:
            lines.append(f"on its own ${float(today.get('own_usd') or 0):.2f} / "
                         f"${max(0.0, budget - float(today.get('reserve') or 0)):.2f} · "
                         f"${float(today.get('reserve') or 0):.2f} kept for you")
        else:
            lines.append(f"on its own ${float(today.get('own_usd') or 0):.2f} · no daily limit")
    lines.append("─" * 76)
    rows = calendar_rows(week)
    done = [row for row in rows if not row["upcoming"]]
    upcoming = [row for row in rows if row["upcoming"]]
    day = None
    for row in done:
        if row["day"] != day:
            day = row["day"]
            lines.append(day)
        lines.append(_calendar_line(row))
    if upcoming:
        lines += ["", "next"]
        lines += [_calendar_line(row, with_day=True) for row in upcoming]
    if not rows:
        lines.append("nothing this week yet")
    lines.append("")
    lines.append("on its own: paused" if week.get("paused_own") else "on its own: on")
    return lines


def _calendar_line(row, with_day=False) -> str:
    when = f"{row['day'][:3]} {row['time']}" if with_day else row["time"]
    tail = f"  {row['tail']}" if row["tail"] else ""
    ident = f"  [{row['id']}]" if row["planned"] and row.get("id") else ""
    return f"  {when:<9} {row['mark']:<2} {row['kind']:<8} {row['title'][:48]:<48}{tail}{ident}"


def calendar_main(arguments=None):
    """harness calendar: the identity's calendar (as /calendar and the app's Calendar)."""
    common = _common()
    parser = argparse.ArgumentParser(prog="the-harness calendar", parents=[common],
                                     description="The identity's calendar: what it did and when (the tree's "
                                                 "reactions, what it did on its own, what you asked, refusals, "
                                                 "outcomes, when it was asleep) and what is planned")
    commands = parser.add_subparsers(dest="command")
    listed = commands.add_parser("list", parents=[common], help="a week (default: this one)")
    for command in (parser, listed):
        command.add_argument("--from", dest="start", help="from this time (ISO; default: this Monday)")
        command.add_argument("--to", dest="end", help="to this time (ISO; default: a week after --from)")
        command.add_argument("-q", "--query", help="only the entries whose title or note holds this text (default "
                                                   "stretch: a year back to a year ahead)")
    add = commands.add_parser("add", parents=[common], help="put an entry on it")
    add.add_argument("title")
    add.add_argument("--at", required=True, help="when: ISO time, or HH:MM (the next one)")
    add.add_argument("--until", help="until when")
    add.add_argument("--kind", default="task", choices=["goal", "task", "reminder", "plan"])
    add.add_argument("--repeat", choices=["daily", "weekly"])
    add.add_argument("--note", default="")
    move = commands.add_parser("move", parents=[common], help="move an entry (its id: harness calendar list)")
    move.add_argument("id")
    move.add_argument("--at", required=True)
    move.add_argument("--until")
    update = commands.add_parser("update", parents=[common], help="change an entry: its title, times, kind, note")
    update.add_argument("id")
    update.add_argument("--title")
    update.add_argument("--at", help="when it starts")
    update.add_argument("--until", help="when it ends")
    update.add_argument("--no-until", action="store_true", help="it has no end")
    update.add_argument("--kind", choices=["goal", "task", "reminder", "plan"])
    update.add_argument("--repeat", choices=["daily", "weekly", "none"])
    update.add_argument("--note")
    remove = commands.add_parser("remove", parents=[common], help="remove an entry")
    remove.add_argument("id")
    restore = commands.add_parser("restore", parents=[common], help="put back an entry that was removed")
    restore.add_argument("id", nargs="?", help="its id (default: the one removed last)")
    pause = commands.add_parser("pause", parents=[common], help="pause what it does on its own (it still answers "
                                                                "you and mentions)")
    pause.add_argument("--off", action="store_true", help="resume what it does on its own")
    args = parser.parse_args(arguments)

    def run():
        client = _client(args)
        if args.command == "add":
            week = client.calendar_change("add", title=args.title, at=args.at, until=args.until, kind=args.kind,
                                          repeat=args.repeat, note=args.note)
            _print(args, week, [f"✓ on the calendar: {args.title} · {args.at} ({client.identity})"])
            return 0
        if args.command == "move":
            week = client.calendar_change("move", id=args.id, at=args.at, until=args.until)
            _print(args, week, [f"✓ moved {args.id} to {args.at}"])
            return 0
        if args.command == "update":
            changes = {key: value for key, value in (("title", args.title), ("at", args.at), ("until", args.until),
                                                     ("kind", args.kind), ("note", args.note)) if value is not None}
            if args.no_until:
                changes["until"] = None
            if args.repeat:
                changes["repeat"] = None if args.repeat == "none" else args.repeat
            if not changes:
                raise ValueError("harness calendar update ID with what changes: --title, --at, --until, --kind, --note")
            week = client.post("calendar", {"action": "update", "id": args.id, **changes})
            entry = week.get("result") or {}
            _print(args, week, [f"✓ {args.id} · {entry.get('title')} · {day_name(entry['at'])} {clock(entry['at'])}"
                                + (f"–{clock(entry['until'])}" if entry.get("until") else "")])
            return 0
        if args.command == "remove":
            week = client.calendar_change("remove", id=args.id)
            _print(args, week, [f"✓ removed {args.id} (harness calendar restore puts it back)"])
            return 0
        if args.command == "restore":
            week = client.calendar_change("restore", id=args.id)
            entry = week.get("result") or {}
            _print(args, week, [f"✓ back on the calendar: {entry.get('title')} [{entry.get('id')}]"])
            return 0
        if args.command == "pause":
            week = client.calendar_change("resume_own" if args.off else "pause_own")
            _print(args, week, ["✓ " + ("it does things on its own again" if args.off else
                                        "paused on its own: it still answers you and mentions") +
                                f" ({client.identity})"])
            return 0
        week = client.calendar(args.start, args.end, args.query)
        usage = client.usage()
        _print(args, week, calendar_lines(week, usage, client.identity))
        return 0

    return _guard("calendar", run)


def said(text, language="en") -> str:
    """A declared text ({en, zh}) in the terminal's language (English: the terminal's fixed words are)."""
    return str((text or {}).get(language) or "") if isinstance(text, dict) else str(text or "")


def channel_lines(rows, kinds=None) -> list:
    """The accounts as the terminal lists them. `kinds`: what harness channels kinds gives
    ({kinds, from}), to say where channels come from when there is nothing to list."""
    if not rows:
        found = (kinds or {}).get("kinds") or []
        if found:
            return ["no channel accounts yet: harness channels add KIND (" + ", ".join(k["kind"] for k in found) + ")"]
        return ["no channel accounts, and no channel is installed.", said((kinds or {}).get("from"))
                or "Channels come from packages: harness install NAME."]
    lines = [f"  {'account':<12} {'kind':<10} {'state':<14} {'groups':<12} owner"]
    for row in rows:
        entered = row.get("entered") or {}
        state = {"logged_in": "online", "waiting_login": "waiting login", "starting": "starting",
                 "unavailable": "unavailable"}.get(row.get("state"), str(row.get("state")))
        lines.append(f"  {row['account']:<12} {str(row.get('kind')):<10} {state:<14} {str(len(entered)) + ' entered':<12} "
                     + (f"bound {row['owner']}" if row.get("owner") else "not bound"))
        if row.get("values"):
            lines.append("  " + " " * 12 + " " + " · ".join(f"{key} {value}" for key, value in row["values"].items()))
        if row.get("problem"):
            lines.append(f"  {'':<12} {row['problem']}")
    for row in rows:
        for request in row.get("pending") or ():
            lines.append(f"  pairing request {request['code']} · {row['account']} · {request.get('user')}"
                         + (f" ({request['name']})" if request.get("name") else "")
                         + f" · until {clock(float(request.get('expires') or 0))}"
                         + f"  (harness channels pair approve {row['account']} {request['code']})")
        if row.get("paired"):
            lines.append(f"  paired on {row['account']}: " + ", ".join(row["paired"]))
    return lines


def kind_lines(found) -> list:
    """The kinds of channel and what each asks for (harness channels kinds)."""
    kinds = found.get("kinds") or []
    if not kinds:
        return ["no channel is installed.", said(found.get("from"))]
    lines = []
    for kind in kinds:
        lines.append(f"{kind['kind']}  {said(kind['name'])} · package {kind['package']}")
        if said(kind.get("about")):
            lines.append(f"  {said(kind['about'])}")
        for field in kind["fields"]:
            choices = " | ".join(str(choice["value"]) for choice in field.get("choices") or ())
            default = "" if field.get("default") in (None, "") else f" (default {field['default']})"
            lines.append(f"  --{field['id'].replace('_', '-'):<14} {said(field['label'])}"
                         + (f": {choices}" if choices else "") + default)
        lines.append("  steps: " + " → ".join(kind["steps"]))
    for kind, problem in (found.get("problems") or {}).items():
        lines.append(f"{kind}  {problem}")
    return lines


def _ask(question, default="", secret=False):
    """A line typed in answer (a secret is not shown while it is typed)."""
    try:
        if secret:
            import getpass

            answer = getpass.getpass(question + " ").strip()
        else:
            print(question, end=" ", file=sys.stderr, flush=True)
            answer = input().strip()
    except EOFError:
        return default
    return answer or default


def _wait(check, seconds, label):
    print(f"  {label} …", file=sys.stderr, flush=True)
    end = time.time() + seconds
    while time.time() < end:
        found = check()
        if found:
            return found
        time.sleep(1.0)
    return None


def _field_values(words) -> dict:
    """{field: value} from --field value and --field=value words (what follows a command
    whose flags are the fields a channel declares)."""
    values, index = {}, 0
    while index < len(words):
        word = words[index]
        if not word.startswith("--") or len(word) < 3:
            raise ValueError(f"{word!r} is not understood here: a field is given as --FIELD VALUE")
        name, sep, value = word[2:].partition("=")
        if not sep:
            if index + 1 >= len(words):
                raise ValueError(f"--{name} needs a value")
            index += 1
            value = words[index]
        values[name.replace("-", "_")] = value
        index += 1
    return values


def channels_main(arguments=None):
    """harness channels: the identity's chat channels (as /channels and Settings › Connectors)."""
    common = _common()
    parser = argparse.ArgumentParser(prog="the-harness channels", parents=[common],
                                     description="Chat channels: each account belongs to one identity, chosen "
                                                 "first. The kinds come from the installed packages (harness "
                                                 "channels kinds), with the fields each asks for")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("list", parents=[common], help="the channel accounts and pairing requests")
    commands.add_parser("kinds", parents=[common], help="the kinds of channel the installed packages provide and "
                                                        "what each asks for")
    add = commands.add_parser("add", parents=[common], help="connect an account: identity and policies first, then "
                                                            "the login, the groups and the owner",
                              epilog="The kind's own fields are given as --FIELD VALUE (harness channels kinds "
                                     "lists them); a terminal is asked for the ones left out.")
    add.add_argument("kind", help="the kind of channel (harness channels kinds)")
    add.add_argument("--group", action="append", default=[], help="let it into this group (repeat; default: none)")
    add.add_argument("--mode", help="how it is woken in those groups (default: the kind's first mode)")
    add.add_argument("--title", help="what the account is called in the list")
    add.add_argument("--address", help=argparse.SUPPRESS)
    add.add_argument("--no-wait", action="store_true", help="do not wait for the login and the owner")
    change = commands.add_parser("set", parents=[common], help="change an account's settings: --FIELD VALUE ...")
    change.add_argument("account")
    groups = commands.add_parser("groups", parents=[common], help="the groups an account is in; let it into some")
    groups.add_argument("account")
    groups.add_argument("--enter", action="append", default=[], metavar="ID", help="let it into this group (repeat)")
    groups.add_argument("--leave", metavar="ID", help="take it out of this group")
    groups.add_argument("--mode", help="how it is woken in the groups it enters")
    code = commands.add_parser("owner-code", parents=[common], help="a new one-time code that binds the owner")
    code.add_argument("account")
    remove = commands.add_parser("remove", parents=[common], help="disconnect a channel account")
    remove.add_argument("account")
    tested = commands.add_parser("test", parents=[common], help="whether an account works now")
    tested.add_argument("account")
    pair = commands.add_parser("pair", parents=[common], help="pairing requests; approve or revoke one")
    pair.add_argument("what", nargs="?", choices=["list", "approve", "revoke"], default="list")
    pair.add_argument("account", nargs="?")
    pair.add_argument("code", nargs="?", help="approve: the request's code; revoke: the person's account")
    # The fields of a kind are flags of add and set: what the parser does not know is theirs.
    args, rest = parser.parse_known_args(arguments)
    if rest and args.command not in ("add", "set"):
        parser.error(f"unrecognized arguments: {' '.join(rest)}")

    def run():
        values = _field_values(rest)
        client = _client(args)
        if args.command == "kinds":
            found = client.channel_kinds()
            _print(args, found, kind_lines(found))
            return 0
        if args.command == "add":
            return _channel_add(args, client, values)
        if args.command == "set":
            if not values:
                raise ValueError("harness channels set ACCOUNT --FIELD VALUE ...")
            answer = client.channel("set", account=args.account, values=values)
            _print(args, answer, [f"✓ {args.account}: " + " · ".join(f"{k} {v}" for k, v in
                                                                     (answer.get("result") or {}).get("values", {}).items())])
            return 0
        if args.command == "groups":
            answer = None
            if args.leave:
                answer = client.channel("leave_group", account=args.account, group=args.leave)
            if args.enter:
                answer = client.channel("groups", account=args.account, groups=args.enter, mode=args.mode)
            row = (client.channels(args.account) or [{}])[0]
            listed = row.get("groups")
            lines = [f"groups of {args.account}"]
            if listed is None:
                lines.append("  not logged in yet (or this channel has no groups)")
            for group in listed or ():
                lines.append(f"  {group['id']:<16} {str(group.get('name') or ''):<30} "
                             + (f"entered · {group['entered']}" if group.get("entered") else "not entered"))
            _print(args, answer or row, lines)
            return 0
        if args.command == "owner-code":
            answer = client.channel("owner_code", account=args.account)
            result = answer.get("result") or {}
            _print(args, answer, [f"{result.get('code')}  {said(result.get('text'))}"])
            return 0
        if args.command == "remove":
            answer = client.channel("remove", account=args.account)
            _print(args, answer, [f"✓ removed {args.account} ({client.identity})"])
            return 0
        if args.command == "test":
            result = client.channel("test", account=args.account).get("result") or {}
            _print(args, result, [f"✓ {args.account} is logged in · {result.get('groups', 0)} group(s) entered · "
                                  + (f"owner {result['owner']}" if result.get("owner") else "no owner bound")])
            return 0
        if args.command == "pair" and args.what != "list":
            if not args.account or not args.code:
                raise ValueError(f"harness channels pair {args.what} ACCOUNT " + ("CODE" if args.what == "approve" else "USER"))
            if args.what == "approve":
                answer = client.channel("pair", account=args.account, code=args.code)
                user = (answer.get("result") or {}).get("user") or ""
                _print(args, answer, [f"✓ paired {args.account} {user} · may ask it for things in that private "
                                      "chat only"])
            else:
                answer = client.channel("unpair", account=args.account, user=args.code)
                _print(args, answer, [f"✓ no longer paired: {args.code}"])
            return 0
        rows = client.channels()
        if args.command == "pair":
            requests = [{**request, "account": row["account"]} for row in rows for request in row.get("pending") or ()]
            _print(args, requests, [f"  {r['code']} · {r['account']} · {r.get('user')}"
                                    + (f" ({r['name']})" if r.get("name") else "")
                                    + f" · until {clock(float(r.get('expires') or 0))}" for r in requests]
                   or ["no pairing requests"])
            return 0
        _print(args, rows, [f"channels of {client.identity}"] + channel_lines(rows, None if rows else client.channel_kinds()))
        return 0

    return _guard("channels", run)


def _channel_add(args, client, values):
    """The four steps in the order the channel's package declares them: the identity (asked
    first, _client) and the values of the kind's fields, the login, the groups, then the
    owner bound with a one-time code. Every question and line comes from the declaration."""
    talk = _interactive() and not args.json
    found = client.channel_kinds()
    kind = next((row for row in found["kinds"] if row["kind"] == args.kind), None)
    if kind is None and not args.address:
        # A package that provides this kind is installed first, as the settings allow.
        from harness.packages import ensure

        try:
            ensure("spaces", args.kind, log=lambda message: print(message, file=sys.stderr))
        except (ValueError, OSError, RuntimeError):
            pass  # nothing provides it, or nothing may be installed: said below, with where channels come from
        found = client.channel_kinds()
        kind = next((row for row in found["kinds"] if row["kind"] == args.kind), None)
    if kind is None:
        raise ValueError(f"no installed package provides a channel called {args.kind!r}. " + said(found.get("from")))
    if talk:
        print(f"{said(kind['name'])}: which identity answers on this account? ✓ {client.identity}", file=sys.stderr)
        for field in kind["fields"]:
            if field["id"] in values:
                continue
            choices = " / ".join(f"[{c['value']}]" if c["value"] == field.get("default") else str(c["value"])
                                 for c in field.get("choices") or ())
            default = "" if field.get("default") in (None, "") or choices else f" [{field['default']}]"
            answer = _ask(f"{said(field['label'])}?{' ' + choices if choices else default}", "",
                          secret=field["kind"] == "secret")
            if answer:
                values[field["id"]] = answer
    answer = client.channel("add", kind=args.kind, values=values, title=args.title, address=args.address)
    account = answer["account"]
    row = (answer.get("channels") or [{}])[0]
    login = said((row.get("login") or {}).get("text"))
    if talk:
        print(f"✓ {account}" + (f" · {login}" if login else ""), file=sys.stderr)
        # What the channel shows for this login now (a link to open, a line), once its space is there.
        shown = _wait(lambda: next(((r.get("login") or {}) for r in client.channels(account)
                                    if r.get("state") != "starting"), None), 30, "starting it") or {}
        for line in (shown.get("url"), shown.get("now")):
            if line:
                print(f"  {line}", file=sys.stderr)
    if args.no_wait:
        _print(args, answer, [f"✓ {account} added to {client.identity}" + (f" · {login}" if login else ""),
                              "  harness channels shows when it is logged in"])
        return 0
    row = _wait(lambda: next((r for r in client.channels(account) if r.get("state") == "logged_in"), None), 600,
                "waiting for the account to log in")
    if row is None:
        _print(args, answer, [f"{account} is added; it has not logged in yet. harness channels shows when it has"])
        return 1
    lines = [f"✓ {account} · logged in"]
    groups = list(args.group)
    if "groups" in kind["steps"]:
        if not groups and talk and row.get("groups"):
            print("Which groups? none by default; numbers separated by spaces:", file=sys.stderr)
            for index, group in enumerate(row["groups"], 1):
                print(f"  {index}. {group.get('name') or group['id']} ({group['id']})", file=sys.stderr)
            picked = _ask(">", "")
            groups = [row["groups"][int(word) - 1]["id"] for word in picked.replace(",", " ").split()
                      if word.isdigit() and 1 <= int(word) <= len(row["groups"])]
        if groups:
            entered = client.channel("groups", account=account, groups=groups, mode=args.mode).get("result") or {}
            lines.append(f"✓ entered {len(groups)} group(s) · {entered.get('mode')}")
        else:
            lines.append("  no groups (harness channels groups " + account + " --enter ID)")
    code = None
    if "owner" in kind["steps"]:
        result = client.channel("owner_code", account=account).get("result") or {}
        code = result.get("code")
        lines.append(f"Bind the owner: {said(result.get('text'))}  {code}")
    if talk:
        print("\n".join(lines), file=sys.stderr)
        lines = []
        if code:
            bound = _wait(lambda: next((r.get("owner") for r in client.channels(account) if r.get("owner")), None), 600,
                          "waiting for your message")
            lines = [f"✓ bound {bound}" if bound else f"not bound yet: harness channels owner-code {account} gives a new code"]
    _print(args, {**answer, "groups": groups, "owner_code": code}, lines)
    return 0


def source_lines(found) -> list:
    """The skill sources as the terminal lists them (harness skills sources)."""
    lines = []
    for row in found.get("sources") or ():
        there = [skill for skill in row["skills"] if skill.get("there")]
        lines.append(f"  {row['id']:<24} {str(row.get('kind') or ''):<5} {len(there)} skill{'' if len(there) == 1 else 's'}"
                     f"  {row['from']}")
        for skill in there:
            lines.append(f"  {'':<24}   {skill['name']} · {EVIDENCE.get(skill.get('evidence'), skill.get('evidence') or '')}")
    if not lines:
        lines.append("no skill sources yet: harness skills add SOURCE (a folder or a SKILL.md here, "
                     "github:OWNER/REPO[#FOLDER], or the address of an archive or of a SKILL.md)")
    for row in found.get("shared") or ():
        lines.append(f"  shared library {row['name']} · {row.get('entries')} entries · read only"
                     + (f" · package {row['package']}" if row.get("package") else ""))
    return lines


def skills_main(arguments=None):
    """harness skills: the identity's skills and where they are taken from (as Settings ›
    Connectors' skill sources and /skills)."""
    common = _common()
    parser = argparse.ArgumentParser(prog="the-harness skills", parents=[common],
                                     description="The identity's skills, and the sources they are taken from: a "
                                                 "folder or a SKILL.md on this computer, a repository, an archive")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("list", parents=[common], help="its skills: evidence, uses, where each came from")
    commands.add_parser("sources", parents=[common], help="the sources its skills are taken from")
    for name in ("add", "install"):
        add = commands.add_parser(name, parents=[common], help="add a source and take its skills in (each as proposed)")
        add.add_argument("source", help="a folder or SKILL.md here, github:OWNER/REPO[#FOLDER], git:URL[#FOLDER], or "
                                        "the address of an archive or of a SKILL.md")
    for name in ("test", "inspect"):
        test = commands.add_parser(name, parents=[common], help="read a source without taking anything: the skills it holds")
        test.add_argument("source", help="where it is, or the id of a source that was added")
    update = commands.add_parser("update", parents=[common], help="read the sources again and take in the new skills")
    update.add_argument("id", nargs="?", help="one source (default: all)")
    for name in ("remove", "uninstall"):
        remove = commands.add_parser(name, parents=[common], help="forget a source, and the skills it brought")
        remove.add_argument("id")
        remove.add_argument("--keep", action="store_true", help="keep the skills it brought")
    args = parser.parse_args(arguments)

    def run():
        client = _client(args)
        command = {"install": "add", "inspect": "test", "uninstall": "remove"}.get(args.command, args.command) or "list"
        if command == "list":
            found = client.learned()
            _print(args, found["skills"], [f"skills of {client.identity}"] + skill_lines(found["skills"]))
        elif command == "sources":
            found = client.skill_sources()
            _print(args, found, [f"skill sources of {client.identity}"] + source_lines(found))
        elif command == "add":
            result = client.skill_source("add", **{"from": args.source})["result"]
            _print(args, result, [f"✓ {result['id']} · {len(result['added'])} skill(s) taken in as proposed: "
                                  + (", ".join(result["added"]) or "none")]
                   + ([f"  left as they are (already there): {', '.join(result['skipped'])}"] if result["skipped"] else []))
        elif command == "test":
            result = client.skill_source("test", **{"from": args.source})["result"]
            _print(args, result, [f"✓ {result['from']} ({result['kind']}) holds {len(result['skills'])} skill(s), "
                                  f"read in {result['seconds']} s"]
                   + [f"  {skill['name']:<28} {str(skill.get('description') or '')[:80]}"
                      + ("  (with a program)" if skill.get("program") else "") for skill in result["skills"]])
        elif command == "update":
            result = client.skill_source("update", id=args.id)["result"]
            _print(args, result, [f"  {name}: " + (", ".join(new) + " taken in" if new else "nothing new")
                                  for name, new in result["updated"].items()] or ["no skill sources"])
        else:
            result = client.skill_source("remove", id=args.id, keep=args.keep)["result"]
            _print(args, result, [f"✓ removed {result['removed']}"
                                  + (f" and its skills: {', '.join(result['skills_removed'])}" if result["skills_removed"]
                                     else "")])
        return 0

    return _guard("skills", run)


def tree_lines(level, labels=None, lit_mark="•") -> list:
    """One level of the tree: the path on top (`labels`: what each node on it is about), the
    nodes in order; one with nodes under it is shown like a folder, with how many it holds."""
    path = labels or level.get("path") or []
    lines = ["tree › " + " › ".join(["root", *path]), "─" * 76]
    for number, node in enumerate(level.get("nodes") or (), 1):
        text = node.get("about") or node["name"]
        if node.get("children"):
            right = f"{node['children']} nodes"
            text = "▸ " + text
        else:
            right = EVIDENCE.get(node.get("evidence") or node.get("source"), node.get("evidence") or node.get("source") or "")
            right += f" · {node.get('uses') or 0} uses"
            text = "  " + text
        mark = lit_mark if node.get("lit") else " "
        off = "" if node.get("enabled", True) else " (disabled)"
        lines.append(f"{mark} {number:>2}. {text[:58]:<60} {right}{off}  [{node['name']}]")
    if not level.get("nodes"):
        lines.append("  (no nodes here)")
    return lines


def skill_lines(skills) -> list:
    lines = [f"  {'skill':<40} {'evidence':<16} {'uses':<6} source"]
    for row in skills:
        source = row.get("source") or {}
        where = " · ".join(str(part) for part in (source.get("chat"), _when(source.get("time"))) if part) \
            or str(source.get("source") or "")
        lines.append(f"  {row['name'][:40]:<40} {EVIDENCE.get(row.get('evidence'), row.get('evidence') or ''):<16} "
                     f"{str(row.get('uses') or 0):<6} {where}")
    return lines if skills else ["  no skills yet"]


def _when(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(value)))
    except (TypeError, ValueError):
        return str(value)[:16]


def memory_lines(entries: dict) -> list:
    lines = [f"  {'memory':<44} {'scope':<10} source"]
    for key, entry in sorted(entries.items(), key=lambda item: str(item[1].get("updated") or "")):
        text = (entry.get("text") or "").strip().splitlines()
        scope = "this chat" if entry.get("scope") == "chat" else "private"
        where = " · ".join(part for part in (str(entry.get("chat") or entry.get("source") or ""),
                                             _when(entry.get("updated"))) if part)
        lines.append(f"  {(text[0] if text else key)[:44]:<44} {scope:<10} {where}")
    return lines if entries else ["  nothing remembered yet"]


def library_main(words) -> int:
    """harness library skills | tree [PATH] | memory | undo NAME: the identity's skills, its
    tree of reactions one level at a time, and its memory (the core's harness library calls this)."""
    common = _common()
    parser = argparse.ArgumentParser(prog="the-harness library", parents=[common],
                                     description="What the identity learned: skills, the tree of reactions, memory")
    commands = parser.add_subparsers(dest="what", required=True)
    commands.add_parser("skills", parents=[common], help="its skills: evidence, uses, where each came from")
    tree = commands.add_parser("tree", parents=[common], help="the tree of reactions, one level like a folder")
    tree.add_argument("path", nargs="?", default="", help="node names from the root, joined by / (default: the root)")
    commands.add_parser("memory", parents=[common], help="its memory: scope and source of each entry")
    undo = commands.add_parser("undo", parents=[common], help="undo a skill it learned (it is no longer loaded)")
    undo.add_argument("name")
    args = parser.parse_args(words)

    def run():
        client = _client(args)
        if args.what == "tree":
            level = client.reactions(args.path)
            names, labels = level.get("path") or [], []
            for index, name in enumerate(names):  # the path in the words of its nodes
                above = client.reactions("/".join(names[:index]))["nodes"]
                labels.append(next((n.get("about") or name for n in above if n["name"] == name), name))
            _print(args, level, tree_lines(level, labels))
        elif args.what == "skills":
            found = client.learned()
            lines = skill_lines(found["skills"])
            shared = found.get("shared_libraries") or []
            if shared:
                lines += ["", "shared libraries (read only): " + ", ".join(str(row.get("name")) for row in shared)]
            _print(args, found["skills"], [f"skills of {client.identity}"] + lines)
        elif args.what == "memory":
            found = client.memory()
            _print(args, found, [f"memory of {client.identity}"] + memory_lines(found.get("entries") or {})
                   + ["  private: your own places only · this chat: where it was written"])
        else:
            answer = client.undo(args.name)
            _print(args, answer, [f"undone {args.name}: no longer loaded; the revision stays in history"])
        return 0

    return _guard("library", run)
