"""What a program does on the machine it runs on, under the user's approvals.

A program of the model runs on the user's machine: it reads what the user can read. Three
kinds of step beyond its own folder go by the user's settings (approvals.programs and
approvals.rules; runtime/safety/approval.py holds the levels and the asking):

  command   it starts a process (the key of a rule and of "once": the program's name)
  network   it connects to a host that is not one of the environment's own services (the host)
  write     it creates, changes or moves a file outside its folder and the temporary
            directory (the folder written in)

Two are sensitive steps (approval.SENSITIVE), which always wait for the user and are refused
where nobody can answer: opening a file that holds credentials, and deleting outside its
folder.

In the kernel an audit hook sees each such step before it happens and asks the conversation
(install); there Programs decides: never refuses, allow lets it through, ask_each asks
every time, ask_once_session once per conversation and key. Where nobody can be asked (a
run without a user) and the level asks, the step is refused with the reason: it never
waits and is never allowed silently. A user who skips confirmations (their physical-input
level is allow) is not asked; never still refuses. Every decision is a record of the
trace (program_permission).

Isolation (runtime/safety/isolation.py) is the stricter setting of evaluations: there
programs reach only the installation, the source and the services, and nothing is asked.
"""

from fnmatch import fnmatchcase
import os
from pathlib import Path
import sys
import threading

from harness.runtime.safety.approval import LEVELS

ACTIONS = ("command", "network", "write")
DEFAULT_LEVEL = "ask_once_session"
# Folders and files that hold credentials, by name.
_CREDENTIAL_FOLDERS = frozenset((".ssh", ".aws", ".gnupg", ".kube", ".azure"))
_CREDENTIAL_FILES = frozenset((".env", ".netrc", ".git-credentials", ".harness_env", ".pypirc", "id_rsa", "id_ed25519",
                               "id_ecdsa", ".credentials.json"))
_PROCESS_EVENTS = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile",
                   "pty.spawn")
_DELETES = ("os.remove", "os.rmdir", "shutil.rmtree")


def credentials(path: str) -> bool:
    """Whether `path` is a file that holds credentials, by the names such files have."""
    parts = Path(path).parts
    name = parts[-1].lower() if parts else ""
    return (name in _CREDENTIAL_FILES or name.startswith(".env.")
            or any(part.lower() in _CREDENTIAL_FOLDERS for part in parts[:-1]))


def level_of(policy: dict, action: str, key: str) -> str:
    """The level of approval.LEVELS for a step: the first rule of `policy` ({"programs":
    level, "rules": [{level, action, match}]}) whose action is this one and whose match
    (a glob, without case) fits `key`; else the policy's level, else DEFAULT_LEVEL."""
    for rule in policy.get("rules") or ():
        if rule.get("action") == action and fnmatchcase(key.lower(), str(rule.get("match") or "*").lower()):
            return rule["level"]
    return policy.get("programs") or DEFAULT_LEVEL


def rules(value) -> list:
    """approvals.rules as kept: each {"level": one of LEVELS, "action": one of ACTIONS,
    "match": a glob on the program's name, the host or the folder}."""
    kept = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"level", "action", "match"}:
            raise ValueError("a rule is {level, action, match}")
        if row["level"] not in LEVELS:
            raise ValueError(f"a rule's level is one of {', '.join(LEVELS)}")
        if row["action"] not in ACTIONS:
            raise ValueError(f"a rule's action is one of {', '.join(ACTIONS)}")
        match = str(row["match"]).strip()
        if not match or len(match) > 200:
            raise ValueError("a rule's match is a glob of 1 to 200 characters: a program's name, a host or a folder")
        kept.append({"level": row["level"], "action": row["action"], "match": match})
    return kept


class Programs:
    """The steps of one conversation's programs on the machine (TaskRun.programs)."""

    def __init__(self, conversation):
        self.conversation = conversation
        self.granted = set()
        self._lock = threading.Lock()

    def handle(self, request: dict) -> dict:
        """Answer the kernel's question about one step: {"value": "session" (it need not
        ask again for this action and key) or "once"} or {"error": why it may not}."""
        conversation, trace = self.conversation, self.conversation.trace
        action, key, what = str(request.get("action")), str(request.get("key") or ""), str(request.get("what") or "")
        sensitive = request.get("sensitive")
        runtime = conversation.config.runtime
        policy = runtime.get("approvals") or {}
        level = "ask_each" if sensitive else level_of(policy, action, key)
        skips = (runtime.get("physical") or {}).get("level") == "allow" and not sensitive
        target = {"command": f"run the command {what}", "network": f"connect to {what}",
                  "write": f"write {what}"}.get(action, what) if not sensitive else what

        def decided(allowed, why="", asked=False):
            trace.emit("program_permission", action=action, key=key, what=what[:300], level=level, allowed=allowed,
                       asked=asked, **({"sensitive": sensitive} if sensitive else {}), **({"reason": why} if why else {}))
            if not allowed:
                return {"error": why}
            return {"value": "session" if level in ("allow", "ask_once_session") and not sensitive else "once"}

        if level == "never":
            return decided(False, f"the user's settings never allow a program to {target} (approvals). Go on "
                                  "without it and say what you could not do.")
        with self._lock:
            granted = (action, key) in self.granted
        if skips or level == "allow" or level == "ask_once_session" and granted:
            return decided(True)
        if not conversation.interactive:
            return decided(False, f"the user's settings ask before a program may {target} (approvals), and nobody "
                                  "can be asked in this run. Go on without it and say what you could not do.")
        accepted, reason = conversation._ask_user(sensitive or "program", target, action=action)
        if not accepted:
            return decided(False, f"the user did not allow the program to {target}" + (f": {reason}" if reason else "")
                           + ". Go on without it and say what you could not do.", asked=True)
        if level == "ask_once_session":
            with self._lock:
                self.granted.add((action, key))
        return decided(True, asked=True)


def install(allowed: set, writable: list, ask) -> None:
    """In the kernel: before a program starts a process, connects to a host outside
    `allowed` ((host, port) of the environment's services), changes a file outside
    `writable`, or opens a file of credentials, ask the conversation: `ask(action=, key=,
    what=, sensitive=)` gives "session" or "once", None when the question was interrupted,
    and raises ValueError with the reason when the step may not be. The harness's own
    threads (those alive now: they serve the answers) are not asked."""
    import socket

    own = frozenset(thread.ident for thread in threading.enumerate())
    asking = threading.local()
    granted, names = set(), {}
    addresses = {}

    def real(path) -> str:
        return os.path.normcase(os.path.realpath(os.fsdecode(path)))

    roots = tuple(dict.fromkeys(real(path) for path in writable))

    def resolve():
        for host, port in allowed:
            try:
                infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except OSError:
                continue
            for info in infos:
                addresses.setdefault(info[4][0], set()).add(port)

    asking.busy = True
    try:
        resolve()
    finally:
        asking.busy = False

    def decide(action, key, what, sensitive=None):
        if getattr(asking, "busy", False) or threading.get_ident() in own:
            return
        if sensitive is None and (action, key) in granted:
            return
        asking.busy = True
        try:
            answer = ask(action=action, key=key, what=what, **({"sensitive": sensitive} if sensitive else {}))
        except (ValueError, RuntimeError) as error:
            raise PermissionError(str(error)) from None
        finally:
            asking.busy = False
        if answer is None:
            raise PermissionError("the question whether this step is allowed was interrupted")
        if answer == "session":
            granted.add((action, key))

    def outside(path) -> str | None:
        if isinstance(path, int) or path is None:
            return None
        resolved = real(path)
        if "__pycache__" in resolved.split(os.sep):
            return None   # the interpreter's own compiled modules
        return None if any(resolved == root or resolved.startswith(root.rstrip(os.sep) + os.sep)
                           for root in roots) else resolved

    def command(event, args):
        if event == "os.system":
            line = os.fsdecode(args[0])
        elif event == "subprocess.Popen":
            line = args[1] if isinstance(args[1], (str, bytes)) else " ".join(map(os.fsdecode, args[1] or [args[0]]))
            line = os.fsdecode(line)
        else:
            # (os.exec: path, args; os.spawn: mode, path, args; os.posix_spawn: path, argv; os.startfile: path)
            line = os.fsdecode(next((part for part in args if isinstance(part, (str, bytes, os.PathLike))), ""))
        first = line.split()[0] if line.split() else ""
        name = os.path.basename(first.strip("\"'")).lower()
        decide("command", name.removesuffix(".exe"), line[:300])

    def hook(event, args):
        if event == "socket.getaddrinfo":
            if isinstance(args[0], str):
                asking.name = args[0]   # the name the next addresses of this thread stand for
        elif event == "socket.connect":
            address = args[1]
            if not (isinstance(address, tuple) and len(address) >= 2):
                return   # a local socket
            host, port = str(address[0]), address[1]
            if port in addresses.get(host, ()):
                return
            name = names.setdefault(host, getattr(asking, "name", None) or host)
            decide("network", name, f"{name}:{port}")
        elif event.startswith(_PROCESS_EVENTS):
            command(event, args)
        elif event == "open":
            path, mode, flags = args
            if isinstance(path, int) or path is None:
                return
            writes = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                      or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT
                                                                   | os.O_APPEND | os.O_TRUNC))))
            if credentials(os.fsdecode(path)):
                decide("read", real(path), f"open {os.fsdecode(path)}, which holds credentials", "credentials")
            elif writes:
                beyond = outside(path)
                if beyond is not None:
                    decide("write", os.path.dirname(beyond), beyond)
        elif event in _DELETES:
            beyond = outside(args[0])
            if beyond is not None:
                decide("write", beyond, f"delete {beyond}", "deleting")
        elif event in ("os.mkdir", "os.rename", "os.link", "os.symlink", "os.truncate", "os.chmod", "os.chown"):
            for path in args[:2] if event in ("os.rename", "os.link") else args[:1]:
                beyond = outside(path) if isinstance(path, (str, bytes, os.PathLike)) else None
                if beyond is not None:
                    decide("write", os.path.dirname(beyond), beyond)

    sys.addaudithook(hook)
