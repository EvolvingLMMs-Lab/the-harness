"""What a package declares of the space its worker kind becomes behind the translation layer.

A package that gives a worker kind may say, in `spaces/<name>.toml` with `kind = "<kind>"`,
what the translation layer would otherwise derive from the worker's profile:

    kind = "workspace"
    worker = "project-workspace"    # optional: the worker, where several drive one kind
    line = "A project folder: its files and the commands run in it"

    [capabilities]                  # merged over what is derived (participants, pace, ...)
    participants = { outside = true }

    [verbs.tick]                    # a method of the worker: how its verb is declared
    line = "One operation in the folder"
    episode = true                  # whether the call takes the episode (filled in; default true)
    effect = "change"               # read, change, send, spend, irreversible
    stale = "refuse"                # what an action based on an old observation gets
    default = { end = "refused", reason = { code = "unsupported" } }

    [verbs.run]                     # a verb made of a tick: its command is `tick` and the args
    tick = { type = "run" }
    params = { type = "object", properties = { command = { type = "string" } }, required = ["command"] }
    effect = "change"
    follow = { id = "process_id", poll = "process", until = "ready", cancel = "cancel", status = "status" }
    ends = { exited = "done", cancelled = "cancelled", timeout = { end = "failed", code = "deadline" } }

    [sending]                       # command lines that send (pushing, publishing): each
    commands = ["git push*"]        # waits for the owner's approval as a sensitive step

    [pages.workspace]               # pages of the vocabulary, read when needed
    text = "..."

    [inspector]                     # the probes `agent-space check` acts with
    done = { verb = "workspace.read", args = { path = "." } }

A verb made of a tick whose result names something that goes on (`follow`) lasts until it
ends: its outcome is the status it ends with, as `ends` maps it (a status not named there is
unknown); cancelling it asks the worker to stop it (`cancel`).
"""

import tomllib
from pathlib import Path


def _read(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def declared(kind: str, worker: str | None = None) -> dict:
    """The declaration of the space `kind` becomes, from the enabled packages ({} without):
    the one that names the worker (`worker`, the name its describe gives) when several
    workers drive one kind, else the one that names only the kind."""
    try:
        from harness.packages import enabled

        packages = enabled()
    except Exception:  # no package store here: nothing is declared
        return {}
    found = []
    for package in packages:
        for name in package.provides.get("spaces", ()):
            path = Path(package.path) / "spaces" / f"{name}.toml"
            try:
                data = _read(path)
            except (OSError, ValueError):
                continue
            if data.get("kind") == kind and data.get("worker") in (None, worker):
                found.append(data)
    return next((d for d in found if d.get("worker") == worker), found[0] if found else {})
