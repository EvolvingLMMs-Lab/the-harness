"""Install on first use: the environment of a bench's worker and kernel when a run needs it
and this machine does not have it yet. Services (their environments and weights) are the
local-models package's (harness_local_models/provision.py); a benchmark's checkout and
assets are the eval package's (harness_eval/provision.py, `harness checkout`).

`harness install NAMES` installs a bench's environment ahead of time.

    harness install sam3 simate robodojo
"""

from . import environments
from ..bench import bench_specs


def bench_environment(deploy, name: str):
    """The environment of bench `name`'s worker and kernel on this deploy, or None
    (environments = "project", or it has none)."""
    bench = bench_specs()[name]
    if bench.environment is None or environments.mode(deploy) == "project":
        return None
    return environments.resolve(name, bench.environment, deploy)


def bench_environment_status(deploy, name: str) -> dict:
    """Whether bench `name`'s environment is installed here."""
    environment = bench_environment(deploy, name)
    if environment is None:
        return {"name": name, "what": "bench", "installed": True, "environment": "the harness's own"}
    ready = environment.installed() is not None
    return {"name": name, "what": "bench", "installed": ready, "environment": str(environment.directory)}


def install_bench_environment(deploy, name: str, *, log=print) -> dict:
    """Install bench `name`'s environment unless it is installed."""
    environment = bench_environment(deploy, name)
    if environment is not None:
        environments.install(environment, log=log)
    return bench_environment_status(deploy, name)
