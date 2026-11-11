"""The eval package's command-line pieces: an experiment or script named on the command
line, the options of a task's own (--physical and the app rules, --window-details, --think,
--workspace) as experiment overrides."""

import argparse
import json
from pathlib import Path


def config_file(text: str) -> Path:
    """An experiment or agent file: a path, or a name of configs/experiments/ (then of
    configs/ablations/, of the core or a package), e.g. dev."""
    from harness.sdk import find

    path = Path(text)
    if path.exists() or path.suffix == ".toml" or "/" in text or "\\" in text:
        return path
    for folder in ("experiments", "ablations"):
        found = find(f"configs/{folder}/{text}.toml")
        if found:
            return found[0]
    raise argparse.ArgumentTypeError(f"no file {text} and no experiment or ablation called {text!r}")


def script_file(text: str) -> Path:
    """Model replies to replay: a path, or a name of configs/scripts/ (pipeline_check) of
    the core or a package."""
    from harness.sdk import find

    path = Path(text)
    if path.exists() or path.suffix == ".json" or "/" in text or "\\" in text:
        return path
    candidate = next(iter(find(f"configs/scripts/{text}.json")), None)
    if candidate is None:
        raise argparse.ArgumentTypeError(f"no file {text} and no script called {text!r} in configs/scripts/")
    return candidate


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


def run_sets(args) -> list[str]:
    """run_flags as experiment overrides (agent.runtime, the worker's options)."""
    return physical_sets(args) + think_sets(args) + workspace_sets(args)


def _physical_arguments(command):
    command.add_argument("--physical", help="the physical-input level for this run in place of "
                                                            "the default of your settings (their rules still hold)")
    command.add_argument("--allow-app", action="append", default=[], metavar="APP",
                         help="allow physical input in APP for this run (its process name; repeatable)")
    command.add_argument("--deny-app", action="append", default=[], metavar="APP",
                         help="never physical input in APP for this run (repeatable)")
    command.add_argument("--ask-app", action="append", default=[], metavar="APP",
                         help="ask before each step of physical input in APP for this run (repeatable)")
    command.add_argument("--window-details",
                         help="what the model learns of your windows the agent does not own, for this run in place "
                              "of the default of your settings (their rules still hold): none, presence (only that "
                              "another window is in front), apps, titles")


def _think_arguments(command):

    command.add_argument("--think", choices=("off", "on", "on_events", "periodic"),
                         help="accepted for older command lines; it has no effect (the model's turn is its own "
                              "while a program runs)")
    command.add_argument("--think-interval", type=float, metavar="SECONDS",
                         help="accepted for older command lines; it has no effect")


def think_sets(args) -> list[str]:
    """harness run and chat --think, --think-interval as experiment overrides."""
    level, interval = getattr(args, "think", None), getattr(args, "think_interval", None)
    if interval is not None and interval <= 0:
        raise ValueError("--think-interval is a number of seconds above 0")
    return [*([f"agent.runtime.think_while_acting={json.dumps(level)}"] if level else []),
            *([f"agent.runtime.think_interval={interval:g}"] if interval is not None else [])]


def _workspace_argument(command):
    command.add_argument("--workspace", choices=("browser", "desktop", "apps", "display"),
                         help="where the agent works: browser (a background browser: a task in words), desktop "
                              "(your screen), apps (your applications in the background: Windows, macOS, Linux on "
                              "X11) or display (a display of its own that you never see: a display server on Linux, "
                              "a virtual machine on Windows and macOS; the settings computer.display_backend and vm_* "
                              "say which); a task in words without it: a browser for a task about the web, else the "
                              "setting computer.mode")
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
    return [*([f"agent.runtime.physical={_toml(policy)}"] if policy else []),
            *([f"agent.runtime.privacy={_toml({'level': seen})}"] if seen else [])]


def _toml(value) -> str:
    """A value as TOML for --set: strings, numbers, booleans, arrays and inline tables."""
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(str(key))} = {_toml(item)}" for key, item in value.items()) + " }"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(item) for item in value) + "]"
    return ("true" if value else "false") if isinstance(value, bool) else json.dumps(value)
