"""The eval package's commands (package.toml [provides] commands; the core's harness run
hands it everything but a task in words, harness doctor an experiment):

    harness run EXPERIMENT [--tasks T] [--seeds S] ...   the agent over an experiment's tasks
                                                         and seeds, workers started (suite.py)
    harness program EXPERIMENT --endpoint URL            the seeds of one task on a worker that runs
    harness config | lock [EXPERIMENT | AGENT]           what the agent resolves to; its lock
    harness runs [ROOT] | inspect OUTPUT                 the suites and their recorded outcomes
    harness view [RUNS]                                  the HTML pages of runs, served
    harness serve --factory module:callable              a worker in its own process
    harness checkout NAMES                               a benchmark's checkout, assets, environment
    harness self-improve ...                             a library grown on development seeds
"""

import argparse
import json
import os
from pathlib import Path
import sys

from harness.sdk import UsageError, cli_output as output, cli_table as table, format as formats
from harness_eval.flags import config_file, run_flags, run_sets, script_file


def _usage(command, message):
    print(f"harness {command}: {message}", file=sys.stderr)
    return 2


def _deploy_argument(command):
    command.add_argument("--deploy", help="deploy name (configs/deploy/<name>.toml) or path; default $HARNESS_DEPLOY")


def _model_arguments(command):
    command.add_argument("--model", help="model roles: a name of configs/models/ (e.g. grok-low) or a .toml file")
    command.add_argument("--agent", type=Path, help="agent file in place of configs/default.toml")


def run_arguments(command):
    """The options of an experiment (harness run, program, config, lock, doctor)."""
    _deploy_argument(command)
    _model_arguments(command)
    command.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY=VALUE",
                         help="override an experiment key, e.g. budget.max_cost_usd=2, agent.runtime.keep_images=1, "
                              "model.main.reasoning_effort=low (repeatable)")
    command.add_argument("--tasks", help="tasks overriding the experiment's: names, dimensions, moving, all")
    command.add_argument("--seeds", help="seeds overriding the experiment's, e.g. 0-4 or 0,2,5")
    command.add_argument("--strict", action=argparse.BooleanOptionalAction, default=None,
                         help="refuse to run without a skill or service the agent names "
                              "(default: on for evaluation layouts)")


def parser():
    root = argparse.ArgumentParser(prog="harness")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the agent over the tasks and seeds of an experiment "
                                          "(configs/experiments/*.toml, or --tasks and --seeds)",
                              epilog="Exit status: 0 every requested episode finished (succeeded or not), "
                                     "3 an episode ended in an error, 4 an episode did not finish or never ran, "
                                     "5 the suite cost cap stopped new episodes (the most severe of 3-5 wins), "
                                     "1 a harness error, 2 a usage error, 130 interrupted. "
                                     "Details: OUTPUT/outcome.json.")
    run.add_argument("config", type=config_file, nargs="?",
                     help="an experiment: a name of configs/experiments/ (dev) or a file (default: none; give --tasks)")
    run_arguments(run)
    run_flags(run)
    run.add_argument("--output", type=Path, help="suite directory, resumed when it exists "
                                                 "(default runs/<experiment>)")
    run.add_argument("--resume", type=Path, metavar="OUTPUT",
                     help="continue the suite in OUTPUT with the arguments its suite.json recorded; only --gpus, "
                          "--workers-per-gpu, --base-port, --workspaces and --rerun-errors may be given besides")
    run.add_argument("--dry-run", action="store_true", help="preview the resolved run and check resume compatibility "
                     "without installing dependencies, starting services or workers, or calling a model")
    run.add_argument("--gpus", help="GPUs for simulator workers, e.g. 3,5 (default: the deploy's [sim] gpus)")
    run.add_argument("--workers-per-gpu", type=int)
    run.add_argument("--base-port", type=int)
    run.add_argument("--workspaces", type=int, metavar="N",
                     help="run N workspaces of this machine side by side, sharing each task's seeds: background "
                          "browsers (bench browser, one context each in the shared headless Chromes) or isolated "
                          "displays and VMs (osworld, osomni); in place of --gpus and --workers-per-gpu")
    run.add_argument("--rerun-errors", action="store_true", help="run again the episodes that ended in an error")
    run.add_argument("--max-total-cost-usd", type=float, help="start no new episode once the suite spent this much")
    run.add_argument("--script", type=script_file, help="model replies to replay instead of calling a model: "
                                                        "a name of configs/scripts/ (pipeline_check) or a JSON file")
    program = commands.add_parser("program", help="Run the seeds of one task against a worker that already runs")
    program.add_argument("config", type=config_file, nargs="?",
                         help="experiment: a name of configs/experiments/ or a file")
    run_arguments(program)
    program.add_argument("--task", help="task (default: the experiment's first)")
    program.add_argument("--endpoint", help="worker URL (default: the experiment's endpoint)")
    program.add_argument("--output", type=Path, default=Path("runs"))
    program.add_argument("--script", type=script_file, help="model replies to replay instead of calling a model "
                                                            "(a name of configs/scripts/ or a JSON file)")
    config = commands.add_parser("config", help="Show what the agent (or an experiment) resolves to on a deploy: "
                                                "skills, services, identity")
    config.add_argument("config", type=config_file, nargs="?",
                        help="experiment or agent: a name (e.g. dev) or a file (default: configs/default.toml)")
    run_arguments(config)
    config.add_argument("--json", action="store_true", help="print the whole resolved configuration")
    lock = commands.add_parser("lock", help="Write the agent's lock: what decides its behavior, and its identity")
    lock.add_argument("config", type=config_file, nargs="?",
                      help="agent or experiment: a name or a file (default: configs/default.toml)")
    run_arguments(lock)
    lock.add_argument("--out", type=Path, help="write the lock here (default: print it)")
    runs = commands.add_parser("runs", help="Find experiment suites and their recorded outcomes without loading a model")
    runs.add_argument("root", type=Path, nargs="?", default=Path("runs"), help="runs directory (default runs)")
    runs.add_argument("--limit", type=int, default=20, help="maximum suites, newest evidence first (default 20)")
    runs.add_argument("--json", action="store_true", help="print the inventory as JSON")
    inspect = commands.add_parser("inspect", help="Read a suite's selection, outcomes, replacement layouts and evidence")
    inspect.add_argument("output", type=Path, help="suite directory containing suite.json")
    inspect.add_argument("--json", action="store_true", help="print the inspection as JSON")
    view = commands.add_parser("view", help="Write the HTML pages of runs (every model request, program, event "
                                            "and action) and serve them")
    view.add_argument("runs", type=Path, nargs="?", default=Path("runs"), help="runs directory (default runs)")
    view.add_argument("--port", type=int, default=8000, help="serve on 127.0.0.1:PORT (default 8000)")
    view.add_argument("--no-serve", action="store_true", help="only write the pages")
    return root


def _main(argv) -> int:
    args = parser().parse_args(argv)
    if args.command == "run":
        try:
            args.sets = list(args.sets) + run_sets(args)
        except ValueError as error:
            return _usage("run", str(error))
    if args.command in ("run", "program", "config", "lock"):
        return _runs(args)
    if args.command in ("runs", "inspect"):
        return _inspect_runs(args)
    return _view(args)


def run_experiment(argv) -> int:
    """harness run EXPERIMENT ... (the core hands it over)."""
    return _main(["run", *argv])


def program(argv) -> int:
    return _main(["program", *argv])


def config(argv) -> int:
    return _main(["config", *argv])


def lock(argv) -> int:
    return _main(["lock", *argv])


def runs(argv) -> int:
    return _main(["runs", *argv])


def inspect(argv) -> int:
    return _main(["inspect", *argv])


def view(argv) -> int:
    return _main(["view", *argv])


def serve(argv) -> int:
    from harness.sdk import serve_worker

    return serve_worker(argv)


def checkout(argv) -> int:
    """harness checkout NAMES: install benchmarks ahead of their first run: each one's checkout at
    the pinned commits, its assets, its environment."""
    parser = argparse.ArgumentParser(prog="harness checkout", description="Install benchmarks ahead of their first "
                                     "run: their checkouts, assets and environments")
    parser.add_argument("names", nargs="+", help="benchmarks (benches/<name>/bench.toml)")
    parser.add_argument("--deploy", help="deploy name (configs/deploy/<name>.toml) or path; default $HARNESS_DEPLOY")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from harness.sdk import bench_names, load_deploy
    from harness_eval.provision import install_bench

    unknown = [name for name in args.names if name not in bench_names()]
    if unknown:
        raise UsageError(f"no benchmark called {unknown[0]!r}; benchmarks: {', '.join(bench_names())}")
    deploy = load_deploy(args.deploy)
    rows = [install_bench(deploy, name, log=lambda message: print(message, file=sys.stderr, flush=True))
            for name in args.names]
    output(rows) if args.json else print(table(rows, ["name", "what", "installed", "environment"]))
    return 0 if all(row["installed"] for row in rows) else 1


def self_improve(argv) -> int:
    from harness_eval.self_improve import main

    return main(argv)


def _view(args):
    """`harness view`: write the run pages (harness_eval/view.py), then serve them with the
    host's file serving (range requests, so the videos seek) until interrupted."""
    from harness.sdk import serve_files
    from harness_eval import view

    if not args.runs.is_dir():
        raise ValueError(f"No runs directory {args.runs}")
    argv = sys.argv
    try:
        sys.argv = ["harness view", str(args.runs)]
        view.main()
    finally:
        sys.argv = argv
    if not args.no_serve:
        serve_files(args.runs, port=args.port)
    return 0


def _load_experiment(args):
    from harness_eval.experiments import load_experiment
    from harness_eval.suite import expand_seeds

    sets = list(args.sets)
    if args.agent:
        sets.append((["agent"], str(args.agent.resolve())))
    return load_experiment(args.config, deploy=args.deploy, sets=sets,
                           tasks=args.tasks.split(",") if getattr(args, "tasks", None) else None,
                           seeds=expand_seeds(args.seeds) if getattr(args, "seeds", None) else None,
                           strict=getattr(args, "strict", None), model=args.model)


def _load_quietly(args):
    """_load_experiment with placement diagnostics on stderr: they must not corrupt the
    JSON a preview or a check prints on stdout."""
    from contextlib import redirect_stdout

    with redirect_stdout(sys.stderr):
        return _load_experiment(args)


def doctor_parser():
    doctor = argparse.ArgumentParser(prog="harness doctor", description="Whether this machine can run an "
                                     "experiment as harness run --dry-run resolves it")
    doctor.add_argument("names", nargs="*", help="an experiment: a name of configs/experiments/ or a .toml file")
    run_arguments(doctor)
    doctor.add_argument("--gpus", help="the simulator GPUs, as harness run --gpus (default: the deploy's [sim] gpus)")
    doctor.add_argument("--json", action="store_true")
    return doctor


def doctor_experiment(argv) -> int:
    """harness doctor EXPERIMENT ... (the core hands over its arguments): whether this
    machine can run the experiment as harness run --dry-run resolves it."""
    from harness_eval.doctor import check_experiment

    args = doctor_parser().parse_args(list(argv))
    if len(args.names) > 1:
        return _usage("doctor", "give one experiment")
    args.config = config_file(args.names[0]) if args.names else None
    if args.config is not None and _is_agent_file(args):
        args.agent, args.config = args.config, None
    run = _load_quietly(args)
    report = check_experiment(run, sim_gpus=[int(g) for g in args.gpus.split(",")] if args.gpus else None)
    if args.json:
        output(report)
    else:
        missing = report["counts"]["missing"]
        print(f"experiment {report['experiment'] or '(none)'} on deploy {report['deploy']}: "
              f"{'ready' if report['ok'] else f'NOT ready, {missing} missing'}")
        print(f"agent {report['agent']} {report['version']}  identity {report['identity']}  "
              f"model {report['model']}  bench {report['bench']}, "
              f"{len(report['tasks'])} tasks x {len(report['seeds'])} seeds")
        print(f"skills on: {', '.join(item['name'] for item in report['checks'] if item['check'] == 'skill')}")
        for name, why in report["skills_off"].items():
            print(f"skill off: {name} ({why})")
        print(table([item for item in report["checks"] if item["check"] != "skill"],
                    ["check", "name", "status", "detail"]))
        for item in report["checks"]:
            if item["status"] == "missing":
                print(f"  fix {item['check']} {item['name']}: {item['fix']}")
        if report["to_install"]:
            print(f"the first run installs: {', '.join(report['to_install'])} "
                  f"(or now: harness install {' '.join(report['to_install'])})")
    return 0 if report["ok"] else 1


def _is_agent_file(args) -> bool:
    """config and lock: no experiment file, or an agent file rather than an experiment."""
    from harness.sdk import load_layered
    from harness_eval.experiments import is_experiment

    return args.config is None or not is_experiment(load_layered(args.config))


def _same_path(a, b) -> bool:
    return a == b or (a is not None and b is not None and Path(a).resolve() == Path(b).resolve())


def _resume(args):
    """harness run --resume OUTPUT: the arguments OUTPUT/suite.json recorded (invocation),
    with the worker placement given now. Any other argument given must match the record."""
    from harness_eval.suite import PLACEMENT, expand_seeds, recorded_invocation, script_hash

    output = args.resume.resolve()
    recorded = recorded_invocation(output)
    script = recorded.get("script")
    given = {
        "experiment": (args.config, not _same_path(args.config, recorded.get("experiment"))),
        "--agent": (args.agent, not _same_path(args.agent, recorded.get("agent"))),
        "--model": (args.model, args.model != recorded.get("model")
                    and not _same_path(args.model, recorded.get("model"))),
        "--set": (args.sets, args.sets != recorded.get("sets", [])),
        "--tasks": (args.tasks, args.tasks and args.tasks.split(",") != recorded.get("tasks")),
        "--seeds": (args.seeds, args.seeds and expand_seeds(args.seeds) != recorded.get("seeds")),
        "--strict": (args.strict, args.strict != recorded.get("strict")),
        "--deploy": (args.deploy, args.deploy != recorded.get("deploy")
                     and not _same_path(args.deploy, recorded.get("deploy"))),
        "--output": (args.output, not _same_path(args.output, output)),
        "--script": (args.script, args.script and script_hash(json.loads(args.script.read_text(encoding="utf-8")))
                     != (script or {}).get("sha256")),
        "--max-total-cost-usd": (args.max_total_cost_usd,
                                 args.max_total_cost_usd != recorded.get("max_total_cost_usd")),
    }
    conflicts = [name for name, (value, differs) in given.items() if value not in (None, []) and differs]
    if conflicts:
        raise UsageError(f"--resume continues {output} as its suite.json recorded; given differently: "
                         f"{', '.join(conflicts)}. Only --gpus, --workers-per-gpu, --base-port, --workspaces and "
                         "--rerun-errors may "
                         "change on resume; leave the others out, or choose a new --output for a changed experiment")
    if script and not (Path(script["path"]).is_file()
                       and script_hash(json.loads(Path(script["path"]).read_text(encoding="utf-8"))) == script["sha256"]):
        raise ValueError(f"Cannot resume {output}: the scripted replies it ran ({script['path']}) are gone or changed")
    args.config = Path(recorded["experiment"]) if recorded.get("experiment") else None
    args.agent = Path(recorded["agent"]) if recorded.get("agent") else None
    args.model, args.sets, args.strict = recorded.get("model"), list(recorded.get("sets", [])), recorded.get("strict")
    args.tasks = ",".join(recorded["tasks"])
    args.seeds = ",".join(str(seed) for seed in recorded["seeds"])
    args.deploy, args.output = recorded.get("deploy"), output
    args.script = Path(script["path"]) if script else None
    args.max_total_cost_usd = recorded.get("max_total_cost_usd")
    args.rerun_errors = args.rerun_errors or bool(recorded.get("rerun_errors"))
    if args.gpus is None and recorded.get("gpus"):
        args.gpus = ",".join(str(gpu) for gpu in recorded["gpus"])
    for key in PLACEMENT[1:]:
        if getattr(args, key) is None:
            setattr(args, key, recorded.get(key))
    return recorded


def _invocation(args, run, script, recorded=None):
    """What suite.json records of this `harness run` (invocation): what decides the episodes
    (paths absolute, tasks and seeds expanded) and where the workers ran. A resume keeps the
    record's rerun_errors: --rerun-errors given then holds for that run only."""
    from harness_eval.suite import script_hash

    def absolute(value):
        return str(Path(value).resolve()) if value is not None and Path(value).exists() else value

    return {
        "experiment": str(run.path) if run.path else None, "agent": absolute(args.agent),
        "model": absolute(args.model), "sets": list(args.sets), "tasks": list(run.tasks), "seeds": list(run.seeds),
        "strict": args.strict, "deploy": absolute(args.deploy or os.environ.get("HARNESS_DEPLOY")),
        "script": {"path": str(args.script.resolve()), "sha256": script_hash(script)} if args.script else None,
        "max_total_cost_usd": args.max_total_cost_usd,
        "rerun_errors": bool(recorded.get("rerun_errors")) if recorded else args.rerun_errors,
        "gpus": [int(gpu) for gpu in args.gpus.split(",")] if args.gpus else None,
        "workers_per_gpu": args.workers_per_gpu, "base_port": args.base_port, "workspaces": args.workspaces,
    }


def _runs(args):
    recorded = _resume(args) if getattr(args, "resume", None) else None
    script = json.loads(args.script.read_text(encoding="utf-8")) if getattr(args, "script", None) else None
    if args.command == "run" and args.output is None:
        args.output = Path("runs") / (args.config.stem if args.config else "run")
    if args.command == "program" and args.task:
        args.tasks = args.task
    if args.command in ("config", "lock") and _is_agent_file(args) and not args.tasks:
        from harness.sdk import DEFAULT_AGENT, apply_sets, load_layered, parse_set, resolve_agent

        path = args.agent or args.config or DEFAULT_AGENT
        tree = apply_sets(load_layered(path), [parse_set(item) for item in args.sets])
        agent = resolve_agent(tree, model=args.model, deploy=args.deploy, strict=bool(args.strict),
                              name=Path(path).stem)
        run = None
    else:
        if args.command in ("config", "lock") and args.config is not None and _is_agent_file(args):
            args.agent, args.config = args.config, None
        run = _load_quietly(args) if args.command == "run" and args.dry_run else _load_experiment(args)
        agent = run.agent
    if args.command == "lock":
        from harness_eval.lock import code_fingerprint

        document = {**agent.lock, "identity": agent.identity, "code": code_fingerprint()}
        text = json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8")
            print(json.dumps({"lock": str(args.out), "identity": agent.identity}))
        else:
            print(text, end="")
        return 0
    if args.command == "config":
        from harness.sdk import load_skills, version

        if args.json:
            output({"agent": agent.name, "version": version, "identity": agent.identity,
                    "main": agent.main, "runtime": agent.runtime, "placement": agent.placement, "lock": agent.lock,
                    **({"tasks": run.tasks, "seeds": run.seeds, "layouts": run.layouts, "strict": run.strict,
                        "deploy": run.deploy.name} if run else {})})
            return 0
        print(f"agent {agent.name} {version}  identity {agent.identity}  mode {agent.lock['mode']}")
        print(f"main model: {agent.main.get('model')} ({agent.main.get('backend', 'openrouter')})")
        if run:
            print(f"bench {run.bench}, {len(run.tasks)} tasks x {len(run.seeds)} seeds, {run.layouts} layouts, "
                  f"deploy {run.deploy.name}, strict {run.strict}")
        dropped = agent.runtime.get("skills_dropped", {})
        rows = [{"skill": name, "on": "yes" if name in agent.runtime["skills"] else "no",
                 "why": dropped.get(name, "" if name in agent.runtime["skills"] else "not in this configuration")}
                for name in load_skills()]
        print(table(rows, ["skill", "on", "why"]))
        rows = []
        for key, value in agent.placement.items():
            if isinstance(value, dict) and "service" in value:
                rows.append({"uses": key, "service": value["service"], "status": value.get("dropped", "")})
            elif isinstance(value, dict):
                rows += [{"uses": key, "service": name, "status": entry.get("dropped", "")}
                         for name, entry in value.items()]
        if rows:
            print(table(rows, ["uses", "service", "status"]))
        return 0
    if args.command == "program":
        from harness_eval.run import run_task
        from harness_eval.suite import preflight

        preflight(run, log=lambda message: print(message, file=sys.stderr, flush=True))
        config = run.task_config(args.task, endpoint=args.endpoint)
        if not config.environment.get("endpoint"):
            raise ValueError("No worker endpoint: give --endpoint or set endpoint in the experiment file "
                             "(or use harness run, which starts workers)")
        result = run_task(config, args.output, script=script)
        output(result)
        return 1 if any(item["status"] == "error" for item in result["episodes"]) else 0
    from harness_eval.suite import preview, run_suite

    invocation = _invocation(args, run, script, recorded)
    if args.dry_run:
        output(preview(run, args.output, script=script, rerun_errors=args.rerun_errors,
                       max_total_cost_usd=args.max_total_cost_usd, invocation=invocation))
        return 0

    if args.workspaces is not None and (args.gpus or args.workers_per_gpu):
        raise UsageError("--workspaces runs on this machine's workspaces: leave out --gpus and --workers-per-gpu")
    result = run_suite(run, args.output, gpus=[int(g) for g in args.gpus.split(",")] if args.gpus else None,
                       workers_per_gpu=args.workers_per_gpu, base_port=args.base_port, workspaces=args.workspaces,
                       rerun_errors=args.rerun_errors, script=script, max_total_cost_usd=args.max_total_cost_usd,
                       invocation=invocation)
    output(result)
    return result["exit_code"]


def _inspect_runs(args):
    from harness_eval.runs import inspect_suite, list_suites

    if args.command == "runs":
        rows = list_suites(args.root, args.limit)
        if args.json:
            output({"schema_version": 1, "root": str(args.root.resolve()), "suites": rows})
        elif not rows:
            print(f"No suites found in {args.root}")
        else:
            print(table([{"output": row["output"], "evidence_updated": row["evidence_updated"],
                          "liveness": row.get("liveness", "unknown"),
                          **row.get("counts", {}), "cost_usd": row.get("recorded_cost_usd"),
                          "coverage": "exact" if row.get("selection_exact") else "legacy/unknown",
                          "problem": row.get("error", "")} for row in rows],
                        ["output", "liveness", "completed", "error", "incomplete", "missing", "unknown", "unreadable",
                         "cost_usd", "coverage", "evidence_updated", "problem"]))
            print("Liveness is checked on the host that runs a suite only. Use harness inspect OUTPUT for details.")
        return 0
    result = inspect_suite(args.output)
    if args.json:
        output(result)
        return 0
    print(f"Suite: {result['output']}")
    print(f"Agent: {result['agent']} {result['agent_version']}  identity: {result['agent_id']}")
    print(f"Benchmark: {result['bench']}  layouts: {result['layout_source']}  pack: {result['layout_pack_seed']}")
    print(f"Latest inspected evidence: {result['evidence_updated']}  process liveness: {result['liveness']}")
    for process in result["processes"]:
        print(f"  running: pid {process.get('pid')} on {process.get('host')} since {process.get('started')}")
    if result["last_outcome"]:
        print(f"Last finished run: {result['last_outcome']['result']} (exit {result['last_outcome']['exit_code']}) "
              f"at {result['last_outcome']['ended']}")
    print(f"Coverage: {'exact requested pairs' if result['selection_exact'] else 'includes unconfirmed legacy candidates'}")
    print(table([result['counts']], ["completed", "error", "incomplete", "missing", "unknown", "unreadable"]))
    print(f"Recorded cost: {formats.cost(result['recorded_cost_usd'])} ({result['cost_scope']}); "
          f"{result['summaries_without_cost']} summaries have no usable cost")
    if result["episodes"]:
        print(table(result["episodes"], ["task", "seed", "actual_seed", "requested", "state", "status", "success"]))
    for row in result["episodes"]:
        if row.get("error") or row.get("reason"):
            print(f"  {row['task']} seed {row['seed']}: {row.get('error') or row.get('reason')}")
    for warning in result["warnings"]:
        print(f"  note: {warning}")
    for key, value in result["next_steps"].items():
        print(f"{key}: {value}")
    return 0
