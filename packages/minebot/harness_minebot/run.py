"""Runs on the body: one agent session on one game server, started from nothing and kept
in a folder of its own.

    harness minebot run <name> --task FILE [--model M] [--minutes 240] [--calls N]   a practice session
    harness minebot run <name> --from <run> ...          one that starts with that run's library and routines
    harness minebot run <name> --verify <run> ...        a verification run of what a practice run learned
    harness minebot run <name> --with bread:4,...        the body is given these as it starts (by /give)
    harness minebot run <name> --replay <run> [--programs N]     a run again, without a model
    harness minebot run <name> --script FILE ...         a run whose model is a script (a JSON list of replies)
    harness minebot run --continue <run> --message "..." one more turn of a run whose turn ended
    harness minebot run --tell "..."                     say something to the agent of the run that runs
    harness minebot stop                                 end the run and what runs beside the body

Every run has its folder runs/<name>/ under the package's data folder; a name is used once.

    practice      a library that learns and a routine store, both empty (--from RUN: copies of
                  RUN's, which go on learning); the session is a "learn this environment" one
    verification  the library and the routines of the named practice run, copied, learning as a
                  task run does; one attempt
    replay        the kind and settings of the named run; the programs that run ran, fed in as
                  the model's replies

The game server is yours: which world it plays, with what rules and whether the body may use
commands there is decided where the server is. Where the settings give a command that makes
a new world (minebot.start_over), the agent begins its attempts with it (start_over()), and a
run started while no server answers has no world until then.

The steps are always the same:

    1. stop what this package started before
    2. make runs/<name>/: library/, store/, config.toml, worker.toml and setup.json (what the
       run was started from: kind, model, settings, the package's and the harness's version)
    3. start the bridge, the game window where the settings ask for one, and the worker
    4. check the start: exactly the routines and library entries the run starts with
    5. start the run (run.log); while it lives, runs/.live names it

`harness minebot table <name>` prints what the game itself recorded of a run.
"""

import argparse
import glob
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

from harness.sdk import UsageError, python_path

from . import stack
from .config import PACKAGE, data_dir, settings


PRACTICE_MINUTES, VERIFY_MINUTES = 240, 120
BASE = PACKAGE / "configs" / "experiments" / "mineflayer.toml"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")
KEPT_SETTINGS = ("host", "port", "version", "username", "auth", "window", "start_over", "keep_start", "kept_info")


def runs_dir() -> Path:
    return data_dir() / "runs"


def live_file() -> Path:
    return runs_dir() / ".live"


def live_run() -> str | None:
    """The name of the run that is live (its process is there), or None."""
    try:
        name = json.loads(live_file().read_text(encoding="utf-8"))["name"]
    except (OSError, ValueError, KeyError):
        return None
    return name if stack.alive("run") else None


def forward(path) -> str:
    return str(path).replace("\\", "/")


def stop(log=print) -> None:
    stack.down(log)
    live_file().unlink(missing_ok=True)


def entries(library) -> list[str]:
    """The entries a library holds: those its index lists (memory entries have no file of
    their own) and the files of its sections."""
    library = Path(library)
    found = {forward(path.relative_to(library)) for section in ("notes", "memory", "skills", "reactive")
             for path in (library / section).glob("*") if path.is_file()}
    try:
        found |= set(json.loads((library / "index.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return sorted(found)


def programs_of(run: Path) -> list[str]:
    """The programs a run ran, in order, as the replies of a script."""
    traces = glob.glob(str(run / "trace" / "**" / "events.jsonl"), recursive=True)
    if not traces:
        raise UsageError(f"{run.name} has no trace to replay")
    rows = [json.loads(line) for line in open(traces[0], encoding="utf-8") if line.strip()]
    return ["<python>\n" + row["code"] + "\n</python>" for row in rows if row.get("event") == "cell" and row.get("code")]


def versions() -> dict:
    """What a run ran on: this package's version and the harness's."""
    import tomllib

    import harness

    with (PACKAGE / "package.toml").open("rb") as handle:
        return {"minebot": tomllib.load(handle)["package"]["version"], "harness": harness.__version__}


def toml_text(value: str) -> str:
    """`value` as a TOML basic string."""
    return json.dumps(str(value), ensure_ascii=False)


def program(run: Path, *arguments, log=print) -> None:
    """Start `harness program` on the run's configuration, as the part "run"."""
    stack.start("run", [sys.executable, "-m", "harness", "program", run / "config.toml", *arguments],
                log=f"run-{run.name}.log", env={**os.environ, "PYTHONPATH": python_path(), "PYTHONUTF8": "1"})
    runs_dir().mkdir(parents=True, exist_ok=True)
    live_file().write_text(json.dumps({"name": run.name, "started": time.time()}), encoding="utf-8")


def go_on(name, message, script=None, log=print) -> int:
    """One more turn of a run whose turn ended: the same session (its messages and facts), library and
    routines. What runs beside the body is started again when it is down; a run that still works is not touched."""
    run = runs_dir() / str(name)
    if not (run / "setup.json").is_file():
        raise UsageError(f"no such run: {name}")
    if not message:
        raise UsageError("--continue goes on with a message: give --message")
    kept = glob.glob(str(run / "trace" / "*" / "seed-*" / "conversation.json"))
    if not kept:
        raise UsageError(f"the run {name} kept no conversation to continue")
    if stack.alive("run"):
        raise UsageError("a run still works: wait for its turn to end, or stop it")
    setup = json.loads((run / "setup.json").read_text(encoding="utf-8"))
    values = settings(setup.get("settings"))
    try:
        up_for = json.loads(live_file().read_text(encoding="utf-8")).get("name")   # the run the parts were started for
    except (OSError, ValueError):
        up_for = None
    if up_for != name or not all(stack.rows(values).values()):
        import tomllib

        with (run / "worker.toml").open("rb") as handle:
            options = tomllib.load(handle)
        if not stack.up(values, store=run / "store", options=options, events_log=run / "body-events.jsonl", log=log):
            log("what runs beside the body did not come up: nothing was started")
            return 1
    arguments = [*(["--model", setup["model"]] if setup.get("model") else []), "--endpoint", stack.endpoint(values),
                 "--continue", os.path.dirname(kept[0]), "--message", message]
    if script:
        arguments += ["--script", script]
    program(run, *arguments)
    log(f"continued: the run {name} (its own session)")
    return 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="harness minebot run", description="A run on the body: one agent session on "
                                      "the game server the settings name, in a folder of its own")
    command.add_argument("name", nargs="?", help="the run's name: lower case letters, digits, - (used once)")
    command.add_argument("--task", metavar="FILE", help="the task the agent gets, as a text file")
    command.add_argument("--message", help="with a new run: added to the task (or the task itself, without --task); "
                                           "with --continue: what to tell the agent")
    command.add_argument("--tell", metavar="TEXT", help="say TEXT to the agent of the run that runs now; it goes on working")
    command.add_argument("--verify", metavar="RUN", help="a verification run of what the practice run RUN learned")
    command.add_argument("--replay", metavar="RUN", help="run RUN's programs again, without a model")
    command.add_argument("--programs", type=int, help="with --replay: only the first N programs")
    command.add_argument("--script", metavar="FILE", help="the model's replies, as a JSON list: a run without a model")
    command.add_argument("--with", dest="given", metavar="ITEMS",
                         help="the body is given these as the run starts: name:count,name:count (by /give: the server obeys "
                              "it where the body may use commands)")
    command.add_argument("--continue", dest="continued", metavar="RUN",
                         help="go on with the run RUN after its turn ended: one more turn in its own session, library and "
                              "routines, started by --message")
    command.add_argument("--from", dest="start_from", metavar="RUN",
                         help="a practice session that starts with the library and routines of the run RUN (copied)")
    command.add_argument("--model", help="the model: a name the harness knows, or a model file (default: the harness's own)")
    command.add_argument("--minutes", type=int, help=f"how long the session may take (default: {PRACTICE_MINUTES} for "
                                                     f"practice, {VERIFY_MINUTES} for verification)")
    command.add_argument("--calls", type=int, help="the model calls it may make (default: 3 a minute)")
    command.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY=VALUE",
                         help="a setting of the package for this run (minebot.KEY), e.g. --set host=play.example.org")
    return command


def main(argv, log=print) -> int:
    options = parser().parse_args(argv)
    overrides = {}
    for item in options.sets:
        key, found, value = item.partition("=")
        if not found:
            raise UsageError(f"--set takes KEY=VALUE, not {item!r}")
        overrides[key.strip().removeprefix("minebot.")] = value
    if options.tell:
        if not stack.alive("run"):
            log("no run is running: nothing was told")
            return 1
        answer = stack.rpc(settings(overrides), "user_says", text=options.tell)
        if not (answer or {}).get("told"):
            log(f"the message did not reach the run: {answer}")
            return 1
        log("told")
        return 0
    if options.continued:
        return go_on(options.continued, options.message, options.script, log)
    try:
        values = settings(overrides)
    except ValueError as error:
        raise UsageError(str(error)) from None
    options.minutes = options.minutes or (VERIFY_MINUTES if options.verify else PRACTICE_MINUTES)
    options.calls = options.calls or options.minutes * 3
    if not options.name or not NAME.fullmatch(options.name):
        raise UsageError("a run needs a name: lower case letters, digits, -")
    run = runs_dir() / options.name
    if run.exists():
        raise UsageError(f"the run {options.name} exists: a run starts from nothing, pick a new name")

    source, replayed, started_from = None, None, None
    if options.script:
        replayed = json.loads(Path(options.script).read_text(encoding="utf-8"))
    kind = "verification" if options.verify else "practice"
    task = Path(options.task).read_text(encoding="utf-8").strip() if options.task else ""
    if options.start_from:
        if options.verify or options.replay:
            raise UsageError("--from starts a practice session: leave out --verify and --replay")
        source, started_from = runs_dir() / options.start_from, options.start_from
        if not (source / "setup.json").is_file():
            raise UsageError(f"no such run: {options.start_from}")
    if options.verify or options.replay:
        source = runs_dir() / (options.verify or options.replay)
        if not (source / "setup.json").is_file():
            raise UsageError(f"no such run: {options.verify or options.replay}")
        was = json.loads((source / "setup.json").read_text(encoding="utf-8"))
        if options.verify and was.get("kind", "practice") != "practice":
            raise UsageError("a verification run takes what a practice run learned")
        if options.replay:
            replayed = programs_of(source)[:options.programs] + ["<finish>replayed</finish>"]
            kind = was.get("kind", "practice")
            options.model, options.minutes = was.get("model"), was["minutes"]
            options.calls = max(was["calls"], len(replayed) + 2)
            values = settings({**(was.get("settings") or {}), **overrides})
            task = task or was.get("task") or ""
            if options.message is None:
                options.message = was.get("message")
            source = runs_dir() / was["source"] if was.get("source") else None   # what that run itself started from
            started_from = was.get("from")
    instruction = "\n\n".join(part for part in (task, options.message or "") if part)
    if not instruction:
        raise UsageError("a run needs a task: --task FILE (a text file), or --message TEXT")
    given = {}
    for part in (options.given or "").split(","):
        if part.strip():
            item, _, count = part.strip().partition(":")
            given[item] = int(count or 1)

    # 1
    stop(log=lambda message: None)

    # 2
    library, store = run / "library", run / "store"
    run.mkdir(parents=True)
    if source and (kind == "verification" or started_from):
        # What the practice session learned (or the run --from names): this run's own copy, which goes on learning.
        shutil.copytree(source / "library", library, ignore=shutil.ignore_patterns(".library.lock"))
        for part in ("skills", "senses", "nav"):
            if (source / "store" / part).is_dir():
                shutil.copytree(source / "store" / part, store / part)
    else:
        library.mkdir()
    (store / "skills").mkdir(parents=True, exist_ok=True)
    starts_with = {"inventory": given, "routines": sorted(path.stem for path in (store / "skills").glob("*.js")),
                   "library": entries(library)}
    # A practice session is an active run (the harness says it is practice); a verification run
    # does the task itself and learns from it as a task run does.
    learning = (f'learn = "on", trigger = "active", reflect = true, active_minutes = {options.minutes}' if kind == "practice"
                else 'learn = "on", trigger = "passive", reflect = true')
    (run / "config.toml").write_text(f'''# Written by harness minebot run for the {kind} run "{options.name}".
description = "A bot body in a Minecraft: Java Edition server: a {kind} run"
include = ["{forward(BASE)}"]
endpoint = "{stack.endpoint(values)}"

[budget]
max_model_calls = {options.calls}
max_wall_seconds = {options.minutes * 60 + 600}

[overrides.agent.botbody.runtime]
library = {{ path = "{forward(library)}", {learning} }}
''', encoding="utf-8", newline="\n")
    more = {**({"given": given} if given else {}), **({"attempts": 1} if kind == "verification" else {})}
    worker = stack.worker_options(values, instruction=instruction, more=more)
    from harness.sdk import toml_dumps

    (run / "worker.toml").write_text(toml_dumps(worker), encoding="utf-8", newline="\n")
    setup = {"name": options.name, "kind": kind, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "model": options.model,
             "minutes": options.minutes, "calls": options.calls, "task": task, "message": options.message,
             "source": source.name if source else None, "from": started_from, "replay_of": options.replay,
             "scripted_replies": len(replayed) if replayed is not None else None, "starts_with": starts_with,
             "settings": {key: values[key] for key in KEPT_SETTINGS}, "versions": versions()}
    (run / "setup.json").write_text(json.dumps(setup, indent=1), encoding="utf-8")
    if replayed is not None:
        (run / "script.json").write_text(json.dumps(replayed), encoding="utf-8")

    # 3
    try:
        came_up = stack.up(values, store=store, options=worker, events_log=run / "body-events.jsonl", log=log)
    except RuntimeError as error:
        log(str(error))
        came_up = False
    if not came_up:
        stop(log=lambda message: None)
        log("what runs beside the body did not come up: nothing was started")
        return 1

    # 4
    body = stack.get(stack.bridge(values) + "/state") or {}
    if given and body.get("connected"):
        # Given before the run begins: the run's own record of commands starts with the run. (Where no world is
        # there yet, the worker gives them as the first attempt begins.)
        for item, count in given.items():
            stack.post(stack.bridge(values) + "/chat", {"text": f"/give @s {item} {count}"})
        time.sleep(2)
        body = stack.get(stack.bridge(values) + "/state") or {}
    clean = {f"the routines it starts with ({len(starts_with['routines'])})": body.get("skills") == starts_with["routines"],
             f"the library entries it starts with ({len(starts_with['library'])})": entries(library) == starts_with["library"]}
    if given and body.get("connected"):
        clean["it holds what it was given: " + ", ".join(f"{count} {item}" for item, count in given.items())] = \
            all((body.get("inventory") or {}).get(item, 0) >= count for item, count in given.items())
    for what, ok in clean.items():
        log(f"{'ok  ' if ok else 'NOT '} {what}")
    if not all(clean.values()):
        stop(log=lambda message: None)
        log("the start is not as the run starts: nothing was started")
        return 1

    # 5
    arguments = [*(["--model", options.model] if options.model else []), "--output", run / "trace"]
    if replayed is not None:
        arguments += ["--script", run / "script.json"]
    program(run, *arguments)
    how = f"replay of {options.replay}" if options.replay else "a script" if replayed is not None else (options.model or "the harness's model")
    log(f"started: the run {options.name} ({kind}, {how}, {options.minutes} min) on {values['host']}:{values['port']}; "
        f"its folder is {run}, its log {stack.logs_dir() / ('run-' + options.name + '.log')}")
    return 0
