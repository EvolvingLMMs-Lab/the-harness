#!/usr/bin/env python3
"""Grow a harness library on development seeds, then freeze it (paper Sec. 3.3).

    harness self-improve --experiment configs/experiments/dev.toml --deploy mine \
        --tasks stack_bowls,classify_objects --explore-seeds 0-3 --validate-seeds 10-13 \
        --library libraries/r4 --gpu 0 --output runs/self-improve

    harness self-improve --experiment configs/experiments/minecraft-practice.toml \
        --tasks s1,s3 --explore-seeds 0-1 --validate-seeds 100-101 \
        --library runs/mc-library --output runs/mc-self-improve --set agent.runtime.physical='{level = "allow"}'

A thin driver over the learner (runtime/learning/learner.py), the same one that learns in a run:
the explore seeds are active learning (the library learns in them: the model may propose
entries, each admitted on its own test, and reflection after each episode proposes one
more), and the validate seeds are the evidence that makes an entry validated. For each
task: run the explore seeds; for each explored episode, the reflection's candidate runs
on the validate seeds with and without it and is kept, validated, only if the mean score
rises by at least --min-gain; then every entry the runs admitted on its own tests (and
each one waiting in candidates/) is measured the same way, validated or taken out
(--no-promote leaves them). Any bench: its hooks start the task's worker (as
`harness run` does) where its slots are (RoboDojo: a GPU of the deploy's [sim] or
--gpu; Minecraft: this computer's game), and the reflection request is the one for
its embodiment, bench and skills (prompts/reflect). A seed is what the bench's
tasks take: a RoboDojo layout (development layouts by default, or an official
pack's when the experiment says `layouts = "eval"`: then evaluate the frozen
library on layouts it never saw), a Minecraft practice segment's world seed (the
tasks are segments, so explore and validate run world seed x segment). Explore and
validate seeds are disjoint from each other.

Explore episodes also add to the library's experience (runtime/learning/experience.py: skill
tallies and hints, kept without validation); validation reads it frozen, so a
candidate is compared on the same experience as its baseline. The final library
version is written to OUTPUT/library.json (the eval package's command).
"""

import argparse
from pathlib import Path
import json
import shutil
import sys
import time

from harness.sdk import ChatModel, Learner, Library, free_port
from harness_eval import suite as run_suite  # (worker start/stop helpers)
from harness_eval.experiments import load_experiment
from harness_eval.run import attach_library, load_task_config, run_program_episode


def log(output, message):
    run_suite.log(output, message)


# RoboDojo refuses an official layout that does not settle after reset; its own evaluation
# loop takes the next layout instead (as harness run does with spares).
UNSTABLE = "unstable after reset"


def run_seeds(config, seeds, directory, spares=(), restart=None):
    """{layout: score} of one episode per seed. A layout that does not settle is set aside
    (seed-<n>.unstable) and the next of `spares` runs in its place; with no spare left it
    scores None (left out of comparisons). An episode the worker fails before its first
    step (its simulator hung) runs once more on a restarted worker (`restart`), else scores
    None; other errors score 0."""
    scores, spares, retried = {}, iter(spares), {}
    for seed in seeds:
        while seed is not None:
            run = directory / f"seed-{seed}"
            summary = run_program_episode(config, seed, run)
            if summary["status"] == "error" and UNSTABLE in str(summary.get("error")):
                run.rename(directory / f"seed-{seed}.unstable-{int(time.time())}")
                scores[seed] = None
                seed = next(spares, None)
                continue
            if summary["status"] == "error" and not summary.get("steps"):
                # The worker failed before the first step (a reset that timed out): not the
                # agent's score. Run the layout once more, else leave it out.
                run.rename(directory / f"seed-{seed}.failed-{int(time.time())}")
                if retried.get(seed):
                    scores[seed] = None
                    break
                retried[seed] = True
                if restart is not None:
                    restart()
                continue
            scores[seed] = 0.0 if summary["status"] == "error" else float(summary["reward"] or 0.0)
            break
    return scores


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def paired_gain(baseline, scores):
    """Mean score rise over the layouts both runs scored."""
    common = [seed for seed in baseline if baseline[seed] is not None and scores.get(seed) is not None]
    return mean([scores[s] for s in common]) - mean([baseline[s] for s in common]), common


class Measure:
    """Validation on held-out development seeds: the evidence that makes an entry validated
    (runtime/learning/learner.py). The library's score without a change is measured once, again only
    after the library changed."""

    def __init__(self, base, library, validate, spares, directory, restart, min_gain):
        self.base, self.library, self.validate, self.spares = base, library, validate, spares
        self.directory, self.restart, self.min_gain = directory, restart, min_gain
        self.baseline = None

    def _baseline(self):
        if self.baseline is None:
            self.baseline = run_seeds(attach_library(self.base, self.library), self.validate,
                                      self.directory / f"validate-baseline-{Library(self.library).version()[:10]}",
                                      self.spares, self.restart)
        return self.baseline

    def _score(self, trial, label):
        """(gain, layouts, scores) of a trial library against the baseline, on the layouts
        the baseline settled on."""
        baseline = self._baseline()
        scores = run_seeds(attach_library(self.base, trial), [s for s, v in baseline.items() if v is not None],
                           self.directory / label, restart=self.restart)
        if getattr(self.base, "embodiment", "robot") != "robot":
            common = list(baseline)
            gain = mean([(scores.get(seed) or 0.0) - (baseline[seed] or 0.0) for seed in common])
            return gain, common, scores
        gain, common = paired_gain(baseline, scores)
        return gain, common, scores

    def candidate(self, learner, candidate) -> dict:
        """A reflection's candidate: admitted as validated when it raises the score."""
        if getattr(self.base, "embodiment", "robot") != "robot" and candidate.kind in ("skill", "reactive"):
            learner.admit(candidate, "proposed", pending=True, why="offline reflection")
            return {"gain": 0.0, "decision": "awaiting trusted verification"}
        trial = learner.trial(candidate, self.directory)
        try:
            gain, common, scores = self._score(trial, f"validate-{candidate.section}-{candidate.name}")
        finally:
            shutil.rmtree(trial, ignore_errors=True)
        accepted, baseline = gain >= self.min_gain, self.baseline
        if accepted:
            revision = candidate.revision()
            learner.admit(candidate, "validated", gain=gain, why="development seeds",
                          proof={"revision": revision.revision,
                                 "conditions": {"method": "development-seed-score", "layouts": common}})
            self.baseline = None  # the library changed; re-measure before the next candidate
        return {"baseline": baseline, "scores": scores, "layouts": common, "gain": gain,
                "decision": "accepted" if accepted else "rejected"}

    def entry(self, learner, row) -> dict:
        """An entry a run admitted on its own test (or one waiting): validated when the
        library scores better with it than without it, else taken out."""
        if getattr(self.base, "embodiment", "robot") != "robot" and row["section"] in ("skills", "reactive"):
            return self._verified_entry(learner, row)
        if row["waiting"]:
            candidate = learner.candidate_from(row["file"])
            outcome = self.candidate(learner, candidate)
            if outcome["decision"] == "rejected":
                learner.remove(row["file"], "no gain on development seeds")
            return outcome
        trial = learner.without(row["file"], self.directory)
        try:
            # The library with the entry is the baseline; the trial is without it.
            loss, common, scores = self._score(trial, f"validate-without-{row['section']}-{row['name']}")
        finally:
            shutil.rmtree(trial, ignore_errors=True)
        gain = -loss
        if gain >= self.min_gain:
            learner.grade(row["file"], "validated", gain=gain, why="development seeds")
            decision = "validated"
        else:
            learner.remove(row["file"], "no gain on development seeds")
            self.baseline = None
            decision = "removed"
        return {"gain": gain, "layouts": common, "scores_without": scores, "decision": decision}


    def _verified_entry(self, learner, row):
        key, revision, pending = row["file"], row["revision"], row["waiting"]
        if not row["verified"]:
            return {"gain": 0.0, "decision": "awaiting trusted verification"}
        candidate = learner.candidate_from(key, pending=pending)
        index_key = f"candidates/{key}" if pending else key
        proof = (learner.index().get(index_key) or {}).get("proof") or {}
        if candidate is None or candidate.revision().revision != revision or proof.get("revision") != revision:
            return {"gain": 0.0, "decision": "revision changed"}

        label = f"validate-{'with' if pending else 'without'}-{revision[:16]}"
        trial = learner.trial(candidate, self.directory, proof=proof) if pending else learner.without(key, self.directory)
        baseline_run = f"validate-baseline-{Library(self.library).version()[:10]}"
        try:
            delta, layouts, scores = self._score(trial, label)
        finally:
            shutil.rmtree(trial, ignore_errors=True)
        gain = delta if pending else -delta
        included, excluded = (label, baseline_run) if pending else (baseline_run, label)

        def activation(run, seed):
            path = self.directory / run / f"seed-{seed}" / "manifest.json"
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))["config"].get("active_library", {})

        pairs = [(activation(included, seed), activation(excluded, seed)) for seed in layouts]
        complete = pairs and all(
            with_item is not None and without is not None and with_item.get(key) == revision
            and without.get(key) != revision
            and {name: value for name, value in with_item.items() if name != key}
                == {name: value for name, value in without.items() if name != key}
            for with_item, without in pairs)
        evidence = {"gain": gain, "layouts": layouts, "baseline": self.baseline, "scores": scores,
                    "with_revision": included, "without_revision": excluded}
        accepted = (complete and gain > 0 and gain >= self.min_gain
                    and learner.grade_development(candidate, revision, pending=pending, score=evidence))
        if accepted:
            self.baseline = None
        return {**evidence, "decision": "validated" if accepted else "no verified improvement"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="harness self-improve", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment", required=True,
                        help="experiment file (configs/experiments/*.toml): the agent, its model, budgets")
    parser.add_argument("--deploy", help="deploy name or path (default $HARNESS_DEPLOY)")
    parser.add_argument("--set", dest="sets", action="append", default=[], help="experiment override key=value")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--explore-seeds", required=True)
    parser.add_argument("--validate-seeds", required=True)
    parser.add_argument("--explore-spares", default="", help="layouts that replace unstable explore layouts")
    parser.add_argument("--validate-spares", default="", help="layouts that replace unstable validate layouts")
    parser.add_argument("--library", required=True, help="library directory (created if missing)")
    parser.add_argument("--min-gain", type=float, default=0.05, help="required rise of the mean score")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--gpu", help="the worker's slot (default the bench's first: a GPU of the deploy's [sim])")
    parser.add_argument("--port", type=int, help="the worker's port (default the bench's, else 8795)")
    parser.add_argument("--no-promote", dest="promote", action="store_false",
                        help="leave the entries the runs admitted on their own tests (and those waiting) unvalidated")
    parser.add_argument("--no-experience", action="store_true",
                        help="explore episodes leave the library's experience as it is")
    parser.add_argument("--dev-layout-dir", help="development layouts (default the RoboDojo checkout's)")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    explore = run_suite.expand_seeds(args.explore_seeds)
    validate = run_suite.expand_seeds(args.validate_seeds)
    explore_spares = run_suite.expand_seeds(args.explore_spares) if args.explore_spares else []
    validate_spares = run_suite.expand_seeds(args.validate_spares) if args.validate_spares else []
    if set(explore + explore_spares) & set(validate + validate_spares):
        raise SystemExit("explore and validate seeds (and their spares) must be disjoint")
    output = Path(args.output).resolve()
    (output / "workers").mkdir(parents=True, exist_ok=True)
    # The one learner (runtime/learning/learner.py): this script only drives it on development seeds.
    learner = Learner(args.library, {"learn": "on", "trigger": "active"}, create=True)
    library = learner.directory
    experiment = load_experiment(args.experiment, deploy=args.deploy, sets=args.sets, tasks=args.tasks)
    # The bench's worker settings as `harness run` makes them: its options, its slots, the
    # run's physical-input policy, the interpreter of its environment (installed first).
    worker_args = run_suite.suite_arguments(experiment, gpus=[args.gpu] if args.gpu else None,
                                            prepared=run_suite.preflight(experiment))
    if args.dev_layout_dir:
        worker_args.dev_layout_dir = args.dev_layout_dir
    slot = worker_args.gpus.split(",")[0]
    port = args.port or free_port(worker_args.base_port)
    learn = "read" if args.no_experience else "learn"
    decisions = []
    for round_index in range(args.rounds):
        for task in run_suite.expand_tasks(args.tasks):
            base = load_task_config(args.experiment, task=task, seeds=explore, deploy=args.deploy, sets=args.sets)
            # What the reflection request says the agent is: its embodiment kind, the bench
            # and the skills it runs with (prompts/reflect).
            names = [base.embodiment, experiment.bench, *(base.runtime.get("skills") or [])]
            log(output, f"round {round_index} {task}: starting worker")
            worker = {"process": run_suite.start_worker(worker_args, task, slot, port, output)}

            def restart():
                log(output, f"{task}: worker failed an episode before its first step; restarting it")
                run_suite.stop_worker(worker["process"])
                worker["process"] = run_suite.start_worker(worker_args, task, slot, port, output)
            try:
                base.environment = {**base.environment, "endpoint": f"http://127.0.0.1:{port}"}
                reflection = ChatModel({**base.main, "temperature": 0.3})
                stamp = f"r{round_index}-{task}-{int(time.time())}"
                # Active learning: the explore episodes learn (the model may propose entries in
                # them, admitted on their own tests) and reflection after each proposes one more.
                current = attach_library(base, library, experience=learn, learn="on", trigger="active")
                explored = output / stamp / "explore"
                ran = run_seeds(current, explore, explored, explore_spares, restart)
                measure = Measure(base, library, validate, validate_spares, output / stamp, restart, args.min_gain)
                # Only episodes that ran are reflected on (an error before the first step
                # has nothing to learn from).
                for seed in [s for s, score in ran.items() if score is not None]:
                    run = explored / f"seed-{seed}"
                    if json.loads((run / "summary.json").read_text(encoding="utf-8")).get("steps", 0) == 0:
                        continue
                    candidate, raw = learner.reflect(reflection, run, names)
                    record = {"round": round_index, "task": task, "from_seed": seed, "candidate": None,
                              "reply": raw[-2000:]}
                    if candidate is None:
                        decisions.append(record)
                        continue
                    record["candidate"] = candidate.key
                    if (library / candidate.section / candidate.filename).exists():
                        record["decision"] = "duplicate name"
                        decisions.append(record)
                        continue
                    record.update(measure.candidate(learner, candidate))
                    decisions.append(record)
                    log(output, f"{task} seed {seed}: {candidate.key} gain {record['gain']:+.3f} -> {record['decision']}")
                if args.promote:
                    # The entries the runs admitted on their own tests, and those waiting: the
                    # development seeds validate them, or they go.
                    for row in [row for row in learner.entries() if row["evidence"] != "validated"]:
                        record = {"round": round_index, "task": task, "entry": row["file"], **measure.entry(learner, row)}
                        decisions.append(record)
                        log(output, f"{task}: {row['file']} ({row['evidence']}) gain {record['gain']:+.3f} -> "
                                    f"{record['decision']}")
            finally:
                run_suite.stop_worker(worker["process"])
            (output / "decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    manifest = Library(library).manifest()
    (output / "library.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(output, f"frozen library version {manifest['version'][:12]} with {sum(len(v) for v in manifest['entries'].values())} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
