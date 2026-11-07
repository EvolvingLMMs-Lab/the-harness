"""Benches: the environments an agent's worker serves, as their bench.toml describes them.

A bench is a package's `benches/<name>/` with

    bench.toml      name, summary, the embodiment kind its worker drives, the worker's
                    factory and the [worker] keys it takes, its [environment] and [sandbox]
    bench.py        its hooks (BENCH_KEYS `hooks`, a subclass of the eval package's Bench)

The core reads what starts a worker (bench_specs): the computer's workspaces start a
bench's worker from it, the session host knows a bench's embodiment kind from it, active
learning its sandbox, `harness install` its environment. Running a bench as a benchmark
(its tasks, the keys of a deploy's [benches.<name>] table, its checkout and assets) is the
eval package's: those keys of bench.toml stay in BenchSpec.benchmark, which the eval
package reads and checks (harness_eval/bench.py), with the hooks.

Adding a bench touches none of the code that reads it. A bench's hooks import only the standard library and their own package's light modules at import;
the simulator, the VM and the benchmark's code stay in the worker process.
"""

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from .embodiments import KINDS


# The keys of benches/<name>/bench.toml the core reads; the others are the eval package's
# (harness_eval/bench.py BENCHMARK_KEYS).
BENCH_KEYS = {
    "name": "the bench's name, the same as its directory (an experiment's `bench`)",
    "summary": "one line: what the bench is",
    "kind": "the embodiment kind its worker drives (embodiments.KINDS)",
    "embodiment": "embodiments/<name> for observation contracts (optional: then only the native contract)",
    "factory": "the worker's environment factory, \"module:callable\" (`python -m harness.core.worker --factory`)",
    "hooks": "the Bench subclass with its hooks, \"module:Class\" (default Bench)",
    "worker": "the experiment [worker] keys it takes: {key = \"what it does\"}",
    "environment": "the environment of its workers and of the kernel, installed on first use ([environment] keys)",
    "notes": "anything an operator should know",
    "sandbox": "the practice sandbox of an active run of learning (runtime/learning/active.py), never of a task run: `what` "
               "(what it is, for the model) and [sandbox.ops] {op = \"what it stages\"}; without ops there is none "
               "(`what` says why)",
}


@dataclass(frozen=True)
class BenchSpec:
    """A bench as its bench.toml declares it (BENCH_KEYS); `path` is its directory."""

    name: str
    summary: str
    kind: str
    factory: str
    embodiment: str | None = None
    hooks: str | None = None
    worker: dict = field(default_factory=dict)
    environment: dict | None = None
    notes: str = ""
    # The practice sandbox of an active run: {"what", "ops": {op: what it stages}}.
    sandbox: dict = field(default_factory=dict)
    # The rest of bench.toml: running it as a benchmark, the eval package's to read and check.
    benchmark: dict = field(default_factory=dict)
    path: Path = field(default=None, compare=False)


def _spec(directory: Path) -> BenchSpec:
    data = tomllib.loads((directory / "bench.toml").read_text(encoding="utf-8"))
    missing = {"name", "summary", "kind", "factory"} - set(data)
    if missing:
        raise ValueError(f"{directory}/bench.toml: missing {sorted(missing)}")
    if data["name"] != directory.name:
        raise ValueError(f"{directory}/bench.toml: name {data['name']!r} is not its directory's")
    if data["kind"] not in KINDS:
        raise ValueError(f"{directory}/bench.toml: kind must be one of {sorted(KINDS)}")
    if not all(isinstance(text, str) for text in data.get("worker", {}).values()):
        raise ValueError(f"{directory}/bench.toml: [worker] maps each key to what it does")
    sandbox = data.get("sandbox", {})
    if (not isinstance(sandbox, dict) or set(sandbox) - {"what", "ops"} or not isinstance(sandbox.get("what", ""), str)
            or not all(isinstance(text, str) for text in sandbox.get("ops", {}).values())):
        raise ValueError(f"{directory}/bench.toml: [sandbox] is what (a text) and ops {{op = \"what it stages\"}}")
    if "environment" in data:
        from .packages.environments import validate

        validate(data["environment"], f"{directory}/bench.toml")
    own = {key: value for key, value in data.items() if key in BENCH_KEYS}
    return BenchSpec(**own, benchmark={key: value for key, value in data.items() if key not in BENCH_KEYS},
                     path=directory)


def bench_dirs() -> dict[str, Path]:
    """Every bench's directory by name: benches/<name>/ of ROOT and of each package
    (paths.roots), the first one of a name winning."""
    from .paths import find

    found = {}
    for folder in find("benches"):
        for path in sorted(folder.glob("*/bench.toml")):
            found.setdefault(path.parent.name, path.parent)
    return found


def bench_names() -> list[str]:
    """The benches of the core and of its packages (benches/<name>/bench.toml)."""
    return sorted(bench_dirs())


def bench_spec(name: str) -> BenchSpec:
    """The bench `name`'s bench.toml; ValueError for a bench no package has."""
    if name not in bench_names():
        raise ValueError(f"Unknown bench {name!r}; benches are {bench_names()}")
    return _spec(bench_dirs()[name])


def bench_specs() -> dict[str, BenchSpec]:
    """Every bench's bench.toml by name, without importing its hooks."""
    return {name: _spec(directory) for name, directory in sorted(bench_dirs().items())}


def declares_channels(spec: BenchSpec) -> bool:
    """Whether a bench's embodiment declares channels (embodiment.toml [channels])."""
    if not spec.embodiment:
        return False
    from .embodiments import load_embodiment

    return bool(load_embodiment(spec.embodiment).get("channels"))
