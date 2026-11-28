"""External top-level sessions. The delegate registry stays in agents.py."""

import json
import re
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


def _unwrap_windows_node_cmd(executable: Path) -> list[str] | None:
    """Bypass Windows `.cmd`/`.bat` -> `powershell.exe` launchers (such as Cursor's
    `cursor-agent.cmd`) when a self-contained `node.exe` + `index.js` ships beside them.
    Under consoleless Windows GUI hosts (`windows_subsystem = "windows"`), `powershell.exe -File`
    with a redirected stdin pipe hangs on `initialize`, whereas invoking `node.exe index.js`
    directly speaks ACP over stdio reliably and cuts startup latency in half."""
    if os.name != "nt" or executable.suffix.lower() not in (".cmd", ".bat"):
        return None
    folder = executable.parent
    direct_node, direct_js = folder / "node.exe", folder / "index.js"
    if direct_node.is_file() and direct_js.is_file():
        return [str(direct_node), str(direct_js)]
    versions_dir = folder / "versions"
    if versions_dir.is_dir():
        candidates = sorted(
            (d for d in versions_dir.iterdir()
             if d.is_dir() and (d / "node.exe").is_file() and (d / "index.js").is_file()),
            key=lambda d: d.name,
            reverse=True,
        )
        if candidates:
            return [str(candidates[0] / "node.exe"), str(candidates[0] / "index.js")]
    return None


def command(settings):
    argv = settings.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
        raise ValueError("an external agent needs a nonempty argv array")
    executable = shutil.which(argv[0])
    if executable is None:
        raise ValueError(f"the configured executable {argv[0]!r} is not installed")
    resolved = Path(executable).resolve()
    unwrapped = _unwrap_windows_node_cmd(resolved)
    if unwrapped is not None:
        return [*unwrapped, *argv[1:]]
    return [str(resolved), *argv[1:]]


def environment(settings):
    common = ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
              "SYSTEMROOT", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
              "NODE_COMPILE_CACHE", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy")
    given = settings.get("env", [])
    if not isinstance(given, list) or any(not isinstance(name, str) or name.upper().startswith("HARNESS_")
                                         for name in given):
        raise ValueError("env must be a list of environment variable names outside HARNESS_*")
    fixed = settings.get("registry_env") or {}
    if any(not isinstance(name, str) or name.upper().startswith("HARNESS_") or not isinstance(value, str)
           for name, value in fixed.items()):
        raise ValueError("invalid registry environment")
    return {**{name: os.environ[name] for name in (*common, *given) if name in os.environ}, **fixed}


def _cli_settings(identifier: str) -> dict | None:
    """Settings for a built-in AgentCli that speaks ACP natively (e.g. `agy acp`)."""
    from harness import providers

    known = providers.AGENTS.get(identifier)
    if known is None or not known.acp_args:
        return None
    exe = providers.which_agent(known.executable)
    return {"argv": [exe, *known.acp_args], "env": []} if exe else None


def _acp_settings(name: str) -> dict | None:
    short = str(name).removeprefix("acp:")
    return configured().get(name) or registry.installed(short) or _cli_settings(short)


def agents():
    from harness import providers

    catalog = registry.catalog()
    rows = [{"id": f"acp:{identifier}", "name": row.get("name") or identifier,
             "kind": "acp", "version": row.get("version"), "source": "registry",
             "platform_available": bool(registry.distribution(row)[0]),
             "installed": bool(registry.installed(identifier)), "verified": False}
            for identifier, row in catalog.items()]
    listed = {row["id"] for row in rows}
    for agent in providers.AGENTS.values():
        identifier = f"acp:{agent.id}"
        if agent.acp_args and identifier not in listed:
            listed.add(identifier)
            rows.append({"id": identifier, "name": agent.name, "kind": "acp", "source": "cli",
                         "platform_available": True, "installed": bool(registry.installed(agent.id)), "verified": False})
    rows.extend({"id": identifier, "name": identifier.split(":", 1)[-1], "kind": identifier.split(":", 1)[0],
                 "source": "custom", "installed": bool(isinstance(row, dict) and row.get("argv")
                                                      and shutil.which(row["argv"][0])),
                 "verified": False} for identifier, row in {**TERMINALS, **configured()}.items()
                if not identifier.startswith("cloud:"))
    rows.extend({"id": f"cloud:{name}", "name": name, "kind": "cloud", "source": "cloud",
                 "installed": f"cloud:{name}" in configured(), "verified": False} for name in PROVIDERS)
    return sorted(rows, key=lambda row: row["id"])


def agent_add(name, argv, env=(), terminal=False) -> str:
    """Trust a command of the user's own as an agent: one that speaks ACP (acp:custom/<name>),
    or with `terminal` a command line driven in a terminal (terminal:<name>). Its id."""
    from harness.sdk import atomic_write

    if not registry.ID.fullmatch(str(name)):
        raise ValueError("an agent's name is lowercase letters, digits, dots, hyphens or underscores")
    identifier = ("terminal:" if terminal else "acp:custom/") + name
    settings = {"argv": [str(word) for word in argv], "env": [str(word) for word in env or ()]}
    command(settings)
    environment(settings)
    atomic_write(config_path(), json.dumps({**configured(), identifier: settings}, indent=2), private=True)
    return identifier


def agent_remove(identifier) -> None:
    """Forget a configured agent, or remove the installed adapter of a registry agent."""
    from harness.sdk import atomic_write

    rows = configured()
    if identifier in rows:
        del rows[identifier]
        atomic_write(config_path(), json.dumps(rows, indent=2), private=True)
        return
    short = str(identifier).removeprefix("acp:")
    if registry.installed(short) is None:
        raise ValueError("no such agent is configured or installed")
    (registry.root() / "installed" / f"{short}.json").unlink()


def agents_refresh() -> int:
    """Read the ACP Registry again: how many agents it lists."""
    return registry.refresh()


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
        settings = _acp_settings(name)
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


def model_backend(config):
    """The transport of a model role whose backend is "acp" (its `agent`: an installed or
    configured ACP agent), or None for another backend."""
    if config.get("backend") != "acp":
        return None
    name = config.get("agent")
    if not isinstance(name, str) or not name.startswith("acp:"):
        raise ValueError("an acp model role names its agent: agent = \"acp:<id>\"")
    settings = _acp_settings(name)
    if not isinstance(settings, dict):
        raise ValueError(f"connect {name!r} first (harness agents add {name.removeprefix('acp:')}) "
                         f"or configure it in {config_path()}")
    from .model import AcpModel

    return AcpModel(config, command(settings), environment(settings), settings.get("auth_method"))


def agent_ready(name, log=None):
    """Have the ACP agent `name` ("acp:<id>") ready to be started: one the user configured is
    taken as it is; one of the ACP Registry gets its pinned adapter installed when it is not
    (the catalog is fetched when it was never saved). A ValueError says what is missing."""
    log = log or (lambda message: None)
    identifier = str(name).removeprefix("acp:")
    if configured().get(name) or registry.installed(identifier):
        return
    cli = _cli_settings(identifier)
    if cli is not None:
        from harness.sdk import atomic_write

        atomic_write(registry.root() / "installed" / f"{identifier}.json", json.dumps(cli), private=True)
        return
    if identifier not in registry.catalog():
        log("reading the ACP Registry")
        registry.refresh()
    if identifier not in registry.catalog():
        raise ValueError(f"the ACP Registry has no agent {identifier!r}: harness agents list --registry lists them, "
                         "harness agents add NAME -- COMMAND adds one of your own")
    log(f"installing the adapter that connects {registry.catalog()[identifier].get('name') or identifier}")
    registry.install(identifier)


def agent_sign_in(name, method=None, timeout=900.0):
    """Signing in to the ACP agent `name` ("acp:<id>", ready here) through the agent itself,
    as Zed offers an agent's authentication methods: no command line of the agent has to be
    installed for it, and nothing of the sign-in is read or kept here.

    Without `method`: the ways it offers that need nothing typed here, [{id, name,
    description}] (one that takes an API key or a gateway is set in the agent's own
    settings). With `method`: that one, now; the agent opens what it needs (a page in the
    browser) and this returns once its user is through: {"signed_in": True, "method"}.
    A ValueError says why it could not be done."""
    import tempfile

    from .acp import Peer

    settings = _acp_settings(name)
    if not isinstance(settings, dict):
        raise ValueError(f"{name} is not connected here (harness agents add)")
    # (the agent may still hold its folder for a moment after it is closed: Windows refuses to remove it then)
    with tempfile.TemporaryDirectory(prefix="harness-acp-sign-in-", ignore_cleanup_errors=True) as folder:
        peer = Peer(command(settings), folder, lambda message: None, lambda problem: None, environment(settings))
        peer.start()
        try:
            answer = peer.request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                                 "clientInfo": {"name": "the-harness", "version": "1"}}).result(30)
            # the ways that need nothing typed here: one that takes a key or a gateway (it says so in
            # its _meta, or in its own words) is set in the agent's own settings
            offered = [row for row in answer.get("authMethods") or [] if isinstance(row, dict) and row.get("id")
                       and not any(key in (row.get("_meta") or {}) for key in ("api-key", "gateway"))
                       and not re.search(r"api key|gateway", f"{row.get('name')} {row.get('description')}", re.I)]
            if method is None:
                return [{"id": row["id"], "name": str(row.get("name") or row["id"]),
                         "description": str(row.get("description") or "")} for row in offered]
            if method not in {row["id"] for row in offered}:
                raise ValueError(f"{name} offers no way to sign in called {method!r}: " +
                                 (", ".join(row["id"] for row in offered) or "it offers none through here"))
            try:
                peer.request("authenticate", {"methodId": method}).result(timeout)
            except TimeoutError:
                raise ValueError("the sign-in was not finished in time: start it again and go through the page it opens") from None
            except RuntimeError as error:
                raise ValueError(f"the agent did not sign in: {error}") from None
            return {"signed_in": True, "method": method}
        finally:
            peer.close()


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
    settings = _acp_settings(name)
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
