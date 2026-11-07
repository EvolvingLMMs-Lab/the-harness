"""Launch the isolated Linux browser or display worker."""

import os
from pathlib import Path
import secrets

from harness.sdk import PACKAGE, linux_sandbox


def worker_command(command, *, python, packages, options, executables=None, desktop_identity=None):
    """Dedicated display or browser, with offline egress and no desktop or host sockets."""
    interpreter = Path(python).absolute()
    prefixes = {interpreter.parents[1], interpreter.resolve().parents[1]}
    if Path("/") in prefixes:
        raise ValueError("The managed worker needs a dedicated interpreter prefix")
    paths = {PACKAGE, *prefixes, *packages}
    for item in ("/etc/fonts", "/opt/google/chrome"):
        if Path(item).is_dir():
            paths.add(Path(item))
    if options is not None:
        paths.add(options)
    roots = os.pathsep.join(map(str, packages))
    env = {"PYTHONPATH": os.pathsep.join((str(PACKAGE.parent), roots)), "HARNESS_PACKAGE_ROOTS": roots,
           "HARNESS_MANAGED_LINUX_WORKER": "1"}
    for name, value in (executables or {}).items():
        if not value:
            continue
        executable = Path(value).resolve(strict=True)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"{name} must name an executable")
        paths.add(executable.parent)
        env[name] = str(executable)
    launch = linux_sandbox.bubblewrap_command(paths, env)
    if desktop_identity is not None:
        # D-Bus needs to resolve the workspace UID. Give the display's private bus
        # a synthetic account and machine ID without mounting the host databases.
        uid, gid = os.getuid(), os.getgid()
        files = {"passwd": f"workspace:x:{uid}:{gid}:Workspace:/tmp/home:/bin/sh\n",
                 "group": f"workspace:x:{gid}:\n", "machine-id": secrets.token_hex(16) + "\n"}
        for name, content in files.items():
            path = desktop_identity / name
            path.write_text(content, encoding="ascii")
            launch += ["--ro-bind", str(path), f"/etc/{name}"]
    return launch + ["--", *command]
