"""What runs beside a bot body, started and stopped as one (harness minebot up | status |
down, the runs, the minebot workspace):

    bridge    the body's bridge (body/bridge.js on Node), which holds the body's process;
              the body joins the game server the settings name
    window    where the settings say so: your own game window, which joins the bridge's
              view port and shows what the body sees (window.py)
    capture   the one capture of that window: the frames the body's eyes read (capture.py)
    worker    the harness worker of the body (benches/mineflayer)

No game server is started, stopped or changed here: the body joins one that is there. Every
process started is recorded (state/<part>.json under the package's data folder), and only
what is recorded is stopped.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

from harness.sdk import bench_environment, environments, load_deploy, pid_alive, python_path, start_detached, toml_dumps

from . import ping, provision, window as windows
from .config import BODY, data_dir, rcon


PARTS = ("run", "worker", "capture", "window", "launcher", "bridge")   # the order they are stopped in
FACTORY = "benches.mineflayer.runtime:create_environment"
QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def state_dir() -> Path:
    return data_dir() / "state"


def logs_dir() -> Path:
    return data_dir() / "logs"


def frames_dir() -> Path:
    return data_dir() / "frames"


def get(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except Exception:
        return None


def post(url, body, timeout=10):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def bridge(values) -> str:
    return f"http://127.0.0.1:{values['bridge_port']}"


def endpoint(values) -> str:
    return f"http://127.0.0.1:{values['worker_port']}"


def rpc(values, name, **arguments):
    """A call of the body's worker, or None when it does not answer."""
    try:
        return post(endpoint(values) + "/rpc", {"method": "call", "arguments": {"name": name, "arguments": arguments}},
                    timeout=4).get("result")
    except Exception:
        return None


# -- the processes this package started -----------------------------------------------------

def record(part: str) -> dict | None:
    try:
        return json.loads((state_dir() / f"{part}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def remember(part: str, pid: int, **more) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / f"{part}.json").write_text(json.dumps({"pid": int(pid), "started": time.time(), **more}), encoding="utf-8")


def alive(part: str) -> bool:
    kept = record(part)
    return bool(kept) and pid_alive(kept["pid"])


def start(part: str, command, *, log: str, env=None, cwd=None) -> int:
    """Start `command` as the part `part`, in a process group of its own, its output appended to logs/<log>."""
    logs_dir().mkdir(parents=True, exist_ok=True)
    process = start_detached([str(item) for item in command], log=logs_dir() / log, env=env, cwd=cwd)
    remember(part, process.pid)
    return process.pid


def end(pid: int, seconds: float = 10.0) -> None:
    """End the process `pid` and what it started."""
    if not pid_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, **QUIET)
    else:
        for how in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pid, how)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(pid, how)
                except ProcessLookupError:
                    return
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline and pid_alive(pid, reap=True):
                time.sleep(0.2)
            if not pid_alive(pid, reap=True):
                return


def stop(part: str, log=print) -> bool:
    """Stop the part `part` when this package started it; whether there was one."""
    kept = record(part)
    if kept is None:
        return False
    if pid_alive(kept["pid"]):
        end(kept["pid"])
        log(f"stopped {part} (process {kept['pid']})")
    (state_dir() / f"{part}.json").unlink(missing_ok=True)
    return True


def down(log=print) -> None:
    """Stop everything this package started, and drop the frames of the session that is over."""
    for part in PARTS:
        stop(part, log)
    for path in frames_dir().glob("*.jpg"):   # nobody's eyes any more
        try:
            path.unlink()
        except OSError:
            pass


# -- up --------------------------------------------------------------------------------------

def listening(port: int) -> bool:
    """Whether something accepts connections on this computer's `port`."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def free_ports(values) -> None:
    """The local ports the body's own processes take are free (this package's parts are stopped by now):
    RuntimeError names the one that something else has, and the setting that moves it."""
    wanted = ["bridge_port", "worker_port", *(["view_port"] if values["window"] == "on" else [])]
    for key in wanted:
        if listening(values[key]):
            raise RuntimeError(f"the local port {values[key]} is in use by something else on this computer: give the body "
                               f"another (the setting minebot.{key})")

def wait(check, seconds, what, log=print) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(1)
    log(f"did not come up: {what}")
    return False


def game_version(values) -> str:
    """The version the body speaks: the setting's, else what the server says of itself."""
    if values["version"]:
        return values["version"]
    found = ping.game_version(ping.status(values["host"], values["port"]))
    if not found:
        raise RuntimeError(f"no game server answers at {values['host']}:{values['port']} to say its version: start it, or "
                           "give the version (the setting minebot.version)")
    return found


def worker_python(log=print) -> str:
    """The interpreter of the body's worker: its bench's environment, installed on first use."""
    environment = bench_environment(load_deploy(None), "mineflayer")
    if environment is None:
        return sys.executable
    if environment.installed() is None:
        environments.install(environment, log=log)
    return str(environment.python)


def worker_options(values, *, instruction=None, more=None) -> dict:
    """The options of the body's worker for these settings (a run adds its own with `more`)."""
    from .config import command

    options = {"bridge": bridge(values), "player": values["username"], "frames": str(frames_dir())}
    if instruction:
        options["instruction"] = instruction
    for key in ("start_over", "keep_start", "kept_info"):
        parts = command(values[key])
        if parts:
            options[key] = parts
    return {**options, **(more or {})}


def bridge_environment(values, version, *, store: Path, events_log=None) -> dict:
    return {**os.environ, "BRIDGE_PORT": str(values["bridge_port"]), "BRIDGE_STORE": str(store),
            "MC_HOST": values["host"], "MC_PORT": str(values["port"]), "MC_VERSION": version, "MC_USER": values["username"],
            "MC_AUTH": values["auth"], "MC_PROFILES": str(data_dir() / "profiles"), "NODE_PATH": provision.node_path(),
            **({"VIEW_PORT": str(values["view_port"])} if values["window"] == "on" else {}),
            **({"BRIDGE_EVENTS_LOG": str(events_log)} if events_log else {}),
            **({"MINEBOT_DIG_RULES": values["dig_rules"]} if values["dig_rules"] else {}),
            **rcon(values)}


def up(values, *, store: Path, options: dict, events_log=None, log=print) -> bool:
    """Bring the parts up from nothing (what this package started before is stopped first):
    the bridge, the game window where the settings ask for one, its capture, the worker.
    `store`: where the body keeps its routines; `options`: the worker's. Returns status()."""
    down(log=lambda message: None)
    provision.ensure(log)
    window = values["window"] == "on"
    if window:
        windows.check(values)
    free_ports(values)
    version = game_version(values)
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    start("bridge", [provision.node(), BODY / "bridge.js"], log="bridge.log", cwd=BODY,
          env=bridge_environment(values, version, store=store, events_log=events_log))
    if not wait(lambda: get(bridge(values) + "/state") is not None, 30, "the bridge", log):
        return False
    if window:
        # The window joins the view port; the bridge lets the body log in once it is there.
        started = windows.launch(values, log)
        if started.get("game"):
            remember("window", started["game"])
        if started.get("launcher"):
            # (The launcher process this start made: where yours was open already, it handed over and ended.)
            remember("launcher", started["launcher"])
    answers = bool((get(bridge(values) + "/server", timeout=5) or {}).get("answers"))
    if answers:
        told = set()

        def joined():
            # (Signing in with an account: the body says where, and with which code.)
            asked = (get(bridge(values) + "/events?after=0&kinds=sign_in&limit=5") or {}).get("events") or []
            for event in asked:
                if event["seq"] not in told:
                    told.add(event["seq"])
                    log(f"sign in to join: open {event.get('uri')} and enter the code {event.get('code')}")
            return bool((get(bridge(values) + "/state") or {}).get("connected"))
        wait(joined, 300 if values["auth"] == "microsoft" else 60, "the body in the world", log)
    python = worker_python(log)
    if window:
        frames_dir().mkdir(parents=True, exist_ok=True)
        start("capture", [python, "-m", "harness_minebot.capture", values["window_title"], frames_dir()], log="capture.log",
              env={**os.environ, "PYTHONPATH": python_path()})
        if answers:
            wait(lambda: (newest_frame_age() or 99) < 2, 20, "the capture of the game window", log)
    state_dir().mkdir(parents=True, exist_ok=True)
    file = state_dir() / "worker.toml"
    file.write_text(toml_dumps(options), encoding="utf-8")
    start("worker", [python, "-m", "harness.core.worker", "--factory", FACTORY, "--port", values["worker_port"],
                     "--options", file], log="worker.log",
          env={**os.environ, "PYTHONPATH": python_path(), "PYTHONUTF8": "1", "MINEFLAYER_FRAMES": str(frames_dir())})
    wait(lambda: (rpc(values, "profile") or {}).get("kind") == "botbody", 60, "the worker", log)
    return status(values, log)


def newest_frame_age():
    times = []
    for path in frames_dir().glob("*.jpg"):
        try:
            times.append(path.stat().st_mtime)
        except OSError:   # the reader removes old frames as it goes
            pass
    return time.time() - max(times) if times else None


def rows(values) -> dict:
    """Each part and whether it is up, for these settings."""
    body = get(bridge(values) + "/state") or {}
    answers = (bool((get(bridge(values) + "/server", timeout=5) or {}).get("answers")) if body
               else ping.status(values["host"], values["port"], timeout=2) is not None)
    found = {"bridge": bool(body)}
    if answers:
        found["the body in the world"] = bool(body.get("connected"))
    else:
        found[f"no game server answers at {values['host']}:{values['port']}: the body waits for one"] = bool(body)
    if values["window"] == "on":
        view = body.get("window") or {}
        age = newest_frame_age()
        if answers:
            found["window on the body"] = bool(view.get("joined") and view.get("attached"))
            found["capture"] = alive("capture") and age is not None and age < 2
        else:
            found["window at the bridge"] = bool(view.get("joined"))
            found["capture running"] = alive("capture")
    found["worker"] = (rpc(values, "profile") or {}).get("kind") == "botbody"
    return found


def status(values, log=print) -> bool:
    found = rows(values)
    for name, ok in found.items():
        log(f"{'ok  ' if ok else 'DOWN'} {name}")
    body = get(bridge(values) + "/state") or {}
    if body:
        log("body: " + json.dumps({key: body.get(key) for key in ("version", "dimension", "position", "health", "deaths")})
            + f", routines: {len(body.get('skills', []))}")
    return all(found.values())
