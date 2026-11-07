---
title: "Troubleshooting"
description: "Where the logs are, what harness doctor checks, how to reset, the common errors by their message, and how to report a bug."
---

## Start with harness doctor

```bash
harness doctor                 # this computer: Python, packages, services, GPUs, keys
harness doctor computer        # what one experiment needs here
harness doctor --json          # the same for a bug report
```

Each check is `ready`, `will_install` (the first run installs it) or `missing`, and a
missing one comes with the line that fixes it. In the app, **Settings → About → Run
harness doctor** shows the same.

## Where the logs are

| Log | Holds |
|---|---|
| `~/.harness/logs/host.log` | the session host: sessions starting and ending, workspaces, installs it started |
| `~/.cache/harness/logs/install-<name>.log` | the install of a package's environment or a service |
| `~/.cache/harness/logs/<service>.log` | a model service while it runs |
| a run's `kernel.log` | the agent's programs: their output and errors |
| a run's `events.jsonl` | everything that happened, record by record ([Events and traces](/docs/reference/traces/)) |
| `suite.log` in a run's output | `harness run`: workers, episodes, errors |

In the app, **Settings → About → Logs** opens the folder. A conversation's own files
are under `~/.harness/conversations/`; `harness replay CONVERSATION` prints what it
did.

## Reset

| To | Do |
|---|---|
| stop everything that runs | `/host stop` in `harness` (ends the session host and its open sessions), and `harness down` for services |
| rebuild one environment | delete its folder under `~/.cache/harness/envs/`; the next run builds it again |
| reinstall a package | `harness remove NAME`, then `harness install NAME` |
| go back to the default settings | delete the sections you changed from `~/.harness/config.toml` (keep `[model]` and `[keys]`) |
| forget a key | remove its line under `[keys]` in `~/.harness/config.toml`, or unset the variable |
| start from nothing | delete `~/.harness/` and `~/.cache/harness/` (this deletes your conversations) |

## Common errors

### `NAME: its environment did not install (...); see .../install-NAME.log`

An environment for a package, a workspace or a service could not be built. The log's
last lines say why: usually a download that failed (a proxy or a mirror: pip's own
settings apply), or a Python version that is missing (install
[uv](https://docs.astral.sh/uv/), which fetches it, or put `python3.11` on your
`PATH`). Fix it and run again; a half-built environment is replaced.

### `KernelDied: Kernel failed to start`

The process that runs the agent's programs could not start. The message's traceback
names the module that failed to import; the environment it ran in is missing a
dependency. Rebuild that environment (see [Reset](#reset)), and report it if it comes
back.

### `... is not set (export it, or keep it in [keys] of the configuration file)`

A model's key is missing. Set the variable the message names
([Models and providers](/docs/configure/models/)), or connect the model again in the app.
A key exported only in one shell is not seen by a session host that was started from
another: type `/host stop` in `harness` and start again from the shell that has it.

### The provider answers 401, 402 or 429

401: the key is wrong or revoked. 402: the account has no credit. 429: too many
requests; The Harness retries with a pause, and a run gives up after its retries. Each
appears in the conversation as an error with the provider's own message.

### `Could not start background Chrome. An installed Google Chrome is required`

A background browser needs Google Chrome. Install it, or point
`HARNESS_CHROME_PATH` at another Chrome or Chromium executable.

### `browser workspaces (...) are not available on this machine` and the like

The app hides the workspaces this computer cannot run, and **Settings → Computer** says
what each one needs: Chrome for a background browser, an X11 session for apps in the
background on Linux, a display server or a virtual machine image for a display of its
own.

### `no X display: DISPLAY is not set`

On Linux, the desktop needs an X11 session. Over SSH or on a server, use a background
browser or a display of its own, which start their own display.

### macOS: the screen is black, or clicks do nothing

Allow **Screen Recording** and **Accessibility** for the terminal or the app that runs
`harness`, in **System Settings → Privacy & Security**, then start it again.

### `waiting for a workspace: 4 of 4 in use`

Every workspace is busy. End a conversation, or raise `workspaces` under `[computer]`
(**Settings → Computer → Conversations working at once** in the app).

### `missing or wrong session key`

HTTP API clients must supply the session host token. Do not share it.

### `out of GPU memory`

A model service, or a self-hosted language model with a long context, ran out of GPU
memory. For a language model, The Harness sends fewer history turns and goes on. For a
service, place it on another GPU or make it on demand in a deploy file
([Services](/docs/configure/services/)).

### `harness run --resume` refuses with exit status 2

The arguments differ from the ones the suite recorded. Only where it runs may change
(`--gpus`, `--workers-per-gpu`, `--base-port`, `--workspaces`) and `--rerun-errors` may
be added; a changed experiment needs a new `--output`.

### The agent repeats itself, or finishes without answering

Try a stronger model, or a higher `reasoning_effort`: small models lose track of long
tasks. Give it the task in more concrete words, or split it. The timeline shows what it
did and when ([Watch and replay a run](/docs/use/replay/)).

## Report a bug

Open an issue at
[github.com/EvolvingLMMs-Lab/the-harness/issues](https://github.com/EvolvingLMMs-Lab/the-harness/issues)
with:

- what you did, what you expected, and what happened;
- `harness doctor --json`;
- the end of the log that shows the error;
- if you can share it, the run's folder, or the app's **⋯ → Export** of the
  conversation.

Look through it before you attach it: a trace holds the screenshots the agent took and
the text it read. Keys are never written to traces or logs.
