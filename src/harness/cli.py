"""The command line, in the forms people know from Claude Code and Hermes:

    harness                          the terminal chat (tui/): the first run asks for the model
    harness "first message"          the chat, started with that message
    harness -p "question"            answer and exit; what is piped in goes with the question
                                     (--output-format text | json | stream-json)
    harness -c | -r [CHAT]           go on with the most recent chat, or with one by id or title
    harness setup | model            the first run again; the model only
    harness status                   version, model, identity, session host, what is connected
    harness doctor                   what is missing here, each with its fix
    harness config show | get | set | unset | edit | path      the settings
    harness sessions                 the chats (list, rename, archive, delete) and the sessions of tasks
    harness logs [NAME] [-n N] [-f]  the logs
    harness mcp list | add | remove | test       the MCP servers the agent uses (mcp serve: as a server)
    harness host [status | start | stop | restart | install | uninstall]     the session host
    harness run "task" [-p] [--json] do a task and end: -p prints only the answer, --json every record
    harness run rpc                  drive the agent from another program: JSON lines both ways
    harness install | list | remove  packages (list searches the registry and shows one package)
    harness library                  what the agent learned: libraries; an identity's skills, its tree
                                     of reactions (harness library tree [PATH]) and its memory
    harness replay RUN               a run as it went, in the terminal
    harness completion SHELL         a completion script

A word that is no command is the first message of the chat, unless it is one word close to a
command: then harness says which it may have been and ends with status 2, starting nothing.

Installed packages add their own commands (package.toml [provides] commands, with a line of
help each in the package's commands.toml); `harness run EXPERIMENT` and `harness doctor EXPERIMENT` are
the eval package's; harness agent, usage, calendar, channels and skills the agent package's,
harness agents the external-agents package's (installed on first use). Two commands of
packages share a name with the core's: harness config EXPERIMENT is the eval package's (the
core's takes show, get, set, unset, edit and path), and harness status with service names
or --deploy is the local-models package's.
"""

import argparse
import importlib
import json
import os
from pathlib import Path
from queue import Queue
import re
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
        # A person reads one line; a program reads the choice as JSON.
        print(f"harness: {error}" if sys.stderr.isatty() else
              json.dumps({"error": str(error), "choice_required": error.choice}), file=sys.stderr, flush=True)
        return 2
    except UsageError as error:
        print(json.dumps({"error": f"usage: {error}"}), file=sys.stderr, flush=True)
        return 2
    except (ValueError, KeyError, OSError, RuntimeError, ImportError, TimeoutError) as error:
        # A person reads the reason and what to do; a program reads one JSON object.
        from .problems import said

        print(said(error, program=not sys.stderr.isatty()), file=sys.stderr, flush=True)
        return 1


def _package_arguments(command):
    command.add_argument("--project", action="store_true", help="the project's packages (harness.toml and "
                                                                "harness.lock here or above) instead of yours")
    command.add_argument("--json", action="store_true")


def _levels(section: str):
    """A settings section's level choices (those a package registers, such as physical and privacy), or
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
    command.add_argument("--bare", action="store_true",
                         help="read no instruction files (~/.harness/AGENTS.md, the project's AGENTS.md) in this "
                              "conversation")


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
                         help="accepted for older command lines; it has no effect (the model's turn is its own "
                              "while a program runs).")
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
                              "the connected tools only), space (any Agent Space Protocol space, entered by its "
                              "address: --space) or a kind the installed packages give (harness packages "
                              "lists them; one that works in a folder takes it with --folder). Without it (and "
                              "without --folder) the setting session.environment decides: ask (the default) asks "
                              "in an interactive terminal and is an error elsewhere, last takes the last choice, a "
                              "kind takes that kind")
    command.add_argument("--space", metavar="ADDRESS",
                         help="work in the space at this address (a ws:// or http:// URL of an Agent Space Protocol "
                              "space; --workspace space): the agent acts through its vocabulary")
    if command.prog.split()[-1] == "run":
        # The packages' own flags for a run (a host module's run_arguments).
        from . import extensions

        extensions.run_arguments(command)


def workspace_sets(args) -> list[str]:
    """harness run --workspace, and the packages' own flags, as experiment overrides (the
    worker's options; a host module's run_sets says what its flags stand for)."""
    kind = getattr(args, "workspace", None)
    if args.command != "run" or isinstance(getattr(args, "config", None), str):
        return []
    from . import extensions

    return ([f"worker.workspace={json.dumps(kind)}"] if kind else []) + extensions.run_sets(args)


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
FIRST_USE = {"agent": "agent", "usage": "agent", "calendar": "agent", "channels": "agent", "skills": "agent",
             "agents": "external-agents", "mcp": "mcp-server"}
# harness library's words that are an agent identity's (the agent package's library_command).
AGENT_LIBRARY = ("skills", "tree", "memory", "undo")


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


def _continue_arguments(command, name: str):
    """The flags that go on with an earlier session in its own id instead of starting one."""
    which = command.add_mutually_exclusive_group()
    which.add_argument("--continue", dest="continue_last", action="store_true",
                       help="go on with the session you last messaged or resumed, in the same session id")
    which.add_argument(name, dest="session", metavar="SESSION",
                       help="go on with that session (its id, as harness sessions ls --all lists it)")


def _continued(args):
    """(host, conversation, the last record's seq) of the session --continue or its id names,
    continued in the session host; None when neither was given."""
    if not (getattr(args, "continue_last", False) or getattr(args, "session", None)):
        return None
    from urllib.parse import quote

    from .host import Host

    host = Host.connect(log=_note)
    conversation = host.resume_session(getattr(args, "session", None) or None)
    records = host.get(f"/api/events?run={quote(conversation.run, safe='')}&after=-1") or []
    return host, conversation, max((int(record.get("seq", -1)) for record in records), default=-1)


def _check_continuation_options(args):
    """A continuation uses its saved settings; reject new-task options before any host call."""
    if not (getattr(args, "continue_last", False) or getattr(args, "session", None)):
        return
    selection = any(getattr(args, key, None) is not None for key in ("model", "effort", "workspace", "vm_image", "library"))
    if selection or _coding(args) or _run_options(args) or getattr(args, "learn_while_working", False):
        raise UsageError("continuation keeps the saved model, workspace and run settings; "
                         "omit --model/--effort and other new-conversation options with --continue/--resume/--session. "
                         "In an open terminal, /effort LEVEL changes that conversation; /model selects only new ones")


def parser(packages: bool = True):
    root = argparse.ArgumentParser(prog="harness", description="Automatic Control for intelligence in action.",
                                   epilog="harness with no command: the terminal chat with the agent on this computer "
                                          "(/help lists its commands: sessions, the session host, settings, model, "
                                          "packages, library)")
    root.add_argument("--version", action="version", version=f"harness {__version__}")
    _continue_arguments(root, "--resume")
    root.add_argument("--model", help="an enabled model from ~/.harness/models.json (ID or provider/model)")
    root.add_argument("--effort", help="the selected model's reasoning effort ID")
    run_flags(root)
    _coding_arguments(root)
    root.add_argument("--identity", help="the agent identity this chat runs as (default: the current one, harness "
                                         "agent use; with several and none chosen it asks)")
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
    # (harness run --resume OUTPUT is the eval package's: a session is named with --session here.)
    _continue_arguments(run, "--session")
    run.add_argument("--library", type=Path, help="explicit reusable learning library: its folder, or its name under "
                                                "$HARNESS_HOME/libraries (where an installed one is); frozen unless "
                                                "--learn-while-working")
    run.add_argument("--learn-while-working", action="store_true", help="learn during the task into --library")
    run_flags(run)
    _coding_arguments(run)
    run.add_argument("--managed-workspace", action="store_true", help="use an isolated managed workspace (supported Linux hosts)")
    _session_commands(commands.add_parser("sessions", help="Manage the session host's coding sessions"))
    install = commands.add_parser("install", help="Install packages (and what they depend on), or update them; and "
                                                  "the services and benches they provide",
                                  epilog="harness install browser; harness install computer@^0.9; harness install "
                                         "git:github.com/x/y@main#packages/z; harness install ./my-package --link; "
                                         "harness install --update (all); harness install NAME (a service). With no "
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
    install.add_argument("--tui", action="store_true", help="prepare the terminal interface's pinned libraries, "
                                                          "without starting a conversation")
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
    library.add_argument("what", nargs="?", choices=["ls", "show", *AGENT_LIBRARY], default="ls",
                         help="ls (default): the libraries under $HARNESS_HOME/libraries; show LIBRARY or RUN; "
                              "an identity's skills, tree [PATH] (its tree of reactions, one level like a folder), "
                              "memory, undo SKILL (--identity ID)")
    library.add_argument("path", nargs="?", help="show: a library's directory or its name under "
                                                 "$HARNESS_HOME/libraries, or a run's directory; tree: node names "
                                                 "from the root joined by /")
    library.add_argument("--json", action="store_true", help="JSON")
    share = commands.add_parser("share", help="Send what an agent learned (a library) as a package that one line "
                                              "installs: to GitHub, another git remote, a folder (a website's files) "
                                              "or another computer",
                                epilog="harness share my-app github:alice/my-app; harness share my-app "
                                       "git:https://git.example.com/alice/agents.git#my-app; harness share my-app "
                                       "./site/agents --url https://alice.dev/agents; harness share my-app "
                                       "alice@alice.dev:/var/www/agents --url https://alice.dev/agents. Others "
                                       "install it with the line it prints. Memory entries (what the agent saw on "
                                       "this computer) stay unless --with-memory.")
    share.add_argument("library", help="a library's folder, or its name under $HARNESS_HOME/libraries")
    share.add_argument("destination", help="github:OWNER/REPO[#FOLDER], git:URL[#FOLDER], USER@HOST:FOLDER (scp), "
                                           "or a folder or .tar.gz file on this computer")
    share.add_argument("--name", help="the package's name (default: the library's)")
    share.add_argument("--version", dest="package_version", metavar="VERSION", help="the package's version (default: the one there, "
                                                                 "its patch raised; else 0.1.0)")
    share.add_argument("--summary", help="one line that says what it learned")
    share.add_argument("--with-memory", action="store_true", help="also send the memory entries")
    share.add_argument("--private", action="store_true", help="github: a repository it creates is private")
    share.add_argument("--url", help="the web address of the folder the archive goes to, for the "
                                                 "line that installs it")
    share.add_argument("--yes", "-y", action="store_true", help="send without asking")
    share.add_argument("--json", action="store_true", help="JSON")
    replay = commands.add_parser("replay", help="Replay a run in the terminal")
    replay.add_argument("run", help="an episode directory, a conversation (its name under conversations/), or a "
                                    "session (SESSION or SESSION/AGENT)")
    replay.add_argument("--json", action="store_true", help="every record of its trace as a JSON line")
    instructions = commands.add_parser("instructions", help="The instruction files (AGENTS.md) a conversation "
                                                            "working in FOLDER reads, and why others are left out")
    instructions.add_argument("folder", nargs="?", type=Path, default=Path("."),
                              help="the conversation's folder (default: this one)")
    instructions.add_argument("--json", action="store_true", help="the files as JSON")
    update = commands.add_parser("update", help="Update this pip install (pip install -U the-harness) and the installed "
                                                "packages; the desktop app updates itself")
    update.add_argument("--check", action="store_true", help="only say whether PyPI has a newer version")
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
    # The deploy and its GPUs matter only where a package places services and a deploy says where.
    placed = doctor is not None and not isinstance(deploy, NoDeploy)
    if args.names and not placed:
        return _usage("doctor", "checking services needs the local-models package (harness install local-models)")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # a console whose code page lacks ✓ or →
    report = _core_report(host=True) if not args.names else {"ok": True, "problems": [], "notes": [], "checks": []}
    if placed:
        services = doctor(deploy, names=args.names or None, core=core)
        report = {**services, "checks": report["checks"], "ok": report["ok"] and services["ok"],
                  "problems": [*report["problems"], *services.get("problems", [])],
                  "notes": [*report["notes"], *services.get("notes", [])]}
    report["packages"] = Packages().installed()
    _package_problems(report)
    if args.json:
        output(report)
        return 0 if report["ok"] else 1
    if report["checks"]:
        print(f"The Harness {__version__}")
        print("\n".join(doctor_lines(report["checks"])))
    if placed and (args.names or args.deploy or services.get("deploy") != "none" or services.get("installed")
                   or services.get("problems")):
        # Where services run: only when a deploy says so (not for a computer that uses hosted models).
        print(f"\ndeploy {report['deploy']}: {'ready' if services['ok'] else 'NOT ready'}")
        if report.get("gpus") is not None:
            print(table(report["gpus"], ["index", "name", "used_gb", "total_gb"]))
        if report.get("installed"):
            print(table(report["installed"], ["name", "what", "installed", "environment"]))
        if report.get("to_install"):
            print(f"the agent would still install: {', '.join(report['to_install'])} (on its first run, "
                  f"or now: harness install {' '.join(report['to_install'])})")
        for problem in services.get("problems", []):
            print(f"  problem: {problem}")
        for note in services.get("notes", []):
            print(f"  note: {note}")
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
    told = " ".join(report.get("problems", []))
    report["problems"] = [*report.get("problems", []), *(why for why in found.values() if why not in told)]
    report["ok"] = report.get("ok", True) and not found


def _core_report(host: bool = False) -> dict:
    """harness doctor with nothing named: the harness itself, whether a model is set up and
    (`host`) whether the session host starts: `checks`, each with its fix; `problems` are the
    ones that failed, as text."""
    checks = doctor_checks(host=host)
    problems = [f"{row['detail']}: {row['fix']}" if row["fix"] else row["detail"] for row in checks if not row["ok"]]
    return {"schema_version": 1, "deploy": "none", "ok": not problems, "problems": problems, "notes": [],
            "checks": checks, "gpus": None, "services": [], "installed": [], "to_install": []}


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


def _left_out(rows: list) -> None:
    """Mark the packages the running session host left out (its `problems`: a host module
    that did not import, a background service that did not start), which only it knows."""
    from .host import Host

    try:
        host = Host.connect(start=False)
    except (OSError, ValueError, RuntimeError):
        host = None
    found = (getattr(host, "state", None) or {}).get("problems") or {}
    for row in rows:
        if row.get("name") in found and "problem" not in row:
            row["problem"] = found[row["name"]]


def _list(args):
    """harness list [QUERY] [--available]: the installed packages (QUERY filters them), the
    registry's (--available; QUERY searches them), one package's description when QUERY is
    its exact name."""
    from .packages import Packages

    packages = Packages()
    rows = packages.search(args.query) if args.available else [
        row for row in packages.installed() if not args.query or args.query.lower() in str(row.get("name")).lower()]
    if not args.available:
        _left_out(rows)
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

    terminal = getattr(args, "tui", False)
    if terminal and args.update:
        raise UsageError("--tui prepares the terminal; run it separately from --update")
    packages = activate(Packages())
    if args.update:
        result = packages.update(args.names, project=args.project, log=_note)
        output(result) if args.json else [print(f"{row['name']} {row['version']}") for row in result["installed"]]
        return 0
    deploy = load_deploy(args.deploy)
    known = set(deploy.services) | set(bench_specs())
    specs = [name for name in args.names if name not in known]
    result = {"installed": [], "problems": []}
    if specs or (not args.names and args.project) or (not args.names and not terminal and packages.project() is not None):
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
    elif not args.names and not terminal:
        return _usage("install", "name packages, services or benches (or run it where harness.toml names the "
                                 "project's packages)")
    # A name a package just brought (a bench) is installed as one now too: its environment.
    known = set(deploy.services) | set(bench_specs())
    provisioned = [name for name in args.names if name in known]
    benches = [name for name in provisioned if name in bench_specs()]
    services = [name for name in provisioned if name not in benches]
    rows = [provision.install_bench_environment(deploy, name, log=_note) for name in benches]
    if terminal:
        from .tui import environment
        from .packages import environments

        prepared = environment()
        environments.install(prepared, log=_note)
        rows.append({"name": "tui", "what": "frontend", "installed": True,
                     "environment": str(prepared.directory)})
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
        for row in result.get("libraries", ()):
            print(f"  library {row['name']}: {row['status']}, {row['path']}"
                  + (f" (use it: harness run \"...\" --library {row['name']})" if row["status"] != "kept" else ""))
        if rows:
            print(table(rows, ["name", "what", "installed", "environment"]))
    return 0


def _usage(command, message):
    print(f"harness {command}: {message}", file=sys.stderr)
    return 2


MCP_COMMANDS = ("list", "ls", "add", "get", "remove", "rm", "enable", "disable", "test")


def _mcp(words) -> int:
    """harness mcp list | add | get | remove | enable | disable | test: the MCP servers the
    agent may use (host/connectors.py), in the forms of `claude mcp`. harness mcp serve, and
    harness mcp with no command, are the mcp-server package's: The Harness as an MCP server."""
    from .host import connectors

    parser = argparse.ArgumentParser(prog="harness mcp", description="The MCP servers the agent may use: list, add, "
                                     "remove, test. (harness mcp serve: The Harness itself as an MCP server.)")
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("list", "ls"):
        commands.add_parser(name, help="the MCP servers you connected").add_argument("--json", action="store_true")
    add = commands.add_parser("add", help="connect an MCP server: NAME URL, or NAME -- COMMAND ARGS",
                              epilog="harness mcp add --transport http notes https://mcp.example.com/mcp; "
                                     "harness mcp add --env API_KEY=... files -- npx -y @example/files-server")
    add.add_argument("--transport", choices=("stdio", "http"), help="stdio: a command started on this computer "
                     "(the default for a command); http: a server at a URL (the default for a URL)")
    add.add_argument("--env", "-e", action="append", default=[], metavar="KEY=VALUE",
                     help="an environment variable of the command (repeat); kept with your credentials")
    add.add_argument("--header", "-H", action="append", default=[], metavar="NAME: VALUE",
                     help="a header sent to the URL (repeat); kept with your credentials")
    add.add_argument("--tools", metavar="A,B", help="only these of its tools may be called (default: all)")
    add.add_argument("name")
    add.add_argument("target", nargs=argparse.REMAINDER, help="its URL, or after -- its command and arguments")
    for name, text in (("get", "one server: what it is"), ("remove", "disconnect a server"), ("rm", "disconnect a server"),
                       ("enable", "switch a server on again"), ("disable", "switch a server off without removing it"),
                       ("test", "connect to it once and list its tools")):
        command = commands.add_parser(name, help=text)
        command.add_argument("name")
        if name in ("get", "test"):
            command.add_argument("--json", action="store_true")
    args = parser.parse_args(words)

    def line(row):
        state = "" if row["enabled"] else "  (off)"
        return f"  {row['name']:<20} {row['transport']:<6} {row['target'][:70]}{state}"

    if args.action in ("list", "ls"):
        rows = connectors.mcp_servers()
        if args.json:
            output(rows)
        else:
            print("\n".join(line(row) for row in rows) if rows else
                  "no MCP servers yet: harness mcp add NAME URL, or harness mcp add NAME -- COMMAND ARGS")
        return 0
    if args.action == "add":
        target = [word for index, word in enumerate(args.target) if not (index == 0 and word == "--")]
        if not target:
            raise UsageError("harness mcp add NAME URL, or harness mcp add NAME -- COMMAND ARGS")
        remote = target[0].startswith(("http://", "https://")) and len(target) == 1
        if args.transport == "http" and not remote:
            raise UsageError("--transport http takes one URL")
        stdio = args.transport == "stdio" or not remote
        if stdio and args.header:
            raise UsageError("--header goes with a URL; a command takes --env")
        if not stdio and args.env:
            raise UsageError("--env goes with a command; a URL takes --header")

        def pairs(given, separator, what):
            found = {}
            for item in given:
                key, found_separator, value = item.partition(separator)
                if not found_separator or not key.strip():
                    raise UsageError(f"{what} is given as {what.upper()[0]}{separator}VALUE, not {item!r}"
                                     if separator == "=" else f"a header is given as \"Name: value\", not {item!r}")
                found[key.strip()] = value.strip()
            return found

        row = connectors.mcp_add(args.name, command=target[0] if stdio else None, args=target[1:] if stdio else (),
                                 url=None if stdio else target[0], env=pairs(args.env, "=", "key"),
                                 headers=pairs(args.header, ":", "header"),
                                 tools=[tool.strip() for tool in args.tools.split(",") if tool.strip()]
                                 if args.tools else None)
        print(f"Added {row['transport']} MCP server {row['name']}: {row['target']}")
        print(f"  harness mcp test {row['name']} connects to it and lists its tools")
        return 0
    if args.action in ("remove", "rm"):
        connectors.mcp_remove(args.name)
        print(f"Removed MCP server {args.name}")
        return 0
    if args.action in ("enable", "disable"):
        row = connectors.mcp_enable(args.name, args.action == "enable")
        print(f"{row['name']} is {'on' if row['enabled'] else 'off'}")
        return 0
    if args.action == "get":
        row = next((row for row in connectors.mcp_servers() if row["name"] == args.name), None)
        if row is None:
            connectors.mcp_remove(args.name)  # says that there is none, and what to do
        if args.json:
            output(row)
        else:
            print(f"{row['name']}:\n  transport {row['transport']}\n  {'command' if row['transport'] == 'stdio' else 'url'} "
                  f"{row['target']}\n  {'on' if row['enabled'] else 'off'}"
                  + (f"\n  environment {', '.join(row['env'])}" if row["env"] else "")
                  + (f"\n  headers {', '.join(row['headers'])}" if row["headers"] else "")
                  + f"\n  tools it may call: {', '.join(row['tools']) or 'none'}")
        return 0
    print(f"connecting to {args.name} …", file=sys.stderr, flush=True)
    found = connectors.mcp_test(args.name)
    if args.json:
        output(found)
    else:
        print(f"✓ {found['name']} answered in {found['seconds']} s with {len(found['tools'])} tool"
              f"{'' if len(found['tools']) == 1 else 's'}")
        for tool in found["tools"]:
            print(f"  {tool['name']:<24} {tool['description'][:90]}")
    return 0


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


# What _ready_model gives when the user left the first run.
LEFT = object()


def _first_run(*, only_model: bool = False) -> bool:
    """Go through the first run in this terminal (tui/first.py): whether a model is in use
    at its end. False: the user left it, and nothing was changed."""
    from . import __version__, tui
    from .packages import activate
    from .paths import data

    activate()  # the packages' parts of it: an agent as the model, an agent to bring over
    tui.load(log=_note)
    from .tui.first import run

    return run(data(), version=__version__, only_model=only_model)


def _setup(words: list) -> int:
    """harness setup: the first run again (the model, an agent to bring over, running in the
    background). harness model, harness setup model: the model only. harness model --list:
    what on this computer can be the model, as JSON."""
    from . import onboarding
    from .paths import data

    rest = words[1:]
    if rest in (["-h"], ["--help"]) or (rest and rest[0] not in ("model", "--list")):
        for line in ("usage: harness setup [model]    the first run again: the model, an agent to bring over, the background",
                     "       harness model            choose the model: an agent signed in here, a provider's key, a local model",
                     "       harness model --list     what on this computer can be the model (JSON)"):
            print(line)
        return 0 if rest in (["-h"], ["--help"]) else 2
    if rest == ["--list"]:
        from .packages import activate

        activate()
        output(onboarding.found(data()))
        return 0
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise UsageError("harness setup asks its questions in a terminal; harness model --list shows what is here")
    return 0 if _first_run(only_model=words[0] == "model" or rest == ["model"]) else 1


def _ready_model(interactive: bool, *, recovery: bool = False) -> str | None:
    """A model in use, asked for in a terminal when there is none yet. The terminal chat
    (`recovery`) goes through the whole first run when it was never gone through here
    (onboarding.needed), and gets LEFT when the user leaves it."""
    from . import onboarding, providers
    from .paths import data

    if recovery and interactive and onboarding.needed(data()):
        return None if _first_run() else LEFT
    model = providers.ready(data())
    if model["ready"]:
        return
    if model.get("selection_error") or ((data() / "models.json").exists() and
                                         model["detail"].startswith("add an enabled model")):
        if recovery:
            return f"{model['detail']}; use /model to choose an enabled model or /models to edit the list"
        raise UsageError(model["detail"])
    if not (interactive and sys.stdin.isatty() and sys.stdout.isatty()):
        raise UsageError("no model is set up yet: run harness setup in a terminal (it finds an agent signed in "
                         "here, a provider's key or a local model and tries it), or export a provider's key")
    if not _first_run(only_model=True):
        raise UsageError("no model is set up: harness setup")


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
    if getattr(args, "bare", False):
        options["instructions"] = {"load": "off"}
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
    return {key: value for key, value in {"agent": agent, "folder": folder, "space": getattr(args, "space", None),
                                           "isolation": getattr(args, "isolation", None),
                                           "mcp_tools": getattr(args, "mcp_tools", None)}.items() if value is not None}


def _starter(args):
    """The terminal chat's start(text, files, log, learn): a conversation of the app's agent with
    the options harness was given (--workspace, --physical, ...); `learn` (/learn): one that learns
    its environment for that many minutes. It keeps the last it started."""
    def start(text, files=(), log=None, learn=None, model_entry=None, reasoning_effort=None, workspace=None,
              folder=None, agents=None):
        # Effort belongs to the startup route. A route picked in the TUI with no
        # effort explicitly asks for that route's default, not the CLI route's effort.
        if model_entry is None and start.model_entry is not None:
            model_entry = start.model_entry
            if reasoning_effort is None:
                reasoning_effort = start.model_effort
        runtime = {**_run_options(args), **({"learn": learn} if learn is not None else {}),
                   **({"agents": True} if agents else {})}
        coding = _coding(args)
        if start.identity and not coding.get("agent"):
            # Its conversations are the identity's (and charged to it).
            runtime.update(start.identity.get("runtime") or {})
        workspace = workspace or getattr(args, "workspace", None)
        if folder and not coding.get("agent"):
            coding["folder"] = Path(folder)
        library = getattr(args, "library", None)
        if library is not None and not library.exists() and len(library.parts) == 1:
            from .packages.libraries import libraries_root

            if (libraries_root() / library.name).is_dir():
                library = libraries_root() / library.name
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
            if selected["provider"].startswith("terminal:"):
                coding["folder"] = Path.cwd()
        start.host, start.conversation = _task(text, workspace,
                                                           runtime=runtime, files=files, log=log, **coding,
                                                           model_entry=model_entry, reasoning_effort=reasoning_effort)
        return start.host, start.conversation

    start.host = start.conversation = None
    start.identity = None
    start.model_entry = start.model_effort = start.model_name = None
    if not _coding(args).get("agent") and not (
            getattr(args, "continue_last", False) or getattr(args, "session", None)) and (
            getattr(args, "model", None) is not None or getattr(args, "effort", None) is not None):
        from .model_list import SelectionError, select
        from .paths import data

        try:
            initial = select(data(), getattr(args, "model", None))
        except SelectionError:
            # An effort-only flag must not close the UI needed to repair a default.
            if getattr(args, "model", None) is not None:
                raise
            initial = None
        if initial is not None:
            start.model_entry, start.model_effort = initial["id"], getattr(args, "effort", None)
            start.model_name = initial["name"]
    # The command line already says where it works: the chat does not ask at its opening.
    start.named = bool(getattr(args, "workspace", None) or getattr(args, "folder", None)
                       or getattr(args, "agent", None))
    return start


def _turn_over(record, answered: bool) -> bool:
    """Whether the turn is over with `record`: its result (turn_result), the conversation's
    end, or an agent of another harness that answered and waits."""
    status = record.get("status") if record.get("event") == "state" else None
    return record.get("event") == "turn_result" or status in ENDED or (status == "IDLE" and answered)


def _ask(question: str) -> str:
    """A line typed in answer to `question`, asked on stderr (stdout may be the answer's pipe)."""
    print(question, end="", file=sys.stderr, flush=True)
    return input().strip()


def _choose_first_use(choice):
    """The interactive run command: require an explicit numbered answer."""
    from .host import Host

    print(choice["title"], file=sys.stderr)
    for index, option in enumerate(choice["options"], 1):
        print(f"  {index}. {option['label']}", file=sys.stderr)
    while True:
        try:
            answer = _ask("Choose a number (no default; q cancels): ")
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
            answer = _ask(ask)
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
        folder = _ask(f"Folder to work in [{suggested}]: ") or suggested
    except EOFError:
        raise UsageError("choice cancelled; task not started") from None
    return row["value"], str(Path(folder).expanduser())


def _run_task(args):
    """harness run "task": the agent on this computer does it and the command ends with the
    turn (its answer, or the limit, error or interrupt that ended it), closing the
    conversation; -p prints only the answer, --json every record."""
    from .terminal import Printer
    from .transcript import answer_of

    _check_continuation_options(args)
    if args.model and _coding(args).get("agent"):
        raise UsageError("--model selects its own provider; use either --model or --agent")
    if not _coding(args).get("agent") and not args.model and not (
            getattr(args, "continue_last", False) or getattr(args, "session", None)):
        _ready_model(interactive=True)
    from .settings import ChoiceRequired

    start = _starter(args)
    place = {}
    continued = _continued(args)
    after = -1
    while True:
        if continued is not None:
            # The task is the next message of that session; only what follows it is shown.
            host, conversation, after = continued
            conversation.send_message(args.task)
            break
        try:
            host, conversation = start(args.task, learn=getattr(args, "learn", None),
                                       model_entry=args.model, reasoning_effort=args.effort, **place)
            break
        except ChoiceRequired as error:
            # Nobody to ask: the error names the flag; nothing is chosen for the user. The
            # question goes to stderr, so `answer=$(harness run "task" -p)` still asks.
            if args.json or not (sys.stdin.isatty() and sys.stderr.isatty()):
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
        for record in conversation.records(after=after):
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
    messages to it: after a turn_result record a message starts its next turn; files: paths
    it attaches), {"type": "message", "text", "files"}, and the terminal
    chat's commands with a method (terminal.COMMANDS): pause, continue, {"type": "approve",
    "remember", "reason"}, {"type": "reject", "reason"}, end; {"type": "confirm", "accept",
    "reason", "remember"} is approve or reject, stop is end; with "agent", they answer that
    sub-agent. Out: {"type": "started", "run"}, {"type": "record", "record"}, {"type":
    "waiting", "agent", "what"} (a sub-agent waits for the user), {"type": "error", "message"};
    it ends when stdin closes, after end, or when the conversation ends."""
    from .terminal import COMMANDS, command as run_command

    if getattr(args, "continue_last", False) or getattr(args, "session", None):
        raise UsageError("run rpc starts a new conversation; use harness run --continue or --session ID "
                         "for an existing conversation")
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


def _as_identity(args) -> bool:
    """Whether the terminal chat runs as an agent identity (the agent package is there, and
    no other agent was named): -c and -r then mean its chats, else the session host's sessions."""
    from .extensions import first
    from .packages import activate

    if _coding(args).get("agent"):
        return False
    activate()
    return bool(getattr(args, "identity", None)) or first("identity") is not None


def _default(args):
    """harness with no command: the terminal chat with the agent on this computer, which
    starts a conversation with the first message; the first run asks for the model and key.
    What the chat is started with is on `start`: `prompt` (harness "first message": sent as
    the first message once it is open) and `chat` (-c, -r: the identity's chat to open)."""
    selecting = getattr(args, "model", None) is not None or getattr(args, "effort", None) is not None
    if selecting and _coding(args).get("agent"):
        raise UsageError("the terminal's --agent cannot be combined with --model or --effort; "
                         "use harness run --agent NAME --effort LEVEL for an explicit agent effort")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise UsageError("the terminal chat needs a terminal: harness -p \"question\" answers without one "
                         "(harness run \"task\" does a task, harness run rpc is driven by a program)")
    from . import tui

    resuming = bool(getattr(args, "continue_last", False)) or getattr(args, "session", None) is not None
    if resuming:
        # The chat goes on as it is: its model is changed in it (/model), not on the way in.
        _check_continuation_options(args)
    as_identity = _as_identity(args)
    continued = None
    if resuming and not as_identity:
        # Without an agent identity: a session of the session host, in its own id.
        if not getattr(args, "continue_last", False) and not args.session:
            raise UsageError("-r needs the session: harness -r SESSION (harness sessions ls lists them)")
        continued = _continued(args)
    start = _starter(args)
    start.warning = None
    start.prompt = getattr(args, "first_message", "") or None
    start.chat = None
    if continued is None and not _coding(args).get("agent") and not getattr(args, "model", None):
        start.warning = _ready_model(interactive=True, recovery=True)
        if start.warning is LEFT:
            return 0  # the first run was left: nothing was changed, and no chat opens
        if getattr(args, "effort", None) is not None and start.model_entry is None:
            start.warning = (start.warning or "") + " --effort was not applied; choose a model, then use /effort LEVEL."
    # After the model's readiness, which names a configuration that does not read.
    start.identity = _identity(args)
    if start.identity and resuming and continued is None:
        from .host import Host

        start.chat = _the_chat(Host.connect(log=_note), start.identity["id"], args, ask=True)
    try:
        if continued is not None:
            tui.chat(continued[1], host=continued[0], start=start)
        else:
            tui.chat(start=start)
    finally:
        if start.identity and start.identity.get("release"):
            start.identity["release"]()  # the identity's life ends with the chat
    return 0


# harness sessions' words that are about an identity's chats (the others: sessions of tasks).
CHAT_ACTIONS = ("list", "new", "rename", "pin", "unpin", "archive", "unarchive", "delete")
SESSIONS_HELP = """usage: harness sessions [COMMAND]

The chats of the agent identity (--identity ID; default: the current one):
  (none), list [-q TEXT] [--archived]    the chats: the main conversation, the pinned, the newest first
  new [TITLE]                            a new chat
  rename CHAT TITLE
  pin | unpin CHAT
  archive | unarchive CHAT
  delete CHAT [--yes]
harness -r CHAT opens one; harness -c the most recent.

The sessions of tasks in the session host (harness run, coding agents):
  ls [--all] [--kind K] [--project P]    list them
  show | stop | resume | cancel | attach SESSION
  send | steer | terminal SESSION TEXT
  diff | merge | discard SESSION
  approve SESSION REQUEST [--reject]     answer what one waits for
  import | discover | observe | reconnect | handoff | config | answer    (each: --help)"""


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
    for name in ("show", "stop", "resume", "cancel", "diff", "merge", "discard", "attach"):
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
    elif action == "resume":
        output({"run": host.resume_session(args.session).run})
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


def _instructions(args):
    """harness instructions [FOLDER]: what a conversation there reads at its start (instructions.py,
    with the settings' [instructions]), what was cut or left out and why."""
    from . import instructions
    from .paths import data
    from .settings import Settings

    folder = args.folder.expanduser().resolve()
    if not folder.is_dir():
        raise UsageError(f"{folder} is not a folder")
    loaded = instructions.load(folder, Settings(data()).get()["instructions"])
    if args.json:
        output(loaded.record())
        return 0
    print(f"A conversation in {folder} reads" + (f" (project root {loaded.root}):" if loaded.root else ":"))
    for item in loaded.files:
        print(f"  {item.label}  {len(item.text.encode('utf-8'))} bytes" + ("  (cut)" if item.cut else ""))
    if not loaded.files:
        print("  no instruction files")
    for label, why in loaded.skipped:
        print(f"  left out: {label}: {why}")
    for warning in loaded.warnings:
        print(f"  {warning}")
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
                        ["name", "entries", "version", "package", "directory"]))
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


def _agent_library(words) -> int:
    """harness library skills | tree [PATH] | memory | undo NAME: an identity's (the agent
    package's library_command, installed first when it is not)."""
    from .extensions import require
    from .packages import activate

    activate()
    return int(require("library_command", "commands", "agent")(list(words)) or 0)


def host_lines(host) -> list[str]:
    """How the session host runs (harness host, /host): its process, the identities it holds
    with their places, the chats and whether it starts at login."""
    import time as clock

    info = host.info()
    since = clock.strftime("%m-%d %H:%M", clock.localtime(float(info["started"]))) if info.get("started") else None
    lines = [f"host running{' since ' + since if since else ''} · pid {info.get('pid')} · {host.url} · "
             f"version {info.get('version')}"]
    try:
        identities = host.get("/api/agent/identities")
    except Exception:  # no agent package in it: its sessions only
        identities = None
    if identities:
        parts, chats, working = [], 0, 0
        for row in identities:
            try:
                life = host.get(f"/api/agent/life?identity={row['id']}")
                listed = host.get(f"/api/agent/chats?identity={row['id']}")["chats"]
            except Exception:
                life, listed = {}, []
            chats += len(listed)
            working += len(life.get("busy") or [])
            state = " paused" if life.get("paused") else ""
            parts.append(f"{row['id']} {row.get('name') or ''} ({len(life.get('places') or [])} places{state})")
        lines.append("  identities  " + " · ".join(parts))
        lines.append(f"  chats       {chats} · {working} working")
    else:
        lines.append(f"  sessions    {info.get('open', 0)} open · idle {info.get('idle_seconds', 0):.0f} s")
    try:
        from .host.login import status

        lines.append("  starts at login · " + ("yes" if status().get("on") else "no (harness host install)"))
    except Exception:
        pass
    return lines


def _host_command(words) -> int:
    """harness host: how the session host runs; harness host stop: end it (actions in progress
    end as cancelled, or unknown where that cannot be confirmed)."""
    from .host import Host

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # a console whose code page lacks ✓ or →
    host = Host.connect(start=False)
    if "stop" in words:
        if host is None:
            print("no session host runs")
            return 0
        working = 0
        try:
            for row in host.get("/api/agent/identities"):
                working += len(host.get(f"/api/agent/life?identity={row['id']}").get("busy") or [])
        except Exception:
            pass
        host.stop(force=True)
        if working:
            print(f"  {working} action{'s' if working != 1 else ''} in progress → cancelled")
        on = False
        try:
            from .host.login import status

            on = bool(status().get("on"))
        except Exception:
            pass
        print("✓ stopped" + (" · starts again at the next login" if on else ""))
        if on:
            print("  harness host uninstall · no longer start at login")
        return 0
    if host is None:
        print("no session host runs (harness starts it; harness host install starts it at login)")
        return 0
    if "--json" in words:
        output(host.info())
        return 0
    print("\n".join(host_lines(host)))
    return 0


def _share(args):
    """harness share: a library as a package (packages/libraries.py), sent where the user says
    after they saw what goes."""
    from .packages.libraries import share

    def confirm(preview):
        print(f"{preview['name']} {preview['version']} (library {preview['library_version'][:12]}) to "
              f"{preview['destination']}" + (f", creating a {preview['creates']} repository" if preview.get("creates")
                                             else ""), file=sys.stderr)
        for entry in preview["entries"]:
            print(f"  {entry['file']}  {entry['evidence']}, {entry['origin']}", file=sys.stderr)
        if not preview["memory"]:
            print("  (memory entries stay here: --with-memory sends them)", file=sys.stderr)
        for warning in preview["warnings"]:
            print(f"  note: {warning}", file=sys.stderr)
        if args.yes:
            return True
        if not sys.stdin.isatty():
            print("harness share --yes sends it", file=sys.stderr)
            return False
        return input("Send it? [y/N] ").strip().lower() in ("y", "yes")

    result = share(args.library, args.destination, name=args.name, version=args.package_version,
                   summary=args.summary or "", with_memory=args.with_memory, private=args.private, url=args.url or "",
                   confirm=confirm, log=_note)
    if args.json:
        output(result)
    elif not result.get("needs_consent"):
        print(f"Others install it with:\n  {result['install']}")
    return 1 if result.get("needs_consent") else 0


def _identity(args):
    """The agent identity the terminal chat runs as ({id, name, runtime}), from the agent
    package (installed first when --identity names one); None without the package. With
    several identities and none chosen it asks here, before the chat opens."""
    from .extensions import first, require

    name = getattr(args, "identity", None)
    if _coding(args).get("agent"):
        if name:
            raise UsageError("--identity is for the Harness agent, not --agent")
        return None
    hook = require("identity", "commands", "agent") if name else first("identity")
    if hook is None:
        return None
    return hook(name, _choose_identity)


def _choose_identity(found):
    """Ask which identity (a terminal; the chat has not opened yet)."""
    print("Several agent identities and none chosen (harness agent use ID remembers one):", file=sys.stderr)
    for index, name in enumerate(found, 1):
        print(f"  {index}. {name}", file=sys.stderr)
    while True:
        try:
            answer = _ask("Choose a number (q cancels): ")
        except EOFError:
            raise UsageError("no identity chosen") from None
        if answer.lower() == "q":
            raise UsageError("no identity chosen")
        if answer.isdigit() and 1 <= int(answer) <= len(found):
            return found[int(answer) - 1]
        if answer in found:
            return answer


# -- harness with no command: the chat, a first message, print mode ---------------------------

# What each command of the core is, in one line, in the order harness --help shows them.
DAILY = (
    ("setup", "the first run again: the model, an agent to bring over, the background"),
    ("model", "choose the model: an agent signed in here, a provider's key, a local model"),
    ("status", "version, model, identity, session host and what is connected"),
    ("doctor", "what is missing on this computer, each with its fix"),
    ("update", "update The Harness and the installed packages"),
    ("config", "settings: show | get KEY | set KEY VALUE | unset KEY | edit | path"),
    ("sessions", "the chats: list | rename | archive | delete; and the sessions of tasks"),
    ("logs", "the logs: harness logs [NAME] [-n N] [-f], harness logs list"),
    ("agent", "identities: new | use | list | rename | delete; say, queue, stop; share, backup"),
    ("usage", "what an identity spent: today, --range week | month"),
    ("calendar", "an identity's calendar: list | add | update | move | remove | restore"),
    ("library", "what it learned: skills | tree | memory | undo"),
)
CONNECT = (
    ("channels", "chat channels: kinds | add | groups | pair | test | remove"),
    ("mcp", "MCP servers: list | add | remove | test; serve: The Harness as one"),
    ("agents", "external agents (ACP): list | add | remove | test"),
    ("skills", "skills and their sources: list | sources | add | test | remove"),
    ("install", "install or update packages (and services, benches)"),
    ("list", "the installed packages; --available: the registry's"),
    ("remove", "remove installed packages"),
    ("host", "the session host: status | start | stop | restart | install | uninstall"),
    ("completion", "print a completion script: bash | zsh | fish"),
)
TASKS = (
    ("run", "do one task and end (harness run \"task\" [-p] [--json]); run rpc: JSON lines"),
    ("replay", "a run as it went, in the terminal"),
    ("instructions", "the instruction files a conversation in a folder reads"),
    ("share", "send what an agent learned (a library) as a package"),
)
# Commands of packages the core itself gives part of, or installs on first use: listed above.
LISTED = {name for group in (DAILY, CONNECT, TASKS) for name, _ in group}


def _command_help() -> dict:
    """{command: its one line} of the installed packages' commands: the line the package
    gives for it in its commands.toml (name = "one line"), else the package's name."""
    import tomllib

    from .paths import packages

    found = {}
    for package in packages():
        lines = {}
        try:
            with (Path(package.path) / "commands.toml").open("rb") as handle:
                lines = tomllib.load(handle)
        except (OSError, ValueError):
            pass
        for name in package.provides.get("commands", ()):
            found.setdefault(name, str(lines.get(name) or f"a command of the package {package.name}"))
    return found


def help_text() -> str:
    """harness --help: short, the daily commands first, then connecting things, tasks, and
    what the installed packages add, each with a line of its own."""
    def rows(group):
        return [f"  {name:<14}{text}" for name, text in group]

    more = sorted((name, text) for name, text in _command_help().items() if name not in LISTED)
    lines = ["usage: harness [\"first message\"]     the chat with the agent on this computer",
             "       harness -p \"question\"        answer and exit; reads what is piped in",
             "       harness COMMAND ...          harness COMMAND --help says more",
             "",
             "  -p, --print                 print the answer and exit (--output-format text | json | stream-json)",
             "  -c, --continue              go on with the most recent chat",
             "  -r, --resume [CHAT]         go on with a chat (its id or title); alone: choose one",
             "      --model MODEL           the model for this chat (an entry of the model list)",
             "      --identity ID           the agent identity (default: the current one)",
             "  -v, --version               the version",
             "", "Every day", *rows(DAILY), "", "Connect and extend", *rows(CONNECT), "", "Tasks", *rows(TASKS)]
    if more:
        lines += ["", "From installed packages", *rows(more)]
    lines += ["", "In the chat, /help lists its commands and ? its keys."]
    return "\n".join(lines)


def known_commands() -> set:
    return {*core_commands(), *FIRST_USE, *package_commands(), "host", "setup", "model", "update", "mcp", "config",
            "status", "logs", "completion", "chat", "rpc", "help"}


# The options of harness itself that take a value (so the word after one is not a command).
VALUE_OPTIONS = {"--model", "--effort", "--identity", "--workspace", "--space", "--agent", "--folder", "--isolation",
                 "--share-mcp-tool", "--physical", "--allow-app", "--deny-app", "--ask-app", "--window-details",
                 "--think", "--think-interval", "--output-format", "--session"}


def first_word(words) -> int | None:
    """Where the first word that is no option (and no option's value) is, or None."""
    index = 0
    while index < len(words):
        word = words[index]
        if word == "--":
            return index + 1 if index + 1 < len(words) else None
        if not word.startswith("-") or word == "-":
            return index
        if word in VALUE_OPTIONS:
            index += 1
        elif word in ("-r", "--resume") and index + 2 < len(words) and not words[index + 1].startswith("-"):
            index += 1  # -r CHAT "message": the chat, then the message
        index += 1
    return None


def mistyped(word: str) -> str | None:
    """The command `word` was most likely meant to be, when it is one word close to one."""
    import difflib

    if not re.fullmatch(r"[A-Za-z][A-Za-z-]*", word):
        return None
    near = difflib.get_close_matches(word.lower(), sorted(known_commands()), n=1, cutoff=0.75)
    return near[0] if near else None


def chat_parser():
    """harness's own options when no command is given: the chat, or with -p one answer."""
    root = argparse.ArgumentParser(prog="harness", add_help=False)
    root.add_argument("-h", "--help", action="store_true")
    root.add_argument("-v", "--version", action="version", version=f"harness {__version__}")
    root.add_argument("-p", "--print", dest="print_mode", action="store_true")
    root.add_argument("--output-format", choices=("text", "json", "stream-json"), default="text")
    root.add_argument("-c", "--continue", dest="continue_last", action="store_true")
    root.add_argument("-r", "--resume", dest="session", nargs="?", const="", metavar="CHAT")
    root.add_argument("--model")
    root.add_argument("--effort")
    run_flags(root)
    _coding_arguments(root)
    root.add_argument("--identity")
    root.add_argument("--managed-workspace", action="store_true")
    root.add_argument("prompt", nargs="*")
    return root


def _chat(words) -> int:
    """harness, harness "first message", harness -p "question": no command was given."""
    parsed = chat_parser()
    args = parsed.parse_args(words)
    args.command = None
    if args.help:
        print(help_text())
        return 0
    prompt = " ".join(args.prompt).strip()
    if args.continue_last and args.session is not None:
        raise UsageError("give -c (the most recent chat) or -r CHAT, not both")
    if args.print_mode:
        return _print_mode(args, prompt)
    if args.output_format != "text":
        raise UsageError("--output-format goes with -p")
    args.first_message = prompt
    return _default(args)


def _piped() -> str:
    """What was piped into this command ("" when its input is a terminal)."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode()
    except (OSError, ValueError):
        return ""
    return data.decode("utf-8", "replace").strip()


def _the_chat(host, identity: str, args, *, ask: bool) -> str | None:
    """The chat -c or -r names (None: neither was given): the most recent one, the one with
    that id or title, or with -r alone the one chosen from the list (`ask`: in a terminal)."""
    from urllib.parse import quote

    from .problems import Problem

    if not args.continue_last and args.session is None:
        return None
    rows = host.get(f"/api/agent/chats?identity={quote(identity)}")["chats"]
    if args.continue_last:
        return max(rows, key=lambda row: row["updated"])["chat"]
    wanted = args.session.strip()
    if not wanted:
        if not ask:
            raise UsageError("-r needs the chat here: harness -r CHAT (harness sessions lists them)")
        print("Which chat?", file=sys.stderr)
        for index, row in enumerate(rows, 1):
            print(f"  {index}. {row['title']}  ({row['chat']})", file=sys.stderr)
        while True:
            try:
                answer = _ask("Choose a number (q cancels): ")
            except EOFError:
                raise UsageError("no chat chosen") from None
            if answer.lower() == "q":
                raise UsageError("no chat chosen")
            if answer.isdigit() and 1 <= int(answer) <= len(rows):
                return rows[int(answer) - 1]["chat"]
    exact = [row for row in rows if wanted in (row["chat"], row["title"])]
    near = exact or [row for row in rows if wanted.casefold() in str(row["title"]).casefold()]
    if len(near) == 1:
        return near[0]["chat"]
    raise Problem(f"no chat called {wanted!r}" if not near else f"{len(near)} chats are called like {wanted!r}",
                  "harness sessions lists the chats with their ids", code="no_chat")


def _print_mode(args, prompt: str) -> int:
    """harness -p "question": the question (with what was piped in) is answered and the
    command ends: by the agent identity in a chat of its own, -c in its most recent chat, -r
    in the one named; without the agent package, as harness run "task" -p does it."""
    piped = _piped()
    text = "\n\n".join(part for part in (prompt, piped) if part)
    if not text:
        raise UsageError("harness -p needs a question: harness -p \"...\", or pipe one in")
    from .extensions import first
    from .packages import activate

    activate()
    if _coding(args).get("agent") or getattr(args, "workspace", None) or first("identity") is None:
        if args.output_format == "stream-json":
            words = ["run", text, "--json"]
        else:
            words = ["run", text, "-p"]
        for name in ("model", "effort", "workspace", "agent", "folder"):
            if getattr(args, name, None):
                words += [f"--{name}", str(getattr(args, name))]
        return _main(words)
    return _answer_as_identity(args, text)


def _answer_as_identity(args, text: str) -> int:
    import time as clock
    from urllib.parse import quote

    from .host import Host

    host = Host.connect(log=_note)
    rows = host.get("/api/agent/identities")
    wanted = getattr(args, "identity", None) or next((row["id"] for row in rows if row.get("current")), None) \
        or (rows[0]["id"] if len(rows) == 1 else None)
    if wanted is None:
        raise UsageError("several agent identities and none chosen: harness -p --identity ID, or harness agent use ID")
    chat = _the_chat(host, wanted, args, ask=False)
    if chat is None:
        chat = host.post("/api/agent/new_chat", {"identity": wanted, "title": " ".join(text.split())[:60]})["chat"]
    if getattr(args, "model", None):
        host.post("/api/agent/chats", {"identity": wanted, "action": "model", "chat": chat, "model": args.model})
    query = f"identity={quote(wanted)}&chat={quote(chat)}"
    before = host.get(f"/api/agent/chat?{query}")["records"]
    after = before[-1]["seq"] if before else 0
    job = host.post("/api/agent/say", {"identity": wanted, "chat": chat, "text": text})["queued"]
    stream = args.output_format == "stream-json"
    answer, problem, started = None, None, False
    try:
        while True:
            found = host.get(f"/api/agent/chat?{query}&after={after}")
            waiting = host.get(f"/api/agent/queue?{query}")
            over = (waiting["running"] or {}).get("id") != job and job not in [row["id"] for row in waiting["queued"]]
            if over:  # what the turn wrote last is read once more after it ended
                found = host.get(f"/api/agent/chat?{query}&after={after}")
            for record in found["records"]:
                after = record["seq"]
                if record["event"] == "turn_started":
                    started = record.get("job") == job
                if not started:
                    continue
                if stream:
                    print(json.dumps(record, ensure_ascii=False), flush=True)
                if record["event"] == "reply":
                    answer = record.get("text")
                elif record["event"] in ("error", "asleep", "interrupted", "spending_limit") and record.get("job", job) == job:
                    problem = record.get("error") or record.get("reason") or record["event"]
            if over:
                break
            clock.sleep(0.25)
    except KeyboardInterrupt:
        host.post("/api/agent/stop", {"identity": wanted, "chat": chat})
        return 130
    failed = answer is None
    if args.output_format == "text":
        if answer is not None:
            print(answer)
        if failed:
            print(f"harness: {problem or 'it ended without an answer'}", file=sys.stderr)
    else:
        result = {"type": "result", "is_error": failed, "result": answer if answer is not None else (problem or ""),
                  "session_id": chat, "identity": wanted}
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if failed else 0


# -- harness status, doctor, config, logs, host, completion -----------------------------------

def _host_now():
    """The session host when one runs (never started for a look), else None."""
    from .host import Host

    try:
        return Host.connect(start=False)
    except (OSError, ValueError, RuntimeError):
        return None


def status_report() -> dict:
    """What harness status shows: the version, the model, the identities, the session host
    and what is connected. Nothing is started for it."""
    from urllib.parse import quote

    from . import onboarding, providers
    from .host import connectors
    from .paths import data

    model = providers.ready(data())
    chosen = onboarding.chosen(data())
    report = {"version": __version__, "python": sys.version.split()[0], "data": str(data()),
              "model": {"ready": bool(model["ready"]), "provider": model.get("provider"), "model": model.get("model"),
                        "name": chosen["name"] if chosen else None, "detail": model.get("detail")},
              "host": None, "identities": [], "channels": [], "mcp": [], "agents": [], "problems": {}}
    host = _host_now()
    if host is not None:
        info = host.info()
        report["host"] = {"url": host.url, "pid": info.get("pid"), "version": info.get("version"),
                          "started": info.get("started"), "open": info.get("open", 0)}
        report["problems"] = dict(info.get("problems") or {})
        try:
            for row in host.get("/api/agent/identities"):
                life = host.get(f"/api/agent/life?identity={quote(row['id'])}")
                report["identities"].append({"id": row["id"], "name": row.get("name"), "current": bool(row.get("current")),
                                             "paused": life.get("paused"), "asleep": life.get("asleep"),
                                             "working": len(life.get("busy") or []),
                                             "spent_today": life.get("spent_today"), "budget": life.get("budget")})
                for account in host.get(f"/api/agent/channels?identity={quote(row['id'])}")["channels"]:
                    report["channels"].append({"identity": row["id"], "account": account["account"],
                                               "kind": account["kind"], "state": account["state"]})
        except (OSError, ValueError, RuntimeError):
            pass  # a host without the agent package: its sessions only
    else:
        from .extensions import first
        from .packages import activate

        try:
            activate()
            agent = first("Agent")
            report["identities"] = [{"id": row["id"], "name": row.get("name"), "current": bool(row.get("current"))}
                                    for row in (agent.list() if agent is not None else [])]
        except (OSError, ValueError, RuntimeError):
            pass
    try:
        report["mcp"] = [{"name": row["name"], "enabled": row["enabled"]} for row in connectors.mcp_servers()]
        report["agents"] = [{"id": row["id"], "state": row["state"], "signed_in": row["signed_in"]}
                            for row in connectors.agents() if row["state"] == "connected"]
    except (OSError, ValueError, RuntimeError):
        pass
    try:
        from .host.login import status as login_status

        report["starts_at_login"] = bool(login_status().get("on"))
    except Exception:  # noqa: BLE001 - a system that cannot be asked: not said
        report["starts_at_login"] = None
    return report


def status_lines(report: dict) -> list[str]:
    import time as clock

    model = report["model"]
    lines = [f"The Harness {report['version']} · Python {report['python']}"]
    if model["ready"]:
        lines.append(f"  model      {model['name'] or model['provider']} · {model['model']}")
    else:
        lines.append(f"  model      not set up ({model['detail']}): harness setup")
    current = [row for row in report["identities"] if row.get("current")] or report["identities"][:1]
    for row in report["identities"]:
        state = "paused" if row.get("paused") else "asleep until 0:00" if row.get("asleep") else \
            f"{row['working']} working" if row.get("working") else "" if "working" not in row else "idle"
        spent = f" · today ${row['spent_today']:.2f} of ${row['budget']:.2f}" if row.get("budget") is not None else ""
        mark = "*" if row in current and len(report["identities"]) > 1 else " "
        lines.append(f"  identity  {mark}{row['id']} ({row.get('name') or row['id']})"
                     + (f" · {state}" if state else "") + spent)
    if not report["identities"]:
        lines.append("  identity   none yet: harness makes one on its first start")
    host = report["host"]
    if host:
        since = clock.strftime("%m-%d %H:%M", clock.localtime(float(host["started"]))) if host.get("started") else "?"
        lines.append(f"  host       running since {since} · pid {host['pid']} · {host['url']}")
    else:
        lines.append("  host       not running (harness starts it; harness host start)")
    if report.get("starts_at_login") is not None:
        lines.append("             starts at login: " + ("yes" if report["starts_at_login"] else
                                                         "no (harness host install)"))
    connected = []
    if report["channels"]:
        connected.append("channels " + ", ".join(f"{row['account']} ({row['state'].replace('_', ' ')})"
                                                 for row in report["channels"]))
    if report["mcp"]:
        connected.append("MCP " + ", ".join(row["name"] + ("" if row["enabled"] else " (off)") for row in report["mcp"]))
    if report["agents"]:
        connected.append("agents " + ", ".join(row["id"].removeprefix("acp:") for row in report["agents"]))
    lines.append("  connected  " + (" · ".join(connected) if connected else
                                    "nothing yet (harness channels, harness mcp, harness agents)"))
    for problem in report["problems"].values():
        lines.append(f"  problem    {problem}")
    return lines


def _status(words) -> int:
    """harness status: one screen of where things stand (hermes status). The services of a
    deploy (harness status NAME, --deploy) are the local-models package's status."""
    parser = argparse.ArgumentParser(prog="harness status", description="Version, model, identity, session host and "
                                     "what is connected. (harness status --deploy NAME, or with service names: the "
                                     "services of a deploy, from the local-models package.)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(words)
    report = status_report()
    output(report) if args.json else print("\n".join(status_lines(report)))
    return 0


def doctor_checks(host: bool = True) -> list[dict]:
    """What a person needs to know of this computer, each {name, ok, detail, fix}: Python,
    the model with its key or sign-in, and with `host` whether the session host can start
    (it is started when none runs, as harness would start it), the packages that were left
    out, and which harness a terminal runs."""
    import shutil

    from . import onboarding, providers
    from .paths import data
    from .problems import explain

    checks = []

    def check(name, ok, detail, fix=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fix": "" if ok else fix})

    check("python", sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}",
          "The Harness needs Python 3.11 or newer")
    try:
        model = providers.ready(data())
        chosen = onboarding.chosen(data())
        name = (chosen or {}).get("name") or model.get("provider")
        if model.get("selection_error"):
            check("model", False, model["detail"], "harness model (or edit the model list it names)")
        elif chosen is None or not model["ready"]:
            check("model", False, f"no model is set up ({model.get('detail') or 'none chosen'})", "harness setup")
        elif providers.is_agent(chosen["provider"]):
            known = providers.AGENTS.get(chosen["provider"].removeprefix("acp:"))
            path = shutil.which(known.executable) if known else None
            signed = onboarding.signed_in(path, known) if path else None
            if known is not None and path is None:
                check("model", False, f"{name} is the model, and its command is not on this computer", known.install)
            elif signed is False:
                check("model", False, f"{name} is the model, and it is not signed in", known.sign_in)
            else:
                check("model", True, f"{name} · {chosen['model']} (under {known.plan if known else 'its own sign-in'})")
        elif not onboarding.kept_ready(data()):
            check("model", False, f"{name} · {chosen['model']}: its key is only in this terminal's environment "
                  f"({model.get('key_env')}), which a session host started at login does not see",
                  "harness setup keeps it with the credentials")
        else:
            check("model", True, f"{name} · {chosen['model']} (key kept with the credentials)"
                  if model.get("key_env") else f"{name} · {chosen['model']}")
    except (ValueError, OSError) as error:
        check("model", False, str(error), "harness setup")
    if not host:
        return checks
    from .host import Host

    try:
        running = _host_now()
        found = running or Host.connect(log=lambda message: None)
        info = found.info()
        check("session host", True, f"{'running' if running else 'started'} · pid {info.get('pid')} · {found.url}")
        left_out = dict(info.get("problems") or {})
    except Exception as error:  # noqa: BLE001 - whatever stopped it is the finding
        problem = explain(error)
        check("session host", False, problem.reason + (f" (log: {problem.log})" if problem.log else ""),
              problem.fix or "harness host start shows why")
        left_out = {}
    from .host.workspaces import package_problems

    try:
        left_out = {**package_problems(), **left_out}
    except (OSError, ValueError, RuntimeError):
        pass
    for name, why in left_out.items():
        reason, _, fix = str(why).rpartition(": ")
        check(f"package {name}", False, reason or str(why), fix if reason else f"harness install --update {name}")
    if not left_out:
        check("packages", True, "every installed package loaded")
    try:
        from harness_app import shell  # the app package, where it is installed

        found = shell.command(new=False)
    except (ImportError, AttributeError):
        found = None
    except Exception:  # noqa: BLE001 - asking another install may fail in ways of its own
        found = None
    if found is not None:
        if found.get("mine") or not found.get("path"):
            check("command", True, f"harness in this terminal is this install ({found.get('path') or 'python -m harness'})")
        else:
            check("command", False, f"harness in this terminal is another install: {found.get('path')}"
                  + (f" ({found['version']})" if found.get("version") else ""), found.get("fix") or
                  "put this install first on PATH, or remove the other one")
    return checks


def doctor_lines(checks) -> list[str]:
    lines = []
    for row in checks:
        lines.append(f"{'✓' if row['ok'] else '✗'} {row['name']:<14} {row['detail']}")
        if row["fix"]:
            lines.append(f"  {'':<14} → {row['fix']}")
    missing = sum(1 for row in checks if not row["ok"])
    lines.append("")
    lines.append("Nothing is missing." if not missing else
                 f"{missing} thing{'s' if missing != 1 else ''} to fix, each with what to do after →.")
    return lines


CONFIG_COMMANDS = ("show", "get", "set", "unset", "edit", "path")


def _value_of(kind: str, text: str):
    """A setting's value from what was typed, by its kind."""
    if kind == "bool":
        if text.lower() in ("true", "on", "yes", "1"):
            return True
        if text.lower() in ("false", "off", "no", "0"):
            return False
        raise UsageError(f"a switch is true or false, not {text!r}")
    if kind in ("int", "float"):
        try:
            return int(text) if kind == "int" else float(text)
        except ValueError:
            raise UsageError(f"a number is expected, not {text!r}") from None
    if kind == "rules":
        try:
            return json.loads(text)
        except ValueError:
            raise UsageError("a list of rules is given as JSON: '[{\"level\": ...}]'") from None
    return text


def _config(words) -> int:
    """harness config show | get | set | unset | edit | path: the settings (hermes config).
    A setting is named section.key; --identity ID reads and writes an agent identity's own
    value of the settings an identity may have one of. A provider's key is set by its
    variable's name (harness config set OPENROUTER_API_KEY ...) and kept with the credentials."""
    from . import providers, settings as settings_module
    from .paths import data
    from .problems import Problem
    from .settings import SCHEMA, Credentials, Settings

    parser = argparse.ArgumentParser(prog="harness config", description="The settings: show them, get, set or unset "
                                     "one (named section.key), edit the file, or print its path")
    commands = parser.add_subparsers(dest="action")
    show = commands.add_parser("show", help="the settings and their values (those changed are marked *)")
    show.add_argument("section", nargs="?", help="only this section")
    get = commands.add_parser("get", help="one setting's value")
    get.add_argument("key")
    change = commands.add_parser("set", help="set one: harness config set approvals.ask programs")
    change.add_argument("key")
    change.add_argument("value")
    unset = commands.add_parser("unset", help="back to its default (for an identity: to the global value)")
    unset.add_argument("key")
    commands.add_parser("edit", help="open the configuration file in your editor ($VISUAL, $EDITOR)")
    commands.add_parser("path", help="print where the configuration file is")
    for command in (show, get, change, unset):
        command.add_argument("--identity", help="an agent identity's own value (the settings an identity may have)")
        command.add_argument("--json", action="store_true")
    args = parser.parse_args(words or ["show"])
    store = Settings(data())
    if args.action == "path":
        print(store.file)
        return 0
    if args.action == "edit":
        import shlex
        import subprocess

        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
        if not store.file.exists():
            settings_module.write(data(), settings_module.read(data()))
        return subprocess.call([*shlex.split(editor, posix=os.name != "nt"), str(store.file)])

    def own(identity):
        """An identity's values over the session host: {values, own, schema}."""
        from urllib.parse import quote

        from .host import Host

        return Host.connect(log=_note), quote(identity)

    key = getattr(args, "key", None)
    secret = bool(key) and key in providers.KEY_NAMES
    if args.action == "show":
        values = store.get()
        mine = {}
        if args.identity:
            host, name = own(args.identity)
            found = host.get(f"/api/agent/settings?identity={name}")
            mine = found["own"]
            for full, value in found["values"].items():
                section, _, name_ = full.partition(".")
                values.setdefault(section, {})[name_] = value
        saved = settings_module.read(data())
        rows = []
        for section, keys in SCHEMA.items():
            if args.section and section != args.section:
                continue
            for name_, spec in keys.items():
                if args.identity and spec.scope != "identity":
                    continue
                full = f"{section}.{name_}"
                changed = full in mine if args.identity else name_ in (saved.get(section) or {})
                rows.append({"setting": full, "value": values.get(section, {}).get(name_, spec.default),
                             "changed": changed, "scope": spec.scope, "kind": spec.kind})
        if args.section and not rows:
            raise Problem(f"no settings section {args.section}", "harness config show lists them", code="no_setting")
        if args.json:
            output(rows)
            return 0
        width = max(len(row["setting"]) for row in rows)
        print(f"# {store.file}" + (f" · identity {args.identity}" if args.identity else ""))
        section = None
        for row in rows:
            if row["setting"].split(".")[0] != section:
                section = row["setting"].split(".")[0]
                print(f"[{section}]")
            value = json.dumps(row["value"], ensure_ascii=False)
            print(f"{'*' if row['changed'] else ' '} {row['setting']:<{width}}  {value}"
                  + ("  (per identity: --identity ID)" if row["scope"] == "identity" and not args.identity else ""))
        print("* changed from its default" + (" for this identity" if args.identity else ""))
        return 0
    if secret:
        credentials = Credentials(data(), [key])
        if args.action == "get":
            credentials.load()
            value = os.environ.get(key) or ""
            masked = (value[:4] + "..." + value[-4:]) if len(value) > 12 else ("set" if value else "")
            output({"key": key, "set": bool(value)}) if args.json else print(masked or "(not set)")
            return 0 if value else 1
        if args.action == "set":
            credentials.save(args.value, key)
            print(f"{key} is kept with the credentials ({store.file})")
        else:
            credentials.keep(key, None)
            print(f"{key} is no longer kept")
        return 0
    try:
        section, name_ = settings_module.split(key)
    except ValueError as error:
        raise Problem(str(error), "harness config show lists the settings", code="no_setting") from None
    spec = SCHEMA[section][name_]
    if args.identity:
        host, name = own(args.identity)
        if args.action == "get":
            found = host.get(f"/api/agent/settings?identity={name}")
            value = found["values"].get(key, store.get()[section][name_])
        else:
            value = None if args.action == "unset" else _value_of(spec.kind, args.value)
            found = host.post("/api/agent/settings", {"identity": args.identity, "key": key, "value": value})
            value = found["values"].get(key)
    elif args.action == "get":
        value = store.get()[section][name_]
    elif args.action == "set":
        try:
            value = store.update({section: {name_: _value_of(spec.kind, args.value)}})[section][name_]
        except ValueError as error:
            fix = f"harness config set {key} {' | '.join(map(str, spec.bounds))}" if spec.kind == "choice" else \
                f"{key}: {spec.about}"
            raise Problem(str(error), fix, code="setting_value") from None
    else:
        value = store.reset(section, name_)[section][name_]
    if args.json:
        output({"setting": key, "value": value})
    elif args.action == "get":
        print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    else:
        where = f" for {args.identity}" if args.identity else ""
        when = {"next_conversation": "  (holds from the next conversation)",
                "app_start": "  (holds when the app starts next)"}.get(spec.applies, "")
        print(f"{key} = {json.dumps(value, ensure_ascii=False)}{where}{when}")
    return 0


def _logs(words) -> int:
    """harness logs [NAME] [-n N] [-f], harness logs list: the logs in the data folder
    (hermes logs). NAME: host (default), or another log there by its name."""
    import time as clock

    from .paths import data
    from .problems import Problem

    parser = argparse.ArgumentParser(prog="harness logs", description="Show a log of The Harness (default: the "
                                     "session host's), or list the logs there are")
    parser.add_argument("name", nargs="?", default="host", help="which log: host (default), another by its name, or "
                        "list")
    parser.add_argument("-n", "--lines", type=int, default=50, help="how many lines (default 50)")
    parser.add_argument("-f", "--follow", action="store_true", help="go on showing new lines until Ctrl+C")
    args = parser.parse_args(words)
    folder = data() / "logs"
    files = sorted(folder.glob("*.log")) if folder.is_dir() else []
    if args.name == "list":
        if not files:
            print(f"no logs yet in {folder}")
        for path in files:
            stamp = clock.strftime("%m-%d %H:%M", clock.localtime(path.stat().st_mtime))
            print(f"  {path.stem:<24} {path.stat().st_size / 1024:>9.1f} KB  {stamp}")
        return 0
    path = folder / f"{args.name.removesuffix('.log')}.log"
    if not path.is_file():
        raise Problem(f"no log called {args.name} in {folder}",
                      "harness logs list shows the ones there are" if files else
                      "none was written yet: the session host writes host.log when it starts", code="no_log")
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - max(1, args.lines) * 400))
        tail = stream.read().decode("utf-8", "replace").splitlines()[-max(1, args.lines):]
        print("\n".join(tail), flush=True)
        if not args.follow:
            return 0
        try:
            while True:
                piece = stream.read()
                if piece:
                    sys.stdout.write(piece.decode("utf-8", "replace"))
                    sys.stdout.flush()
                else:
                    clock.sleep(0.5)
        except KeyboardInterrupt:
            return 0


HOST_HELP = """usage: harness host [COMMAND]

The session host: the one background process that keeps the agent identities alive and
serves the app, the terminal chat and the API.

  (none), status   how it runs: since when, the identities it holds, whether it starts at login
  start            start it when it does not run
  stop             end it (actions in progress end as cancelled)
  restart          stop, then start
  install          start it at login (a scheduled task, a LaunchAgent or a systemd user service)
  uninstall        no longer start it at login
  serve            run it in this terminal (what the others start)

  --json           with status: the facts as JSON"""


def _host(words) -> int:
    """harness host [status | start | stop | restart]: in the forms of hermes gateway."""
    from .host import Host

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # a console whose code page lacks ✓ or →
    rest = [word for word in words if word != "--json"]
    if rest[:1] in (["-h"], ["--help"], ["help"]):
        print(HOST_HELP)
        return 0
    action = rest[0] if rest else "status"
    if action not in ("status", "start", "stop", "restart") or len(rest) > 1:
        near = mistyped_among(action, ("status", "start", "stop", "restart", "install", "uninstall", "serve"))
        print(f"harness host: no command {' '.join(rest)!r}." + (f" Did you mean harness host {near}?" if near else "")
              + " harness host --help lists them.", file=sys.stderr)
        return 2
    if action in ("stop", "restart"):
        status = _host_command(["stop"])
        if action == "stop":
            return status
    if action in ("start", "restart"):
        running = _host_now() if action == "start" else None
        host = running or Host.connect(log=_note)
        print(("already running · " if running else "✓ started · ") + f"pid {host.info().get('pid')} · {host.url}")
        return 0
    return _host_command(["--json"] if "--json" in words else [])


def mistyped_among(word: str, names) -> str | None:
    import difflib

    near = difflib.get_close_matches(str(word).lower(), list(names), n=1, cutoff=0.6)
    return near[0] if near else None


def _completion(words) -> int:
    """harness completion bash | zsh | fish: a completion script for the commands and their
    first words, printed for the shell's profile (hermes completion)."""
    parser = argparse.ArgumentParser(prog="harness completion", description="Print a shell completion script: "
                                     "harness completion bash >> ~/.bashrc")
    parser.add_argument("shell", choices=("bash", "zsh", "fish"))
    args = parser.parse_args(words)
    second = {"config": CONFIG_COMMANDS, "host": ("status", "start", "stop", "restart", "install", "uninstall"),
              "mcp": (*MCP_COMMANDS, "serve"), "agents": ("list", "add", "get", "remove", "test", "update"),
              "channels": ("list", "kinds", "add", "set", "groups", "owner-code", "pair", "test", "remove"),
              "skills": ("list", "sources", "add", "test", "update", "remove"),
              "calendar": ("list", "add", "update", "move", "remove", "restore", "pause"),
              "sessions": ("list", "rename", "archive", "unarchive", "pin", "unpin", "delete", "ls", "show", "stop",
                           "resume", "attach"),
              "agent": ("new", "use", "list", "about", "rename", "delete", "say", "chats", "queue", "stop", "memory",
                        "share", "adopt", "backup", "restore", "retire", "import"),
              "library": ("ls", "show", "skills", "tree", "memory", "undo"), "logs": ("list", "host"),
              "usage": ("--range", "--week", "--raise-today")}
    first = sorted(known_commands() - {"chat", "rpc", "help"})
    if args.shell == "bash":
        cases = "\n".join(f"        {name}) words=\"{' '.join(found)}\" ;;" for name, found in sorted(second.items()))
        print(f"""_harness() {{
    local cur="${{COMP_WORDS[COMP_CWORD]}}" words=""
    if [ "$COMP_CWORD" -eq 1 ]; then
        words="{' '.join(first)} --help --version -p -c -r --model"
    else
        case "${{COMP_WORDS[1]}}" in
{cases}
        esac
    fi
    COMPREPLY=( $(compgen -W "$words" -- "$cur") )
}}
complete -o default -F _harness harness""")
    elif args.shell == "zsh":
        cases = "\n".join(f"            {name}) compadd {' '.join(found)} ;;" for name, found in sorted(second.items()))
        print(f"""#compdef harness
_harness() {{
    if (( CURRENT == 2 )); then
        compadd {' '.join(first)} --help --version -p -c -r --model
    else
        case "$words[2]" in
{cases}
            *) _files ;;
        esac
    fi
}}
compdef _harness harness""")
    else:
        print("complete -c harness -f")
        print(f"complete -c harness -n __fish_use_subcommand -a '{' '.join(first)}'")
        for name, found in sorted(second.items()):
            print(f"complete -c harness -n '__fish_seen_subcommand_from {name}' -a '{' '.join(found)}'")
    return 0


def main(argv=None):
    """Catch setup and activation failures as well as command-dispatch failures."""
    return _guarded(lambda: _main(argv))


def _main(argv=None):
    words = list(sys.argv[1:] if argv is None else argv)
    if words[:1] == ["rpc"]:
        words.insert(0, "run")
    if words[:1] == ["chat"]:
        words.pop(0)
    if words[:1] == ["help"]:
        words = ["--help"] if len(words) == 1 else [*words[1:], "--help"]
    # A word that is no command is the chat's first message; one close to a command is a slip.
    at = first_word(words)
    if at is None or words[at] not in known_commands():
        if at is not None and at == len(words) - 1:
            near = mistyped(words[at])
            if near:
                print(f"harness: no command {words[at]!r}. Did you mean harness {near}?", file=sys.stderr)
                return 2
        return _guarded(lambda: _chat(words))
    if at:
        raise UsageError(f"put options after the command: harness {words[at]} {' '.join(words[:at])} ...")
    if words[:2] == ["host", "serve"]:
        from .host.server import main as serve

        return _guarded(lambda: serve(words[2:]))
    if words[:2] in (["host", "install"], ["host", "uninstall"]):
        from .host.login import main as login

        return _guarded(lambda: login(words[1:]))
    if words[:1] == ["host"]:
        return _guarded(lambda: _host(words[1:]))
    if words[:1] in (["setup"], ["model"]) and len(words) <= 2:
        return _guarded(lambda: _setup(words))
    if words[:1] == ["status"]:
        if all(word in ("--json", "-h", "--help") for word in words[1:]):
            return _guarded(lambda: _status(words[1:]))
        if "status" not in package_commands():
            raise UsageError("harness status takes --json; the services of a deploy (harness status NAME, "
                             "--deploy) need the local-models package: harness install local-models")
        return _guarded(lambda: _package_command("status", words[1:]))
    if words[:1] == ["config"]:
        if len(words) == 1 or words[1] in CONFIG_COMMANDS or words[1] in ("-h", "--help"):
            return _guarded(lambda: _config(words[1:]))
        if "config" in package_commands():
            return _guarded(lambda: _package_command("config", words[1:]))  # the eval package's: an experiment
        near = mistyped_among(words[1], CONFIG_COMMANDS)
        print(f"harness config: no command {words[1]!r}." + (f" Did you mean harness config {near}?" if near else "")
              + " It takes show, get, set, unset, edit and path.", file=sys.stderr)
        return 2
    if words[:1] == ["logs"]:
        return _guarded(lambda: _logs(words[1:]))
    if words[:1] == ["completion"]:
        return _guarded(lambda: _completion(words[1:]))
    if words[:1] == ["sessions"]:
        if words[1:2] in (["-h"], ["--help"]):
            print(SESSIONS_HELP)
            return 0
        if len(words) == 1 or words[1] in CHAT_ACTIONS or words[1].startswith("-"):
            # The chats of the agent identity (the agent package's), as harness agent chats.
            rest = words[1:] if len(words) > 1 and words[1] in CHAT_ACTIONS else ["list", *words[1:]]
            return _guarded(lambda: _package_command("agent", ["chats", *rest]))
    if words[:1] == ["mcp"] and len(words) > 1 and words[1] in MCP_COMMANDS:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
        return _guarded(lambda: _mcp(words[1:]))
    if words[:2] == ["mcp", "serve"]:
        words.pop(1)  # harness mcp serve [--http]: the mcp-server package's, as harness mcp alone is
    if words[:1] == ["update"]:
        from .update import main as update

        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")  # a console whose code page lacks ✓ or →
        return _guarded(lambda: update(words[1:]))
    if words[:1] == ["library"] and len(words) > 1 and words[1] in AGENT_LIBRARY:
        return _guarded(lambda: _agent_library(words[1:]))
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

        try:
            activate()
        except (ValueError, OSError, RuntimeError, ImportError) as error:
            if args.command == "doctor" and args.json:
                output({"schema_version": 1, "ok": False, "problems": [str(error)], "error": str(error)})
                return 1
            raise
    commands = {"install": _install, "list": _list, "remove": _remove, "library": _library_command, "sessions": _sessions,
                "replay": _replay, "instructions": _instructions, "share": _share}
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
