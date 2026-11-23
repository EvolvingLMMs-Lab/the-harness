"""What the game itself recorded of a run, not what the model said:

    harness minebot table <name>

read from the run's body-events.jsonl (everything that happened to the body, with the
world's age in game ticks) and written to its table.md: the advancements with the game time
and the real time since the body joined, the deaths with the game's reason, the commands
the body typed (and how many the game refused), the restarts of the body.
"""

import collections
import glob
import json
import re

from .run import runs_dir


def clock(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def table(name):
    run = runs_dir() / name
    setup = json.loads((run / "setup.json").read_text(encoding="utf-8"))
    path = run / "body-events.jsonl"
    events = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()] if path.exists() else []
    joined = next((event for event in events if event["kind"] == "joined"), None)
    if not joined:
        return f"# {name}\n\nThe body never joined the world.\n", {}
    player = re.escape((setup.get("settings") or {}).get("username") or "minebot")

    def when(event):
        game = (event["age"] - joined["age"]) / 20.0 if event.get("age") is not None and joined.get("age") is not None else None
        return (clock(game) if game is not None else "?"), clock((event["t"] - joined["t"]) / 1000.0)

    said = [event for event in events if event["kind"] == "chat"]
    advancements = [(re.search(r"\[(.+)\]", event["message"]).group(1), *when(event)) for event in said
                    if re.match(rf"{player} has (made the advancement|reached the goal|completed the challenge) \[", event.get("message", ""))]
    told = [(event.get("what") or "?", *when(event)) for event in events if event["kind"] == "told"]
    deaths = [(event.get("message") or "?", *when(event)) for event in events if event["kind"] == "death"]
    commands = [event["text"].split()[0] for event in events if event["kind"] == "command"]
    refused = sum(1 for event in said if re.search(r"Unknown command|do not have permission|Incorrect argument|Unknown or incomplete command", event.get("message", "")))
    restarts = [(event.get("why") or "?", *when(event)) for event in events if event["kind"] == "body_restarted"]
    rejected = 0
    for trace in glob.glob(str(run / "trace" / "**" / "events.jsonl"), recursive=True):
        rejected += open(trace, encoding="utf-8", errors="replace").read().count("rejected transaction")
    last = when(events[-1])
    lines = [f"# {name}: {setup.get('kind', 'practice')} run, {setup.get('model') or 'the default model'}", "",
             f"From the body's events, up to game time {last[0]} (real {last[1]}) after it joined.", "",
             "| advancement | game time | real time |", "|---|---|---|"]
    lines += [f"| {title} | {game} | {real} |" for title, game, real in advancements] or ["| (none) | | |"]
    lines += ["", f"Told by the game to every player: {len(told)}"] + [f"- {game} (real {real}): {what}" for what, game, real in told]
    lines += ["", f"Deaths: {len(deaths)}"] + [f"- {game} (real {real}): {reason}" for reason, game, real in deaths]
    counted = collections.Counter(commands)
    lines += ["", f"Commands typed by the body: {len(commands)}" + (f", refused by the game: {refused}" if commands else "")]
    lines += [f"- {word} x{count}" for word, count in counted.most_common()]
    lines += ["", f"Restarts of the body: {len(restarts)}"] + [f"- {game} (real {real}): {why}" for why, game, real in restarts]
    lines += ["", f"Inventory clicks the server rejected (from the run's trace): {rejected}", ""]
    facts = {"advancements": [title for title, _, _ in advancements], "told": [what for what, _, _ in told], "deaths": len(deaths),
             "commands": len(commands), "refused": refused, "restarts": len(restarts), "rejected_clicks": rejected}
    return "\n".join(lines), facts


def write(name) -> str:
    text, _ = table(name)
    (runs_dir() / name / "table.md").write_text(text, encoding="utf-8", newline="\n")
    return text
