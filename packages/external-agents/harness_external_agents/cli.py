"""Configure which external coding agents the user trusts to start."""

import argparse
import json
from pathlib import Path

from harness.sdk import atomic_write

from . import hooks, host, registry


def main(arguments=None):
    parser = argparse.ArgumentParser(prog="harness agents", description="Manage external coding agent adapters")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("ls", help="list discovered and configured adapters")
    commands.add_parser("update", help="refresh the ACP Registry catalog")
    install = commands.add_parser("install", help="install an exact distribution from the saved ACP Registry")
    install.add_argument("id")
    add = commands.add_parser("add", help="trust a local ACP command: agents add NAME -- COMMAND ARGS")
    add.add_argument("--terminal", action="store_true", help="use a terminal for a non-ACP CLI")
    add.add_argument("--env", action="append", default=[], help="an environment variable the program may receive")
    add.add_argument("name")
    add.add_argument("argv", nargs=argparse.REMAINDER)
    remove = commands.add_parser("remove", help="disable an adapter's saved configuration")
    remove.add_argument("id")
    editor = commands.add_parser("import-editor", help="preview or explicitly trust commands from a selected editor file")
    editor.add_argument("format", choices=("zed", "jetbrains"))
    editor.add_argument("path", type=Path)
    editor.add_argument("--trust", action="store_true")
    cloud = commands.add_parser("configure-cloud", help="configure a provider from a JSON file containing no tokens")
    cloud.add_argument("provider", choices=tuple(host.PROVIDERS))
    cloud.add_argument("path", type=Path)
    bridge = commands.add_parser("hooks", help="configure explicit project-scoped native approval forwarding")
    bridge.add_argument("mode", choices=("enable", "disable", "dispatch"))
    bridge.add_argument("provider", choices=("claude-code", "codex"))
    bridge.add_argument("folder", nargs="?")
    args = parser.parse_args(arguments)
    if args.action == "ls":
        print(json.dumps(host.agents(), ensure_ascii=False, indent=2))
    elif args.action == "update":
        print(f"Saved {registry.refresh()} ACP Registry entries.")
    elif args.action == "install":
        print(f"Installed {args.id} {registry.install(args.id.removeprefix('acp:'))}.")
    elif args.action == "add":
        if not registry.ID.fullmatch(args.name):
            parser.error("use a lowercase agent name with letters, digits, dots, hyphens or underscores")
        name = ("terminal:" if args.terminal else "acp:custom/") + args.name
        settings = {"argv": args.argv, "env": args.env}
        host.command(settings)
        host.environment(settings)
        atomic_write(host.config_path(), json.dumps({**host.configured(), name: settings}, indent=2), private=True)
        print(name)
    elif args.action == "hooks":
        if args.mode == "dispatch":
            hooks.dispatch(args.provider)
        else:
            if not args.folder:
                parser.error("select an explicit project directory")
            hooks.set_scope(args.provider, args.folder, args.mode == "enable")
    elif args.action == "import-editor":
        settings = json.loads(args.path.read_text(encoding="utf-8"))
        servers = settings.get("agent_servers") if args.format == "zed" else settings.get("acpServers")
        if not isinstance(servers, dict):
            parser.error("the selected editor file has no named ACP servers")
        imported = {}
        for name, item in servers.items():
            if isinstance(item, dict) and isinstance(item.get("command"), str) and registry.ID.fullmatch(name):
                argv = [item["command"], *(item.get("args") or [])]
                if all(isinstance(arg, str) for arg in argv):
                    imported["acp:custom/" + name] = {"argv": argv}
        print(json.dumps(imported, ensure_ascii=False, indent=2))
        if args.trust:
            atomic_write(host.config_path(), json.dumps({**host.configured(), **imported}, indent=2), private=True)
    elif args.action == "configure-cloud":
        settings = json.loads(args.path.read_text(encoding="utf-8"))
        allowed = {"credential", "account_scope", "project", "repository", "ref", "model", "environment",
                   "environment_id", "agent_id", "source", "require_plan_approval", "organization"}
        if not isinstance(settings, dict) or set(settings) - allowed:
            parser.error("cloud adapter settings must use the documented configuration fields")
        if "environment" in settings:
            environment = settings["environment"]
            if not isinstance(environment, dict) or set(environment) - {"type", "network_policy"}:
                parser.error("only environment type and network policy may be set in this file")
        name = "cloud:" + args.provider
        atomic_write(host.config_path(), json.dumps({**host.configured(), name: settings}, indent=2), private=True)
        print(name)
    else:
        rows = host.configured()
        if args.id in rows:
            del rows[args.id]
            atomic_write(host.config_path(), json.dumps(rows, indent=2), private=True)
        else:
            identifier = args.id.removeprefix("acp:")
            if registry.installed(identifier) is None:
                parser.error("unknown external agent")
            (registry.root() / "installed" / f"{identifier}.json").unlink()
    return 0
