"""A display of a workspace's own (the display workspace, on Linux): an X display nobody
else sees or uses, where the agent's applications run and its input goes (XTest), never
the user's screen, mouse or keyboard.

The display server is Xvfb when it is installed, else a headless weston (the nested
compositor) with Xwayland on it, full screen; either serves an X display :N on a number
no other display uses (from 100 up). Beside it run a D-Bus session bus of the display's
own and the accessibility bus (at-spi-bus-launcher, which puts the bus's address on the
display's root window), so the applications' accessibility trees are read there
(desktop/atspi.py); without at-spi2-core the display works, without trees.

A guard process owns them (`python -m harness_computer.desktop.display`): it starts them in a
process group of its own, prints the display's name and environment, and ends the group
when its standard input closes: when the Display is closed, and when the worker that made
it ends in any way. Standard library only.

    display = Display((1280, 800)).start()
    display.name        ":101"
    display.env         {"DISPLAY": ":101", "DBUS_SESSION_BUS_ADDRESS": ...}
    display.close()
"""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

# Where at-spi-bus-launcher is installed (Debian/Ubuntu, Fedora, Arch, openSUSE).
LAUNCHERS = ("/usr/libexec/at-spi-bus-launcher", "/usr/lib/at-spi2-core/at-spi-bus-launcher",
             "/usr/lib/at-spi2/at-spi-bus-launcher", "/usr/lib64/at-spi2-core/at-spi-bus-launcher",
             "/usr/lib/at-spi-bus-launcher")
# Programs found on PATH unless these variables name them ($HARNESS_DISPLAY_SERVER: xvfb or
# weston picks the server).
OVERRIDES = {"xvfb": "HARNESS_XVFB", "weston": "HARNESS_WESTON", "xwayland": "HARNESS_XWAYLAND",
             "dbus": "HARNESS_DBUS_DAEMON", "atspi": "HARNESS_ATSPI_LAUNCHER"}
FIRST_NUMBER = 100
START_SECONDS = 20.0
INSTALL = ("a display workspace needs Xvfb (Debian/Ubuntu: sudo apt install xvfb; Fedora: sudo dnf install "
           "xorg-x11-server-Xvfb; Arch: sudo pacman -S xorg-server-xvfb), or weston with Xwayland")


def programs() -> dict:
    """The programs a display uses that this machine has: xvfb, weston, xwayland, dbus
    (dbus-daemon), atspi (at-spi-bus-launcher); None where missing."""
    found = {}
    for key, names in (("xvfb", ("Xvfb",)), ("weston", ("weston",)), ("xwayland", ("Xwayland",)),
                       ("dbus", ("dbus-daemon",))):
        given = os.environ.get(OVERRIDES[key])
        found[key] = given if given and Path(given).is_file() else next(
            (path for path in (shutil.which(name) for name in names) if path), None)
    given = os.environ.get(OVERRIDES["atspi"])
    found["atspi"] = given if given and Path(given).is_file() else next(
        (path for path in LAUNCHERS if Path(path).is_file()), None)
    return found


def server(found: dict | None = None) -> str | None:
    """The display server this machine runs: "xvfb", "weston" (with Xwayland), or None;
    $HARNESS_DISPLAY_SERVER picks one of them."""
    found = programs() if found is None else found
    wanted = os.environ.get("HARNESS_DISPLAY_SERVER")
    if wanted == "xvfb":
        return "xvfb" if found.get("xvfb") else None
    if wanted == "weston":
        return "weston" if found.get("weston") and found.get("xwayland") else None
    if found.get("xvfb"):
        return "xvfb"
    if found.get("weston") and found.get("xwayland"):
        return "weston"
    return None


def route(choice: str | None = None, system: str | None = None) -> str:
    """Where display workspaces run: "local" (a display server on this computer: Linux) or
    "vm" (a virtual machine of their own, desktop/vm.py). `choice` is the setting
    computer.display_backend (auto: local on Linux, a VM on Windows and macOS)."""
    system = system or sys.platform
    if choice in ("local", "vm"):
        return choice
    return "local" if system.startswith("linux") else "vm"


def available(system: str | None = None, settings: dict | None = None) -> bool:
    """Whether display workspaces run here: Linux with Xvfb, or weston and Xwayland; or a
    virtual machine (desktop/vm.py), as the computer's settings choose."""
    return not unavailable(system, settings)


def unavailable(system: str | None = None, settings: dict | None = None) -> str:
    """Why display workspaces do not run here (empty when they do), with what to install or
    set. `settings` are the computer's (default: the app's)."""
    from . import vm

    system = system or sys.platform
    settings = vm.options(settings)
    if route(settings.get("display_backend"), system) == "vm":
        return vm.unavailable(settings, system)
    if not system.startswith("linux"):
        return "a display server of this computer's own runs on Linux only: set computer.display_backend to vm " \
               "(or auto) for a virtual machine"
    return "" if server() is not None else INSTALL


def free_number(first: int = FIRST_NUMBER) -> int:
    """A display number no X server uses (its socket and lock file are free)."""
    for number in range(first, first + 900):
        if not Path(f"/tmp/.X11-unix/X{number}").exists() and not Path(f"/tmp/.X{number}-lock").exists():
            return number
    raise RuntimeError("no free X display number from :100 to :999")


class Display:
    """A display of a workspace's own (see the module's text)."""

    def __init__(self, size=(1280, 800), directory=None):
        self.size = (int(size[0]), int(size[1]))
        self.directory = Path(directory) if directory else None
        self.name = None
        self.env = {}
        self.server = None
        self.accessibility = None
        self._guard = None

    def start(self, timeout: float = START_SECONDS):
        if not sys.platform.startswith("linux"):
            raise RuntimeError(unavailable())
        found = programs()
        kind = server(found)
        if kind is None:
            raise RuntimeError(INSTALL)
        directory = self.directory or Path(tempfile.mkdtemp(prefix="harness-display-"))
        directory.mkdir(parents=True, exist_ok=True)
        request = {"server": kind, "programs": found, "size": list(self.size), "directory": str(directory)}
        self._guard = subprocess.Popen([sys.executable, "-m", "harness_computer.desktop.display", json.dumps(request)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       start_new_session=True, env={**os.environ, "PYTHONPATH": _python_path()})
        line = _read_line(self._guard.stdout, timeout)
        if not line:
            self.close()
            raise RuntimeError(f"the display did not start within {timeout:g} s ({kind}; see {directory})")
        answer = json.loads(line)
        if answer.get("error"):
            self.close()
            raise RuntimeError(f"the display did not start: {answer['error']}")
        self.name, self.env, self.server = answer["display"], answer["env"], kind
        self.accessibility = answer.get("accessibility")
        return self

    def close(self) -> None:
        guard, self._guard = self._guard, None
        if guard is None:
            return
        for stream in (guard.stdin, guard.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            guard.wait(5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(guard.pid, signal.SIGKILL)
        except OSError:
            pass
        guard.wait()

    def describe(self) -> dict:
        return {"display": self.name, "server": self.server, "size": list(self.size),
                "accessibility": bool(self.accessibility)}

    def __enter__(self):
        return self.start() if self._guard is None else self

    def __exit__(self, *_):
        self.close()


def _python_path() -> str:
    """The harness and its packages first (this one among them), so the guard imports this
    harness."""
    from harness.sdk import python_path

    return python_path(os.environ.get("PYTHONPATH"))


def _read_line(stream, timeout) -> str:
    import selectors

    selector = selectors.DefaultSelector()
    selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    data = b""
    while b"\n" not in data:
        left = deadline - time.monotonic()
        if left <= 0 or not selector.select(left):
            return ""
        chunk = os.read(stream.fileno(), 4096)
        if not chunk:
            return ""
        data += chunk
    return data.split(b"\n", 1)[0].decode("utf-8")


# -- the guard ----------------------------------------------------------------------------


def _guard(request: dict) -> int:
    """Start the display, its session bus and accessibility bus in this process group;
    print {"display", "env", "accessibility"}; end them all when stdin closes."""
    found, directory = request["programs"], Path(request["directory"])
    width, height = request["size"]
    children = []

    def end(*_):
        for process in children:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
        deadline = time.monotonic() + 2.0
        for process in children:
            try:
                process.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        try:
            os.killpg(0, signal.SIGKILL)
        except OSError:
            pass
        os._exit(0)

    signal.signal(signal.SIGTERM, end)
    signal.signal(signal.SIGHUP, end)

    def log(name):
        return open(directory / f"{name}.log", "ab")

    def run(argv, env=None, **options):
        process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, **options)
        children.append(process)
        return process

    try:
        env = {key: value for key, value in os.environ.items() if key not in ("WAYLAND_DISPLAY", "DISPLAY")}
        number = None
        for attempt in range(8):
            number = free_number(FIRST_NUMBER + attempt * 3 if attempt else FIRST_NUMBER)
            if request["server"] == "xvfb":
                started = run([found["xvfb"], f":{number}", "-screen", "0", f"{width}x{height}x24", "-nolisten", "tcp",
                               "-noreset", "+extension", "Composite"], env=env, stdout=log("xvfb"), stderr=log("xvfb"))
            else:
                runtime = directory / "runtime"
                runtime.mkdir(mode=0o700, exist_ok=True)
                env["XDG_RUNTIME_DIR"] = str(runtime)
                socket = f"harness-{number}"
                (directory / "weston.ini").write_text("[core]\nidle-time=0\n", encoding="utf-8")
                run([found["weston"], "--backend=headless-backend.so", "--use-pixman", f"--width={width}",
                     f"--height={height}", f"--socket={socket}", "--shell=kiosk-shell.so",
                     f"--config={directory / 'weston.ini'}", f"--log={directory / 'weston.log'}"], env=env,
                    stdout=log("weston"), stderr=log("weston"))
                if not _wait(lambda: (runtime / socket).exists(), 10):
                    raise RuntimeError(f"weston did not start (see {directory / 'weston.log'})")
                started = run([found["xwayland"], f":{number}", "-noreset", "-nolisten", "tcp", "-shm"],
                              env={**env, "WAYLAND_DISPLAY": socket}, stdout=log("xwayland"), stderr=log("xwayland"))
            if _wait(lambda: Path(f"/tmp/.X11-unix/X{number}").exists() or started.poll() is not None, 10) and \
                    started.poll() is None:
                break
            number = None
        if number is None:
            raise RuntimeError(f"the X server did not start (see {directory})")
        display = f":{number}"
        env["DISPLAY"] = display
        # The display's applications never reach the user's session bus (nor start the
        # user's accessibility services there): a bus of the display's own, or none.
        shown = {"DISPLAY": display, "DBUS_SESSION_BUS_ADDRESS": "disabled:"}
        env["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
        accessibility = None
        if found.get("dbus"):
            bus = run([found["dbus"], "--session", "--nofork", "--print-address=1"], env=env, stdout=subprocess.PIPE,
                      stderr=log("dbus"))
            address = _read_line(bus.stdout, 10).strip()
            if address:
                env["DBUS_SESSION_BUS_ADDRESS"] = shown["DBUS_SESSION_BUS_ADDRESS"] = address
                if found.get("atspi"):
                    run([found["atspi"], "--launch-immediately"], env=env, stdout=log("atspi"), stderr=log("atspi"))
                    accessibility = _root_property(display, "AT_SPI_BUS", 10)
                    if accessibility:
                        shown["AT_SPI_BUS_ADDRESS"] = accessibility
        print(json.dumps({"display": display, "env": shown, "accessibility": accessibility}), flush=True)
    except Exception as error:
        print(json.dumps({"error": str(error)}), flush=True)
        end()
    while True:
        try:
            if not os.read(0, 4096):
                break
        except InterruptedError:
            continue
        except OSError:
            break
    end()
    return 0


def _wait(predicate, seconds) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _root_property(display, name, seconds):
    """A string property of the display's root window, once it is set (python-xlib when
    this Python has it, else xprop)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = None
        try:
            from Xlib import X, display as xdisplay

            connection = xdisplay.Display(display)
            try:
                found = connection.screen().root.get_full_property(connection.intern_atom(name), X.AnyPropertyType)
                value = found.value.decode("utf-8") if found is not None else None
            finally:
                connection.close()
        except ImportError:
            try:
                text = subprocess.run(["xprop", "-display", display, "-root", name], capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=3).stdout
                value = text.split("=", 1)[1].strip().strip('"') if "=" in text else None
            except (OSError, subprocess.SubprocessError):
                return None
        except Exception:
            value = None
        if value:
            return value
        time.sleep(0.1)
    return None


if __name__ == "__main__":
    sys.exit(_guard(json.loads(sys.argv[1])))
