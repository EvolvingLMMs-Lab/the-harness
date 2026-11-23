"""harness minebot ...: the package's command.

    harness minebot setup                  install what the body needs (Node, its libraries), ahead of its first use
    harness minebot status                 what is installed, and what runs
    harness minebot up [--set KEY=VALUE]   start the body beside the game server the settings name, and its worker
    harness minebot down                   stop what this package started
    harness minebot run ...                a run on the body (harness minebot run --help)
    harness minebot stop                   end the run and what runs beside the body
    harness minebot table NAME             what the game recorded of a run
    harness minebot check                  the body's own checks against the server the settings name
    harness minebot window setup ...       make the launcher instance of the game window from an instance of yours
"""

import argparse
import sys

from harness.sdk import Settings, UsageError, cli_table, data

from .config import SECTION, data_dir, settings


def _overrides(items) -> dict:
    found = {}
    for item in items or ():
        key, has, value = item.partition("=")
        if not has:
            raise UsageError(f"--set takes KEY=VALUE, not {item!r}")
        found[key.strip().removeprefix("minebot.")] = value
    return found


def _values(items) -> dict:
    try:
        return settings(_overrides(items))
    except ValueError as error:
        raise UsageError(str(error)) from None


def _note(message) -> None:
    print(message, file=sys.stderr, flush=True)


def setup(argv) -> int:
    argparse.ArgumentParser(prog="harness minebot setup", description="Install what the body needs ahead of its first "
                            "use: Node and the body's libraries. Nothing of the game is installed.").parse_args(argv)
    from . import provision, stack

    provision.ensure(_note)
    stack.worker_python(_note)
    print(cli_table(provision.status(), ["what", "installed", "where"]))
    return 0


def status(argv) -> int:
    parser = argparse.ArgumentParser(prog="harness minebot status", description="What is installed for the body, and "
                                     "whether its parts run")
    parser.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args(argv)
    from . import provision, stack

    print(cli_table(provision.status(), ["what", "installed", "where"]))
    values = _values(args.sets)
    print(f"the server: {values['host']}:{values['port']} (auth {values['auth']}, window {values['window']})")
    return 0 if stack.status(values) else 1


def up(argv) -> int:
    parser = argparse.ArgumentParser(prog="harness minebot up", description="Start the body beside the game server the "
                                     "settings name: its bridge, the game window where one is set up, the worker")
    parser.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY=VALUE",
                        help="a setting for this start (minebot.KEY), e.g. --set host=play.example.org")
    parser.add_argument("--instruction", help="the task the worker gives an agent that joins it")
    args = parser.parse_args(argv)
    from . import stack

    values = _values(args.sets)
    try:
        came_up = stack.up(values, store=data_dir() / "store", options=stack.worker_options(values, instruction=args.instruction),
                           events_log=stack.logs_dir() / "body-events.jsonl", log=_note)
    except RuntimeError as error:
        _note(str(error))
        return 1
    if came_up:
        print(stack.endpoint(values))
    return 0 if came_up else 1


def down(argv) -> int:
    argparse.ArgumentParser(prog="harness minebot down", description="Stop what this package started").parse_args(argv)
    from . import run

    run.stop(_note)
    return 0


def table(argv) -> int:
    parser = argparse.ArgumentParser(prog="harness minebot table", description="What the game itself recorded of a run")
    parser.add_argument("name")
    args = parser.parse_args(argv)
    from . import run, table as tables

    if not (run.runs_dir() / args.name / "setup.json").is_file():
        raise UsageError(f"no such run: {args.name}")
    print(tables.write(args.name))
    return 0


def window(argv) -> int:
    parser = argparse.ArgumentParser(prog="harness minebot window", description="The game window of the body: your own "
                                     "game, in a launcher instance of its own that holds the window mod")
    actions = parser.add_subparsers(dest="action", required=True)
    make = actions.add_parser("setup", help="make that instance from an instance of yours (Fabric Loader, game version "
                                            "1.16.1) and turn the window on")
    make.add_argument("--launcher", required=True, help="your launcher's program (Prism Launcher)")
    make.add_argument("--from", dest="source", required=True, help="an instance of yours with Fabric Loader on 1.16.1")
    make.add_argument("--instance", help="the name of the window's instance (default: the setting minebot.instance)")
    make.add_argument("--instances", help="the launcher's instances folder (default: beside the launcher, else its data folder)")
    args = parser.parse_args(argv)
    from . import window as windows

    values = settings()
    instance = args.instance or values["instance"]
    try:
        windows.setup(launcher=args.launcher, source=args.source, instance=instance, view_port=values["view_port"],
                      instances=args.instances, log=_note)
    except RuntimeError as error:
        raise UsageError(str(error)) from None
    Settings(data()).update({SECTION: {"launcher": args.launcher, "instance": instance, "window": "on"}})
    print(f"the window is on: minebot.launcher, minebot.instance = {instance}, minebot.window = on")
    return 0


def main(argv) -> int:
    from . import check, run

    commands = {"setup": setup, "status": status, "up": up, "down": down, "stop": down, "run": lambda rest: run.main(rest, _note),
                "table": table, "check": check.main, "window": window}
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] not in commands:
        raise UsageError(f"harness minebot {argv[0]}: no such command; there are {', '.join(commands)}")
    return int(commands[argv[0]](list(argv[1:])) or 0)
