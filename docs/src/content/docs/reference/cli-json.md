---
title: "CLI JSON"
description: "The JSON that harness run, inspect, runs and doctor print, the files a suite keeps, and the other commands' JSON output."
---

What scripts read. Each document below carries `schema_version`, the version
of its own format. Within a version, fields are only added; a field removed, renamed or
given another meaning raises the version. A reader ignores fields it does not know and
checks `schema_version` before relying on the others. These tables list every field the
commands write; a release that changes one changes its table too.

Other commands print JSON without a version ([Other JSON output](#other-json-output)), and
every command reports an error the same way ([Errors](#errors)).

A type ending in `?` may be `null`. Rows marked *optional* appear only in some cases. Times
are ISO 8601 in UTC unless the row says otherwise; costs are US dollars.

## suite.json

`OUTPUT/suite.json`, written by `harness run` when it starts and by every process that
joins the suite. Version 2 added `invocation`; a version 1 file (or one without
`schema_version`) still reads and resumes with the original flags.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 2 |
| `episodes` | list | the requested episodes, every run that wrote to this output together |
| `episodes[].task` | string | task |
| `episodes[].seed` | integer | requested seed (layout) |
| `legacy_selection` | object? | set when a version 1 file only had task and seed unions: its `tasks` and `seeds`, candidates rather than requested pairs |
| `invocation` | object? | the command line `harness run --resume` repeats; `null` when the suite was written without one (the Python API) |
| `invocation.experiment` | string? | absolute path of the experiment file; `null`: none, `--tasks` only |
| `invocation.agent` | string? | `--agent`, absolute when it is a file |
| `invocation.model` | string? | `--model`: a name of `configs/models/`, or an absolute path |
| `invocation.sets` | list | the `--set KEY=VALUE` items, in order |
| `invocation.tasks` | list | task names, expanded (`all`, dimensions and moving resolved); with several runs in one output, all of theirs |
| `invocation.seeds` | list | seeds, expanded and sorted; with several runs, all of theirs |
| `invocation.strict` | boolean? | `--strict` / `--no-strict`; `null`: the default |
| `invocation.deploy` | string? | `--deploy`, else `$HARNESS_DEPLOY` at the time, absolute when it is a file; `null`: automatic placement |
| `invocation.script` | object? | `--script`; `null`: a model answered |
| `invocation.script.path` | string | absolute path of the scripted replies |
| `invocation.script.sha256` | string | their hash, as `execution.script_sha256`; a resume refuses changed replies |
| `invocation.max_total_cost_usd` | number? | `--max-total-cost-usd` |
| `invocation.rerun_errors` | boolean | `--rerun-errors` of the run that created the record; `--resume --rerun-errors` holds for that run only |
| `invocation.gpus` | list? | `--gpus` of the latest run; `null`: the deploy's |
| `invocation.workers_per_gpu` | integer? | `--workers-per-gpu` of the latest run |
| `invocation.base_port` | integer? | `--base-port` of the latest run |
| `invocation.workspaces` | integer? | `--workspaces` of the latest run |
| `run` | string? | the experiment file |
| `agent` | string | agent name |
| `agent_id` | string | agent identity |
| `execution` | object | what may not change while the suite grows; a resume compares it |
| `execution.agent_id` | string | agent identity |
| `execution.bench` | string | benchmark |
| `execution.layout_source` | string | `procedural`, `dev` or `eval` |
| `execution.layout_pack_seed` | integer? | evaluation layout pack |
| `execution.dev_layout_dir` | string? | development layout directory |
| `execution.worker` | object | the bench's worker options |
| `execution.budget` | object | episode budget |
| `execution.budget.max_model_calls` | integer? | model calls per episode |
| `execution.budget.max_wall_seconds` | number? | wall time per episode |
| `execution.budget.max_cost_usd` | number? | cost per episode |
| `execution.script_sha256` | string? | hash of the scripted replies; `null`: a model answered |
| `legacy_unchecked_fields` | list | execution fields an older suite did not record, so its earlier episodes were not checked against them |
| `agent_version` | string | the harness's version |
| `deploy` | string? | deploy name |
| `tasks` | list | every task requested so far |
| `seeds` | list | every seed requested so far |
| `layout_source` | string | as `execution.layout_source` |
| `layout_pack_seed` | integer? | as `execution.layout_pack_seed` |
| `started` | string | local time the suite was created (`YYYY-MM-DD HH:MM:SS`) |

## .running

`OUTPUT/.running`, while a `harness run` process works on the suite.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 1 |
| `processes` | list | one entry per running process; each removes its own when it ends |
| `processes[].host` | string | host name |
| `processes[].pid` | integer | process id |
| `processes[].started` | string | when it started |
| `processes[].boot_id` | string? | the host's boot id (Linux), so a pid of an earlier boot is not taken for a live one |

## run --dry-run

`harness run --dry-run`, also with `--resume`: the run it would start.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 1 |
| `dry_run` | boolean | `true` |
| `output` | string | absolute suite directory |
| `invocation` | object | what `suite.json` would record (fields as there) |
| `experiment` | string? | experiment file |
| `agent` | string | agent name |
| `agent_version` | string | the harness's version |
| `execution` | object | as in `suite.json` |
| `model` | string? | main model |
| `tasks` | list | tasks |
| `seeds` | list | seeds |
| `selected_episodes` | integer | tasks × seeds, before resume and layout replacement |
| `strict` | boolean | whether a missing skill or service refuses the run |
| `skills` | list | skills on |
| `skills_dropped` | object | skill name → why it is off |
| `services` | list | services the run uses |
| `max_total_cost_usd` | number? | suite cost cap of this run |
| `resume` | object | what an existing output means for the run |
| `resume.existing_suite` | boolean | `suite.json` exists |
| `resume.unchecked_legacy_fields` | list | execution fields the existing suite did not record |
| `resume.rerun_errors` | boolean | episodes that ended in an error run again |
| `resume.policy` | string | how finished and incomplete episodes are treated |
| `readiness` | string | what the preview did not check |

## run and outcome.json

What `harness run` prints at the end and writes to `OUTPUT/outcome.json`.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 1 |
| `output` | string | absolute suite directory |
| `result` | string | `complete`, `errors`, `incomplete`, `budget_exhausted` or `interrupted` |
| `exit_code` | integer | the exit status for `result`: 0, 3, 4, 5, 130 |
| `interrupted` | boolean | Ctrl-C stopped the run |
| `started` | string | when this process started |
| `ended` | string | when it ended |
| `tasks` | list | tasks of this run |
| `seeds` | list | seeds of this run |
| `requested_episodes` | integer | tasks × seeds of this run |
| `finished_episodes` | integer | of those, completed or ended in an error |
| `counts` | object | episodes of this run by state |
| `counts.completed` | integer | ended with a summary, successful or not |
| `counts.error` | integer | ended in an error |
| `counts.incomplete` | integer | started, no summary |
| `counts.missing` | integer | never started |
| `counts.unreadable` | integer | a damaged record |
| `episodes` | list | the episodes of this run that did not complete |
| `episodes[].task` | string | task |
| `episodes[].seed` | integer | requested seed |
| `episodes[].actual_seed` | integer? | the layout that ran for it (an unstable one is replaced) |
| `episodes[].state` | string | `error`, `incomplete`, `missing` or `unreadable` |
| `episodes[].status` | string? | the summary's status |
| `episodes[].error` | string? | the error |
| `worker_failures` | list | workers that failed |
| `worker_failures[].slot` | integer | worker slot |
| `worker_failures[].task` | string | task it served |
| `worker_failures[].stage` | string | `start`, `restart` or `episode` |
| `worker_failures[].reason` | string | why |
| `budget` | object | the suite cost cap |
| `budget.max_total_cost_usd` | number? | the cap |
| `budget.spent_usd` | number | spent by this run |
| `budget.reached` | boolean | the cap was reached |
| `budget.skipped` | list | episodes not started because of it |
| `budget.skipped[].task` | string | task |
| `budget.skipped[].seed` | integer | seed |
| `cost_usd` | number | model and verifier cost of this run |

## inspect

`harness inspect OUTPUT --json`. It reads the files and changes nothing.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 1 |
| `suite_schema_version` | integer | the `schema_version` of `suite.json` (1 when it has none) |
| `output` | string | absolute suite directory |
| `observed_at` | string | when this was read |
| `evidence_updated` | string | the newest file read |
| `liveness` | string | `running`, `stale`, `unknown` or `stopped` |
| `processes` | list | the entries of `.running` (fields as there) |
| `last_outcome` | object? | the run that ended last (`outcome.json`) |
| `last_outcome.exit_code` | integer | its exit status |
| `last_outcome.result` | string | its result |
| `last_outcome.ended` | string | when it ended |
| `agent` | string? | agent name |
| `agent_version` | string? | the harness's version |
| `agent_id` | string? | agent identity |
| `bench` | string? | benchmark |
| `layout_source` | string? | layouts |
| `layout_pack_seed` | integer? | evaluation layout pack |
| `execution` | object | as in `suite.json` (`{}` when it has none) |
| `invocation` | object? | as in `suite.json` |
| `experiment` | string? | experiment file |
| `deploy` | string? | deploy name |
| `selection_exact` | boolean | the requested pairs are recorded (not legacy unions) |
| `requested_episodes` | integer | requested episodes |
| `candidate_episodes` | integer | requested plus legacy candidates |
| `counts` | object | episodes by state |
| `counts.completed` | integer | ended with a summary, successful or not |
| `counts.error` | integer | ended in an error |
| `counts.incomplete` | integer | started, no summary |
| `counts.missing` | integer | requested, never started |
| `counts.unknown` | integer | a legacy candidate without a directory |
| `counts.unreadable` | integer | a damaged record |
| `episodes` | list | every requested or candidate episode |
| `episodes[].task` | string | task |
| `episodes[].seed` | integer | requested seed |
| `episodes[].requested` | boolean | `false`: a legacy candidate |
| `episodes[].actual_seed` | integer? | the layout that ran for it; `null` while it awaits a new one |
| `episodes[].state` | string | `completed`, `error`, `incomplete`, `missing`, `unknown` or `unreadable` |
| `episodes[].status` | string? | the summary's status |
| `episodes[].success` | boolean? | the summary's success |
| `episodes[].cost_usd` | number? | the summary's cost |
| `episodes[].error` | string? | the error, or why the record cannot be read |
| `episodes[].directory` | string, optional | the episode directory, once its layout is known |
| `episodes[].reason` | string, optional | why it has no layout yet |
| `recorded_cost_usd` | number | cost in the current summaries |
| `summaries_without_cost` | integer | current summaries without a usable cost |
| `cost_scope` | string | what `recorded_cost_usd` covers |
| `legacy_unchecked_fields` | list | as in `suite.json` |
| `warnings` | list | what could not be read or certified |
| `next_steps` | object | commands to go on with |
| `next_steps.report` | string | `harness report OUTPUT` |
| `next_steps.view` | string | `harness view OUTPUT` |
| `next_steps.resume` | string | `harness run --resume OUTPUT`; for a suite without `invocation`, how to resume it by hand |

## runs

`harness runs [ROOT] --json`: the suites under ROOT, newest evidence first.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 1 |
| `root` | string | absolute runs directory |
| `suites` | list | one object per suite: the fields of `inspect` without `schema_version`, `episodes`, `execution` and `invocation`; a suite that cannot be read has only `output`, `error` and `evidence_updated` |

## doctor

`harness doctor [SERVICE ...] --json`: whether this machine can run the deploy's services.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 1 |
| `deploy` | string | deploy name |
| `ok` | boolean | no problem found (exit status 0) |
| `problems` | list | what stops a run, one sentence each |
| `notes` | list | what a run will do about itself (install, reuse a port), one sentence each |
| `gpus` | list? | the GPUs here; `null`: none found |
| `gpus[].index` | integer | GPU index |
| `gpus[].name` | string | model |
| `gpus[].used_gb` | number | memory in use |
| `gpus[].total_gb` | number | memory |
| `services` | list | the services checked, as rows of `harness status --json` |
| `installed` | list | the services, installed or not |
| `installed[].name` | string | name |
| `installed[].what` | string | `service` |
| `installed[].installed` | string | `yes` or `no` |
| `installed[].environment` | string, optional | its environment directory, or which interpreter it uses |
| `installed[].environment_installed` | boolean, optional | its environment is installed |
| `installed[].missing_files` | list, optional | its weights, sources or assets still missing |
| `installed[].note` | string, optional | why nothing needs installing (an external service) |
| `to_install` | list | what a run would install first (`harness install` does it now) |
| `packages` | list | the installed packages, as rows of `harness list --json` |
| `packages[].name` | string | the package |
| `packages[].version` | string | its installed version |
| `packages[].scope` | string | `user` (yours) or `project` (the project's harness.lock) |
| `packages[].source` | string | where it came from: `registry`, `registry:<address>`, `git:...`, `url:...`, `path:...`, `migrated:addons` |
| `packages[].path` | string | the installed folder |
| `packages[].link` | boolean | a folder used where it is (`harness install --link`) |
| `packages[].enabled` | boolean | runs use it |
| `packages[].trusted` | boolean | it may run code here |
| `packages[].summary` | string | one line: what it lets the agent do |
| `packages[].provides` | object | what it provides, by kind: `{"skills": [...], "embodiments": [...], ...}` |
| `packages[].problem` | string, optional | why it does not load |

## doctor EXPERIMENT

`harness doctor EXPERIMENT --json` (also with `--model`, `--set`, `--tasks`, `--seeds`,
`--agent`, `--strict`, `--gpus`): whether this machine can run the experiment as
configured. Exit status 1 while `counts.missing` is not 0.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 1 |
| `experiment` | string? | the experiment file; `null`: none (`--tasks` only) |
| `deploy` | string | deploy name |
| `agent` | string | agent name |
| `version` | string | the harness's version |
| `identity` | string | the agent's identity, as `harness run --dry-run` reports it |
| `model` | string? | the main model |
| `bench` | string | benchmark |
| `tasks` | list | task names |
| `seeds` | list | seeds |
| `ok` | boolean | nothing missing (exit status 0) |
| `counts` | object | how many checks are in each state |
| `counts.ready` | integer | ready |
| `counts.will_install` | integer | the first run installs it |
| `counts.missing` | integer | missing |
| `checks` | list | one row per check |
| `checks[].check` | string | `python`, `skill`, `service`, `weights`, `benchmark`, `simulator`, `gpu` or `key` |
| `checks[].name` | string | what it checks: a skill, service, benchmark, GPU index or environment variable |
| `checks[].status` | string | `ready`, `will_install` or `missing` |
| `checks[].detail` | string | what was found; a key's value is never included |
| `checks[].fix` | string, optional | the command or setting that fixes it (every check not ready) |
| `skills_off` | object | skills the configuration leaves off: name → why |
| `gpus` | list? | the GPUs here; `null`: none found |
| `gpus[].index` | integer | GPU index |
| `gpus[].name` | string | model |
| `gpus[].used_gb` | number | memory in use |
| `gpus[].total_gb` | number | memory |
| `to_install` | list | what the first run installs (`harness install` does it now) |

## Other JSON output

These commands print JSON with `--json` (or always), without a `schema_version`: their
shape follows the command and may change between releases.

| Command | What it prints |
| --- | --- |
| `harness list --json` | one row per installed package (`--available`: per package of the registry); `harness list NAME --json` one package with what it provides |
| `harness replay RUN --json` | the run's trace records, one JSON line each ([Events and traces](/docs/reference/traces/)) |
| `harness library ls --json` | one row per library |
| `harness library show LIBRARY --json`, `harness library show RUN --json` | the entries in the one memory format (`scope`, `kind`, `name`, `text`, `where`, `evidence`, `source`, `seen`, `version`, `cells`): a library's, or a run's memory followed by its library's |
| `harness config --json` | the resolved agent: `agent`, `agent_version`, `identity`, `main`, `runtime`, `placement`, `lock`; for an experiment also its tasks, seeds, layouts and strictness |
| `harness library show LIBRARY --json` | `{"directory", "version", "entries"}` |
| `harness config --json` | the resolved agent: `agent`, `version`, `identity`, `main`, `runtime`, `placement`, `lock`; for an experiment also its tasks, seeds, layouts and strictness |
| `harness services --json` | one row per service: `service`, `kind`, `protocol`, `port`, `vram_gb`, `summary` |
| `harness up --json`, `harness status --json` | one row per service of the deploy: where it runs and whether it answers |
| `harness report RUNS --json` | the score table over the runs' episodes |
| `harness audit-run RUN --json` | the audit's report, as `audit.json` |

## Errors

A command that fails prints one JSON line to standard error and exits with a non-zero
status.

| Field | Type | Meaning |
| --- | --- | --- |
| `error` | string | `usage: ...` for a wrong command line (exit status 2); otherwise the error's type and message, such as `ValueError: limits.max_steps is between 1 and 1000` (exit status 1) |

Ctrl-C ends a command with exit status 130.
