"""Workspaces: where an agent acts, each served by a worker process of its own.

A workspace's kind decides its worker (KINDS):

  browser  benches.browser: a context of its own (cookies, storage and pages apart) in a
           headless Chrome that browser workspaces share (Chromes, at most `chromes` of
           them); never the user's screen, mouse or keyboard, so several run side by side.
  desktop  benches.computer: this computer's screen, mouse and keyboard. Several may run:
           their steps take the real mouse and keyboard in turn (the input lock), each into
           windows of its own (window ownership, coordination.py), as the physical-input
           policy allows (physical.py).
  apps     benches.computer with workspace "apps": the user's applications operated in the
           background, one window at a time (harness/desktop: the accessibility tree,
           window pictures, input sent to the window), the real mouse and keyboard only as
           the policy allows; where the system has a desktop backend (Windows; macOS; Linux
           on an X display).
  display  benches.computer with workspace "display": a display of the workspace's own
           (harness/desktop/display.py: Xvfb, or a headless weston with Xwayland, on Linux;
           a virtual machine, harness/desktop/vm.py, on Windows and macOS or where the
           setting computer.display_backend says vm), where the agent's applications run
           and it acts with that display's pointer and keyboard, never the user's; several
           run side by side, at most `displays` of them.

The app's conversations each take a
workspace from the WorkerPool when they begin and give it back when they end. A worker
whose conversation ended stays ready for the next one (SPARE of them), whose episode
resets it (a browser workspace gets a fresh context). The pool runs at most `workspaces`
workers: at the cap a new conversation takes the place of a free worker, else of a
conversation that waits for the user (the app ends the one that waited longest), else it
waits until one ends. Each worker is a process of its own: one that crashes or changes
kind leaves the others running. Standard library only.
"""

from contextlib import ExitStack
from collections.abc import Mapping
import itertools
import json
import math
import os
import re
import secrets
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import tomllib
from urllib.error import URLError

from harness_computer import desktop
from harness_computer.linux_workspace import worker_command
from harness_computer.managed import HostWorkspace
from harness_computer.desktop import display as displays
from harness.sdk import WorkerPipe, active_packages, approval, bench_spec, find, free_port, linux_sandbox, post_json, python_path

KINDS = {"browser": "browser", "desktop": "computer", "apps": "computer", "display": "computer"}
# Kinds that run only where this machine has what they need: what each is.
NEEDS = {"apps": "the user's applications, operated in the background", "display": "a display of its own"}
# The limits a pool runs under (the app's computer settings): workers at once, headless
# Chromes the browser workspaces share, isolated displays.
LIMITS = {"workspaces": 4, "chromes": 1, "displays": 2, "browser_windows": "off", "browser_display": "",
          "browser_area": "0,0,1920,1080"}
# Free workers kept ready for the next conversation.
SPARE = 1
# The environment variable that gives a browser worker the shared Chrome to attach to (an
# environment variable, unlike a command line, is readable by this user only).
CHROME_ENV = "HARNESS_CHROME"
# Browser windows shown (browser_windows "tiled" or "cascade"): the shared Chrome shows its
# windows (on the display browser_display names, else this computer's own), and each browser
# worker puts its window where it is given here, in browser_area: the rect "x,y,width,height"
# of its tile, or of its place in the cascade (LAYOUT_ENV says which).
WINDOW_ENV = "HARNESS_BROWSER_WINDOW"
LAYOUT_ENV = "HARNESS_BROWSER_LAYOUT"
# The ways browser windows show: tiles of a grid, or overlapping as a person leaves them.
LAYOUTS = ("tiled", "cascade")
HEADED_ENV = "HARNESS_CHROME_HEADED"
# A Chrome or Chromium executable background browsers use instead of the installed Google
# Chrome (a machine without one, such as a server with a virtual screen).
CHROME_PATH_ENV = "HARNESS_CHROME_PATH"


# A language tag (BCP 47, as browsers take it: en, en-US, zh-Hans-CN), or "system".
LOCALE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*")

def browser_locale(value) -> str:
    """A background browser's locale as written: "system" (also for empty), or a
    language tag; ValueError otherwise."""
    text = str(value if value is not None else "").strip() or "system"
    if text != "system" and not LOCALE.fullmatch(text):
        raise ValueError(f"{text!r} is not a language tag such as en-US (or system)")
    return text


def browser_area(value) -> str:
    """browser_area as written: four whole numbers x,y,width,height, the size above 0."""
    text = str(value if value is not None else "").replace(" ", "")
    parts = text.split(",")
    if len(parts) != 4 or not all(part.lstrip("-").isdigit() for part in parts) or int(parts[2]) <= 0 \
            or int(parts[3]) <= 0:
        raise ValueError(f"{value!r} is not x,y,width,height (e.g. 0,0,1920,1080)")
    return text


def tile(index: int, count: int, area) -> tuple:
    """The rect (x, y, width, height) of tile `index` of `count` tiles in `area` (x, y,
    width, height): a grid as square as it can be, filled row by row (1: the whole area, 2:
    side by side, 3 and 4: two by two, 5 and 6: three by two ...)."""
    count = max(1, int(count))
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    x, y, width, height = (int(value) for value in area)
    column, row = index % columns, (index // columns) % rows
    left, right = x + width * column // columns, x + width * (column + 1) // columns
    top, bottom = y + height * row // rows, y + height * (row + 1) // rows
    return left, top, right - left, bottom - top


def cascade(index: int, area) -> tuple:
    """The rect (x, y, width, height) of the `index`th window that opens in `area` (x, y,
    width, height) as a person's do: each a little lower and to the right of the one
    before, in one of a few sizes, overlapping the ones under it; past the bottom right it
    starts again from the top left, shifted. The first four stay in order, so each one's top
    left (where its agent's pointer rests) is left of the windows opened after it."""
    x, y, width, height = (int(value) for value in area)
    shares = ((0.58, 0.64), (0.5, 0.58), (0.62, 0.68), (0.54, 0.6))
    share_x, share_y = shares[index % len(shares)]
    w, h = int(width * share_x), int(height * share_y)
    margin_x, margin_y = width // 40, height // 30
    room_x, room_y = max(1, width - w - 2 * margin_x), max(1, height - h - 2 * margin_y)
    left = x + margin_x + (index * width // 8 + (index // 5) * width // 23) % room_x
    top = y + margin_y + (index * height // 10 + (index // 5) * height // 19) % room_y
    return left, top, w, h


def area_of(text) -> tuple:
    """browser_area "x,y,width,height" as numbers (ValueError when it is not)."""
    values = [int(part) for part in str(text).split(",")]
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise ValueError(f"browser_area is x,y,width,height, not {text!r}")
    return tuple(values)


from harness.sdk import Worker as BaseWorker, WorkerPool as BaseWorkerPool, WorkerCancelled as Cancelled


def check_kind(kind: str) -> str:
    missing = _missing(kind)
    if missing:
        raise ValueError(f"{kind} workspaces ({NEEDS[kind]}) are not available on this machine: {missing}")
    if kind in KINDS:
        return kind
    raise ValueError(f"a workspace is one of {', '.join(KINDS)}, not {kind!r}")


def available_kinds() -> list[str]:
    """The workspace kinds this machine serves."""
    return [kind for kind in KINDS if not _missing(kind)]


def _missing(kind: str) -> str:
    """Why this machine does not serve `kind` (empty when it does)."""
    if kind == "apps" and not desktop.available():
        return desktop.unavailable() or "it has no desktop backend"
    if kind == "display" and not displays.available():
        return displays.unavailable() or "it has no display server"
    return ""


def write_options(path: Path, options: dict) -> None:
    """A worker's options as the TOML file `harness serve --options` reads (unset (None)
    values left out)."""
    from harness.sdk import toml_dumps

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(toml_dumps(options), encoding="utf-8")


def environment_python(kind: str, log=print, installing=None) -> str:
    """The interpreter of `kind`'s bench environment (installed first when it is not; then
    `installing()` is called), or this one where environments are the project's."""
    from harness.sdk import environments
    from harness.sdk import bench_environment
    from harness.sdk import load_deploy

    environment = bench_environment(load_deploy(None), KINDS[check_kind(kind)])
    if environment is None:
        return sys.executable
    if environment.installed() is None:
        if installing is not None:
            installing()
        environments.install(environment, log=log)
    return str(environment.python)


def _stop_process(process, seconds=10.0) -> None:
    if process is None or process.poll() is not None:
        return
    if getattr(process, "stdin", None) is not None:
        process.stdin.close()
    process.terminate()
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


class Chrome:
    """One shared headless Chrome (benches/browser/chrome.py) and the workers attached to it."""

    def __init__(self, process, endpoint: str):
        self.process = process
        self.endpoint = endpoint
        self.users = set()
        # The environment it showed its windows with (tiled browser windows), or None.
        self.headed = None

    def alive(self) -> bool:
        return self.process.poll() is None

    def stop(self, seconds=10.0) -> None:
        # Its end of input closes the server and Chrome with it.
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        if self.process.stdout is not None:
            self.process.stdout.close()


class Chromes:
    """The headless Chromes browser workers share, at most `limit()` of them: a worker
    takes a Chrome nobody uses, else a new one while there are fewer than the limit, else
    the one with the fewest workers. A Chrome stops when its last worker detaches."""

    def __init__(self, logs: Path, limit=lambda: LIMITS["chromes"]):
        self.logs = Path(logs)
        self.limit = limit
        self._chromes = []
        self._lock = threading.Lock()

    def attach(self, user, python: str, seconds=60.0, headed: dict | None = None) -> str:
        """The endpoint of the Chrome `user` (a worker) is to use: one that shows its windows
        when `headed` (the environment it starts with: HEADED_ENV, DISPLAY), else a headless one."""
        with self._lock:
            live = [chrome for chrome in self._chromes if chrome.alive() and chrome.headed == (headed or None)]
            mine = next((chrome for chrome in live if user in chrome.users), None)
            if mine is not None:
                return mine.endpoint
            chrome = next((chrome for chrome in live if not chrome.users), None)
            if chrome is None and len(live) < max(1, int(self.limit())):
                chrome = self._start(python, seconds, headed)
                self._chromes.append(chrome)
            elif chrome is None:
                chrome = min(live, key=lambda item: len(item.users))
            chrome.users.add(user)
            return chrome.endpoint

    def alive(self, endpoint: str) -> bool:
        with self._lock:
            return any(chrome.endpoint == endpoint and chrome.alive() for chrome in self._chromes)

    def detach(self, user) -> None:
        stop = []
        with self._lock:
            for chrome in list(self._chromes):
                if user in chrome.users:
                    chrome.users.discard(user)
                    if not chrome.users:
                        self._chromes.remove(chrome)
                        stop.append(chrome)
        for chrome in stop:
            chrome.stop()

    def count(self) -> int:
        with self._lock:
            return sum(1 for chrome in self._chromes if chrome.alive())

    def close(self) -> None:
        with self._lock:
            chromes, self._chromes = self._chromes, []
        for chrome in chromes:
            chrome.stop()

    def _start(self, python: str, seconds: float, headed: dict | None = None) -> Chrome:
        self.logs.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONPATH": python_path(), "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
               **(headed or {})}
        with open(self.logs / "chrome.log", "ab") as log_file:
            process = subprocess.Popen([python, "-m", "benches.browser.chrome"], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=log_file, env=env)
        line = []
        reader = threading.Thread(target=lambda: line.append(process.stdout.readline()), daemon=True)
        reader.start()
        reader.join(seconds)
        chrome = Chrome(process, None)
        chrome.headed = headed or None
        try:
            chrome.endpoint = json.loads(line[0])["endpoint"]
        except (IndexError, ValueError, KeyError, TypeError):
            chrome.stop()
            raise RuntimeError(f"background Chrome did not start; see {self.logs / 'chrome.log'}") from None
        return chrome


class Worker(BaseWorker):
    def __init__(self, *args, reusable=True, **kwargs):
        super().__init__(*args, reusable=reusable, **kwargs)
        self._host_pipe = not reusable
        self._pipe = self._host_workspace = None
        self.chrome = self.tile = None

    def host_workspace(self, run):
        """Return the private workspace only to its current lease owner."""
        with self._approval_lock:
            if self.run == run and run is not None and self.status == "ready" and self.alive():
                return self._host_workspace
            return None

    def screen(self) -> bytes | None:
        """The workspace's screen now as JPEG bytes, while the worker runs."""
        from harness.sdk import decode_data_url

        if self.status != "ready":
            return None
        if self._host_pipe:
            return decode_data_url(self._host_workspace.call("preview")["image"])
        if self.endpoint is None:
            return None
        image = post_json(self.endpoint + "/rpc", {"method": "call", "arguments": {"name": "preview", "arguments": {}}},
                          timeout=10)["result"]["image"]
        return decode_data_url(image)



class WorkerPool(BaseWorkerPool):
    worker_class = Worker

    def __init__(self, logs, limits=None, launch=None):
        super().__init__(logs, limits or (lambda: dict(LIMITS)), launch)
        self.chromes = Chromes(self.logs, lambda: self.limits()["chromes"])

    def check_kind(self, kind):
        return check_kind(kind)

    def kind_limit(self, kind, limits):
        return int(limits.get("displays", LIMITS["displays"])) if kind == "display" else None

    def alive(self, worker):
        return worker.alive() and (worker.chrome is None or self.chromes.alive(worker.chrome))

    def acquire(self, run, kind, options=None, *, _host_pipe=False, **waiting):
        if _host_pipe and (run is None or kind not in ("desktop", "browser")):
            raise ValueError("A host-owned workspace needs a desktop or browser lease")
        return super().acquire(run, kind, options, reusable=not _host_pipe, **waiting)

    def screen(self, run=None) -> bytes | None:
        """The screen of `run`'s workspace, or of the one taken last."""
        worker = self.of(run) if run else max(
            (worker for worker in self.held() if worker.status == "ready"), key=lambda item: item.since, default=None)
        return worker.screen() if worker is not None else None

    def _acquire_host_workspace(self, run, kind, options=None, **waiting):
        """Private entry for a trusted scheduler. Never pass this lease into a kernel."""
        linux_sandbox.require_linux()
        options = {key: value for key, value in (options or {}).items()
                   if key in ("max_side", "step_limit", "locale")}
        if kind == "desktop":
            options.update(workspace="display", display_backend="local")
        worker = self.acquire(run, kind, options, _host_pipe=True, **waiting)
        workspace = worker.host_workspace(run)
        if workspace is None:
            self.release(run)
            raise RuntimeError("Could not acquire an authenticated managed workspace")
        return workspace

    def python(self, kind: str, log=print) -> str:
        """The interpreter of `kind`'s workers (and kernels), installed when it is not."""
        with self._changed:
            known = next((worker.python for worker in self.workers if worker.kind == kind and worker.python), None)
        return known or environment_python(kind, log)

    def close(self) -> None:
        with self._changed:
            workers, self.workers = self.workers, []
            self._changed.notify_all()
        for worker in workers:
            self._stop(worker)
        self.chromes.close()

    # Workers' processes.

    def _start(self, worker: Worker, log) -> None:
        try:
            self.launch(worker, log)
            if worker._host_pipe and (worker._host_workspace is None or worker.endpoint is not None):
                raise RuntimeError("A host-owned workspace requires verified private transport")
        except Exception as error:
            worker.status, worker.error = "error", f"{type(error).__name__}: {error}"
            self.error = worker.error
            with self._changed:
                if worker in self.workers:
                    self.workers.remove(worker)
                self._changed.notify_all()
            self._stop(worker)
            raise
        worker.status, self.error = "ready", None
        with self._changed:
            self._changed.notify_all()

    def _stop(self, worker: Worker) -> None:
        with worker._approval_lock:
            if worker.status in ("ready", "starting"):
                worker.status = "stopped"
        if worker._pipe is not None:
            worker._pipe.close()
        _stop_process(worker.process)
        if worker._pipe is not None:
            worker.process.stdout.close()
        if worker.chrome is not None:
            self.chromes.detach(worker.id)

    def _window(self, worker: Worker, env: dict) -> dict | None:
        """Browser windows shown: the free place `worker` takes (the lowest no other live
        browser worker has: a tile, or a place in the cascade) as WINDOW_ENV and LAYOUT_ENV in
        `env`, and the environment of a shared Chrome that shows its windows (DISPLAY:
        browser_display). None: headless."""
        limits = self.limits()
        layout = limits.get("browser_windows", "off")
        if layout not in LAYOUTS:
            return None
        count = max(1, int(limits["workspaces"]))
        with self._changed:
            taken = {other.tile for other in self.workers if other is not worker and other.kind == "browser"
                     and other.status in ("starting", "ready")}
            worker.tile = next(index for index in range(count + len(taken) + 1) if index not in taken)
        area = area_of(limits.get("browser_area") or LIMITS["browser_area"])
        rect = tile(worker.tile, count, area) if layout == "tiled" else cascade(worker.tile, area)
        env[WINDOW_ENV] = ",".join(str(value) for value in rect)
        env[LAYOUT_ENV] = layout
        display = limits.get("browser_display") or ""
        headed = {HEADED_ENV: "1", **({"DISPLAY": display} if display else {})}
        if display:
            env["DISPLAY"] = display
        return headed

    def _launch(self, worker: Worker, log) -> None:
        """Start `worker`'s process in its bench's environment (installed on first use) and
        wait until it answers."""

        def installing():
            self.installing = True

        try:
            worker.python = environment_python(worker.kind, log, installing)
        finally:
            self.installing = False
        env = {**os.environ, "PYTHONPATH": python_path(), "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        env = {name: value for name, value in env.items() if name.upper() != approval.WORKER_APPROVAL_KEY}
        if worker._host_pipe:
            env = {name: value for name, value in env.items() if name.upper() != "HARNESS_WORKER_TOKEN"}
        env.pop(CHROME_ENV, None)
        env.pop(WINDOW_ENV, None)
        env.pop(LAYOUT_ENV, None)
        if worker.kind == "browser" and not worker._host_pipe:
            headed = self._window(worker, env)
            worker.chrome = env[CHROME_ENV] = self.chromes.attach(worker.id, worker.python, headed=headed)
        port = None if worker._host_pipe else free_port()
        self.logs.mkdir(parents=True, exist_ok=True)
        # Its input is the pool's: it ends with this process even when it is not stopped.
        command = [worker.python, "-m", "harness.core.worker", "--factory",
                   bench_spec(KINDS[worker.kind]).factory,
                   "--exit-with-stdin", approval.APPROVAL_PIPE_FLAG]
        if port is not None:
            command += ["--port", str(port)]
        path = None
        if worker.options or not worker._host_pipe:
            path = self.logs.parent / "workspaces" / f"{worker.id}.toml"
            options = ({"strict_input": False, **worker.options}
                       if not worker._host_pipe and worker.kind in ("browser", "desktop", "apps", "display")
                       else worker.options)
            write_options(path, options)
            command += ["--options", str(path)]
        with ExitStack() as stack:
            if worker._host_pipe:
                needed = {"computer", worker.kind} - {"desktop"}
                roots = [package.path for package in active_packages() if package.name in needed]
                if len(roots) != len(needed):
                    raise RuntimeError("Managed worker packages are unavailable")
                tools = ({CHROME_PATH_ENV: env.get(CHROME_PATH_ENV)} if worker.kind == "browser"
                         else {name: env.get(name) for name in displays.OVERRIDES.values()})
                identity = (Path(stack.enter_context(TemporaryDirectory(prefix="display-id-", dir=self.logs)))
                            if worker.kind == "desktop" else None)
                command = worker_command(command, python=worker.python, packages=roots, options=path,
                                         executables=tools, desktop_identity=identity)
                env = {}
            with open(self.logs / f"workspace-{worker.id}.log", "ab") as log_file:
                stdout = subprocess.PIPE if worker._host_pipe else log_file
                stderr = log_file if worker._host_pipe else subprocess.STDOUT
                worker.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, env=env)
            if worker._host_pipe:
                key = secrets.token_hex(32)
                approval.write_approval_key(worker.process.stdin, key, host_pipe=True)
                worker._pipe = WorkerPipe(worker.process, key)
                description = worker._pipe.request("describe", {}, timeout=60)
                if description.get("host_pipe") is not True or description.get("managed_approval") is not True:
                    raise RuntimeError("The worker did not verify its private transport")
                worker._host_workspace = HostWorkspace(worker, worker._pipe)
                return
            worker.approval_key = secrets.token_hex(32)
            approval.write_approval_key(worker.process.stdin, worker.approval_key)
        worker.endpoint = f"http://127.0.0.1:{port}"
        token = env.get("HARNESS_WORKER_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._wait(worker, port, headers=headers)

    def _wait(self, worker: Worker, port: int, seconds=60.0, *, headers=None) -> dict:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if worker.process.poll() is not None:
                raise RuntimeError(f"the {worker.kind} worker exited ({worker.process.returncode}); see "
                                   f"{self.logs / f'workspace-{worker.id}.log'}")
            try:
                description = post_json(f"http://127.0.0.1:{port}/rpc", {"method": "describe", "arguments": {}},
                                        headers=headers, timeout=2).get("result")
                if isinstance(description, dict) and description:
                    return description
            except (URLError, OSError, ValueError):
                time.sleep(0.3)
        raise RuntimeError(f"the {worker.kind} worker did not answer within a minute")
