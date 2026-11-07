"""Isolation of the program kernel (App. A: each episode runs in an isolated
container holding the kernel and its workspace, which can reach only the model
endpoint and the policy servers).

File system: the kernel starts in new user, mount and PID namespaces (util-linux
unshare; no privileges needed). Its view of the hidden roots (by default the user's
home directory) is empty except for the Python installation and, read-only, the
harness source, so benchmark checkouts, task files, run directories and keys are
not visible. /tmp is a fresh tmpfs that disappears with the episode; the working
directory is /tmp/workspace. Host processes are not visible.

Network and processes: once the session has started, an audit hook lets sockets
connect only to the endpoints named in the kernel options (worker, models, policy
servers) and refuses to start processes or to load native code through ctypes. The
hook guards against programs reaching data and services, not against deliberate
escape from the Python interpreter.

Files: from then on the same kind of hook lets programs open and list only the Python
installation, the harness source, system directories and their own process in /proc,
and write only their workspace (and the sandbox's private /tmp). On Linux a
dedicated shared lock directory supports coordination across kernels. It holds where the
sandbox cannot run, and inside it covers what the sandbox leaves visible: directories
outside the hidden roots, such as another run's results on a data disk. Whether a path
exists is not hidden.

A worker's private files (its profile's `private_paths`, e.g. a game's instance) are
refused to programs whether or not the kernel is isolated, and each attempt is reported
to the host, which records it in the trace (`file_access`).

Without the sandbox the kernel still gets only the environment of `kernel_environment`
(no keys but its models'), and runs in a fresh workspace directory, its HOME and
TMPDIR, that is removed with it.
"""

import os
from pathlib import Path
import re
import shlex
import socket
import sys
import threading
from urllib.parse import urlsplit

from harness.runtime.safety.approval import WORKER_APPROVAL_KEY

from harness.core.procs import SHARED_LOCK_DIR


# Audit events a program may not trigger once the kernel is serving.
_BLOCKED_EVENTS = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork", "os.forkpty",
                   "os.spawn", "pty.spawn", "ctypes.dlopen", "ctypes.dlsym")
_DEFAULT_PORTS = {"http": 80, "ws": 80, "https": 443, "wss": 443}
# What programs may read besides the Python installation and the harness source.
_SYSTEM_ROOTS = ("/usr", "/lib", "/lib32", "/lib64", "/libx32", "/bin", "/sbin", "/etc", "/sys", "/dev")
_PROC_FILES = ("/proc/cpuinfo", "/proc/meminfo", "/proc/stat", "/proc/loadavg", "/proc/version")
# Audit events naming paths: (indices of the path arguments, whether they write).
_PATH_EVENTS = {"os.listdir": ((0,), False), "os.scandir": ((0,), False), "os.chdir": ((0,), False),
                "os.remove": ((0,), True), "os.rmdir": ((0,), True), "os.mkdir": ((0,), True),
                "os.rename": ((0, 1), True), "os.link": ((0, 1), True), "os.symlink": ((1,), True),
                "os.truncate": ((0,), True), "os.chmod": ((0,), True), "os.chown": ((0,), True),
                "os.utime": ((0,), True), "shutil.rmtree": ((0,), True), "sqlite3.connect": ((0,), True)}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
# Environment variables the kernel keeps; API keys named in the options are added.
_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "TZ", "PYTHONPATH", "PYTHONUNBUFFERED", "PYTHONNOUSERSITE",
                "HARNESS_WORKER_TOKEN", "HARNESS_PACKAGE_ROOTS",
                "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")
_WINDOWS_ENVIRONMENT = ("SYSTEMROOT", "WINDIR", "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")


def sandbox_command(command: list[str], *, keep: list[Path], read_only: list[Path],
                    hide: list[Path], cwd: Path | None = None) -> list[str]:
    """Wrap `command` so it runs in the namespaces described above. `hide` are the
    roots whose content is replaced by an empty tmpfs; `keep` (read-write) and
    `read_only` paths inside them stay visible."""
    tmp = Path("/tmp").resolve()
    roots = {tmp, *(Path(p).resolve() for p in hide)}
    visible = {Path(p).resolve(): False for p in keep}
    visible.update({Path(p).resolve(): True for p in read_only})
    visible = {path: ro for path, ro in visible.items()
               if path != tmp and roots.intersection((path, *path.parents))}

    # The working directory still refers to the old /tmp after the new one covers it.
    # A relative bind source reaches it only if mount leaves the source uncanonicalized.
    lines = ["set -e", "cd /tmp", "mount -t tmpfs tmpfs /tmp", 'staging=$(mktemp -d /tmp/.harness-mounts.XXXXXX)']
    slots = {}
    for index, path in enumerate(visible):
        slot = slots[path] = f'"$staging/{index}"'
        source = f"./{path.relative_to(tmp)}" if tmp in path.parents else str(path)
        lines += [f"mkdir {slot}", f"mount --no-canonicalize --rbind {shlex.quote(source)} {slot}"]

    # Mount parents first. A hidden child of a restored parent needs its own cover.
    for path in sorted((roots | visible.keys()) - {tmp}, key=lambda path: (len(path.parts), path)):
        target = shlex.quote(str(path))
        lines.append(f"mkdir -p {target}")
        if path in roots and (tmp not in path.parents or any(parent in visible for parent in path.parents)):
            lines.append(f"mount -t tmpfs tmpfs {target}")
        if path in visible:
            lines.append(f"mount --rbind {slots[path]} {target}")
            if visible[path]:
                lines.append(f"mount -o remount,bind,ro {target}")
    for slot in slots.values():
        lines += [f"umount -l {slot}", f"rmdir {slot}"]
    workspace = shlex.quote(str(cwd or "/tmp/workspace"))
    lines += ['rmdir "$staging"', f"mkdir -p {workspace}", f"cd {workspace}",
              "exec " + " ".join(shlex.quote(part) for part in command)]
    return ["unshare", "--user", "--map-root-user", "--mount", "--pid", "--fork", "--mount-proc",
            "--kill-child", "--", "/bin/sh", "-c", "\n".join(lines)]


# Packages the kernel imports that may be installed outside the Python prefix
# (editable installs): the policy client of XPolicyLab.
KERNEL_PACKAGES = ("client_server",)
# Modules imported before the network guard is installed: importing them loads
# native code through ctypes, which programs may not do.
KERNEL_IMPORTS = ("client_server.ws.model_client",)


def package_dirs(names=KERNEL_PACKAGES, python: str | None = None) -> list[Path]:
    """Where these packages live on the host, so the sandbox can show them read-only
    at the same paths (an editable install's finder points there): for this interpreter,
    or for another one (`python`, the kernel's), asked in a process of its own."""
    import importlib.util

    if python and Path(python).absolute() != Path(sys.executable).absolute():
        import json
        import subprocess

        code = ("import importlib.util, json, sys\n"
                "dirs = []\n"
                "for name in sys.argv[1:]:\n"
                "    try:\n"
                "        spec = importlib.util.find_spec(name)\n"
                "    except (ImportError, ValueError):\n"
                "        spec = None\n"
                "    dirs += list(spec.submodule_search_locations or []) if spec else []\n"
                "print(json.dumps(dirs))\n")
        result = subprocess.run([python, "-c", code, *names], capture_output=True, encoding="utf-8", errors="replace",
                                timeout=60)
        return [Path(item) for item in json.loads(result.stdout or "[]")] if result.returncode == 0 else []
    dirs = []
    for name in names:
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is not None:
            dirs += [Path(location) for location in (spec.submodule_search_locations or [])]
    return dirs


def hidden_roots(paths: list[Path], extra=()) -> list[Path]:
    """The home directory and, for each path, its highest ancestor owned by this
    user (e.g. /data/<user> for a checkout in it): the user's own directories."""
    roots = {Path.home().resolve()}
    uid = os.getuid()
    for path in paths:
        owned = None
        for parent in [Path(path).resolve(), *Path(path).resolve().parents]:
            try:
                if parent != Path("/") and parent.stat().st_uid == uid:
                    owned = parent
            except OSError:
                pass
        if owned is not None:
            roots.add(owned)
    roots |= {Path(p).expanduser().resolve() for p in extra}
    # Drop roots inside other roots: hiding the outer one hides them.
    return sorted(root for root in roots if not any(other in root.parents for other in roots))


def kernel_environment(options: dict, base: dict, python: str | None = None) -> dict:
    """The kernel's environment: basic variables, HOME in the empty home, and the
    API keys its model clients need (their URLs are resolved already: config/agent.py
    _role). `python` is the kernel's interpreter (default this one)."""
    names = set(_ENVIRONMENT)
    for config in _model_configs(options):
        names.add(config.get("api_key_env") or ("OPENROUTER_API_KEY"
                                                if config.get("backend", "openrouter") == "openrouter" else ""))
    if sys.platform == "win32":
        # What Python and its sockets need on Windows.
        names |= set(_WINDOWS_ENVIRONMENT)
    env = {name: base[name] for name in names if name and name.upper() != WORKER_APPROVAL_KEY and name in base}
    env["HOME"] = base.get("HOME", "/tmp")
    env["TMPDIR"] = "/tmp"
    # Packages installed for the user belong to the installation the kernel sees; their
    # directory depends on variables (APPDATA, HOME) the kernel does not keep. They are
    # this interpreter's: a kernel on another one (a bench's environment) gets none, or
    # it would import packages built for another Python.
    users = user_site() if python is None or same_interpreter(python) else None
    if users is not None:
        env["PYTHONPATH"] = os.pathsep.join([path for path in (env.get("PYTHONPATH"), str(users)) if path])
        env[USER_SITE_VARIABLE] = str(users)
    return env


def same_interpreter(python: str) -> bool:
    """Whether `python` is this interpreter."""
    try:
        return Path(python).resolve() == Path(sys.executable).resolve() or Path(python).samefile(sys.executable)
    except OSError:
        return False


# The host's user site-packages, as the kernel is told it (read_roots).
USER_SITE_VARIABLE = "HARNESS_USER_SITE"


def user_site() -> Path | None:
    """This interpreter's user site-packages when it uses one; in a kernel, the host's."""
    import site

    if os.environ.get(USER_SITE_VARIABLE):
        return Path(os.environ[USER_SITE_VARIABLE])
    if not site.ENABLE_USER_SITE:
        return None
    path = Path(site.getusersitepackages())
    return path if path.is_dir() else None


def endpoints(options: dict) -> set[tuple[str, int]]:
    """(host, port) of every service named in the kernel options."""
    from harness.runtime.decision.model import chat_url

    urls = []

    def scan(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("endpoint", "url", "base_url") and isinstance(item, str):
                    urls.append(item)
                else:
                    scan(item)
        elif isinstance(value, list):
            for item in value:
                scan(item)

    scan(options)
    urls += [chat_url(config.get("backend", "openrouter"), config.get("base_url"))
             for config in _model_configs(options)]
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if os.environ.get(name):
            urls.append(os.environ[name])
    result = set()
    for url in urls:
        parts = urlsplit(url if "://" in url else "http://" + url)
        if parts.hostname:
            result.add((parts.hostname, parts.port or _DEFAULT_PORTS.get(parts.scheme, 80)))
    return result


def _model_configs(options: dict) -> list[dict]:
    return [options[name] for name in ("vlm", "pointer", "verifier") if isinstance(options.get(name), dict)]


def install_network_guard(allowed: set[tuple[str, int]]) -> None:
    """Refuse connections to anything but `allowed`, and process creation and
    ctypes, for the rest of the process's life (audit hooks cannot be removed)."""
    import importlib

    for name in KERNEL_IMPORTS:
        try:
            importlib.import_module(name)
        except ImportError:
            pass  # not installed here; skills that need it report the error
    hosts = frozenset(host for host, _port in allowed)
    addresses: dict[str, set[int]] = {}

    def resolve():
        for host, port in allowed:
            try:
                infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except OSError:
                continue
            for info in infos:
                addresses.setdefault(info[4][0], set()).add(port)

    def permitted(address) -> bool:
        return (isinstance(address, tuple) and len(address) >= 2
                and address[1] in addresses.get(str(address[0]), ()))

    resolve()

    def hook(event, args):
        if event == "socket.getaddrinfo":
            if str(args[0]) not in hosts and str(args[0]) not in addresses:
                raise PermissionError(f"programs may not resolve {args[0]!r}")
        elif event == "socket.connect":
            if not permitted(args[1]):
                resolve()  # addresses of the allowed names may have changed
                if not permitted(args[1]):
                    raise PermissionError(f"programs may not connect to {args[1]!r}")
        elif event.startswith(_BLOCKED_EVENTS):
            raise PermissionError(f"programs may not use {event}")

    sys.addaudithook(hook)


def install_private_guard(paths: list, report) -> list[str]:
    """Refuse opening, listing and changing anything under `paths` (the worker's private
    files, e.g. a game's instance) for the rest of the process's life, with or without the
    rest of the isolation, and call `report(event, path)` first for each attempt (the
    trace records it). Paths are compared resolved and, on Windows, without case. Returns
    the guarded roots."""
    roots = tuple(dict.fromkeys(os.path.normcase(os.path.realpath(os.fspath(path))) for path in paths if path))
    if not roots:
        return []
    reporting = threading.local()

    def private(path) -> str | None:
        if isinstance(path, int) or path is None:
            return None
        resolved = os.path.normcase(os.path.realpath(os.fsdecode(path)))
        return resolved if any(resolved == root or resolved.startswith(root.rstrip(os.sep) + os.sep)
                               for root in roots) else None

    def refuse(event, path):
        if not getattr(reporting, "busy", False):
            reporting.busy = True
            try:
                report(event, path)
            except Exception:
                pass  # the refusal stands whether or not it could be recorded
            finally:
                reporting.busy = False
        raise PermissionError(f"programs may not open the worker's private files ({path!r})")

    def hook(event, args):
        if event == "open":
            hit = private(args[0])
            if hit is not None:
                refuse(event, hit)
        elif event in _PATH_EVENTS:
            for index in _PATH_EVENTS[event][0]:
                hit = private(args[index]) if index < len(args) else None
                if hit is not None:
                    refuse(event, hit)

    sys.addaudithook(hook)
    return list(roots)


def read_roots(source: list[Path]) -> list[Path]:
    """What a program may read: the Python installation (prefixes, site-packages),
    `source`, packages installed outside the prefix (KERNEL_PACKAGES) and system
    directories."""
    import site

    roots = [sys.prefix, sys.exec_prefix, sys.base_prefix, sys.base_exec_prefix, *site.getsitepackages(),
             *([user_site()] if user_site() else []), *source, *package_dirs(), *_SYSTEM_ROOTS]
    return [Path(root) for root in roots]


def _real(path) -> str:
    r"""The resolved path, in the plain form: on Windows realpath of a file reached through a
    junction (uv's Python is one: cpython-3.12 -> cpython-3.12.15) comes back as
    \\?\C:\..., while a directory's does not, so the two would never compare equal."""
    path = os.path.realpath(path)
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def install_file_guard(read: list[Path], write: list[Path]) -> None:
    """Refuse opening and listing anything but `read` and `write` (and this process in
    /proc), and changing anything but `write`, for the rest of the process's life. Paths
    are resolved first, so a link in the workspace does not lead out of it. The
    directories on sys.path may be listed (imports scan them), not read."""
    def real(paths):
        resolved = (_real(p) for p in paths)
        return tuple(dict.fromkeys(p for p in resolved if p != "/"))

    writable = real(write)
    readable = real(read) + writable + (f"/proc/{os.getpid()}",)
    listable = frozenset(real(entry or "." for entry in sys.path))
    proc_files = frozenset(_PROC_FILES)
    # Resolve the system mount, keeping the lock directory itself fixed so a
    # symlink cannot change the scope of the exception.
    lock_directory = (os.path.join(_real("/dev/shm"), "harness-locks")
                      if sys.platform.startswith("linux") and Path(SHARED_LOCK_DIR).parent == Path("/dev/shm")
                      else None)

    def inside(path, roots):
        return any(path == root or path.startswith(root + os.sep) for root in roots)

    def check(path, writes, lists=False):
        if isinstance(path, int) or path is None:
            return  # an open descriptor, or the working directory
        path = _real(os.fsdecode(path))
        if writes:
            if not inside(path, writable):
                raise PermissionError(f"programs may not change {path!r}")
        elif not (inside(path, readable) or path in proc_files or (lists and path in listable)):
            raise PermissionError(f"programs may not read {path!r}")

    def hook(event, args):
        if event == "open":
            path, mode, flags = args
            if (lock_directory and isinstance(path, (str, bytes)) and isinstance(flags, int)
                    and flags & os.O_NOFOLLOW and not flags & (os.O_TRUNC | os.O_APPEND)
                    and (not flags & os.O_CREAT or flags & os.O_EXCL)):
                parent, name = os.path.split(_real(os.fsdecode(path)))
                if parent == lock_directory and re.fullmatch(r"[a-z0-9._-]+[.]lock", name):
                    return
            writes = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                      or (isinstance(flags, int) and bool(flags & _WRITE_FLAGS)))
            check(path, writes)
        elif (lock_directory and event in ("os.mkdir", "os.chmod") and len(args) == 3
              and isinstance(args[0], (str, bytes)) and _real(os.fsdecode(args[0])) == lock_directory
              and args[2] == -1 and (event == "os.mkdir" or args[1] == 0o1777)):
            return
        elif event in _PATH_EVENTS:
            indices, writes = _PATH_EVENTS[event]
            for index in indices:
                if index < len(args):
                    check(args[index], writes, lists=event in ("os.listdir", "os.scandir"))

    sys.addaudithook(hook)
