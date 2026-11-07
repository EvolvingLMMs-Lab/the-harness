"""Experiments: the agent with a model on a benchmark, as configs/experiments/<name>.toml
describes it.

    agent = "../my-agent.toml"              optional: the agent file (default configs/default.toml)
    model = "grok-low"                      optional: configs/models/<name>.toml (default the agent's)
    bench = "robodojo"                      a bench of benches/<name>/bench.toml
    tasks = ["general_pickup"]              as the bench takes them (its bench.toml `tasks`)
    seeds = [0]
    layouts = "procedural"                  procedural (development) | eval
    layout_pack_seed = 0                    eval: which official pack
    deploy = "mine"                         optional; else --deploy or $HARNESS_DEPLOY
    strict = true                           default: true for eval layouts
    endpoint = "http://127.0.0.1:8771"      `harness program`: a worker that already runs

    [budget]                                per episode, and for the whole suite
    max_wall_seconds = 5400
    max_cost_usd = 4.0
    max_total_cost_usd = 20.0

    [worker]                                options of the bench's worker (its bench.toml `worker`)
    record_video = false

    [overrides.agent]                       changes to the agent for this experiment
    runtime.keep_images = 1
    [overrides.model]                       changes to the model roles
    main.reasoning_effort = "low"

`--set key.path=value` writes into this tree; `--set agent.a.b=v` and
`--set model.a.b=v` go to the overrides, `--set model=NAME` (or `--model NAME`)
picks the model file.
"""

from dataclasses import dataclass, field
from pathlib import Path

from harness.sdk import (ResolvedAgent, apply_sets, bench_names, bench_spec, declares_channels, load_deploy,
                         load_layered, overridden_agent, parse_set, task_config)


LAYOUTS = ("procedural", "eval")
EXPERIMENT_KEYS = {
    "description": "one line",
    "agent": "the agent file, or a profile's name (configs/profiles/<name>.toml; default configs/default.toml)",
    "model": "the model roles: a name of configs/models/ (default the agent's)",
    "bench": "a bench of benches/<name>/bench.toml (default robodojo)",
    "tasks": "the bench's tasks, as its bench.toml `tasks` says (RoboDojo: names, dimension names, \"moving\", \"all\")",
    "seeds": "a list, or a range such as \"0-49\" (default [0])",
    "layouts": f"one of {', '.join(LAYOUTS)}: development or official evaluation layouts",
    "layout_pack_seed": "eval layouts: which official pack (0, 1, 2)",
    "dev_layout_dir": "development layouts' directory (default <RoboDojo>/harness_dev_layouts/arx_x5)",
    "deploy": "the deploy to resolve against (else --deploy or $HARNESS_DEPLOY)",
    "strict": "fail instead of dropping a skill or service (default: true for eval layouts)",
    "endpoint": "`harness program`: a worker that already runs",
    "timeout_seconds": "worker request timeout (default 600)",
    "budget": "max_wall_seconds, max_cost_usd, max_model_calls per episode; max_total_cost_usd per suite",
    "worker": "options of the bench's worker: the keys of its bench.toml [worker]",
    "suite": "options of `harness run` (boot_timeout, ...)",
    "overrides": "[overrides.agent] and [overrides.model]: changes for this experiment only",
}
# Keys that make a file an experiment rather than an agent file.
EXPERIMENT_ONLY = ("agent", "bench", "tasks", "seeds", "layouts", "layout_pack_seed", "endpoint")


def is_experiment(tree: dict) -> bool:
    """Whether a loaded file is an experiment (it names a bench, tasks, seeds, layouts or
    an agent) rather than an agent file."""
    return bool(set(tree) & set(EXPERIMENT_ONLY))


@dataclass
class Experiment:
    """A loaded experiment: its tree (with --set items applied), the agent resolved
    against the deploy, the expanded tasks and seeds, and the experiment's budget,
    worker and suite options. `task_config` gives the driver's configuration for one
    task."""

    path: Path | None
    tree: dict
    agent: ResolvedAgent
    deploy: object
    bench: str
    tasks: list[str]
    seeds: list[int]
    layouts: str
    layout_pack_seed: int
    strict: bool
    budget: dict = field(default_factory=dict)
    worker: dict = field(default_factory=dict)
    suite: dict = field(default_factory=dict)
    endpoint: str | None = None
    timeout_seconds: float = 600.0

    def task_config(self, task: str | None = None, seeds=None, endpoint: str | None = None):
        """The driver's configuration for one task (default: the experiment's first)."""
        return task_config(self.agent, task or self.tasks[0], seeds if seeds is not None else self.seeds,
                           budget=self.budget, endpoint=endpoint or self.endpoint,
                           timeout_seconds=self.timeout_seconds, path=self.path)


def _sets(sets):
    """--set items, with agent.* and model.* moved under overrides (model=NAME stays: it
    picks the model file)."""
    out = []
    for item in sets or ():
        keys, value = parse_set(item) if isinstance(item, str) else item
        if keys and keys[0] in ("agent", "model") and len(keys) > 1:
            keys = ["overrides", *keys]
        out.append((keys, value))
    return out


def load_experiment(path=None, *, tree: dict | None = None, deploy=None, sets=(), tasks=None, seeds=None,
                    strict: bool | None = None, model=None, frozen_identity: bool | None = None) -> Experiment:
    """An experiment file (or tree; neither: an empty experiment, the default agent on
    RoboDojo's development layouts) with --set items applied, its agent resolved against
    the deploy (argument, the file's `deploy`, or $HARNESS_DEPLOY). `model` (a model
    name or file) replaces the experiment's. Scoring keeps the frozen identity schema."""
    if tree is None:
        if path is not None:
            from harness.sdk import locate

            path = locate(Path(path)).resolve()
            tree = load_layered(path)
        else:
            tree = {}
    tree = apply_sets(tree, _sets(sets))
    if model is not None:
        tree["model"] = str(model)
    unknown = set(tree) - set(EXPERIMENT_KEYS)
    if unknown:
        raise ValueError(f"Experiment {path}: unknown keys {sorted(unknown)}")
    bench = tree.get("bench", "robodojo")
    if bench not in bench_names():
        raise ValueError(f"bench must be one of {bench_names()}")
    spec = bench_spec(bench)
    unknown = set(tree.get("worker", {})) - set(spec.worker)
    if unknown:
        raise ValueError(f"Experiment {path}: the {bench} worker takes {sorted(spec.worker)}, not {sorted(unknown)}")
    layouts = tree.get("layouts", "procedural")
    if layouts not in LAYOUTS:
        raise ValueError(f"layouts must be one of {LAYOUTS}")
    if tasks is not None:
        tree["tasks"] = tasks
    if seeds is not None:
        tree["seeds"] = seeds
    if not tree.get("tasks"):
        raise ValueError(f"Experiment {path or '(none)'}: names no tasks (give --tasks)")
    from harness_eval.suite import expand_seeds, expand_tasks

    deploy = deploy if deploy is not None and not isinstance(deploy, (str, Path)) else load_deploy(
        deploy or tree.get("deploy"))
    task_list = tree["tasks"]
    task_list = expand_tasks(task_list if isinstance(task_list, str) else ",".join(task_list), bench, layouts,
                             deploy)
    seed_list = tree.get("seeds", [0])
    seed_list = expand_seeds(seed_list) if isinstance(seed_list, str) else [int(seed) for seed in seed_list]
    strict = (layouts == "eval") if strict is None and tree.get("strict") is None else (
        strict if strict is not None else bool(tree["strict"]))
    overrides = tree.get("overrides", {})
    unknown = set(overrides) - {"agent", "model"}
    if unknown:
        raise ValueError(f"Experiment {path}: overrides are [overrides.agent] and [overrides.model], "
                         f"not {sorted(unknown)}")
    agent = overridden_agent(overrides, agent=tree.get("agent"), model=tree.get("model"), deploy=deploy,
                             strict=strict, embodiment=spec.kind, channels=declares_channels(spec),
                             package_paths=[spec.path],
                             frozen_identity=spec.kind == "robot" if frozen_identity is None else frozen_identity)
    return Experiment(path=path, tree=tree, agent=agent, deploy=agent.deploy, bench=bench, tasks=task_list,
                      seeds=seed_list, layouts=layouts, layout_pack_seed=int(tree.get("layout_pack_seed", 0)),
                      strict=strict, budget=dict(tree.get("budget", {})), worker=dict(tree.get("worker", {})),
                      suite=dict(tree.get("suite", {})), endpoint=tree.get("endpoint"),
                      timeout_seconds=float(tree.get("timeout_seconds", 600)))
