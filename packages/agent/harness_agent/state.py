"""Agent-owned state. Run evidence and executable learning libraries remain separate."""
import json
from pathlib import Path
import re
import time
import uuid
import tomllib
from harness.sdk import atomic_write, sha256
from harness.sdk import file_lock
from harness.sdk import home, data


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("identity/session IDs use 1-64 letters, digits, underscores or hyphens")
    return value


def read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n", private=True)


class Identity:
    def __init__(self, name="default", *, root=None):
        self.id = identifier(name)
        self.directory = Path(root or home() / "agents") / self.id
        self.directory.mkdir(parents=True, exist_ok=True)
        with file_lock(self.directory / ".identity.lock"):
            path = self.directory / "identity.json"
            if not path.exists():
                instructions = ""
                legacy = data() / "config.toml"
                if self.id == "default" and root is None and legacy.exists():
                    personal = tomllib.loads(legacy.read_text(encoding="utf-8")).get("personal", {})
                    instructions = "\n".join(str(personal.get(k) or "") for k in ("about", "instructions")).strip()
                save(path, {"schema": 1, "id": self.id, "created": time.time(), "instructions": instructions})
            self.config = read(path, {})
            if self.config.get("schema") != 1 or self.config.get("id") != self.id:
                raise ValueError("identity schema or ID mismatch")
        self.library = self.directory / "library"
        self.library.mkdir(exist_ok=True)

    def memory(self):
        return read(self.directory / "memory.json", {"schema": 1, "revision": 0, "entries": {}})

    def remember(self, key, text, *, source, expected):
        if not isinstance(key, str) or not key.strip() or len(key) > 160:
            raise ValueError("memory key must be 1-160 characters")
        if text is not None and (not isinstance(text, str) or len(text) > 8000):
            raise ValueError("one memory entry is at most 8000 characters")
        with file_lock(self.directory / ".memory.lock"):
            state = self.memory()
            if state["revision"] != expected:
                raise ValueError("memory changed; read the current revision before updating")
            if text is None:
                state["entries"].pop(key, None)
            else:
                state["entries"][key] = {"text": text, "source": source, "updated": time.time()}
            if len(json.dumps(state["entries"], ensure_ascii=False)) > 64000:
                raise ValueError("memory capacity reached; consolidate or forget an entry")
            state["revision"] += 1
            save(self.directory / "memory.json", state)
            return state

    def session(self, session=None):
        key = identifier(session or uuid.uuid4().hex)
        directory = self.directory / "sessions" / key
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def history(self, query, limit=8):
        query = str(query).casefold()
        found = []
        for path in sorted((self.directory / "sessions").glob("*/events.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("event") in ("user", "reply") and query in str(row.get("text", "")).casefold():
                    found.append({"session": path.parent.name, "text": row["text"], "time": row["time"]})
        return found[-min(int(limit), 20):]
