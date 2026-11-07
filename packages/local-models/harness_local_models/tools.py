"""`harness doctor` and `harness fetch`: is this machine ready for a deploy or an
experiment, and get the weights it lacks."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from harness_local_models import deploy as deploys
from harness_local_models.supervisor import status


def gpus() -> list[dict] | None:
    """GPUs nvidia-smi reports (index, name, memory in GB), or None without it."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, encoding="utf-8",
                             errors="replace", timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    rows = []
    for line in out.strip().splitlines():
        index, name, used, total = [part.strip() for part in line.split(",")]
        rows.append({"index": int(index), "name": name, "used_gb": round(float(used) / 1024, 1),
                     "total_gb": round(float(total) / 1024, 1)})
    return rows


def doctor(deploy, *, names=None, keys=(), agent=None, core=False) -> dict:
    """What stands between this machine and running `deploy`: what is installed and what
    is not (a run installs it), ports held by something else, GPUs short of memory,
    missing interpreters and API keys. `keys` are environment variables the selected
    system needs (API keys); `agent`, a resolved agent whose services are the ones to check.
    `core`: no service, only the harness itself and whether a model is set up
    (`harness doctor` with nothing named and no deploy file)."""
    from harness_local_models.provision import service_status, services_used

    problems, notes = [], []
    if sys.version_info < (3, 11):
        problems.append(f"Python {sys.version.split()[0]}: 3.11 or newer is needed")
    if deploy.path is None:
        notes.append("No deploy file, and no GPU here with room for the agent's models: hosted models only.")
    elif deploy.path.parent == deploys.home() / "deploy":
        notes.append(f"No deploy file: the harness places the services itself ({deploy.path})")
    devices = gpus()
    by_index = {gpu["index"]: gpu for gpu in devices or []}
    names = [] if core else list(names) if names else (
        services_used(agent) if agent is not None else
        sorted(n for n, p in deploy.placements.items() if p.mode != "off"))
    if core:
        from harness.sdk import data, providers

        model = providers.ready(data())
        if not model["ready"]:
            problems.append(f"no model set up ({model['provider']}: {model['key_env']} is not set): run harness once "
                            "in a terminal, or export the key")
    installed = [service_status(deploy, name) for name in names if name in deploy.services
                 and deploy.placement(name).mode != "off"]
    names = [name for name in names if name in deploy.services]
    planned: dict[int, float] = {}
    groups: dict[tuple, float] = {}
    rows = {row["service"]: row for row in status(deploy, names)}
    for name in names:
        placement = deploy.placement(name)
        spec = deploy.services[name]
        if placement.mode == "off":
            continue
        if placement.mode == "external":
            if not rows[name].get("up"):
                problems.append(f"{name}: external URL {placement.url} does not answer")
            continue
        if not service_status(deploy, name)["installed"]:
            notes.append(f"{name}: not installed yet; the first run that uses it installs it (or: harness install "
                         f"{name})")
            argv = None
        else:
            argv, _environment, cwd = deploys.launch(deploy, name)
        if argv and not (Path(argv[0]).exists() or shutil.which(argv[0])):
            problems.append(f"{name}: interpreter {argv[0]} not found (set python for it in the deploy file)")
        if argv and not Path(cwd).is_dir():
            problems.append(f"{name}: working directory {cwd} not found")
        if not rows[name].get("up") and isinstance(placement.gpu, int):
            if placement.mode == "on_demand" and placement.swap:
                # One service of a swap group is loaded at a time: count the largest.
                key = (placement.gpu, placement.swap)
                groups[key] = max(groups.get(key, 0.0), spec.vram_gb)
            else:
                planned[placement.gpu] = planned.get(placement.gpu, 0.0) + spec.vram_gb
        if isinstance(placement.gpu, int) and devices is not None and placement.gpu not in by_index:
            problems.append(f"{name}: GPU {placement.gpu} does not exist here")
        port = deploys.port(deploy, name)
        if rows[name].get("up") and not rows[name].get("started_by_harness"):
            notes.append(f"{name}: port {port} already answers (started outside harness up); it will be used as is")
    for (index, _group), need in groups.items():
        planned[index] = planned.get(index, 0.0) + need
    for index, need in sorted(planned.items()):
        gpu = by_index.get(index)
        if gpu and gpu["total_gb"] - gpu["used_gb"] < need:
            problems.append(f"GPU {index}: {need:.1f} GB planned for services still to start, "
                            f"{gpu['total_gb'] - gpu['used_gb']:.1f} GB free")
    for name in (deploy.sim.get("gpus") or []):
        if devices is not None and name not in by_index:
            problems.append(f"sim: GPU {name} does not exist here")
    if keys:
        from harness.sdk import Credentials, data

        Credentials(data(), list(keys)).load()
    for key in keys:
        if not os.environ.get(key):
            problems.append(f"{key} is not set (export it, or keep it in [keys] of the configuration file)")
    to_install = [row["name"] for row in installed if not row["installed"]
                  and (row["what"] == "service" or row["name"] == "robodojo")]
    return {"schema_version": 1, "deploy": deploy.name, "ok": not problems, "problems": problems, "notes": notes,
            "gpus": devices, "services": [rows[name] for name in names if name in rows],
            "installed": [{**row, "installed": "yes" if row["installed"] else "no"} for row in installed],
            "to_install": to_install}


READY, WILL_INSTALL, MISSING = "ready", "will_install", "missing"
# What a [[weights]] entry downloads from; an entry without one is put in place by hand.
WEIGHT_SOURCES = ("modelscope_model", "modelscope_dataset", "hf_model", "hf_dataset")


def _placed(agent):
    """(uses, service, why it was dropped or None) of each service the agent's placement names."""
    for key, value in agent.placement.items():
        if isinstance(value, dict) and "service" in value:
            yield key, value["service"], value.get("dropped")
        elif isinstance(value, dict):
            for name, entry in value.items():
                yield key, name, entry.get("dropped")


def _files(paths) -> str:
    return f"{len(paths)} file{'' if len(paths) == 1 else 's'}"


def model_keys(agent) -> dict:
    """The environment variables the agent's hosted models read their key (or URL) from,
    each with the roles that need it."""
    configs = {"main": agent.main, "vlm": agent.runtime.get("vlm"), "pointer": agent.runtime.get("pointer")}
    if agent.runtime.get("verifier", True) and agent.runtime.get("mode") != "direct":
        configs["verifier"] = {**agent.main, **agent.verifier}
    keys: dict[str, list[str]] = {}
    for role, config in configs.items():
        if not isinstance(config, dict):
            continue
        backend = config.get("backend", "openrouter")
        names = [config.get("api_key_env") or ("OPENROUTER_API_KEY" if backend == "openrouter" else None)]
        if config.get("base_url_env") and not config.get("base_url"):
            names.append(config["base_url_env"])
        for name in names:
            if name:
                keys.setdefault(name, []).append(role)
    return keys


def fetch(deploy, name: str, *, log=print) -> int:
    """Download the weights of one service into the deploy's weights root. Returns
    the number of entries that failed."""
    return sum(not download(entry, Path(deploy.weights) / entry["dir"], label=name, log=log)
               for entry in deploy.services[name].weights)


def download(entry: dict, dest: Path, *, label: str, log=print) -> bool:
    """Download one [[weights]] (or a benchmark's [[assets]]) entry into `dest`: ModelScope
    and Hugging Face sources skip files whose sha256 already matches and resume the rest.
    A symlink, or an entry marked local, is left as it is. Whether it succeeded."""
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if dest.is_symlink() or (dest.exists() and entry.get("local")):
        log(f"{label}: {dest} is provided locally; skipped")
        return True
    if "modelscope_model" in entry:
        command = [sys.executable, str(scripts / "modelscope_download.py"), "model", entry["modelscope_model"], str(dest)]
    elif "modelscope_dataset" in entry:
        command = [sys.executable, str(scripts / "modelscope_download.py"), "dataset",
                   entry["modelscope_dataset"], str(dest), "--root", entry.get("root", "")]
    elif "hf_model" in entry or "hf_dataset" in entry:
        repo = entry.get("hf_model") or entry["hf_dataset"]
        command = [sys.executable, str(scripts / "hf_mirror_download.py"), repo, str(dest)]
        if "hf_dataset" in entry:
            command += ["--repo-type", "dataset"]
        for pattern in entry.get("include", []):
            command += ["--include", pattern]
    else:
        log(f"{label}: {entry['dir']} must be put in place by hand ({entry.get('local')})")
        return True
    for pattern in entry.get("exclude", []) if "modelscope_model" in entry or "modelscope_dataset" in entry else []:
        command += ["--exclude", pattern]
    if entry.get("parallel") and ("modelscope_model" in entry or "modelscope_dataset" in entry):
        command += ["--parallel", str(entry["parallel"])]
    log(f"{label}: {' '.join(command)}")
    return subprocess.run(command).returncode == 0
