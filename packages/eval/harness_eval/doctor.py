"""`harness doctor EXPERIMENT`: whether this machine can run an experiment as it is
configured: its skills, services, weights, benchmark, simulator GPUs and keys. The
services' checks are the local-models package's (harness_local_models/tools.py)."""

import os
from pathlib import Path
import shutil
import sys

from harness.sdk import version as harness_version
from harness_local_models import deploy as deploys
from harness_local_models.supervisor import status
from harness_local_models import tools
from harness_local_models.tools import MISSING, READY, WEIGHT_SOURCES, WILL_INSTALL, _files, _placed, model_keys


def check_experiment(run, *, sim_gpus=None, environ=None) -> dict:
    """`harness doctor EXPERIMENT`: whether this machine can run a loaded experiment as it
    is configured. Each check is ready; will_install (the first run installs it, or
    `harness install` now); or missing: the run fails, or runs without it, and `fix` says
    what to do. Keys are checked for being set; their values are never read out.
    `sim_gpus` replaces the deploy's simulator GPUs (`harness run --gpus`)."""
    from harness_eval.provision import bench_status
    from harness_eval.bench import Bench, load_bench
    from harness_local_models.provision import service_status, services_used
    from harness_eval.suite import suite_arguments

    environ = os.environ if environ is None else environ
    deploy, agent = run.deploy, run.agent
    checks = []

    def add(check, name, state, detail="", fix=None):
        checks.append({"check": check, "name": str(name), "status": state, "detail": detail,
                       **({"fix": fix} if fix else {})})

    version = sys.version.split()[0]
    if sys.version_info < (3, 11):
        add("python", version, MISSING, "3.11 or newer is needed", "install Python 3.11 or newer")
    else:
        add("python", version, READY)
    for name in agent.runtime.get("skills", []):
        add("skill", name, READY, "enabled")
    # A skill is off when the configuration has nothing it needs (the default agent names
    # no world model): that is the experiment as configured. A service it names that this
    # deploy does not run is missing.
    for uses, name, dropped in _placed(agent):
        if dropped:
            add("service", name, MISSING, f"{uses}: {dropped}",
                f"run it on this deploy: [services.{name}] in the deploy file (or a deploy with room for it)")
    devices = tools.gpus()
    by_index = {device["index"]: device for device in devices or []}
    names = services_used(agent)
    rows = {row["service"]: row for row in status(deploy, names)}
    planned: dict[int, float] = {}
    groups: dict[tuple, float] = {}
    users: dict[int, list[str]] = {}
    for name in names:
        placement, spec = deploy.placement(name), deploy.services[name]
        if placement.mode == "external":
            if rows[name].get("up"):
                add("service", name, READY, f"external, answers at {placement.url}")
            else:
                add("service", name, MISSING, f"external URL {placement.url} does not answer",
                    f"start it there, or change [services.{name}] url in the deploy file")
            continue
        state = service_status(deploy, name)
        where = f"{placement.mode} on GPU {placement.gpu}" if isinstance(placement.gpu, int) else placement.mode
        if not state["installed"]:
            lacking = ([f"environment {state['environment']}"] if not state["environment_installed"] else []) + \
                      ([_files(state["missing_files"])] if state["missing_files"] else [])
            add("service", name, WILL_INSTALL, f"{where}; not installed yet: {', '.join(lacking)}",
                f"harness install {name}")
        else:
            argv, _environment, cwd = deploys.launch(deploy, name)
            if argv and not (Path(argv[0]).exists() or shutil.which(argv[0])):
                add("service", name, MISSING, f"interpreter {argv[0]} not found",
                    f"set python for it in the deploy file's [services.{name}]")
            elif argv and not Path(cwd).is_dir():
                add("service", name, MISSING, f"working directory {cwd} not found", f"harness install {name}")
            else:
                running = rows[name].get("up")
                add("service", name, READY, where + ("; running" if running else ""))
        if spec.weights:
            absent = [entry for entry in spec.weights if not (Path(deploy.weights) / entry["dir"]).exists()]
            by_hand = [entry for entry in absent if not any(key in entry for key in WEIGHT_SOURCES)]
            if not absent:
                add("weights", name, READY, str(deploy.weights))
            elif by_hand:
                add("weights", name, MISSING, f"{', '.join(entry['dir'] for entry in by_hand)} not in {deploy.weights}",
                    by_hand[0].get("local") or f"put {by_hand[0]['dir']} in {deploy.weights} by hand")
            else:
                add("weights", name, WILL_INSTALL,
                    f"{', '.join(entry['dir'] for entry in absent)} not downloaded to {deploy.weights} yet",
                    f"harness fetch {name}")
        if not rows[name].get("up") and isinstance(placement.gpu, int):
            users.setdefault(placement.gpu, []).append(name)
            if placement.mode == "on_demand" and placement.swap:
                # One service of a swap group is loaded at a time: count the largest.
                key = (placement.gpu, placement.swap)
                groups[key] = max(groups.get(key, 0.0), spec.vram_gb)
            else:
                planned[placement.gpu] = planned.get(placement.gpu, 0.0) + spec.vram_gb
    for (index, _group), need in groups.items():
        planned[index] = planned.get(index, 0.0) + need
    state = bench_status(deploy, run.bench)
    if state["installed"]:
        add("benchmark", run.bench, READY, state.get("checkout") or state.get("note") or state["environment"])
    else:
        lacking = ([f"environment {state['environment']}"] if not state["environment_installed"] else []) + \
                  ([f"{_files(state['missing_files'])} in {state['checkout']}"] if state["missing_files"] else [])
        add("benchmark", run.bench, WILL_INSTALL, f"not installed yet: {', '.join(lacking)}",
            f"harness checkout {run.bench}")
    table = (getattr(deploy, "benches", {}) or {}).get(run.bench, {})
    for key in ("checkout", "python"):
        if table.get(key) and not Path(table[key]).exists():
            add("benchmark", run.bench, MISSING, f"[benches.{run.bench}] {key} {table[key]} not found",
                f"set {key} in the deploy file's [benches.{run.bench}]")
    bench = load_bench(run.bench)
    on_gpus = type(bench).slots is Bench.slots
    try:
        args = suite_arguments(run, gpus=sim_gpus)
    except ValueError as error:
        add("simulator", run.bench, MISSING, str(error),
            "give --gpus, or [sim] gpus in the deploy file" if on_gpus
            else f"fill the deploy file's [benches.{run.bench}]")
    else:
        slots = [int(item) for item in str(args.gpus).split(",")]
        if on_gpus:
            add("simulator", run.bench, READY, f"{args.workers_per_gpu} workers on each of GPUs "
                                                f"{', '.join(map(str, slots))}")
            for index in slots:
                planned[index] = planned.get(index, 0.0) + deploys.SIM_GPU_GB * args.workers_per_gpu
                users.setdefault(index, []).append(f"{args.workers_per_gpu} simulator workers")
        else:
            add("simulator", run.bench, READY, f"{len(slots)} workers: {', '.join(bench.where(s) for s in slots)}")
    if planned and devices is None:
        add("gpu", "nvidia-smi", MISSING, "nvidia-smi not found: the GPUs the run places work on cannot be seen",
            "run where the GPUs are, with the NVIDIA driver's nvidia-smi on PATH")
    elif planned:
        for index, need in sorted(planned.items()):
            device = by_index.get(index)
            what = ", ".join(users.get(index, []))
            if device is None:
                add("gpu", index, MISSING, f"does not exist here ({what})",
                    "pick GPUs that exist: --gpus, or the gpu settings of the deploy file")
                continue
            free = device["total_gb"] - device["used_gb"]
            if free < need:
                add("gpu", index, MISSING, f"{need:.1f} GB to start ({what}), {free:.1f} GB free",
                    f"free memory on GPU {index}, or place the work on another GPU (--gpus, the deploy file)")
            else:
                add("gpu", index, READY, f"{need:.1f} GB to start ({what}), {free:.1f} GB free")
    for key, roles in model_keys(agent).items():
        if (environ.get(key) or "").strip():
            add("key", key, READY, f"set; the {', '.join(roles)} model{'s' if len(roles) > 1 else ''} use it")
        else:
            add("key", key, MISSING, f"not set; the {', '.join(roles)} model{'s' if len(roles) > 1 else ''} need it",
                f"export {key}=... (keys live in environment variables, never in files)")
    counts = {state: sum(item["status"] == state for item in checks) for state in (READY, WILL_INSTALL, MISSING)}
    return {"schema_version": 1, "experiment": str(run.path) if run.path else None, "deploy": deploy.name,
            "agent": agent.name,
            "version": harness_version, "identity": agent.identity,
            "model": agent.main.get("model"), "bench": run.bench, "tasks": list(run.tasks), "seeds": list(run.seeds),
            "ok": not counts[MISSING], "counts": counts, "checks": checks,
            "skills_off": dict(agent.runtime.get("skills_dropped", {})), "gpus": devices,
            "to_install": list(dict.fromkeys(item["name"] for item in checks if item["status"] == WILL_INSTALL))}
