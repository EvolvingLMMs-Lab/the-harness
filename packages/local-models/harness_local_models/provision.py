"""Install on first use: a service's environment ([environment] of its manifest), sources
and weights, when a run calls it and this machine does not have it yet (harness install
NAMES does it ahead of time). Benchmarks are the core's (harness.packages.provision);
before a suite's first episode the eval package installs both (harness_eval/provision.py)."""

from pathlib import Path
import sys

from harness.sdk import environments
from harness_local_models import deploy as deploys
from harness_local_models.tools import download


def environment_of(deploy, name: str):
    """The environment service `name` runs in on this deploy, or None: its placement
    names an interpreter, it has none, or the deploy runs everything in the harness's own
    (environments = "project")."""
    spec = deploy.services[name]
    if spec.environment is None or deploy.placement(name).python or environments.mode(deploy) == "project":
        return None
    return environments.resolve(name, spec.environment, deploy, services=deploy.services)


def python(deploy, name: str) -> str:
    """The interpreter of service `name`: its placement's, its environment's, or the
    harness's own."""
    if deploy.placement(name).python:
        return deploys.render(deploy.placement(name).python, deploy.variables())
    environment = environment_of(deploy, name)
    return str(environment.python) if environment else sys.executable


def service_status(deploy, name: str) -> dict:
    """Whether service `name` is installed here: its environment and its files."""
    placement = deploy.placement(name)
    if placement.mode == "external":
        return {"name": name, "what": "service", "installed": True, "note": "external: nothing to install"}
    environment = environment_of(deploy, name)
    missing = deploys.missing_files(deploy, name)
    ready = (environment is None or environment.installed() is not None) and not missing
    return {"name": name, "what": "service", "installed": ready,
            "environment": str(environment.directory) if environment else "the harness's own",
            "environment_installed": environment is None or environment.installed() is not None,
            "missing_files": missing}


def install_service(deploy, name: str, *, log=print) -> dict:
    """Install service `name` unless it is installed: its environment (sources included),
    then its weights; then check that the files it needs are there."""
    if deploy.placement(name).mode == "external":
        return service_status(deploy, name)
    environment = environment_of(deploy, name)
    if environment is not None:
        environments.install(environment, log=log)
    if deploys.missing_files(deploy, name) or any(not path.exists() for path in deploys.weight_dirs(deploy, name)):
        for entry in deploy.services[name].weights:
            if not download(entry, Path(deploy.weights) / entry["dir"], label=name, log=log):
                raise RuntimeError(f"{name}: the weights in {entry['dir']} did not download")
    missing = deploys.missing_files(deploy, name)
    if missing:
        raise RuntimeError(f"{name}: installed, but these are still missing: {', '.join(missing)}")
    return service_status(deploy, name)


def install(deploy, names, *, log=print) -> list[dict]:
    """Install services by name (`harness install`; the core installs benchmarks)."""
    rows = []
    for name in names:
        if name not in deploy.services:
            raise ValueError(f"Nothing called {name!r} to install: services {sorted(deploy.services)}")
        rows.append(install_service(deploy, name, log=log))
    return rows


def services_used(agent) -> list[str]:
    """The services a resolved agent calls (its placement, without the dropped ones)."""
    names = []
    for value in agent.placement.values():
        if isinstance(value, dict) and "service" in value and not value.get("dropped"):
            names.append(value["service"])
        elif isinstance(value, dict) and "service" not in value:
            names += [name for name, entry in value.items() if not entry.get("dropped")]
    return sorted(set(names))
