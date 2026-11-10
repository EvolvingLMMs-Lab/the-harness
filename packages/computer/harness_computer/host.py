"""What the computer package adds to the session host and its frontends (package.toml
[provides] host; harness/extensions.py): the workspaces conversations run in, this computer's line over the terminal chat's /settings, what an agent
waits for, screen recordings and screen areas, the Chromes a suite's background browsers
share."""

import os
from pathlib import Path
import re
import sys
import threading
from urllib.error import URLError

from harness.sdk import RemoteEnvironment, bench_spec, find, WorkspaceProvider, linux_sandbox
from harness_computer import screen_recording
from harness_computer.coordination import InputLock, WindowOwners
from harness_computer.desktop import display as displays
from harness_computer.desktop import permissions as desktop_permissions
from harness_computer.workspaces import (KINDS, LAYOUTS, Cancelled, Chromes, WorkerPool, area_of,  # noqa: F401
                                         available_kinds, check_kind)

# Sub-agents' colours, as the app's timeline gives their lanes (ui/static/timeline.js
# AGENT_COLORS): a1 the first, a2 the second ...
AGENT_COLORS = ("#2f6fdb", "#d9822b", "#2e9e6b", "#b8429a", "#7a5af8", "#c23b3b", "#1f9bb5", "#8a8a1e")


def agent_color(agent: str) -> str:
    """The colour of sub-agent `agent` (a1, a2 ...) on the timeline."""
    found = re.fullmatch(r"a(\d+)", agent)
    return AGENT_COLORS[(int(found.group(1)) - 1) % len(AGENT_COLORS)] if found else AGENT_COLORS[0]


class Workspaces(WorkspaceProvider):
    """The session host's workspaces (the app's, App): a pool of workers of this computer,
    one workspace per conversation or sub-agent, of a kind (KINDS: a background browser,
    this computer's desktop, its applications in the background, a display of their own),
    under the limits of the computer's settings."""

    Cancelled = Cancelled

    def __init__(self, directory, settings):
        self.directory = Path(directory)
        self.settings = settings
        self.pool = WorkerPool(self.directory / "logs", limits=self.limits)

    def builtin_skills(self, kind):
        return ("desktop", *self.extra_skills(kind))

    def extra_skills(self, kind):
        kind = self.kind(kind)
        return ("screens", "browser" if kind == "browser" else "physical",
                *(("windowtools",) if kind in ("apps", "display", "browser") else ()))

    def validate_managed(self, kind):
        linux_sandbox.require_linux()
        if kind not in ("desktop", "browser"):
            raise ValueError("A managed workspace requires desktop or browser")

    def acquire_managed(self, run, kind, **waiting):
        self.validate_managed(kind)
        return self.pool._acquire_host_workspace(run, kind, self.options(kind), **waiting)

    def kinds(self) -> tuple:
        """The workspace kinds this computer serves."""
        return tuple(available_kinds())

    def kind(self, requested: str | None = None, text: str | None = None) -> str:
        """The computer kind `requested`, else ("auto" or none) the preselected one:
        computer.mode. Each new conversation chooses where it works (the session host's
        session.environment); this is what that choice highlights before there is a last
        one, and the kind of what is asked without a conversation (the skills listed, the
        workspace warmed up). The task's words do not choose it (`text` is not read)."""
        if requested in (None, "auto"):
            requested = self.settings.get()["computer"]["mode"]
            if requested not in self.kinds():
                requested = self.kinds()[0]
        return check_kind(requested)

    def describe(self, kind):
        from .first_use import KINDS as ABOUT

        label, about = ABOUT[kind]
        return {"label": label, "about": about, "views": True,
                **({"physical": True} if kind in ("desktop", "apps") else {})}

    def require_choices(self, kind, runtime=None):
        from .first_use import for_workspace

        for_workspace(self.settings, kind, runtime)

    def bench(self, kind: str) -> str:
        """The bench that serves a workspace of `kind` (its package is installed first)."""
        return KINDS[self.kind(kind)]

    def limits(self) -> dict:
        """The pool's limits, from the computer's settings."""
        computer = self.settings.get()["computer"]
        return {"workspaces": computer["workspaces"], "chromes": computer["chromes"],
                "displays": computer["displays"], "browser_windows": computer["browser_windows"],
                "browser_display": computer["browser_display"], "browser_area": computer["browser_area"]}

    def presentation(self):
        return {"computer": self.status()}

    def status(self) -> dict:
        """This computer as the pages show it: the pool, its workspaces and limits, the kinds it
        serves, the system's permissions and what display workspaces still need."""
        computer = self.settings.get()["computer"]
        return {"status": self.pool.status(), "error": self.pool.error, "mode": computer["mode"],
                "workspaces": self.pool.describe(), "limits": self.limits(), "kinds": available_kinds(),
                "permissions": desktop_permissions(), "display": displays.unavailable(settings=computer)}

    def tree(self, tree: dict, kind: str) -> dict:
        """The assistant's configuration for a workspace of `kind`: a background browser's has the
        browser's prompt, its main model only and the core's session."""
        tree["bench"] = self.bench(kind)
        agent = tree["overrides"]["agent"]
        agent["prompt"]["desktop"] = str(find("prompts/computer")[0])
        agent["desktop"] = {"skills": {"enable": ["checklist"]}, "runtime": {
            "contract": "native", "max_history_turns": 10, "think_while_acting": "on_events"}}
        if self.kind(kind) == "desktop":
            agent["desktop"]["skills"]["disable"] = ["windowtools", "browser"]
        if self.kind(kind) == "browser":
            tree["bench"] = "browser"
            agent = tree["overrides"]["agent"]
            agent["prompt"]["desktop"] = str(find("prompts/browser")[0])
            desktop = agent.setdefault("desktop", {})
            desktop["roles"] = ["main"]
            desktop["runtime"] = {**desktop.get("runtime", {}),
                                  "bootstrap": "harness.runtime.execution.session:create_session", "verifier": False}
        return tree

    def options(self, kind: str | None = None) -> dict:
        """The computer's settings, as a worker of `kind` takes them (only those changed from
        the worker's defaults)."""
        computer = self.settings.get()["computer"]
        kind = self.kind(kind)
        defaults = {"monitor": 1, "max_side": 1920, "step_limit": 300}
        options = {key: computer[key] for key in defaults if computer[key] != defaults[key]}
        if kind == "browser":
            options.pop("monitor", None)
            if computer["browser_locale"] != "system":
                options["locale"] = computer["browser_locale"]
        else:
            # The physical-input policy of these settings, and the locks of this computer.
            options["physical"] = {"data": str(self.directory)}
        if kind in ("apps", "display"):
            options["workspace"] = kind
        if kind == "display":
            # A display server, or a virtual machine of these settings (desktop/vm.py).
            from harness_computer.desktop.vm import SETTINGS

            options["display_backend"] = computer["display_backend"]
            options["vm"] = {key: computer[key] for key in SETTINGS if key.startswith("vm_")}
        return options

    def acquire(self, run: str, kind: str, log, evict=None, cancelled=None, options=None):
        """A worker of `kind` for `run` (its endpoint and python), waiting for one when the
        pool is full; `evict(runs)` may end another conversation to make room."""
        worker = self.pool.acquire(run, kind, {**self.options(kind), **(options or {})}, log=log, evict=evict, cancelled=cancelled)
        self._name_pointer(worker, run, kind)
        return worker

    def _name_pointer(self, worker, run: str, kind: str) -> None:
        """Browser windows shown: the sub-agent `run` is (SESSION/a1) shows its pointer in its
        window with its name, in its lane's colour on the timeline; another run, none."""
        if kind != "browser" or self.settings.get()["computer"]["browser_windows"] not in LAYOUTS:
            return
        agent = re.search(r"/(a\d+)$", str(run))
        named = {"label": agent.group(1), "color": agent_color(agent.group(1))} if agent else {}
        # An environment's own method goes through the worker's `call` (core/worker.py).
        try:
            RemoteEnvironment(worker.endpoint, timeout=5, approval_key=getattr(worker, "approval_key", None)).call(
                "pointer", **named)
        except (URLError, OSError, ValueError, RuntimeError):
            pass  # it works on, its pointer unnamed

    def release(self, run: str) -> None:
        self.pool.release(run)

    def of(self, run: str):
        return self.pool.of(run)

    def screen(self, run: str | None):
        """The screen of `run`'s workspace now (JPEG bytes), or None."""
        return self.pool.screen(run)

    def restart(self) -> int:
        """Stop the workspaces no conversation uses and start one again with the computer's
        settings; those in use run on until their conversations end. How many are in use."""
        used = self.pool.stop_free()
        kind = self.kind()

        def warm():
            try:
                self.pool.warm(kind, self.options(kind), log=lambda message: None)
            except Exception:
                pass  # the error is the pool's, for the page

        threading.Thread(target=warm, name="workspace-warm", daemon=True).start()
        return used

    def record(self, directory: Path, kind: str, trace):
        """The screen's recording for a conversation in `directory` (screen_recording.py),
        when record_screen is on: for a browser, where its windows show (tiled, cascade), the
        area they open in on their display; for a desktop, its whole screen with the
        pointer (on Linux, the X display it is on). None: nothing to record (or ffmpeg is
        missing, which the trace says)."""
        computer = self.settings.get()["computer"]
        if computer["record_screen"] != "on":
            return None
        if kind == "browser" and computer["browser_windows"] in LAYOUTS:
            where = {"display": computer["browser_display"] or None, "area": area_of(computer["browser_area"])}
        elif kind == "desktop" and (sys.platform == "win32" or os.environ.get("DISPLAY")):
            where = {"display": os.environ.get("DISPLAY") if sys.platform != "win32" else None, "pointer": True}
        else:
            return None
        try:
            recording = screen_recording.Recording(directory, **where)
        except (RuntimeError, OSError, ValueError) as error:
            trace.emit("screen_recording", error=str(error))
            return None
        trace.emit("screen_recording", **recording.info)
        return recording

    def windows(self):
        """Who owns which window of this computer (share hands a parent's windows to a
        sub-agent, runtime/task/delegation.py)."""
        return WindowOwners(self.directory / "locks")

    def close(self) -> None:
        self.pool.close()


def note(values: dict) -> str:
    """Where display workspaces run, and what they still need (the terminal chat's /settings)."""
    computer = values["computer"]
    where = displays.route(computer.get("display_backend"))
    missing = displays.unavailable(settings=computer)
    place = f"a virtual machine ({computer.get('vm_image') or 'no image yet'})" if where == "vm" \
        else "a display server of this computer"
    return f"Display workspaces run on {place} (computer.display_backend){': ' + missing if missing else ''}."


def waiting(owner: dict) -> str | None:
    """What an agent of a session waits for: the input lock, behind whom."""
    return InputLock().waiting(owner)


def recording(directory: Path) -> dict | None:
    """A run's screen recording (screen.json beside its trace): {"path", "start", "stop", "area"}."""
    return screen_recording.find(directory)


def areas(text: str) -> tuple:
    """A screen area "x,y,width,height" as numbers (ValueError when it is not)."""
    return area_of(text)
