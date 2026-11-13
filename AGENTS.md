# Development conventions

## One agent

- There is one agent: `configs/default.toml` with the code it runs. A result identifies it
  by its lock (the hash of the agent and every component) and the git commit, which every
  result records; `harness.__version__` names a release, not a change.
- A pull request changes no version and no changelog. A change people would notice comes
  with a change note in `changes/` (`private/changes/` for private packages), `minor` for a
  change in what the agent does (prompt, skills, defaults, high-level loop) or a new
  capability, `patch` for a fix, with the evidence in the pull request; an internal change
  adds a note with an empty header. `changes/README.md` describes notes; a release
  (`python tools/release.py prepare`, a pull request titled "Release X.Y.Z") turns them into
  versions and changelogs. `python tools/release.py check-pr --base origin/main` checks this.
- No named harnesses. Code, configs and directories carry no harness or iteration names
  (z1, z2, r4, v03, ...). A variant is an ablation (`configs/ablations/<what it changes>.toml`,
  including `../default.toml`) or an experiment override, never a copy. A retired harness
  goes to an archive tag or branch (`archive/pre-default-agent`, `archive/z2`,
  `archive/step-loop`), not into main.
- Capabilities are plugins: a skill package (`skills/<name>/`: `skill.toml` + code), a
  service manifest (`services/<name>.toml`, what the model is told about it in
  `client.description`), a prompt pack section. A skill's calls are bounded executions
  that end with an event; it keeps no state across episodes (experience goes through the
  library, frozen for evaluation).

## Configuration

- Layers, later ones winning: code defaults < `configs/default.toml` < `configs/models/<name>.toml`
  (`--model`) < `configs/experiments/<name>.toml` < `--agent`, `--set`. Where services run
  is the deploy's (`configs/deploy/`). Keys live in environment variables, never in files.
- A configuration key the code reads is documented in the dictionary next to its validator.
- Every result records the lock and identity (agent version, prompt, skills, models,
  services, runtime), the git commit and whether the tree was dirty.

## Evidence

- The agent sees what the evaluator hands a policy (`runtime.contract`); more is a
  development diagnostic or a separately reported setting.
- Develop on development layouts and evaluation layouts alike; a run on evaluation
  layouts measures one frozen configuration (`layouts = "eval"` resolves strictly).
  Compare the agent with the learned policy it wraps on the same layouts.
- One hypothesis per change. A change enters the default when development runs show it
  beats the noise: paired comparisons (same tasks, seeds, budget, model), the spread of a
  repeated run next to the difference, calls and cost per episode next to the score.
  Failed cases stay in the denominator.
- The paper is a reference, not a specification: when results contradict it, change the
  code, then the paper text, and keep `docs/src/content/docs/concepts/method-conformance.md` true.

## Code

- Keep the core (`src/harness`) standard-library Python 3.11 at import: Isaac,
  CUDA, torch and benchmark code stay in worker, kernel and service processes.
- A checkout installs like the package: `pip install -e .`. Each service and benchmark
  gets an environment of its own from the `[environment]` of its manifest on first use,
  under the pins of `environment/lock/pip-freeze.txt` (`environment/README.md`): a
  dependency goes into the manifest, a pin into the pins, committed together.
- No downloads or paid API calls in tests; a quickstart installs only what a run of it
  uses (installed on first use).
- Preserve original observations, action receipts and errors in traces. A recorded
  observation replay is not a new closed-loop evaluation, and a mock is never a result.
- Motion requests are tied to an episode and observation step. Never silently retry a
  possibly executed motion.
- Never commit credentials, simulator assets, checkpoints, environments or run artifacts.
- One topic per pull request; a change of several steps is one pull request with one
  commit per step.

## Testing and PR readiness

- Follow [the local testing guide](docs/TESTING.md) for setup, commands and evidence.
  CI (`.github/workflows/checks.yml`) runs minimal lint and offline tests; local validation of affected contracts remains required.
- Do not run the full suite. Validate the affected contracts, an installed wheel in a clean
  environment, and representative real Harness tasks. Record failures and missing
  environments separately; do not fix unrelated historical test failures.
- Add or extend meaningful tests for new functional behavior, changed contracts and
  bug fixes. Cover the intended result, relevant failure paths and boundaries; a bug
  regression must fail before the fix and pass after it.
- For performance-sensitive changes (latency, throughput, memory, concurrency, model
  calls or cost), add a suitable regression test or repeatable benchmark and report
  before/after measurements on the same workload and environment. Keep timing checks
  out of ordinary unit tests when stable work-count or resource assertions suffice.
- A skip does not validate changed behavior. Prepare the required environment or
  report the missing validation as a blocker. Pure prose, formatting and other
  reversible changes without a behavior or performance effect need no new tests;
  do not add tests that merely restate the implementation.

## Four-layer architecture in documentation

Keep the four-layer structure and its diagram in both English and Chinese: language
model, programs and learned policies, reactive layer, safety layer. Use technical
names, without human-body metaphors. The tick coordinates these layers; the worker
enforces safety at the environment boundary. Neither replaces the four-layer model
with a flat list of implementation components.
