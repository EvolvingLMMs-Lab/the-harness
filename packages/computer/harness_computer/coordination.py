"""What the agents of every session on this computer share, kept in files (DATA/locks), not
in a process: the input lock and who owns which window.

Sessions run in the session host, in the app, in a script's own process (an in-process
Conversation) or in a worker on its own; all of them read and write the same files, so
the rules hold without the host.

- The input lock: the user's real mouse and keyboard serve one agent at a time. Only the
  physical dispatch of an input step holds it (never a screenshot, a model call or a
  background step). On Windows it is a named mutex, elsewhere an flock on locks/input.lock;
  both are freed by the system when the holder dies. Waiters line up in locks/input-queue
  (one ticket each, oldest first), so the lock goes round in order and a session can say
  it waits for it and behind whom. The holder writes locks/input-holder.json, and after
  each dispatch locks/input-last.json (when, by whom, where the pointer ended), which a
  worker reads to tell another agent's input from the user's.
- Window ownership: a window takes one agent's input at a time. An agent owns a window
  once input reached it; another agent's input into it is refused (the shield's check
  "window") until the owner gives it up (its episode ends) or hands it on (transfer:
  a parent agent lending a window to a sub-agent). One file per window under
  locks/windows; an owner whose process died owns nothing.

Standard library only.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time

from harness.sdk import atomic_write, data, pid_alive

# How often a waiter looks at the queue again.
POLL_SECONDS = 0.02
# A file lock (the queue's, a window's) older than this was left by a process that died.
STALE_SECONDS = 10.0


def locks_dir(directory=None) -> Path:
    """The coordination files: `directory`, else DATA/locks."""
    return Path(directory) if directory is not None else data() / "locks"


def alive(pid) -> bool:
    """Whether process `pid` runs (on this computer; core/procs.py)."""
    return pid_alive(pid)


def owner_name(owner) -> str:
    """An owner as one string: "<session>/<agent>" for {session, agent}, else itself."""
    if isinstance(owner, dict):
        return f"{owner.get('session') or '?'}/{owner.get('agent') or 'main'}"
    return str(owner)


def _read(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, value) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False))


# The lock of this process for each lock directory: a named mutex is the thread's (taken
# again by the thread that holds it), so threads of one process take this one first.
_LOCAL = {}
_LOCAL_GUARD = threading.Lock()


class _Mutex:
    """The system lock under the input lock: a named mutex on Windows (Local\\, this
    logon's desktop), an flock elsewhere, under a lock of this process. Taken and released
    by the same thread."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._handle = None
        self._file = None
        with _LOCAL_GUARD:
            self._local = _LOCAL.setdefault(str(Path(directory).resolve()).lower(), threading.Lock())

    def try_take(self) -> bool:
        if not self._local.acquire(blocking=False):
            return False
        try:
            taken = self._system_take()
        except BaseException:
            self._local.release()
            raise
        if not taken:
            self._local.release()
        return taken

    def _system_take(self) -> bool:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            if self._handle is None:
                digest = hashlib.sha1(str(self.directory.resolve()).lower().encode()).hexdigest()[:16]
                handle = kernel32.CreateMutexW(None, False, f"Local\\the-harness-input-{digest}")
                if not handle:
                    raise OSError(f"the input lock's mutex could not be made ({ctypes.GetLastError()})")
                self._handle = handle
            # WAIT_OBJECT_0, or WAIT_ABANDONED: its holder died, and it is ours now.
            if kernel32.WaitForSingleObject(self._handle, 0) in (0, 0x80):
                return True
            return False
        import fcntl

        if self._file is None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._file = open(self.directory / "input.lock", "a+", encoding="utf-8")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def release(self) -> None:
        try:
            if sys.platform == "win32":
                import ctypes

                if self._handle is not None:
                    ctypes.windll.kernel32.ReleaseMutex(self._handle)
            elif self._file is not None:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._local.release()

    def close(self) -> None:
        if sys.platform == "win32":
            import ctypes

            if self._handle is not None:
                ctypes.windll.kernel32.CloseHandle(self._handle)
                self._handle = None
        elif self._file is not None:
            self._file.close()
            self._file = None


class Held:
    """The input lock, held: release() it (the thread that took it), or use it as a
    context manager. `waited`: seconds spent in the queue; `since`: when it was taken."""

    def __init__(self, lock: "InputLock", mutex: _Mutex, owner: dict, waited: float):
        self.lock = lock
        self._mutex = mutex
        self.owner = owner
        self.waited = waited
        self.since = time.monotonic()
        self.released = False

    def held_for(self) -> float:
        return time.monotonic() - self.since

    def others_waiting(self) -> bool:
        """Whether another agent waits in the queue for the lock."""
        return bool(self.lock.queue())

    def record(self, began: float, ended: float, pointer=None, window=None) -> None:
        """Note this holder's dispatch (wall-clock times): other workers do not take its
        input for the user's."""
        _write(self.lock.directory / "input-last.json",
               {"owner": owner_name(self.owner), "pid": os.getpid(), "began": began, "ended": ended,
                "pointer": list(pointer) if pointer is not None else None, "window": window})

    def pass_on(self, timeout: float | None = None) -> bool:
        """Let the agents in line have the lock, then take it again in turn (the same
        thread): whether it came back within `timeout`."""
        self.release()
        again = self.lock.acquire(self.owner, timeout=timeout)
        if again is None:
            return False
        self._mutex, self.since, self.released = again._mutex, again.since, False
        self.waited += again.waited
        return True

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            (self.lock.directory / "input-holder.json").unlink()
        except OSError:
            pass
        self._mutex.release()
        self._mutex.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


class InputLock:
    """The machine-wide input lock (see the module docstring)."""

    def __init__(self, directory=None):
        self.directory = locks_dir(directory)

    @property
    def _queue(self) -> Path:
        return self.directory / "input-queue"

    def acquire(self, owner: dict, timeout: float | None = None, cancelled=None) -> Held | None:
        """Take the lock for `owner` ({session, agent, ...}) in turn: None when `timeout`
        seconds passed or `cancelled()` held first."""
        began = time.monotonic()
        self._queue.mkdir(parents=True, exist_ok=True)
        ticket = self._queue / f"{time.time_ns():020d}-{os.getpid()}-{secrets.token_hex(3)}.json"
        _write(ticket, {**{key: value for key, value in owner.items() if isinstance(value, (str, int, float))},
                        "owner": owner_name(owner), "pid": os.getpid(), "since": time.time()})
        mutex = _Mutex(self.directory)
        try:
            while True:
                if self._first(ticket) and mutex.try_take():
                    _write(self.directory / "input-holder.json",
                           {"owner": owner_name(owner), "pid": os.getpid(), "since": time.time()})
                    return Held(self, mutex, owner, time.monotonic() - began)
                if (timeout is not None and time.monotonic() - began >= timeout) or (cancelled and cancelled()):
                    mutex.close()
                    return None
                time.sleep(POLL_SECONDS)
        finally:
            try:
                ticket.unlink()
            except OSError:
                pass

    def _tickets(self) -> list[Path]:
        """The queue's tickets, oldest first, less those of processes that died."""
        try:
            tickets = sorted(self._queue.glob("*.json"))
        except OSError:
            return []
        live = []
        for ticket in tickets:
            match = re.match(r"\d+-(\d+)-", ticket.name)
            if match and not alive(match.group(1)):
                try:
                    ticket.unlink()
                except OSError:
                    pass
                continue
            live.append(ticket)
        return live

    def _first(self, ticket: Path) -> bool:
        tickets = self._tickets()
        return not tickets or tickets[0] == ticket

    def queue(self) -> list[dict]:
        """Who waits for the lock, first in line first."""
        return [item for item in map(_read, self._tickets()) if item]

    def holder(self) -> dict | None:
        """Who holds the lock now (owner, pid, since), when its process runs."""
        item = _read(self.directory / "input-holder.json")
        return item if item and alive(item.get("pid")) else None

    def last(self) -> dict | None:
        """The last dispatch (owner, pid, began, ended, pointer, window)."""
        return _read(self.directory / "input-last.json")

    def waiting(self, owner) -> str | None:
        """What `owner` waits for, when it is in the queue: "the input lock (N ahead of it;
        held by S/A)"; None when it does not wait."""
        name = owner_name(owner)
        line = self.queue()
        for place, item in enumerate(line):
            if item.get("owner") == name:
                holder = self.holder()
                held = f"; held by {holder['owner']}" if holder else ""
                return f"waiting for the input lock ({place} ahead{held})"
        return None


def _key(window) -> str:
    """A window's file name: its handle (or what names it), made safe."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(window))[:120] or "_"


class WindowOwners:
    """Who owns which window (see the module docstring). A window is named by what the
    worker knows of it: its handle where the system gives one."""

    def __init__(self, directory=None):
        self.directory = locks_dir(directory) / "windows"

    def _path(self, window) -> Path:
        return self.directory / f"{_key(window)}.json"

    def owner(self, window) -> dict | None:
        """The owner of `window` ({owner, pid, since, app, title}), when its process runs."""
        item = _read(self._path(window))
        return item if item and alive(item.get("pid")) else None

    def claim(self, window, owner, **about) -> dict | None:
        """Own `window` for `owner`, unless another live owner has it: then that owner's
        entry (and nothing changes); None when it is `owner`'s now."""
        name = owner_name(owner)
        path = self._path(window)
        self.directory.mkdir(parents=True, exist_ok=True)
        entry = {"window": str(window), "owner": name, "pid": os.getpid(), "since": time.time(),
                 **{key: value for key, value in about.items() if value is not None}}
        for _ in range(3):
            try:
                handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                current = _read(path)
                if current is None:
                    # Being written, or left half-written by a process that died.
                    try:
                        if time.time() - path.stat().st_mtime > STALE_SECONDS:
                            path.unlink()
                    except OSError:
                        pass
                    time.sleep(POLL_SECONDS)
                    continue
                if current.get("owner") == name:
                    if current.get("pid") != os.getpid():
                        _write(path, {**current, "pid": os.getpid()})
                    return None
                if alive(current.get("pid")):
                    return current
                # Its owner's process died: the window is free.
                _write(path, entry)
                return None
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(json.dumps(entry, ensure_ascii=False))
            return None
        return _read(path)

    def release(self, window, owner) -> bool:
        """Give `window` up, when `owner` owns it."""
        path = self._path(window)
        current = _read(path)
        if current is None or current.get("owner") != owner_name(owner):
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return True

    def release_all(self, owner) -> int:
        """Give up every window `owner` owns (its episode ended); how many."""
        return sum(self.release(item["window"], owner) for item in self.listed() if item.get("owner") ==
                   owner_name(owner))

    def transfer(self, window, owner, to) -> None:
        """Hand `window` from `owner` to `to` (a parent lends it to a sub-agent, which hands
        it back): ValueError when `owner` does not own it."""
        path = self._path(window)
        current = _read(path)
        if current is None or current.get("owner") != owner_name(owner):
            raise ValueError(f"{owner_name(owner)} does not own window {window}")
        _write(path, {**current, "owner": owner_name(to), "since": time.time()})

    def held(self, owner) -> list[dict]:
        """The windows `owner` owns now."""
        name = owner_name(owner)
        return [{**item, "id": item["window"],
                 "label": f"window {item.get('title') or item['window']}"
                          + (f" ({item['app']})" if item.get("app") else "")}
                for item in self.listed() if item.get("owner") == name]

    def listed(self) -> list[dict]:
        """Every window owned now, by owners whose process runs."""
        try:
            paths = sorted(self.directory.glob("*.json"))
        except OSError:
            return []
        return [item for item in map(_read, paths) if item and alive(item.get("pid"))]
