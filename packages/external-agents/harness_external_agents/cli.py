"""harness agents: the external agents the user connects, written like harness mcp.

    harness agents [list] [--registry]       the agents found here and the ones connected
    harness agents add NAME                  connect an agent of the ACP Registry (its adapter is installed)
    harness agents add NAME -- COMMAND ARGS  connect a command of your own that speaks ACP
    harness agents get NAME                  one agent
    harness agents remove NAME
    harness agents test NAME                 start it and ask it for one word

    harness agents update                    read the ACP Registry again
    harness agents import-editor | configure-cloud | hooks    as before
"""

import argparse
import json
import sys
from pathlib import Path

from harness.sdk import atomic_write

from . import hooks, host, registry


def _rows(with_registry: bool) -> list:
    from harness.sdk import connectors

    return connectors.agents(registry=with_registry)


def _state(row) -> str:
    words = {"connected": "connected", "found": "found here", "available": "in the registry"}[row["state"]]
    if row.get("signed_in") is True:
        words += " · signed in"
    elif row.get("signed_in") is False:
        words += " · not signed in" + (f" ({row['sign_in']})" if row.get("sign_in") else "")
    return words


def _lines(rows) -> list:
    if not rows:
        return ["no agents connected, and none found on this computer.",
                "harness agents list --registry lists the ACP Registry's; harness agents add NAME connects one, "
                "harness agents add NAME -- COMMAND one of your own."]
    width = max(len(row["id"]) for row in rows)
    return [f"  {row['id']:<{width}}  {row['name'][:28]:<28}  {_state(row)}" for row in rows]


def main(arguments=None):
    from harness.sdk import connectors, problems

    parser = argparse.ArgumentParser(prog="harness agents", description="The external agents you connect over the "
                                     "Agent Client Protocol: list, add, remove, test")
    commands = parser.add_subparsers(dest="action")
    for name in ("list", "ls"):
        listing = commands.add_parser(name, help="the agents found on this computer and the ones connected")
        listing.add_argument("--registry", action="store_true", help="also the ACP Registry's agents")
        listing.add_argument("--json", action="store_true")
    add = commands.add_parser("add", help="connect an agent: NAME of the ACP Registry, or NAME -- COMMAND ARGS for "
                                          "a command of your own that speaks ACP",
                              epilog="harness agents add gemini; harness agents add mine -- my-agent --acp")
    add.add_argument("--terminal", action="store_true", help="a command line that does not speak ACP, driven in a terminal")
    add.add_argument("--env", action="append", default=[], help="an environment variable the program may receive")
    add.add_argument("name")
    add.add_argument("argv", nargs=argparse.REMAINDER)
    get = commands.add_parser("get", help="one agent: what it is and whether it is ready")
    get.add_argument("id")
    get.add_argument("--json", action="store_true")
    for name in ("remove", "rm"):
        remove = commands.add_parser(name, help="disconnect an agent")
        remove.add_argument("id")
    test = commands.add_parser("test", help="start the agent and ask it for one word")
    test.add_argument("id")
    test.add_argument("--json", action="store_true")
    login = commands.add_parser("login", help="sign in to an agent through the agent itself: the ways it offers, or "
                                              "one of them now (it opens a page in the browser)")
    login.add_argument("id")
    login.add_argument("method", nargs="?", help="the way to sign in (without it: the ways the agent offers)")
    login.add_argument("--json", action="store_true")
    commands.add_parser("update", help="read the ACP Registry again")
    install = commands.add_parser("install", help="the same as add NAME, for an agent of the ACP Registry")
    install.add_argument("id")
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
    action = args.action or "list"
    try:
        if action in ("list", "ls"):
            rows = _rows(getattr(args, "registry", False))
            print(json.dumps(rows, ensure_ascii=False, indent=2) if getattr(args, "json", False) else "\n".join(_lines(rows)))
        elif action == "get":
            wanted = args.id if ":" in args.id else connectors._agent_id(args.id)
            row = next((row for row in _rows(False) if row["id"] == wanted), None) or \
                next((row for row in _rows(True) if row["id"] == wanted), None)
            if row is None:
                raise problems.Problem(f"no agent called {args.id}", "harness agents list --registry shows them",
                                       code="no_agent")
            print(json.dumps(row, ensure_ascii=False, indent=2) if args.json else
                  "\n".join([f"{row['id']}  {row['name']}", f"  {_state(row)}"]
                            + ([f"  version {row['version']}"] if row.get("version") else [])
                            + ([f"  runs under {row['plan']}"] if row.get("plan") else [])))
        elif action == "update":
            print(f"Saved {connectors.registry_refresh()['entries']} ACP Registry entries.")
        elif action in ("add", "install"):
            argv = [word for word in getattr(args, "argv", []) if word != "--"] if action == "add" else []
            if action == "add" and args.terminal:
                if not argv:
                    parser.error("a terminal agent needs its command: harness agents add --terminal NAME -- COMMAND")
                print(f"Added {host.agent_add(args.name, argv, args.env, terminal=True)}")
            else:
                name = args.name if action == "add" else args.id
                found = connectors.agent_add(name, argv or None, env=getattr(args, "env", ()))
                print(f"Added {found['id']}" + ("" if argv else " (its adapter is installed)")
                      + f": harness agents test {found['id'].removeprefix('acp:').removeprefix('custom/')} tries it")
        elif action in ("remove", "rm"):
            wanted = args.id if ":" in args.id else connectors._agent_id(args.id)
            host.agent_remove(wanted) if wanted.startswith(("terminal:", "cloud:")) else connectors.agent_remove(wanted)
            print(f"Removed {wanted}")
        elif action == "login":
            said = lambda message: print(f"  {message}", file=sys.stderr, flush=True)  # noqa: E731
            if args.method is None:
                ways = connectors.agent_sign_in(args.id, log=said)
                print(json.dumps(ways, ensure_ascii=False) if args.json else "\n".join(
                    f"{row['id']:<18} {row['name']}" + (f"  ·  {row['description']}" if row["description"] else "")
                    for row in ways) or f"{args.id} offers no way to sign in through here: use its own command")
            else:
                print(f"signing in to {args.id}: finish in the page it opens …", file=sys.stderr, flush=True)
                answer = connectors.agent_sign_in(args.id, args.method, log=said)
                print(json.dumps(answer, ensure_ascii=False) if args.json else f"✓ signed in to {args.id}")
        elif action == "test":
            print(f"asking {args.id} for one word …", file=sys.stderr, flush=True)
            answer = connectors.agent_test(args.id, log=lambda message: print(f"  {message}", file=sys.stderr, flush=True))
            print(json.dumps(answer, ensure_ascii=False) if args.json else
                  f"✓ {answer['id']} answered in {answer['seconds']} s: {answer['reply']}")
        elif action == "hooks":
            if args.mode == "dispatch":
                hooks.dispatch(args.provider)
            else:
                if not args.folder:
                    parser.error("select an explicit project directory")
                hooks.set_scope(args.provider, args.folder, args.mode == "enable")
        elif action == "import-editor":
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
        else:
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
    except problems.Problem as error:
        print(problems.said(error), file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(problems.said(error), file=sys.stderr)
        return 2
    return 0
