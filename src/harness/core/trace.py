from datetime import datetime
from functools import cache
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import threading
from time import time

from . import atomic_write, sha256


def write_json(path: Path, data) -> None:
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def git_revision(root) -> dict:
    """The commit of the checkout `root` and whether its tree was dirty: {"commit", "dirty"},
    each None where git cannot say (no git, not a checkout)."""
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, encoding="utf-8",
                                errors="replace")
        return result.stdout.strip() if result.returncode == 0 else None
    try:
        commit, status = git("rev-parse", "HEAD"), git("status", "--porcelain")
    except OSError:
        commit, status = None, None
    return {"commit": commit, "dirty": bool(status) if status is not None else None}


def now() -> str:
    """The local time, to the second, as ISO 8601 with its offset (a result's started_at)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp() -> str:
    """The local time as a file name part, to the millisecond (20261103_142501_123)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


@cache
def provenance() -> dict:
    """The Python, git commit and the hash of each of the harness's files, once per process
    (the code that runs is the code imported)."""
    package = Path(__file__).resolve().parents[1]
    files = {str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(package.rglob("*.py"))}
    revision = git_revision(package)
    return {"python": platform.python_version(), "git_commit": revision["commit"], "git_dirty": revision["dirty"],
            "package_sha256": sha256(files), "package_files": files}


# Who a trace record comes from (its `source`).
SOURCES = ("user", "agent", "program", "environment", "harness")


class Trace:
    """The append-only record of one episode (events.jsonl): every record has its number
    `seq` (its id), the wall-clock `time` and its kind `event`. With `kinds` ({kind:
    {"source", ...}}, runtime/conversation.py EVENTS) a record also says its `source`, and
    a kind not in the table is refused. Subscribers get each record as it is written;
    records may come from several threads. `context`, when set, gives what goes into every
    record (whose trace it is: a conversation of a session, runtime/conversation.py)."""

    def __init__(self, directory: Path, kinds: dict | None = None, *, append: bool = False):
        path = directory / "events.jsonl"
        if append:
            from .episodes import read_records

            if not path.is_file():
                raise ValueError("the existing session trace is missing")
            sequence = max((record["seq"] for record in read_records(directory)), default=-1) + 1
        else:
            directory.mkdir(parents=True, exist_ok=False)
            path.touch()
            sequence = 0
        self.directory = directory
        self.sequence = sequence
        self.kinds = kinds
        self.subscribers = []
        self.context = None
        self._lock = threading.Lock()

    def subscribe(self, callback) -> None:
        """Call `callback(record)` with every record written from now on."""
        self.subscribers.append(callback)

    def emit(self, event: str, **data):
        if self.kinds is not None:
            if event not in self.kinds:
                raise ValueError(f"Unknown trace event {event!r}")
            # A record may name another source than its kind's (a program's finish()), never
            # something that is no source.
            if data.get("source", self.kinds[event]["source"]) not in SOURCES:
                raise ValueError(f"A record's source is one of {list(SOURCES)}, not {data['source']!r}")
            data = {"source": self.kinds[event]["source"], **data}
        with self._lock:
            record = {"seq": self.sequence, "time": time(), "event": event,
                      **(self.context() if self.context is not None else {}), **data}
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
            self.sequence += 1
            for callback in list(self.subscribers):
                try:
                    callback(record)
                except Exception:
                    # A viewer that fails never stops the episode.
                    pass
        return record


def _text_of(content):
    if isinstance(content, str):
        return [content]
    return [part.get("text", "") for part in content or [] if part.get("type") in ("text", "input_text")]


def context_summary(messages, system=None):
    """What one model call received in full, one short row per message: role, opening
    text, size, images still attached and images replaced by an omission note. The
    trace keeps each message's content once (where it was first sent); this records
    how the whole history looked at each call, after windowing and image pruning."""
    rows = [{"role": "system", "text": system[:160], "chars": len(system), "images": 0, "omitted": 0}] if system else []
    for message in messages:
        content = message.get("content")
        texts = _text_of(content)
        parts = [] if isinstance(content, str) else list(content or [])
        calls = [f"{(c.get('function') or {}).get('name')}(...)" for c in message.get("tool_calls") or []]
        joined = " ".join(t for t in texts if t) or " ".join(calls)
        rows.append({
            "role": message.get("role"),
            "text": " ".join(joined.split())[:160],
            "chars": sum(len(t) for t in texts),
            "images": sum(part.get("type") in ("input_image", "image_url") for part in parts),
            "omitted": sum("image omitted" in t for t in texts),
        })
    return rows
