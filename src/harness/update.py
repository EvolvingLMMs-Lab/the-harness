"""Updating a pip install of The Harness (the desktop app updates itself: packages/app/shell).

    harness update            pip install -U the-harness with this Python, then the installed
                              packages to the newest version in their range that works with it
                              (harness install --update)
    harness update --check    the newest version on PyPI, without installing

The terminal chat says in one line when PyPI has a newer version. PyPI is asked at most once a
day (DATA/update-check.json keeps the answer), in the background, never while tests run
($HARNESS_UPDATE_CHECK=0 turns it off) and not when app.update is none. A copy that came with
the desktop app (its own Python under runtime/) is updated by the app, not by pip: as with an
app a package manager installed, the updater that installed it updates it."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen

PACKAGE = "the-harness"
PYPI = f"https://pypi.org/pypi/{PACKAGE}/json"
CACHE = "update-check.json"
# Seconds between two questions to PyPI.
DAY = 24 * 60 * 60
ENV = "HARNESS_UPDATE_CHECK"


def version_key(text: str) -> tuple:
    """A release's version as a comparable tuple: 0.88.0 > 0.87.10 > 0.87.0 > 0.87.0rc1."""
    found = re.match(r"(\d+(?:\.\d+)*)(.*)", str(text or "").strip())
    if not found:
        return ()
    numbers = tuple(int(part) for part in found.group(1).split("."))
    numbers += (0,) * (4 - len(numbers))
    # A pre-release (a, b, rc, dev) sorts before its release.
    return numbers + ((0,) if found.group(2) else (1,))


def newer(candidate: str, current: str) -> bool:
    return bool(version_key(candidate)) and version_key(candidate) > version_key(current)


def current() -> str:
    from . import __version__

    return __version__


def bundled() -> bool:
    """Whether this Python is the desktop app's own runtime (installers put it at
    runtime/python beside runtime/packages)."""
    prefix = Path(sys.prefix).resolve()
    return prefix.name == "python" and prefix.parent.name == "runtime" and (prefix.parent / "packages").is_dir()


def mode() -> str:
    """app.update as config.toml has it (default when unset or the app package is absent)."""
    try:
        from .paths import data
        from .settings import read

        value = (read(data()).get("app") or {}).get("update")
    except Exception:
        value = None
    return value if value in ("default", "start", "manual", "none") else "default"


def enabled() -> bool:
    """Whether the terminal chat may ask PyPI on its own."""
    if os.environ.get(ENV, "").strip().lower() in ("0", "off", "false", "no"):
        return False
    if "PYTEST_CURRENT_TEST" in os.environ or bundled():
        return False
    return mode() in ("default", "start")


def _cache_path() -> Path:
    from .paths import data

    return data() / CACHE


def cached() -> dict:
    try:
        found = json.loads(_cache_path().read_text(encoding="utf-8"))
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def stale(now: float | None = None) -> bool:
    return (now or time.time()) - float(cached().get("checked") or 0) >= DAY


def latest(refresh: bool = False, timeout: float = 5.0) -> dict:
    """{version, checked} of the newest release on PyPI: the kept answer when it is less than a
    day old (unless `refresh`), else PyPI's (kept). {error} when PyPI cannot be reached."""
    if not refresh and not stale():
        return cached()
    from .core import atomic_write

    try:
        request = Request(PYPI, headers={"Accept": "application/json", "User-Agent": f"the-harness/{current()}"})
        with urlopen(request, timeout=timeout) as answer:
            version = str(json.load(answer)["info"]["version"])
    except Exception as error:
        return {**cached(), "error": str(error)}
    found = {"version": version, "checked": time.time()}
    try:
        atomic_write(_cache_path(), json.dumps(found))
    except OSError:
        pass
    return found


def notice() -> str | None:
    """The terminal chat's line when the kept answer names a newer release."""
    version = cached().get("version")
    if version and newer(version, current()):
        return f"— The Harness {version} is available (this is {current()}): harness update"
    return None


def check_in_background(say) -> None:
    """The kept notice at once; PyPI asked in a thread when the answer is a day old, `say`
    called with the notice when a newer release turns up."""
    if not enabled():
        return
    line = notice()
    if line:
        say(line)
        return
    if not stale():
        return
    import threading

    def ask():
        latest(refresh=True)
        found = notice()
        if found:
            say(found)

    threading.Thread(target=ask, name="update-check", daemon=True).start()


def main(arguments=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="harness update", description="Update this pip install of The Harness "
                                     "(pip install -U the-harness) and its installed packages")
    parser.add_argument("--check", action="store_true", help="only say whether PyPI has a newer version")
    given = parser.parse_args(arguments)
    if bundled():
        print("This copy came with The Harness desktop app, which updates itself: Settings > About > Check for "
              "updates, or Restart to update in the tray.", file=sys.stderr)
        return 1
    if given.check:
        found = latest(refresh=True)
        if found.get("error") and not found.get("version"):
            print(f"PyPI did not answer: {found['error']}", file=sys.stderr)
            return 1
        if newer(found["version"], current()):
            print(f"{found['version']} is available (this is {current()}): harness update")
        else:
            print(f"{current()} is the newest")
        return 0
    if importlib.util.find_spec("pip") is None:
        print(f"This Python has no pip; update with the tool that installed The Harness (pipx upgrade {PACKAGE}, "
              f"uv tool upgrade {PACKAGE}).", file=sys.stderr)
        return 1
    before = current()
    command = [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", PACKAGE]
    print("+ " + " ".join(command[2:]), flush=True)
    if subprocess.run(command).returncode != 0:
        return 1
    # The new version's own process: it knows which package versions work with it.
    after = subprocess.run([sys.executable, "-c", "import harness; print(harness.__version__)"], capture_output=True,
                           text=True).stdout.strip() or before
    print(f"+ harness install --update", flush=True)
    packages = subprocess.run([sys.executable, "-m", "harness", "install", "--update"]).returncode
    try:
        _cache_path().unlink()
    except OSError:
        pass
    if after == before:
        print(f"✓ {after} is the newest")
    else:
        print(f"✓ {before} → {after} · the session host takes it when it is next idle (harness host stop: now)")
    return 0 if packages == 0 else 1
