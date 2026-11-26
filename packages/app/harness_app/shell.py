"""The desktop shell (packages/app/shell/, a Tauri window over the host's page) when it is
installed: `harness app` opens its window instead of printing only the address.

It is found by $HARNESS_APP_SHELL, else by its name on PATH, else where its installers put
it: Windows %LOCALAPPDATA%\\The Harness\\the-harness.exe, macOS /Applications/The
Harness.app/Contents/MacOS/the-harness, Linux /usr/bin/the-harness (.deb) or the AppImage.
Another channel's shell has that channel's names (The Harness Dev, the-harness-dev), and its
terminal command is that channel's too (harness-dev), in that app's own runtime\\bin: what
follows about `harness` holds for each channel's own command.
The shell is started with the page's address as its one argument.

The `harness` command in a terminal. The desktop app brings a launcher that runs the harness
with the app's own Python runtime, so a terminal uses the version the app has, and puts it on
the PATH as Ollama's and VS Code's installers do with `ollama` and `code`:

  Windows  runtime\\bin\\harness.exe; the installer adds its folder to the user's PATH
           (HKCU\\Environment, appended once; the change is broadcast, so a terminal opened
           afterwards has it) and removes it when the app is uninstalled
  macOS    runtime/bin/harness inside the app, linked from /usr/local/bin/harness when the
           user asks (the tray's "Install 'harness' command in PATH", as VS Code's shell
           command; macOS asks for an administrator's password when the folder needs one)
  Linux    the .deb's /usr/bin/harness

command() says which `harness` a terminal runs and whether it is this install's (another
install earlier on the PATH, of another version, would work on the same data folder): the
app's About page asks for a terminal opened now, `harness doctor` for the terminal it runs in.
As a program (the shell's --path, which the installers run):

    python shell.py command on [--report FILE]    put the app's command on the PATH
    python shell.py command off                   take it off
    python shell.py command status [--json]       which harness a new terminal runs

This file runs by its path with the bundled Python, before any package is installed for the
user: standard library only at import.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ENV = "HARNESS_APP_SHELL"
try:
    from harness import channel

    PRODUCT, BINARY, COMMAND = channel.product(), channel.tag("the-harness"), channel.tag("harness")
except ImportError:  # a core from before channels
    PRODUCT, BINARY, COMMAND = "The Harness", "the-harness", "harness"
NAMES = (BINARY,)
# macOS: where the app links its command, as VS Code links `code`.
LINK = Path("/usr/local/bin") / COMMAND
# Windows: the user's and the machine's environment in the registry, and the two types a Path
# value has there (REG_SZ, REG_EXPAND_SZ).
_USER_ENV = "Environment"
_MACHINE_ENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_TEXT, _EXPANDED_TEXT = 1, 2
# Seconds another install's answer to --version stands (the About page asks often).
VERSION_SECONDS = 60.0
_versions: dict = {}


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
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / PRODUCT
        candidates = [base / f"{BINARY}.exe"]
    elif sys.platform == "darwin":
        candidates = [Path(folder) / f"{PRODUCT}.app" / "Contents" / "MacOS" / BINARY
                      for folder in ("/Applications", Path.home() / "Applications")]
    else:
        # the .deb's binary, else an AppImage: where it was run from ($APPIMAGE), or one kept in
        # the usual folders
        candidates = [Path("/usr/bin") / BINARY]
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


# -- the harness command in a terminal ---------------------------------------------------------

def _windows() -> bool:
    return sys.platform.startswith("win")


def _file_name() -> str:
    return COMMAND + (".exe" if _windows() else "")


def launcher() -> Path | None:
    """The desktop app's own `harness` command, when this Python is the app's runtime (the
    installers put it at runtime/python): runtime/bin/harness on Windows and macOS, the .deb's
    /usr/bin/harness. None for a pip install and for an AppImage, which has no command."""
    prefix = Path(sys.prefix).resolve()
    if not (prefix.name == "python" and prefix.parent.name == "runtime"):
        return None
    candidates = [prefix.parent / "bin" / _file_name()]
    if sys.platform.startswith("linux") and Path("/usr/lib") in prefix.parents:
        candidates.append(Path("/usr/bin") / COMMAND)
    return next((path for path in candidates if path.is_file()), None)


def own_commands() -> list[Path]:
    """This install's command files: the app's launcher, and the console script pip made for
    this Python (a pip install, a venv)."""
    import sysconfig

    found = [launcher(), Path(sysconfig.get_path("scripts")) / _file_name()]
    return [path for path in found if path is not None and path.is_file()]


def _read_path(machine: bool = False) -> tuple[str, int]:
    """Windows: the user's Path (or the machine's) as it is written in the registry, not
    expanded, and its type; ("", REG_EXPAND_SZ) when there is none."""
    import winreg

    root, key = (winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV) if machine else (winreg.HKEY_CURRENT_USER, _USER_ENV)
    try:
        with winreg.OpenKey(root, key) as opened:
            value, kind = winreg.QueryValueEx(opened, "Path")
        return str(value), kind
    except OSError:
        return "", _EXPANDED_TEXT


def _write_path(value: str, kind: int) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _USER_ENV, 0, winreg.KEY_SET_VALUE) as opened:
        winreg.SetValueEx(opened, "Path", 0, kind, value)


def _broadcast() -> None:
    """Windows: tell running programs that the environment changed (WM_SETTINGCHANGE), so a
    terminal opened from now on has the new PATH without signing out, as Inno Setup's
    ChangesEnvironment does for Ollama's and VS Code's installers."""
    import ctypes

    result = ctypes.c_size_t()
    # HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG, at most 5 s for each window
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))


def _folder_key(folder: str) -> str:
    """A PATH entry as it compares: quotes and a trailing separator dropped, variables expanded,
    case folded where the system folds it."""
    text = os.path.expandvars(folder.strip().strip('"'))
    return os.path.normcase(os.path.normpath(text)) if text else ""


def path_add(folder: str) -> bool:
    """Windows: append `folder` to the user's PATH unless it is there; whether it was added.
    What is there stays as written: only the text ";folder" is added, the value keeps its type."""
    value, kind = _read_path()
    if any(_folder_key(part) == _folder_key(folder) for part in value.split(";") if part.strip()):
        return False
    joined = value + ("" if not value or value.endswith(";") else ";") + folder
    _write_path(joined, kind if kind in (_TEXT, _EXPANDED_TEXT) else _EXPANDED_TEXT)
    _broadcast()
    return True


def path_remove(folder: str) -> bool:
    """Windows: take `folder` out of the user's PATH; whether it was there. The other entries
    stay as written."""
    value, kind = _read_path()
    parts = value.split(";")
    kept = [part for part in parts if not (part.strip() and _folder_key(part) == _folder_key(folder))]
    if len(kept) == len(parts):
        return False
    _write_path(";".join(kept), kind)
    _broadcast()
    return True


def terminal_path(new: bool = True) -> list[str]:
    """The folders a terminal looks in, in order. `new`: a terminal opened now, as the system
    gives it its PATH, whatever this process inherited: on Windows the machine's Path then the
    user's, from the registry; on macOS this process's PATH and the folders of /etc/paths and
    /etc/paths.d, which every login shell gets. Otherwise, and on Linux: this process's PATH."""
    current = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part.strip()]
    if not new:
        return current
    if _windows():
        import winreg

        written = _read_path(machine=True)[0].split(";") + _read_path()[0].split(";")
        return [winreg.ExpandEnvironmentStrings(part) for part in written if part.strip()]
    if sys.platform == "darwin":
        files = [Path("/etc/paths")] + (sorted(Path("/etc/paths.d").iterdir()) if Path("/etc/paths.d").is_dir() else [])
        for file in files:
            try:
                rows = file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            current += [row.strip() for row in rows if row.strip() and row.strip() not in current]
    return current


def commands(folders) -> list[Path]:
    """Every `harness` in `folders`, in the order a terminal takes them (in one folder the
    first of the system's executable extensions wins, as cmd and PowerShell choose)."""
    if _windows():
        extensions = [ext.lower() for ext in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if ext]
    else:
        extensions = [""]
    found, seen = [], set()
    for folder in folders:
        for extension in extensions:
            file = Path(folder.strip().strip('"')) / (COMMAND + extension)
            if file.is_file() and (_windows() or os.access(file, os.X_OK)):
                key = os.path.normcase(str(file))
                if key not in seen:
                    seen.add(key)
                    found.append(file)
                break
    return found


def _same(one: Path, other: Path) -> bool:
    """The same file, a link to it, or a copy of it (uv and pipx link or copy a console script
    into their own bin folder; a console script's bytes name its Python, so equal bytes run
    the same install)."""
    try:
        if os.path.samefile(one, other):
            return True
        return one.stat().st_size == other.stat().st_size and one.read_bytes() == other.read_bytes()
    except OSError:
        return False


def _version(file: Path) -> str | None:
    """What another install's command answers to --version ("harness 0.80.0", or with its
    channel after it: "harness-dev 0.87.0-dev.412 (dev channel)"): its version, or
    None when it gave none in time. It is asked without this process's PYTHON* variables: the
    host runs with a PYTHONPATH of this install, under which the other one would import this
    install's code and answer with this version."""
    kept = _versions.get(str(file))
    if kept and time.monotonic() - kept[0] < VERSION_SECONDS:
        return kept[1]
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("PYTHON")}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        done = subprocess.run([str(file), "--version"], capture_output=True, text=True, errors="replace", timeout=20,
                              stdin=subprocess.DEVNULL, env=env, **flags)
        words = (done.stdout or "").split()
        found = words[min(1, len(words) - 1)] if done.returncode == 0 and words else None
    except (OSError, subprocess.SubprocessError):
        found = None
    _versions[str(file)] = (time.monotonic(), found)
    return found


def command(new: bool = True) -> dict:
    """Which `harness` a terminal runs, and whether it is this install's.

    `new`: a terminal opened now (what the app's About page shows); False: the terminal this
    process runs in (what `harness doctor` checks). The answer:

      path     the first harness on that terminal's PATH, or None when there is none
      mine     whether that one is this install's
      version  its version: this one's when mine, else what it answered to --version (None
               when it gave none)
      own      this install's own command file, on the PATH or not (None: it has none, as a
               source checkout run with `python -m harness`)
      on_path  whether this install's command is on that PATH at all (first or not)
      this     this install's version
      fix      what to do when a terminal does not run this install; "" when it does
    """
    from harness import __version__

    try:  # the build's own version on a channel that numbers its builds
        __version__ = channel.version()
    except NameError:  # a core from before channels
        pass
    mine = own_commands()
    found = commands(terminal_path(new))
    first = found[0] if found else None
    listed = next((file for file in found if any(_same(file, each) for each in mine)), None)
    own = listed or (mine[0] if mine else None)
    answer = {"path": str(first) if first else None, "mine": False, "version": None,
              "own": str(own) if own else None, "on_path": listed is not None, "this": __version__, "fix": ""}
    if first is not None and any(_same(first, each) for each in mine):
        return {**answer, "mine": True, "version": __version__}
    if first is None:
        if own is None:
            answer["fix"] = "this harness has no command of its own here: run it as python -m harness"
        elif launcher() is None:
            answer["fix"] = f"add {own.parent} to the PATH, then open a new terminal"
        elif sys.platform == "darwin":
            answer["fix"] = (f"choose Install '{COMMAND}' command in PATH in {PRODUCT}'s menu bar menu, then open "
                             "a new terminal")
        else:
            answer["fix"] = f"install {PRODUCT} again (its installer adds {own.parent} to the PATH), or add it yourself"
        return answer
    answer["version"] = _version(first)
    theirs = f"{first} ({answer['version'] or 'its version is unknown'})"
    answer["fix"] = (f"a terminal runs another {COMMAND} first: {theirs}; this one is {__version__}. Both use the same "
                     "data folder, and that one does not update with this one. Remove it (pip uninstall the-harness, "
                     "or uv tool uninstall the-harness)" + (f", or run this one as {own}" if own else ""))
    return answer


def _as_administrator(script: str) -> None:
    """macOS: run a shell line with an administrator's rights; the system asks for the
    password itself (as VS Code's shell command does: osascript, "with administrator
    privileges")."""
    quoted = script.replace("\\", "\\\\").replace('"', '\\"')
    done = subprocess.run(["osascript", "-e", f'do shell script "{quoted}" with administrator privileges'],
                          capture_output=True, text=True, errors="replace")
    if done.returncode != 0:
        raise RuntimeError((done.stderr or "").strip() or "the administrator's permission was not given")


def _link(own: Path) -> None:
    """macOS: LINK -> the app's launcher. A link there is replaced; another program's file is not."""
    if LINK.is_symlink() or LINK.exists():
        if _same(LINK, own):
            return
        if not LINK.is_symlink():
            raise ValueError(f"{LINK} is there already and is not a link: remove it first")
    try:
        LINK.parent.mkdir(parents=True, exist_ok=True)
        if LINK.is_symlink():
            LINK.unlink()
        LINK.symlink_to(own)
    except PermissionError:
        _as_administrator(f"mkdir -p {shlex.quote(str(LINK.parent))} && ln -sf {shlex.quote(str(own))} "
                          f"{shlex.quote(str(LINK))}")


def _unlink(own: Path) -> None:
    """macOS: remove LINK when it points at the app's launcher."""
    if not (LINK.is_symlink() and _same(LINK, own)):
        return
    try:
        LINK.unlink()
    except PermissionError:
        _as_administrator(f"rm -f {shlex.quote(str(LINK))}")


def _app_command() -> Path:
    own = launcher()
    if own is None:
        raise ValueError("there is no harness command of the desktop app here to put on the PATH (a pip install's "
                         "is where pip put it; an AppImage has none, the .deb installs /usr/bin/harness)")
    return own


def command_on() -> dict:
    """Put the desktop app's `harness` on the PATH (Windows: its folder in the user's PATH;
    macOS: the link; the .deb installed it already). The answer of command() afterwards."""
    own = _app_command()
    if _windows():
        path_add(str(own.parent))
    elif sys.platform == "darwin":
        _link(own)
    return command()


def command_off() -> dict:
    """Take the desktop app's `harness` off the PATH again (the .deb's goes with the package)."""
    own = _app_command()
    if _windows():
        path_remove(str(own.parent))
    elif sys.platform == "darwin":
        _unlink(own)
    return command()


def said(found: dict, new: bool = True) -> str:
    """command() in a line or two for a terminal (`new` as it was asked)."""
    where = f"{COMMAND} in a new terminal" if new else f"{COMMAND} in this terminal"
    if found["path"] is None:
        return f"{where}: not found\n  {found['fix']}"
    if found["mine"]:
        return f"{where}: {found['path']} (this one, {found['version']})"
    return f"{where}: {found['path']} ({found['version'] or 'another install'})\n  {found['fix']}"


def main(argv=None) -> int:
    parsed = argparse.ArgumentParser(prog="shell.py", description="The harness command of the desktop app in a terminal.")
    parts = parsed.add_subparsers(dest="part", required=True)
    given = parts.add_parser("command", help="put the app's harness command on the PATH, take it off, or say which "
                                             "harness a new terminal runs")
    given.add_argument("action", choices=("on", "off", "status"))
    given.add_argument("--json", action="store_true", help="print JSON")
    given.add_argument("--report", type=Path, metavar="FILE",
                       help="write two lines for the installer's finish page (UTF-16): the file and the version of "
                            "another harness a new terminal runs first; both empty when it runs this one")
    args = parsed.parse_args(argv)
    try:
        found = {"on": command_on, "off": command_off, "status": command}[args.action]()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"harness: {error}", file=sys.stderr)
        return 1
    if args.report:
        other = found["path"] is not None and not found["mine"]
        lines = [found["path"] if other else "", (found["version"] or "") if other else ""]
        args.report.write_bytes("".join(f"{line}\r\n" for line in lines).encode("utf-16-le"))
    print(json.dumps(found) if args.json else said(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
