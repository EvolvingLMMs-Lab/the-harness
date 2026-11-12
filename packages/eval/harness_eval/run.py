"""Episodes of a task: one (run_program_episode, a conversation nobody talks to), every
seed of a task against a worker that runs (run_task, `harness program`), and the
configuration of an experiment file for one task (load_task_config). A library attached
to a task's configuration (attach_library) is what self-improvement compares runs with.
"""

from pathlib import Path

from harness.sdk import TaskConfig, resolve_skills, run_name, write_json


def attach_library(config: "TaskConfig", directory, layers=("notes", "skills", "reactive"), experience="read",
                   **learning):
    """Return a copy of `config` that uses the library at `directory` (frozen at its
    current version, unless `learning` says it learns: runtime/learning/learner.py SETTINGS) on top
    of the harness prompt without any library. The legacy experience option controls whether
    the run records uses of its active revisions."""
    from copy import deepcopy

    from harness.sdk import SECTIONS, Library, learning_settings as settings

    chosen = settings(learning)
    if chosen["learn"] == "on":
        for section in SECTIONS:
            (Path(directory) / section).mkdir(parents=True, exist_ok=True)
    library = Library(directory, layers, chosen["load"])
    captured = library.capture()
    updated = deepcopy(config)
    updated.runtime["library"] = {"path": str(library.directory), "layers": list(layers),
                                  "manifest": captured.manifest(), "experience": experience,
                                  **{key: value for key, value in learning.items() if value is not None}}
    roles = {"main": config.main, "verifier": config.verifier}
    reactive = "reactive" in resolve_skills(updated.runtime, roles, config.embodiment).enabled
    selected = {item.key for item in captured.entries if item.key.startswith("skills/")
                or reactive and item.key.startswith("reactive/")}
    updated.system_prompt = config.base_prompt + captured.api_summary(selected) + captured.notes()
    return updated


def load_task_config(path, *, task=None, seeds=None, model=None, deploy=None, sets=()) -> TaskConfig:
    """The driver's configuration of an experiment file (configs/experiments/*.toml) for
    one task: `task` (default: the experiment's first), `seeds`, `model` (a model file's
    name or path, configs/models/), `deploy` and --set items override the file."""
    from harness_eval.experiments import load_experiment

    experiment = load_experiment(path, deploy=deploy, sets=sets, tasks=[task] if task else None,
                                 seeds=list(seeds) if seeds is not None else None, model=model)
    return experiment.task_config(task, seeds)


def run_program_episode(config: TaskConfig, seed: int, directory: Path, *,
                        chat=None, verifier=None, environment=None) -> dict:
    """Run one episode of `config.task` with `seed` and return its summary (status,
    evaluator outcome, model calls, tokens, cost, times), also written with the trace and
    manifest under `directory`. `chat`, `verifier` and `environment` replace the configured
    models and worker. An error ends the episode with status "error" instead of raising.
    The episode is a conversation nobody talks to (runtime/task/run.py)."""
    from harness.sdk import TaskRun

    return TaskRun(config, seed, directory, chat=chat, verifier=verifier, environment=environment).run()


def continue_program_episode(config: TaskConfig, directory: Path, message: str, *,
                             chat=None, verifier=None, environment=None) -> dict:
    """One more turn of the episode kept in `directory`, started by `message`: the same
    directory, trace and session, its messages and facts, a new kernel, the worker that
    runs now. Returns its summary. (As a conversation is continued: runtime/task/run.py.)"""
    from harness.sdk import TaskRun, saved_conversation

    kept = saved_conversation(directory)
    if kept is None:
        raise ValueError(f"{directory} kept no conversation to continue")
    seed = (kept.get("summary") or {}).get("seed", config.seeds[0])
    run = TaskRun(config, seed, Path(directory), chat=chat, verifier=verifier, environment=environment, restore=kept)
    run.send_message(message)
    return run.run()


def run_task(config: TaskConfig, output: Path, *, script: list | dict | None = None) -> dict:
    """Run every seed. With `script` (a list of replies, or {"replies", "verifier"}),
    replies are replayed and no model is called."""
    from harness.sdk import scripted_models

    directory = output.resolve() / run_name()
    directory.mkdir(parents=True)
    episodes = []
    result = {"experiment": str(directory), "kind": "program", "config": config.snapshot(), "episodes": episodes}
    try:
        for seed in config.seeds:
            scripted = {} if script is None else scripted_models(script)
            episodes.append(run_program_episode(config, seed, directory / f"seed-{seed}", **scripted))
            write_json(directory / "experiment.json", result)
    finally:
        # Over the scored episodes: a worker without an evaluator (this computer, a game the
        # user judges) reports no success.
        scored = [bool(item["success"]) for item in episodes if item.get("success") is not None]
        result["success_rate"] = sum(scored) / len(scored) if scored else None
        result["completed_cases"] = len(episodes)
        result["planned_cases"] = len(config.seeds)
        write_json(directory / "experiment.json", result)
    return result
