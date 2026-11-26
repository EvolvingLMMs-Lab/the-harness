"""What the app package gives the session host (the core calls these by name,
harness/extensions.py, and imports nothing of this package):

    pages    the app at / (ui/static/)
    api      /api/app/<name> beside the core's own /api/app/... routes:
               found      what onboarding finds on this computer: model keys, a local Ollama,
                          an OpenClaw or Hermes agent to bring over
               onboard    POST {provider, model, base_url}: one test call with the key found
                          here; a working key is saved to the credentials file, then the model
               elsewhere  GET: the OpenClaw and Hermes agents on this computer; POST {kind}:
                          bring one over as a new identity (the agent package's take.py)
               persona    an identity's persona files (IDENTITY.md, SOUL.md, USER.md, MEMORY.md);
                          POST {identity, file, text} writes one
               skill      a skill's own files (SKILL.md and its program) for What it learned
               place      what a place chat works in: its folder's changes (git diff) and files
               about      the version, the identity's fingerprint and where its files are
               update     the desktop app's own update (update.py): what the page shows, and
                          the desktop shell's reports and the owner's Restart to update
    focus    bring the desktop shell's window to the front

The page reads and writes only the host's API; the agent's life runs in the host whether
or not a page is open."""
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

from .shell import focus  # noqa: F401  (extensions.focus)
from .update import update

pages = {"/": "index.html"}

STATIC = Path(__file__).resolve().parents[1] / "ui" / "static"
PERSONA = ("IDENTITY.md", "SOUL.md", "USER.md", "MEMORY.md")
# Bytes of a diff the Changes tab shows.
DIFF_LIMIT = 400_000


def _one(body, key, default=None):
    value = body.get(key, default)
    return value[0] if isinstance(value, list) else value


def _agent(name):
    """The agent package's API handler `name`, or None when that package is not here."""
    from harness.extensions import hosts

    for package, module in hosts():
        if package.name == "agent":
            return (getattr(module, "api", None) or {}).get(name)
    return None


def _life(server, identity):
    service = (getattr(server, "background", None) or {}).get("agent")
    if service is None:
        return None
    try:
        return service.life(identity)
    except Exception:
        return None


def _identity_row(server, identity):
    rows = (_agent("identities") or (lambda server, body: []))(server, {})
    chosen = identity or next((row["id"] for row in rows if row.get("current")), None)
    row = next((row for row in rows if row["id"] == chosen), None)
    if row is None:
        raise ValueError(f"no identity {chosen!r}")
    return row


def found(server, body):
    """What onboarding finds here. Keys are never sent to the page: only which ones are set."""
    from harness import providers

    app = getattr(server, "app", None)
    if app is not None:
        app.credentials.load()
    keys = []
    for provider in providers.PROVIDERS.values():
        if provider.key_env and os.environ.get(provider.key_env):
            source = app.credentials.status(provider.key_env).get("source") if app is not None else None
            keys.append({"provider": provider.id, "name": provider.name, "key_env": provider.key_env,
                         "saved": bool(source), "model": providers.DEFAULT["model"] if provider.id == "openrouter"
                         else None})
    local = []
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=0.6) as answer:
            local = [row.get("name") for row in json.load(answer).get("models") or [] if row.get("name")]
    except Exception:
        local = []
    agents = [row["kind"] for row in _elsewhere()]
    llm = app.llm() if app is not None else {"ready": False}
    return {"keys": keys, "ollama": local, "bring_over": agents, "llm": llm}


def onboard(server, body):
    """Step one of onboarding: the chosen model, tried once with the key found on this computer;
    only a working key is kept (in the credentials file: a host started at login cannot read
    the user's shell variables)."""
    from harness import providers

    app = getattr(server, "app", None)
    if app is None:
        raise ValueError("models are chosen in the session host")
    provider = providers.PROVIDERS.get(str(body.get("provider") or ""))
    if provider is None:
        raise ValueError("choose a provider")
    request = {"provider": provider.id, "model": str(body.get("model") or ""), "base_url": body.get("base_url") or None}
    if provider.key_env:
        app.credentials.load()
        key = str(body.get("key") or "").strip() or os.environ.get(provider.key_env) or ""
        if key and not app.credentials.status(provider.key_env).get("source"):
            request["key"] = key
        elif body.get("key"):
            request["key"] = key
    started = time.monotonic()
    result = app.set_model(request)
    return {**result, "seconds": round(time.monotonic() - started, 1)}


def _elsewhere() -> list:
    try:
        from harness_agent.take import found_elsewhere
    except ImportError:
        return []
    return found_elsewhere()


def elsewhere(server, body):
    """The OpenClaw and Hermes agents on this computer ("bring it over"); POST {kind}: a new
    identity from one: persona, memory and skills, never its channel tokens or keys."""
    kind = _one(body, "kind")
    if kind:
        from harness_agent.take import import_from

        return import_from(str(kind))
    return {"found": _elsewhere()}


def persona(server, body):
    row = _identity_row(server, _one(body, "identity"))
    folder = Path(row["folder"])
    if body.get("file") is not None and body.get("text") is not None:
        name = str(body["file"])
        if name not in PERSONA:
            raise ValueError(f"a persona file is one of {', '.join(PERSONA)}")
        (folder / name).write_text(str(body["text"]), encoding="utf-8")
    return {"identity": row["id"], "folder": f"agents/{row['id']}/",
            "files": [{"name": name, "text": (folder / name).read_text(encoding="utf-8")
                       if (folder / name).is_file() else ""} for name in PERSONA]}


def skill(server, body):
    """GET {identity, name}: the files of one of the identity's skills, as What it learned shows
    them when the item is opened."""
    row = _identity_row(server, _one(body, "identity"))
    name = Path(str(_one(body, "name") or "")).name
    folder = Path(row["folder"]) / "skills" / name
    if not name or not folder.is_dir():
        raise ValueError(f"no skill {name!r}")
    files = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix in (".md", ".py") and path.stat().st_size < 64_000:
            files.append({"name": path.name, "text": path.read_text(encoding="utf-8", errors="replace")})
    return {"name": name, "files": files}


def _place_folder(server, identity, chat):
    life = _life(server, identity)
    if life is None:
        return None
    meta = life.chats.meta(chat)
    place = life.places.get(meta.get("place")) if meta.get("place") else None
    if place is None and chat == "main":
        place = next((item for item in life.places.values() if getattr(item, "kind", None) == "folder"), None)
    row = getattr(place, "row", None) or {}
    folder = row.get("folder") if row.get("kind") == "folder" else None
    return Path(folder) if folder and Path(folder).is_dir() else None


def place(server, body):
    """GET {identity, chat}: the folder the chat's place works in, its changes and its files."""
    identity = _identity_row(server, _one(body, "identity"))["id"]
    folder = _place_folder(server, identity, _one(body, "chat") or "main")
    if folder is None:
        return {"folder": None, "diff": "", "files": []}
    diff = ""
    try:
        diff = subprocess.run(["git", "-C", str(folder), "diff", "HEAD"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15).stdout[:DIFF_LIMIT]
    except (OSError, subprocess.SubprocessError):
        diff = ""
    files = []
    for path in sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:300]:
        if path.name.startswith("."):
            continue
        files.append({"name": path.name, "dir": path.is_dir(), "size": None if path.is_dir() else path.stat().st_size,
                      "modified": path.stat().st_mtime})
    return {"folder": folder.name, "diff": diff, "files": files}


def about(server, body):
    from harness import __version__

    row = _identity_row(server, _one(body, "identity"))
    downloads = Path.home() / "Downloads"
    fingerprint = None
    try:
        from harness_agent.state import Identity

        fingerprint = Identity(row["id"], create=False).to_dict(verbose=True).get("fingerprint")
    except Exception:
        fingerprint = None
    return {"version": __version__, "identity": row["id"], "name": row.get("name"), "fingerprint": fingerprint,
            "folder": f"agents/{row['id']}/", "save_to": str(downloads if downloads.is_dir() else Path.home())}


api = {"found": found, "onboard": onboard, "elsewhere": elsewhere, "persona": persona, "skill": skill, "place": place, "about": about,
       "update": update}
