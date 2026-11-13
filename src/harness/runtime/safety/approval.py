"""Approvals: which steps wait for the user, and the words every frontend asks with.

Every command reaches the world through a shield (a worker's, the gate of another
harness's agent run as a sub-agent, an MCP tool's call), and some wait for the user first.
The core holds the mechanism only; what a step is, the side that performs it says, from
what it really acts on (the element under the pointer, a page's fields, a tool's
annotations, a command line):

- A sensitive step (one of SENSITIVE) always waits for the user, whatever the settings; the
  answer covers that one step only and is never remembered.
- The rest follows the settings: approvals.ask is sensitive (the default: only those wait)
  or programs (every program waits as well). The physical-input policy of a package that
  uses the user's real mouse and keyboard grades that input on top, per app and window.
- A sensitive step is refused when nobody can answer.

A request goes to the user as a `physical_request` record (its `sensitive` kind and
`target` in words, or the app and window of physical input); the conversation answers it
(confirm), in every frontend.

WORDS is one key table for every frontend: English with {placeholders}; the terminals
say() them, the pages get them in GET /api/info and translate by key."""

import hmac
import json
import re
import secrets


WORKER_APPROVAL_KEY = "HARNESS_WORKER_APPROVAL_KEY"
WORKER_APPROVAL_HEADER = "X-Harness-Worker-Approval"
APPROVAL_PIPE_FLAG = "--_approval-from-stdin"
APPROVAL_PIPE_FRAME = b"harness-worker-approval-v1 "
_HOST_PIPE_FRAME = b"harness-worker-host-pipe-v1 "
_PIPE_FRAME = APPROVAL_PIPE_FRAME


def worker_approval_proof(key: str, request: dict) -> str:
    """Authenticate one host approval RPC, including its operation and all arguments."""
    body = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hmac.digest(key.encode(), b"harness worker approval v1\0" + body, "sha256").hex()


def write_approval_key(pipe, key: str, *, host_pipe=False) -> None:
    """Send the key over the managed worker's private startup pipe."""
    prefix = _HOST_PIPE_FRAME if host_pipe else _PIPE_FRAME
    pipe.write(prefix + key.encode("ascii") + b"\n")
    pipe.flush()


def read_worker_startup(pipe) -> tuple[str, bool]:
    """Read one startup frame and leave the pipe positioned at its first request."""
    frame = pipe.readline(max(len(_PIPE_FRAME), len(_HOST_PIPE_FRAME)) + 65)
    for prefix in (_PIPE_FRAME, _HOST_PIPE_FRAME):
        if re.fullmatch(re.escape(prefix) + rb"[0-9a-f]{64}\n", frame):
            return frame[len(prefix):-1].decode("ascii"), prefix == _HOST_PIPE_FRAME
    raise ValueError("Invalid managed worker startup frame")


def read_approval_key(pipe) -> str:
    """Read the legacy approval startup key."""
    key, host_pipe = read_worker_startup(pipe)
    if host_pipe:
        raise ValueError("Expected an approval startup frame")
    return key


# The kinds of sensitive steps.
WORKER_APPROVAL_SECONDS = 300.0
SENSITIVE = ("credentials", "payment", "sending", "deleting", "irreversible")
# What the host itself asks the user through the same request: another environment for the
# conversation, sub-agents switched on (runtime/task/environments.py), a step of a program
# on the machine (runtime/safety/permissions.py). Never a worker's offer.
HOST_ASKS = ("environment", "agents", "program")
# The levels of what the host asks about, strictest first: never; ask every time; ask once
# per conversation and kind; allow (settings: environments.attach, approvals.programs).
LEVELS = ("never", "ask_each", "ask_once_session", "allow")
# The setting approvals.ask (settings.py).
ASK = ("sensitive", "programs")


def request(kind: str, target: str, actions=(), **detail) -> dict:
    """A sensitive step's request to the user: its kind (SENSITIVE), what it acts on in words."""
    if kind not in SENSITIVE + HOST_ASKS:
        raise ValueError(f"a sensitive step is one of {', '.join(SENSITIVE)}, not {kind!r}")
    return {**detail, "id": f"sensitive-{secrets.token_hex(8)}", "sensitive": kind,
            "target": str(target)[:300], "actions": [str(action) for action in actions]}


# doing.*: what a step does (a rule's actions); answer.* and allowed.*: one per REMEMBER value
# (runtime/safety/input.py), then the others; label.*: an app and a window as rules and requests name them.
WORDS = {
    "doing.pointer": "click", "doing.drag": "drag", "doing.keyboard": "press keys", "doing.clipboard": "type",
    "doing.foreground": "switch windows", "doing.other": "act",
    "request": "it wants to {doing} in {app}{window} with your mouse and keyboard",
    "asks": "agent {agent} of session {session} wants to use your mouse and keyboard: {what}",
    "sensitive": "it wants to do something that waits for you ({kind}): {target}",
    "sensitive.credentials": "credentials", "sensitive.payment": "a payment", "sensitive.sending": "sending",
    "sensitive.deleting": "deleting", "sensitive.irreversible": "a step that cannot be undone",
    "sensitive.environment": "another environment", "sensitive.agents": "sub-agents",
    "sensitive.program": "a step of its program on this computer",
    "answer.once": "allow this time", "answer.app": "{app} is fine for this chat",
    "answer.session": "anything is fine for this chat", "answer.always": "always allow {app}",
    "answer.no": "don't allow", "answer.later": "not now", "answer.why": "reason (optional, it will see this)",
    "allowed.once": "allowed this time", "allowed.app": "{app} is allowed for this chat",
    "allowed.session": "anything is allowed for this chat",
    "allowed.always": "{app} is always allowed now: a rule in your settings", "refused": "not allowed{reason}",
    "label.app": "app (e.g. wechat)", "label.window": "words in the window title", "label.that_app": "that app",
    "label.this_window": "this window", "label.the_window": "the window {title}",
}


def say(key: str, **values) -> str:
    """WORDS[key] with its placeholders filled in (one not given: nothing)."""
    return re.sub(r"\{(\w+)\}", lambda match: str(values.get(match.group(1), "") or ""), WORDS[key])


# The confirmation policies: never ask (evaluation), or ask before every program.
CONFIRMATION_POLICIES = ("never", "always")


def confirmation_policy(given: str | None = None) -> str:
    """The confirmation policy of a conversation a user starts, the same for every frontend
    (the app, terminal chat and RPC). Use the frontend's explicit choice `given`
    for this conversation, otherwise the settings' `approvals.ask`."""
    if given is not None:
        if given not in CONFIRMATION_POLICIES:
            raise ValueError(f"confirmation must be one of {CONFIRMATION_POLICIES}")
        return given
    from harness.paths import data
    from harness.settings import Settings

    try:
        asks = Settings(data()).get()["approvals"]["ask"] == "programs"
    except Exception:
        asks = False
    return "always" if asks else "never"
