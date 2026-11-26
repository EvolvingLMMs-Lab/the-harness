"""The desktop shell (packages/app/shell/, a Tauri window over the host's page) when it is
installed: `harness app` opens its window instead of printing only the address.

It is found by $HARNESS_APP_SHELL, else by its name on PATH, else where its installers put
it: Windows %LOCALAPPDATA%\\The Harness\\the-harness.exe, macOS /Applications/The
Harness.app/Contents/MacOS/the-harness, Linux /usr/bin/the-harness (.deb) or the AppImage.
The shell is started with the page's address as its one argument; with `--overlay` and an
address it opens the timeline overlay instead."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ENV = "HARNESS_APP_SHELL"
NAMES = ("the-harness",)


def find() -> Path | None:
    """The shell's executable, or None when it is not installed."""
    given = os.environ.get(ENV)
    if given:
        return Path(given) if Path(given).exists() else None
    for name in NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "The Harness"
        candidates = [base / "the-harness.exe"]
    elif sys.platform == "darwin":
        candidates = [Path(folder) / "The Harness.app" / "Contents" / "MacOS" / "the-harness"
                      for folder in ("/Applications", Path.home() / "Applications")]
    else:
        # the .deb's binary, else an AppImage: where it was run from ($APPIMAGE), or one kept in
        # the usual folders
        candidates = [Path("/usr/bin/the-harness")]
        if os.environ.get("APPIMAGE"):
            candidates.append(Path(os.environ["APPIMAGE"]))
        for folder in (Path.home() / "Applications", Path.home() / ".local" / "bin", Path.home() / "Downloads"):
            candidates += sorted(folder.glob("[Tt]he[ -_][Hh]arness*.AppImage"), reverse=True) if folder.is_dir() else []
    return next((path for path in candidates if path.is_file()), None)


def open_window(url: str, *arguments: str) -> subprocess.Popen | None:
    """Start the shell on `url` (its own window, owned by no terminal); None when it is not
    installed."""
    shell = find()
    if shell is None:
        return None
    flags = {}
    if sys.platform.startswith("win"):
        flags["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        flags["start_new_session"] = True
    return subprocess.Popen([str(shell), *arguments, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **flags)


def focus() -> bool:
    """Bring the shell's window to the front: `--focus` raises the window of the instance that
    runs and exits 0, or exits 1 without opening one. False when none is open."""
    shell = find()
    if shell is None:
        return False
    try:
        done = subprocess.run([str(shell), "--focus"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
