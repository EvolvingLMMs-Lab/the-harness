# Environments

The harness itself is standard-library Python and installs with npm or pip:
`npm install -g @lmmslab/harness`, `pip install the-harness`, or `pip install -e .` in a checkout. Everything a run needs
beyond it is installed the first time a run needs it, or ahead of time with
`harness install <name>`: each service and each benchmark gets an environment of its
own under `~/.cache/harness/envs/` (`HARNESS_HOME` moves it), built from the
`[environment]` table of its manifest (`services/<name>.toml`,
`benches/<name>/bench.toml`).

This folder holds the pinned core (`constraints.txt`). What the environments of services and
benchmarks share is in the packages that bring them (their `environment/` folders): the pins
every install respects, and whatever a package's own environment needs to build.

Every install runs under the pins, so no service or benchmark can move a pinned
dependency: a package that cannot be installed under them fails instead of
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
to install; that machine also sets what those environments would set.
