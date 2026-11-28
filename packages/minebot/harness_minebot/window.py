"""The game window of a bot body: your own game, started by your own launcher, in a launcher
instance of its own that holds one mod of this package (window/: its source and its jar).
The mod joins the bridge's view port once the game has loaded; the client is then sent what
the body is sent, and what it shows is what the body sees.

Nothing of the game comes with this package: the instance is a copy of one of yours.

    setup(...)    make that instance from an instance of yours (Fabric Loader, game version
                  1.16.1): copied without its worlds and its mods, with the window mod and
                  the address of the view port
    check(...)    whether a window can be started with these settings; RuntimeError says why not
    launch(...)   start it and take it out of the foreground (Windows)
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .config import WINDOW


MOD = WINDOW / "libs" / "harness-camera-0.1.0.jar"
GAME_VERSION = "1.16.1"
NOT_COPIED = ("saves", "logs", "crash-reports", "screenshots", "mods", "replay_recordings")
QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def instances_dir(launcher: str, given=None) -> Path:
    """Where the launcher keeps its instances: `given`, else beside the launcher's program (a
    portable install), else the launcher's own data folder for this user."""
    if given:
        return Path(given).expanduser()
    beside = Path(launcher).expanduser().parent / "instances"
    if beside.is_dir():
        return beside
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", "")) / "PrismLauncher" / "instances"
    home = Path.home()
    mac = home / "Library" / "Application Support" / "PrismLauncher" / "instances"
    return mac if mac.is_dir() else home / ".local" / "share" / "PrismLauncher" / "instances"


def game_folder(instance: Path) -> Path:
    for name in (".minecraft", "minecraft"):
        if (instance / name).is_dir():
            return instance / name
    return instance / ".minecraft"


def setup(*, launcher: str, source: str, instance: str, view_port: int, instances=None, log=print) -> Path:
    """Make the instance `instance` from your instance `source`; returns its folder."""
    if not Path(launcher).expanduser().is_file():
        raise RuntimeError(f"no launcher at {launcher}: give your launcher's program")
    root = instances_dir(launcher, instances)
    origin, target = root / source, root / instance
    if not (origin / "instance.cfg").is_file():
        raise RuntimeError(f"no instance {source!r} in {root}: name an instance of yours that has Fabric Loader and "
                           f"the game version {GAME_VERSION}")
    if source == instance:
        raise RuntimeError("the window's instance is one of its own: give another name than the instance it is made from")
    pack = origin / "mmc-pack.json"
    described = pack.read_text(encoding="utf-8", errors="replace") if pack.is_file() else ""
    if "net.fabricmc.fabric-loader" not in described or f'"{GAME_VERSION}"' not in described:
        raise RuntimeError(f"the instance {source!r} is not Fabric Loader on the game version {GAME_VERSION}: the window "
                           "mod is made for that")
    if not target.is_dir():
        shutil.copytree(origin, target, ignore=lambda folder, names: [name for name in names if name in NOT_COPIED])
        log(f"copied your instance {source} to {target} (without its worlds and mods)")
    point(target, instance, view_port)
    mods = game_folder(target) / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    for old in mods.glob("harness-camera-*.jar"):
        old.unlink()
    shutil.copyfile(MOD, mods / MOD.name)
    log(f"the window mod is in {mods}; the instance joins 127.0.0.1:{int(view_port)} once the game has loaded")
    return target


def point(folder: Path, instance: str, view_port: int) -> None:
    """Write into the instance where its window joins: the view port of the body's bridge."""
    config = folder / "instance.cfg"
    before = config.read_text(encoding="utf-8")
    wanted = {"name": instance, "OverrideJavaArgs": "true",
              "JvmArgs": f"-Dharness.camera.server=127.0.0.1:{int(view_port)}"}
    # The launcher reads these in the file's [General] section (the first; a file without sections is all General).
    rows = before.splitlines()
    headers = [index for index, row in enumerate(rows) if re.fullmatch(r"\[.+\]", row.strip())]
    general = next((index for index in headers if rows[index].strip() == "[General]"), None)
    start = general + 1 if general is not None else 0
    end = next((index for index in headers if index >= start), len(rows)) if general is not None or not headers else 0
    kept, seen = [], set()
    for index, row in enumerate(rows):
        key = row.split("=", 1)[0].strip()
        if key in wanted:
            if not start <= index < end or key in seen:
                continue                      # (out of place, or twice: the launcher does not read it there)
            row = f"{key}={wanted[key]}"
            seen.add(key)
        kept.append(row)
    missing = [f"{key}={value}" for key, value in wanted.items() if key not in seen]
    if general is None and headers:
        kept = ["[General]", *missing, *kept]
    else:
        at = kept.index("[General]") + 1 if general is not None else 0
        kept[at:at] = missing
    text = "\n".join(kept) + "\n"
    if text != before:
        config.write_text(text, encoding="utf-8")


def check(values) -> None:
    if os.name != "nt":
        raise RuntimeError("a game window is started on Windows only for now: set minebot.window to off (the body then "
                           "has no pictures)")
    if not values["launcher"] or not Path(values["launcher"]).expanduser().is_file():
        raise RuntimeError("minebot.window is on, and minebot.launcher names no launcher: run "
                           "harness minebot window setup --launcher PROGRAM --from YOUR_INSTANCE")


def launch(values, log=print) -> dict:
    """Start the window and wait until it is at the bridge: {"joined", "game": its process id}."""
    folder = instances_dir(values["launcher"]) / values["instance"]
    if (folder / "instance.cfg").is_file():
        point(folder, values["instance"], values["view_port"])   # (the port may be another than at its setup)
    done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WINDOW / "launch-window.ps1"),
                           "-Launcher", str(Path(values["launcher"]).expanduser()), "-Instance", values["instance"],
                           "-Bridge", f"http://127.0.0.1:{values['bridge_port']}"],
                          capture_output=True, text=True, timeout=400, **QUIET)
    lines = [line for line in done.stdout.strip().splitlines() if line.startswith("{")]
    try:
        answer = json.loads(lines[-1]) if lines else {}
    except ValueError:
        answer = {}
    if not answer.get("joined"):
        log("the game window did not come to the bridge: "
            + (answer.get("error") or done.stderr.strip()[-300:]
               or (f"the game runs (process {answer['game']}) and did not join the view port" if answer.get("game")
                   else "the launcher did not start the game")))
    return answer
