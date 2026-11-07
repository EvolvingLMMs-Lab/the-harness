"""Processes and locks on this computer, one way for every package: whether a process runs
(pid_alive), a lock on a file across processes and threads (file_lock), a detached process (start_detached).

Standard library only.
"""

import contextlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

# Linux kernels have private temporary directories and share this directory for file locks.
SHARED_LOCK_DIR = os.path.join("/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir(),
                               "harness-locks")


# GetExitCodeProcess's code of a process that has not exited (Windows).
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_LIBRARY_INJECTION = ("LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES")


def service_environment(environment=None, log=None) -> dict:
    """Copy the environment for a service or installer, dropping inherited library injection.

    Keep library search paths and let the caller apply explicit service settings on top.
    Report only the removed names. Worker and desktop launchers keep their run environment.
    """
    result = dict(os.environ if environment is None else environment)
    removed = [name for name in _LIBRARY_INJECTION if name in result]
    for name in removed:
        del result[name]
    if removed and log is not None:
        log("Removed inherited library injection: " + ", ".join(removed))
    return result


def pid_alive(pid, *, reap: bool = False) -> bool:
    """Whether process `pid` runs on this computer. A process we may not query runs (access
    denied means it exists); this process runs; a zombie (exited, not yet reaped) does not,
    and with `reap` an exited child of this process is reaped. It never signals the process
    (os.kill(pid, 0) would send CTRL_C_EVENT on Windows)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.GetLastError() == _ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    if reap:
        try:
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                return False
        except ChildProcessError:
            pass  # not our child
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split(") ", 1)[1][:1] != "Z"
    except (OSError, IndexError):
        return True  # no /proc (macOS): it answered the signal check


def _open(path: Path, mode):
    """A descriptor of the lock file, created when missing (with `mode`'s permission bits,
    whatever the umask); read-only when another account's file cannot be opened for writing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = getattr(os, "O_BINARY", 0)
    if path.parent == Path(SHARED_LOCK_DIR):
        flags |= getattr(os, "O_NOFOLLOW", 0)
    for _ in range(10):
        # An existing file is opened without O_CREAT: in a sticky directory the kernel refuses
        # O_CREAT on another account's file (fs.protected_regular), even one that exists.
        try:
            return os.open(path, os.O_RDWR | flags)
        except PermissionError:
            return os.open(path, os.O_RDONLY | flags)
        except FileNotFoundError:
            pass
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | flags, 0o666 if mode is None else mode)
        except FileExistsError:
            continue  # another process created it in between (or a dangling symlink)
        if mode is not None and hasattr(os, "fchmod"):
            with contextlib.suppress(OSError):
                os.fchmod(descriptor, mode)
        return descriptor
    raise OSError(f"cannot open or create the lock file {path}")


def _try(descriptor) -> bool:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _unlock(descriptor) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        with contextlib.suppress(OSError):
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(path, *, blocking: bool = True, timeout: float | None = None, mode: int | None = None):
    """Hold an exclusive lock on the file at `path` while the block runs, across the
    processes and threads of this computer: fcntl.flock on POSIX, a lock on the file's first
    byte on Windows. The file is created when missing (`mode`: its permission bits). It waits
    for the lock, at most `timeout` seconds (then TimeoutError); without `blocking` it raises
    BlockingIOError at once when another holds it. The system releases the lock when its
    process ends, so a holder that died never leaves it behind."""
    descriptor = _open(Path(path), mode)
    try:
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        if blocking and deadline is None and sys.platform != "win32":
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        else:
            while not _try(descriptor):
                if not blocking:
                    raise BlockingIOError(f"{path} is locked by another process")
                if deadline is not None and time.monotonic() > deadline:
                    raise TimeoutError(f"{path} stayed locked for {timeout} s")
                time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(descriptor)
    finally:
        os.close(descriptor)


def start_detached(command, *, log: Path | None = None, popen=None, **options) -> subprocess.Popen:
    """`command` in a session (Windows: a process group, no window) of its own, its output appended to `log`."""
    detached = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                if os.name == "nt" else {"start_new_session": True})
    with open(log, "ab") if log is not None else contextlib.nullcontext(subprocess.DEVNULL) as out:
        return (popen or subprocess.Popen)(command, **{"stdin": subprocess.DEVNULL, "close_fds": True, "stdout": out,
                                                       "stderr": subprocess.DEVNULL if log is None else subprocess.STDOUT,
                                                       **detached, **options})
