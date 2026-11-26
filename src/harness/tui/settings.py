"""/config (/settings), /permissions and /agent in the terminal.

/config lists every setting by the name people read (its title, from the settings'
descriptions: the same titles, explanations and choice names the app's Settings shows), under
the page the app has it on, with its value said in words; typing searches titles, pages,
keys and values (Claude Code's /config: a searchable list, Enter changes the chosen setting,
Esc closes with the changes kept). A setting of an identity (its limits, its learning) is
read and written for the identity the chat runs as; every other one for this computer.
/permissions is the same list, of the page "Permissions and limits".

/agent lists the identities: Enter makes one the current one, n makes a new one (which may
take the persona, skills and reactions of another, never its memory), r renames, x deletes
after listing what goes with it (Hermes's profile commands, with our names)."""

import asyncio

from ..core import format as formats
from . import views

ORDER = ("General", "Model", "Permissions and limits", "What it learned", "Personalization", "Packages", "Data", "Computer",
         "About")
PAGES = {"general": "General", "terminal": "General", "session": "General", "agent": "General", "model": "Model",
         "approvals": "Permissions and limits", "physical": "Permissions and limits", "privacy": "Permissions and limits",
         "limits": "Permissions and limits", "environments": "Permissions and limits", "learning": "What it learned",
         "instructions": "Personalization", "personal": "Personalization", "packages": "Packages", "data": "Data",
         "computer": "Computer", "app": "About"}
KEYS = {"agent.daily_budget": "Permissions and limits", "agent.daily_calls": "Permissions and limits",
        "agent.reserve": "Permissions and limits", "agent.keep_days": "Data", "agent.model": "Model"}
# Settings that are not the terminal's to show: the page's own looks, and keys kept for old files.
LEFT_OUT = ("general.language", "general.theme", "general.open_browser", "model.reasoning_effort",
            "model.think_while_acting", "model.think_interval")


def en(words, fallback="") -> str:
    if isinstance(words, dict):
        return str(words.get("en") or fallback)
    return str(words or fallback)


def described() -> dict:
    """{section: {key: description}} of every setting: its title, what it is, its kind and
    the names of its choices (settings.described where the core has it)."""
    from .. import settings

    found = getattr(settings, "described", None)
    if found is not None:
        return found()
    return {section: {key: {"name": f"{section}.{key}", "title": {"en": key.replace("_", " ").capitalize()},
                            "about": {"en": spec.about}, "type": spec.kind, "choices": list(spec.bounds or ())
                            if spec.kind == "choice" else None, "bounds": spec.bounds, "labels": None, "scope": "global",
                            "applies": spec.applies} for key, spec in keys.items()}
            for section, keys in settings.SCHEMA.items()}


def page_of(name: str) -> str:
    section = name.split(".", 1)[0]
    return KEYS.get(name) or PAGES.get(section) or section.replace("_", " ").capitalize()


def shown(description: dict, value) -> str:
    """A value in words: a choice by its name, a switch as on or off, rules by their count."""
    kind = description.get("type") or description.get("kind")
    if kind == "rules":
        return f"{len(value or ())} rule{'' if len(value or ()) == 1 else 's'}"
    if kind == "bool":
        return "on" if value else "off"
    if kind == "choice":
        return en((description.get("labels") or {}).get(value), str(value))
    return formats.clip(str(value).replace("\n", " "), 50) if value not in ("", None) else "(empty)"


def settings_rows(schema: dict, values: dict, own: dict | None = None, pages=None) -> list:
    """Every setting as {name, section, key, page, title, about, description, value, scope},
    in the order of the app's pages; `own`: {name: value} of the identity's own settings."""
    out = []
    for section, keys in schema.items():
        for key, description in keys.items():
            name = f"{section}.{key}"
            page = page_of(name)
            if name in LEFT_OUT or pages is not None and page not in pages:
                continue
            identity = description.get("scope") == "identity" and own is not None
            value = own[name] if identity and name in own else (values.get(section) or {}).get(key, description.get("default"))
            out.append({"name": name, "section": section, "key": key, "page": page,
                        "title": en(description.get("title"), key), "about": en(description.get("about")),
                        "description": description, "value": value, "scope": "identity" if identity else "global"})
    rank = {page: index for index, page in enumerate(ORDER)}
    return sorted(out, key=lambda row: (rank.get(row["page"], len(ORDER)), row["page"]))


async def config_view(directory, client=None, pages=None, title="Settings") -> list[str]:
    """Change settings one at a time until closed; what changed, as lines. `client`: the
    identity's routes, for the settings an identity has of its own."""
    from ..settings import SCHEMA, Settings

    store, changed, at = Settings(directory), [], 0
    while True:
        values, schema, own = store.get(), described(), None
        if client is not None:
            try:
                answer = await asyncio.to_thread(client.get, "settings")
                own = answer.get("values") or {}
                for name, description in (answer.get("schema") or {}).items():
                    section, _, key = name.partition(".")
                    schema.setdefault(section, {})[key] = description
            except Exception:  # noqa: BLE001 - a host without them: the computer's settings alone
                own = None
        found = settings_rows(schema, values, own, pages)
        lines = [f"{row['page'] + ' › ' + row['title']:<58} {shown(row['description'], row['value'])}" for row in found]
        about = [f"{row['about']}\n{row['name']}" + (f" · for the identity {client.identity}" if row["scope"] == "identity" else "")
                 for row in found]
        at = await views.choose(title, lines, current=at, about=about,
                                hint="↑↓ move · Enter change · type to search · Esc close")
        if at is None:
            return changed
        row = found[at]
        description, kind = row["description"], row["description"].get("type") or row["description"].get("kind")
        try:
            if kind == "bool":
                value = not row["value"]
            elif kind == "choice":
                choices = list(description.get("choices") or description.get("bounds") or ())
                picked = await views.choose(row["title"], [en((description.get("labels") or {}).get(choice), str(choice))
                                                           for choice in choices], text=row["about"],
                                            current=choices.index(row["value"]) if row["value"] in choices else 0,
                                            hint="↑↓ move · Enter choose · Esc keep it as it is")
                value = None if picked is None else choices[picked]
            elif kind == "rules":
                value = await views._rules({"setting": row["name"], "about": row["about"], "value": row["value"] or [],
                                            "section": row["section"], "key": row["key"]}, SCHEMA[row["section"]][row["key"]])
            else:
                typed = await views.ask(f"{row['title']} ({row['about']})", "" if row["value"] is None else str(row["value"]),
                                        hint="Enter save · Esc keep it as it is")
                value = None if typed is None else int(typed) if kind == "int" else float(typed) if kind == "float" else typed
            if value is None or value == row["value"]:
                continue
            if row["scope"] == "identity":
                await asyncio.to_thread(client.post, "settings", {"key": row["name"], "value": value})
            else:
                store.update({row["section"]: {row["key"]: value}})
            changed.append(f"{row['title']} ({row['name']}) = {shown(description, value)}")
        except Exception as error:  # noqa: BLE001 - said; nothing was changed
            await views.failed("Not changed", error)


async def identities_view(host, current: str | None):
    """/agent: the identities. Returns the {id, name} to open when one was made current, None
    when closed."""
    at = 0
    while True:
        try:
            found = await asyncio.to_thread(host.get, "/api/agent/identities")
        except Exception as error:  # noqa: BLE001
            await views.failed("The identities could not be read", error)
            return None
        rows = [f"{'●' if row.get('current') else ' '} {row['id'][:20]:<20} {str(row.get('name') or '')[:24]:<24} "
                f"{'(open here)' if row['id'] == current else ''}" for row in found]
        picked = await views.browse("Identities", rows, keys=["n", "r", "x"], current=at,
                                    top="● the current one: what harness opens",
                                    hint="↑ ↓ move · Enter use · n new · r rename · x delete · esc back",
                                    empty="No identity yet. n makes one.")
        if picked is None:
            return None
        key, index = picked
        at = index or 0
        row = found[index] if index is not None else None

        def change(body):
            return host.post("/api/agent/identity", body)

        try:
            if key == "n":
                name = await views.ask("The new identity's id (letters, digits, hyphens; it never changes)",
                                       hint="Enter next · Esc cancel")
                if not name or not name.strip():
                    continue
                display = await views.ask("Its name, as it is shown (it can change later; empty: the id)",
                                          hint="Enter next · Esc cancel")
                if display is None:
                    continue
                source = await views.choose("Start it from", ["Nothing: a new persona", *[
                    f"{other['id']}: its persona, skills and reactions (never its memory)" for other in found]])
                if source is None:
                    continue
                await asyncio.to_thread(change, {"action": "new", "id": name.strip(), **({"name": display.strip()} if display.strip() else {}),
                                                 **({"from": found[source - 1]["id"]} if source else {})})
            elif row is None:
                continue
            elif key == "enter":
                await asyncio.to_thread(change, {"action": "use", "id": row["id"]})
                return {"id": row["id"], "name": row.get("name") or row["id"]}
            elif key == "r":
                name = await views.ask(f"The name of {row['id']}", str(row.get("name") or ""), hint="Enter save · Esc cancel")
                if name and name.strip():
                    await asyncio.to_thread(change, {"action": "rename", "id": row["id"], "name": name.strip()})
            elif key == "x":
                if await views.confirm(f"Delete the identity {row['id']}?", await asyncio.to_thread(_goes_with, host, row["id"]),
                                       yes="Yes, delete it and all of that"):
                    await asyncio.to_thread(change, {"action": "delete", "id": row["id"]})
        except Exception as error:  # noqa: BLE001
            await views.failed("That did not work", error)


def _goes_with(host, identity: str) -> str:
    """What deleting an identity takes with it: its conversations, its channel accounts and
    what it spent (each line said even when its route does not answer)."""
    def read(path):
        try:
            return host.get(f"/api/agent/{path}{'&' if '?' in path else '?'}identity={identity}")
        except Exception:  # noqa: BLE001
            return None

    chats, channels, usage = read("chats"), read("channels"), read("usage?range=month")
    lines = ["With it go:"]
    lines.append(f"  conversations   {len(chats['chats'])}: " + ", ".join(str(row.get("title")) for row in chats["chats"][:6])
                 if chats else "  conversations   (could not be read)")
    lines.append(f"  channels        {len(channels['channels'])}: " + ", ".join(str(row.get("account")) for row in channels["channels"])
                 if channels else "  channels        (could not be read)")
    lines.append(f"  spent           ${float(usage.get('cost_usd') or 0):.2f} in the last 30 days, {int((usage.get('calls') or {}).get('total') or 0)} calls"
                 if usage and "calls" in usage else "  spent           (could not be read)")
    lines.append("  and its persona, memory, skills and tree of reactions. harness agent backup keeps a copy first.")
    return "\n".join(lines)
