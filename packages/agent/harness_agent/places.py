"""The places an identity is connected to: its environments, each a chat of its own.

places.json in the identity folder lists them:

    {"id": "room", "kind": "space", "title": "The shared room", "address": "ws://..."}
    {"id": "chat-2", "kind": "space", "title": "Example chat", "channel": "chat",
     "serve": ["chat", "--config", "channels/chat-2.json"], "values": {"dm": "pairing"},
     "secrets": {"CHAT_TOKEN": "HARNESS_CHANNEL_CHAT_2_TOKEN"}}
    {"id": "project", "kind": "folder", "title": "project · the-harness", "folder": "/path",
     "check": "python -m pytest -q"}
    {"id": "browser", "kind": "browser", "title": "browser"}
    {"id": "desktop", "kind": "desktop", "title": "desktop"}

A space is entered through the Agent Space Protocol at its address (a space a package
serves, `serve`, is started by the life and entered at the address it prints); what it
pushes reaches the life as events. A chat channel's account is such a space (`channel`: its
kind, channels.py): `values` are its settings, and `secrets` names the credentials it is
given in its environment ({variable: the name it is kept under}), never kept here. A folder is watched: a change of its files is an event,
and the check it declares (its CI, run on a change) ends with an outcome like any action,
done or failed. Work in a folder, a browser or on the desktop goes through the task engine
(Host.task) with that environment. The desktop has one body: one chat uses it at a time.

Every place has `proactive` (spaces.<id>.proactive): off, learn or do; by default do for
folders and browsers, learn for the desktop, off for chat spaces."""
import fnmatch
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .state import identifier, read, save

KINDS = ("space", "folder", "browser", "desktop")
# Environments with one body: one chat at a time.
SINGLE_BODY = ("desktop",)
PROACTIVE = ("off", "learn", "do")
DEFAULT_PROACTIVE = {"folder": "do", "browser": "do", "desktop": "learn", "space": "off"}
# A folder's files are looked at this often; a change is told once nothing changed for QUIET.
LOOK_SECONDS, QUIET_SECONDS = 3.0, 2.0
IGNORED = (".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", ".harness")


def load(identity) -> list:
    return [dict(row) for row in read(identity.directory / "places.json", [])]


def store(identity, rows) -> None:
    save(identity.directory / "places.json", rows)


def add(identity, kind, *, id=None, title=None, **fields) -> dict:
    """Connect a place (harness agent connect, Settings › Computer and Connectors)."""
    if kind not in KINDS:
        raise ValueError(f"a place is one of {', '.join(KINDS)}")
    rows = load(identity)
    place = identifier(id or kind)
    if any(row["id"] == place for row in rows):
        raise ValueError(f"place {place!r} is connected already")
    if kind == "folder":
        folder = Path(fields.get("folder") or "").expanduser()
        if not folder.is_dir():
            raise ValueError("a folder place needs an existing folder")
        fields["folder"] = str(folder.resolve())
    if kind == "space" and not (fields.get("address") or fields.get("serve")):
        raise ValueError("a space place needs its address (or what serves it)")
    row = {"id": place, "kind": kind, "title": title or (f"{kind} · {Path(fields['folder']).name}" if kind == "folder"
                                                        else place), **fields}
    rows.append(row)
    store(identity, rows)
    return row


def remove(identity, place) -> None:
    store(identity, [row for row in load(identity) if row["id"] != place])


def proactive(identity, place: dict) -> str:
    """spaces.<id>.proactive for this identity: off, learn or do."""
    own = (identity.settings_section("spaces").get(place["id"]) or {}) if hasattr(identity, "settings_section") else {}
    value = place.get("proactive") or own.get("proactive")
    if value in PROACTIVE:
        return value
    if place.get("kind") == "space" and place.get("goal"):
        return "do"  # a group the owner gave it a goal in
    return DEFAULT_PROACTIVE.get(place.get("kind"), "off")


class Place:
    """A connected place: tells the life what happens there (`tell(place, entry)`)."""

    single_body = False

    def __init__(self, row, tell):
        self.row, self.id, self.kind, self.tell = row, row["id"], row["kind"], tell
        self.online = False

    def start(self) -> None:
        self.online = True

    def close(self) -> None:
        self.online = False

    def describe(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.row.get("title"), "online": self.online,
                "single_body": self.single_body}


class SpacePlace(Place):
    """A space entered at its address; started first when a package serves it."""

    def __init__(self, row, tell, *, key=None, folder=None):
        super().__init__(row, tell)
        self.key, self.folder = key, folder
        self.environment = None
        self.child = None
        self._closing = False

    def _serve(self) -> str:
        args = [sys.executable, "-m", "harness.space.serve", *self.row["serve"]]
        if self.key is not None and "--owner" not in args:
            # The identity this account belongs to may take the owner role there.
            args += ["--owner", self.key.identity]
        from harness.paths import python_path

        log = Path(self.folder or ".") / "logs" / f"place-{self.id}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        secrets = {}
        if self.row.get("secrets"):
            from harness.sdk import Credentials, data

            kept = Credentials(data())
            secrets = {name: kept.secret(key) for name, key in self.row["secrets"].items() if kept.secret(key)}
        self.child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log.open("ab"), cwd=self.folder,
                                      env={**os.environ, **secrets,
                                           "PYTHONPATH": python_path(os.environ.get("PYTHONPATH"))},
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = self.child.stdout.readline()
        if not line:
            raise RuntimeError(f"the space of {self.id} did not start (exit {self.child.poll()})")
        return json.loads(line)["space"]

    def start(self) -> None:
        threading.Thread(target=self._enter, name=f"place-{self.id}", daemon=True).start()

    def _enter(self) -> None:
        from harness.space.environment import SpaceEnvironment

        told, wait = None, 10
        while not self._closing:
            try:
                address = self.row.get("address") or self._serve()
                role = "owner" if self.row.get("serve") and self.key is not None else None
                self.environment = SpaceEnvironment.connect(address, key=self.key, timeout=60, role=role)
                self.presence = self.environment.presence
                self.environment.listen(lambda entry: self.tell(self.id, entry))
                self.environment.on_outcome(lambda outcome, verb: self.tell(self.id, {
                    "type": "asp.outcome", "verb": verb, "end": getattr(outcome.end, "value", outcome.end),
                    "reason": getattr(outcome.reason, "code", None) if outcome.reason else None,
                    "source": f"presence/{self.presence}"}))
                self.online = True
                self.tell(self.id, {"type": "place.online", "data": {"online": True}, "source": "place"})
                return
            except Exception as error:  # an environment that is not there yet: tried again, less often
                self.online = False
                reason = f"{type(error).__name__}: {error}"
                if reason != told:   # told once, not every try
                    told = reason
                    self.tell(self.id, {"type": "place.offline", "data": {"reason": reason}, "source": "place"})
                if self.child is not None and self.child.poll() is None:
                    self.child.terminate()
                time.sleep(wait)
                wait = min(wait * 2, 300)

    def vocabulary(self) -> dict:
        return self.environment.vocabulary() if self.environment is not None else {}

    def act(self, verb, args=None, object=None):
        """One action in the space: its outcome {end, result, reason}."""
        if self.environment is None:
            return {"end": "refused", "reason": "the place is not connected"}
        outcome = self.environment.participant.act(verb, object, args or {}, id=self.environment.next_id(),
                                                   timeout=90)
        end = getattr(outcome.end, "value", outcome.end)
        reason = outcome.reason
        return {"end": end, "result": outcome.result,
                "reason": (getattr(reason, "code", None) or str(reason)) if reason else None}

    def close(self) -> None:
        self._closing = True
        if self.environment is not None:
            self.environment.close()
        if self.child is not None and self.child.poll() is None:
            self.child.terminate()
        super().close()


class FolderPlace(Place):
    """A project folder: its changes are events; its declared check, run after a change,
    ends with an outcome (done when it passes, failed with its output when not)."""

    def __init__(self, row, tell):
        super().__init__(row, tell)
        self.folder = Path(row["folder"])
        self._stop = threading.Event()
        self._seen = None

    def _snapshot(self) -> dict:
        found = {}
        for root, folders, files in os.walk(self.folder):
            folders[:] = [name for name in folders if name not in IGNORED]
            for name in files:
                path = Path(root) / name
                try:
                    found[str(path.relative_to(self.folder))] = path.stat().st_mtime_ns
                except OSError:
                    pass
        return found

    def start(self) -> None:
        self.online = True
        self._seen = self._snapshot()
        threading.Thread(target=self._watch, name=f"place-{self.id}", daemon=True).start()
        if self.row.get("check"):
            # Where the check stands when it is connected (or the life starts again).
            threading.Thread(target=self.check, name=f"check-{self.id}", daemon=True).start()

    def _watch(self) -> None:
        pending, since = set(), 0.0
        while not self._stop.wait(LOOK_SECONDS):
            now = self._snapshot()
            changed = {path for path in set(now) | set(self._seen) if now.get(path) != self._seen.get(path)}
            self._seen = now
            if changed:
                pending |= changed
                since = time.time()
                continue
            if pending and time.time() - since >= QUIET_SECONDS:
                files = sorted(pending)[:50]
                pending = set()
                self.tell(self.id, {"type": "folder.changed", "data": {"files": files}, "source": "outside"})
                if self.row.get("check") and not all(fnmatch.fnmatch(f, "*.md") for f in files):
                    self.check()

    def check(self) -> dict:
        """Run the declared check now: an outcome of the verb folder.check."""
        command = self.row["check"]
        started = time.time()
        try:
            done = subprocess.run(command, shell=True, cwd=self.folder, capture_output=True, text=True,
                                  timeout=float(self.row.get("check_timeout") or 900), encoding="utf-8",
                                  errors="replace")
            end = "done" if done.returncode == 0 else "failed"
            output = (done.stdout + done.stderr)[-4000:]
            code = done.returncode
        except subprocess.TimeoutExpired:
            end, output, code = "failed", "the check ran out of time", None
        outcome = {"type": "asp.outcome", "verb": "folder.check", "end": end, "source": "place",
                   "data": {"command": command, "exit": code, "output": output, "seconds": round(time.time() - started, 1)}}
        self.tell(self.id, outcome)
        return outcome

    def close(self) -> None:
        self._stop.set()
        super().close()


class TaskPlace(Place):
    """A browser or the desktop: reached through the task engine's environment of that kind."""

    def __init__(self, row, tell):
        super().__init__(row, tell)
        self.single_body = row["kind"] in SINGLE_BODY


def open_place(row, tell, *, key=None, folder=None) -> Place:
    if row["kind"] == "space":
        return SpacePlace(row, tell, key=key, folder=folder)
    if row["kind"] == "folder":
        return FolderPlace(row, tell)
    return TaskPlace(row, tell)
