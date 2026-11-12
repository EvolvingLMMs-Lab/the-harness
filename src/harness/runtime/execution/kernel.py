"""A persistent Python kernel for model-written programs, in its own process.

The host sends programs over stdin and reads JSON messages from a private descriptor, so
anything a program prints cannot corrupt the protocol. The kernel namespace comes from a
bootstrap callable `module:function` that receives JSON options and returns a session
object with:

    namespace: dict       names visible to programs
    drain() -> dict       what the unit that calls it gathered (attachments, events, state)
    close() -> None

Every program runs as a unit (runtime/execution/entries.py): a thread of its own in the one
namespace, with its own output, events, pictures and result, beside the units already
running. The reply to a program comes at once: its result when it was over within the
grace the host gave, else {"status": "running", "unit": id}; the result of a unit that
outlived its reply, and the end of every other unit (spawned code, a sub-agent), is a
`unit_end` message. The host may cancel a unit, pause all of them and resume.

A managed kernel (an isolated process whose programs only propose operations) speaks the
same protocol: the same loop serves it, and its proposals travel beside the units'
messages. The host takes nothing of it on trust: runtime/execution/managed.py admits each
proposal and keeps what each unit did.

The kernel reports imported Harness package modules to the host as a `modules` note:
those of the bootstrap once it is ready, then those new after each unit and at the close.
The trace records what code the run loaded.
"""

import argparse
import importlib
import io
from functools import partial
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from types import SimpleNamespace

from harness.paths import PACKAGE, ROOT, import_roots, package_roots
from harness.core import spans
from harness.runtime.execution import control
from harness.runtime.execution.entries import Tree, current_entry


# The kernel bootstrap: the embodiment's session with its skills (runtime/execution/session.py).
DEFAULT_BOOTSTRAP = "harness.runtime.execution.session:create_session"


# The kernel's interpreter when the agent's runtime names none: what `harness run` installed
# for the benchmark (the eval package's preflight), else the conversation's own.
KERNEL_PYTHON_ENV = "HARNESS_KERNEL_PYTHON"


def kernel_python(runtime: dict) -> str:
    """The interpreter the kernel of an episode runs in."""
    return runtime.get("python") or os.environ.get(KERNEL_PYTHON_ENV) or sys.executable


# What the model is told of what a unit printed or returned: all of it up to INLINE_CHARS;
# more is saved to a file the model's programs can read, and it is told the file and the
# first PREVIEW_CHARS. A unit that failed is told the first and last FAILED_CHARS / 2.
INLINE_CHARS, PREVIEW_CHARS, FAILED_CHARS = 30_000, 2_000, 10_000
# Program output is a bounded stream, including when a program never returns.
MAX_PROGRAM_OUTPUT_CHARS = 1024 * 1024
_saved = SimpleNamespace(directory=None)


def told(text: str, name: str, failed: bool = False) -> str:
    """`text` (what the unit `name` printed or returned) as the model is told it: whole
    when it is short; else, of a unit that failed, its beginning and end with what lies
    between counted; of any other, the file it was saved to and its beginning."""
    if len(text) <= (FAILED_CHARS if failed else INLINE_CHARS):
        return text
    if failed:
        half = FAILED_CHARS // 2
        return text[:half] + f"\n... [{len(text) - FAILED_CHARS} characters omitted] ...\n" + text[-half:]
    if _saved.directory is None:
        _saved.directory = Path(tempfile.mkdtemp(prefix="harness-output-"))
    path = _saved.directory / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    return (f"Output too large ({len(text)} characters). Full output saved to: {path}\n"
            f"Preview (first {PREVIEW_CHARS} characters):\n{text[:PREVIEW_CHARS]}")
# The longest that what a unit printed waits before it goes to the host.
OUTPUT_NOTE_SECONDS = 1.0


class ProgramOutput:
    """What one unit printed: bounded, and streamed to the host as program_output notes
    (`cell`: the number of the model's program, None for other units), a full chunk at once
    and anything less within OUTPUT_NOTE_SECONDS, so the host knows when a unit last printed."""

    def __init__(self, cell, unit=None):
        self.cell, self.unit, self.size, self.pending = cell, unit, 0, ""
        self.parts = []
        self.exhausted = False
        self._writing = threading.RLock()
        self._due = None

    def write(self, text):
        text = str(text)
        with self._writing:
            if self.size + len(text) > MAX_PROGRAM_OUTPUT_CHARS:
                self.exhausted = True
                self.flush()
                raise RuntimeError("program output limit exceeded (1048576 characters); write large data in the target")
            self.size += len(text)
            self.parts.append(text)
            self.pending += text
            while len(self.pending) >= 8192:
                chunk, self.pending = self.pending[:8192], self.pending[8192:]
                self._note(chunk)
            if self.pending and self._due is None:
                self._due = threading.Timer(OUTPUT_NOTE_SECONDS, self.flush)
                self._due.daemon = True
                self._due.start()
        return len(text)

    def _note(self, text):
        spans.note("program_output", cell=self.cell, text=text, **({"unit": self.unit} if self.unit else {}))

    def flush(self):
        with self._writing:
            if self._due is not None:
                self._due.cancel()
                self._due = None
            if self.pending:
                self._note(self.pending)
                self.pending = ""

    def recent(self, chars):
        """The last `chars` characters printed so far (at most INLINE_CHARS); reading takes
        nothing away."""
        chars = max(0, min(int(chars), INLINE_CHARS))
        with self._writing:
            return "".join(self.parts)[-chars:] if chars else ""

    def getvalue(self):
        self.flush()
        with self._writing:
            return "".join(self.parts)


class UnitOutput:
    """The kernel's sys.stdout or sys.stderr: what a unit's code writes (on its thread, or
    on a thread acting for it) goes to that unit's output, anything else to `fallback`."""

    def __init__(self, fallback):
        self.fallback = fallback

    def _sink(self):
        entry = current_entry()
        return (entry.box.output if entry is not None and entry.box.output is not None else None) or self.fallback

    def write(self, text):
        return self._sink().write(text)

    def flush(self):
        self._sink().flush()

    def __getattr__(self, name):
        return getattr(self.fallback, name)


# Top-level packages of the source checkout that kernels import (skills, benches).
REPO_PACKAGES = ("skills", "benches")


def repo_modules() -> list[str]:
    """Imported modules from Harness packages, including the shared namespaces."""
    roots = {root.absolute() for root in package_roots()}
    found = []
    for name, module in list(sys.modules.items()):
        if name.partition(".")[0] in REPO_PACKAGES:
            found.append(name)
            continue
        origin = getattr(module, "__file__", None)
        if isinstance(origin, str) and any(parent in roots for parent in Path(origin).parents):
            found.append(name)
    return sorted(found)


class PlainSession:
    """A bootstrap with an empty namespace, for tests and debugging."""

    def __init__(self, options=None):
        self.namespace = {"__name__": "__program__"}

    def drain(self):
        """Nothing: a plain session gathers no attachments or events."""
        return {}

    def close(self):
        """Nothing to release."""
        pass


class KernelDied(RuntimeError):
    """The kernel process failed to start, is not running, or did not answer in time (it is
    then killed)."""
    pass


_SANDBOX = None


def sandbox_available() -> bool:
    """Whether this machine can run the kernel's sandbox (util-linux unshare with user,
    mount and PID namespaces)."""
    global _SANDBOX
    if _SANDBOX is None:
        try:
            result = subprocess.run(["unshare", "--user", "--map-root-user", "--mount", "--pid", "--fork",
                                     "--mount-proc", "true"], capture_output=True, timeout=30)
            _SANDBOX = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _SANDBOX = False
    return _SANDBOX


class Kernel:
    """Host-side handle. One kernel lives for one episode.

    A managed workspace supplies the admission of its proposals (`managed`:
    runtime/execution/managed.py Admission) and a launcher context manager factory. The
    launcher takes the admission's options and yields the command and descriptors to pass
    to the kernel process.
    """

    def __init__(self, bootstrap: str, options: dict, *, python: str = sys.executable,
                 cwd: str | None = None, env: dict | None = None, log_path: Path | None = None,
                 start_timeout: float = 300.0, on_span=None, managed=None, managed_launcher=None):
        if (managed is None) != (managed_launcher is None):
            raise ValueError("A managed kernel requires both a dispatcher and a launcher")
        # Called with every span record of the kernel's skills and service calls.
        self.on_span = on_span
        self._managed = managed
        self._log = open(log_path, "ab") if log_path else subprocess.DEVNULL
        if env is None:
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(import_roots() + [p for p in [env.get("PYTHONPATH")] if p])
        isolation = options.get("isolation")
        if isolation == "auto":
            # Containers often forbid user namespaces; an evaluation host need not allow them.
            # The guard inside the kernel (reachable services, no processes) needs none.
            isolation = True if sandbox_available() else {"sandbox": False}
            if isolation is not True:
                print("kernel: user namespaces are not available here; programs run without the filesystem "
                      "sandbox (the network, process and file guard stays)", file=sys.stderr, flush=True)
            options = {**options, "isolation": isolation}
        command = [python, "-u", "-m", "harness.runtime.execution.kernel",
                   "--bootstrap", bootstrap, "--options", "-"]
        self._workspace = None
        if isinstance(isolation, dict) and isolation.get("sandbox") is False:
            # No sandbox: the file guard inside the kernel (isolation.py) keeps programs to
            # the installation, the source and this workspace; the environment carries no
            # keys but the models'.
            from harness.runtime.safety.isolation import kernel_environment

            if cwd is None:
                self._workspace = cwd = tempfile.mkdtemp(prefix="harness-kernel-")
            env = {**kernel_environment(options, env, python), "HOME": cwd, "TMPDIR": cwd,
                   "TEMP": cwd, "TMP": cwd, "PYTHONDONTWRITEBYTECODE": "1"}
        elif isolation:
            # App. A: the kernel sees only the Python installation and the harness
            # source, and reaches only the services in its options (isolation.py).
            from harness.runtime.safety.isolation import hidden_roots, kernel_environment, package_dirs, sandbox_command

            # A virtual environment's interpreter links to a base installation: both are shown.
            prefixes = sorted({Path(python).absolute().parents[1], Path(python).resolve().parents[1]})
            source = [*map(Path, import_roots()[1:]), PACKAGE, *(ROOT / name for name in REPO_PACKAGES),
                      *package_dirs(python=python)]
            extra = isolation.get("hide", []) if isinstance(isolation, dict) else []
            workspace = Path(cwd).resolve() if cwd else None
            keep = [workspace] if workspace else []
            command = sandbox_command(command, keep=keep, read_only=[*prefixes, *source],
                                      hide=hidden_roots([*prefixes, PACKAGE.parent, *keep], extra), cwd=workspace)
            env, cwd = kernel_environment(options, env, python), None
            if workspace:
                env["PYTHONDONTWRITEBYTECODE"] = "1"
        from harness.runtime.safety.approval import WORKER_APPROVAL_KEY

        env = {name: value for name, value in env.items() if name.upper() != WORKER_APPROVAL_KEY}
        if managed is not None:
            with managed_launcher(managed.options()) as (launch, pass_fds):
                self.process = subprocess.Popen(launch, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=self._log, env={}, pass_fds=pass_fds, bufsize=0)
        else:
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                cwd=cwd, env=env, bufsize=0,
            )
            # Startup data can exceed Windows' command-line limit as the library grows.
            self._send(options)
        self._replies: queue.Queue = queue.Queue()
        # run() and pause() may write from different threads; the order of what they
        # write is the order the kernel sees.
        self._writing = threading.Lock()
        # A managed kernel: the cell whose reply is awaited, the cells whose reply went as
        # "running" (their result is a unit_end), their deadlines, and what the isolated
        # kernel calls each unit.
        self._awaited = None
        self._detached = set()
        self._deadlines = {}
        self._names = {}
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.cells = 0
        ready = self._receive(start_timeout)
        if ready.get("status") != "ready":
            self.close()
            raise KernelDied(f"Kernel failed to start: {ready.get('error')}")
        self.names = ready.get("names", [])
        # The worker's private paths the kernel refuses to programs (isolation.py).
        self.private = ready.get("private", [])

    def _read(self):
        if self._managed is not None:
            self._read_managed()
            return
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._replies.put({"status": "protocol_error", "error": line[:200].decode(errors="replace")})
                continue
            if isinstance(message, dict) and message.get("op") == "worker_request":
                try:
                    if self.on_span is None:
                        raise RuntimeError("Kernel has no worker dispatcher")
                    self.on_span(message)
                except Exception as error:
                    self.answer(message["id"], {"worker": True, "error": str(error)})
                continue
            if isinstance(message, dict) and message.get("op") in ("span_start", "span_end", "note", "entry_start",
                                                                   "entry_claims", "entry_end", "world",
                                                                   "unit_end"):
                if self.on_span is not None:
                    try:
                        self.on_span(message)
                    except Exception:
                        # A span that cannot be recorded never stops the replies.
                        pass
                continue
            if not isinstance(message, dict) or message.get("op") is not None or not any(
                    key in message for key in ("status", "value", "error")):
                self.process.kill()
                self._replies.put({"status": "protocol_error", "error": "Unknown kernel message; execution stopped"})
                break
            self._replies.put(message)
        self._replies.put(None)

    def _read_managed(self):
        # After startup every child message is untrusted. Only proposals, the reply to the
        # program that is awaited and the end of a program that outlived its reply enter
        # the conversation, each admitted by the host (runtime/execution/managed.py).
        stream = self.process.stdout
        limit = 64 * 1024
        try:
            line = stream.readline(limit + 1)
            if not line or len(line) > limit:
                return
            self._replies.put(json.loads(line))
            while line := stream.readline(limit + 1):
                if len(line) > limit:
                    break
                message = json.loads(line)
                if not isinstance(message, dict):
                    break
                op, cell = message.get("op"), message.get("cell")
                if op == "workspace_proposal":
                    identifier = message.get("id")
                    def reply(result, identifier=identifier):
                        self._write({"op": "workspace_result", "id": identifier, **result})
                    if not self._managed.submit(message, reply):
                        break
                elif op is None and message.get("status") == "running":
                    unit = self._managed.running(cell) if cell == self._awaited else None
                    if unit is None:
                        break
                    name = message.get("unit")
                    self._names[cell] = name[:32] if isinstance(name, str) else None
                    self._detached.add(cell)
                    self._replies.put({"status": "running", "unit": unit, "cell": cell})
                elif op in (None, "unit_end") and self._managed.settled(cell):
                    continue
                elif ((op is None and cell == self._awaited and cell not in self._detached)
                      or (op == "unit_end" and cell in self._detached)) and self._managed.accept_result(cell):
                    self._managed_result(message, cell)
                else:
                    break
        except (ValueError, OSError):
            pass
        finally:
            self.kill()
            self._replies.put(None)

    def _managed_result(self, message, cell) -> None:
        """The result of a managed program, as the host kept it: the reply to its program
        while that is awaited, else a unit_end for on_span."""
        deadline = self._deadlines.pop(cell, None)
        if deadline is not None:
            deadline.cancel()
        self._names.pop(cell, None)
        result = self._managed.result(message, cell)
        if cell in self._detached:
            self._detached.discard(cell)
            if self.on_span is not None:
                try:
                    self.on_span({"op": "unit_end", **result})
                except Exception:
                    pass
        else:
            self._replies.put(result)

    def _managed_expired(self, cell) -> None:
        """A managed program's time is over and no result came: the host cancels its unit
        and ends it itself (the isolated kernel's word is not waited for)."""
        if self._managed.accept_result(cell):
            self._managed.cancel(self._managed.unit(cell))
            self._ask({"op": "cancel", "unit": self._names.get(cell)})
            self._managed_result({"status": "error", "error": "Program deadline exceeded"}, cell)

    def _receive(self, timeout):
        try:
            reply = self._replies.get(timeout=timeout)
        except queue.Empty:
            self.kill()
            raise KernelDied(f"Kernel did not answer within {timeout:.0f} s; it was killed") from None
        if reply is None:
            raise KernelDied(f"Kernel exited with code {self.process.wait()}")
        return reply

    def start(self, code: str, grace: float, timeout: float | None = None, *, name: str | None = None,
              announce=None) -> dict:
        """Start `code` as a unit called `name` and return the kernel's reply, at most
        `grace` seconds later: the unit's result when it was over by then (status ok,
        error, escalated, episode_ended or finished, clipped stdout, error, seconds, and
        what the unit gathered: attachments, events, state, usage), else {"status":
        "running", "unit"}: its result then comes as a `unit_end` message to on_span. Both
        carry `cell`, this kernel's number of the program, which `announce(cell)` is told
        before the program is sent. The kernel cancels the unit after `timeout` seconds.
        Raises KernelDied when the kernel is not running, exits, or does not reply."""
        request = {"op": "run", "code": code, "grace": max(0.0, float(grace))}
        if timeout is not None:
            request["timeout"] = float(timeout)
        if name:
            request["name"] = str(name)
        return self._cell(request, float(grace) + 60.0, announce)

    def run(self, code: str, timeout: float) -> dict:
        """Run `code` as a unit and wait for its result (see start), at most `timeout`
        seconds, after which the kernel cancels it."""
        return self._cell({"op": "run", "code": code, "grace": float(timeout) + 10.0, "timeout": float(timeout)},
                          float(timeout) + 70.0)

    def run_staged(self, code: str, timeout: float) -> dict:
        """Run `code` (an entry's own test) as a cell on the library entries prepared and not
        yet committed (load_library "prepare"): it sees them and the namespace, the names it
        binds are dropped, and what it executes counts as testing, not as uses. It runs as a
        unit like every program and is waited for; the kernel ends it after `timeout`
        seconds. The reply is run()'s; the host that asked reads it (runtime/task/run.py)."""
        return self._cell({"op": "run", "code": code, "staged": True, "grace": float(timeout) + 10.0,
                           "timeout": float(timeout)}, float(timeout) + 70.0)

    def load_library(self, phase, entries=(), *, timeout=120):
        return self._cell({"op": "library", "phase": phase,
                           "entries": [(item.revision, item.pack().decode(), hand) for item, hand in entries]}, timeout)

    def _cell(self, request, timeout, announce=None):
        if self.process.poll() is not None:
            raise KernelDied("Kernel is not running")
        self.cells += 1
        cell = self.cells
        if announce is not None:
            announce(cell)
        if self._managed is not None:
            if request["op"] != "run":
                raise ValueError("A managed kernel only runs programs")
            self._managed.begin(cell, request.get("name"))
            if request.get("timeout") is not None:
                # The host keeps the program's time itself, a moment after the isolated
                # kernel should have.
                deadline = self._deadlines[cell] = threading.Timer(
                    float(request["timeout"]) + 5.0, self._managed_expired, (cell,))
                deadline.daemon = True
                deadline.start()
        with self._writing:
            request["cell"] = cell
            self._awaited = cell
            self._send(request)
        result = self._receive(timeout)
        if result.get("cell", cell) != cell:
            self.kill()
            raise KernelDied("Kernel returned a result for another cell")
        return result

    def _send(self, request: dict) -> None:
        data = (json.dumps(request) + "\n").encode()
        if self._managed is None:
            self.process.stdin.write(data)
            self.process.stdin.flush()
            return
        # An isolated kernel that stops reading must not hold the host: the write has
        # five seconds.
        done, failed = threading.Event(), []

        def write():
            try:
                view = memoryview(data)
                while view:
                    view = view[self.process.stdin.write(view) or 0:]
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                failed.append(error)
            finally:
                done.set()

        threading.Thread(target=write, name="managed-write", daemon=True).start()
        if not done.wait(5):
            self.kill()
            raise BrokenPipeError("The managed kernel stopped reading")
        if failed:
            raise BrokenPipeError(str(failed[0]))

    def _write(self, request: dict) -> None:
        with self._writing:
            self._send(request)

    def pause(self) -> None:
        """Pause the model's units: each stops at its next execution step or wait, and
        nothing acts until resume() (runtime/execution/control.py); nothing when the kernel no
        longer runs. A managed kernel's proposals are refused by the host meanwhile."""
        if self._managed is not None:
            self._managed.stop()
        self._ask({"op": "pause"})

    def resume(self) -> None:
        """The pause is over."""
        if self._managed is not None:
            self._managed.resume()
        self._ask({"op": "resume"})

    def cancel(self, unit: str | None = None) -> None:
        """Cancel the unit `unit` (None: every unit of the model); its end comes as its
        result or a `unit_end` message."""
        if self._managed is not None:
            # The host ends the unit's part here; the isolated kernel is told its own name of it.
            cells = self._managed.cancel(unit)
            for cell in ([None] if unit is None else cells):
                self._ask({"op": "cancel", "unit": None if cell is None else self._names.get(cell)})
            return
        self._ask({"op": "cancel", "unit": unit})

    def _ask(self, request) -> None:
        if self.process.poll() is not None:
            return
        try:
            self._write(request)
        except OSError:
            pass

    def answer(self, identifier, value) -> None:
        """Answer a request the running program sent as a note (runtime/execution/control.py);
        nothing when the kernel no longer runs."""
        if self.process.poll() is not None:
            return
        try:
            self._write({"op": "answer", "id": str(identifier), "value": value})
        except OSError:
            pass

    def agent_ended(self, agent, report, *, cancelled=False) -> None:
        """Tell the kernel that a sub-agent ended, with its report (its unit ends,
        runtime/execution/entries.py); nothing when the kernel no longer runs."""
        if self.process.poll() is not None:
            return
        try:
            self._write({"op": "agent_ended", "agent": str(agent), "report": report, "cancelled": cancelled})
        except OSError:
            pass

    def kill(self):
        """Kill the kernel process if it still runs."""
        if self._managed is not None:
            self._managed.stop()
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()

    def close(self):
        """Ask the kernel to close its session and exit (killing it when it does not within
        30 s), then close the pipes and the log."""
        if self._managed is not None:
            self.kill()
        if self.process.poll() is None:
            try:
                self._write({"op": "close"})
                self.process.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                self.kill()
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()
        self._reader.join(timeout=5)
        if self._log is not subprocess.DEVNULL:
            self._log.close()
        if self._workspace:
            shutil.rmtree(self._workspace, ignore_errors=True)


def format_error(error: BaseException) -> str:
    """Traceback restricted to program frames, plus the frame that raised."""
    summary = traceback.TracebackException.from_exception(error)
    frames = [frame for frame in summary.stack if frame.filename.startswith("<cell-")]
    if summary.stack and (not frames or frames[-1] is not summary.stack[-1]):
        frames.append(summary.stack[-1])
    lines = ["Traceback (program frames):\n"]
    for frame in frames:
        lines.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n')
        if frame.line:
            lines.append(f"    {frame.line}\n")
    lines.extend(summary.format_exception_only())
    return "".join(lines)


def restore_api(namespace: dict, api: dict) -> list[str]:
    """Put back the session's API names that a program rebound or deleted (a model's
    own `def pick(m): ...` would otherwise break every later call of the skill) and
    return them, sorted."""
    missing = object()
    restored = []
    for name, value in api.items():
        current = namespace.get(name, missing)
        if current is value:
            continue
        try:  # a constant set to the same value again (TABLE_Z = 0.765) is not rebound
            same = not callable(value) and bool(current == value)
        except Exception:
            same = False
        if not same:
            namespace[name] = value
            restored.append(name)
    return sorted(restored)


def _serve(bootstrap: str, options: dict, *, forward_workspace_requests: bool = False) -> None:
    channel = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    # Stray writes to descriptor 1 from programs or libraries go to the log instead.
    os.dup2(2, 1)
    # What a unit prints is its own output; anything else goes to the log.
    sys.stdout = UnitOutput(io.TextIOWrapper(os.fdopen(1, "wb", buffering=0), encoding="utf-8", errors="replace",
                                             write_through=True))
    sys.stderr = UnitOutput(sys.stderr)

    writing = threading.Lock()

    def reply(data):
        line = json.dumps(data, allow_nan=False, default=repr) + "\n"
        with writing:
            channel.write(line)

    control.host_thoughts = bool(options.get("host_thoughts"))
    managed = forward_workspace_requests
    proposals = {}
    proposal_lock = threading.Lock()
    sequence = 0

    def propose(name, *args, **kwargs):
        """Propose an operation to the host as the unit that calls it, and wait for the
        host's answer (or for what ends the unit: its cancellation, a pause)."""
        nonlocal sequence
        unit = current_entry()
        if unit is None or unit.cell is None:
            raise RuntimeError("Only a program proposes operations")
        tree.check(unit)
        answered = queue.Queue(1)
        with proposal_lock:
            sequence += 1
            identifier = sequence
            proposals[identifier] = answered
            reply({"op": "workspace_proposal", "id": identifier, "cell": unit.cell,
                   "name": name, "args": args, "kwargs": kwargs})
        try:
            while True:
                try:
                    answer = answered.get(timeout=0.1)
                    break
                except queue.Empty:
                    tree.check(unit)
        finally:
            with proposal_lock:
                proposals.pop(identifier, None)
        if "error" in answer:
            raise RuntimeError(answer.get("error") or "The host refused the proposal")
        return answer.get("value")

    if options.get("host_controls"):
        options["worker_relay"] = partial(control.worker_call, reply)
    try:
        module_name, _, function_name = bootstrap.partition(":")
        factory = getattr(importlib.import_module(module_name), function_name)
        session = factory(options, propose) if managed else factory(options)
        namespace = session.namespace
    except BaseException as error:
        reply({"status": "error", "error": format_error(error) if not isinstance(error, SystemExit)
               else "bootstrap exited"})
        return
    isolation = options.get("isolation")
    if isolation:
        from harness.runtime.safety.isolation import endpoints, install_file_guard, install_network_guard, read_roots

        install_network_guard(endpoints(options))
        sandboxed = not (isinstance(isolation, dict) and isolation.get("sandbox") is False)
        source = [*map(Path, import_roots()[1:]), PACKAGE, *(ROOT / name for name in REPO_PACKAGES)]
        # The sandbox's /tmp is its own; without it the workspace is the kernel's working directory.
        install_file_guard(read_roots(source), [Path.cwd(), *([Path("/tmp")] if sandboxed else [])])
    private = []
    if options.get("private_paths"):
        from harness.runtime.safety.isolation import install_private_guard

        # The worker's private files: refused, and each attempt noted to the host.
        private = install_private_guard(options["private_paths"],
                                        lambda event, path: spans.note("file_access", operation=event, path=path))
    reply({"status": "ready", "names": sorted(name for name in namespace if not name.startswith("_")),
           **({"private": private} if private else {})})
    # Spans of skills and service calls go to the host as they start and end.
    if not managed:
        spans.set_sink(reply)
    reported = set()

    def report_modules():
        # The repository's modules imported since the last report (the bootstrap's first).
        new = [name for name in repo_modules() if name not in reported]
        if new:
            reported.update(new)
            spans.note("modules", loaded=new)

    report_modules()
    # The names the session provides, restored after every program that rebinds them.
    api = {name: value for name, value in namespace.items() if not name.startswith("__")}
    api_lock = threading.Lock()
    # The session's units (runtime/execution/entries.py); a session without a tree gets one here.
    tree = getattr(session, "_entry_tree", None)
    own_tree = tree is None
    if own_tree:
        tree = Tree(SimpleNamespace(state={}, reactive=None, _events=[], _ticker=SimpleNamespace(channels={})))
    tree.new_output = lambda entry: ProgramOutput(entry.cell, entry.id)
    # The programs whose reply has not gone yet, by number: {"result", "detached", "done"}.
    replies = {}
    replying = threading.Lock()
    active_library = {}
    staged_library = None

    def ended(result, timed_out) -> str:
        status = result["status"]
        if timed_out and status == "error":
            return "its time limit"
        trace = result.get("escalation") or result.get("episode_ended")
        if trace:
            return f"the event {trace['event']['kind']}"
        return {"ok": "by itself", "error": "an error", "cancelled": "cancelled", "finished": "finish"}.get(status, status)

    def unit_ended(entry, handled):
        """A unit ended: its result is the reply to its program when that has not gone
        yet, else a unit_end message."""
        box = entry.box
        result = {"unit": entry.id, "name": entry.name, "kind": entry.kind, **(entry.outcome or {"status": entry.status})}
        if entry.raised is not None:
            result["error"] = "KeyboardInterrupt" if isinstance(entry.raised, KeyboardInterrupt) else format_error(
                entry.raised)
        timer = getattr(entry, "deadline", None)
        if timer is not None:
            timer.cancel()
        if getattr(entry, "timed_out", False) and result["status"] not in ("episode_ended", "finished"):
            result.update(status="error", error=result.get("error") or "Program deadline exceeded")
        # The end report every unit gives, whoever started it (runtime/decision/messages.py ended()):
        # how it ended, and whether what it was for is the case (None: it stated no condition).
        result["ended"] = ended(result, getattr(entry, "timed_out", False))
        result["done"] = entry.ok
        if entry.cell is not None:
            with api_lock:
                # Names the session gained while the program ran (an attached environment,
                # skills switched on) are part of its API from now on; those it gave up
                # are no longer.
                changed = getattr(session, "_api_changes", None)
                if changed:
                    for name, value in changed.items():
                        if value is None:
                            api.pop(name, None)
                            namespace.pop(name, None)
                        else:
                            api[name] = namespace[name] = value
                    changed.clear()
                restored = restore_api(namespace, api)
            if restored and box.output is not None and not box.output.exhausted:
                box.output.write(f"\nWarning: the program rebound the API name(s) {', '.join(restored)}; they were "
                                 "restored to the built-in skills after it ended. Give your own functions and "
                                 "variables other names.\n")
        if box.output is not None:
            if box.output.exhausted:
                result.update(status="error", error="Program output resource limit exceeded")
            result["stdout"] = told(box.output.getvalue(), f"program-{entry.cell}" if entry.cell is not None
                                    else f"unit-{entry.id}", failed=result.get("status") == "error")
        result["seconds"] = (entry.ended or time.time()) - entry.started
        report_modules()
        if entry.cell is not None:
            try:
                result.update(session.drain())
            except Exception as error:
                result["drain_error"] = format_error(error)
            result["cell"] = entry.cell
        else:
            for key in ("attachments", "events", "looks", "event_counts"):
                if getattr(box, key):
                    result[key] = getattr(box, key)
            if entry.status == "done" and entry.result is not None:
                returned = entry.result if isinstance(entry.result, (dict, list, str, int, float, bool)) else repr(
                    entry.result)
                result["returned"] = returned if entry.agent is not None else told(str(returned), f"returned-{entry.id}")
            if entry.agent is not None:
                result["agent"] = entry.agent
            if handled:
                result["handled"] = True
            if entry.quiet:
                # The tree of reflexes answers the ends of its programs itself (runtime/reactive/tree.py).
                result["quiet"] = True
        with replying:
            waiting = replies.get(entry.cell) if entry.cell is not None else None
            if waiting is not None and not waiting["detached"]:
                waiting["result"] = result
                waiting["done"].set()
            else:
                reply({"op": "unit_end", **result})

    tree.on_end = unit_ended

    def wake_entries():
        with tree._changed:
            tree._changed.notify_all()

    def cancel_units(identifier):
        targets = tree.running() if identifier is None else [tree.entries.get(str(identifier))]
        for entry in targets:
            if entry is not None and entry is not tree.root and entry.running:
                try:
                    entry.cancel()
                except BaseException:
                    pass

    # Requests are read on their own thread so that a pause or a cancellation reaches the
    # units while the main thread waits for a program's grace.
    requests = queue.Queue()

    def read_requests():
        for line in sys.stdin:
            request = json.loads(line)
            if managed and request["op"] == "workspace_result":
                with proposal_lock:
                    answered = proposals.get(request.get("id"))
                if answered is not None:
                    answered.put(request)
                continue
            if request["op"] == "pause":
                control.request_pause()
                wake_entries()
                continue
            if request["op"] == "resume":
                control.resume()
                continue
            if request["op"] == "cancel":
                threading.Thread(target=cancel_units, args=(request.get("unit"),), name="cancel", daemon=True).start()
                continue
            if request["op"] == "answer":
                control.answer(request["id"], request.get("value"))
                continue
            if request["op"] == "agent_ended":
                control.agent_ended(request.get("agent"), request.get("report"),
                                    cancelled=bool(request.get("cancelled")))
                continue
            requests.put(request)
        requests.put(None)

    threading.Thread(target=read_requests, daemon=True).start()
    while True:
        request = requests.get()
        if request is None or request["op"] == "close":
            break
        if request["op"] == "library":
            from harness.runtime.learning.library import Revision, publish_entries, stage_entries

            try:
                phase = request["phase"]
                reactive = getattr(session, "reactive", None)
                if phase == "prepare":
                    staged_library = None
                    items = []
                    for expected, data, hand in request["entries"]:
                        item = Revision.unpack(data)
                        if item.revision != expected:
                            raise ValueError("library payload does not match its revision")
                        items.append((item, hand))
                    staged_library = stage_entries(items, namespace, active_library, reactive, api=api)
                elif phase == "commit" and staged_library is not None:
                    publish_entries(staged_library, namespace, active_library, reactive)
                    staged_library = None
                elif phase == "discard":
                    staged_library = None
                else:
                    raise ValueError("invalid library activation phase")
                reply({"status": "ok", "active": {key: row[0] for key, row in active_library.items()}})
            except BaseException as error:
                staged_library = None
                reply({"status": "error", "error": format_error(error)})
            continue
        number = request["cell"]
        waiting = {"result": None, "detached": False, "done": threading.Event()}
        with replying:
            replies[number] = waiting

        staged = bool(request.get("staged"))

        def program(source=request["code"], number=number, library=staged_library if staged else None):
            code = compile(source, f"<cell-{number}>", "exec")
            if library is None:
                exec(code, namespace)
                return
            from harness.runtime.learning.library import testing_staged

            # An entry's own test runs on a copy of the staged scope (the entry is not in the
            # programs' namespace before the host admits it), and what it executes counts as
            # testing, not as uses.
            with spans.testing(True), testing_staged(library) as target:
                exec(code, target)

        try:
            if staged and staged_library is None:
                raise RuntimeError("no library entry is prepared for its test")
            unit = tree.spawn(program, name=request.get("name") or f"cell {number}", cell=number)
        except BaseException as error:
            with replying:
                del replies[number]
            reply({"status": "error", "error": format_error(error), "stdout": "", "seconds": 0.0, "cell": number})
            continue
        if request.get("timeout") is not None:
            def expire(unit=unit):
                unit.timed_out = True
                unit.cancel()

            unit.deadline = threading.Timer(float(request["timeout"]), expire)
            unit.deadline.daemon = True
            unit.deadline.start()
        # The reply goes at once: the result when the program is over within its grace
        # (no grace given: whenever it is over), else its handle.
        waiting["done"].wait(request.get("grace"))
        with replying:
            # (Under the lock: a unit_end of this program never comes before this reply.)
            del replies[number]
            result = waiting["result"]
            waiting["detached"] = result is None
            reply(result if result is not None else {"status": "running", "unit": unit.id, "cell": number})
    report_modules()
    if own_tree:
        tree.close()
    session.close()


def main(argv=None):
    """The kernel process: build the session from `--bootstrap` with the JSON
    `--options` (or its first stdin line for `-`), then read cells from stdin."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--options", default="{}")
    parser.add_argument("--forward-workspace-requests", action="store_true")
    args = parser.parse_args(argv)
    _serve(args.bootstrap, json.loads(sys.stdin.readline() if args.options == "-" else args.options),
           forward_workspace_requests=args.forward_workspace_requests)


if __name__ == "__main__":
    main()
