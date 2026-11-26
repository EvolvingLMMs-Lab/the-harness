"""Chat channels, as the packages that provide them declare them. The agent knows no channel
by name: a channel is a space a package serves (spaces/<kind>.toml: `line`, `entry`) whose
declaration has a [channel] table, and everything a frontend shows or asks, and every verb
and event the life uses, comes from that table.

    [channel]
    name = { en = "Example chat", zh = "示例聊天" }     # what the kind is called
    about = { en = "One account of ...", zh = "……" }   # one line under it
    serve = ["--config", "{config}"]                    # the entry's arguments for one account:
                                                        # {config} the account's file, {account},
                                                        # {identity}, and {<id>} of a field

    [[channel.fields]]                                  # step 1, after the identity: its policies
    id = "dm"                                           # and whatever the account needs
    kind = "choice"                                     # choice, text, bool or secret
    label = { en = "Private messages from strangers", zh = "陌生人私聊" }
    help = { en = "...", zh = "……" }                    # optional
    default = "pairing"
    choices = [{ value = "pairing", en = "Pairing code", zh = "配对码" }, ...]
    # a secret (a bot token) is kept with the credentials, never in the account's file, and
    # reaches the entry in the environment variable it names: env = "EXAMPLE_TOKEN"

    [channel.login]                                     # step 2: how the account logs in
    text = { en = "Scan the code with ...", zh = "……" } # shown while it waits; {<id>} of a field
    verb = "example.login"                              # optional: asked as the owner while it
                                                        # waits; its result ({qr, url, text}: an
                                                        # image as a data: URL, a link, a line) is shown
    online = "example.online"                           # the event (data.online) that tells logged in or out

    [channel.groups]                                    # step 3; left out by a channel without groups
    list = "example.groups"                             # -> {groups: [{group, name, entered}]}
    enter = "example.enter_group"                       # args {group, mode}
    leave = "example.leave_group"                       # args {group}
    modes = [{ value = "mention", en = "When it is named", zh = "被点名时" }, ...]   # the first is the default

    [channel.owner]                                     # step 4: binding the owner's own account
    code = "example.owner_code"                         # -> {code, expires}
    bound = "example.owner_bound"                       # the event (data.user) once the code arrived
    text = { en = "From your own account, send this code to it in a private chat.", zh = "……" }

    [channel.pairing]                                   # strangers; left out when it has none
    requested = "example.pairing_requested"             # the event (data: user, name, code, expires)
    approve = "example.pair"                            # args {code} -> {user}
    revoke = "example.unpair"                           # args {user}

    [channel.messages]
    event = "example.message"                           # a message came in (data: chat, text, message,
                                                        # name, owner, addressed); a chat is
                                                        # "private:<user>" or anything else for a group
    reply = "example.reply"                             # object: the message; args {text}
    send = "example.send"                               # object: the chat; args {text}

An account is one place of an identity (places.json, `channel`: its kind). Its file
channels/<account>.json in the identity's folder is made here with `identity` and the values
of its fields, and the space keeps what it learns there under these names: `owner` (the bound
owner's account), `paired` (accounts), `pending` ({code: {user, name, expires}}), `groups`
({group: mode}). The owner's verbs are acted as the owner, with the identity's own key.

The host route /api/agent/channels is channels(); harness channels, /channels and
harness.sdk.Agent draw the same steps from the same declarations."""
import re
import time

from harness.sdk import Credentials, Problem, data

from .state import read, save

STEPS = ("policies", "login", "groups", "owner")
KINDS_OF_FIELD = ("choice", "text", "bool", "secret")
NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
# Where channels come from, told wherever none is installed.
FROM = {"en": "Channels come from packages. None is installed: install one that provides a channel "
              "(harness list --available lists the registry's packages; harness install NAME installs one).",
        "zh": "渠道由扩展包提供。现在一个都没有安装：安装一个提供渠道的扩展包"
              "（harness list --available 列出可安装的包，harness install 名字 安装）。"}


def words(value, fallback="") -> dict:
    """A text in both languages ({en, zh}) from what a declaration gives: a table with one or
    both, or one string for both."""
    if isinstance(value, dict):
        en = str(value.get("en") or value.get("zh") or fallback)
        return {"en": en, "zh": str(value.get("zh") or en)}
    text = str(value) if value not in (None, "") else str(fallback)
    return {"en": text, "zh": text}


def _verb(table, key, where, problems, required=False):
    value = (table or {}).get(key)
    if value in (None, ""):
        if required:
            problems.append(f"{where}.{key} is missing")
        return None
    if not isinstance(value, str):
        problems.append(f"{where}.{key} is a verb or event name")
        return None
    return value


def checked(kind: str, package: str, space: dict) -> dict:
    """The declaration of the channel `kind` as every frontend reads it, from its space's
    declaration; a ValueError says what in it does not read."""
    table = space.get("channel")
    if not isinstance(table, dict):
        raise ValueError("no [channel] table")
    problems = []
    fields = []
    for row in table.get("fields") or ():
        if not isinstance(row, dict) or not NAME.fullmatch(str(row.get("id") or "")):
            problems.append("a field needs an id of lowercase letters, digits and _")
            continue
        field_kind = row.get("kind", "text")
        if field_kind not in KINDS_OF_FIELD:
            problems.append(f"field {row['id']}: kind is one of {', '.join(KINDS_OF_FIELD)}")
            continue
        field = {"id": row["id"], "kind": field_kind, "label": words(row.get("label"), row["id"]),
                 "help": words(row.get("help")), "default": row.get("default"),
                 "required": bool(row.get("required", False))}
        if field_kind == "choice":
            choices = [{"value": choice.get("value"), **words(choice, choice.get("value"))}
                       for choice in row.get("choices") or () if isinstance(choice, dict) and "value" in choice]
            if not choices:
                problems.append(f"field {row['id']}: a choice needs choices")
                continue
            field["choices"] = choices
            if field["default"] is None:
                field["default"] = choices[0]["value"]
        if field_kind == "secret":
            if not isinstance(row.get("env"), str) or not row["env"].isidentifier():
                problems.append(f"field {row['id']}: a secret names the environment variable it reaches the "
                                "space in (env)")
                continue
            field["env"] = row["env"]
            field["default"] = None
        fields.append(field)
    names = {field["id"] for field in fields if field["kind"] != "secret"} | {"config", "account", "identity"}
    serve = table.get("serve", ["--config", "{config}"])
    if not isinstance(serve, list) or any(not isinstance(word, str) for word in serve):
        problems.append("serve is the list of the entry's arguments")
        serve = []
    for word in serve:
        for name in PLACEHOLDER.findall(word):
            if name not in names:
                problems.append(f"serve names {{{name}}}, which is no field of it")
    login = table.get("login") if isinstance(table.get("login"), dict) else {}
    groups = table.get("groups") if isinstance(table.get("groups"), dict) else None
    owner = table.get("owner") if isinstance(table.get("owner"), dict) else None
    pairing = table.get("pairing") if isinstance(table.get("pairing"), dict) else None
    messages = table.get("messages") if isinstance(table.get("messages"), dict) else {}
    found = {
        "kind": kind, "package": package, "name": words(table.get("name"), kind),
        "about": words(table.get("about"), space.get("line") or ""), "serve": list(serve), "fields": fields,
        "login": {"text": words(login.get("text")), "verb": _verb(login, "verb", "login", problems),
                  "online": _verb(login, "online", "login", problems)},
        "groups": None, "owner": None, "pairing": None,
        "messages": {"event": _verb(messages, "event", "messages", problems, required=True),
                     "reply": _verb(messages, "reply", "messages", problems),
                     "send": _verb(messages, "send", "messages", problems)},
    }
    if groups is not None:
        modes = [{"value": mode.get("value"), **words(mode, mode.get("value"))}
                 for mode in groups.get("modes") or () if isinstance(mode, dict) and "value" in mode]
        found["groups"] = {"list": _verb(groups, "list", "groups", problems, required=True),
                           "enter": _verb(groups, "enter", "groups", problems, required=True),
                           "leave": _verb(groups, "leave", "groups", problems), "modes": modes}
    if owner is not None:
        found["owner"] = {"code": _verb(owner, "code", "owner", problems, required=True),
                          "bound": _verb(owner, "bound", "owner", problems, required=True),
                          "text": words(owner.get("text"))}
    if pairing is not None:
        found["pairing"] = {"requested": _verb(pairing, "requested", "pairing", problems),
                            "approve": _verb(pairing, "approve", "pairing", problems, required=True),
                            "revoke": _verb(pairing, "revoke", "pairing", problems)}
    if problems:
        raise ValueError("; ".join(problems))
    found["steps"] = [step for step in STEPS if step in ("policies", "login") or found[step] is not None]
    return found


def kinds() -> tuple:
    """({kind: declaration}, {kind: why its declaration does not read}) of the channels the
    enabled packages provide. Nothing is cached: a package installed a moment ago is there."""
    from harness.sdk import served_spaces

    found, problems = {}, {}
    for name, (package, space) in sorted(served_spaces().items()):
        if "channel" not in space or not space.get("entry"):
            continue
        try:
            found[name] = checked(name, package.name, space)
        except ValueError as error:
            problems[name] = f"the package {package.name} declares the channel {name} in a way that does not read: {error}"
    return found, problems


def declared(kind):
    """The declaration of the channel `kind`, or None when no enabled package provides it."""
    return kinds()[0].get(kind)


def _declaration(kind) -> dict:
    found, problems = kinds()
    if kind in found:
        return found[kind]
    if kind in problems:
        raise Problem(problems[kind], "update the package that provides it (harness install --update)",
                      code="channel_declaration")
    have = ", ".join(sorted(found))
    raise Problem(f"no installed package provides a channel called {kind!r}",
                  (f"the installed ones are {have}; " if have else "") + "harness install NAME installs a package "
                  "that provides one (harness list --available lists them)", code="no_channel_kind")


def render(text: str, values: dict) -> str:
    """`text` with {name} taken from `values` (a name it does not have stays as it is)."""
    return PLACEHOLDER.sub(lambda match: str(values[match[1]]) if match[1] in values else match[0], str(text))


def _values(declaration, given, *, complete=True) -> tuple:
    """(values, secrets) of an account's fields from what was given: each checked against
    its field; with `complete`, the defaults for the rest and an error for a required one
    that is missing."""
    given = dict(given or {})
    fields = {field["id"]: field for field in declaration["fields"]}
    unknown = sorted(set(given) - set(fields))
    if unknown:
        raise Problem(f"{declaration['name']['en']} has no field {unknown[0]!r}",
                      "its fields are " + (", ".join(fields) or "none"), code="no_field")
    values, secrets = {}, {}
    for name, field in fields.items():
        value = given.get(name)
        if value in (None, ""):
            if not complete and name not in given:
                continue
            value = field["default"]
        if value in (None, ""):
            if field["required"] and complete:
                raise Problem(f"{field['label']['en']} is needed", f"give a value for the field {name}", code="field_required")
            continue
        if field["kind"] == "choice":
            allowed = [choice["value"] for choice in field["choices"]]
            if value not in allowed:
                raise Problem(f"{field['label']['en']} is one of {', '.join(map(str, allowed))}", f"not {value!r}",
                              code="field_choice")
        elif field["kind"] == "bool":
            if isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "yes", "on")
            value = bool(value)
        else:
            value = str(value).strip()
        (secrets if field["kind"] == "secret" else values)[name] = value
    return values, secrets


def _secret_name(account, field) -> str:
    return "HARNESS_CHANNEL_" + re.sub(r"[^A-Z0-9]", "_", f"{account}_{field}".upper())


def _serve(declaration, account, identity, config, values) -> list:
    known = {**values, "config": config, "account": account, "identity": identity}
    return [declaration["kind"], *(render(word, known) for word in declaration["serve"])]


def accounts(life) -> list:
    from . import places as places_module

    return [row for row in places_module.load(life.identity) if row.get("channel")]


def _row(life, account) -> dict:
    row = next((row for row in accounts(life) if row["id"] == account), None)
    if row is None:
        raise Problem(f"no channel account {account!r} on identity {life.identity.id}",
                      "harness channels lists the accounts", code="no_account")
    return row


def add(life, body) -> dict:
    """Step 1: an account of the kind `kind` for this identity, with the values of its
    fields; its space starts and the login begins. {account, state, login}."""
    from . import places as places_module

    declaration = _declaration(str(body.get("kind") or ""))
    kind = declaration["kind"]
    values, secrets = _values(declaration, body.get("values"))
    taken = {row["id"] for row in places_module.load(life.identity)}
    account = kind if kind not in taken else next(f"{kind}-{n}" for n in range(2, 1000) if f"{kind}-{n}" not in taken)
    config = f"channels/{account}.json"
    save(life.identity.directory / config, {"identity": life.identity.id, **values})
    kept = {}
    for name, value in secrets.items():
        field = next(field for field in declaration["fields"] if field["id"] == name)
        Credentials(data()).keep(_secret_name(account, name), value)
        kept[field["env"]] = _secret_name(account, name)
    fields = {"id": account, "title": str(body.get("title") or declaration["name"]["en"]), "channel": kind,
              "config": config, "values": values, **({"secrets": kept} if kept else {})}
    if body.get("address"):
        fields["address"] = body["address"]  # a space that runs already
    else:
        fields["serve"] = _serve(declaration, account, life.identity.id, config, values)
    row = life.connect("space", **fields)
    return {"account": row["id"], "kind": kind}


def change(life, account, given) -> dict:
    """Change the values of an account's fields: kept in its file, and its space started
    again so that it reads them."""
    row = _row(life, account)
    declaration = _declaration(row["channel"])
    values, secrets = _values(declaration, given, complete=False)
    path = life.identity.directory / row["config"]
    save(path, {**read(path, {}), **values})
    kept = dict(row.get("secrets") or {})
    for name, value in secrets.items():
        field = next(field for field in declaration["fields"] if field["id"] == name)
        Credentials(data()).keep(_secret_name(account, name), value)
        kept[field["env"]] = _secret_name(account, name)
    merged = {**(row.get("values") or {}), **values}
    changed = {"values": merged, **({"secrets": kept} if kept else {})}
    if row.get("serve"):
        changed["serve"] = _serve(declaration, account, life.identity.id, row["config"], merged)
    life.reconnect(account, **changed)
    return {"account": account, "values": merged}


def remove(life, account) -> dict:
    row = _row(life, account)
    life.disconnect(account)
    if row.get("config"):
        (life.identity.directory / row["config"]).unlink(missing_ok=True)
    for name in (row.get("secrets") or {}).values():
        Credentials(data()).keep(name, None)
    return {"removed": account}


def _key(life):
    try:
        import base64
        from agent_space.identity import KeyPair

        stored = read(life.identity.root / ".keys" / f"{life.identity.id}.json", None)
        return KeyPair(base64.b64decode(stored["seed"])) if stored else None
    except Exception:
        return None


def owner_act(life, account, verb, args):
    """What only the owner may do in a channel (its groups, binding, pairing): done through
    the host as the account's owner, the identity's own key. The verb's result."""
    _row(life, account)
    place = life.places.get(account)
    environment = getattr(place, "environment", None)
    if environment is None or not getattr(place, "online", False):
        raise Problem(f"channel {account} is not connected yet", "it starts with the session host; harness channels "
                      "shows when it is there", code="channel_offline")
    from harness.space.environment import SpaceEnvironment

    owner = SpaceEnvironment.connect(environment.address, key=_key(life), role="owner", timeout=30)
    try:
        outcome = owner.participant.act(verb, None, args, id=owner.next_id(), timeout=30)
    finally:
        owner.close()
    end = getattr(outcome.end, "value", outcome.end)
    if end != "done":
        reason = outcome.reason
        why = getattr(reason, "text", None) or getattr(reason, "code", None) or reason
        raise Problem(f"{verb} ended {end}: {why}", code="channel_refused")
    return outcome.result


def _need(declaration, part, what) -> dict:
    if declaration.get(part) is None:
        raise Problem(f"{declaration['name']['en']} has no {what}", code="not_declared")
    return declaration[part]


def enter_groups(life, account, groups, mode=None) -> dict:
    """Step 3: let the account into these groups (none by default), each with `mode`."""
    part = _need(_declaration(_row(life, account)["channel"]), "groups", "groups")
    modes = [row["value"] for row in part["modes"]]
    mode = mode or (modes[0] if modes else None)
    if modes and mode not in modes:
        raise Problem(f"a group's mode is one of {', '.join(map(str, modes))}", f"not {mode!r}", code="group_mode")
    entered = []
    for group in [str(group) for group in (groups if isinstance(groups, list) else [groups])]:
        owner_act(life, account, part["enter"], {"group": group, **({"mode": mode} if mode else {})})
        entered.append(group)
    return {"entered": entered, "mode": mode}


def leave_group(life, account, group) -> dict:
    part = _need(_declaration(_row(life, account)["channel"]), "groups", "groups")
    if not part.get("leave"):
        raise Problem("this channel does not take an account out of a group", code="not_declared")
    owner_act(life, account, part["leave"], {"group": str(group)})
    return {"left": str(group)}


def owner_code(life, account) -> dict:
    """Step 4: a one-time code the owner sends the account from their own account; shown in
    the main conversation too."""
    part = _need(_declaration(_row(life, account)["channel"]), "owner", "owner to bind")
    result = owner_act(life, account, part["code"], {}) or {}
    life.chats.record("main", "channel", account=account, owner_code=result.get("code"),
                      expires=result.get("expires"), text=part["text"])
    return {"code": result.get("code"), "expires": result.get("expires"), "text": part["text"]}


def pair(life, account, code) -> dict:
    part = _need(_declaration(_row(life, account)["channel"]), "pairing", "pairing")
    return owner_act(life, account, part["approve"], {"code": str(code or "").strip().upper()}) or {}


def unpair(life, account, user) -> dict:
    part = _need(_declaration(_row(life, account)["channel"]), "pairing", "pairing")
    if not part.get("revoke"):
        raise Problem("this channel does not revoke a pairing", code="not_declared")
    return owner_act(life, account, part["revoke"], {"user": str(user or "")}) or {}


def rows(life, account=None) -> list:
    """The identity's channel accounts. One asked for by name also has its groups and what
    its login shows now."""
    found, _ = kinds()
    listed = []
    for row in accounts(life):
        if account and row["id"] != account:
            continue
        declaration = found.get(row["channel"])
        place = life.places.get(row["id"])
        config = read(life.identity.directory / row["config"], {}) if row.get("config") else {}
        online = bool(getattr(place, "online", False))
        now = time.time()
        values = dict(row.get("values") or {})
        item = {"account": row["id"], "kind": row.get("channel"), "title": row.get("title"),
                "name": declaration["name"] if declaration else words(row.get("channel")),
                "identity": life.identity.id, "online": online, "values": values,
                "entered": config.get("groups") or {}, "owner": config.get("owner") or row.get("owner"),
                "paired": config.get("paired") or [],
                "pending": [{"code": code, **request} for code, request in (config.get("pending") or {}).items()
                            if float(request.get("expires") or 0) > now]}
        if declaration is None:
            item.update(state="unavailable", problem=f"no installed package provides the channel {row.get('channel')}")
            listed.append(item)
            continue
        logged_in = life.logged_in.get(row["id"])
        groups = None
        if online and declaration["groups"] and (account or logged_in is None):
            # Asking for its groups also tells whether it is logged in (when no event said so yet).
            try:
                answer = (owner_act(life, row["id"], declaration["groups"]["list"], {}) or {}).get("groups") or []
                groups = [{"id": str(group.get("group")), "name": group.get("name"), "entered": group.get("entered")}
                          for group in answer]
                logged_in = life.logged_in[row["id"]] = True
            except (ValueError, OSError, RuntimeError):
                logged_in = bool(logged_in)
        if logged_in is None:
            logged_in = online and not declaration["login"]["online"]
        item["state"] = "logged_in" if online and logged_in else "waiting_login" if online else "starting"
        item["login"] = {"text": {key: render(text, values) for key, text in declaration["login"]["text"].items()}}
        if account:
            item["groups"] = groups
            if item["state"] == "waiting_login" and declaration["login"]["verb"]:
                try:
                    shown = owner_act(life, row["id"], declaration["login"]["verb"], {}) or {}
                    # What the channel shows for this login now: a code to scan, a link, a line.
                    item["login"].update({key: str(shown[key]) for key in ("qr", "url") if shown.get(key)})
                    if shown.get("text"):
                        item["login"]["now"] = str(shown["text"])
                except (ValueError, OSError, RuntimeError):
                    pass
        listed.append(item)
    return listed


def channels(server, body):
    """GET {account}: the kinds of channel the installed packages declare (`kinds`, with what
    each step asks and shows; `from`: where channels come from, for when there is none), and
    the identity's accounts (`channels`; one named by `account` also has its groups and what
    its login shows). POST {action: add | set | groups | leave_group | owner_code | pair |
    unpair | remove, ...}: one step; `result` is what it gave."""
    from .host import _life, _one

    life = _life(server, body)
    action = _one(body.get("action"))
    account = _one(body.get("account"))
    result = None
    if action == "add":
        result = add(life, body)
        account = result["account"]
    elif action == "set":
        result = change(life, account, body.get("values"))
    elif action == "groups":
        result = enter_groups(life, account, body.get("groups") or [], body.get("mode"))
    elif action == "leave_group":
        result = leave_group(life, account, body.get("group"))
    elif action == "owner_code":
        result = owner_code(life, account)
    elif action == "pair":
        result = pair(life, account, body.get("code"))
    elif action == "unpair":
        result = unpair(life, account, body.get("user"))
    elif action == "remove":
        result = remove(life, account)
        account = None
    elif action:
        raise Problem(f"no channel action {action!r}", "the actions are add, set, groups, leave_group, owner_code, "
                      "pair, unpair and remove", code="no_action")
    found, problems = kinds()
    return {"identity": life.identity.id, "kinds": list(found.values()), "problems": problems, "from": FROM,
            "channels": rows(life, account), **({"result": result} if result is not None else {}),
            **({"account": account} if action == "add" else {})}
