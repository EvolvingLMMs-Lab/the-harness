---
title: "Configuration"
description: "One configuration file for you, an optional one for a project, and the files that describe a run: where each is, what wins, and the options you change most."
---

The Harness reads one file of yours, `~/.harness/config.toml`, and, inside a project,
that project's `harness.toml`. Both files can start empty. Every new conversation
chooses where it works; real-input permission, other-window information and screen
recording require explicit choices when first used. Internal schema defaults are not
treated as consent.

## config.toml

`harness` writes it on its first run, with the model and key you chose. The app's
**Settings** page and the terminal interface change it too, and you can edit it by hand:

```toml
[model]
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash"
reasoning_effort = "low"

[keys]
OPENROUTER_API_KEY = "sk-or-..."

[limits]
max_steps = 60                     # steps per task
max_minutes = 120                  # minutes per conversation

[session]
environment = "ask"                # ask where each new conversation works

[computer]
mode = "browser"                   # the computer kind that choice highlights first

[physical]
level = "ask_once_app"             # when the agent may use your mouse and keyboard

[[physical.rules]]
level = "never"
app = "wechat"

[packages]
auto_install = "official"          # install the packages a task needs, from the official registry
```

| Section | |
|---|---|
| `[model]` | the provider and model, and its advanced settings ([Models and providers](/docs/configure/models/)) |
| `[keys]` | the keys of your providers and connectors, by the name of their variable; the file is readable by you only |
| `[packages]` | install on first use, the registry, the packages you installed ([Packages](/docs/configure/packages/)) |
| `[general]` | language, theme, notifications |
| `[limits]` | steps, minutes and dollars per conversation, sub-agent levels, asking before each step |
| `[session]` | where a new conversation works, and whether it has sub-agents |
| `[environments]` | when an agent may take another environment into its conversation ([Permissions and privacy](/docs/configure/permissions/#another-environment)) |
| `[computer]` | the computer kind highlighted first, the monitor, the screenshot size, how many conversations work at once |
| `[physical]`, `[privacy]` | the mouse and keyboard, and what the model learns about your windows ([Permissions and privacy](/docs/configure/permissions/)) |
| `[personal]` | what the agent should know about you, in your words |
| `[data]` | how long conversations are kept |


## Where a conversation works

Each new conversation chooses its environment. The choice lists what your installed
packages provide:

| Environment | `--workspace` | |
|---|---|---|
| No environment | `none` | conversation only: the model and your connected tools. No worker starts and nothing is shown to the model |
| Project folder | `project` | reads and changes files and runs commands in one folder you name; no screen |
| Background browser | `browser` | an isolated browser without your logins |
| Background applications | `apps` | your applications, off your screen |
| Your desktop | `desktop` | your screen, and your mouse and keyboard as your settings allow |
| Separate display | `display` | a display or virtual machine of its own |

`session.environment` says how the choice is made:

| Value | |
|---|---|
| `ask` (default) | ask at the start of every conversation; your last choice is highlighted and Enter takes it |
| `last` | take the last choice without asking |
| a kind, such as `none` or `browser` | always that one |

Every frontend has it: the terminal's opening choice and `/environment`, the picker
beside the model in the app, `--workspace` and `--folder` on the command line, and
`workspace=` in Python. Where nobody can be asked (a script, the Python API) and the
setting is `ask`, the task is not started and the error names the option: nothing is
chosen for you. `computer.mode` is only the computer kind the choice highlights before
you have made one.

A conversation is not confined to that environment. When a step needs another one, the
agent asks to take it: see [Another environment](/docs/configure/permissions/#another-environment).

The [settings reference](/docs/reference/settings/) lists every key, its values and its
default. A change applies to the next conversation; the permission levels and the
number of workspaces apply at once.

## A project's harness.toml

A folder with a `harness.toml` is a project. It names the packages the project uses,
and `harness install` there writes `harness.lock` beside it, so everyone who works on the
project gets the same packages:

```toml
[packages]
computer = "^1.0"
mine = { source = "git:github.com/you/mine@v0.3", range = "^0.3" }
```

## What wins

From lowest to highest: the defaults, `config.toml`, the project's `harness.toml`, the
environment variables, and the options of one command (such as `harness run --workspace
browser "task"`), which hold for that run only.

## Environment variables

| Variable | |
|---|---|
| `OPENROUTER_API_KEY`, ... | a provider's key, in place of `[keys]` |
| `HARNESS_DATA` | where `config.toml`, conversations and libraries are (default `~/.harness`) |
| `HARNESS_HOME` | where packages, environments and weights are (default `~/.cache/harness`) |
| `HARNESS_REGISTRY` | another package registry: an https address or a local folder |
| `HARNESS_CHROME_PATH` | a Chrome executable for background browsers, in place of the installed Google Chrome |
| `HARNESS_HOST_IDLE` | seconds the session host stays up with nothing open (default 1800) |

## The files that describe a run

Benchmarks and other repeated runs describe what they run in TOML files that packages
ship and that you can write yourself: an **agent** (its prompt, skills and runtime
settings), a **model file** (which model plays each role) and an **experiment** (an
environment, its tasks and seeds, the budgets of an episode, and changes to the agent
and model). Each layer overrides the one before it, and the options of the command come
last:

```toml
#:schema https://harness.lmms-lab.com/docs/schema/experiment.json
description = "my game, five seeds, a cheaper model"
bench = "mygame"
tasks = ["play"]
seeds = "0-4"
model = "deepseek-flash"

[budget]
max_model_calls = 40               # per episode
max_cost_usd = 0.5                 # per episode
max_total_cost_usd = 5             # the whole run

[overrides.agent.runtime]
think_while_acting = "on"          # ask the model again while a program runs
verifier = false                   # do not check the result with a second model

[overrides.model.main]
reasoning_effort = "low"
```

The first line lets an editor that reads JSON schemas for TOML (Taplo, or the Even
Better TOML extension) complete and explain every key. The
[configuration keys](/docs/reference/configuration/) reference lists them all, and a
benchmark package's README shows how it runs its experiments.

Every run resolves these files into a **lock**: everything that decides what it
computes (the versions, the prompt, the skills, the model roles, the runtime settings,
the packages) and nothing about where it runs. The lock's hash is the run's
**identity**, recorded in its `manifest.json`: two runs with the same identity ran the
same configuration.
