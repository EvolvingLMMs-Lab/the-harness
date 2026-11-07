"""Run an experiment over many tasks and seeds: `harness run EXPERIMENT.toml`.

A worker serves one task, so each slot starts a worker for its next task, runs that
task's seeds, then stops the worker. The bench (harness.sdk Bench) says what the
experiment's tasks are, what a slot is (a GPU of the deploy's [sim] x workers_per_gpu,
or, on OS-Omni, a VM of its deploy table) and how a task's worker starts. Finished
episodes (summary.json present) are skipped, so a rerun resumes. With `--workspaces N`
the slots are N workspaces of this machine instead (background browsers, isolated
displays or VMs: Bench.workspace_slots), which share each task's seeds; background
browsers attach to the headless Chromes they share (the computer's `chromes` setting),
each in a context of its own. Results go to
OUTPUT/<task>/seed-<n>/; summarize with `harness report OUTPUT`. While it runs, the
process is listed in OUTPUT/.running (runs.liveness); at the end it writes what ran to
OUTPUT/outcome.json, with the exit code of `harness run` (EXIT_CODES). OUTPUT/suite.json
records the run's command line (`invocation`), so `harness run --resume OUTPUT` continues
it without the original flags (recorded_invocation). Before the first episode, what the
run uses and this machine lacks is installed (packages/provision.py), and its resident services are
started.
"""

import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from harness.sdk import (KERNEL_PYTHON_ENV, ROOT, RemoteEnvironment, atomic_write, file_lock, format as formats,
                         free_ports, python_path, scripted_models, sha256, toml_dumps, version)
from harness_eval.bench import bench_table, load_bench
from harness_eval.run import run_program_episode
from harness_eval.runs import RUNNING, inspect_suite, running_entry, running_processes

LOCK = threading.Lock()
# Model and verifier cost (USD) of the episodes this suite has run, all slots.
SPENT = {"usd": 0.0}
# The worker processes started and not stopped yet, stopped when the run is interrupted.
WORKERS = set()
# The exit code of `harness run` for each result. Several at once: the most severe
# (budget_exhausted > incomplete > errors).
EXIT_CODES = {"complete": 0, "errors": 3, "incomplete": 4, "budget_exhausted": 5, "interrupted": 130}
# suite.json: 2 added `invocation`; files of version 1 (or none) still read and resume
# with the original flags.
SUITE_SCHEMA_VERSION = 2
# What `harness run --resume` may change: where the workers run.
PLACEMENT = ("gpus", "workers_per_gpu", "base_port", "workspaces")


def log(output, message):
    """Print `message` with the time and append it to OUTPUT/suite.log (one slot at a time)."""
    line = f"{time.strftime('%H:%M:%S')} {message}"
    with LOCK:
        print(line, flush=True)
        with open(output / "suite.log", "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def expand_tasks(spec, benchmark="robodojo", layouts="procedural", deploy=None):
    """The task names of a comma-separated spec, in order and without repeats: each item as
    the bench expands it (its bench.toml `tasks`), with the bench's table of `deploy`."""
    items = [item.strip() for item in spec.split(",") if item.strip()]
    table = bench_table(deploy, benchmark)
    return list(dict.fromkeys(load_bench(benchmark).expand_tasks(items, layouts, table)))


def expand_seeds(spec):
    """The seeds of a comma-separated spec of seeds and inclusive ranges ("0-4,7")."""
    seeds = []
    for item in spec.split(","):
        if "-" in item:
            low, high = item.split("-")
            seeds += list(range(int(low), int(high) + 1))
        elif item:
            seeds.append(int(item))
    return seeds


def worker_name(args, task, slot) -> str:
    """worker-<task>, and -<slot> where workspaces run the same task side by side."""
    return f"worker-{task}" + (f"-{slot}" if getattr(args, "workspaces", None) else "")


def worker_options(args, task, directory, slot=None):
    """Write the bench's worker options for `task` (on `slot`) to
    `<directory>/<worker_name>.toml` and return the path."""
    options = load_bench(args.benchmark).worker_options(args, task, Path(directory), slot)
    path = Path(directory) / f"{worker_name(args, task, slot)}.toml"
    path.write_text(toml_dumps(options), encoding="utf-8")
    return path


def start_worker(args, task, gpu, port, output):
    """Start the bench's worker for `task` on slot `gpu`, serving on `port` in its own process
    group (log: `workers/<worker_name>.log`), and return the process once it answers. Raises
    RuntimeError when it exits, or stops it and raises when it is not ready in time."""
    options = worker_options(args, task, output / "workers", slot=gpu)
    # Isaac Lab logs under $TMPDIR/isaaclab; a shared /tmp may belong to another user.
    tmpdir = output / "tmp" / f"gpu{gpu}-port{port}"
    tmpdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, **(args.environment or {}), CUDA_VISIBLE_DEVICES=str(gpu), PYTHONUNBUFFERED="1",
               TMPDIR=str(tmpdir), PYTHONPATH=python_path(os.environ.get("PYTHONPATH")))
    if args.checkout:
        # The bench's checkout, where the harness installed it (HARNESS_ROBODOJO_ROOT, ...).
        env[f"HARNESS_{Path(args.checkout).name.upper()}_ROOT"] = args.checkout
    bench = load_bench(args.benchmark)
    python = bench.worker_process(args, gpu, env)
    name = worker_name(args, task, gpu)
    log_file = open(output / "workers" / f"{name}.log", "ab")
    process = subprocess.Popen(
        [python, "-u", "-m", "harness.core.worker",
         "--factory", bench.spec.factory,
         "--options", str(options), "--port", str(port),
         *(["--contract", args.contract, "--embodiment", args.embodiment]
           if getattr(args, "contract", "native") != "native" else []),
         *(["--exit-with-stdin"] if os.name == "nt" else [])],
        cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT, **_own_group())
    with LOCK:
        WORKERS.add(process)
    deadline = time.time() + args.boot_timeout
    while time.time() < deadline:
        if process.poll() is not None:
            WORKERS.discard(process)
            raise RuntimeError(f"worker for {task} exited with {process.returncode}; see workers/{name}.log")
        try:
            RemoteEnvironment(f"http://127.0.0.1:{port}", timeout=10).tools()
            return process
        except Exception:
            time.sleep(5)
    stop_worker(process)
    raise RuntimeError(f"worker for {task} did not become ready in {args.boot_timeout} s")


def _own_group() -> dict:
    """Popen's arguments for a worker that stop_worker can stop: a process group of its own
    (POSIX), or, on Windows, where a process without a console cannot signal another, a
    stdin it serves until it closes (`harness serve --exit-with-stdin`)."""
    if os.name == "nt":
        return {"stdin": subprocess.PIPE, "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_worker(process):
    """Stop a worker's process group if it still runs: SIGINT (on Windows its stdin closes,
    and the worker shuts its server down and closes its environment: a game's held keys go
    up), then a kill after 30 s."""
    try:
        if process.poll() is not None:
            return
        # Isaac Kit ignores SIGTERM; SIGINT usually works, SIGKILL always does.
        if os.name == "nt":
            if process.stdin is not None:
                process.stdin.close()
        else:
            os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    except ProcessLookupError:
        pass  # another thread stopped it first (an interrupted run stops every worker)
    finally:
        WORKERS.discard(process)


def new_record():
    """What the slots of one run report besides episode summaries: worker failures, episodes
    skipped at the suite's cost cap, and the event that tells them to stop."""
    return SimpleNamespace(failures=[], skipped=[], stop=threading.Event())


def done(directory, rerun_errors):
    """An episode counts as done once it has a summary; with rerun_errors, one that
    ended in an error (provider outage, dead worker) is run again."""
    summary = directory / "summary.json"
    if not summary.exists():
        return False
    return not (rerun_errors and json.loads(summary.read_text(encoding="utf-8")).get("status") == "error")


def replacements(task_dir, name="unstable"):
    """<task>/unstable.json: {unstable seed: the layout run in its place}, so a resumed suite runs
    the same replacement again instead of retrying the unstable layout. <task>/displaced.json:
    {requested seed: the layout run for it}, for a requested layout an earlier suite in this
    output had already run in place of an unstable one (that run keeps counting for its owner)."""
    path = task_dir / f"{name}.json"
    return {int(k): int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()} if path.exists() else {}


def write_replacements(task_dir, name, mapping):
    """Write <task>/<name>.json atomically: a kill mid-write must not leave broken JSON for the resume."""
    atomic_write(task_dir / f"{name}.json", json.dumps(mapping, indent=2))


def pack_size(args, task):
    """Number of layouts of `task` the bench can replace an unstable one from, or None when
    it is not known here."""
    return load_bench(args.benchmark).spare_layouts(args, task)[1]


def run_slot(args, slot, gpu, port, tasks, output, run, record=None):
    """One slot's loop: take tasks from the queue until it is empty (a task, or a task and
    its share of the seeds), and for each start a worker, run the seeds not done yet, and
    stop it. On RoboDojo eval layouts an unstable
    layout is replaced by the pack's next unused one; another worker error restarts the
    worker, and once the suite's cost cap is reached the remaining episodes are skipped.
    Worker failures and skipped episodes go to `record` (new_record); once its stop event
    is set, the slot starts nothing more."""
    record = record or new_record()
    while True:
        if record.stop.is_set():
            return
        try:
            item = tasks.get_nowait()
        except queue.Empty:
            return
        task, seeds = item if isinstance(item, tuple) else (item, args.seed_list)
        task_dir = output / task
        # As RoboDojo's own eval loop: an official layout that does not settle stably is skipped
        # (set aside as seed-<n>.unstable-<time>) and the next unused layout of the pack runs instead.
        spares = load_bench(args.benchmark).spare_layouts(args, task)[0]
        replaced = replacements(task_dir) if spares else {}
        displaced = replacements(task_dir, "displaced") if spares else {}
        size = pack_size(args, task) if spares else None
        if spares and size is None:
            log(output, f"[slot {slot}] {task}: layout count unknown (RoboDojo checkout not readable here); "
                        "spares are bounded by --unstable-spares only")
        # A spare is never a layout this suite was asked for, one already used, or one past the pack.
        # It is the next one after all of those (RoboDojo takes the next layout that settles).
        taken = set(args.seed_list) | set(replaced) | set(replaced.values()) | set(displaced.values())

        def next_spare():
            spare = max(taken) + 1
            while spare in taken or (task_dir / f"seed-{spare}").exists():
                spare += 1
            return None if size is not None and spare >= size else spare

        def resolve(seed):
            seed = displaced.get(seed, seed)
            while seed in replaced:
                seed = replaced[seed]
            return seed

        # A requested layout that an earlier suite in this output ran in place of an unstable one
        # still answers for that seed; the requested seed gets a layout of its own, so no layout
        # is counted twice.
        owners = {new: old for old, new in [*replaced.items(), *displaced.items()]}
        for seed in seeds:
            if spares and seed in owners and seed not in displaced:
                spare = next_spare()
                if spare is None:
                    log(output, f"[slot {slot}] {task} seed {seed}: already ran in place of seed {owners[seed]} "
                                "and no free layout is left in the pack")
                    continue
                displaced[seed] = spare
                taken.add(spare)
                write_replacements(task_dir, "displaced", displaced)
                log(output, f"[slot {slot}] {task} seed {seed}: already ran in place of seed {owners[seed]}; "
                            f"running seed {spare} for it")

        pending = list(dict.fromkeys(resolve(seed) for seed in seeds))
        pending = [seed for seed in pending if not done(task_dir / f"seed-{seed}", args.rerun_errors)]
        if not pending:
            log(output, f"[slot {slot}] {task}: all seeds done")
            continue
        where = load_bench(args.benchmark).where(gpu)
        log(output, f"[slot {slot}] {task}: starting worker on {where} port {port} for seeds {pending}")
        try:
            process = start_worker(args, task, gpu, port, output)
        except Exception as error:
            log(output, f"[slot {slot}] {task}: WORKER FAILED {error}")
            record.failures.append({"slot": slot, "task": task, "stage": "start", "reason": str(error)})
            continue
        stage = "episode"
        try:
            config = experiment_for(run, task, pending)
            config.environment = {**config.environment, "endpoint": f"http://127.0.0.1:{port}"}
            if args.max_model_calls:
                config.max_model_calls = args.max_model_calls
            if args.max_cost_usd:
                config.max_cost_usd = args.max_cost_usd
            spares_left = args.unstable_spares - len(replaced) if spares else 0
            retried = set()
            if pending and not record.stop.is_set():
                run_active(args, config, task_dir, pending[0], slot, output)
            while pending and not record.stop.is_set():
                seed = pending.pop(0)
                if args.max_total_cost_usd and SPENT["usd"] >= args.max_total_cost_usd:
                    log(output, f"[slot {slot}] {task} seed {seed}: skipped, suite spent "
                                f"{formats.cost(SPENT['usd'])} of {formats.cost(args.max_total_cost_usd)}")
                    record.skipped.append({"task": task, "seed": seed})
                    continue
                directory = output / task / f"seed-{seed}"
                if directory.exists():
                    # An interrupted or failed episode is rerun from scratch; the old run is kept.
                    kind = "error" if (directory / "summary.json").exists() else "incomplete"
                    directory.rename(directory.with_name(f"seed-{seed}.{kind}-{int(time.time())}"))
                scripted = {} if args.script_replies is None else scripted_models(args.script_replies)
                summary = run_program_episode(config, seed, directory, **scripted)
                with LOCK:
                    SPENT["usd"] += summary["cost_usd"]
                if record.stop.is_set() and summary["status"] == "error":
                    # The interrupted run stopped this episode's worker: keep the episode incomplete
                    # (summary set aside), so a resume runs it again instead of skipping an error.
                    os.replace(directory / "summary.json", directory / "summary.interrupted.json")
                    log(output, f"[slot {slot}] {task} seed {seed}: interrupted, left incomplete")
                    break
                log(output, f"[slot {slot}] {task} seed {seed}: {summary['status']} success={summary['success']} "
                            f"reward={summary['reward']} calls={summary['model_calls']} "
                            f"cost={formats.cost(summary['cost_usd'])} wall={formats.duration(summary['wall_seconds'])}")
                # RoboDojo drops a layout that does not settle at reset, and an episode it marks
                # unstable mid-way (scripted support arms); both are replaced by the next layout.
                unstable = summary["status"] == "error" and bool(
                    re.search(r"unstable after (reset|step)", str(summary.get("error", ""))))
                spare = next_spare() if unstable and spares_left > 0 else None
                if unstable and spare is None and spares:
                    log(output, f"[slot {slot}] {task} seed {seed}: unstable layout, no spare left; kept as an error")
                if spare is not None:
                    directory.rename(directory.with_name(f"seed-{seed}.unstable-{int(time.time())}"))
                    replaced[seed] = spare
                    taken.add(spare)
                    write_replacements(task_dir, "unstable", replaced)
                    log(output, f"[slot {slot}] {task} seed {seed}: unstable layout, skipped; running seed {spare} instead")
                    pending.append(spare)
                    spares_left -= 1
                    # The worker is still usable: its next reset loads the replacement layout into
                    # the same simulator (RoboDojo itself relaunches every round). In the R4 2-case
                    # run 8 replacements after unstable layouts ran full episodes this way.
                elif summary["status"] == "error" and not unstable and (
                        "Worker" in str(summary.get("error", "")) or not summary.get("steps")):
                    # An unstable layout leaves the worker usable; any other worker error restarts it,
                    # and so does an episode that failed before its first step (a reset that timed
                    # out: the simulator hung, and every later episode on it timed out too). That
                    # layout runs once more on the new worker.
                    log(output, f"[slot {slot}] {task}: worker error, restarting worker")
                    stop_worker(process)
                    if record.stop.is_set():
                        break
                    stage = "restart"
                    process = start_worker(args, task, gpu, port, output)
                    stage = "episode"
                    if not summary.get("steps") and seed not in retried:
                        retried.add(seed)
                        pending.insert(0, seed)
        except Exception as error:
            log(output, f"[slot {slot}] {task}: FAILED {type(error).__name__}: {error}")
            record.failures.append({"slot": slot, "task": task, "stage": stage,
                                    "reason": f"{type(error).__name__}: {error}"})
        finally:
            stop_worker(process)


def run_active(args, config, task_dir, seed, slot, output):
    """The active trigger before a task's runs (runtime/learning/active.py), when its library learns
    and asks for it: one run on the first seed's environment that learns it, in
    active-<seed>/ (once: a finished one is not run again). Its result is not a task result."""
    from harness.sdk import active

    if not active.wanted(config.runtime):
        return None
    directory = task_dir / f"active-{seed}"
    if (directory / "summary.json").exists():
        return None
    if directory.exists():
        directory.rename(directory.with_name(f"active-{seed}.incomplete-{int(time.time())}"))
    learning = active.active_config(config)
    # The task's environment without a time limit of its own: the run's live time bounds it,
    # and the practice sandbox of the bench where it has one (this run's only).
    bench = load_bench(args.benchmark)
    learning.task = bench.active_task(config.task)
    if (bench.spec.sandbox or {}).get("ops") and learning.task.endswith(active.LEARN):
        learning.runtime = {**learning.runtime, "sandbox": dict(bench.spec.sandbox)}
    log(output, f"[slot {slot}] {task_dir.name}: active run on seed {seed} "
                f"({learning.max_wall_seconds / 60:g} min) before the task's runs")
    scripted = {} if args.script_replies is None else scripted_models(args.script_replies)
    summary = run_program_episode(learning, seed, directory, **scripted)
    with LOCK:
        SPENT["usd"] += summary["cost_usd"]
    log(output, f"[slot {slot}] {task_dir.name} active run: {summary['status']} calls={summary['model_calls']} "
                f"cost={formats.cost(summary['cost_usd'])} wall={formats.duration(summary['wall_seconds'])}")
    return summary


def experiment_for(run, task, seeds):
    """The driver's configuration of one task of the experiment."""
    return run.task_config(task, seeds)


def suite_arguments(run, *, gpus=None, workers_per_gpu=None, base_port=None, rerun_errors=False, script=None,
                    max_total_cost_usd=None, prepared=None, workspaces=None):
    """The suite's settings: the run's, the deploy's [sim] section (or the bench's slots,
    or `workspaces` of this machine), then the command line."""
    sim = dict(getattr(run.deploy, "sim", {}) or {})
    suite = run.suite
    bench = load_bench(run.bench)
    contract = run.agent.runtime.get("contract", "native")
    if contract != "native" and bench.spec.embodiment is None:
        raise ValueError(f"The agent's contract {contract!r} needs an embodiment profile, and bench {run.bench} has "
                         "none: set agent.runtime.contract = \"native\" for it")
    args = SimpleNamespace(
        benchmark=run.bench, seed_list=list(run.seeds), layout_source=run.layouts,
        layout_pack_seed=run.layout_pack_seed,
        # Without one, the worker uses its checkout's (RoboDojo harness_dev_layouts, RoboTwin harness_seeds).
        dev_layout_dir=run.tree.get("dev_layout_dir"),
        worker=dict(run.worker), bench_deploy=bench_table(run.deploy, run.bench),
        boot_timeout=float(suite.get("boot_timeout", 600)),
        max_model_calls=run.budget.get("max_model_calls"), rerun_errors=rerun_errors,
        max_cost_usd=run.budget.get("max_cost_usd"),
        max_total_cost_usd=max_total_cost_usd or run.budget.get("max_total_cost_usd"),
        unstable_spares=int(suite.get("unstable_spares", 5)),
        contract=contract, embodiment=bench.spec.embodiment, script_replies=script,
        # The run's physical-input policy (--physical, --allow-app...), for a bench whose
        # worker acts before the session identifies itself (Minecraft's new world at reset).
        physical=dict(run.agent.runtime.get("physical") or {}),
        # The interpreter of the bench's environment, its checkout and its environment
        # variables, when the harness installed them (install.prepare).
        python=(prepared or {}).get("python"), checkout=(prepared or {}).get("checkout"),
        environment=(prepared or {}).get("env"), workspaces=int(workspaces) if workspaces else None)
    if workspaces is not None and int(workspaces) < 1:
        raise ValueError("--workspaces is at least 1")
    slots = bench.workspace_slots(args, args.workspaces) if args.workspaces else bench.slots(args)
    if slots is not None:
        gpus, workers_per_gpu = slots, 1
        base_port = base_port or bench.base_port(args)
    gpu_list = gpus if gpus is not None else sim.get("gpus")
    if not gpu_list:
        raise ValueError("No GPUs for simulator workers: give --gpus or a deploy file with [sim] gpus")
    args.gpus = ",".join(str(g) for g in gpu_list)
    args.workers_per_gpu = int(workers_per_gpu or sim.get("workers_per_gpu", 1))
    # The first worker's port when the command line, the bench or the deploy names one; else
    # the workers take ports the system gives (core/ports.py), never one another's.
    args.base_port = int(base_port or sim.get("base_port") or 0) or None
    return args


def preflight(run, log=print):
    """Before any worker boots: install what the run uses and this machine lacks
    (install.prepare), start the resident services that do not answer, check that the
    external ones do, and start the broker of the on-demand ones. Returns the interpreter
    of the bench's workers and kernel (None: the harness's own), its checkout and its
    environment variables; the kernel's interpreter goes to $HARNESS_KERNEL_PYTHON for
    the driver."""
    from harness_eval.provision import prepare
    from harness_local_models.provision import services_used
    from harness_local_models import deploy as deploys
    from harness_local_models.supervisor import listening, start_broker, up

    deploy = run.deploy
    prepared = prepare(run, log=log)
    if prepared["python"]:
        os.environ[KERNEL_PYTHON_ENV] = prepared["python"]
    names = services_used(run.agent)
    resident = [name for name in names if deploy.placement(name).mode == "resident"
                and not listening(deploys.port(deploy, name))]
    if resident:
        up(deploy, resident, log=log)
    down = []
    for name in names:
        placement = deploy.placement(name)
        if placement.mode == "external":
            address = deploys.url(deploy, name).split("://", 1)[-1].split("/", 1)[0]
            host, _, port = address.rpartition(":")
            if port.isdigit() and not listening(int(port), host):
                down.append(name)
    if down:
        raise RuntimeError(f"external services {down} do not answer")
    if any(deploy.placement(name).mode == "on_demand" for name in names):
        start_broker(deploy, log=log)
    return prepared


def execution_settings(run, script=None):
    """Settings that may not change while adding tasks or seeds to a suite.

    Placement, worker slots and the suite spending cap may change. Episode budgets,
    worker options and scripted replies affect the measured result and may not.
    """
    config = run.task_config()
    return {
        "agent_id": run.agent.identity, "bench": run.bench,
        "layout_source": run.layouts, "layout_pack_seed": run.layout_pack_seed,
        "dev_layout_dir": run.tree.get("dev_layout_dir"), "worker": run.worker,
        "budget": {"max_model_calls": config.max_model_calls, "max_wall_seconds": config.max_wall_seconds,
                   "max_cost_usd": config.max_cost_usd},
        "script_sha256": script_hash(script),
    }


def script_hash(script):
    """The hash of scripted replies (None: a model answers), as execution settings record it."""
    return None if script is None else sha256(script)


def merge_invocation(previous, invocation):
    """The invocation suite.json keeps when a run joins or extends a suite: this run's flags,
    with the tasks and seeds of both (several processes may share one output). None keeps
    the previous one."""
    if invocation is None:
        return previous
    if not previous:
        return invocation
    return {**invocation, "tasks": list(dict.fromkeys([*previous.get("tasks", []), *invocation["tasks"]])),
            "seeds": sorted({*previous.get("seeds", []), *invocation["seeds"]})}


def recorded_invocation(output):
    """The `harness run` arguments OUTPUT/suite.json recorded, for `harness run --resume`.
    Raises ValueError when there is no suite, when it predates `invocation` (with the
    command to resume it by hand), or when its episodes are not the tasks x seeds of the
    invocation (runs of other selections shared it: resuming would add episodes)."""
    output = Path(output).resolve()
    path = output / "suite.json"
    if not path.is_file():
        raise ValueError(f"Cannot resume {output}: no suite.json there (harness runs lists the suites)")
    suite = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(suite, dict):
        raise ValueError(f"Cannot resume {output}: suite metadata must be a JSON object")
    invocation = suite.get("invocation")
    if not isinstance(invocation, dict):
        command = ["harness", "run", *([suite["run"]] if suite.get("run") else []),
                   *(["--deploy", suite["deploy"]] if suite.get("deploy") else []),
                   *(["--tasks", ",".join(suite["tasks"])] if suite.get("tasks") else []),
                   *(["--seeds", ",".join(str(seed) for seed in suite["seeds"])] if suite.get("seeds") else []),
                   "--output", str(output), "--dry-run"]
        raise ValueError(f"Cannot resume {output} by its path: its suite.json (schema_version "
                         f"{suite.get('schema_version', 1)}) has no recorded command line. Resume it with the original "
                         f"command and the same --model, --set and --script, previewing first: {shlex.join(command)}")
    grid = {(task, seed) for task in invocation.get("tasks", []) for seed in invocation.get("seeds", [])}
    requested = {(entry.get("task"), entry.get("seed")) for entry in suite.get("episodes", [])
                 if isinstance(entry, dict)}
    if requested != grid:
        raise ValueError(f"Cannot resume {output} by its path: its episodes are not the recorded tasks x seeds "
                         "(runs with other selections shared it, or one predates the record). Resume each part "
                         "with its original command and --output")
    return invocation


def check_resume(output, settings, previous=None):
    """Refuse to mix incompatible results. Return fields an older suite did not record.

    Call before preflight and again under the suite metadata lock. Reading a legacy
    suite checks the identity and layouts it recorded; the preview exposes what could
    not be checked, and the next real run records the full settings.
    """
    output = Path(output)
    if previous is None:
        path = output / "suite.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError(f"Cannot resume {output}: suite metadata must be a JSON object")
    if not previous:
        if next(output.glob("*/seed-*"), None) is not None:
            raise ValueError(f"Cannot resume {output}: episode directories exist without suite metadata; "
                             "choose a new --output directory")
        return []
    recorded = previous.get("execution", previous)
    if not isinstance(recorded, dict):
        raise ValueError(f"Cannot resume {output}: execution settings must be a JSON object")
    changed = [key for key in settings if key in recorded and recorded[key] != settings[key]]
    if changed:
        details = "; ".join(f"{key}: {recorded[key]!r} -> {settings[key]!r}" for key in changed)
        raise ValueError(f"Cannot resume {output}: incompatible {details}. Choose a new --output directory "
                         "for a changed experiment; keep the original settings to resume this suite")
    return sorted((set(settings) - set(recorded)) | set(previous.get("legacy_unchecked_fields", [])))


def preview(run, output, *, script=None, rerun_errors=False, max_total_cost_usd=None, invocation=None):
    """Describe the selected experiment without installing or executing it.

    Configuration resolution has already happened (automatic placement may cache its
    deploy). This is a configuration preview, not a hardware or service readiness check
    (harness doctor EXPERIMENT is). `invocation` is the command line the run would record
    (run_suite).
    """
    from harness_local_models.provision import services_used

    output = Path(output).resolve()
    settings = execution_settings(run, script)
    unchecked = check_resume(output, settings)
    return {
        "schema_version": 1, "dry_run": True, "output": str(output), "invocation": invocation,
        "experiment": str(run.path) if run.path else None,
        "agent": run.agent.name, "agent_version": run.agent.lock.get("agent_version", version),
        "execution": settings, "model": run.agent.main.get("model"),
        "tasks": list(run.tasks), "seeds": list(run.seeds),
        "selected_episodes": len(run.tasks) * len(run.seeds), "strict": run.strict,
        "skills": run.agent.runtime.get("skills", []),
        "skills_dropped": run.agent.runtime.get("skills_dropped", {}),
        "services": services_used(run.agent),
        "max_total_cost_usd": max_total_cost_usd or run.budget.get("max_total_cost_usd"),
        "resume": {"existing_suite": (output / "suite.json").is_file(),
                   "unchecked_legacy_fields": unchecked, "rerun_errors": rerun_errors,
                   "policy": "skip episodes with summaries; restart incomplete episodes from reset"},
        "readiness": "not checked; harness doctor with the same experiment and options checks it",
    }


@contextlib.contextmanager
def metadata_lock(output):
    """Hold OUTPUT/suite.json.lock: several processes may share one output (one per GPU)."""
    with file_lock(output / "suite.json.lock"):
        yield


def write_running(output, entry, add=True):
    """Add `entry` to OUTPUT/.running, or remove it (and the file once no process is left).
    The caller holds metadata_lock."""
    try:
        processes = running_processes(output)
    except (OSError, ValueError):
        processes = []
    processes = [item for item in processes
                 if (item.get("host"), item.get("pid")) != (entry["host"], entry["pid"])]
    if add:
        processes.append(entry)
    if processes:
        atomic_write(output / RUNNING, json.dumps({"schema_version": 1, "processes": processes}, indent=2))
    else:
        (output / RUNNING).unlink(missing_ok=True)


def outcome(output, tasks, seeds, record, *, started, interrupted=False, max_total_cost_usd=None):
    """What one `harness run` did with the episodes it was asked for (OUTPUT/outcome.json).

    Episode states are inspect_suite's for these tasks and seeds only: other processes
    sharing the output answer for theirs. `result` picks the exit code (EXIT_CODES).
    """
    wanted = {(task, seed) for task in tasks for seed in seeds}
    rows = [row for row in inspect_suite(output)["episodes"] if (row["task"], row["seed"]) in wanted]
    counts = {state: sum(row["state"] == state for row in rows)
              for state in ("completed", "error", "incomplete", "missing", "unreadable")}
    if interrupted:
        result = "interrupted"
    elif record.skipped:
        result = "budget_exhausted"
    elif counts["incomplete"] or counts["missing"] or counts["unreadable"]:
        result = "incomplete"
    elif counts["error"]:
        result = "errors"
    else:
        result = "complete"
    return {
        "schema_version": 1, "output": str(output), "result": result, "exit_code": EXIT_CODES[result],
        "interrupted": interrupted, "started": started,
        "ended": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "tasks": list(tasks), "seeds": list(seeds), "requested_episodes": len(wanted),
        "finished_episodes": counts["completed"] + counts["error"], "counts": counts,
        "episodes": [{key: row.get(key) for key in ("task", "seed", "actual_seed", "state", "status", "error")}
                     for row in rows if row["state"] != "completed"],
        "worker_failures": list(record.failures),
        "budget": {"max_total_cost_usd": max_total_cost_usd, "spent_usd": SPENT["usd"],
                   "reached": bool(max_total_cost_usd) and SPENT["usd"] >= max_total_cost_usd,
                   "skipped": list(record.skipped)},
        "cost_usd": SPENT["usd"],
    }


def stop_workers():
    """Stop every worker this process started and has not stopped."""
    for process in list(WORKERS):
        stop_worker(process)


def run_suite(run, output, *, invocation=None, **options):
    """Run every task and seed of `run` into `output` (see suite_arguments for options) and
    return its outcome, also written to OUTPUT/outcome.json. Ctrl-C stops this run's workers
    and returns the outcome with result "interrupted". `invocation`, the `harness run`
    arguments, goes to suite.json for `harness run --resume` (merge_invocation)."""
    output = Path(output).resolve()
    settings = execution_settings(run, options.get("script"))
    check_resume(output, settings)
    prepared = preflight(run, log=lambda message: print(message, file=sys.stderr, flush=True))
    args = suite_arguments(run, prepared=prepared, **options)
    (output / "workers").mkdir(parents=True, exist_ok=True)
    (output / "truth").mkdir(exist_ok=True)
    tasks = list(run.tasks)
    slots = [(gpu, index) for gpu in args.gpus.split(",") for index in range(args.workers_per_gpu)]
    if args.workspaces and args.benchmark == "browser":
        # The headless Chromes the background browsers share, as the computer package keeps
        # them (harness/extensions.py), at most its chromes setting.
        from harness.sdk import Settings, data, first

        Chromes = first("Chromes")
        if Chromes is not None:
            limit = Settings(data()).get()["computer"]["chromes"]
            args.chromes = Chromes(output / "workers", lambda: limit)
    # Several processes may share one output (one per GPU): merge their tasks and seeds.
    entry = running_entry()
    with metadata_lock(output):
        previous = (json.loads((output / "suite.json").read_text(encoding="utf-8"))
                    if (output / "suite.json").exists() else {})
        unchecked = check_resume(output, settings, previous)
        episodes = list(previous.get("episodes", []))
        known = {(entry["task"], entry["seed"]) for entry in episodes}
        for task in tasks:
            for seed in args.seed_list:
                if (task, seed) not in known:
                    episodes.append({"task": task, "seed": seed})
                    known.add((task, seed))
        legacy_selection = previous.get("legacy_selection")
        if previous and "episodes" not in previous:
            legacy_selection = {"tasks": previous.get("tasks", []), "seeds": previous.get("seeds", [])}
        document = {
            "schema_version": SUITE_SCHEMA_VERSION, "episodes": episodes, "legacy_selection": legacy_selection,
            "invocation": merge_invocation(previous.get("invocation"), invocation),
            "run": str(run.path) if run.path else None, "agent": run.agent.name, "agent_id": run.agent.identity,
            "execution": settings,
            "legacy_unchecked_fields": unchecked,
            "agent_version": run.agent.lock.get("agent_version", version),
            "deploy": getattr(run.deploy, "name", None),
            "tasks": list(dict.fromkeys([*previous.get("tasks", []), *tasks])),
            "seeds": sorted({*previous.get("seeds", []), *args.seed_list}),
            "layout_source": args.layout_source, "layout_pack_seed": args.layout_pack_seed,
            "started": previous.get("started") or time.strftime("%Y-%m-%d %H:%M:%S")}
        atomic_write(output / "suite.json", json.dumps(document, indent=2))
        write_running(output, entry)
    try:
        work = queue.Queue()
        for task in tasks:
            if args.workspaces and len(slots) > 1:
                # Workspaces share a task's seeds: a share each, on a worker of its own.
                for index in range(len(slots)):
                    if args.seed_list[index::len(slots)]:
                        work.put((task, args.seed_list[index::len(slots)]))
            else:
                work.put(task)
        log(output, f"suite: {len(tasks)} tasks x {len(args.seed_list)} seeds on {len(slots)} slots "
                    f"(agent {run.agent.name} {run.agent.identity})")
        with LOCK:
            SPENT["usd"] = 0.0
        record = new_record()
        threads = []
        ports = free_ports(len(slots), args.base_port)

        def drive_slot(done, *slot_args):
            try:
                run_slot(*slot_args)
            finally:
                done.set()

        interrupted = False
        try:
            for number, (gpu, _index) in enumerate(slots):
                done = threading.Event()
                thread = threading.Thread(target=drive_slot, daemon=True, args=(
                    done, args, number, gpu, ports[number], work, output, run, record))
                threads.append((thread, done))
                thread.start()
            for thread, done in threads:
                # An interrupted Thread.join can mark a running thread as stopped on
                # CPython 3.11. Wait for the slot's own completion signal first.
                while not done.wait(1):
                    pass
                thread.join()
        except KeyboardInterrupt:
            interrupted = True
            record.stop.set()
            log(output, "suite: interrupted, stopping this run's workers")
            stop_workers()
            # Let the episodes whose workers stopped end before reading their state.
            deadline = time.monotonic() + 60
            for thread, done in threads:
                if thread.ident is not None and done.wait(max(0.0, deadline - time.monotonic())):
                    thread.join(max(0.0, deadline - time.monotonic()))
        result = outcome(output, tasks, args.seed_list, record, started=entry["started"],
                         interrupted=interrupted, max_total_cost_usd=args.max_total_cost_usd)
        atomic_write(output / "outcome.json", json.dumps(result, indent=2))
        log(output, f"suite: {result['result']} (exit {result['exit_code']}), "
                    f"{result['finished_episodes']} of {result['requested_episodes']} episodes finished, "
                    f"model cost {formats.cost(SPENT['usd'])}")
        return result
    finally:
        if getattr(args, "chromes", None) is not None:
            args.chromes.close()
        with metadata_lock(output):
            write_running(output, entry, add=False)
