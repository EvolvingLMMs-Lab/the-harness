"""External top-level sessions. The delegate registry stays in agents.py."""

import json
import os
from pathlib import Path
import shutil

from harness.sdk import home

from .acp import AcpSession, Peer
from . import registry
from .project import Project
from .terminal import TerminalSession
from .observe import ObservedSession, identity
from .cloud import CloudSession, PROVIDERS, cloud_list, configured_provider
from .hooks import receive as hook

api = {"hook": hook}
TERMINALS = {"terminal:aider": {"argv": ["aider"]}, "terminal:continue": {"argv": ["cn"]}}


def config_path():
    return home() / "external-agents.json"


def configured():
    path = config_path()
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, dict):
        raise ValueError("external-agents.json must map agent IDs to settings")
    return rows


def command(settings):
    argv = settings.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
        raise ValueError("an external agent needs a nonempty argv array")
    executable = shutil.which(argv[0])
    if executable is None:
        raise ValueError(f"the configured executable {argv[0]!r} is not installed")
    return [str(Path(executable).resolve()), *argv[1:]]


def environment(settings):
    common = ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
              "SYSTEMROOT", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")
    given = settings.get("env", [])
    if not isinstance(given, list) or any(not isinstance(name, str) or name.upper().startswith("HARNESS_")
                                         for name in given):
        raise ValueError("env must be a list of environment variable names outside HARNESS_*")
    fixed = settings.get("registry_env") or {}
    if any(not isinstance(name, str) or name.upper().startswith("HARNESS_") or not isinstance(value, str)
           for name, value in fixed.items()):
        raise ValueError("invalid registry environment")
    return {**{name: os.environ[name] for name in (*common, *given) if name in os.environ}, **fixed}


def agents():
    catalog = registry.catalog()
    rows = [{"id": f"acp:{identifier}", "name": row.get("name") or identifier,
             "kind": "acp", "version": row.get("version"), "source": "registry",
             "platform_available": bool(registry.distribution(row)[0]),
             "installed": bool(registry.installed(identifier)), "verified": False}
            for identifier, row in catalog.items()]
    rows.extend({"id": identifier, "name": identifier.split(":", 1)[-1], "kind": identifier.split(":", 1)[0],
                 "source": "custom", "installed": bool(isinstance(row, dict) and row.get("argv")
                                                      and shutil.which(row["argv"][0])),
                 "verified": False} for identifier, row in {**TERMINALS, **configured()}.items()
                if not identifier.startswith("cloud:"))
    rows.extend({"id": f"cloud:{name}", "name": name, "kind": "cloud", "source": "cloud",
                 "installed": f"cloud:{name}" in configured(), "verified": False} for name in PROVIDERS)
    return sorted(rows, key=lambda row: row["id"])


def session_adapter(name, directory, *, cwd, isolation, model, effort, restore=None, observe=None):
    if isinstance(name, str) and name.startswith("cloud:"):
        if cwd is not None or isolation or model or effort or restore:
            raise ValueError("configure the remote project and model in the cloud adapter")
        adapter = CloudSession(directory, name, configured_provider(name, configured().get(name)))
        if observe:
            adapter.identifier_to_observe = observe
            adapter.session_metadata.update(owner="external", observed=True, external_id=observe)
        return adapter
    if not isinstance(name, str) or not name.startswith(("acp:", "terminal:")):
        return None
    terminal = name.startswith("terminal:")
    settings = configured().get(name) or TERMINALS.get(name)
    if settings is None and not terminal:
        settings = registry.installed(name.removeprefix("acp:"))
    if not isinstance(settings, dict):
        raise ValueError(f"configure {name!r} in {config_path()} first")
    if cwd is None:
        raise ValueError("a local coding session needs a project directory")
    if observe is not None:
        if terminal:
            raise ValueError("select an ACP adapter to index its discovered session")
        session = ObservedSession(directory, None, name, False, observe, cwd, adapter=name)
        session.session_metadata.update(Project(cwd, None, directory.name).metadata())
        return session
    if restore is not None and terminal:
        raise ValueError("use an ACP adapter to recover a native session")
    if terminal and (model or effort):
        raise ValueError("choose the model or effort in the terminal agent itself")
    argv, env = command(settings), environment(settings)
    project = Project(cwd, isolation, directory.name)
    session = (TerminalSession(directory, name, project.cwd, argv, env) if terminal else
               AcpSession(directory, name, project.cwd, argv, model, effort, env, restore=restore))
    session.project = project
    if not terminal:
        session.auth_method = settings.get("auth_method")
    session.session_metadata.update(project.metadata())
    return session


def import_session(directory, provider, filename, follow):
    if provider not in ("claude-code", "codex"):
        raise ValueError("transcript format is claude-code or codex")
    path = Path(filename).expanduser().resolve(strict=True)
    if path.suffix.lower() != ".jsonl" or not path.is_file():
        raise ValueError("select one native JSONL transcript file")
    external_id, cwd = identity(path, provider)
    return ObservedSession(directory, path, provider, follow, external_id, cwd)


def discover_sessions(name, folder, cursor=None):
    if name.startswith("cloud:"):
        return cloud_list(configured_provider(name, configured().get(name)), cursor)
    if not name.startswith("acp:"):
        raise ValueError("select an ACP adapter")
    settings = configured().get(name) or registry.installed(name.removeprefix("acp:"))
    if not isinstance(settings, dict):
        raise ValueError("configure or install the selected adapter first")
    cwd = Path(folder).expanduser().resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("select a project directory")
    peer = Peer(command(settings), cwd, lambda message: None, lambda problem: None, environment(settings))
    peer.start()
    try:
        result = peer.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}}).result(20)
        capabilities = result.get("agentCapabilities") or {}
        if result.get("protocolVersion") != 1 or not (capabilities.get("sessionCapabilities") or {}).get("list"):
            raise ValueError("this ACP agent does not advertise session discovery")
        result = peer.request("session/list", {"cwd": str(cwd), **({"cursor": cursor} if cursor else {})}).result(20)
        return {"sessions": [{key: row[key] for key in ("sessionId", "title", "cwd", "updatedAt") if key in row}
                             for row in result.get("sessions", [])], "nextCursor": result.get("nextCursor")}
    finally:
        peer.close()
