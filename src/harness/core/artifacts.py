"""Run evidence: immutable payloads and a small append-only index, independent of cell replies."""

import hashlib
import json
from pathlib import Path
import threading
import time


class Evidence:
    """Bounded disk evidence. Repeated payloads share bytes, never mutable target paths.

    A record's reference can be resolved after the controller exits. Exhaustion is an
    explicit error; callers must not retry an action whose result could not be recorded.
    """

    def __init__(self, directory, limit=256 * 1024 * 1024):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self.lock = threading.RLock()
        self.used = sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file())

    def reserve(self, size):
        with self.lock:
            if self.used + size > self.limit:
                raise OSError("run evidence limit reached; execution must stop")
            self.used += size

    def record(self, kind, payload, **identity):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        filename = digest + ".json"
        row = (json.dumps({"kind": kind, "time": time.time(), **identity,
                           "payload": filename}, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock:
            path = self.directory / filename
            needed = len(row) + (0 if path.exists() else len(raw))
            self.reserve(needed)
            if not path.exists():
                path.write_bytes(raw)
            with (self.directory / "index.jsonl").open("ab") as stream:
                offset = stream.tell()
                stream.write(row)
                stream.flush()
        return {"path": str(path), "sha256": digest, "index_offset": offset}
