"""Before a suite's first episode (or a conversation's on a bench's worker): install the
services its agent calls on this machine (the local-models package) and its benchmark,
when they are not yet. A benchmark is its bench's environment (the core's) and, for one
with an official checkout, that checkout at the pinned commits and its assets; `harness
checkout NAMES` installs them ahead of time."""

from pathlib import Path

from harness.sdk import bench_environment, bench_environment_status, bench_spec, environments, install_bench_environment
from harness_eval.bench import benchmark, load_bench
from harness_local_models import deploy as deploys
from harness_local_models.provision import install_service, service_status, services_used


def bench_checkout(deploy, name: str) -> Path | None:
    """Where benchmark `name`'s checkout is (or will be) on this deploy; None for a bench
    that names none (its deploy table says where it runs)."""
    bench = benchmark(bench_spec(name))
    if not bench.source:
        return None
    return environments.source({"source": bench.source, "nested": list(bench.nested)}, deploy).path


def _missing(paths, variables) -> list[str]:
    return [path for path in environments._render(list(paths), variables) if not Path(path).exists()]


def bench_status(deploy, name: str) -> dict:
    """Whether benchmark `name` is installed here: its checkout, assets and environment."""
    checkout = bench_checkout(deploy, name)
    environment = bench_environment_status(deploy, name)
    if checkout is None:
        return {**environment, "what": "benchmark", "environment_installed": environment["installed"],
                "missing_files": []}
    missing = _missing(benchmark(bench_spec(name)).needs_files, {"checkout": str(checkout)})
    return {"name": name, "what": "benchmark", "installed": environment["installed"] and not missing,
            "checkout": str(checkout), "environment": environment["environment"],
            "environment_installed": environment["installed"], "missing_files": missing}


def install_bench(deploy, name: str, *, log=print) -> dict:
    """Install benchmark `name` unless it is installed: its checkout at the pinned commits,
    its assets, its environment."""
    bench = benchmark(bench_spec(name))
    checkout = bench_checkout(deploy, name)
    if checkout is None:
        install_bench_environment(deploy, name, log=log)
        return bench_status(deploy, name)
    if environments.mode(deploy) == "own":
        item = environments.source({"source": bench.source, "nested": list(bench.nested)}, deploy)
        logs = environments.home() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / f"install-{name}.log", "a", encoding="utf-8") as out:
            environments.checkout(item, out)
    if _missing(bench.needs_files, {"checkout": str(checkout)}):
        for entry in bench.assets:
            if not _download(entry, (checkout / entry["dir"]).resolve(), label=name, log=log):
                raise RuntimeError(f"{name}: the assets in {entry['dir']} did not download")
    install_bench_environment(deploy, name, log=log)
    load_bench(name).prepare_checkout(Path(checkout), log=log)
    missing = _missing(bench.needs_files, {"checkout": str(checkout)})
    if missing:
        raise RuntimeError(f"{name}: installed, but these are still missing: {', '.join(missing)}")
    return bench_status(deploy, name)


def _download(entry: dict, dest: Path, *, label: str, log=print) -> bool:
    """A benchmark's [[assets]] entry, downloaded as a service's weights are (ModelScope,
    Hugging Face)."""
    from harness_local_models.tools import download

    return download(entry, dest, label=label, log=log)


def prepare(run, *, log=print) -> dict:
    """Before a run's first episode: install the services its agent calls on this machine
    and its benchmark, when they are not yet; returns the interpreter of the benchmark's
    worker and kernel, its checkout and the environment variables of its environment."""
    deploy = run.deploy
    for name in services_used(run.agent):
        if deploy.placement(name).mode in deploys.LOCAL and not service_status(deploy, name)["installed"]:
            install_service(deploy, name, log=log)
    if not bench_status(deploy, run.bench)["installed"]:
        install_bench(deploy, run.bench, log=log)
    environment = bench_environment(deploy, run.bench)
    checkout = bench_checkout(deploy, run.bench)
    if checkout is not None:
        load_bench(run.bench).prepare_checkout(Path(checkout), log=log)
    return {"python": str(environment.python) if environment else None,
            "checkout": str(checkout) if checkout else None,
            # The variables its environment sets (the simulator's EULA), for its workers too.
            "env": environments._render(environment.spec.get("env", {}), environment.variables())
            if environment else {}}
