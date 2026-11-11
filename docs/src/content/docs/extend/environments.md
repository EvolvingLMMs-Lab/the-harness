---
title: "Add an environment"
description: "Connect a new environment the agent can see and act in: a worker that serves it over HTTP, the kind of embodiment it is, and a bench of tasks."
---

The agent can work in any environment it can see and act in: an app, a website, a game,
a simulator, a robot. The Harness reaches each one through a **worker**: a process that
serves the environment over HTTP, checks every step before it acts, and keeps the score
to itself. To add an environment, you write its worker and say what kind of
environment it is; the agent's skills then work on it unchanged.

## Three parts

| Part | Says | File |
|---|---|---|
| **worker** | how to observe the environment and act on it | a Python class and a factory function |
| **embodiment** | what kind of environment it is (`desktop`, `browser`, `game`, `robot`) and its facts: screen size, controls, control rate, limits | `embodiments/<name>/embodiment.toml` |
| **bench** | its tasks, how to start its worker for a run, how a run is scored | `benches/<name>/bench.toml` |

The kind decides which skills the agent gets: a `game` gets screenshots, keys and the
mouse and channels; a `desktop` gets windows, accessibility and input; a
`robot` gets motions, kinematics and controllers. Pick the kind your environment is
closest to, and the agent's prompts and skills for that kind apply.

## 1. The worker

A worker is an object with `reset(task, seed)` and the calls of its kind. Every worker
answers these:

| Call | Returns |
|---|---|
| `profile` | the static facts: the kind, the control rate, the screen or cameras, the limits |
| `state` | the state now |
| `tick` | one step: the command, the check's verdict, the new state |
| `observe` | the state and the images |
| `claim_outcome`, `outcome` | the result of the episode, for the run only, never for the agent |

A game worker answers its input in the form the `game` kind defines (keys, buttons and
mouse motion for one control period) and returns frames as images. The
[worker protocol](/docs/reference/worker-protocol/) gives every call of every kind.

```python
# mygame/worker.py
class MyGame:
    def reset(self, task="play", seed=0):
        ...                                  # start the level; return the first observation

    def call(self, name, arguments):
        return getattr(self, name)(**arguments)

    def profile(self):
        return {"kind": "game", "name": "mygame", "control_hz": 20,
                "screen": {"width": 1280, "height": 720}}

    # state, tick, observe, claim_outcome, outcome ...


def create_environment(**options):
    return MyGame(**options)
```

The `fakegame` bench, a made-up game drawn with numpy, is a complete small worker to
read and copy.

## 2. Serve it

```bash
harness serve --factory mygame.worker:create_environment --port 8765
```

The worker prints one line with its address once it listens. It answers one request at
a time on this computer only; to serve it to another computer, set
`HARNESS_WORKER_TOKEN`, which every request must then carry.

## 3. Check every step

Every command passes the worker's own check before it acts. The check rejects commands
that are bugs (malformed, out of range, a jump no controller would make) and changes
nothing else: it never clamps, shortens or slows a command. Nothing the agent writes or
learns can turn it off. A game's check also holds fairness caps, such as how far the
view may turn in one period, so that what the agent does is play a person could match.
Use the check of your kind, and set its limits in the embodiment.

## 4. The bench

```toml
# benches/mygame/bench.toml
name = "mygame"
summary = "My game, played from its pixels"
kind = "game"
embodiment = "mygame"
factory = "mygame.worker:create_environment"
tasks = "\"play\": reach the end of the first level"

[environment]                       # the worker's own Python environment
python = "3.12"
requirements = ["pillow==12.1.1", "numpy==2.4.4"]
imports = ["PIL", "numpy"]
```

With a bench, `harness run` starts the worker by itself, in an environment of its own,
for each task and seed, and scores the result:

```toml
# experiments/mygame.toml
description = "My game, first level"
bench = "mygame"
tasks = ["play"]
seeds = [0, 1, 2]
```

```bash
harness run experiment experiments/mygame.toml --dry-run
```

A bench may also give hooks in Python for what its tasks need: expanding task groups,
options for each worker, how many run side by side.

## 5. Ship it

Put the worker, the embodiment, the bench, its experiments and any skills for it in a
package ([Write a package](/docs/extend/packages/)). A run that needs the environment
then installs the package by itself, and the agent can
[learn the environment](/docs/learn/learn-an-environment/) before it works in it.
