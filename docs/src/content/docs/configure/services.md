---
title: "Services"
description: "Model services that run on your own GPUs: how they install, start, share a GPU and stop, and how to place them yourself."
---

Some abilities need a model that runs on your own hardware: a segmenter, a learned
policy for a robot, a world model, a local language model. The Harness runs each as a
**service**: a process of its own, in an environment of its own, that the agent's
skills call over HTTP. Packages provide them; `harness services` lists the ones you
have.

You rarely start services yourself. When a run starts, The Harness works out which
services the agent's skills use, installs the ones this computer lacks, and starts them
on the GPUs it finds. With a package that provides services installed, the commands
below do it by hand: to install ahead of time, to keep a model loaded between runs, or
to see what runs.

## Commands

```bash
harness services              # every service: what it does, its port, the GPU memory it needs
harness doctor sam3           # whether it is installed, what is missing, the GPUs and their free memory
harness install sam3          # its environment, sources and weights, without starting it
harness fetch sam3            # only its weights
harness up sam3               # start it (without names: every resident service)
harness status                # where each runs and whether it answers
harness down sam3             # stop it (without names: everything harness up started)
```

`harness install` builds the environment the service names (its Python version, pinned
requirements and sources) under `~/.cache/harness/envs/`, downloads its weights and
checks they are complete, and checks that it imports. An environment that already
matches is left alone. The log of each install is in
`~/.cache/harness/logs/install-<name>.log`.

## Where they run

Without any configuration, The Harness places services itself: a service is
**resident** (loaded once and kept) when there is room for it on a GPU, and **on
demand** (started when a skill first calls it, stopped after a while idle) when GPUs
must be shared. A computer without a GPU runs agents whose models are all hosted, or
reaches services that run elsewhere by their URL.

To decide yourself, write a **deploy** file and pass it with `--deploy FILE` (every
command takes it) or `HARNESS_DEPLOY`:

```toml
# my-deploy.toml
[services.sam3]
gpu = 0                   # resident on GPU 0

[services.g05]
gpu = 1
mode = "on_demand"
swap = "policies"         # services of one swap group share GPU 1, one loaded at a time
idle_seconds = 600        # stopped after 10 minutes without a request

[services.openwam]
gpu = 1
mode = "on_demand"
swap = "policies"

[services.molmo2]
mode = "external"         # someone else runs it
url = "http://gpu-box.local:8830"
```

| Key | |
|---|---|
| `gpu` | the GPU it runs on |
| `mode` | `resident` (default), `on_demand` or `external` |
| `swap` | a group of on-demand services that share a GPU, one loaded at a time |
| `idle_seconds` | how long an on-demand service stays up without a request |
| `url` | an external service's address |
| `python`, `env` | another interpreter, or environment variables, for the service |

Where a service runs is never part of a run's identity: the same agent with the same
services computes the same thing on any computer.

## On demand

On-demand services are started by a small **broker** process that `harness up` (or a
run) starts when a deploy has any. A skill asks the broker before each call; the broker
starts the service if it is not up, waits until it answers, and stops it after
`idle_seconds` without a request. In a swap group, starting one service stops the
others first.

## Logs and problems

Each service writes its log to `~/.cache/harness/logs/<name>.log`. `harness status`
says whether each one answers. A service whose port already answers when it should
start is used as it is (another run, or started by hand), and `harness down` stops only
what `harness up` started.

When a run cannot start a service it needs, the agent may run without the skills that
use it; `harness doctor EXPERIMENT` and `harness run --dry-run` list the skills that
would be dropped and why. `--strict` makes the run refuse instead.
[Troubleshooting](/docs/troubleshooting/) has the common errors.
