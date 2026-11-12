"""The episodes under a runs directory, as the GUI lists and reads them.

An episode is a directory with an events.jsonl (runtime/conversation.py); its
manifest.json and summary.json say what ran and how it ended. An episode without a
summary, or whose summary is `open` (a conversation between two turns), is still being
written (or was cut off).
"""

import json
import os
from pathlib import Path
import secrets
import time


# Files of an episode the GUI may serve, by extension.
MEDIA_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".json": "application/json", ".log": "text/plain; charset=utf-8",
               ".txt": "text/plain; charset=utf-8"}


def new_name(suffix: str = "") -> str:
    """A new run's directory name: "20261102-140530-3fa9c1", then "-<suffix>" when given."""
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}" + (f"-{suffix}" if suffix else "")


# How an episode ended (finished, closed, budget, step_limit, interrupted, error), and its words, where not the same.
ENDINGS = {"success": "finished", "budget_exhausted": "budget", "cost_exhausted": "budget",
           "wall_time_exhausted": "budget", "episode_ended": "step_limit"}
ENDING_WORDS = {"closed": "closed by the user", "budget": "out of budget", "step_limit": "step limit"}


def summary(directory) -> dict:
    """An episode's summary.json, {} when it has none or it cannot be read."""
    value = _read_json(Path(directory) / "summary.json")
    return value if isinstance(value, dict) else {}


def usage(source) -> dict | None:
    """{model_calls, cost_usd} of a summary or of a directory's (None when it has none)."""
    found = source if isinstance(source, dict) else summary(source) or None
    return None if found is None else {"model_calls": int(found.get("model_calls") or 0),
                                       "cost_usd": round(float(found.get("cost_usd") or 0), 6)}


def ending(found: dict | None) -> str | None:
    """How an episode ended (its summary's status, as ENDINGS names it); None without one."""
    status = (found or {}).get("status")
    return ENDINGS.get(str(status), str(status)) if status else None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def episode_dir(root: Path, run: str) -> Path:
    """The episode directory `run` (a path relative to `root`); ValueError when it leaves
    the root or has no trace."""
    directory = (root / run).resolve()
    if directory != root and root not in directory.parents:
        raise ValueError("run outside the runs directory")
    if not (directory / "events.jsonl").is_file():
        raise ValueError(f"no episode at {run}")
    return directory


def describe(root: Path, directory: Path) -> dict:
    """One episode as the list shows it: where it is, its task, seed, status and ending,
    when its trace last changed, and whether it is still being written."""
    done = summary(directory)
    manifest = _read_json(directory / "manifest.json") or {}
    config = manifest.get("config") or {}
    trace = directory / "events.jsonl"
    return {
        "run": directory.relative_to(root).as_posix(),
        "group": directory.parent.relative_to(root).as_posix() if directory.parent != root else "",
        "task": done.get("task") or config.get("task"),
        "seed": done.get("seed", manifest.get("seed")),
        "status": done.get("status"),
        "ending": ending(done),
        "success": done.get("success"),
        "model": (config.get("main") or {}).get("model"),
        "interactive": "interactive" in manifest,
        "modified": trace.stat().st_mtime,
        "live": not done or bool(done.get("open")),
    }


def list_episodes(root: Path, limit: int = 500) -> list[dict]:
    """The episodes under `root`, the most recently changed first (at most `limit`)."""
    found = []
    for current, directories, files in os.walk(root):
        if "events.jsonl" in files:
            found.append(Path(current))
            directories[:] = []
            continue
        directories[:] = sorted(name for name in directories if not name.startswith("."))
    found.sort(key=lambda path: (path / "events.jsonl").stat().st_mtime, reverse=True)
    return [describe(root, path) for path in found[:limit]]


def read_records(directory: Path, after: int = -1) -> list[dict]:
    """The trace records of an episode with `seq` above `after` (a line still being
    written is left for later)."""
    records = []
    with (directory / "events.jsonl").open("rb") as handle:
        for line in handle:
            if not line.endswith(b"\n"):
                break
            record = json.loads(line)
            if record.get("seq", -1) > after:
                records.append(record)
    return records


class Follow:
    """New records of a trace as they are written: next() returns the records added since
    the previous call (complete lines only)."""

    def __init__(self, directory: Path, after: int = -1):
        self.path = directory / "events.jsonl"
        self.after = after
        self.offset = 0
        self.partial = b""

    def next(self) -> list[dict]:
        records = []
        if not self.path.is_file():
            # A conversation that has not written its first record yet.
            return records
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            data = handle.read()
        self.offset += len(data)
        lines = (self.partial + data).split(b"\n")
        self.partial = lines.pop()
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("seq", -1) > self.after:
                self.after = record["seq"]
                records.append(record)
        return records

    def ended(self) -> bool:
        """Whether the episode has its last summary (nothing more will be written)."""
        return bool(summary(self.path.parent)) and not summary(self.path.parent).get("open")
