"""/library, /skills and /memory: what an identity learned, as the app's "What it learned"
page and `harness library` show it. Three groups and the shared libraries:

    skills            each with its evidence, its uses and where it came from (a source that
                      was dropped for its age reads "expired"); Enter opens one: d its diff
                      to the version before, u undoes it, a approves a proposal, r restores
                      one that was undone or archived, x deletes it (Hermes's /skills)
    tree of reactions browsed level by level like folders (Enter into a branch, ← up): m
                      moves a node under another, x disables or enables it, u removes one
                      that is not built in (ours; the browsing is a file manager's)
    memory            what it remembers, private or of one chat; Enter reads one, x forgets
                      it (Claude Code's /memory lists the entries the same way)
    shared libraries  read only

Everything is the host's learned and tree routes."""

import asyncio
import time

from ..core import format as formats
from . import views
from .agent import EVIDENCE


def _when(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(value)))
    except (TypeError, ValueError):
        return str(value)[:16]


def origin(skill: dict) -> str:
    """Where a skill came from, in a few words."""
    source = skill.get("source") or {}
    where = " · ".join(str(part) for part in (source.get("chat") or source.get("source") or source.get("from"),
                                              _when(source.get("time"))) if part)
    return where + (" (record expired)" if source.get("expired") else "")


def listing(learned: dict, level: dict) -> tuple[list, list, list]:
    """(rows, headers, items) of the library's first view."""
    rows, headers, items = [], [], []

    def group(name):
        headers.append(len(rows))
        rows.append(name)
        items.append(("group", name))

    group("skills")
    for skill in learned.get("skills") or ():
        state = "archived" if skill.get("archived") else EVIDENCE.get(skill.get("evidence"), skill.get("evidence") or "")
        rows.append(f"{skill['name'][:34]:<34} {state:<15} {str(skill.get('uses') or 0) + ' uses':<9} {origin(skill)}")
        items.append(("skill", skill))
    if not learned.get("skills"):
        headers.append(len(rows))
        rows.append("  none yet: what it learns to do becomes a skill, and a skill source (/mcp) brings others")
        items.append(("group", "skills"))
    group("tree of reactions")
    total = sum(1 + (node.get("children") or 0) for node in level.get("nodes") or ())
    rows.append(f"▸ root{'':<28} {total} nodes")
    items.append(("tree",))
    group("memory")
    entries = sorted((learned.get("memory") or {}).items(), key=lambda pair: str(pair[1].get("updated") or ""))
    for key, entry in entries:
        text = (entry.get("text") or key).strip()
        scope = "this chat" if entry.get("scope") == "chat" else "private"
        where = " · ".join(part for part in (str(entry.get("chat") or entry.get("source") or ""), _when(entry.get("updated"))) if part)
        rows.append(f"{(text.splitlines()[0] if text else key)[:34]:<34} {scope:<15} {where}")
        items.append(("memory", key, entry))
    if not entries:
        headers.append(len(rows))
        rows.append("  nothing yet: tell it \"remember …\"")
        items.append(("group", "memory"))
    group("shared libraries (read only)")
    rows.append("▸ libraries and this conversation's memory")
    items.append(("libraries",))
    return rows, headers, items


async def library_view(client, note, libraries=None, group=None) -> None:
    """`group` ("skills", "memory"): the group it opens on (/skills, /memory)."""
    at = None
    while True:
        try:
            learned = await asyncio.to_thread(client.get, "learned")
            level = await asyncio.to_thread(client.get, "tree", path="")
        except Exception as error:  # noqa: BLE001
            await views.failed("The library could not be read", error)
            return
        rows, headers, items = listing(learned, level)
        if at is None:
            start = next((index for index, item in enumerate(items) if item == ("group", group)), -1)
            at = next((index for index in range(start + 1, len(rows)) if index not in headers), 0)
        picked = await views.browse(f"Library · {client.identity}", rows, headers=headers, keys=["u", "x", "d"], current=at,
                                    hint="↑ ↓ move · Enter open · u undo a skill · x delete or forget · esc back")
        if picked is None:
            return
        key, index = picked
        at = index or 0
        item = items[index] if index is not None else None
        if item is None:
            continue
        try:
            if item[0] == "tree":
                await tree_view(client)
            elif item[0] == "libraries" and libraries is not None:
                await libraries()
            elif item[0] == "skill":
                await skill_view(client, item[1], note, key)
            elif item[0] == "memory" and key in ("x", "d"):
                if await views.confirm(f"Forget {item[1]}?", str(item[2].get("text") or ""), yes="Yes, forget it"):
                    await asyncio.to_thread(client.post, "learned", {"action": "forget", "name": item[1]})
            elif item[0] == "memory":
                entry = item[2]
                await views.read(item[1], "\n".join([entry.get("text") or "", "",
                                                     f"scope   {'this chat' if entry.get('scope') == 'chat' else 'private'}",
                                                     f"source  {entry.get('source') or ''} {entry.get('chat') or ''}",
                                                     "private: your own places only · this chat: where it was written"]))
        except Exception as error:  # noqa: BLE001 - said; the library opens again
            await views.failed("That did not work", error)


async def skill_view(client, skill, note, key="enter") -> None:
    """A skill: where it came from, its evidence and uses, and what can be done with it."""
    name = skill["name"]
    level = skill.get("evidence")
    about = "\n".join([f"source    {origin(skill) or '—'}",
                       f"evidence  {EVIDENCE.get(level, level)}"
                       + (f" (history: {' → '.join(map(str, skill['history']))})" if skill.get("history") else ""),
                       f"uses      {skill.get('uses') or 0}" + (f" · success {skill['success_rate']:.0%}"
                                                               if isinstance(skill.get("success_rate"), (int, float)) else ""),
                       "", str(skill.get("description") or "")])
    actions = [("diff", "See what changed from the version before"),
               *([("approve", "Approve it (it is a proposal)")] if level == "proposed" else []),
               *([("restore", "Restore it")] if level in ("undone", "archived") or skill.get("archived") else
                 [("undo", "Undo it: no longer loaded, kept in its history")]),
               ("delete", "Delete it")]
    if key == "u":
        action = "undo"
    elif key == "x":
        action = "delete"
    elif key == "d":
        action = "diff"
    else:
        picked = await views.choose(name, [label for _, label in actions], text=about, hint="↑↓ move · Enter do it · Esc back")
        if picked is None:
            return
        action = actions[picked][0]
    if action == "delete" and not await views.confirm(f"Delete the skill {name}?", "Its folder and its history go.",
                                                      yes="Yes, delete it"):
        return
    answer = await asyncio.to_thread(client.post, "learned", {"action": action, "name": name})
    if action == "diff":
        result = answer.get("result")
        text = result if isinstance(result, str) else (result or {}).get("diff") or (result or {}).get("text") or ""
        await views.read(f"{name}: what changed", str(text) or "There is no version before this one to compare with.")
    else:
        note({"undo": f"undone {name}: no longer loaded; the revision stays in its history",
              "approve": f"approved {name}", "restore": f"restored {name}", "delete": f"deleted the skill {name}"}[action])


def tree_rows(level):
    rows = []
    for number, node in enumerate(level.get("nodes") or (), 1):
        lit = "•" if node.get("lit") else " "
        label = node.get("about") or node["name"]
        if node.get("children"):
            rows.append(f"{lit}{number:>2}. ▸ {label[:56]:<56} {node['children']} nodes")
        else:
            off = " (disabled)" if not node.get("enabled", True) else ""
            rows.append(f"{lit}{number:>2}.   {label[:56]:<56} "
                        f"{EVIDENCE.get(node.get('evidence') or node.get('source'), node.get('evidence') or '')}{off}")
    return rows


async def tree_view(client) -> None:
    """The tree of reactions like a file manager: one level in order, the path on top; Enter
    opens a node with nodes under it, ← goes up; x disables or enables, m moves under another
    branch, u removes a node the owner added or it learned (the built-in ones can only be
    disabled)."""
    path, labels, at = [], [], 0
    while True:
        level = await asyncio.to_thread(client.get, "tree", path="/".join(path))
        nodes = level.get("nodes") or []
        picked = await views.browse("Library", tree_rows(level), top="› tree › " + " › ".join(["root", *labels]),
                                    current=at, keys=["x", "m", "u"], back=True, empty="No reactions on this level.",
                                    hint="↑ ↓ move · Enter open · ← up · m move under another branch · u remove · "
                                         "x disable or enable · esc back")
        if picked is None:
            return
        key, index = picked
        node = nodes[index] if index is not None and index < len(nodes) else None
        at = index or 0
        try:
            if key == "left":
                if not path:
                    return
                path.pop()
                labels.pop()
                at = 0
            elif node is None:
                continue
            elif key == "enter" and node.get("children"):
                path.append(node["name"])
                labels.append(node.get("about") or node["name"])
                at = 0
            elif key == "enter":
                await views.read(node.get("about") or node["name"], "\n".join(
                    f"{name:<9} {value}" for name, value in (
                        ("name", node["name"]), ("when", node.get("when")), ("do", node.get("do")),
                        ("source", node.get("source")), ("evidence", EVIDENCE.get(node.get("evidence"), node.get("evidence"))),
                        ("uses", f"{node.get('uses') or 0} · {node.get('done') or 0} done"),
                        ("enabled", "yes" if node.get("enabled", True) else "no"),
                        ("last", formats.timestamp(node["last"]) if node.get("last") else "never"))))
            elif key == "x":
                await asyncio.to_thread(client.post, "tree", {"action": "disable" if node.get("enabled", True) else "enable",
                                                              "name": node["name"]})
            elif key == "u":
                if node.get("source") == "builtin":
                    await views.read("Not removed", "A built-in reaction can only be disabled (x).")
                elif await views.confirm(f"Remove the reaction {node.get('about') or node['name']}?", yes="Yes, remove it"):
                    await asyncio.to_thread(client.post, "tree", {"action": "remove", "name": node["name"]})
            elif key == "m":
                under = await views.ask(f"Move {node['name']} under which node (its name; empty: the root)",
                                        hint="Enter move · Esc cancel")
                if under is not None:
                    await asyncio.to_thread(client.post, "tree", {"action": "move", "name": node["name"],
                                                                  "under": under.strip() or None})
        except Exception as error:  # noqa: BLE001
            await views.failed("The tree was not changed", error)
