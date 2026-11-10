"""The command line:

    harness                          the terminal chat (tui/): the first run asks for the model and key
    harness run "task" [-p] [--json] do a task and end: -p prints only the answer, --json every record
    harness run rpc                  drive the agent from another program: JSON lines both ways
    harness install | list | remove  packages (list searches the registry and shows one package)
    harness library                  what the agent learned
    harness replay RUN               a run as it went, in the terminal
    harness doctor                   whether this computer can run the agent

Installed packages add their own commands (package.toml [provides] commands); `harness run
EXPERIMENT` and `harness doctor EXPERIMENT` are the eval package's. Sessions, the session
host and the settings are commands of the terminal chat (/sessions, /host, /settings).
"""

import argparse
import importlib
import json
import os
from pathlib import Path
from queue import Queue
import sys
import threading

from . import __version__
from .host.sessions import ENDED


class UsageError(ValueError):
    """Arguments that cannot go together: exit status 2, like argparse's own errors."""


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def table(rows, columns):
    """Rows of dicts as an aligned text table."""
    cells = [[("" if row.get(column) is None else str(row.get(column))) for column in columns] for row in rows]
    widths = [max([len(column)] + [len(line[i]) for line in cells]) for i, column in enumerate(columns)]
    lines = ["  ".join(column.ljust(width) for column, width in zip(columns, widths))]
    lines += ["  ".join(cell.ljust(width) for cell, width in zip(line, widths)) for line in cells]
    return "\n".join(line.rstrip() for line in lines)


def _is_experiment(text: str) -> bool:
    """Recognize a legacy experiment argument by an existing configuration."""
    from .paths import find

    try:
        if Path(text).suffix.lower() == ".toml" and Path(text).is_file():
            return True
        if Path(text).name == text and text:
            return any(find(f"configs/{folder}/{text}.toml") for folder in ("experiments", "ablations"))
    except (OSError, ValueError):
        pass
    return False


def _guarded(call) -> int:
    """`call()`'s exit status, with the CLI's error handling."""
    from .settings import ChoiceRequired

    try:
        return int(call() or 0)
    except KeyboardInterrupt:
        return 130
    except ChoiceRequired as error:
        print(json.dumps({"error": str(error), "choice_required": error.choice}), file=sys.stderr, flush=True)
        return 2
    except UsageError as error:
        print(json.dumps({"error": f"usage: {error}"}), file=sys.stderr, flush=True)
        return 2
    except (ValueError, KeyError, OSError, RuntimeError, ImportError, TimeoutError) as error:
        print(json.dumps({"error": f"{type(error).__name__}: {error}"}), file=sys.stderr, flush=True)
        return 1


def _package_arguments(command):
    command.add_argument("--project", action="store_true", help="the project's packages (harness.toml and "
                                                                "harness.lock here or above) instead of yours")
    command.add_argument("--json", action="store_true")


def _levels(section: str):
    """A settings section's level choices (the computer package's physical and privacy), or
    None where no package registers the section (then the host checks the value)."""
    from .settings import SCHEMA

    return SCHEMA[section]["level"].bounds if section in SCHEMA else None


def _rule_arguments(command):
    """harness settings rules add's flags: --level and one per field of a section's rules."""
    from .settings import SCHEMA, rule_fields

    sections = [section for section in SCHEMA if rule_fields(section)]
    having = {}
    for section in sections:
        for name in rule_fields(section):
            having.setdefault(name, []).append(section)
    command.add_argument("--level", help="rules add: the rule's level")
    for name, where in having.items():
        command.add_argument(f"--{name}", help=f"rules add: the rule's {name}"
                             + (f" ({', '.join(where)})" if len(where) < len(sections) else ""))


def _run_rules(level=None, allow_apps=(), deny_apps=(), ask_apps=()) -> dict:
    """A run's physical-input policy from its flags: {"level", "rules"} (runtime.physical; the
    computer's policy checks it where it is used)."""
    rules = [*({"level": "allow", "app": app} for app in allow_apps),
             *({"level": "ask_each", "app": app} for app in ask_apps),
             *({"level": "never", "app": app} for app in deny_apps)]
    return {**({"level": level} if level else {}), **({"rules": rules} if rules else {})}


def run_flags(command):
    """harness run's flags of a task's own (and an experiment's): --physical and the app rules,
    --window-details, --think, --workspace."""
    _physical_arguments(command)
    _think_arguments(command)
    _workspace_argument(command)
    command.add_argument("--agents", action="store_true",
                         help="sub-agents on in this conversation (they are off unless the setting session.agents "
                              "is on; the agent may also ask you to switch them on)")


def _coding_arguments(command):
    command.add_argument("--agent", help="use the native agent (harness) or a configured ACP, terminal or cloud coding agent")
    command.add_argument("--folder", type=Path, help="bind a project directory for the native Harness or an external agent")
    command.add_argument("--isolation", choices=("folder", "worktree"), help="local project's working directory")
    command.add_argument("--share-mcp-tool", dest="mcp_tools", action="append", choices=("project_info", "project_diff"),
                         help="grant a read-only project tool to this ACP session (repeatable)")


def run_sets(args) -> list[str]:
    """run_flags as experiment overrides (agent.runtime, the worker's options)."""
    return physical_sets(args) + think_sets(args) + workspace_sets(args)


def _physical_arguments(command):
    command.add_argument("--physical", choices=_levels("physical"), help="the physical-input level for this run in place of "
                                                            "the default of your settings (their rules still hold)")
    command.add_argument("--allow-app", action="append", default=[], metavar="APP",
                         help="allow physical input in APP for this run (its process name; repeatable)")
    command.add_argument("--deny-app", action="append", default=[], metavar="APP",
                         help="never physical input in APP for this run (repeatable)")
    command.add_argument("--ask-app", action="append", default=[], metavar="APP",
                         help="ask before each step of physical input in APP for this run (repeatable)")
    command.add_argument("--window-details", choices=_levels("privacy"),
                         help="what the model learns of your windows the agent does not own, for this run in place "
                              "of the default of your settings (their rules still hold): none, presence (only that "
                              "another window is in front), apps, titles")


def _think_arguments(command):
    from .settings import SCHEMA

    command.add_argument("--think", choices=[level for level in SCHEMA["model"]["think_while_acting"][2]
                                             if level != "default"],
                         help="allow one speculative thought during a long program (on) or disable it (off). "
                              "Legacy on_events and periodic act like on.")
    command.add_argument("--think-interval", type=float, metavar="SECONDS",
                         help="accepted for older configurations. Decision scheduling is event-driven.")


def think_sets(args) -> list[str]:
    """harness run and chat --think, --think-interval as experiment overrides."""
    level, interval = getattr(args, "think", None), getattr(args, "think_interval", None)
    if interval is not None and interval <= 0:
        raise ValueError("--think-interval is a number of seconds above 0")
    return [*([f"agent.runtime.think_while_acting={json.dumps(level)}"] if level else []),
            *([f"agent.runtime.think_interval={interval:g}"] if interval is not None else [])]


def _workspace_argument(command):
    command.add_argument("--workspace", metavar="KIND",
                         help="where the agent works: none (no environment: the conversation, the model and "
                              "the connected tools only), project (one folder: give it with --folder), browser (a "
                              "background browser), desktop (your screen), apps (your applications in the "
                              "background: Windows, macOS, Linux on X11) or display (a display of its own that you "
                              "never see: a display server on Linux, a virtual machine on Windows and macOS; the "
                              "settings computer.display_backend and vm_* say which). Without it (and without "
                              "--folder) the setting session.environment decides: ask (the default) asks in an "
                              "interactive terminal and is an error elsewhere, last takes the last choice, a kind "
                              "takes that kind")
    if command.prog.split()[-1] == "run":
        command.add_argument("--vm-image", metavar="IMAGE",
                             help="with --workspace display: each workspace is a virtual machine started from IMAGE "
                                  "(a disk image or a VMware or Tart folder) in place of the setting computer.vm_image")


def workspace_sets(args) -> list[str]:
    """harness run --workspace (and --vm-image) as experiment overrides (the computer
    worker's options)."""
    kind = getattr(args, "workspace", None)
    if args.command != "run" or isinstance(getattr(args, "config", None), str):
        return []
    if kind == "browser":
        raise ValueError("--workspace browser is for a task in words; an experiment in a browser runs the "
                         "browser bench")
    sets = [f"worker.workspace={json.dumps(kind)}"] if kind else []
    image = getattr(args, "vm_image", None)
    if image:
        if kind != "display":
            raise ValueError("--vm-image goes with --workspace display")
        sets += ['worker.display_backend="vm"', f"worker.vm.vm_image={json.dumps(str(Path(image).resolve()))}"]
    return sets


def physical_sets(args) -> list[str]:
    """The run's physical-input flags as an experiment override (agent.runtime.physical)."""
    policy = _run_rules(getattr(args, "physical", None), getattr(args, "allow_app", ()), getattr(args, "deny_app", ()),
                       getattr(args, "ask_app", ()))
    seen = getattr(args, "window_details", None)
    if not policy and not seen:
        return []
    from .config import toml_value

    return [*([f"agent.runtime.physical={toml_value(policy)}"] if policy else []),
            *([f"agent.runtime.privacy={toml_value({'level': seen})}"] if seen else [])]


def package_commands() -> dict:
    """{name: ("module:function", package, summary)} of the commands the installed packages
    bring. The function takes the command's arguments (a list) and returns the exit status."""
    from .paths import packages

    found = {}
    for package in packages():
        for name in package.provides.get("commands", ()):
            found.setdefault(name, (package.commands[name], package.name, package.summary))
    return found


# Commands the core installs a package for on first use: {name: package}.
FIRST_USE = {"agent": "agent"}


def _package_command(name: str, arguments) -> int:
    """An installed package's command, or (FIRST_USE) its package installed first. Its own
    parser reads the arguments."""
    from .packages import Packages, activate

    packages = None
    if name not in package_commands():
        packages = Packages()
        packages.ensure("commands", name, log=_note)
    activate(packages)
    module, _, function = package_commands()[name][0].partition(":")
    return int(getattr(importlib.import_module(module), function)(list(arguments)) or 0)


def _experiment(arguments) -> int:
    """harness run EXPERIMENT ...: the eval package's (installed first when it is not)."""
    from .extensions import require
    from .packages import activate

    activate()
    return int(require("run_experiment", "commands", "program")(list(arguments)) or 0)


def parser(packages: bool = True):
    root = argparse.ArgumentParser(prog="harness", description="Automatic Control for anything that acts.",
                                   epilog="harness with no command: the terminal chat with the agent on this computer "
                                          "(/help lists its commands: sessions, the session host, settings, model, "
                                          "packages, library)")
    root.add_argument("--version", action="version", version=f"harness {__version__}")
    run_flags(root)
    _coding_arguments(root)
    root.add_argument("--managed-workspace", action="store_true", help="use an isolated managed workspace (supported Linux hosts)")
    commands = root.add_subparsers(dest="command")
    run = commands.add_parser("run", help="Do a task on this computer and end (harness run \"rename the photos by "
                                          "date\"); harness run rpc: drive the agent from another program",
                              epilog="harness run rpc: JSON lines on stdin ({\"type\": \"prompt\", \"text\"}, then "
                                     "message, pause, continue, approve, reject, end) and the records of its trace "
                                     "as JSON lines on stdout.")
    run.add_argument("task", help="a task, or rpc for the JSON-lines protocol")
    run.add_argument("--model", help="an enabled model from ~/.harness/models.json (ID or provider/model)")
    run.add_argument("--effort", help="the selected model's reasoning effort ID")
    output_mode = run.add_mutually_exclusive_group()
    output_mode.add_argument("-p", "--print", action="store_true", help="print only the agent's answer")
    output_mode.add_argument("--json", action="store_true", help="print every record of its trace as a JSON line")
    run.add_argument("--learn", nargs="?", const=True, type=_minutes, metavar="MINUTES",
                     help="learn this environment for the task instead of doing it: read, try the controls, write "
                          "skills with tests, practise, for MINUTES of live time (default: the settings' "
                          "learning.active_minutes); what it learns goes into the library")
    run.add_argument("--library", type=Path, help="explicit reusable learning library; frozen unless --learn-while-working")
    run.add_argument("--learn-while-working", action="store_true", help="learn during the task into --library")
    run_flags(run)
    _coding_arguments(run)
    run.add_argument("--managed-workspace", action="store_true", help="use an isolated managed workspace (supported Linux hosts)")
    _session_commands(commands.add_parser("sessions", help="Manage the session host's coding sessions"))
    install = commands.add_parser("install", help="Install packages (and what they depend on), or update them; and "
                                                  "the services and benches they provide",
                                  epilog="harness install browser; harness install computer@^0.5; harness install "
                                         "git:github.com/x/y@main#packages/z; harness install ./my-package --link; "
                                         "harness install --update (all); harness install sam3 (a service). With no "
                                         "names in a folder with harness.toml: the project's packages, from its "
                                         "harness.lock.")
    install.add_argument("names", nargs="*", help="packages (a registry name with an optional range, a git or archive "
                                                  "URL, a folder), services and benches")
    _package_arguments(install)
    install.add_argument("--update", action="store_true", help="update the named packages (default: all) to the "
                                                               "newest version in their range")
    install.add_argument("--yes", "-y", action="store_true", help="install packages from outside the registry "
                                                                 "without asking (they run code on this computer)")
    install.add_argument("--link", action="store_true", help="a folder: use it where it is instead of a copy (a "
                                                            "package under development)")
    install.add_argument("--deploy", help="services: the deploy that places them (default $HARNESS_DEPLOY)")
    listed = commands.add_parser("list", help="The installed packages; --available: the registry's (QUERY "
                                              "searches them); one package by its name: what it provides")
    listed.add_argument("query", nargs="?", default="")
    listed.add_argument("--available", action="store_true", help="the packages the registry has")
    _package_arguments(listed)
    remove = commands.add_parser("remove", help="Remove installed packages")
    remove.add_argument("names", nargs="+")
    _package_arguments(remove)
    library = commands.add_parser("library", help="What the agent remembers (runtime/task/context.py): the libraries, a "
                                                  "library's entries with their evidence, tests and uses, and a run's "
                                                  "memory of what it saw and where beside its library's entries")
    library.add_argument("what", nargs="?", choices=["ls", "show"], default="ls",
                         help="ls (default): the libraries under $HARNESS_HOME/libraries; show LIBRARY or RUN")
    library.add_argument("path", nargs="?", help="show: a library's directory or its name under "
                                                 "$HARNESS_HOME/libraries, or a run's directory")
    library.add_argument("--json", action="store_true", help="JSON")
    replay = commands.add_parser("replay", help="Replay a run in the terminal")
    replay.add_argument("run", help="an episode directory, a conversation (its name under conversations/), or a "
                                    "session (SESSION or SESSION/AGENT)")
    replay.add_argument("--json", action="store_true", help="every record of its trace as a JSON line")
    doctor = commands.add_parser("doctor", help="Whether this computer can run the agent: Python, the model and its "
                                                "key, the packages; or services, or an experiment (the eval "
                                                "package's: harness doctor EXPERIMENT --help)",
                                 epilog="Exit status: 0 nothing missing, 1 something missing, 2 a usage error.")
    doctor.add_argument("names", nargs="*", help="services (default: the core), or an experiment")
    doctor.add_argument("--deploy", help="the deploy that places the services (default $HARNESS_DEPLOY)")
    doctor.add_argument("--json", action="store_true")
    # The installed packages' commands, after the core's (their own parsers read their arguments).
    for name, (_, package, summary) in (package_commands().items() if packages else ()):
        if name in commands.choices:
            continue
        command = commands.add_parser(name, help=f"{summary} (package {package})", add_help=False)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    return root


def core_commands() -> set:
    """The commands of the core itself (the others are packages')."""
    commands = next(action for action in parser(packages=False)._actions
                    if isinstance(action, argparse._SubParsersAction))
    return set(commands.choices) - set(FIRST_USE)


def _services(args):
    """harness doctor of services (and without names or a deploy file, of the core): what the
    package that places services checks (local-models), else the core's own checks."""
    from .extensions import first
    from .packages import Packages
    from .services.placement import NoDeploy, load_deploy

    deploy = load_deploy(args.deploy)
    doctor = first("doctor")
    core = isinstance(deploy, NoDeploy) or (deploy.automatic and not args.names)
    if doctor is not None and not isinstance(deploy, NoDeploy):
        report = doctor(deploy, names=args.names or None, core=core)
    elif args.names:
        return _usage("doctor", "checking services needs the local-models package (harness install local-models)")
    else:
        report = _core_report()
    report["packages"] = Packages().installed()
    _package_problems(report)
    if args.json:
        output(report)
    else:
        print(f"deploy {report['deploy']}: {'ready' if report['ok'] else 'NOT ready'}")
        if report.get("gpus") is not None:
            print(table(report["gpus"], ["index", "name", "used_gb", "total_gb"]))
        if report.get("installed"):
            print(table(report["installed"], ["name", "what", "installed", "environment"]))
        if report.get("to_install"):
            print(f"the agent would still install: {', '.join(report['to_install'])} (on its first run, "
                  f"or now: harness install {' '.join(report['to_install'])})")
        for problem in report["problems"]:
            print(f"  problem: {problem}")
        for note in report["notes"]:
            print(f"  note: {note}")
        _print_packages(report["packages"])
    return 0 if report["ok"] else 1


def _package_problems(report: dict) -> None:
    """Installed packages whose host code does not fit this harness (host/workspaces.py
    package_problems): the session host leaves them out, so they are problems of the report,
    each with the command that fixes it."""
    from .host.workspaces import package_problems

    found = package_problems()
    for row in report["packages"]:
        if row["name"] in found and "problem" not in row:
            row["problem"] = found[row["name"]]
    report["problems"] = [*report.get("problems", []), *found.values()]
    report["ok"] = report.get("ok", True) and not found


def _core_report() -> dict:
    """harness doctor with nothing named: the harness itself and whether a model is set up."""
    from . import providers
    from .paths import data

    problems, notes = [], []
    if sys.version_info < (3, 11):
        problems.append(f"Python {sys.version.split()[0]}: 3.11 or newer is needed")
    model = providers.ready(data())
    if not model["ready"]:
        problems.append(f"no model set up ({model['provider']}: {model['key_env']} is not set): run harness once "
                        "in a terminal, or export the key")
    notes.append("No package places services here: hosted models only (harness install local-models for "
                 "models on this machine's GPUs).")
    return {"schema_version": 1, "deploy": "none", "ok": not problems, "problems": problems, "notes": notes,
            "gpus": None, "services": [], "installed": [], "to_install": []}


def _print_packages(rows, columns="installed"):
    """Packages as harness list and doctor print them (describe()), installed or "available"."""
    from .packages import COLUMNS, rows as package_rows

    if not rows and columns == "installed":
        print("packages: none installed (harness list --available lists the registry's; a task installs what it "
              "needs)")
        return
    print(table(package_rows(rows, columns, 70), list(COLUMNS[columns])))


def _print_package(found, file=None):
    """One package's lines (describe()): harness list NAME, and what harness install asks to trust."""
    from .packages import describe

    first, *rest = describe(found)["lines"]
    print("\n".join([first, *(f"  {line}" for line in rest)]), file=file or sys.stdout)


def _list(args):
    """harness list [QUERY] [--available]: the installed packages (QUERY filters them), the
    registry's (--available; QUERY searches them), one package's description when QUERY is
    its exact name."""
    from .packages import Packages

    packages = Packages()
    rows = packages.search(args.query) if args.available else [
        row for row in packages.installed() if not args.query or args.query.lower() in str(row.get("name")).lower()]
    exact = [row for row in rows if row.get("name") == args.query]
    if args.query and len(exact) == 1:
        found = packages.info(args.query)
        output(found) if args.json else _print_package(found)
        return 0
    if args.json:
        output(rows)
    elif rows or not args.available:
        _print_packages(rows, "available" if args.available else "installed")
    else:
        print(f"no package matches {args.query!r}")
    return 0 if args.available or not any("problem" in row for row in rows) else 1


def _remove(args):
    from .packages import Packages

    removed = Packages().remove(args.names, project=args.project, log=_note)
    output(removed) if args.json else print(f"removed {', '.join(removed)}")
    return 0


def _install(args):
    """harness install: packages, then the services and benches among the names; --update:
    the named packages (default all) to the newest version in their range."""
    from .bench import bench_specs
    from .packages import Packages, activate, provision
    from .services.placement import load_deploy

    packages = activate(Packages())
    if args.update:
        result = packages.update(args.names, project=args.project, log=_note)
        output(result) if args.json else [print(f"{row['name']} {row['version']}") for row in result["installed"]]
        return 0
    deploy = load_deploy(args.deploy)
    known = set(deploy.services) | set(bench_specs())
    specs = [name for name in args.names if name not in known]
    result = {"installed": [], "problems": []}
    if specs or (not args.names and args.project) or (not args.names and packages.project() is not None):
        def consent(found):
            for package in found:
                _print_package(package, file=sys.stderr)
            if args.yes:
                return True
            if not sys.stdin.isatty():
                print("these packages are not from the registry and run code on this computer: "
                      "harness install --yes to install them", file=sys.stderr)
                return False
            return input("They are not from the registry and run code on this computer. Install? [y/N] ") \
                .strip().lower() in ("y", "yes")

        project = args.project or (not args.names and packages.project() is not None)
        result = packages.install(specs, project=project, consent=consent, link=args.link, log=_note)
        if result.get("needs_trust"):
            return 1
    elif not args.names:
        return _usage("install", "name packages, services or benches (or run it where harness.toml names the "
                                 "project's packages)")
    # A name a package just brought (a bench) is installed as one now too: its environment.
    known = set(deploy.services) | set(bench_specs())
    provisioned = [name for name in args.names if name in known]
    benches = [name for name in provisioned if name in bench_specs()]
    services = [name for name in provisioned if name not in benches]
    rows = [provision.install_bench_environment(deploy, name, log=_note) for name in benches]
    if services:
        # Services' environments and weights: the package that places services installs them.
        from .extensions import require

        rows += require("install_services", "commands", "fetch")(load_deploy(args.deploy), services, log=_note)
    if args.json:
        output({**result, "provisioned": rows})
    else:
        for row in result["installed"]:
            print(f"{row['name']} {row['version']} ({row['source']})")
        for problem in result["problems"]:
            print(f"  not installed: {problem}")
        if rows:
            print(table(rows, ["name", "what", "installed", "environment"]))
    return 0


def _usage(command, message):
    print(f"harness {command}: {message}", file=sys.stderr)
    return 2


def _doctor(args, words) -> int:
    """harness doctor: services (or with nothing named, the core); an experiment (a name of
    configs/experiments/ or a .toml file) or the experiment options are the eval package's,
    which reads `words` (what followed doctor) itself."""
    from .paths import find
    from .services.registry import load_services

    services = set(load_services())
    experiments = [name for name in args.names if name.endswith(".toml") or "/" in name or "\\" in name
                   or bool(find(f"configs/experiments/{name}.toml"))]
    both = [name for name in experiments if name in services]
    if both:
        return _usage("doctor", f"{both[0]!r} is both a service and an experiment: for the experiment give its "
                                f"file (configs/experiments/{both[0]}.toml)")
    options = [word for word in words if word.startswith("--") and word.split("=")[0] not in ("--deploy", "--json")]
    if args.names and all(name in services for name in args.names) and options:
        return _usage("doctor", f"{', '.join(options)} need an experiment: harness doctor EXPERIMENT {options[0]} ...")
    if experiments or options:
        from .extensions import require

        return int(require("doctor_experiment", "commands", "program")(list(words)) or 0)
    unknown = [name for name in args.names if name not in services]
    if unknown:
        return _usage("doctor", f"no service or experiment called {unknown[0]!r}")
    return _services(args)


def _note(message):
    print(message, file=sys.stderr, flush=True)


def _ready_model(interactive: bool) -> None:
    """A model and its key, asked for on the first run in a terminal (providers.setup)."""
    from . import model_list, providers
    from .paths import data

    if model_list.select(data()) is not None or providers.ready(data())["ready"]:
        return
    if not (interactive and sys.stdin.isatty()):
        raise UsageError("no model is set up yet: run harness in a terminal once (it asks for the model and key), "
                         "or export the provider's key")
    providers.setup(data())


def _run_options(args) -> dict:
    """A task's own runtime from its flags (--physical, --allow-app, --deny-app, --ask-app,
    --window-details, --think, --think-interval): app.RUN_KEYS."""
    options = {"managed_workspace": True} if getattr(args, "managed_workspace", False) else {}
    policy = _run_rules(getattr(args, "physical", None), getattr(args, "allow_app", ()), getattr(args, "deny_app", ()),
                       getattr(args, "ask_app", ()))
    if policy:
        options["physical"] = policy
    if getattr(args, "window_details", None):
        options["privacy"] = {"level": args.window_details}
    if getattr(args, "think", None):
        options["think_while_acting"] = args.think
    if getattr(args, "think_interval", None) is not None:
        if args.think_interval <= 0:
            raise UsageError("--think-interval is a number of seconds above 0")
        options["think_interval"] = args.think_interval
    if getattr(args, "learn", None) is not None:
        options["learn"] = args.learn
    if getattr(args, "agents", False):
        options["agents"] = True
    return options


def _minutes(value: str) -> float:
    """--learn's MINUTES (a number; the task in words goes before --learn)."""
    try:
        return float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"MINUTES is a number, not {value!r}: harness run \"for what\" --learn "
                                         "[MINUTES]") from None


def _task(text: str, workspace=None, confirmation=None, runtime=None, files=(), log=None, **coding):
    """The session host (started when none runs) and a conversation of the app's agent in it
    (Host.task); without a workspace named, the host takes the one the task asks for.
    `log`: where starting the host is said (default stderr)."""
    from .host import Host

    host = Host.connect(log=log or _note)
    return host, host.task(text, workspace or "auto", confirmation, runtime=runtime, files=files, **coding)


def _coding(args):
    agent = getattr(args, "agent", None)
    folder = getattr(args, "folder", None)
    if folder:
        folder = folder.expanduser().resolve()
    if not folder and agent and agent.startswith(("acp:", "terminal:")):
        folder = Path.cwd()
    return {key: value for key, value in {"agent": agent, "folder": folder,
                                           "isolation": getattr(args, "isolation", None),
                                           "mcp_tools": getattr(args, "mcp_tools", None)}.items() if value is not None}


def _starter(args):
    """The terminal chat's start(text, files, log, learn): a conversation of the app's agent with
    the options harness was given (--workspace, --physical, ...); `learn` (/learn): one that learns
    its environment for that many minutes. It keeps the last it started."""
    def start(text, files=(), log=None, learn=None, model_entry=None, reasoning_effort=None, workspace=None,
              folder=None, agents=None):
        runtime = {**_run_options(args), **({"learn": learn} if learn is not None else {}),
                   **({"agents": True} if agents else {})}
        coding = _coding(args)
        workspace = workspace or getattr(args, "workspace", None)
        if folder and not coding.get("agent"):
            coding["folder"] = Path(folder)
        library = getattr(args, "library", None)
        if getattr(args, "learn_while_working", False) and library is None:
            raise UsageError("--learn-while-working requires --library PATH")
        if library is not None:
            coding["library"] = {"path": str(library.resolve()),
                                 "learn": "on" if getattr(args, "learn_while_working", False) else "off",
                                 "reflect": bool(getattr(args, "learn_while_working", False))}
        if not coding.get("agent"):
            from .model_list import select
            from .paths import data

            selected = select(data(), model_entry, native=bool(runtime or workspace or coding.get("folder")))
            if selected is None:
                raise ValueError("add an enabled model in Settings or ~/.harness/models.json")
            model_entry = selected["id"]
            if selected["provider"].startswith(("acp:", "terminal:")):
                coding["folder"] = Path.cwd()
        start.host, start.conversation = _task(text, workspace,
                                                           runtime=runtime, files=files, log=log, **coding,
                                                           model_entry=model_entry, reasoning_effort=reasoning_effort)
        return start.host, start.conversation

    start.host = start.conversation = None
    # The command line already says where it works: the chat does not ask at its opening.
    start.named = bool(getattr(args, "workspace", None) or getattr(args, "folder", None)
                       or getattr(args, "agent", None))
    return start


def _turn_over(record, answered: bool) -> bool:
    status = record.get("status") if record.get("event") == "state" else None
    return status in ENDED or (status == "IDLE" and (answered or record.get("reason") == "budget"))


def _choose_first_use(choice):
    """The interactive run command: require an explicit numbered answer."""
    from .host import Host

    print(choice["title"], file=sys.stderr)
    for index, option in enumerate(choice["options"], 1):
        print(f"  {index}. {option['label']}", file=sys.stderr)
    while True:
        try:
            answer = input("Choose a number (no default; q cancels): ").strip()
        except EOFError:
            raise UsageError("choice cancelled; task not started") from None
        if answer.lower() == "q":
            raise UsageError("choice cancelled; task not started")
        if answer.isdigit() and 1 <= int(answer) <= len(choice["options"]):
            value = choice["options"][int(answer) - 1]["value"]
            Host.connect().post("/api/app/settings", {choice["section"]: {choice["key"]: value}})
            return


def _choose_environment(choice):
    """The interactive run command: where this conversation works. Enter takes the
    highlighted last choice; with none yet an explicit number is required. (kind, folder)."""
    options = choice["options"]
    values = [row["value"] for row in options]
    default = values.index(choice["selected"]) + 1 if choice.get("selected") in values else None
    print(choice["title"], file=sys.stderr)
    for index, option in enumerate(options, 1):
        mark = "*" if index == default else " "
        print(f" {mark}{index}. {option['label']}", file=sys.stderr)
    ask = f"Choose a number ({f'Enter: {default}' if default else 'no default'}; q cancels): "
    while True:
        try:
            answer = input(ask).strip()
        except EOFError:
            raise UsageError("choice cancelled; task not started") from None
        if answer.lower() == "q":
            raise UsageError("choice cancelled; task not started")
        if not answer and default:
            answer = str(default)
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            row = options[int(answer) - 1]
            break
    if not row.get("folder"):
        return row["value"], None
    here = Path.cwd()
    inside = any((parent / ".git").exists() for parent in (here, *here.parents))
    suggested = str(here if inside or not choice.get("folder") else choice["folder"])
    try:
        folder = input(f"Folder to work in [{suggested}]: ").strip() or suggested
    except EOFError:
        raise UsageError("choice cancelled; task not started") from None
    return row["value"], str(Path(folder).expanduser())


def _run_task(args):
    """harness run "task": the agent on this computer does it and the command ends when it has
    answered; -p prints only the answer, --json every record."""
    from .terminal import Printer
    from .transcript import answer_of

    if args.model and _coding(args).get("agent"):
        raise UsageError("--model selects its own provider; use either --model or --agent")
    if not _coding(args).get("agent") and not args.model:
        _ready_model(interactive=True)
    from .settings import ChoiceRequired

    start = _starter(args)
    place = {}
    while True:
        try:
            host, conversation = start(args.task, learn=getattr(args, "learn", None),
                                       model_entry=args.model, reasoning_effort=args.effort, **place)
            break
        except ChoiceRequired as error:
            # Nobody to ask: the error names the flag; nothing is chosen for the user.
            if args.json or not (sys.stdin.isatty() and sys.stdout.isatty()):
                raise
            if error.choice.get("per_conversation"):
                place = dict(zip(("workspace", "folder"), _choose_environment(error.choice)))
            else:
                _choose_first_use(error.choice)
    printer, answer, failed = Printer(), None, False
    asking = threading.Lock()

    def sub_agent(agent, what, request_id):
        with asking:
            if watch.is_set():
                return
            accept, reason = _answer(what)
            try:
                host.approve(conversation.run, accept, reason, agent, request_id=request_id)
            except (ValueError, OSError, RuntimeError) as error:
                print(f"harness: {error}", file=sys.stderr, flush=True)

    watch = _watch_sub_agents(host, conversation, sub_agent)
    try:
        for record in conversation.records():
            if args.json:
                print(json.dumps(record, ensure_ascii=False), flush=True)
            elif not args.print:
                for line in printer.lines(record):
                    print(line, flush=True)
                if args.learn is not None and record.get("event") in ("library", "cell"):
                    # Where learning the environment stands (runtime/learning/active.py progress()).
                    from harness.runtime.learning.active import progress_line

                    now = host.learning(conversation.run)
                    if now.get("active"):
                        print(progress_line(now), flush=True)
            elif record.get("event") == "error":
                # -p prints only the answer; why there is none still goes to stderr.
                print(f"harness: {record.get('message')}", file=sys.stderr, flush=True)
            request = record.get("request") if record.get("event") == "state" and (
                record.get("status") == "WAITING_FOR_CONFIRMATION") else None
            if request is not None:
                with asking:
                    accept, reason = _answer(_waits_for(request))
                try:
                    conversation.confirm(accept, reason, request_id=request["id"])
                except (ValueError, RuntimeError) as error:
                    print(f"harness: {error}", file=sys.stderr, flush=True)
            found = answer_of(record)
            if found is not None:
                answer = found
            failed = failed or (record.get("event") == "state" and record.get("status") == "ERROR")
            if _turn_over(record, answer is not None):
                break
    finally:
        watch.set()
        try:
            conversation.close()
        except Exception:
            pass
    if args.print:
        print(answer or "")
    return 1 if failed or answer is None else 0


def _waits_for(record) -> str:
    """What a waiting record asks the user, in every frontend's words (transcript.py)."""
    from .transcript import items

    if "code" in record:
        return f"Run this program?\n{record['code']}"
    return next((item["text"] for item in items({**record, "event": "physical_request"}, {}) if item.get("text")),
                "the agent waits for you")


def _answer(what: str) -> tuple[bool, str]:
    """The user's answer in this terminal to what an agent of harness run "task" waits for (a
    program under approvals.ask = programs, a sensitive step, physical input); without a
    terminal, no, with the reason."""
    if not sys.stdin.isatty():
        return False, "nobody to ask: harness run without a terminal (harness, or harness run rpc, can answer)"
    try:
        print(f"{what}\nAllow it? [y/N] ", file=sys.stderr, end="", flush=True)
        answer = input().strip().lower()
    except EOFError:
        answer = ""
    return (True, "") if answer in ("y", "yes") else (False, "the user declined")


def _watch_sub_agents(host, conversation, ask, seconds: float = 1.0) -> threading.Event:
    """Follow the session of `conversation` for sub-agents that wait for the user (their
    records are not in the main agent's): ask(agent, what, request_id) once for each wait. Returns the
    event that ends the watch."""
    done, seen = threading.Event(), {}

    def watch():
        while not done.wait(seconds):
            try:
                agents = list(host.session(conversation.run, lines=0).agents())
                for agent in agents:
                    request_id = agent.get("approval_id")
                    if (agent.get("depth") and agent.get("status") == "WAITING_FOR_CONFIRMATION" and request_id
                            and seen.get(agent["id"]) != request_id):
                        seen[agent["id"]] = request_id
                        what = agent.get("waiting") or "waits for approval"
                        threading.Thread(target=ask, args=(agent["id"], what, request_id), daemon=True).start()
            except (ValueError, OSError, RuntimeError):
                continue

    threading.Thread(target=watch, name="sub-agents", daemon=True).start()
    return done


def _rpc(args):
    """harness run rpc: one conversation driven by JSON lines on stdin, its records on stdout.
    In: {"type": "prompt", "text", "files"} (the first starts the conversation, later ones are
    messages; files: paths it attaches), {"type": "message", "text", "files"}, and the terminal
    chat's commands with a method (terminal.COMMANDS): pause, continue, {"type": "approve",
    "remember", "reason"}, {"type": "reject", "reason"}, end; {"type": "confirm", "accept",
    "reason", "remember"} is approve or reject, stop is end; with "agent", they answer that
    sub-agent. Out: {"type": "started", "run"}, {"type": "record", "record"}, {"type":
    "waiting", "agent", "what"} (a sub-agent waits for the user), {"type": "error", "message"};
    it ends when stdin closes, after end, or when the conversation ends."""
    from .terminal import COMMANDS, command as run_command

    if args.model and _coding(args).get("agent"):
        raise UsageError("--model selects its own provider; use either --model or --agent")
    if not _coding(args).get("agent") and not args.model:
        _ready_model(interactive=False)
    start = _starter(args)
    lock = threading.Lock()

    def send(message):
        with lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    conversation, streaming, watching = None, None, None
    commands = Queue()

    def read_input():
        try:
            for line in sys.stdin:
                commands.put(line)
        finally:
            commands.put(None)

    def stream(conversation):
        try:
            for record in conversation.records():
                send({"type": "record", "record": record})
                if record.get("event") == "state" and record.get("status") in ENDED:
                    break
        except Exception as error:  # the host went away
            send({"type": "error", "message": str(error)})
        finally:
            commands.put(None)

    threading.Thread(target=read_input, name="rpc-input", daemon=True).start()
    for line in iter(commands.get, None):
        if not line.strip():
            continue
        try:
            command = json.loads(line)
            if not isinstance(command, dict) or not isinstance(command.get("type"), str):
                raise ValueError("a command must be an object with a string type")
            kind = command["type"]
            if kind in ("prompt", "message") and conversation is None:
                host, conversation = start(str(command.get("text") or ""), files=command.get("files") or (),
                                           model_entry=args.model, reasoning_effort=args.effort)
                send({"type": "started", "run": conversation.run})
                watching = _watch_sub_agents(host, conversation, lambda agent, what, request_id: send(
                    {"type": "waiting", "agent": agent, "what": what, "request_id": request_id}))
                streaming = threading.Thread(target=stream, args=(conversation,), daemon=True)
                streaming.start()
            elif conversation is None:
                raise ValueError("start with {\"type\": \"prompt\", \"text\": ...}")
            elif kind in ("prompt", "message"):
                conversation.send_message(str(command.get("text") or ""),
                                          **({"files": command["files"]} if command.get("files") else {}))
            elif kind == "steer":
                conversation.steer(str(command.get("text") or ""), command.get("files") or ())
            elif kind == "cancel":
                conversation.cancel()
            elif kind == "terminal":
                conversation.terminal_input(str(command.get("text") or ""))
            elif kind == "config":
                send({"type": "config", **conversation.set_config(command.get("id"), command.get("value"))})
            elif kind == "answer":
                conversation.answer(command.get("request_id"), command.get("content"))
            elif kind in ("approve", "reject", "confirm"):
                if kind == "confirm" and type(command.get("accept")) is not bool:
                    raise ValueError("confirm requires a boolean accept")
                accept = kind == "approve" or (kind == "confirm" and command["accept"])
                agent, request_id = command.get("agent"), command.get("request_id")
                reason = str(command.get("reason") or "")
                remember = command.get("remember") if accept else None
                remember = "once" if remember == "step" else remember
                if agent:
                    if not isinstance(request_id, str) or not request_id:
                        raise ValueError("a sub-agent answer requires the request_id from its waiting message")
                    host.approve(conversation.run, accept, reason, str(agent), remember, request_id=request_id)
                else:
                    conversation.confirm(accept, reason, remember,
                                         **({"request_id": request_id} if request_id else {}))
            else:
                name = {"stop": "end", "confirm": "approve" if command.get("accept") else "reject"}.get(kind, kind)
                if not COMMANDS.get(name, COMMANDS["help"]).method:
                    raise ValueError(f"unknown type {kind!r}")
                run_command(conversation, name, {key: str(command[key]) for key in ("remember", "reason")
                                                 if command.get(key) is not None})
                if name == "end":
                    break
        except (ValueError, KeyError, OSError, RuntimeError) as error:
            send({"type": "error", "message": f"{type(error).__name__}: {error}"})
    if watching is not None:
        watching.set()
    if conversation is not None and streaming is not None:
        try:
            conversation.close()
        except Exception:
            pass
        streaming.join(5)
    return 0


def _default(args):
    """harness with no command: the terminal chat with the agent on this computer, which
    starts a conversation with the first message; the first run asks for the model and key."""
    if not _coding(args).get("agent"):
        _ready_model(interactive=True)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise UsageError("the terminal chat needs a terminal: harness run \"task\", or harness run rpc")
    from . import tui

    tui.chat(start=_starter(args))
    return 0


def _session_commands(parser):
    actions = parser.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("ls")
    listing.add_argument("--kind")
    listing.add_argument("--project")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--json", action="store_true")
    importing = actions.add_parser("import")
    importing.add_argument("provider", choices=("claude-code", "codex"))
    importing.add_argument("file", type=Path)
    importing.add_argument("--follow", action="store_true")
    discover = actions.add_parser("discover")
    discover.add_argument("agent")
    discover.add_argument("--folder", type=Path)
    discover.add_argument("--cursor")
    observe = actions.add_parser("observe")
    observe.add_argument("agent")
    observe.add_argument("external_id")
    observe.add_argument("--folder", type=Path)
    reconnect = actions.add_parser("reconnect")
    reconnect.add_argument("session")
    reconnect.add_argument("--agent")
    reconnect.add_argument("--released", action="store_true", help="the previous controller has stopped")
    for name in ("show", "stop", "cancel", "diff", "merge", "discard", "attach"):
        actions.add_parser(name).add_argument("session")
    for name in ("send", "steer", "terminal"):
        send = actions.add_parser(name)
        send.add_argument("session")
        send.add_argument("text")
    config = actions.add_parser("config")
    config.add_argument("session")
    config.add_argument("id")
    config.add_argument("value")
    approve = actions.add_parser("approve")
    approve.add_argument("session")
    approve.add_argument("request_id")
    approve.add_argument("--agent")
    approve.add_argument("--reject", action="store_true")
    answer = actions.add_parser("answer")
    answer.add_argument("session")
    answer.add_argument("request_id")
    answer.add_argument("content", type=json.loads, help="JSON object, or null to decline")
    handoff = actions.add_parser("handoff")
    handoff.add_argument("session")
    handoff.add_argument("agent")
    handoff.add_argument("context")
    handoff.add_argument("--folder", type=Path)
    handoff.add_argument("--isolation", choices=("folder", "worktree"))


def _sessions(args):
    from .host import Host
    from .host.sessions import COLUMNS, table_rows

    host = Host.connect(start=False)
    if host is None:
        host = Host.connect()
    action = args.action
    if action == "ls":
        project = str(Path(args.project).resolve()) if args.project else None
        rows = [session.row for session in host.sessions(all=args.all, limit=0)
                if (not args.kind or session.row.get("kind") == args.kind)
                and (not project or session.row.get("project") in (project, args.project))]
        if args.json:
            output(rows)
        else:
            print(table(table_rows(rows), COLUMNS))
    elif action == "import":
        output({"run": host.import_session(args.file.resolve(), args.provider, follow=args.follow).run})
    elif action == "discover":
        output(host.discover_sessions(args.agent, args.folder.resolve() if args.folder else None, args.cursor))
    elif action == "observe":
        output({"run": host.observe_external(args.agent, args.external_id,
                                             folder=args.folder.resolve() if args.folder else None).run})
    elif action == "reconnect":
        output({"run": host.reconnect_session(args.session, released=args.released, agent=args.agent).run})
    elif action == "show":
        output(host.session(args.session).row)
    elif action == "stop":
        output({"stopped": host.stop_session(args.session)})
    elif action == "approve":
        output({"agent": host.approve(args.session, not args.reject, agent=args.agent, request_id=args.request_id)})
    else:
        conversation = host.conversation(args.session)
        if action == "attach":
            from . import tui

            row = conversation.describe()
            if os.name == "posix" and row.get("kind") == "terminal":
                from .tui.pty import attach

                attach(conversation, host)
            else:
                tui.chat(conversation, host=host)
        elif action in ("diff", "merge", "discard", "cancel"):
            output(getattr(conversation, action)() or {"ok": True})
        elif action == "handoff":
            next_session = conversation.handoff(args.agent, args.context, folder=args.folder, isolation=args.isolation)
            output({"run": next_session.run})
        elif action == "config":
            output(conversation.set_config(args.id, args.value))
        elif action == "answer":
            conversation.answer(args.request_id, args.content)
        else:
            method = {"send": "send_message", "steer": "steer", "terminal": "terminal_input"}[action]
            getattr(conversation, method)(args.text)
    return 0


def _replay(args):
    """harness replay RUN: terminal records, or raw records with --json."""
    from .core.episodes import read_records
    from .host import resolve_run

    directory = resolve_run(args.run)
    records = read_records(directory)
    if not records:
        raise ValueError(f"no trace at {directory}")
    from .terminal import Printer

    printer = Printer()
    for record in records:
        if args.json:
            print(json.dumps(record, ensure_ascii=False), flush=True)
        else:
            for line in printer.lines(record):
                print(line, flush=True)
    return 0


def _library_command(args):
    """harness library: the libraries, and a library's or a run's memory (runtime/task/context.py
    rows), as the app and the terminal chat show them."""
    from .paths import home
    from harness.runtime.learning import learner
    from harness.core import memory as memory_view

    if args.what == "ls":
        rows = learner.libraries()
        if args.json:
            output(rows)
        elif rows:
            print(table([{**row, "version": row["version"][:12], "entries": str(row["entries"])} for row in rows],
                        ["name", "entries", "version", "directory"]))
        else:
            print(f"No library under {home() / 'libraries'}")
        return 0
    if not args.path:
        raise ValueError("harness library show LIBRARY or RUN (a directory, or a library's name under "
                         "$HARNESS_HOME/libraries)")
    path = Path(args.path)
    if not path.is_dir():
        path = home() / "libraries" / args.path
    found = memory_view.rows(run=path) if (path / "events.jsonl").is_file() else memory_view.rows(library=path)
    if args.json:
        output(found)
    else:
        print(table([dict(zip(memory_view.COLUMNS, row["cells"])) for row in found], list(memory_view.COLUMNS))
              if found else "(empty)")
    return 0


def main(argv=None):
    words = list(sys.argv[1:] if argv is None else argv)
    if words[:1] == ["rpc"]:
        words.insert(0, "run")
    if words[:1] == ["chat"]:
        words.pop(0)
    if words[:2] == ["host", "serve"]:
        from .host.server import main as serve

        return _guarded(lambda: serve(words[2:]))
    if words[:2] == ["run", "experiment"]:
        return _guarded(lambda: _experiment(words[2:]))
    explicit_task = "--" in words
    if words[:1] == ["run"] and len(words) > 1 and not explicit_task:
        first = words[1]
        if _is_experiment(first) or first.partition("=")[0] in ("--resume", "--dry-run", "--script"):
            return _guarded(lambda: _experiment(words[1:]))
    if words and not words[0].startswith("-") and words[0] not in core_commands() and (
            words[0] in FIRST_USE or words[0] in package_commands()):
        return _guarded(lambda: _package_command(words[0], words[1:]))
    command_parser = parser()
    args, rest = command_parser.parse_known_args(words)
    if rest and args.command != "doctor":
        command_parser.parse_args(words)  # says what it does not know, exit status 2
    if args.command not in (None, "install", "remove", "list"):
        # The enabled packages' skills load here and in the kernels it starts.
        from .packages import activate

        activate()
    commands = {"install": _install, "list": _list, "remove": _remove, "library": _library_command, "sessions": _sessions,
                "replay": _replay}
    if args.command == "run":
        if args.task == "rpc" and not explicit_task:
            if args.print or args.json:
                command_parser.error("harness run rpc already uses JSON lines")
            return _guarded(lambda: _rpc(args))
        return _guarded(lambda: _run_task(args))
    if args.command == "doctor":
        return _guarded(lambda: _doctor(args, words[words.index("doctor") + 1:]))
    if args.command is None:
        return _guarded(lambda: _default(args))
    return _guarded(lambda: commands[args.command](args))
