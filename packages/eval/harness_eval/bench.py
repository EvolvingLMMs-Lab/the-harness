"""A bench run as a benchmark: the keys of its bench.toml that only a benchmark run reads
(BENCHMARK_KEYS: its tasks, the keys of a deploy's [benches.<name>] table, its checkout and
assets), and its hooks (its bench.toml `hooks`, a subclass of Bench): how an experiment's
tasks expand, a task's worker's options and process, the suite's slots, preparing the
checkout, the compliance audit, and the check of the deploy's [benches.<name>] table. The
core reads only what starts a bench's worker (harness/bench.py); these run where benches
run over tasks and seeds (suite.py, experiments.py)."""

from dataclasses import dataclass, field
import importlib
import os
from pathlib import Path
import sys

from harness.sdk import BenchSpec, bench_names, bench_spec, environments, roots

# The keys of benches/<name>/bench.toml a benchmark run reads (the core's are BENCH_KEYS).
BENCHMARK_KEYS = {
    "tasks": "what an experiment's `tasks` items may be, in words (the documentation)",
    "deploy": "the keys of a deploy's [benches.<name>] table: {key = \"what it is\"}",
    "source": "its checkout, installed on first use: a source of third_party/sources.toml (a deploy's robodojo, "
              "or $HARNESS_<NAME>_ROOT, puts one of your own in its place)",
    "nested": "the nested checkouts of the source it needs",
    "assets": "[[assets]] entries as a service's [[weights]], with dir below the checkout: downloaded on install",
    "needs_files": "paths that must exist once it is installed ({checkout}/...)",
}


@dataclass(frozen=True)
class Benchmark:
    """What running a bench as a benchmark takes (BENCHMARK_KEYS of its bench.toml)."""

    tasks: str = ""
    deploy: dict = field(default_factory=dict)
    # Installed on first use (provision.py): the checkout and its assets.
    source: str | None = None
    nested: tuple = ()
    assets: tuple = ()
    needs_files: tuple = ()


def benchmark(spec: BenchSpec) -> Benchmark:
    """The benchmark keys of `spec`'s bench.toml, checked."""
    where = f"{spec.path}/bench.toml"
    data = spec.benchmark
    unknown = set(data) - set(BENCHMARK_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    if not all(isinstance(text, str) for text in data.get("deploy", {}).values()):
        raise ValueError(f"{where}: [deploy] maps each key to what it is")
    if "source" in data and data["source"] not in environments.shared_sources():
        raise ValueError(f"{where}: source must name a source of third_party/sources.toml")
    return Benchmark(tasks=data.get("tasks", ""), deploy=dict(data.get("deploy", {})), source=data.get("source"),
                     nested=tuple(data.get("nested", ())), needs_files=tuple(data.get("needs_files", ())),
                     assets=tuple(dict(entry) for entry in data.get("assets", [])))


class Bench:
    """A bench's hooks; each default suits a simulator worker that serves one task on one
    GPU of the deploy's [sim] section. `args` is the suite's settings (the eval package's
    suite_arguments): the experiment's tasks, seeds, layouts and [worker] table (`worker`),
    the deploy's [benches.<name>] table (`bench_deploy`) and the command line's."""

    def __init__(self, spec: BenchSpec):
        self.spec = spec
        self.benchmark = benchmark(spec)

    def expand_tasks(self, items: list[str], layouts: str, deploy: dict) -> list[str]:
        """The task names of an experiment's `tasks` items (stripped, non-empty), in order;
        repeats are removed by the caller. `deploy` is the deploy's [benches.<name>] table
        (its checkout, where the bench has one)."""
        return list(items)

    def worker_options(self, args, task: str, directory: Path, slot) -> dict:
        """The keyword arguments of the worker's factory for `task` (written to
        `<directory>/worker-<task>.toml`). `slot` is what slots() named."""
        return {"task": task, **{key: value for key, value in args.worker.items() if key in self.spec.worker}}

    def worker_process(self, args, slot, env: dict) -> str:
        """The interpreter that runs the worker; `env` (a copy of this process's
        environment with CUDA_VISIBLE_DEVICES set to the slot, PYTHONUNBUFFERED, a TMPDIR of
        its own and the harness on PYTHONPATH) may be changed in place. Default: the
        interpreter of the bench's environment, when the harness installed it
        (`args.python`), else the harness's own."""
        return getattr(args, "python", None) or sys.executable

    def active_task(self, task: str) -> str:
        """The task an active run of learning plays for `task` (runtime/learning/active.py): the same
        environment without a time limit of the task's own, where the task has one. Default:
        the task itself, or, where the bench has a practice sandbox, the task with
        active.LEARN: the worker allows the sandbox in that episode and in no other."""
        from harness.sdk import active

        return task + active.LEARN if (self.spec.sandbox or {}).get("ops") else task

    def slots(self, args) -> list | None:
        """The suite's slots, one worker each: None for the GPUs of the deploy's [sim]
        section (or --gpus) times workers_per_gpu."""
        return None

    def workspace_slots(self, args, count: int) -> list:
        """The suite's slots for `harness run --workspaces N`: N workspaces on this machine
        (background browsers, isolated displays or VMs), one worker each. Default: none,
        the bench's workers run on simulator GPUs."""
        raise ValueError(f"bench {self.spec.name} runs its workers on simulator GPUs: give --gpus and "
                         "--workers-per-gpu, not --workspaces")

    def base_port(self, args) -> int | None:
        """The first worker port when the deploy's [sim] does not give one."""
        return None

    def where(self, slot) -> str:
        """The slot in the suite's log."""
        return f"GPU {slot}"

    def prepare_checkout(self, checkout: Path, log=print) -> None:
        """Make the bench's checkout ready to run, after its install and before every run;
        it must do nothing when the checkout is ready. Default: nothing."""
        return None

    def spare_layouts(self, args, task: str):
        """Whether a layout that does not settle is replaced by the next one (RoboDojo's
        evaluation loop), and how many layouts the task has (None: unknown)."""
        return False, None

    def audit(self, episode: Path, options: dict, deploy, log=print) -> int:
        """`harness audit-run`: check an episode against the benchmark's rules, write its
        report and return the exit status (0: it passed). `options` are the command line's
        (recording, out, legal_builds, ledger, instance, game_region, fps, json). Default:
        the bench has no rules to audit against."""
        raise ValueError(f"bench {self.spec.name} has no compliance audit")

    def check_deploy(self, table: dict, resolve) -> dict:
        """The deploy's [benches.<name>] table, validated against the manifest's `deploy`
        keys; `resolve(path)` makes a path absolute against the deploy file."""
        unknown = set(table) - set(self.benchmark.deploy)
        if unknown:
            raise ValueError(f"[benches.{self.spec.name}] takes {sorted(self.benchmark.deploy)}, not {sorted(unknown)}")
        return dict(table)


_LOADED = {}


def load_bench(name: str) -> Bench:
    """The bench `name` with its hooks (cached)."""
    if name not in _LOADED:
        if name not in bench_names():
            raise ValueError(f"Unknown bench {name!r}; benches are {bench_names()}")
        spec = bench_spec(name)
        cls = Bench
        if spec.hooks:
            module, _, attribute = spec.hooks.partition(":")
            for root in reversed(roots()):
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
            cls = getattr(importlib.import_module(module), attribute)
            if not (isinstance(cls, type) and issubclass(cls, Bench)):
                raise ValueError(f"benches/{name}: hooks {spec.hooks} is not a Bench subclass")
        _LOADED[name] = cls(spec)
    return _LOADED[name]


def bench_table(deploy, name: str) -> dict:
    """The deploy's [benches.<name>] table as the bench takes it (its check_deploy), its
    paths resolved against the deploy file's directory (the local-models package keeps the
    table as it is)."""
    table = dict((getattr(deploy, "benches", None) or {}).get(name, {}))
    path = getattr(deploy, "path", None)
    base = Path(path).resolve().parent if path else Path.cwd()

    def resolve(value):
        found = Path(os.path.expandvars(os.path.expanduser(str(value))))
        return str(found if found.is_absolute() else (base / found).resolve())

    return load_bench(name).check_deploy(table, resolve)

