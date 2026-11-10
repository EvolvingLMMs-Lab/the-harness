"""Resolve user-configured MCP connections without installing optional capabilities.

The existing connectors settings are shared by headless hosts and optional frontends.
Catalog entries belong to their installed provider. Generic entries are owned here.
Secrets resolve only in the host, never in the controller namespace or run manifest.
"""
import math
import os
import re

from .mcp import McpError

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_FIELD = re.compile(r"\{([A-Z0-9_]+)\}")


def configured_servers(settings, credentials):
    servers = {}
    for record in settings.get("connectors", []):
        if not record.get("enabled", True) or record.get("catalog"):
            continue
        identifier = record.get("id", "")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier in servers:
            raise ValueError("Each MCP connection requires a unique lowercase id (letters, digits, hyphens)")

        def render(text):
            def field(match):
                key = match[1]
                if key in record.get("secrets", []):
                    name = f"HARNESS_MCP_{identifier.upper().replace('-', '_')}_{key}"
                    value = credentials.secret(name)
                    if not value:
                        raise McpError(f"{identifier}: credential {key} is not set")
                    return value
                if key not in record.get("fields", {}):
                    raise McpError(f"{identifier}: field {key} is not set")
                return os.path.expanduser(str(record["fields"][key]))
            return _FIELD.sub(field, str(text))

        config = {"connector_id": identifier, "description": str(record.get("description") or record.get("name") or identifier),
                  "timeout_seconds": float(record.get("timeout_seconds", 60)),
                  "resource": record.get("resource") or identifier}
        if not math.isfinite(config["timeout_seconds"]) or config["timeout_seconds"] <= 0 or not isinstance(config["resource"], str):
            raise ValueError(f"{identifier}: positive timeout and resource name required")
        for key in ("allowed_tools", "read_only_tools", "tools_off"):
            value = record.get(key, [])
            if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
                raise ValueError(f"{identifier}: {key} must be a list of tool names")
            config[key] = list(value)
        transport = record.get("transport")
        if transport == "stdio":
            command, args = record.get("command"), record.get("args", [])
            if not isinstance(command, str) or not command or not isinstance(args, list) or any(
                    not isinstance(arg, str) for arg in args):
                raise ValueError(f"{identifier}: stdio requires command and an argv list")
            config.update(command=render(command), args=[render(arg) for arg in args],
                          env={key: render(value) for key, value in record.get("env", {}).items()})
            if record.get("cwd"):
                config["cwd"] = render(record["cwd"])
        elif transport == "http":
            url = render(record.get("url", ""))
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"{identifier}: HTTP connection requires an http(s) URL")
            config.update(url=url, headers={key: render(value) for key, value in record.get("headers", {}).items()})
        else:
            raise ValueError(f"{identifier}: transport must be stdio or http")
        servers[identifier] = config
    return servers


def authorize_connector(settings, credentials, config, tool=None):
    """Recheck a host-owned connection; never retarget an already-running client."""
    identifier = config.get("connector_id")
    if identifier is None:
        return  # Package gateways enforce their own live policy.
    records = [row for row in settings.get("connectors", []) if row.get("id") == identifier]
    current = configured_servers({"connectors": records}, credentials).get(identifier)
    if current is None:
        raise McpError("The MCP connection was disabled or removed")
    policy = {"description", "allowed_tools", "read_only_tools", "tools_off"}
    if ({k: v for k, v in current.items() if k not in policy} !=
            {k: v for k, v in config.items() if k not in policy}):
        raise McpError("The MCP connection or credentials changed; start a new task")
    if tool is not None:
        grants = current.get("allowed_tools", ())
        if tool in current.get("tools_off", ()) or not (
                tool in current.get("read_only_tools", ()) or tool in grants or "*" in grants):
            raise McpError("The MCP tool permission was revoked")
