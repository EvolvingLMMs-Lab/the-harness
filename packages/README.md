# Packages

What the harness can do beyond its core comes in packages (`src/harness/packages/`):
`harness install NAME` installs one from the registry at
`https://harness.lmms-lab.com/registry`, and a task installs what it needs the first
time it needs it (`packages.auto_install`).

This folder holds the official packages, each `<name>/` with its `package.toml`. They
are not part of the harness's wheel: each is built and published to the registry on
its own, with the tools in `tools/`:

| Tool | Does |
| --- | --- |
| `tools/check.py [NAMES]` | Each package loads, and its Python imports only `harness.sdk`, the standard library, its own modules, the packages it depends on and third-party modules. |
| `tools/build.py [NAMES] [--out dist]` | Deterministic package files (`<name>-<version>.tar.gz`) and their sha256. |
| `tools/release.py NAME --registry DIR [--commit]` | Check, refuse a version that is published already, install it with a clean HOME from a copy of the registry and run its `tests/`, then add it to the registry directory (a worktree of this repository's `registry` branch, which only grows). |

The registry's layout and `index.json` are described in
`src/harness/packages/registry.py`; the site publishes it with `deno task registry`
(`docs/README.md`).
