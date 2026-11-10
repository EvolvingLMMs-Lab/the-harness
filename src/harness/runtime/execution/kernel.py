"""A persistent Python kernel for model-written programs, in its own process.

The host sends cells over stdin and reads one JSON reply per cell from a
private descriptor, so anything a program prints cannot corrupt the protocol.
The kernel namespace comes from a bootstrap callable `module:function` that
receives JSON options and returns a session object with:

    namespace: dict       names visible to programs
    drain() -> dict       attachments and events gathered during the cell
    close() -> None

Between cells the host may ask for the truth of an expression on the namespace
(Kernel.check), which runs no cell and drains nothing. While a cell runs it may run code
beside it (Kernel.side), on a thread of its own in the same namespace: what it prints
goes into the running cell's output, and a side_result message says how it ended.

The kernel reports imported Harness package modules to the host as a `modules` note:
those of the bootstrap once it is ready, then those new after each cell, side run and at
the close. The trace records what code the run loaded.
"""

import argparse
import contextlib
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

from harness.paths import PACKAGE, ROOT, import_roots, package_roots
from harness.core import spans
from harness.runtime.execution import control
from harness.runtime.events import EpisodeEnded, Escalation, ProgramFinished


# The kernel bootstrap: the embodiment's session with its skills (runtime/execution/session.py).
DEFAULT_BOOTSTRAP = "harness.runtime.execution.session:create_session"


# The kernel's interpreter when the agent's runtime names none: what `harness run` installed
# for the benchmark (the eval package's preflight), else the conversation's own.
KERNEL_PYTHON_ENV = "HARNESS_KERNEL_PYTHON"


def kernel_python(runtime: dict) -> str:
    """The interpreter the kernel of an episode runs in."""
    return runtime.get("python") or os.environ.get(KERNEL_PYTHON_ENV) or sys.executable


MAX_OUTPUT_CHARS = 8000
# Program output is a bounded stream, including when a program never returns.
MAX_PROGRAM_OUTPUT_CHARS = 1024 * 1024


class ProgramOutput:
    def __init__(self, cell):
        self.cell, self.size, self.pending = cell, 0, ""
        self.head = self.tail = ""
        self.exhausted = False

    def write(self, text):
        text = str(text)
        if self.size + len(text) > MAX_PROGRAM_OUTPUT_CHARS:
            self.exhausted = True
            self.flush()
            raise RuntimeError("program output limit exceeded (1048576 characters); write large data in the target")
        self.size += len(text)
        self.head = (self.head + text)[:MAX_OUTPUT_CHARS // 2]
        self.tail = (self.tail + text)[-MAX_OUTPUT_CHARS // 2:]
        self.pending += text
        while len(self.pending) >= 8192:
            chunk, self.pending = self.pending[:8192], self.pending[8192:]
            spans.note("program_output", cell=self.cell, text=chunk)
        return len(text)

    def flush(self):
        if self.pending:
            spans.note("program_output", cell=self.cell, text=self.pending)
            self.pending = ""

    def getvalue(self):
        self.flush()
        if self.size <= MAX_OUTPUT_CHARS // 2:
            return self.head
        if self.size <= MAX_OUTPUT_CHARS:
            return self.head + self.tail[-(self.size - len(self.head)):]
        return self.head + f"\n... {self.size - MAX_OUTPUT_CHARS} characters omitted; see program_output trace ...\n" + self.tail
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

    A managed workspace supplies its dispatcher and a launcher context manager factory.
    The launcher takes the dispatcher's options and yields the command and descriptors
    to pass to the kernel process.
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
            os.set_blocking(self.process.stdin.fileno(), False)
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
        self._running = False
        self._pause_pending = False
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
                                                                   "side_result"):
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
        # After startup every child message is untrusted. Only proposals and one reply
        # for the active host cell enter the managed conversation.
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
                if message.get("op") == "workspace_proposal":
                    identifier = message.get("id")
                    def reply(result, identifier=identifier):
                        self._write({"op": "workspace_result", "id": identifier, **result})
                    if not self._managed.submit(message, reply):
                        break
                elif message.get("op") is None and self._managed.accept_result(message.get("cell")):
                    self._replies.put(self._managed.result(message))
                else:
                    break
        except (ValueError, OSError):
            pass
        finally:
            self.kill()
            self._replies.put(None)

    def _receive(self, timeout):
        try:
            reply = self._replies.get(timeout=timeout)
        except queue.Empty:
            self.kill()
            raise KernelDied(f"Kernel did not answer within {timeout:.0f} s; it was killed") from None
        if reply is None:
            raise KernelDied(f"Kernel exited with code {self.process.wait()}")
        return reply

    def run(self, code: str, timeout: float) -> dict:
        """Run `code` as the next cell and return the kernel's reply: status (ok, error,
        escalated, episode_ended or finished), clipped stdout, error, seconds, and what the
        session drained (attachments, events, state, usage). Raises KernelDied when the
        kernel is not running, exits, or does not reply within `timeout` seconds."""
        return self._cell({"op": "run", "code": code}, timeout)

    def load_library(self, phase, entries=(), *, timeout=120):
        return self._cell({"op": "library", "phase": phase,
                           "entries": [(item.revision, item.pack().decode(), hand) for item, hand in entries]}, timeout)

    def _cell(self, request, timeout):
        if self.process.poll() is not None:
            raise KernelDied("Kernel is not running")
        self.cells += 1
        if self._managed is not None:
            if request["op"] != "run":
                raise ValueError("Managed workspace cells only support running programs")
            if request["code"] == "__wrap_up__()":
                return self._managed.result({"status": "ok"})
            self._managed.begin(self.cells)
        with self._writing:
            request["cell"] = self.cells
            if self._pause_pending:
                request["pause"] = True
            self._pause_pending = False
            self._running = True
            self._send(request)
        try:
            result = self._receive(timeout)
            if result.get("cell", self.cells) != self.cells:
                self.kill()
                raise KernelDied("Kernel returned a result for another cell")
            return result
        finally:
            if self._managed is not None:
                self._managed.stop()
            with self._writing:
                self._running = False
                self._pause_pending = False

    def check(self, condition: str, output: str, seconds: float) -> dict:
        """Evaluate `condition` (an expression) on what the last cell left, with `output`
        (what it printed) as the name output: {"value": its truth} or {"error": why not},
        within `seconds` (runtime/conversation.py: what a reply made while the cell ran
        expected it to leave)."""
        if self._managed is not None:
            return {"error": "Managed workspace cells do not support speculative checks"}
        if self.process.poll() is not None:
            raise KernelDied("Kernel is not running")
        with self._writing:
            self._send({"op": "check", "condition": condition, "output": output, "seconds": seconds})
        return self._receive(seconds + 30)

    def _send(self, request: dict) -> None:
        data = (json.dumps(request) + "\n").encode()
        if self._managed is None:
            self.process.stdin.write(data)
        else:
            import selectors

            view = memoryview(data)
            deadline = time.monotonic() + 5
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdin, selectors.EVENT_WRITE)
                while view:
                    if not selector.select(max(0, deadline - time.monotonic())):
                        self.kill()
                        raise BrokenPipeError("The managed kernel stopped reading")
                    count = self.process.stdin.write(view)
                    if count is not None:
                        view = view[count:]
        self.process.stdin.flush()

    def _write(self, request: dict) -> None:
        with self._writing:
            self._send(request)

    def pause(self) -> None:
        """Ask the program that runs, or is about to run, to stop at its next execution step
        (runtime/execution/control.py); nothing when the kernel no longer runs."""
        if self._managed is not None:
            self._managed.stop()
            return
        if self.process.poll() is not None:
            return
        with self._writing:
            if not self._running:
                # run() is about to send its cell: the request goes with it.
                self._pause_pending = True
                return
            try:
                self._send({"op": "pause"})
            except OSError:
                pass

    def message(self) -> None:
        """Tell the running cell a message for the model came (runtime/execution/control.py)."""
        if self._managed is not None:
            self._managed.stop()
            return
        with self._writing:
            if not self._running or self.process.poll() is not None:
                return
            try:
                self._send({"op": "message"})
            except OSError:
                pass

    def side(self, code: str, identifier: str) -> bool:
        """Run `code` beside the running cell, in the same namespace (its side_result
        message, with `identifier`, goes to on_span); False when no cell runs."""
        if self._managed is not None:
            return False
        with self._writing:
            if not self._running or self.process.poll() is not None:
                return False
            try:
                self._send({"op": "side", "id": identifier, "code": code})
            except OSError:
                return False
        return True

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
        """Tell the program that a sub-agent it started ended, with its report (its entry
        ends, runtime/execution/entries.py); nothing when the kernel no longer runs."""
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


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return text[:half] + f"\n... [{len(text) - MAX_OUTPUT_CHARS} characters omitted] ...\n" + text[-half:]


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
    sys.stdout = io.TextIOWrapper(os.fdopen(1, "wb", buffering=0), encoding="utf-8", errors="replace",
                                  write_through=True)

    writing = threading.Lock()

    def reply(data):
        line = json.dumps(data, allow_nan=False, default=repr) + "\n"
        with writing:
            channel.write(line)

    control.host_thoughts = bool(options.get("host_thoughts"))
    managed = forward_workspace_requests
    proposal_result = queue.Queue()
    proposal_lock = threading.Lock()
    cell = sequence = 0

    def propose(name, *args, **kwargs):
        nonlocal sequence
        with proposal_lock:
            sequence += 1
            reply({"op": "workspace_proposal", "id": sequence, "cell": cell,
                   "name": name, "args": args, "kwargs": kwargs})
            answer = proposal_result.get()
            if answer.get("id") != sequence or "error" in answer:
                raise RuntimeError(answer.get("error") or "The managed workspace reply is out of order")
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
    # The names the session provides, restored after every cell that rebinds them.
    api = {name: value for name, value in namespace.items() if not name.startswith("__")}
    # Requests are read on their own thread so that a pause reaches a running program.
    requests = queue.Queue()
    active_library = {}
    staged_library = None

    def wake_entries():
        tree = getattr(session, "_entry_tree", None)
        if tree is not None:
            with tree._changed:
                tree._changed.notify_all()

    def read_requests():
        for line in sys.stdin:
            request = json.loads(line)
            if managed and request["op"] == "workspace_result":
                proposal_result.put(request)
                continue
            if request["op"] == "pause":
                control.request_pause()
                wake_entries()
                continue
            if request["op"] == "message":
                control.request_message()
                wake_entries()
                continue
            if request["op"] == "side":
                _side(namespace, request, reply, report_modules, getattr(session, "_entry_tree", None))
                continue
            if request["op"] == "answer":
                control.answer(request["id"], request.get("value"))
                continue
            if request["op"] == "agent_ended":
                control.agent_ended(request.get("agent"), request.get("report"),
                                    cancelled=bool(request.get("cancelled")))
                continue
            if request["op"] == "run":
                # A pause belongs to the cell after which it was sent.
                control.clear()
                if request.get("pause"):
                    control.request_pause()
            requests.put(request)
        requests.put(None)

    threading.Thread(target=read_requests, daemon=True).start()
    while True:
        request = requests.get()
        if request is None or request["op"] == "close":
            break
        if request["op"] == "check":
            reply(_check(namespace, request))
            continue
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
        if managed:
            cell = request["cell"]
        started = time.perf_counter()
        buffer = ProgramOutput(request["cell"])
        result = {"status": "ok", "error": None, "escalation": None, "episode_ended": None}
        # The session's entries (runtime/execution/entries.py): an event for the model that came while
        # no program ran ends this one before it starts, and one that came while it ran
        # ends it if it did not meet it.
        tree = getattr(session, "_entry_tree", None)
        try:
            code = compile(request["code"], f"<cell-{request['cell']}>", "exec")
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                if tree is not None:
                    tree.begin_program()
                exec(code, namespace)
                if tree is not None:
                    tree.end_program()
        except Escalation as escalation:
            result["status"] = "escalated"
            result["escalation"] = escalation.trace.to_dict()
        except EpisodeEnded as ended:
            result["status"] = "episode_ended"
            result["episode_ended"] = ended.trace.to_dict()
        except ProgramFinished as finished:
            result["status"] = "finished"
            result["finish"] = finished.summary
        except KeyboardInterrupt:
            result["status"] = "error"
            result["error"] = "KeyboardInterrupt"
        except BaseException as error:
            result["status"] = "error"
            result["error"] = format_error(error)
        if control.host_thoughts:
            spans.note("cell_finishing", cell=request["cell"])
        # Names the session gained while the cell ran (an attached environment, skills
        # switched on) are part of its API from now on; those it gave up are no longer.
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
        if restored:
            buffer.write(f"\nWarning: the program rebound the API name(s) {', '.join(restored)}; they were restored "
                         "to the built-in skills after it ended. Give your own functions and variables other names.\n")
        result["stdout"] = _clip(buffer.getvalue())
        if buffer.exhausted:
            result.update(status="error", error="Program output resource limit exceeded")
        result["seconds"] = time.perf_counter() - started
        report_modules()
        try:
            result.update(session.drain())
        except Exception as error:
            result["drain_error"] = format_error(error)
        result["cell"] = request["cell"]
        reply(result)
    report_modules()
    session.close()


def _side(namespace: dict, request: dict, reply, report_modules=None, tree=None) -> None:
    """Run a side request's code on a thread of its own in `namespace`, beside the cell,
    and reply how it ended (side_result: status ok, escalated or error), after
    `report_modules()` tells the host the modules it imported."""

    def run():
        result = {"op": "side_result", "id": request.get("id"), "status": "ok", "error": None}
        try:
            exec(compile(request["code"], f"<side-{request.get('id')}>", "exec"), namespace)
        except Escalation as escalation:
            result.update(status="escalated", escalation=escalation.trace.to_dict())
        except BaseException as error:
            result.update(status="error", error=format_error(error))
        if report_modules is not None:
            report_modules()
        reply(result)

    if tree is None:
        threading.Thread(target=run, name="side", daemon=True).start()
    else:
        try:
            tree.spawn(run, name=f"parallel {request['id']}")
        except Exception as error:
            reply({"op": "side_result", "id": request.get("id"), "status": "error", "error": format_error(error)})


def _check(namespace: dict, request: dict) -> dict:
    """The truth of a check request's condition on `namespace`, with its output as the
    name output, evaluated on a thread of its own for at most its seconds."""
    checked = {}

    def evaluate():
        try:
            scope = {**namespace, "output": request.get("output") or ""}
            checked["value"] = bool(eval(compile(request["condition"], "<assume>", "eval"), scope))
        except BaseException as error:
            checked["error"] = f"{type(error).__name__}: {error}"[:300]

    thread = threading.Thread(target=evaluate, name="check", daemon=True)
    thread.start()
    thread.join(float(request.get("seconds") or 2.0))
    if thread.is_alive():
        return {"status": "check", "error": "the condition took too long"}
    return {"status": "check", **checked}


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
