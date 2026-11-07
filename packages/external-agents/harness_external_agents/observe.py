"""Read a user-selected native session export without acquiring control of it."""

import json
from pathlib import Path
import threading

from .session import Session


MAX_LINE = 4 * 1024 * 1024


def records(path, stop=None):
    with path.open("rb") as handle:
        while True:
            start = handle.tell()
            line = handle.readline(MAX_LINE + 1)
            if len(line) > MAX_LINE:
                raise ValueError("the selected transcript contains an oversized line")
            if line.endswith(b"\n") or line and stop is None:
                try:
                    item = json.loads(line)
                except (UnicodeError, ValueError):
                    continue
                if isinstance(item, dict):
                    yield item
            elif stop is None or stop.wait(0.5):
                return
            else:
                handle.seek(start)


def identity(path, provider):
    for number, item in enumerate(records(path)):
        if number >= 1000:
            break
        if provider == "codex" and item.get("type") == "session_meta":
            source = item.get("payload") or {}
            if source.get("id") and source.get("cwd"):
                return str(source["id"]), str(source["cwd"])
        elif provider == "claude-code" and item.get("sessionId") and item.get("cwd"):
            return str(item["sessionId"]), str(item["cwd"])
    raise ValueError("the selected transcript does not identify the native session and directory")


def message(item, provider):
    if provider == "codex":
        if item.get("type") != "response_item":
            return None
        body = item.get("payload") or {}
        if body.get("type") != "message":
            return None
        role = body.get("role")
        kinds = ("input_text", "output_text")
    else:
        role = item.get("type")
        body = item.get("message") or {}
        kinds = ("text",)
    if role not in ("user", "assistant"):
        return None
    content = body.get("content")
    text = content if isinstance(content, str) else "\n".join(
        str(part.get("text") or "") for part in (content or []) if isinstance(part, dict) and part.get("type") in kinds)
    if text.strip():
        return ("user_message" if role == "user" else "agent_message"), text
    return None


class ObservedSession(Session):
    def __init__(self, directory, path, provider, follow, external_id, cwd, *, adapter=None):
        super().__init__(directory, adapter or "observed:" + provider, Path(cwd))
        self.path, self.provider, self.follow = path, provider, follow
        self.stop = threading.Event()
        self.session_metadata.update(source="terminal" if path else "acp_discovery", owner="external",
                                     external_id=external_id, observed=True)

    def open(self, text, files):
        with self.lock:
            if self.ended:
                return
            if self.path is None:
                self.end("FINISHED")
                return
            self.state("RUNNING", "observing the external transcript")
        seen = set()
        for item in records(self.path, self.stop if self.follow else None):
            with self.lock:
                if self.ended:
                    return
                identifier = item.get("uuid")
                if isinstance(identifier, str):
                    if identifier in seen:
                        continue
                    seen.add(identifier)
                found = message(item, self.provider)
                if found:
                    self.trace.emit(found[0], text=found[1], replay=True)
        with self.lock:
            self.end("FINISHED")

    def send_message(self, text, files=()):
        raise ValueError("an imported transcript is read-only")

    def cancel(self):
        raise ValueError("the original terminal controls this session")

    def set_model(self, model=None, reasoning_effort=None):
        raise ValueError("the original terminal controls this session")

    def close_transport(self):
        self.stop.set()
