"""The agent's entries in the command line and in Python, over the session host: what the app,
the terminal chat (/calendar, /channels, /library, /usage) and these show is one life, read
and changed through the host's /api/agent routes, never through the files the life owns.

    harness calendar [list] [--from ISO] [--to ISO]     a week: what it did, who, the outcome
    harness calendar add TITLE --at TIME [--until TIME] [--kind KIND] [--repeat daily|weekly]
    harness calendar move ID --at TIME [--until TIME]
    harness calendar remove ID
    harness calendar pause [--off]                      pause (or resume) what it does on its own
    harness channels [list]                             the channel accounts and pairing requests
    harness channels add qq [--dm POLICY] [--groups mention|all] [--onebot URL] [--group ID ...]
    harness channels remove ACCOUNT
    harness channels pair [approve ACCOUNT CODE | revoke ACCOUNT USER]
    harness library skills | tree [PATH] | memory | undo NAME   (the core's harness library)

Each acts on --identity, else the current identity, else the only one; a terminal is asked
when several are left, a script fails. The same calls are harness.sdk.Agent's methods
(sdk.py), and the host route /api/agent/channels is here (channels())."""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from . import state
from .state import IdentityError, read, save

# What an evidence level is called wherever it is shown.
EVIDENCE = {"builtin": "built in", "owner": "added by owner", "proposed": "proposed", "own_test": "own test",
            "replayed": "replayed", "effective": "effective", "archived": "archived", "undone": "undone",
            "failed own test": "failed own test"}
# The mark of an outcome, as the terminal chat draws it.
MARKS = {"done": "✓", "refused": "⊘", "failed": "✗", "unknown": "?", "cancelled": "–", "waiting": "●"}
GROUP_MODES = ("mention", "all")
DM_POLICIES = ("pairing", "allowlist", "open", "off")
CHANNEL_KINDS = ("qq",)
ONEBOT = "ws://127.0.0.1:3001"


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

    def post(self, name, body=None) -> dict:
        return self.host.post(f"/api/agent/{name}", {"identity": self.identity, **(body or {})})

    # One to one with the commands (and harness.sdk.Agent).

    def chats(self) -> list:
        return self.get("chats")["chats"]

    def memory(self) -> dict:
        return self.get("memory")

    def reactions(self, path="") -> dict:
        return self.get("tree", path="/".join(path) if isinstance(path, (list, tuple)) else path)

    def learned(self) -> dict:
        return self.get("learned")

    def undo(self, name) -> dict:
        return self.post("learned", {"action": "undo", "name": name})

    def usage(self, week=False) -> dict:
        return self.get("usage", week=1 if week else None)

    def calendar(self, start=None, end=None) -> dict:
        return self.get("calendar", **{"from": _iso(start), "to": _iso(end)})

    def calendar_change(self, action, **fields) -> dict:
        return self.post("calendar", {"action": action, **{k: v for k, v in fields.items() if v is not None}})

    def life(self) -> dict:
        return self.get("life")

    def settings(self) -> dict:
        return self.get("settings")

    def channels(self, account=None) -> list:
        return self.get("channels", account=account)["channels"]

    def channel(self, action, **fields) -> dict:
        return self.post("channels", {"action": action, **{k: v for k, v in fields.items() if v is not None}})


def _iso(value):
    """A time for the host: ISO as given, seconds or a datetime turned into ISO."""
    from datetime import datetime

    if value is None or isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return datetime.fromtimestamp(float(value)).isoformat()


# -- the host route: /api/agent/channels -----------------------------------------------------

def channels(server, body):
    """GET {account}: the identity's channel accounts (with the account's groups once it is
    logged in) and the pairing requests; POST {action: add | groups | owner_code | pair |
    unpair | remove, ...}. A channel always belongs to one identity, chosen before login."""
    from .host import _life, _one

    life = _life(server, body)
    action = _one(body.get("action"))
    account = _one(body.get("account"))
    result = None
    if action == "add":
        result = _add(life, body)
        account = result["account"]
    elif action == "groups":
        result = _groups(life, account, body.get("groups") or [], body.get("mode") or "mention")
    elif action == "owner_code":
        result = _owner_act(life, account, "qq.owner_code", {})
        life.chats.record("main", "channel", account=account, owner_code=(result or {}).get("code"),
                          expires=(result or {}).get("expires"))
    elif action == "pair":
        result = _owner_act(life, account, "qq.pair", {"code": str(body.get("code") or "").upper()})
    elif action == "unpair":
        result = _owner_act(life, account, "qq.unpair", {"user": str(body.get("user") or "")})
    elif action == "remove":
        row = _row(life, account)
        life.disconnect(account)
        if row.get("config"):
            (life.identity.directory / row["config"]).unlink(missing_ok=True)
        result = {"removed": account}
    elif action:
        raise ValueError("action is add, groups, owner_code, pair, unpair or remove")
    rows = _rows(life, account)
    return {"identity": life.identity.id, "channels": rows, **({"result": result} if result is not None else {}),
            **({"account": account, "state": rows[0]["state"], "onebot": rows[0].get("onebot"), "qr": None}
               if action == "add" and rows else {})}


def _channel_rows(life) -> list:
    from . import places as places_module

    return [row for row in places_module.load(life.identity) if row.get("channel")]


def _row(life, account) -> dict:
    row = next((row for row in _channel_rows(life) if row["id"] == account), None)
    if row is None:
        raise ValueError(f"no channel {account!r} on identity {life.identity.id}")
    return row


def _add(life, body) -> dict:
    kind = body.get("kind") or "qq"
    if kind not in CHANNEL_KINDS:
        raise ValueError(f"a channel is one of {', '.join(CHANNEL_KINDS)}")
    dm = body.get("dm") or "pairing"
    if dm not in DM_POLICIES:
        raise ValueError(f"the private-chat policy is one of {', '.join(DM_POLICIES)}")
    mode = body.get("groups") if isinstance(body.get("groups"), str) else "mention"
    if mode not in GROUP_MODES:
        raise ValueError("groups wake it on mention or on every message (all)")
    from . import places as places_module

    taken = {row["id"] for row in places_module.load(life.identity)}
    account = kind if kind not in taken else next(f"{kind}-{n}" for n in range(2, 100) if f"{kind}-{n}" not in taken)
    config = f"channels/{account}.json"
    path = life.identity.directory / config
    save(path, {"identity": life.identity.id, "dm": dm, "groups": {}, "group_mode": mode, "owner": None,
                "paired": [], "pending": {}, "owner_codes": {}})
    onebot = body.get("onebot") or ONEBOT
    fields = {"id": account, "title": body.get("title") or kind.upper(), "channel": kind, "config": config,
              "onebot": onebot, "dm": dm, "group_mode": mode}
    if body.get("address"):
        fields["address"] = body["address"]  # a space that runs already
    else:
        owner = _key(life)
        fields["serve"] = [kind, "--onebot", onebot, "--config", config,
                           *(["--owner", owner.identity] if owner is not None else [])]
    row = life.connect("space", **fields)
    return {"account": row["id"], "config": config, "onebot": onebot}


def _key(life):
    try:
        import base64
        from agent_space.identity import KeyPair

        stored = read(life.identity.root / ".keys" / f"{life.identity.id}.json", None)
        return KeyPair(base64.b64decode(stored["seed"])) if stored else None
    except Exception:
        return None


def _owner_act(life, account, verb, args):
    """What only the owner may do in a channel (its groups, binding, pairing): done through
    the host as the account's owner, the identity's own key."""
    _row(life, account)
    place = life.places.get(account)
    environment = getattr(place, "environment", None)
    if environment is None or not getattr(place, "online", False):
        raise ValueError(f"channel {account} is not connected yet")
    from harness.space.environment import SpaceEnvironment

    owner = SpaceEnvironment.connect(environment.address, key=_key(life), role="owner", timeout=30)
    try:
        outcome = owner.participant.act(verb, None, args, id=owner.next_id(), timeout=30)
    finally:
        owner.close()
    end = getattr(outcome.end, "value", outcome.end)
    if end != "done":
        reason = outcome.reason
        raise ValueError(f"{verb} ended {end}: {getattr(reason, 'text', None) or getattr(reason, 'code', None) or reason}")
    return outcome.result


def _groups(life, account, groups, mode) -> dict:
    if mode not in GROUP_MODES:
        raise ValueError("groups wake it on mention or on every message (all)")
    groups = [str(group) for group in (groups if isinstance(groups, list) else [groups])]
    entered = []
    for group in groups:
        _owner_act(life, account, "qq.enter_group", {"group": group, "mode": mode})
        entered.append(group)
    return {"entered": entered, "mode": mode}


def _rows(life, account=None) -> list:
    rows = []
    for row in _channel_rows(life):
        if account and row["id"] != account:
            continue
        place = life.places.get(row["id"])
        config = read(life.identity.directory / row["config"], {}) if row.get("config") else {}
        online = bool(getattr(place, "online", False))
        now = time.time()
        found = {"account": row["id"], "kind": row.get("channel"), "title": row.get("title"),
                 "identity": life.identity.id, "online": online, "state": "logged_in" if online else "waiting_login",
                 "onebot": row.get("onebot"), "dm": config.get("dm", row.get("dm")),
                 "group_mode": config.get("group_mode", row.get("group_mode")),
                 "entered": config.get("groups") or {}, "owner": config.get("owner") or row.get("owner"),
                 "paired": config.get("paired") or [],
                 "pending": [{"code": code, **request} for code, request in (config.get("pending") or {}).items()
                             if float(request.get("expires") or 0) > now]}
        if account and online:
            try:
                listed = (_owner_act(life, row["id"], "qq.groups", {}) or {}).get("groups") or []
                found["groups"] = [{"id": g["group"], "name": g.get("name"), "entered": g.get("entered")} for g in listed]
            except (ValueError, OSError, RuntimeError):
                found["groups"] = None
        rows.append(found)
    return rows


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
    try:
        return run()
    except IdentityError as error:
        print(f"harness {command}: {error}", file=sys.stderr)
        return 2
    except (UsageError, ValueError, KeyError) as error:
        print(f"harness {command}: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # the host's answer (RemoteError) or the connection
        print(f"harness {command}: {error}", file=sys.stderr)
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
        lines.append(f"on its own ${float(today.get('own_usd') or 0):.2f} / "
                     f"${float(today.get('daily_budget') or 0) - float(today.get('reserve') or 0):.2f} · "
                     f"${float(today.get('reserve') or 0):.2f} kept for you")
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
    parser = argparse.ArgumentParser(prog="harness calendar", parents=[common],
                                     description="The identity's calendar: what it did and when (the tree's "
                                                 "reactions, what it did on its own, what you asked, refusals, "
                                                 "outcomes, when it was asleep) and what is planned")
    commands = parser.add_subparsers(dest="command")
    listed = commands.add_parser("list", parents=[common], help="a week (default: this one)")
    for command in (parser, listed):
        command.add_argument("--from", dest="start", help="from this time (ISO; default: this Monday)")
        command.add_argument("--to", dest="end", help="to this time (ISO; default: a week after --from)")
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
    remove = commands.add_parser("remove", parents=[common], help="remove an entry")
    remove.add_argument("id")
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
        if args.command == "remove":
            week = client.calendar_change("remove", id=args.id)
            _print(args, week, [f"✓ removed {args.id}"])
            return 0
        if args.command == "pause":
            week = client.calendar_change("resume_own" if args.off else "pause_own")
            _print(args, week, ["✓ " + ("it does things on its own again" if args.off else
                                        "paused on its own: it still answers you and mentions") +
                                f" ({client.identity})"])
            return 0
        week = client.calendar(args.start, args.end)
        usage = client.usage()
        _print(args, week, calendar_lines(week, usage, client.identity))
        return 0

    return _guard("calendar", run)


def channel_lines(rows) -> list:
    if not rows:
        return ["no channels: harness channels add qq"]
    lines = [f"  {'account':<10} {'state':<10} {'dm':<10} {'groups':<20} owner"]
    for row in rows:
        entered = row.get("entered") or {}
        lines.append(f"  {row['account']:<10} {('online' if row['online'] else 'offline'):<10} {str(row.get('dm')):<10} "
                     f"{(str(len(entered)) + ' entered, ' + str(row.get('group_mode') or 'mention')):<20} "
                     + (f"bound {row['kind'].upper()} {row['owner']}" if row.get("owner") else "not bound"))
    for row in rows:
        for request in row.get("pending") or ():
            lines.append(f"  pairing request {request['code']} · {row['account']} · {request.get('user')}"
                         + (f" ({request['name']})" if request.get("name") else "")
                         + f" · until {clock(float(request.get('expires') or 0))}"
                         + f"  (harness channels pair approve {row['account']} {request['code']})")
        if row.get("paired"):
            lines.append(f"  paired on {row['account']}: " + ", ".join(row["paired"]))
    return lines


def _ask(question, default=""):
    print(question, end=" ", file=sys.stderr, flush=True)
    try:
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


def channels_main(arguments=None):
    """harness channels: the identity's chat channels (as /channels and Settings › Connectors)."""
    common = _common()
    parser = argparse.ArgumentParser(prog="harness channels", parents=[common],
                                     description="Chat channels: each account belongs to one identity, chosen "
                                                 "first, with its private-chat and group policies")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("list", parents=[common], help="the channel accounts and pairing requests")
    add = commands.add_parser("add", parents=[common], help="connect a channel account: identity and policies "
                                                            "first, then the login, the groups and the owner")
    add.add_argument("kind", choices=CHANNEL_KINDS)
    add.add_argument("--dm", choices=DM_POLICIES, help="private messages from strangers (default: pairing)")
    add.add_argument("--groups", choices=GROUP_MODES, default="mention", help="in a group it is let into, wake on "
                     "a mention (default) or on every message")
    add.add_argument("--group", action="append", default=[], help="let it into this group (repeat; default: none)")
    add.add_argument("--onebot", default=None, help=f"the OneBot 11 implementation's WebSocket (default {ONEBOT})")
    add.add_argument("--address", help=argparse.SUPPRESS)
    add.add_argument("--no-wait", action="store_true", help="do not wait for the login and the owner")
    remove = commands.add_parser("remove", parents=[common], help="disconnect a channel account")
    remove.add_argument("account")
    pair = commands.add_parser("pair", parents=[common], help="pairing requests; approve or revoke one")
    pair.add_argument("what", nargs="?", choices=["list", "approve", "revoke"], default="list")
    pair.add_argument("account", nargs="?")
    pair.add_argument("code", nargs="?", help="approve: the request's code; revoke: the person's account")
    args = parser.parse_args(arguments)

    def run():
        client = _client(args)
        if args.command == "add":
            return _channel_add(args, client)
        if args.command == "remove":
            answer = client.channel("remove", account=args.account)
            _print(args, answer, [f"✓ removed {args.account} ({client.identity})"])
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
        _print(args, rows, [f"channels of {client.identity}"] + channel_lines(rows))
        return 0

    return _guard("channels", run)


def _channel_add(args, client):
    """In the order OpenClaw and Hermes use: the identity (asked first, _client), the policy,
    the login, the groups, then the owner bound with a one-time code."""
    talk = _interactive() and not args.json
    if talk:
        print(f"Which identity answers on this account? ✓ {client.identity}", file=sys.stderr)
    dm = args.dm
    if dm is None:
        dm = _ask("Private messages from strangers? [pairing] / allowlist / open / off", "pairing") if talk else "pairing"
        if dm not in DM_POLICIES:
            raise ValueError(f"the private-chat policy is one of {', '.join(DM_POLICIES)}")
    if not args.address:
        from harness.packages import ensure

        if talk:
            print("installing the OneBot channel package if needed …", file=sys.stderr)
        ensure("spaces", args.kind, log=lambda message: print(message, file=sys.stderr))
    answer = client.channel("add", kind=args.kind, dm=dm, groups=args.groups, onebot=args.onebot, address=args.address)
    account = answer["account"]
    if talk:
        print(f"✓ {account} · log in to the account in your OneBot 11 implementation (NapCat or another) serving "
              f"{answer.get('onebot')}", file=sys.stderr)
    if args.no_wait:
        _print(args, answer, [f"✓ {account} added to {client.identity}; harness channels list shows when it is online"])
        return 0
    row = _wait(lambda: next((r for r in client.channels(account) if r.get("online") and r.get("groups") is not None),
                             None), 600, "waiting for the account to log in")
    if row is None:
        _print(args, answer, [f"{account} is added; it was not online yet. harness channels list shows when it is"])
        return 1
    groups = list(args.group)
    if not groups and talk and row.get("groups"):
        print("Which groups? none by default; numbers separated by spaces:", file=sys.stderr)
        for index, group in enumerate(row["groups"], 1):
            print(f"  {index}. {group.get('name') or group['id']} ({group['id']})", file=sys.stderr)
        picked = _ask(">", "")
        groups = [row["groups"][int(word) - 1]["id"] for word in picked.replace(",", " ").split()
                  if word.isdigit() and 1 <= int(word) <= len(row["groups"])]
    if groups:
        client.channel("groups", account=account, groups=groups, mode=args.groups)
    code = (client.channel("owner_code", account=account).get("result") or {}).get("code")
    lines = [f"✓ {account} · " + (f"entered {len(groups)} group(s), {args.groups}" if groups else "no groups"),
             f"Bind the owner: from your own account, send {code} to it in a private chat"]
    if talk:
        print("\n".join(lines), file=sys.stderr)
        bound = _wait(lambda: next((r.get("owner") for r in client.channels(account) if r.get("owner")), None), 600,
                      "waiting for your message")
        lines = [f"✓ bound {args.kind.upper()} {bound}" if bound else "not bound yet: the code is valid ten minutes"]
    _print(args, {**answer, "groups": groups, "owner_code": code}, lines)
    return 0


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
    parser = argparse.ArgumentParser(prog="harness library", parents=[common],
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
