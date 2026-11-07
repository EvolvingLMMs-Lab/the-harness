"""Common Linux namespace launch and process-handle protection."""

import os
from pathlib import Path
import stat
import sys


def _trusted_bwrap():
    configured = os.environ.get("HARNESS_BWRAP")
    path = Path(configured or "/usr/bin/bwrap")
    if not path.is_absolute():
        raise ValueError("HARNESS_BWRAP must be an absolute path")
    path = path.resolve(strict=True)
    trusted_owners = {0, os.geteuid()} if configured else {0}
    for item in (path, *path.parents):
        metadata = item.stat()
        if metadata.st_uid not in trusted_owners or metadata.st_mode & (stat.S_ISUID | stat.S_ISGID | 0o022):
            raise PermissionError("The Bubblewrap executable or its parent directory is not trusted")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("The Bubblewrap path is not executable")
    return str(path)


def require_linux():
    if sys.platform != "linux" or os.geteuid() == 0:
        raise RuntimeError("Managed workspaces require unprivileged Linux")
    try:
        return _trusted_bwrap()
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Managed workspaces require a trusted Bubblewrap executable: {error}") from None


def bubblewrap_command(paths, env):
    """Start an offline namespace with only explicitly mounted runtime paths."""
    # Explicit flags fail if a namespace cannot be created. Never share the host network.
    launch = [require_linux(), "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
              "--new-session", "--die-with-parent", "--cap-drop", "ALL", "--clearenv",
              "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/dev/shm", "--tmpfs", "/tmp",
              "--dir", "/tmp/home", "--perms", "0700", "--dir", "/tmp/run", "--chdir", "/tmp/home"]
    system = ("/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache")
    for item in sorted({str(path) for path in paths} | {path for path in system if Path(path).exists()}):
        launch += ["--ro-bind", item, item]
    for key, value in {"PATH": "/usr/bin:/bin", "HOME": "/tmp/home", "XDG_RUNTIME_DIR": "/tmp/run",
                       "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", **env}.items():
        launch += ["--setenv", key, value]
    return launch


def protect_process_handles():
    """Prevent other processes in the namespace from opening this process's descriptors."""
    import ctypes

    if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
        raise RuntimeError("Could not protect the managed worker's process handles")
