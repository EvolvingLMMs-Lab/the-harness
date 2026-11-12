---
title: "Traces"
description: "The files of a run and every kind of record in its trace."
---

Every conversation and every episode leaves a directory: what was configured
(`manifest.json`), everything that happened, in order (`events.jsonl`, the trace), and how
it ended (`summary.json`). [`harness replay`](/docs/use/replay/), the app and the terminal chat read
these files; nothing else is needed to follow a run afterwards.

## Files of a run

### An episode or a conversation

| File | What it holds |
|---|---|
| `manifest.json` | the configuration the episode ran with, its hash, the seed, the worker's profile and where the code came from ([below](#manifestjson)) |
| `events.jsonl` | the trace: one record per line, appended as it happens ([below](#eventsjsonl)) |
| `summary.json` | how the episode ended, what it spent and how its calls went ([below](#summaryjson)); its presence marks the episode as finished |
| `kernel.log` | the output of the process the agent's programs run in |
| `videos/` | `episode-<camera>.mp4`, one per camera, when the worker records video |
| `screen.mkv`, `screen.json` | the screen the conversation worked on, when `computer.record_screen` is on: the video, each frame with its wall-clock time, and what was recorded (`video`, `display`, `area`, `fps`, `clock`, `start`, `stop`) |
| `agents/<id>/` | a sub-agent's own directory, with the same files |
| `meta.json` | the app's conversations only: the title the app shows |

Files the agent's programs write stay beside these, in the same directory.

The app keeps its conversations in `~/.harness/conversations/` (or under `$HARNESS_DATA`).

### A run of many episodes

`harness run` writes each episode to `OUTPUT/<task>/seed-<n>/`, for example
`runs/dev/stack_bowls/seed-0/`. The output directory itself holds:

| File | What it holds |
|---|---|
| `suite.json` | the requested episodes, the command line and the settings a resume must keep ([CLI JSON](/docs/reference/cli-json/#suitejson)) |
| `outcome.json` | what the latest `harness run` did and its exit status ([CLI JSON](/docs/reference/cli-json/#run-and-outcomejson)) |
| `.running` | the processes working on the suite now ([CLI JSON](/docs/reference/cli-json/#running)) |
| `suite.log` | the run's log lines, each with its time |
| `workers/<name>.log` | each worker's output |
| `<task>/unstable.json` | `{unstable seed: the layout run in its place}`, so a resumed run runs the same replacement |
| `<task>/displaced.json` | `{requested seed: the layout run for it}`, for a requested layout an earlier run in this output had already run in place of an unstable one |

`harness program`, which runs one task's seeds against a worker that already runs, writes
`OUTPUT/<time>-<id>/seed-<n>/` and, beside them, `experiment.json`: the configuration, the
episodes' summaries, `success_rate`, `completed_cases` and `planned_cases`.

## manifest.json

| Key | What it holds |
|---|---|
| `schema_version`, `kind` | `1`, `program` |
| `config` | `environment`, `version` (`agent_version` in older traces), `main` (the main model's role), `runtime`, `verifier`, `system_prompt`, `task`, `seeds`, `max_model_calls`, `max_wall_seconds`, `task_description`, `max_cost_usd`, `agent_id` (the agent's identity), `agent_lock`, `placement`; `embodiment` when it is not a robot |
| `config_sha256` | the hash of `config` |
| `seed` | the episode's seed |
| `embodiment_profile`, `embodiment_sha256` | the worker's profile after the reset (without task-specific keys) and its hash |
| `provenance` | the Python version, the git commit and whether the checkout had changes, the package's files with their hashes, and the package's hash |
| `interactive` | only for a conversation a user took part in: `confirmation` (`never` or `always`) and `instruction` (the user's first message, or null) |
| `agent` | only for a sub-agent: its `session`, `agent`, `parent`, `depth`, `workspace` and `budget` (`calls`, `cost`, `seconds`) |

## events.jsonl

One JSON object per line. Every record has:

| Field | What it holds |
|---|---|
| `seq` | the record's number, from 0: its id |
| `time` | wall-clock time, epoch seconds |
| `event` | the kind of record (the tables below) |
| `source` | who it comes from: `user`, `agent` (the main model), `program` (code running in the agent's kernel), `environment` (the worker) or `harness` |
| `who` | once the conversation is in a session: `{session, agent, parent}`, whose record it is |

and the fields of its kind. The catalog of kinds is `harness.runtime.conversation.EVENTS`
(each with its source, whether the model is shown what it holds, and a line on what it
is); a kind not in it is refused. The records marked *shown* below hold what the model
sees, so the model's history can be rebuilt from the trace alone
(`harness.runtime.conversation.rebuild_messages`).

### The conversation

| Event | Source | Fields |
|---|---|---|
| `state` | harness | `status`: the execution status, one of `IDLE` (between turns: the conversation keeps everything and waits for what starts the next turn), `RUNNING`, `PAUSED`, `WAITING_FOR_CONFIRMATION`, `FINISHED`, `ERROR`; `reason`: after a turn, how it ended (as in `turn_result`); when the conversation ended, the summary's status |
| `reset` | environment | *shown.* `observation`: `episode_id`, `step`, `instruction`, `state`, `images` (data URLs) |
| `user_message` | user | *shown.* `text`, for the model's next call; `sender` when a parent agent sent it |
| `agent_message` | agent | *shown.* `text`: a reply without a block: the model's answer, which ends its turn |
| `turn_result` | harness | the end of a turn. `reason`: `answer`, `budget` (the turn's model calls), `wall_time` (the turn's time), `cost` (the conversation's limit), `error`, `interrupted`, `episode_ended`, or `closed` when the conversation was ended during the turn; `turn` (its number), `session`, `model_calls` (in this turn), `cost_usd` (of the conversation so far), `seconds`, `result` (the answer), `error` |
| `resumed` | harness | *shown.* the conversation goes on in a new process: `messages` restored, the `facts` restored, the `units` that died with the old process |
| `confirmation_request` | harness | `code`: a program waits for the user's approval |
| `confirmation` | user | *shown.* `accepted`, `reason`: the user approved or rejected the waiting program |
| `program_held` | harness | the user paused while the model answered: its program waits for a resume |
| `program_dropped` | harness | `reason` (`user_message`): the held program did not run, the user's message replaced it |
| `user_took_over` | harness | `window`: the user brought a window of theirs to the front; the conversation pauses until they hand the computer back |
| `workspace_reclaimed` | harness | `by`: the app ended this conversation, which was waiting for the user, so that conversation could take its workspace |
| `environment_attached` | harness | *shown.* `kind`, `label`, `why` (the model's reason), `level`, `asked`, `skipped_confirmation`, `folder`: another environment was taken into the conversation |
| `environment_refused` | harness | *shown.* `kind`, `why`, `reason`, `level`, `asked`: a request for another environment was refused, by the settings, the user or because nobody could be asked |
| `environment_released` | harness | *shown.* `kind`, `label`, `reason`: an attached environment was given back |
| `agents_enabled` | harness | *shown.* `enabled`, `asked_by` (`user` or `model`), `why`: sub-agents were switched on for the conversation, or the user declined |
| `views` | program | `action`: `looked` (with `program` and `views`: each `camera`, `region`, `pin`), `watch`, `unwatch`, `keep`, `unpin`: what a program said of the views the model sees |
| `stuck` | harness | `repeated` (`program` or `event`), `what`: the same program or the same unhandled event three times in a row (interactive conversations; only noted) |
| `screen_recording` | harness | the screen the conversation works on is recorded (`screen.mkv`, `screen.json`): `video`, `display`, `area`, `fps`, `clock`, `start`, `stop`; or `error` when it cannot be |

### Model calls

| Event | Source | Fields |
|---|---|---|
| `thought_queued`, `thought_started`, `thought_cancelled`, `thought_exited` | agent | Thought ID, role, trigger, owner, and input revision. The exit receipt records elapsed time and known usage. |
| `model_request` | harness | *shown.* `call` (from 0); `model` and `reasoning_effort`, where the call goes; `reason`: `start`, `user`, `program_end`, `program_running` (the turn came back while the program still runs), `unit_end` (a unit that is not a program of the model ended), `wait_end`, `escalation`, `error`, `verify`, `format`, `empty`, `rejected`; `total_messages`, `sent_messages`, `new_messages` (the messages added since the previous call); `context` (one row per message sent: `role`, the start of its text, `chars`, `images`, `omitted`); `replaces`: how many of the last history messages `new_messages` replace |
| `model_text` | agent | `call`, `kind` (`text` or `reasoning`), `text`: a piece of a streamed reply, at most one per kind every 0.3 s while the call runs; `model_reply` holds all of it |
| `model_reply` | agent | *shown.* `call` (from 1), the original `text`, `usage` (`input_tokens`, `output_tokens`, `cost_usd`, `finish_reason`), `response_id`, `seconds`, `reasoning` when the provider returns it; `presentation`, the reply as the app shows it: `kind`, `body`, `thought`; `kind` is `message` for a reply in prose and `invalid` when nothing can run |
| `model_preempted` | harness | `call`, `back` (whether the reply had come; then its `text` and `usage`), `reason`: something reached the model while the call was out (a message, an unhandled event, a unit that ended with an error or an event), so its reply is set aside and the model is asked again |
| `empty_reply` | harness | `call`, `usage`, `seconds`, `reasoning`: a reply with no text (reasoning only, not cut off); the model is asked again at once, without a format error, up to twice in a row |
| `protocol_error` | harness | *shown.* `message`, `truncated`; `announced` when the reply only said what the model would do: the reply had no valid block, nothing ran and the model is told |
| `malformed_dropped` | harness | `messages`: malformed exchanges left the history once a valid reply came |
| `context_shortened` | harness | `history_turns`, `sent_messages`: fewer history turns are sent after the model server ran out of memory |
| `verify` | environment | *shown.* `claim`, `answer`: the verifier's answer to the model's claim |

### Units and waiting

Every program the model writes runs as a unit beside the others. The model's turn comes
back at once: with the program's result when it was over within
`runtime.turn_grace_seconds`, else while it still runs.

| Event | Source | Fields |
|---|---|---|
| `unit_end` | program | *shown.* `unit`, `name`, `kind` (`program` for code a program spawned or a rule started, `agent` for a sub-agent), `status` (`ok`, `error`, `escalated`, `cancelled`, `episode_ended`, `finished`), `error`, `escalation`, `stdout`, `returned`, `seconds`, `events`, `handled` (a handler took its failure): a unit that is not a program of the model ended. A program's end is its `cell` record |
| `wait` | agent | `seconds` (how long it lasts at most), `asked` (the seconds the reply named): the model replied `<wait>` |
| `wait_end` | harness | *shown.* `why`: `unit` (a unit the model started ended), `message`, `event`, `time` or `pause`; `seconds` |
| `rule` | program | `name`, `action` (`began`, `ended`), `unit`, `priority`: a rule started its program, or its end condition ended it |
| `fact` | program | `name`, `value` (the start of it), or `dropped`: a fact of the run changed |
| `preempted` | program | `unit`, `by`, `priority`, `restart`: a unit of higher priority took the environment from an execution, which is started again afterwards (`restart`) or ends with `PREEMPTED` |

### Programs

| Event | Source | Fields |
|---|---|---|
| `cell` | program | *shown.* `code`; `action` (direct mode: the action the model wrote); `result`: `status`, `error`, `escalation`, `episode_ended`, `finish`, `stdout`, `seconds`, `events` (one per bounded execution, [below](#execution-events)), `state`, `usage`, `report` (the skills' turn report: `text` and the cameras it outlined, `images`), `strategy`; `attachments` (how many) |
| `plan` | program | `steps`: the plan the user sees, with which steps are done |
| `skill_step` | program | `skill`, `step`, `of`, `what`, `ok`, `seconds`, `reason`: a step of a skill's plan ended while its program ran; news for the model's next look |
| `guard` | program | `name`, `action`, `stops`: a guard fired, and whether it stops the execution it fired in |
| `model_changed` | user | `model`, `reasoning_effort`: the main model from the next call on (POST /api/conversations/model) |
| `decision` | program | what the agent's turn asks the user to decide (a package's skill, with a decision tool): `subject`, `question`, `options`, `default` (an option's index), `irreversible` |
| `stay_on_screen` | program | the agent keeps the screen when its turn ends; the chat stays behind |
| `world` | program | the run's memory changed (runtime/memory.py): `action` (`remember`, `seen`, `forget`, `carried`; `recall`: `query`, `kind`, `near`, `radius` and the ids it `found` and the returned `results`; `refused`: a request nobody waited for that failed, `request` and `reason`), `id`, `kind`, `name`, `text`, `where`, `space`, `by` (who noted it), `confidence`, `seen`, `version` (`carried`: an entry of a store the run was handed); the model is told a summary after each program |
| `private_paths` | harness | `paths`: the worker's private files (its profile's `private_paths`, such as a game's instance); `guarded`: the roots the kernel refuses to programs from its start |
| `file_access` | program | `operation` (`open`, `os.listdir`, ...), `path`: a program tried to open or list one of the worker's private files; it was refused |
| `modules` | harness | `loaded`: the modules of the `skills` and `benches` packages the kernel imported, those of its start first, then the new ones after each program; `harness audit-run` reads them |
| `kernel_died` | harness | `message`: the kernel process died |

### The environment and input

| Event | Source | Fields |
|---|---|---|
| `input` | environment | how an input step reached the computer: `command` (its type), `executed`, `sent` (what it sent: the keys, buttons and pointer motion; typed text by its length only), `mechanism` (`semantic`, `targeted` or `physical`), `status` (`delivered`, `unverified`, `not_delivered`), the `app` and window `title` it went to, `waited` (seconds it waited for the input lock) |
| `physical_request` | harness | `id`, `level`, `app`, `window`, `handle`, `actions` (and why, from `request_physical`): a step needs the user's real mouse and keyboard, and the physical-input level asks first |
| `physical_answer` | user | `id`, `accepted`, `remember` (`once`, `app`, `session`, `always`), `reason`: the user's answer to a physical-input request |
| `page_read` | environment | `text`, `links`, `url`, `title`, `offset`, `total_chars`, `next_offset`: visible web text and links returned to a program; what it prints reaches the model |

### Library

| Event | Source | Fields |
|---|---|---|
| `library` | harness | `action` and its fields. `opened`: `version` and its loaded `entries` (each `id`, `name`, `sha256`, `evidence`, `source`, `summary` and its text (a 400-character preview for code)), the library as the run starts with it. `loaded`: `version`, `status`, `error`, the library's code ran in the kernel. `used`: `uses`, after an episode with use counting enabled, how many executions of the library's code counted as uses of its entries. `replayed`: `entries`, `status`, `error`, the provisional entries' tests ran again at the start. `test` (source `program`): `entry` (its kind), `name`, `ok`, `seconds`, `reason`, an entry's own test ran before it was proposed. `admitted` (*shown*): `section`, `name` (the entry's file), `sha256` of its bytes, `kind`, `evidence` (`proposed`, `provisional`, `replayed`, `validated`), `admitted` (whether it entered the library or waits), `version_before`, `version` (after), `origin` (`model` or `reflection`); `learned`: how it was learned, `active` or `passive`. The library's `admissions.jsonl` has the same line `rejected`: `kind`, `name`, `reason`, the library refused an entry (a frozen library, a bad name). `promoted`: `key`, `evidence` (or `failed`), `why`, an entry's evidence changed. `admission`: `level` (`off`, `fixture`, `own_test`), `allowed` (what the host allows), `physical` (what the worker's profile says), how learned code is admitted in this run. `trial_started`, `trial_observed`, `trial_pending`: `key`, `revision` and, where the host ran the entry's own test, `method` `own_test`, `ok`, `seconds`, `error`, `stdout`; a pending proposal's verification between programs. `demoted`: `key`, `revision`, `ok`, `failed`, an entry admitted by its own test went back to pending after failing in use. Older traces name each action as a record of its own (`library_loaded`, `library_admitted`, ...) |

### Sub-agents and entries

| Event | Source | Fields |
|---|---|---|
| `agent_delegated` | program | `agent` (its id), `run`, `task`, `workspace`, `kind`, `budget`, `model`, `windows` (those handed to it), `directory`: a program started a sub-agent |
| `agent_waited` | program | `agents`, `timeout`, `seconds`, `states` (each agent's status after): a program waited for sub-agents |
| `agent_sent` | program | `agent`, `text`: a program sent a sub-agent a message |
| `agent_cancelled` | program | `agent`: a program stopped a sub-agent |
| `agent_report` | harness | `agent`, `run`, `status`, `result`, `question`, `error`, `model_calls`, `cost_usd`, `seconds`, `directory`, `files`: a sub-agent ended |
| `entry_start` | program | `id` (`e1`, `e2`, ...), `parent` (`e0`, the model: every unit belongs to it), `name`, `kind` (`program`, `agent`), `cell` (the program of the model it is), `rule` (the rule whose program it is), `priority`, `claims`, `agent` (a sub-agent's id), `span` |
| `entry_claims` | program | `id`, `claims`: the channels a unit claims now, after a `claim` or a `release` |
| `entry_end` | program | `id`, `status` (`done`, `failed`, `cancelled`); `error`, or `event_kind` when it failed on an event |

### Timeline

| Event | Source | Fields |
|---|---|---|
| `span_start` | harness | `id`, `lane` (the kind of part: `model`, `verifier`, `program`, `skill`, `service`, `env`), `entry` (the entry whose code it is, when not the agent's programs), `name`, `parent` (the span it ran in: a skill's program, a service call's skill), and the part's details (a skill's `parameters` and `tick`, a model call's `call` and `reason`, ...); `time` is when it started |
| `span_end` | harness | `id`; `time` is when it ended; for a skill `event_kind` and `end_tick` (`escalated` when the event went up), for a program `status`, for a model call `output_tokens`; `error` when it raised |
| `tick_periods` | program | for an environment driven at a rate (`max_hz`): how its control periods went, their count, target, lengths and parts, and how many were late |

The replay's and the app's timeline lanes are read from the spans and the units.

### The end

| Event | Source | Fields |
|---|---|---|
| `policy_to_end` | program | `status`, `error`: the handed-over task ran on to the end once the calls after the policy's run were used up |
| `finish` | agent | `text`: an answer given as `<finish>` (the same as a reply in plain text); `source` is `program` when a program called `finish()`, `harness` when the turn was ended after `policy_to_end` |
| `wrap_up` | program | `status`, `error`, `events`: the benchmark's end-of-episode convention ran |
| `outcome` | environment | `outcome`: `success`, `reward`, `process_score`, `terminated`, `truncated`, `steps`, read with the token after the episode; never shown to the model |
| `episode_video` | environment | `files` (camera → path): the episode's videos were written |
| `interrupted` | harness | the turn was cancelled, or the run was interrupted |
| `error` | harness | `message`: the turn (before the first one: the conversation) ended in an error |
| `cleanup_error` | harness | `message`: closing the episode failed in part |

## summary.json

| Key | What it holds |
|---|---|
| `run`, `task`, `seed` | the episode's directory, task and seed |
| `status` | how the last turn ended: `finished` (an answer), `episode_ended`, `budget_exhausted`, `wall_time_exhausted`, `cost_exhausted`, `interrupted`, `error`; `closed` when the user or the host ended the conversation during a turn (one closed between turns keeps its last turn's status) |
| `open` | `true` in the summary written at a turn's end while the conversation goes on; absent once it ended |
| `success`, `reward`, `process_score`, `steps` | from the outcome |
| `model_calls`, `verifier_calls`, `cells` | calls of the main model and the verifier, programs run |
| `input_tokens`, `output_tokens`, `cost_usd` | the main model and the verifier, plus the vision calls programs made |
| `agent_seconds`, `kernel_seconds`, `wall_seconds` | time in model calls, in programs, in all |
| `decisions` | model calls by `reason` (as in `model_request`) |
| `empty_replies` | replies with no text, asked again at once |
| `events_handled`, `events_escalated` | execution events handled below the model, and those that went up to it |
| `guard_triggers` | guards that fired |
| `vision_calls`, `vision_cost_usd` | vision calls programs made |
| `agents` | when sub-agents ran: `started`, `model_calls`, `cost_usd` |
| `strategy` | the choice of `start(strategy, kind)`: `strategy` (A, B, C), `kind`, `policy`, `step`; `policy_ran` once the handed-over task ran; `after` when B handed over later |
| `error` | when the status is `error` |

## Execution events

`cell.result.events` lists one entry per bounded execution:

```json
{"skill": "move_eef", "event": {"kind": "COMPLETED", "source": "move_eef", "detail": {}, "tick": 22}, "ticks": 22}
```

| Kind | Meaning |
|---|---|
| `COMPLETED`, `PREDICATE_SATISFIED` | nominal: the program goes on without a handler |
| `TIMEOUT` | the execution ran out of ticks |
| `BLOCKED` | a motion's path was executed but the arm did not arrive: contact or a load holds it back |
| `GUARD_TRIGGERED` (or a guard's own event name) | a guard fired |
| `REGION_EXIT` | the motion left its allowed region |
| `SHIELD_REJECTED` | the worker's shield rejected the command |
| `REACTIVE_FAULT` | a reactive rule failed |
| `SKILL_ERROR` | the skill raised |
| `EPISODE_ENDED` | the environment ended the episode |
| `USER_PAUSED` | the user paused: every unit of the model stops, and the model hears of it |
| `PREEMPTED` | a unit of higher priority took the environment from an execution of a unit started with `restart=False` |
| `ENTRY_FAILED` | a unit that is not a program of the model failed (an exception, or an event nobody handled) |
| `CHANNEL_CONFLICT` | a unit reached for a channel another unit claims, drives or holds |

An event that goes up to the model carries the whole execution: `skill`, `parameters`,
`start_tick`, `end_tick`, `event`, `samples` (the state every 5 ticks).

## Execution feedback records

`execution_event` stores a nested `execution` record containing the bounded execution's
`skill`, terminal `event`, `ticks` and optional `entry`. Its event retains action identity and evidence references; the operation
value belongs to the calling program and is not serialized into the event. `program_output`
records `cell` and an ordered text chunk while a program runs. The cell reply contains a
bounded preview and `event_counts`; the trace retains the streamed records.
