"""Files and bounded processes in an explicitly bound, trusted-local target."""
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import tempfile
import threading
import time
import uuid

from harness.sdk import BenchWorker, EpisodeCursor, Evidence, Observation, WORKER_METHODS

ENVIRONMENT = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR", "COMSPEC",
               "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR")
OUTPUT_LIMIT = 16 * 1024 * 1024
PROCESS_LIMIT = 16


def create_environment(**options):
    return WorkspaceEnvironment(**options)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def window(path, offset=0, limit=12000):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 64000:
        raise ValueError("offset must be nonnegative and limit between 1 and 64000 bytes")
    with path.open("rb") as stream:
        stream.seek(offset)
        raw = stream.read(limit)
        size = os.fstat(stream.fileno()).st_size
    # Do not split a UTF-8 character between successive windows. Invalid bytes are
    # explicitly replaced; arbitrary binary work should use target commands.
    if offset + len(raw) < size:
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as error:
            if error.reason == "unexpected end of data" and error.start > 0:
                raw = raw[:error.start]
    end = offset + len(raw)
    return {"text": raw.decode("utf-8", errors="replace"), "offset": offset,
            "next_offset": end, "bytes": size, "truncated": end < size}


class Process:
    """Worker-owned resource. Stop requests and observed termination are separate facts."""
    def __init__(self, command, cwd, environment, timeout, directory, evidence, identity, scope):
        self.id, self.scope = uuid.uuid4().hex, scope
        self.command, self.cwd = command, str(cwd)
        self.output = directory / (self.id + ".log")
        self.output.touch()
        self.started, self.ended = time.monotonic(), None
        self.timeout, self.reason, self.cleanup_error = timeout, None, None
        self.evidence, self.identity, self.reference = evidence, identity, None
        self.lock, self.done = threading.RLock(), threading.Event()
        if isinstance(command, str) and command:
            argv = (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
                    if os.name == "nt" else ["/bin/sh", "-c", command])
        elif isinstance(command, list) and command and all(isinstance(x, str) for x in command):
            argv = command
        else:
            raise ValueError("command must be a nonempty argv list or shell string")
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                   if os.name == "nt" else {"start_new_session": True})
        self.process = subprocess.Popen(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **options)
        self.reader = threading.Thread(target=self._read, name="target-output", daemon=True)
        self.reader.start()
        threading.Thread(target=self._watch, name="target-lifetime", daemon=True).start()

    def _read(self):
        try:
            with self.output.open("ab", buffering=0) as output:
                total = 0
                while chunk := self.process.stdout.read1(8192):
                    remaining = max(0, OUTPUT_LIMIT - total)
                    self.evidence.reserve(min(len(chunk), remaining))
                    output.write(chunk[:remaining])
                    total += len(chunk)
                    if total > OUTPUT_LIMIT:
                        self.stop("output_limit")
                        break
        except OSError as error:
            self.cleanup_error = str(error)
            self.stop("output_error")
        finally:
            self.process.stdout.close()

    def _kill_group(self):
        try:
            if os.name == "nt":
                if self.process.poll() is None:
                    result = subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                            capture_output=True, timeout=5,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode and self.process.poll() is None:
                        self.cleanup_error = "taskkill did not confirm termination"
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except (OSError, subprocess.TimeoutExpired) as error:
            self.cleanup_error = str(error)

    def stop(self, reason="cancelled"):
        with self.lock:
            if self.ended is None:
                self.reason = self.reason or reason
                self._kill_group()

    def _watch(self):
        try:
            try:
                self.process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                self.stop("timeout")
                self.process.wait(timeout=5)
            self._kill_group()
            self.reader.join(5)
            if self.reader.is_alive():
                self.cleanup_error = "output pipe still open; descendant termination unconfirmed"
        except (OSError, subprocess.TimeoutExpired) as error:
            self.cleanup_error = str(error)
        finally:
            self.ended = time.monotonic()
            try:
                self.reference = self.evidence.record("process_end", self.result(), **self.identity, process_id=self.id)
            except OSError as error:
                self.cleanup_error = f"evidence incomplete: {error}"
            self.done.set()

    def result(self):
        size = self.output.stat().st_size
        return {"process_id": self.id, "scope": self.scope,
                "status": "running" if self.ended is None else "unknown" if self.process.poll() is None else self.reason or "exited",
                "exit_code": self.process.poll(), "stop_requested": self.reason,
                "cwd": self.cwd, "command": self.command, "timeout": self.timeout,
                "seconds": round((self.ended or time.monotonic()) - self.started, 3),
                "output": window(self.output, max(0, size - 6000), 6000), "output_file": str(self.output),
                "cleanup": {"scope": "process_group" if os.name != "nt" else "best_effort_tree",
                            "error": self.cleanup_error}, "evidence": self.reference}


class WorkspaceEnvironment(BenchWorker):
    name = "project-workspace"
    methods = (*WORKER_METHODS, "process", "cancel", "release")
    managed_control_calls = frozenset({"tick", "cancel", "release"})
    program_control_calls = frozenset({"tick", "cancel"})
    VIEWS = ()

    def __init__(self, folder, artifacts=None, environment=None):
        self.root = Path(folder).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("folder must be an existing directory")
        self.artifacts = Path(artifacts or tempfile.mkdtemp(prefix="harness-artifacts-")).resolve()
        if self.artifacts.is_relative_to(self.root):
            raise ValueError("run evidence must be outside the target project")
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.evidence = Evidence(self.artifacts / "evidence")
        self.environment = {k: v for k, v in os.environ.items() if k.upper() in ENVIRONMENT}
        self.environment.update(environment or {})
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in self.environment.items()):
            raise ValueError("target environment keys and values must be strings")
        self.processes, self.lock = {}, threading.RLock()
        self._cursor = EpisodeCursor()

    def reset(self, task, seed):
        if task != "free":
            raise ValueError("project tasks use free")
        self.close()
        self.processes = {}
        self._cursor = EpisodeCursor()
        self._cursor.start(uuid.uuid4().hex)
        self.new_outcome()
        return Observation(self._cursor.episode_id, 0, "Work in the bound target.", self._state(), {})

    def _state(self):
        return {"step": self._cursor.step, "ended": False, "root": str(self.root),
                "platform": platform.system(), "backend": "trusted-local",
                "processes": {k: p.result()["status"] for k, p in self.processes.items() if not p.done.is_set()}}

    def _call_profile(self):
        return {"name": self.name, "kind": "workspace", "clock": "events",
                "episode_id": self._cursor.episode_id, "root": str(self.root), "backend": "trusted-local",
                "action_ids": True, "environment_keys": sorted(self.environment), "artifacts": str(self.artifacts),
                "limits": {"processes": PROCESS_LIMIT, "output_bytes_per_process": OUTPUT_LIMIT,
                           "evidence_bytes": self.evidence.limit},
                "toolchain": "target PATH and explicit per-command env; no controller PYTHONPATH"}

    def _ended(self):
        return False

    def _evaluate(self):
        return {"success": None, "reward": None, "process_score": None, "steps": self._cursor.step,
                "reason": "Task acceptance is independent of process termination."}

    def _screenshot(self):
        return {}

    def path(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("file path leaves the bound target")
        return path

    def _call_tick(self, episode_id, step, command, cameras=None, action_id=None, execution_id=None):
        with self.lock:
            self.tick_begins(episode_id, step)
            identity = {"episode_id": episode_id, "step": step, "action_id": action_id}
            self.evidence.record("request", command, **identity)
            try:
                result = self._operate(command, identity)
            except (OSError, ValueError, KeyError, TypeError) as error:
                result = {"status": "error", "error": type(error).__name__, "message": str(error)}
            self._cursor.advance()
            try:
                reference = self.evidence.record("result", result, **identity)
            except OSError:
                # The action may have happened. Invalidate, do not retry from the old cursor.
                self._cursor.invalidate()
                raise
            return {"executed": True, "action_id": action_id, "state": self._state(),
                    "result": result, "evidence": reference,
                    "shield": {"verdict": "PASS", "command": command, "reasons": []}}

    def _operate(self, command, identity):
        op = command["type"]
        if op == "read":
            path = self.path(command["path"])
            return {**window(path, command.get("offset", 0), command.get("limit", 12000)), "sha256": digest(path)}
        if op == "write":
            path = self.path(command["path"])
            actual = digest(path) if path.exists() else None
            if actual != command.get("expected"):
                return {"status": "error", "error": "conflict", "message": "file changed; read before replacing", "sha256": actual}
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(command["text"].encode("utf-8"))
            try:
                if path.exists():
                    os.chmod(temporary, path.stat().st_mode)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return {"path": str(path), "sha256": digest(path)}
        if op in ("run", "start"):
            seconds = float(command.get("timeout", 120))
            if not math.isfinite(seconds) or not 0 < seconds <= 3600:
                raise ValueError("timeout must be between 0 and 3600 seconds")
            if sum(not p.done.is_set() for p in self.processes.values()) >= PROCESS_LIMIT:
                raise ValueError("task process limit reached")
            process = Process(command["command"], self.path(command.get("cwd", ".")),
                              {**self.environment, **(command.get("env") or {})}, seconds,
                              self.artifacts, self.evidence, identity, "task" if op == "start" else "execution")
            self.processes[process.id] = process
            return process.result()
        process = self.processes[command["process_id"]]
        if op == "output":
            return window(process.output, command.get("offset", 0), command.get("limit", 12000))
        if op == "cancel":
            process.stop()
            process.done.wait(5)
        elif op != "status":
            raise ValueError(f"unknown operation {op}")
        return process.result()

    def _call_process(self, episode_id, process_id):
        self._check_episode(episode_id)
        process = self.processes[process_id]
        return {**process.result(), "ready": process.done.is_set()}

    def _call_cancel(self, episode_id, process_id, reason="cancelled"):
        self._check_episode(episode_id)
        process = self.processes[process_id]
        self.evidence.record("stop_requested", {"process_id": process_id, "reason": reason}, episode_id=episode_id)
        process.stop("cancelled")
        process.done.wait(5)
        return process.result()

    def _call_release(self, episode_id):
        self._check_episode(episode_id)
        self.close()
        return {"processes": {k: p.result() for k, p in self.processes.items()}}

    def close(self):
        for process in self.processes.values():
            process.stop("session_closed")
        deadline = time.monotonic() + 10
        for process in self.processes.values():
            process.done.wait(max(0, deadline - time.monotonic()))
