# Environments

The harness itself is standard-library Python and installs with npm or pip:
`npm install -g @lmmslab/harness`, `pip install the-harness`, or `pip install -e .` in a checkout. Everything a run needs
beyond it is installed the first time a run needs it, or ahead of time with
`harness install <name>`: each service and each benchmark gets an environment of its
own under `~/.cache/harness/envs/` (`HARNESS_HOME` moves it), built from the
`[environment]` table of its manifest (`services/<name>.toml`,
`benches/<name>/bench.toml`).

This folder holds the pinned core (`constraints.txt`: the browser benchmark's
environment, and `install.sh` of an exported XPolicyLab policy). What the environments of
services and benchmarks share is the local-models package's `environment/`:

| File | Used by |
|---|---|
| `lock/pip-freeze.txt` | the pins every service's and benchmark's environment installs under (`constraints = "environment/lock/pip-freeze.txt"`) |
| `requirements-skills.txt` | what `install.sh` of an exported XPolicyLab policy installs into RoboDojo's policy environment: the packages of the analytic and learned skills |
| `cuda_toolkit.sh` | the CUDA 12.8 build toolkit cuRobo is compiled with (RoboDojo's and RoboTwin's environments) |

RoboTwin's two source edits and its own cuRobo build are the robotwin package's
(`environment/robotwin_edits.py`, `environment/robotwin_curobo.sh`).

Every install runs under the pins, so no service or benchmark can move torch, numpy,
Isaac Sim or websockets: a package that cannot be installed under them fails instead of
upgrading the core. An environment's directory is named by a hash of everything that
decides what is installed (its table and the pins, comments excluded), so changing a pin
builds the environments that use it anew the next time a run needs them and leaves the
others as they are.

The documentation site is not Python: it is a Deno project with its own lock
(`docs/deno.json`, `docs/deno.lock`; see `docs/README.md`).

## Changing a pin or adding a dependency

A dependency of a service or benchmark goes into the `requirements` of its manifest; a
pin goes into `lock/pip-freeze.txt`. Install it with `harness install <name>`, run
something that uses it, and commit the manifest and the pins together.

## One interpreter for everything

`HARNESS_ENVIRONMENTS=project` (or `environments = "project"` in a deploy) installs
nothing but weights: every service and worker runs in the interpreter of the harness
itself. It is for a machine where one environment already holds everything, not a way
to install; that machine also sets what those environments would set, such as
`OMNI_KIT_ACCEPT_EULA=YES` for RoboDojo's workers.

## Known deviations from upstream

- `isaacsim-kernel` declares `websockets==12.0`, which only Kit's asset-search
  extensions use; headless simulation does not load them. XPolicyLab policy servers
  need the websockets 13+ asyncio API, so RoboDojo's environment overrides it with 17.1
  (`overrides` in `benches/robodojo/bench.toml`).
