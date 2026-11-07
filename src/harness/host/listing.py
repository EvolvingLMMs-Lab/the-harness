"""The shared conversation list for the app and taptab."""

import json
from pathlib import Path

from ..core import episodes as runs
from . import sessions


def conversations(server) -> list[dict]:
    """The app's conversations, and the other sessions the server runs: each with its session's
    id, what started it (`frontend`), what it waits for, what it spent (`usage`) and its agents;
    the app's own with their meta.json (title, pin)."""
    app, listed = server.app, {row["run"]: row for row in server.conversations.sessions()}
    index = server.conversations.index
    history = {row["run"]: row for row in sessions.history(index)} if index else {}
    rows = []
    for episode in runs.list_episodes(app.conversations_dir, limit=500):
        directory = app.conversations_dir / episode["run"]
        try:
            meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        run = directory.relative_to(server.root).as_posix()
        conversation, session = server.conversations.get(run), listed.get(run)
        identity = session or history.get(run) or {}
        status = (conversation.status if conversation else
                  sessions.ended_status(directory) if not episode["live"] else None)
        rows.append({"run": run, "title": meta.get("title") or episode["run"], "text": meta.get("text"),
                     "created": meta.get("created"), "pinned": bool(meta.get("pinned")),
                     "model": meta.get("model"), "model_entry": meta.get("model_entry"), "reasoning_effort": meta.get("reasoning_effort"),
                     "profile": meta.get("profile"), "modified": episode["modified"],
                     "status": status, "controllable": (conversation is not None and sessions.live(status)
                                                        and not identity.get("metadata", {}).get("observed")),
                     "starting": app.starting.get(run), "frontend": identity.get("frontend", "app"),
                     "workspace": _workspace(app, run, meta), "session": identity.get("id"),
                     "kind": identity.get("kind", "harness"), "project": identity.get("project"),
                     "metadata": identity.get("metadata", {}), "capabilities": identity.get("capabilities"),
                     "waiting": session["waiting"] if session else None,
                     "usage": session["usage"] if session else None,
                     "agents": session["agents"] if session else []})
    mine = app.conversations_dir.resolve()
    for session in listed.values():
        directory = Path(session["directory"]) if session["directory"] else None
        if directory is None or directory == mine or mine in directory.parents:
            continue
        trace = directory / "events.jsonl"
        status = next((agent["status"] for agent in session["agents"] if agent["depth"] == 0), None)
        rows.append({"run": session["run"], "title": session["title"] or session["id"], "text": None,
                     "created": session["created"], "pinned": False, "model": None, "reasoning_effort": None,
                     "profile": None, "modified": trace.stat().st_mtime if trace.is_file() else session["created"],
                     "status": status, "controllable": status is not None and sessions.live(status),
                     "starting": None, "frontend": session["frontend"], "workspace": None, "session": session["id"],
                     "kind": session["kind"], "project": session["project"],
                     "metadata": session["metadata"], "capabilities": session["capabilities"],
                     "waiting": session["waiting"], "usage": session["usage"], "agents": session["agents"]})
    # Pinned ones first; each group newest first.
    return sorted(rows, key=lambda row: (not row["pinned"], -(row["modified"] or 0)))


def _workspace(app, run, meta) -> dict | None:
    """A conversation's workspace: its kind, and the worker serving it while one does."""
    kind = app._kinds.get(run) or meta.get("workspace")
    if kind is None:
        return None
    workspaces = app.available_workspaces()
    worker = workspaces.of(run) if workspaces is not None else None
    return {"kind": kind, **({"id": worker.id, "status": worker.status} if worker is not None else {})}
