"""The connectors in the terminal: one list of what the agent is connected to, in the four
classes the app's Connectors page has, each listed, added, removed and tested the same way:

    channels          the accounts of this identity in the kinds of channel the installed
                      channel packages declare (/channels). Every question of adding one, and
                      every word shown, comes from the package's declaration: this file knows
                      no channel.
    MCP servers       /mcp, in the form of Claude Code's /mcp list (a server, how it is
                      reached, whether it is on; Enter for its tools and what can be done)
    external agents   /acp: agents that speak ACP, found here, from the public registry, or a
                      command of your own
    skill sources     where this identity's skills come from besides what it learned, and
                      the shared libraries, read only

a adds to the group the cursor is in, t tests, x removes (asked first), Enter opens a row
with what can be done to it. The host's routes do the work (channels, skill_sources of the
identity; /api/app/mcp and /api/app/acp of the computer), as `harness channels`, `harness
mcp`, `harness agents` and `harness skills` do."""

import asyncio
from shlex import split
import time

from . import views

GROUPS = ("channels", "mcp", "acp", "skills")
TITLES = {"channels": "Channels", "mcp": "MCP servers", "acp": "External agents", "skills": "Skill sources"}
STATES = {"starting": "starting", "waiting_login": "waits for its login", "logged_in": "online",
          "unavailable": "its package is gone"}
HINT = "↑ ↓ move · Enter open · a add · t test · x remove · esc back"


def en(words) -> str:
    """What a declaration says, in the terminal's language (its fixed text is English)."""
    if isinstance(words, dict):
        return str(words.get("en") or next(iter(words.values()), "") or "")
    return str(words or "")


def listing(found: dict) -> tuple[list, list, list]:
    """(rows, headers, items) of the whole list from what each route answered (or the error
    it raised, said in its group)."""
    rows, headers, items = [], [], []

    def group(name, note=""):
        headers.append(len(rows))
        rows.append(TITLES[name] + (f" · {note}" if note else ""))
        items.append(("group", name))

    def problem(name):
        if isinstance(found.get(name), Exception):
            headers.append(len(rows))
            rows.append(f"  could not be read: {found[name]}")
            items.append(("group", name))
            return True
        return False

    channels = found.get("channels")
    group("channels", "" if channels is not None else "of an agent identity: harness --identity ID")
    if channels is not None and not problem("channels"):
        kinds = {kind["kind"]: kind for kind in channels.get("kinds") or ()}
        for row in channels.get("channels") or ():
            kind = en((kinds.get(row.get("kind")) or {}).get("name")) or en(row.get("name")) or str(row.get("kind"))
            values = ", ".join(f"{key} {value}" for key, value in (row.get("values") or {}).items())
            rows.append(f"{str(row.get('title') or row['account'])[:22]:<22} {kind[:16]:<16} "
                        f"{STATES.get(row.get('state'), str(row.get('state'))):<20} "
                        + (f"owner {row['owner']}" if row.get("owner") else "no owner bound") + (f" · {values}" if values else ""))
            items.append(("account", row))
            for request in row.get("pending") or ():
                rows.append(f"  asks to pair: {request.get('name') or request.get('user')} · code {request.get('code')} · "
                            f"until {time.strftime('%H:%M', time.localtime(float(request.get('expires') or 0)))}")
                items.append(("request", row, request))
        for kind, why in (channels.get("problems") or {}).items():
            headers.append(len(rows))
            rows.append(f"  {kind}: its declaration does not read ({why})")
            items.append(("group", "channels"))
        rows.append("＋ Add a channel" if channels.get("kinds") else "＋ Add a channel (no channel package is installed yet)")
        items.append(("add", "channels"))
    group("mcp")
    if not problem("mcp"):
        for row in (found.get("mcp") or {}).get("servers") or ():
            rows.append(f"{row['name'][:22]:<22} {row.get('transport', ''):<6} {'on' if row.get('enabled') else 'off':<4} "
                        f"{str(row.get('target') or '')[:60]}")
            items.append(("server", row))
        rows.append("＋ Add an MCP server")
        items.append(("add", "mcp"))
    group("acp")
    if not problem("acp"):
        for row in (found.get("acp") or {}).get("agents") or ():
            signed = {True: "signed in", False: f"not signed in: {row.get('sign_in') or ''}", None: ""}[row.get("signed_in")]
            rows.append(f"{str(row.get('name') or row['id'])[:22]:<22} {row.get('source', ''):<9} {row.get('state', ''):<10} "
                        + " · ".join(part for part in (signed, str(row.get("plan") or "")) if part))
            items.append(("agent", row))
        rows.append("＋ Add an external agent")
        items.append(("add", "acp"))
    sources = found.get("skills")
    group("skills", "" if sources is not None else "of an agent identity: harness --identity ID")
    if sources is not None and not problem("skills"):
        for row in sources.get("sources") or ():
            names = ", ".join(skill["name"] for skill in row.get("skills") or ())
            rows.append(f"{str(row.get('from'))[:44]:<44} {row.get('kind', ''):<5} {len(row.get('skills') or ())} skills"
                        + (f": {names[:40]}" if names else ""))
            items.append(("source", row))
        for row in sources.get("shared") or ():
            rows.append(f"{str(row.get('name'))[:44]:<44} shared library · {row.get('entries', 0)} entries · read only")
            items.append(("shared", row))
        rows.append("＋ Add a skill source")
        items.append(("add", "skills"))
    return rows, headers, items


async def connectors_view(host, client, note, group=None) -> None:
    """The four classes in one list; `group`: the one the cursor starts in."""
    at = None
    while True:
        found = {}
        for name, read in (("channels", (lambda: client.get("channels")) if client else None),
                           ("mcp", lambda: host.get("/api/app/mcp")), ("acp", lambda: host.get("/api/app/acp")),
                           ("skills", (lambda: client.get("skill_sources")) if client else None)):
            if read is None:
                found[name] = None
                continue
            try:
                found[name] = await asyncio.to_thread(read)
            except Exception as error:  # noqa: BLE001 - said in its group; the others still show
                found[name] = error
        rows, headers, items = listing(found)
        if at is None:
            start = next((index for index, item in enumerate(items) if item == ("group", group or "channels")), 0)
            at = next((index for index in range(start + 1, len(rows)) if index not in headers), 0)
        picked = await views.browse("Connectors", rows, headers=headers, keys=["a", "t", "x"], current=at, hint=HINT)
        if picked is None:
            return
        key, index = picked
        at = index or 0
        item = items[index] if index is not None else ("group", "mcp")
        try:
            if key == "a" or item[0] == "add" and key == "enter":
                where = item[1] if item[0] in ("add", "group") else {"account": "channels", "request": "channels",
                                                                     "server": "mcp", "agent": "acp"}.get(item[0], "skills")
                await {"channels": _add_channel, "mcp": _add_server, "acp": _add_agent, "skills": _add_source}[where](
                    host, client, found.get(where) or {}, note)
            elif item[0] == "account":
                await _account(client, found["channels"], item[1], key, note)
            elif item[0] == "request" and key == "enter":
                if await views.confirm(f"Let {item[2].get('name') or item[2].get('user')} talk to it in a private chat?",
                                       yes="Yes, pair them", no="Not now"):
                    await _wait("Pairing", lambda: client.post("channels", {"action": "pair", "account": item[1]["account"],
                                                                            "code": item[2]["code"]}))
            elif item[0] == "server":
                await _server(host, item[1], key, note)
            elif item[0] == "agent":
                await _agent(host, item[1], key, note)
            elif item[0] == "source":
                await _source(client, item[1], key, note)
            elif item[0] == "shared" and key == "enter":
                await views.read(str(item[1].get("name")), f"A shared library, read only.\n{item[1].get('entries', 0)} entries\n"
                                 f"{item[1].get('folder') or ''}\n\n/library reads its entries.")
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - said; the list opens again
            await views.failed("That did not work", error)


async def _wait(title, call):
    return await views._load(title, call)


async def _menu(title, about, actions) -> str | None:
    picked = await views.choose(title, [label for _, label in actions], text=about, hint="↑↓ move · Enter do it · Esc back")
    return None if picked is None else actions[picked][0]


# -- channels ------------------------------------------------------------------------------

async def _add_channel(host, client, channels, note):
    kinds = channels.get("kinds") or []
    if not kinds:
        await views.read("Add a channel", en(channels.get("from")) or "Channels come from channel packages; none is installed.")
        return
    which = 0 if len(kinds) == 1 else await views.choose(
        "Which kind of channel", [f"{en(kind.get('name'))} — {en(kind.get('about'))}" for kind in kinds],
        text=f"The account will belong to the identity {client.identity} (harness --identity picks another).")
    if which is None:
        return
    kind, values = kinds[which], {}
    for field in kind.get("fields") or ():
        value = await _field(field, field.get("default"))
        if value is None:
            return  # left: nothing was added
        if value != "":
            values[field["id"]] = value
    answer = await _wait(f"Adding {en(kind.get('name'))}", lambda: client.post(
        "channels", {"action": "add", "kind": kind["kind"], "values": values}))
    account = answer.get("account")
    note(f"added the {en(kind.get('name'))} account {account} to {client.identity}")
    steps = kind.get("steps") or []
    if "login" in steps and not await _login(client, account, kind):
        return
    if "groups" in steps and kind.get("groups"):
        await _groups(client, account, kind)
    if "owner" in steps and kind.get("owner"):
        await _owner(client, account)


async def _field(field, now):
    """Ask one declared field; "" for an optional one left empty, None when the add is left."""
    label = en(field.get("label")) or field["id"]
    about = en(field.get("help"))
    kind = field.get("kind")
    if kind == "choice":
        choices = field.get("choices") or []
        current = next((index for index, choice in enumerate(choices) if choice.get("value") == now), 0)
        picked = await views.choose(label, [en(choice) or str(choice.get("value")) for choice in choices], text=about,
                                    current=current, hint="↑↓ move · Enter choose · Esc cancel")
        return None if picked is None else choices[picked]["value"]
    if kind == "bool":
        picked = await views.choose(label, ["No", "Yes"], text=about, current=1 if now else 0)
        return None if picked is None else bool(picked)
    while True:
        value = await views.ask(label + (f" ({about})" if about else ""), "" if kind == "secret" else str(now or ""),
                                hint="Enter next · Esc cancel", secret=kind == "secret")
        if value is None:
            return None
        if value.strip() or not field.get("required"):
            return value.strip()


async def _login(client, account, kind) -> bool:
    """Wait until the account is logged in, showing what its declaration and the channel say."""
    def follow(log):
        said, end = [], time.monotonic() + 600
        while time.monotonic() < end:
            found = client.get("channels", account=account)["channels"]
            row = found[0] if found else {}
            login = row.get("login") or {}
            for line in (en(login.get("text") or (kind.get("login") or {}).get("text")), login.get("url"), login.get("now"),
                         "A QR code waits in the app (Settings › Connectors): a terminal cannot draw it."
                         if login.get("qr") else None):
                if line and line not in said:
                    said.append(line)
                    log(line)
            if row.get("state") == "logged_in":
                return True
            if row.get("state") == "unavailable":
                raise ValueError(row.get("problem") or "the channel's package is gone")
            time.sleep(1.0)
        return False

    done, error = await views.working(f"Logging in to {account}", follow, cancellable=True)
    if isinstance(error, InterruptedError):
        return False  # left: /channels shows where it stands
    if error:
        raise error
    return bool(done)


async def _groups(client, account, kind):
    found = (await _wait("Reading its groups", lambda: client.get("channels", account=account)))["channels"]
    groups = (found[0].get("groups") if found else None)
    if groups is None:
        await views.read("Groups", "The account is not logged in yet: its groups are listed once it is.")
        return
    modes = (kind.get("groups") or {}).get("modes") or []
    mode = None
    if len(modes) > 1:
        picked = await views.choose("In the groups you let it into, it wakes", [en(mode) or mode["value"] for mode in modes])
        if picked is None:
            return
        mode = modes[picked]["value"]
    while True:
        picked = await views.choose("Let it into a group (Enter lets it in or takes it out; Esc when done)",
                                    [f"{'[x]' if group.get('entered') else '[ ]'} {group.get('name') or group['id']} ({group['id']})"
                                     for group in groups], empty="It is in no group.")
        if picked is None:
            return
        group = groups[picked]
        if group.get("entered"):
            await asyncio.to_thread(client.post, "channels", {"action": "leave_group", "account": account, "group": group["id"]})
            group["entered"] = None
        else:
            await asyncio.to_thread(client.post, "channels", {"action": "groups", "account": account, "groups": [group["id"]],
                                                              **({"mode": mode} if mode else {})})
            group["entered"] = mode or True


async def _owner(client, account):
    result = (await _wait("Making a code", lambda: client.post("channels", {"action": "owner_code", "account": account})))["result"]
    await views.read("Bind the owner", f"{en(result.get('text'))}\n\n    {result.get('code')}\n")


async def _account(client, channels, row, key, note):
    kind = next((kind for kind in channels.get("kinds") or () if kind["kind"] == row.get("kind")), {})
    account = row["account"]
    if key == "t":
        action = "test"
    elif key == "x":
        action = "remove"
    else:
        about = "\n".join([f"state    {STATES.get(row.get('state'), row.get('state'))}", f"owner    {row.get('owner') or 'not bound'}",
                           f"groups   {len(row.get('entered') or {})} entered", f"paired   {len(row.get('paired') or ())}",
                           *[f"{name:<8} {value}" for name, value in (row.get("values") or {}).items()]])
        action = await _menu(f"{row.get('title') or account}", about, [
            ("test", "Test it"), *([("login", "Log in")] if row.get("state") != "logged_in" else []),
            *([("groups", "Groups")] if kind.get("groups") else []),
            *([("owner", "Bind the owner (a one-time code)")] if kind.get("owner") else []),
            *([("set", "Change a value")] if kind.get("fields") else []), ("remove", "Remove it")])
    if action == "test":
        result = (await _wait(f"Testing {account}", lambda: client.post("channels", {"action": "test", "account": account})))["result"]
        await views.read(f"{account} answers", "\n".join(f"{name:<8} {value}" for name, value in result.items()))
    elif action == "login":
        await _login(client, account, kind)
    elif action == "groups":
        await _groups(client, account, kind)
    elif action == "owner":
        await _owner(client, account)
    elif action == "set":
        fields = [field for field in kind["fields"] if field.get("kind") != "secret"] or kind["fields"]
        which = await views.choose("Change which value", [f"{en(field.get('label')) or field['id']:<32} "
                                                          f"{(row.get('values') or {}).get(field['id'], '')}" for field in fields])
        if which is None:
            return
        value = await _field(fields[which], (row.get("values") or {}).get(fields[which]["id"]))
        if value is not None:
            await _wait("Saving", lambda: client.post("channels", {"action": "set", "account": account,
                                                                    "values": {fields[which]["id"]: value}}))
    elif action == "remove" and await views.confirm(f"Remove {account} from {client.identity}?", yes="Yes, remove it"):
        await _wait("Removing", lambda: client.post("channels", {"action": "remove", "account": account}))
        note(f"removed the channel account {account}")


# -- MCP servers ---------------------------------------------------------------------------

async def _add_server(host, client, servers, note):
    name = await views.ask("A name for the MCP server (lower-case letters, digits, hyphens)", hint="Enter next · Esc cancel")
    if not name:
        return
    target = await views.ask("Its address (https://…), or the command that starts it", hint="Enter next · Esc cancel")
    if not target or not target.strip():
        return
    target = target.strip()
    secrets = await views.ask("Environment variables or headers it needs, as NAME=value separated by spaces (optional)",
                              hint="Enter add · Esc cancel")
    if secrets is None:
        return
    pairs = dict(pair.split("=", 1) for pair in split(secrets) if "=" in pair)
    if target.startswith(("http://", "https://")):
        body = {"action": "add", "name": name.strip(), "url": target, **({"headers": pairs} if pairs else {})}
    else:
        command, *args = split(target, posix=False)
        body = {"action": "add", "name": name.strip(), "command": command, "args": args, **({"env": pairs} if pairs else {})}
    await _wait(f"Adding {name}", lambda: host.post("/api/app/mcp", body))
    note(f"added the MCP server {name.strip()} · t in /mcp tests it")


async def _server(host, row, key, note):
    name = row["name"]
    if key == "t":
        action = "test"
    elif key == "x":
        action = "remove"
    else:
        about = "\n".join([f"reached   {row.get('transport')} · {row.get('target')}", f"state     {'on' if row.get('enabled') else 'off'}",
                           f"tools     {', '.join(row.get('tools') or ['*'])}",
                           f"secrets   {', '.join([*(row.get('env') or ()), *(row.get('headers') or ())]) or 'none'} (kept, never shown)"])
        action = await _menu(str(row.get("title") or name), about, [
            ("test", "Test it: connect and list its tools"), ("disable" if row.get("enabled") else "enable",
                                                              "Turn it off" if row.get("enabled") else "Turn it on"),
            ("remove", "Remove it")])
    if action == "test":
        result = (await views._load(f"Connecting to {name}", lambda: host.post("/api/app/mcp", {"action": "test", "name": name},
                                                                              timeout=180)))["result"]
        tools = result.get("tools") or []
        await views.read(f"{name} answers in {result.get('seconds')} s · {len(tools)} tools",
                         "\n".join(f"{tool['name']:<28} {tool.get('description') or ''}" for tool in tools) or "It offers no tools.")
    elif action in ("enable", "disable"):
        await _wait("Saving", lambda: host.post("/api/app/mcp", {"action": action, "name": name}))
    elif action == "remove" and await views.confirm(f"Remove the MCP server {name}?", yes="Yes, remove it"):
        await _wait("Removing", lambda: host.post("/api/app/mcp", {"action": "remove", "name": name}))
        note(f"removed the MCP server {name}")


# -- external agents -------------------------------------------------------------------------

async def _add_agent(host, client, agents, note):
    how = await views.choose("Add an external agent", ["From the public registry of ACP agents", "A command of your own"],
                             text="An external agent runs under its own sign-in: nothing of it is installed or signed in for you.")
    if how is None:
        return
    if how == 0:
        listed = [row for row in (await views._load("Reading the registry", lambda: host.get("/api/app/acp?registry=1")))["agents"]
                  if row.get("state") == "available"]
        picked = await views.choose("Which agent", [f"{str(row.get('name') or row['id']):<28} {row.get('version') or ''}"
                                                    for row in listed], empty="Every agent of the registry is connected already.")
        if picked is None:
            return
        name = listed[picked]["id"]
        await views._load(f"Connecting {listed[picked].get('name') or name}", lambda: host.post(
            "/api/app/acp", {"action": "add", "name": name}, timeout=600))
    else:
        name = await views.ask("A name for it", hint="Enter next · Esc cancel")
        command = await views.ask("The command that starts it speaking ACP", hint="Enter add · Esc cancel") if name else None
        if not name or not command:
            return
        await _wait(f"Adding {name}", lambda: host.post("/api/app/acp", {"action": "add", "name": name.strip(),
                                                                          "argv": split(command, posix=False)}))
    note(f"added the external agent {name} · t in /acp tests it; /model makes it the model")


async def _agent(host, row, key, note):
    identifier, name = row["id"], str(row.get("name") or row["id"])
    if key == "t":
        action = "test"
    elif key == "x":
        action = "remove"
    else:
        about = "\n".join([f"id        {identifier}", f"from      {row.get('source')}", f"state     {row.get('state')}",
                           f"version   {row.get('version') or '—'}",
                           f"sign-in   {'signed in' if row.get('signed_in') else row.get('sign_in') or 'unknown'}",
                           f"paid by   {row.get('plan') or '—'}"])
        action = await _menu(name, about, [("test", "Test it: have it answer one word (this uses its own plan)"),
                                           ("remove", "Remove it")])
    if action == "test":
        if key == "t" and not await views.confirm(f"Have {name} answer one word?", "The call is made under its own sign-in and plan.",
                                                  yes="Yes, test it"):
            return
        result = (await views._load(f"Asking {name}", lambda: host.post("/api/app/acp", {"action": "test", "id": identifier},
                                                                       timeout=300)))["result"]
        await views.read(f"{name} answers in {result.get('seconds')} s", str(result.get("reply") or ""))
    elif action == "remove" and await views.confirm(f"Remove the external agent {name}?", yes="Yes, remove it"):
        await _wait("Removing", lambda: host.post("/api/app/acp", {"action": "remove", "id": identifier}))
        note(f"removed the external agent {name}")


# -- skill sources ---------------------------------------------------------------------------

async def _add_source(host, client, sources, note):
    origin = await views.ask("Where the skills come from: a folder or SKILL.md here, github:OWNER/REPO[#FOLDER], "
                             "git:URL, or an address", hint="Enter next · Esc cancel")
    if not origin or not origin.strip():
        return
    found = (await views._load("Reading it", lambda: client.post("skill_sources", {"action": "test", "from": origin.strip()},
                                                                 )))["result"]
    names = "\n".join(f"{skill['name']:<28} {skill.get('description') or ''}" + ("  (has a program: set aside until tested here)"
                                                                               if skill.get("program") else "")
                      for skill in found.get("skills") or ())
    if not await views.confirm(f"Take these {len(found.get('skills') or ())} skills as proposals?", names, yes="Yes, add the source"):
        return
    result = (await views._load("Adding", lambda: client.post("skill_sources", {"action": "add", "from": origin.strip()})))["result"]
    note(f"added the skill source {result.get('from')}: {', '.join(result.get('added') or ()) or 'no new skill'}"
         + (f" (already here: {', '.join(result['skipped'])})" if result.get("skipped") else ""))


async def _source(client, row, key, note):
    identifier = row["id"]
    if key == "t":
        action = "test"
    elif key == "x":
        action = "remove"
    else:
        about = "\n".join([f"from     {row.get('from')}", f"kind     {row.get('kind')}",
                           *[f"skill    {skill['name']} · {skill.get('evidence')}" + ("" if skill.get("there", True) else " (removed)")
                             for skill in row.get("skills") or ()]])
        action = await _menu(str(row.get("from")), about, [("test", "Test it: read what it holds now"),
                                                            ("update", "Update: take in skills that are new there"),
                                                            ("remove", "Remove it")])
    if action == "test":
        result = (await views._load("Reading it", lambda: client.post("skill_sources", {"action": "test", "id": identifier})))["result"]
        await views.read(f"{result.get('from')} · {len(result.get('skills') or ())} skills · {result.get('seconds')} s",
                         "\n".join(f"{skill['name']:<28} {skill.get('description') or ''}" for skill in result.get("skills") or ()))
    elif action == "update":
        result = (await views._load("Reading it", lambda: client.post("skill_sources", {"action": "update", "id": identifier})))["result"]
        new = (result.get("updated") or {}).get(identifier) or []
        note(f"skill source updated: {', '.join(new) if new else 'nothing new'}")
    elif action == "remove":
        picked = await views.choose(f"Remove the source {row.get('from')}?", ["No", "Yes, with the skills it brought",
                                                                              "Yes, but keep its skills"])
        if picked in (1, 2):
            await _wait("Removing", lambda: client.post("skill_sources", {"action": "remove", "id": identifier, "keep": picked == 2}))
            note(f"removed the skill source {row.get('from')}")
