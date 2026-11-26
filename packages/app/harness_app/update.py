"""/api/app/update: the desktop app's own update, between the page and the desktop shell.

The shell (packages/app/shell) checks, downloads and verifies the update with the Tauri updater
and installs it only when the owner clicks Restart to update (the page's button, the identity
menu, the tray). It holds no page of its own, so it reports here every second and takes what
the page asked for in the answer:

    GET                       what the page shows: this version, app.update, the shell's state
                              (checking, downloading with its progress, ready with the version,
                              error), a restart that waits and for what, a pip install's newest
                              release on PyPI
    POST {action: check}      check now (a pip install: PyPI, answered at once)
    POST {action: restart, chat, view, interrupt}
                              install and restart once nothing is at work (no identity busy in a
                              chat, no session running); interrupt: now, ending what runs. The
                              chat and view reopen after the restart
    POST {action: cancel}     the restart no longer waits
    POST {action: dismiss, version}
                              the button leaves the left column for that version (it stays in the
                              identity menu and the tray)
    POST {action: shell, state}
                              the shell's report; answered with {mode, requests, restart,
                              language}: language is general.language (system, zh or en),
                              which the tray's words follow as the page's do

A pip install has no shell: `harness update` updates it (harness/update.py)."""
import threading
import time

# Seconds after the shell's last report while it counts as present.
SHELL_SECONDS = 15.0
MODES = ("default", "start", "manual", "none")

_lock = threading.Lock()
_shell = {"state": None, "seen": 0.0}
_requests: list = []
_pending: dict | None = None
_last_chat: dict = {}


def reset() -> None:
    """Forget everything (a new host starts with nothing; tests)."""
    global _pending
    with _lock:
        _shell.update(state=None, seen=0.0)
        _requests.clear()
        _pending = None
        _last_chat.clear()


def _one(body, key, default=None):
    value = body.get(key, default)
    return value[0] if isinstance(value, list) else value


def mode(server) -> str:
    """app.update as config.toml has it (read raw: the shell asks every second)."""
    from harness.settings import read

    app = getattr(server, "app", None)
    try:
        value = (read(app.directory).get("app") or {}).get("update") if app is not None else None
    except Exception:
        value = None
    return value if value in MODES else "default"


def language(server) -> str:
    """general.language as config.toml has it: the page's language, which the shell's own
    words (the tray, its notifications) follow; system is the system's."""
    from harness.settings import read

    app = getattr(server, "app", None)
    try:
        value = (read(app.directory).get("general") or {}).get("language") if app is not None else None
    except Exception:
        value = None
    return value if value in ("zh", "en") else "system"


def busy(server) -> list:
    """What is at work: each identity's busy chats, and sessions running in the host."""
    rows = []
    service = (getattr(server, "background", None) or {}).get("agent")
    for name, life in list((getattr(service, "lives", None) or {}).items()):
        if getattr(life, "alive", True):
            rows += [{"identity": name, "chat": chat} for chat in sorted(getattr(life, "busy", ()) or ())]
    running = getattr(server, "running", None)
    if callable(running) and running():
        rows.append({"session": True})
    return rows


def _present(now=None) -> bool:
    return _shell["state"] is not None and (now or time.time()) - _shell["seen"] < SHELL_SECONDS


def _installer() -> str:
    from harness.update import bundled

    return "desktop" if _present() or bundled() else "pip"


def _dismissed(server):
    app = getattr(server, "app", None)
    try:
        return app.settings.remembered("app", "update_dismissed") if app is not None else None
    except Exception:
        return None


def view(server, pip=None) -> dict:
    from harness import __version__
    from harness.update import cached, newer

    installer = _installer()
    with _lock:
        shell = dict(_shell["state"]) if _present() else None
        pending = dict(_pending) if _pending else None
    answer = {"version": __version__, "mode": mode(server), "installer": installer, "shell": shell,
              "restart": pending, "busy": busy(server) if pending else [], "dismissed": _dismissed(server)}
    if installer == "pip":
        found = pip if pip is not None else cached()
        answer["pip"] = {**found, "newer": bool(found.get("version")) and newer(found["version"], __version__),
                         "command": "harness update"}
    return answer


def shell_report(server, state) -> dict:
    """The shell's report; its answer: the mode, the checks asked for, and the restart when it
    may happen now (nothing at work, or the owner chose to interrupt)."""
    global _pending
    state = state if isinstance(state, dict) else {}
    at_work = busy(server)
    with _lock:
        _shell.update(state=state, seen=time.time())
        requests = list(_requests)
        _requests.clear()
        restart = None
        if _pending and state.get("phase") == "ready" and (_pending.get("interrupt") or not at_work):
            restart = {key: _pending.get(key) for key in ("chat", "view", "interrupt")}
            _pending = None
    return {"mode": mode(server), "requests": requests, "restart": restart, "language": language(server)}


def update(server, body):
    global _pending
    action = _one(body, "action")
    chat = _one(body, "chat")
    if chat:
        _last_chat["chat"] = str(chat)
    if action == "shell":
        return shell_report(server, body.get("state"))
    if action == "check":
        if _installer() == "pip":
            from harness.update import latest

            return view(server, pip=latest(refresh=True))
        with _lock:
            if "check" not in _requests:
                _requests.append("check")
        return view(server)
    if action == "restart":
        with _lock:
            state = _shell["state"] if _present() else None
            if not state or state.get("phase") != "ready":
                raise ValueError("no update is ready to install")
            _pending = {"chat": str(chat or _last_chat.get("chat") or "main"), "view": _one(body, "view") or None,
                        "interrupt": bool(_one(body, "interrupt")), "asked": time.time(),
                        "version": state.get("version")}
        return view(server)
    if action == "cancel":
        with _lock:
            _pending = None
        return view(server)
    if action == "dismiss":
        app = getattr(server, "app", None)
        if app is not None:
            app.settings.remember("app", "update_dismissed", str(_one(body, "version") or "") or None)
        return view(server)
    if action:
        raise ValueError("action is check, restart, cancel, dismiss or shell")
    return view(server)
