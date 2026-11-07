"""Launch the isolated Python kernel for workspace proposals."""

from contextlib import contextmanager
import errno
from pathlib import Path
import platform
import tempfile

from harness.sdk import PACKAGE, linux_sandbox


def _program_python():
    for path in (Path("/usr/local/bin/python3.11"), Path("/usr/bin/python3.11"), Path("/usr/bin/python3")):
        if not path.is_file() or path.stat().st_uid != 0:
            continue
        return str(path)
    raise RuntimeError("Managed workspaces require system Python 3.11 or newer")


@contextmanager
def program_command(options):
    """The proposal kernel receives only the protocol pipes and its fixed options."""
    import json

    linux_sandbox.require_linux()
    if platform.machine() not in ("x86_64", "aarch64"):
        raise RuntimeError("Managed proposal isolation requires x86-64 or ARM64 Linux")
    bootstrap = Path(__file__).resolve().with_name("managed_program.py")
    bootstrap_dir = "/harness-bootstrap"
    with _program_filter() as fd:
        command = [_program_python(), "-B", "-u", "-m", "harness.runtime.execution.kernel",
                   "--bootstrap", "managed_program:ManagedProgram", "--forward-workspace-requests",
                   "--options", json.dumps(options)]
        env = {"PYTHONPATH": f"{PACKAGE.parent}:{bootstrap_dir}", "HARNESS_PACKAGE_ROOTS": ""}
        launch = linux_sandbox.bubblewrap_command((PACKAGE,), env)
        launch += ["--ro-bind", str(bootstrap), f"{bootstrap_dir}/{bootstrap.name}"]
        yield launch + ["--seccomp", str(fd), "--", *command], (fd,)


@contextmanager
def _program_filter():
    """Deny network and process-handle access and creation of nested user namespaces."""
    import ctypes as c

    try:
        lib = c.CDLL("libseccomp.so.2")
    except OSError:
        raise RuntimeError("Managed workspace isolation requires libseccomp") from None
    lib.seccomp_init.argtypes, lib.seccomp_init.restype = [c.c_uint32], c.c_void_p
    lib.seccomp_release.argtypes = [c.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes = [c.c_char_p]
    lib.seccomp_rule_add.argtypes = [c.c_void_p, c.c_uint32, c.c_int, c.c_uint]
    lib.seccomp_export_bpf.argtypes = [c.c_void_p, c.c_int]

    class Argument(c.Structure):
        _fields_ = [("index", c.c_uint), ("op", c.c_int), ("mask", c.c_uint64), ("value", c.c_uint64)]

    lib.seccomp_rule_add_array.argtypes = [c.c_void_p, c.c_uint32, c.c_int, c.c_uint, c.POINTER(Argument)]
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("Could not initialize the managed kernel filter")
    try:
        for name in (b"socket", b"socketpair", b"connect", b"ptrace", b"process_vm_readv",
                     b"process_vm_writev", b"pidfd_getfd", b"io_uring_setup", b"bpf", b"unshare", b"setns"):
            syscall = lib.seccomp_syscall_resolve_name(name)
            if syscall == -1 or lib.seccomp_rule_add(context, 0x00050000 | errno.EPERM, syscall, 0) != 0:
                raise RuntimeError("Could not install the managed kernel filter")
        # glibc falls back to clone for threads when clone3 is unavailable. On the
        # supported architectures clone's first argument is its flags.
        clone3 = lib.seccomp_syscall_resolve_name(b"clone3")
        clone = lib.seccomp_syscall_resolve_name(b"clone")
        new_user = 0x10000000
        condition = Argument(0, 7, new_user, new_user)  # SCMP_CMP_MASKED_EQ
        if (clone3 == -1 or clone == -1
                or lib.seccomp_rule_add(context, 0x00050000 | errno.ENOSYS, clone3, 0)
                or lib.seccomp_rule_add_array(context, 0x00050000 | errno.EPERM, clone, 1, c.byref(condition))):
            raise RuntimeError("Could not prevent nested user namespaces")
        with tempfile.TemporaryFile() as stream:
            if lib.seccomp_export_bpf(context, stream.fileno()) != 0:
                raise RuntimeError("Could not export the managed kernel filter")
            stream.seek(0)
            yield stream.fileno()
    finally:
        lib.seccomp_release(context)
