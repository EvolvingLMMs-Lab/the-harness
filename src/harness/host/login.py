"""The session host at login: `harness host install`, `harness host uninstall` and
`harness host status`.

Each system's own way to start a program when its user logs in, as OpenClaw's and Hermes'
`gateway install` register their gateway and as Ollama's installer registers its app:

  Windows  a scheduled task at logon, "The Harness host"; where creating one is refused, a
           launcher in the user's Startup folder
  macOS    a launchd LaunchAgent, ~/Library/LaunchAgents/com.lmms-lab.harness.host.plist (the
           system shows its "background item added" notice the first time it loads)
  Linux    a systemd user service, ~/.config/systemd/user/harness-host.service; on a server it
           runs without a login session only with lingering on (loginctl enable-linger), which
           install and status point out

The login item is the only record: status() asks the system every time, nothing is kept
beside it, so an item the user turned off or removed in the system's settings reads as off.
The item runs `python -m harness.host.login run`, which starts the session host (`python -m
harness.host.server`) the way a client starts it and waits for it; with the agent package
the host stays up while an identity is alive (its background service's keep_alive). The
setting agent.autostart reads and switches the same item (autostart()).

The installers' desktop shell registers its own launcher instead (HARNESS_HOST_COMMAND, a
JSON list): an AppImage's files move each time it mounts, so the item runs the AppImage.
"""

import argparse
import getpass
import json
import os
from pathlib import Path
import plistlib
import shlex
import signal
import subprocess
import sys
import time
from xml.sax.saxutils import escape

NAME = "The Harness host"
LABEL = "com.lmms-lab.harness.host"
UNIT = "harness-host.service"
COMMAND_ENV = "HARNESS_HOST_COMMAND"
# Seconds a read of the system stands for autostart() (Settings reads it often).
CACHE_SECONDS = 3.0
_cache: list = [0.0, None]


def system() -> str:
    """windows, macos or linux (any other POSIX system is taken as linux)."""
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def _run(command: list[str]) -> subprocess.CompletedProcess:
    """A system command's result; a missing program is exit status 127, never an exception."""
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        return subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=30, **options)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(command, 127, "", str(error))


def command() -> list[str]:
    """What the login item runs: HARNESS_HOST_COMMAND when given, else this Python (on
    Windows its windowless pythonw.exe) with the runner; then the data and install folders
    when HARNESS_DATA or HARNESS_HOME moved them, so the host at login uses the same ones."""
    from ..paths import DATA_ENV, HOME_ENV

    given = os.environ.get(COMMAND_ENV)
    if given:
        words = json.loads(given)
        if not (isinstance(words, list) and words and all(isinstance(word, str) and word for word in words)):
            raise ValueError(f"{COMMAND_ENV} is a JSON list of the command's words")
    else:
        python = Path(sys.executable)
        if system() == "windows" and python.with_name("pythonw.exe").is_file():
            python = python.with_name("pythonw.exe")
        words = [str(python), "-m", "harness.host.login", "run"]
    for name, flag in ((DATA_ENV, "--data"), (HOME_ENV, "--home")):
        if os.environ.get(name):
            words += [flag, str(Path(os.path.expanduser(os.environ[name])).resolve())]
    return words


def directory() -> str:
    """The item's working directory: the folder holding the harness package (site-packages,
    or a checkout's src/), so `python -m harness...` imports it there too. With the shell's
    own launcher (HARNESS_HOST_COMMAND) the package may sit in a mount that is gone after a
    restart (an AppImage's), so the item runs in the home folder instead."""
    from ..paths import PACKAGE

    if os.environ.get(COMMAND_ENV):
        return str(Path.home())
    return str(PACKAGE.parent)


# -- Windows ---------------------------------------------------------------------------------

def _startup_file() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{NAME}.cmd"


def _task_xml(words: list[str], folder: str) -> str:
    user = "\\".join(part for part in (os.environ.get("USERDOMAIN"), os.environ.get("USERNAME") or getpass.getuser())
                     if part)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Starts the session host of The Harness when you log in (harness host uninstall removes it).</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(words[0])}</Command>
      <Arguments>{escape(subprocess.list2cmdline(words[1:]))}</Arguments>
      <WorkingDirectory>{escape(folder)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _startup_approved(name: str) -> bool:
    """Whether Windows lets a Startup-folder item run (Task Manager's Startup apps can turn
    it off: the first byte of its StartupApproved value is odd then)."""
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as opened:
            value, _ = winreg.QueryValueEx(opened, name)
        return not (bytes(value)[:1] and bytes(value)[0] & 1)
    except (ImportError, OSError, TypeError, ValueError):
        return True


def _windows_status() -> dict:
    found = _run(["schtasks", "/Query", "/TN", NAME, "/FO", "CSV", "/NH"])
    if found.returncode == 0:
        return {"on": "disabled" not in (found.stdout or "").lower(), "kind": "scheduled task", "where": NAME}
    file = _startup_file()
    if file.is_file():
        return {"on": _startup_approved(file.name), "kind": "startup folder", "where": str(file)}
    return {"on": False, "kind": None, "where": None}


def _windows_install(words: list[str], folder: str, scratch: Path) -> dict:
    xml = scratch / "harness-host-task.xml"
    xml.write_text(_task_xml(words, folder), encoding="utf-16")
    try:
        made = _run(["schtasks", "/Create", "/TN", NAME, "/XML", str(xml), "/F"])
    finally:
        xml.unlink(missing_ok=True)
    if made.returncode == 0:
        _startup_file().unlink(missing_ok=True)
        return {"kind": "scheduled task", "where": NAME}
    # Creating a task is refused (policy, a locked-down account): a login item in the
    # Startup folder instead.
    file = _startup_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(f'@echo off\r\ncd /d "{folder}"\r\nstart "" {subprocess.list2cmdline(words)}\r\n',
                    encoding="utf-8", newline="")
    return {"kind": "startup folder", "where": str(file),
            "note": f"a scheduled task was refused ({(made.stderr or made.stdout).strip()})"}


def _windows_uninstall() -> None:
    if _run(["schtasks", "/Query", "/TN", NAME]).returncode == 0:
        removed = _run(["schtasks", "/Delete", "/TN", NAME, "/F"])
        if removed.returncode != 0:
            raise RuntimeError(f"schtasks /Delete: {(removed.stderr or removed.stdout).strip()}")
    _startup_file().unlink(missing_ok=True)


# -- macOS -----------------------------------------------------------------------------------

def _plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _macos_status() -> dict:
    file = _plist()
    if not file.is_file():
        return {"on": False, "kind": None, "where": None}
    disabled = _run(["launchctl", "print-disabled", _domain()]).stdout
    off = any(f'"{LABEL}"' in line and ("disabled" in line or "true" in line) for line in disabled.splitlines())
    return {"on": not off, "kind": "launchd LaunchAgent", "where": str(file)}


def _macos_install(words: list[str], folder: str) -> dict:
    file = _plist()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(plistlib.dumps({"Label": LABEL, "ProgramArguments": words, "WorkingDirectory": folder,
                                     "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
                                     "ProcessType": "Interactive"}))
    # A LaunchAgent the user turned off stays off until it is enabled again.
    _run(["launchctl", "enable", f"{_domain()}/{LABEL}"])
    return {"kind": "launchd LaunchAgent", "where": str(file)}


def _macos_uninstall() -> None:
    _run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])
    _plist().unlink(missing_ok=True)


# -- Linux -----------------------------------------------------------------------------------

def _unit() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user" / UNIT


def _quoted(word: str) -> str:
    return '"' + word.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _unit_text(words: list[str], folder: str) -> str:
    return (f"[Unit]\nDescription=The Harness session host\n\n"
            f"[Service]\nType=simple\nWorkingDirectory={folder}\nExecStart={' '.join(map(_quoted, words))}\n"
            f"Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n")


def linger() -> bool | None:
    """Whether this user's services run without a login session (None: unknown)."""
    answer = _run(["loginctl", "show-user", getpass.getuser(), "--property=Linger", "--value"])
    return answer.stdout.strip() == "yes" if answer.returncode == 0 else None


def linger_hint() -> str:
    return (f"on a server, it runs without anyone logged in only with lingering on: "
            f"sudo loginctl enable-linger {getpass.getuser()}")


def _linux_status() -> dict:
    enabled = _run(["systemctl", "--user", "is-enabled", UNIT]).stdout.strip()
    on = enabled in ("enabled", "enabled-runtime")
    return {"on": on, "kind": "systemd user service" if on or _unit().is_file() else None,
            "where": str(_unit()) if _unit().is_file() else None, "linger": linger()}


def _linux_install(words: list[str], folder: str) -> dict:
    file = _unit()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(_unit_text(words, folder), encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"])
    enabled = _run(["systemctl", "--user", "enable", UNIT])
    if enabled.returncode != 0:
        file.unlink(missing_ok=True)
        raise RuntimeError("systemd user services are not available here (systemctl --user enable: "
                           f"{(enabled.stderr or enabled.stdout).strip()})")
    return {"kind": "systemd user service", "where": str(file), "linger": linger()}


def _linux_uninstall() -> None:
    _run(["systemctl", "--user", "disable", UNIT])
    _unit().unlink(missing_ok=True)
    _run(["systemctl", "--user", "daemon-reload"])


# -- the commands ----------------------------------------------------------------------------

def status() -> dict:
    """{on, kind, where} as the system has it now (Linux: also linger)."""
    found = {"windows": _windows_status, "macos": _macos_status, "linux": _linux_status}[system()]()
    _cache[:] = [time.monotonic(), found["on"]]
    return {"system": system(), **found}


def install() -> dict:
    """Register the login item (replacing one there is); what the system now has."""
    import tempfile

    words, folder = command(), directory()
    _cache[0] = 0.0
    if system() == "windows":
        with tempfile.TemporaryDirectory() as scratch:
            made = _windows_install(words, folder, Path(scratch))
    elif system() == "macos":
        made = _macos_install(words, folder)
    else:
        made = _linux_install(words, folder)
    return {"system": system(), "on": True, "command": words, **made}


def uninstall() -> dict:
    """Remove the login item (nothing to remove is not an error)."""
    _cache[0] = 0.0
    {"windows": _windows_uninstall, "macos": _macos_uninstall, "linux": _linux_uninstall}[system()]()
    return status()


def autostart(value=None) -> bool:
    """agent.autostart: with no value, whether the login item is on (read from the system,
    kept a few seconds); with true or false, install or uninstall it."""
    if value is None:
        if _cache[1] is not None and time.monotonic() - _cache[0] < CACHE_SECONDS:
            return bool(_cache[1])
        try:
            return bool(status()["on"])
        except (OSError, RuntimeError, ValueError):
            return False
    if not isinstance(value, bool):
        raise ValueError("true or false")
    (install if value else uninstall)()
    return value


def run(data_folder: str | None = None, home_folder: str | None = None) -> int:
    """The login item's process: the session host in a child process, waited for (a service
    manager follows this process; stopping it stops the host). Nothing to do when a host
    already answers."""
    from ..paths import DATA_ENV, HOME_ENV

    if data_folder:
        os.environ[DATA_ENV] = data_folder
    if home_folder:
        os.environ[HOME_ENV] = home_folder
    from ..paths import data, python_path
    from . import _reachable, read_address

    if _reachable(read_address()) is not None:
        return 0
    logs = data() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": python_path(), "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with open(logs / "host.log", "ab") as log:
        child = subprocess.Popen([sys.executable, "-m", "harness.host.server"], env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, **options)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda *_: child.terminate())
        try:
            return child.wait()
        except KeyboardInterrupt:
            child.terminate()
            return child.wait()


def page() -> dict:
    """The session host (started when none runs) and its app page: {url, token, page}."""
    from . import Host

    host = Host.connect(log=lambda line: print(line, file=sys.stderr))
    return {"url": host.url, "token": host.token, "page": host.page()}


def _say(found: dict) -> None:
    if found.get("on"):
        print(f"starts at login: yes ({found.get('kind')}: {found.get('where')})")
    else:
        print("starts at login: no" + (f" ({found['kind']} turned off: {found['where']})" if found.get("kind") else ""))
    if found.get("note"):
        print(f"  {found['note']}")
    if found.get("system") == "linux" and found.get("on") and found.get("linger") is not True:
        print(f"  {linger_hint()}")


def main(argv=None) -> int:
    parsed = argparse.ArgumentParser(prog="harness host", description="The session host at login.")
    commands = parsed.add_subparsers(dest="command", required=True)
    for name, about in (("install", "start the session host at login (Windows: a scheduled task; macOS: a "
                                    "LaunchAgent; Linux: a systemd user service)"),
                        ("uninstall", "no longer start it at login"),
                        ("status", "whether it starts at login, as the system has it")):
        commands.add_parser(name, help=about).add_argument("--json", action="store_true", help="print JSON")
    ran = commands.add_parser("run", help="the login item's process: the session host, waited for")
    ran.add_argument("--data", help="the data folder (HARNESS_DATA)")
    ran.add_argument("--home", help="the install folder (HARNESS_HOME)")
    commands.add_parser("page", help="start the session host if needed and print its page as JSON")
    given = parsed.parse_args(argv)
    if given.command == "run":
        return run(given.data, given.home)
    if given.command == "page":
        print(json.dumps(page()))
        return 0
    try:
        found = {"install": install, "uninstall": uninstall, "status": status}[given.command]()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"harness host {given.command}: {error}", file=sys.stderr)
        return 1
    if given.command == "status":
        from . import _reachable, read_address

        running = _reachable(read_address())
        found["running"] = None if running is None else {"url": running.url, "pid": getattr(running, "pid", None)}
    if given.json:
        print(json.dumps(found))
        return 0
    if given.command == "install":
        print(f"login item registered ({found['kind']}: {found['where']})")
        if found.get("note"):
            print(f"  {found['note']}")
        if found["system"] == "linux" and found.get("linger") is not True:
            print(f"  {linger_hint()}")
        return 0
    _say(found)
    if given.command == "status":
        print("host: " + (f"running at {found['running']['url']}" if found["running"] else "not running"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
