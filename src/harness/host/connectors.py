"""What the user connects the harness to, managed the same way from every frontend: each
class can be listed, added, removed and tested.

    MCP servers        [[connectors]] of config.toml (services/connectors.py reads them for a
                       conversation): a name with a command or a URL. Tested by connecting
                       once and listing its tools.
    external agents    agents that speak the Agent Client Protocol: the command lines found on
                       this computer, the ACP Registry's, and a command of the user's own (the
                       package that connects them is installed on first use). Tested by asking
                       one for one word, as the first run does (onboarding.tryout).

The other two classes belong to an agent identity and are the agent package's: chat channels
(/api/agent/channels) and skill sources (/api/agent/skill_sources).

These functions are the Python API (harness.sdk.connectors), what harness mcp and harness
agents call, and what the host's routes /api/app/mcp and /api/app/agents answer with.
A secret (the value of an environment variable or of a header) is kept with the credentials
and never listed.

Standard library only.
"""

import re
import time
from pathlib import Path

from ..problems import Problem

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def _settings(directory=None):
    from ..paths import data
    from ..settings import Credentials, Settings

    directory = Path(directory) if directory else data()
    return Settings(directory), Credentials(directory)


# -- MCP servers ---------------------------------------------------------------------------

def _secret_name(name: str, key: str) -> str:
    # The name services/connectors.py reads a record's secret under.
    return f"HARNESS_MCP_{name.upper().replace('-', '_')}_{key}"


def _field(key: str) -> str:
    """The placeholder name of a secret: its key in capitals, digits and _."""
    return re.sub(r"[^A-Z0-9]", "_", key.upper())


def mcp_row(record: dict) -> dict:
    """An MCP server as a frontend lists it (no secret is in it)."""
    stdio = record.get("transport") == "stdio"
    return {"name": record.get("id"), "title": record.get("name") or record.get("id"),
            "transport": record.get("transport"),
            "target": " ".join([str(record.get("command") or ""), *map(str, record.get("args") or ())]).strip()
            if stdio else str(record.get("url") or ""),
            "enabled": bool(record.get("enabled", True)), "env": sorted(record.get("env") or {}),
            "headers": sorted(record.get("headers") or {}), "tools": list(record.get("allowed_tools") or ()),
            "tools_off": list(record.get("tools_off") or ()), "from": "catalog" if record.get("catalog") else "added"}


def mcp_servers(directory=None) -> list:
    """The MCP servers the user connected: [{name, title, transport, target, enabled, env,
    headers, tools, tools_off, from}]."""
    settings, _ = _settings(directory)
    return [mcp_row(record) for record in settings.get().get("connectors", []) if isinstance(record, dict)]


def _record(settings, name: str) -> dict:
    record = next((row for row in settings.get().get("connectors", []) if row.get("id") == name), None)
    if record is None:
        raise Problem(f"no MCP server called {name!r}", "harness mcp list shows the ones there are",
                      code="no_mcp_server")
    return record


def mcp_add(name: str, *, command=None, args=(), url=None, env=None, headers=None, tools=None, title=None,
            timeout=None, directory=None) -> dict:
    """Connect an MCP server: `command` (and `args`) for one started on this computer over
    stdio, or `url` for one over streamable HTTP. `env` and `headers` are kept as secrets.
    `tools`: the tools conversations may call (default: all of it; a list names them).
    The server as listed. Nothing is started until it is tested or a conversation uses it."""
    name = str(name or "").strip()
    if not NAME.fullmatch(name):
        raise Problem(f"{name!r} cannot name an MCP server", "use lowercase letters, digits and hyphens, at most 40",
                      code="mcp_name")
    if bool(command) == bool(url):
        raise Problem("an MCP server is either a command or a URL", "give its command (after --) for one that runs "
                      "here, or its http(s) address", code="mcp_target")
    if url and not str(url).startswith(("http://", "https://")):
        raise Problem(f"{url!r} is not an http(s) address", "an MCP server's address starts with http:// or https://",
                      code="mcp_target")
    settings, credentials = _settings(directory)
    records = [row for row in settings.get().get("connectors", []) if isinstance(row, dict)]
    if any(row.get("id") == name for row in records):
        raise Problem(f"an MCP server called {name!r} is there already", f"remove it first (harness mcp remove "
                      f"{name}), or pick another name", code="mcp_exists")
    record = {"id": name, "name": str(title or name), "enabled": True,
              "allowed_tools": ["*"] if tools is None else [str(tool) for tool in tools]}
    if timeout is not None:
        record["timeout_seconds"] = float(timeout)
    secrets = {}
    for kind, given in (("env", env), ("headers", headers)):
        if given:
            record[kind] = {}
            for key, value in dict(given).items():
                secrets[_field(key)] = str(value)
                record[kind][str(key)] = "{" + _field(key) + "}"
    if secrets:
        record["secrets"] = sorted(secrets)
    if command:
        record.update(transport="stdio", command=str(command), args=[str(arg) for arg in args or ()])
    else:
        record.update(transport="http", url=str(url))
    for key, value in secrets.items():
        credentials.keep(_secret_name(name, key), value)
    settings.put("connectors", [*records, record])
    return mcp_row(record)


def mcp_remove(name: str, directory=None) -> dict:
    """Disconnect an MCP server and forget its secrets."""
    settings, credentials = _settings(directory)
    record = _record(settings, name)
    for key in record.get("secrets") or ():
        credentials.keep(_secret_name(name, key), None)
    settings.put("connectors", [row for row in settings.get().get("connectors", []) if row.get("id") != name])
    return {"removed": name}


def mcp_enable(name: str, on: bool = True, directory=None) -> dict:
    """Switch an MCP server on or off without removing it."""
    settings, _ = _settings(directory)
    _record(settings, name)
    records = [{**row, "enabled": bool(on)} if row.get("id") == name else row
               for row in settings.get().get("connectors", [])]
    settings.put("connectors", records)
    return mcp_row(next(row for row in records if row.get("id") == name))


def mcp_test(name: str, directory=None) -> dict:
    """Connect to the server once and list its tools: {name, tools: [{name, description}],
    seconds}. A Problem says why it did not answer and what to do."""
    from ..services.connectors import configured_servers
    from ..services.mcp import McpClient, McpError

    settings, credentials = _settings(directory)
    record = _record(settings, name)
    started = time.monotonic()
    client = None
    try:
        config = configured_servers({"connectors": [{**record, "enabled": True}]}, credentials)[name]
        seconds = min(float(config.get("timeout_seconds", 60)), 60.0)
        if config.get("command"):
            import shutil
            import tempfile

            from ..services.mcp_stdio import StdioServer

            if shutil.which(config["command"]) is None and not Path(config["command"]).is_file():
                raise Problem(f"{name}: the command {config['command']!r} is not on this computer",
                              "install it, or give its full path (harness mcp remove, then add again)",
                              code="mcp_command")
            log = Path(tempfile.mkdtemp(prefix="harness-mcp-test-")) / "server.log"
            client = StdioServer([config["command"], *config.get("args", [])], config.get("env", {}), log,
                                 cwd=config.get("cwd"), timeout=seconds)
        else:
            client = McpClient(config["url"], timeout=seconds, headers=config.get("headers"))
        tools = client.tools()
    except Problem:
        raise
    except (McpError, OSError, ValueError, RuntimeError, TimeoutError) as error:
        text = " ".join(str(error).split())[:300]
        low = text.lower()
        if "credential" in low or "is not set" in low:
            fix = "its secret is missing: remove it and add it again with the value"
        elif "401" in low or "403" in low or "unauthorized" in low:
            fix = "it wants a token: add it again with --header \"Authorization: Bearer ...\""
        elif record.get("transport") == "stdio":
            fix = "run its command by itself to see what it prints"
        else:
            fix = "check the address and that the server is running"
        raise Problem(f"{name} did not answer as an MCP server: {text}", fix, code="mcp_failed") from None
    finally:
        if client is not None:
            try:
                client.stop()
            except Exception:  # noqa: BLE001 - the answer, or its failure, is what counts
                pass
    return {"name": name, "seconds": round(time.monotonic() - started, 1),
            "tools": [{"name": tool.get("name"), "description": " ".join(str(tool.get("description") or "").split())[:200]}
                      for tool in tools]}


# -- External agents (ACP) -----------------------------------------------------------------

def _hook(name: str, install: bool = True):
    """What the package that connects agents gives under `name`, the package installed first
    when it is not there (as the settings allow)."""
    from ..extensions import first, require
    from ..packages import activate

    activate()
    found = first(name)
    if found is None and install:
        found = require(name, "commands", "agents")
    return found


def agents(*, registry: bool = False, directory=None, wait: bool = True) -> list:
    """The agents that can be connected over ACP: [{id, name, kind, source, state, version,
    signed_in, sign_in, plan}]. `source`: found (its command line is on this computer),
    custom (a command of the user's own), registry (the ACP Registry's). `state`:
    connected (ready to be started), found (here, its adapter installs on first use),
    available (in the registry, not installed). Without `registry`, only those that are
    here or connected. Without `wait` (a page's request), `signed_in` is what was found last
    (None the first time) and is found again behind the request."""
    from .. import onboarding

    rows = {}
    listing = _hook("agents", install=registry)
    listed = [row for row in (listing() if listing is not None else ()) if row.get("kind") == "acp"]
    if registry and not any(row.get("source") == "registry" for row in listed):
        # The ACP Registry was never read here: read it now.
        registry_refresh()
        listed = [row for row in listing() if row.get("kind") == "acp"]
    for row in listed:
        rows[row["id"]] = {"id": row["id"], "name": (row.get("name") or row["id"]).removeprefix("custom/"), "kind": "acp",
                           "source": "custom" if row.get("source") == "custom" else "registry",
                           "state": "connected" if row.get("installed") else "available",
                           "version": row.get("version"), "signed_in": None, "sign_in": "", "plan": "",
                           "runs_here": row.get("platform_available", True)}
    for row in onboarding.agent_sources(wait=wait):
        known = rows.get(row["provider"], {})
        rows[row["provider"]] = {"id": row["provider"], "name": row["name"].removeprefix("custom/"), "kind": "acp",
                                 "source": known.get("source") if known.get("source") == "custom" else "found",
                                 "state": "connected" if known.get("state") == "connected" else "found",
                                 "version": known.get("version"), "signed_in": row.get("signed_in"),
                                 "sign_in": row.get("sign_in") or "", "plan": row.get("plan") or "", "runs_here": True}
    found = [row for row in rows.values() if registry or row["state"] != "available"]
    return sorted(found, key=lambda row: (row["state"] == "available", row["name"].lower()))


def agent_add(name: str, argv=None, *, env=()) -> dict:
    """Connect an agent: with `argv`, a command of your own that speaks ACP (named `name`:
    it becomes acp:custom/<name>); without, the ACP Registry's agent `name`, whose pinned
    adapter is installed. {id}."""
    name = str(name or "").strip().removeprefix("acp:")
    try:
        if argv:
            return {"id": _hook("agent_add")(name, list(argv), list(env or ()))}
        _hook("agent_ready")(f"acp:{name}", None)
        return {"id": f"acp:{name}"}
    except Problem:
        raise
    except (ValueError, OSError, RuntimeError) as error:
        raise Problem(f"the agent {name} could not be connected: {error}",
                      "harness agents list --registry lists the registry's agents; harness agents add NAME -- "
                      "COMMAND adds one of your own", code="agent_unavailable") from None


def agent_remove(identifier: str) -> dict:
    """Disconnect an agent: a command of your own is forgotten, a registry agent's adapter removed."""
    identifier = _agent_id(identifier)
    try:
        _hook("agent_remove")(identifier)
    except (ValueError, OSError) as error:
        raise Problem(f"{identifier} is not connected: {error}", "harness agents list shows the ones that are",
                      code="no_agent") from None
    return {"removed": identifier}


def agent_test(identifier: str, directory=None, log=None) -> dict:
    """Start the agent and ask it for one word, as the first run does: {id, seconds, reply}.
    A Problem says why it did not answer (not installed, not signed in, its plan's limit)."""
    from .. import onboarding
    from ..paths import data

    identifier = _agent_id(identifier)
    answer = onboarding.tryout(Path(directory) if directory else data(), {"provider": identifier, "model": "default"},
                               log=log)
    return {"id": identifier, **answer}


def _agent_id(identifier: str) -> str:
    """The id of the agent a person named: acp:<name>, or their own command acp:custom/<name>."""
    identifier = str(identifier or "").strip()
    if not identifier:
        raise Problem("name the agent", "harness agents list shows them", code="no_agent")
    if identifier.startswith("acp:"):
        return identifier
    known = {row["id"] for row in agents()}
    own = f"acp:custom/{identifier}"
    return own if own in known and f"acp:{identifier}" not in known else f"acp:{identifier}"


def registry_refresh() -> dict:
    """Read the ACP Registry again: {entries}."""
    try:
        return {"entries": int(_hook("agents_refresh")())}
    except (ValueError, OSError, RuntimeError) as error:
        raise Problem(f"the ACP Registry could not be read: {error}", "check the network, then try again",
                      code="network") from None
