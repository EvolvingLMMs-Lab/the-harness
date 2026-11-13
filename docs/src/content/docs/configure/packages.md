---
title: "Packages"
description: "Install, update and remove packages; install on first use; pin a project's packages with a lock file; trust and offline registries."
---

pip/npm install only the small core of The Harness. **Packages** deliver environments
and their skills, alongside benchmarks and model services:

- `computer`: apps and windows, including browser workspaces.
- `browser`: websites in a background browser, within computer work.
- `workspace`: project files and processes in a bound working directory.
- `robot`: robots; Settings `robot.mode` selects this package's stack — **Fast** by default; **Max is TBD** ([Robot modes](/docs/extend/integrations/#robot-modes)); it is not in the public registry yet.

The [package directory](https://harness.lmms-lab.com/packages/) lists the official ones,
each with its README.

Installing core does not select an external app or agent for you. Automatic installation resolves the packages required by your requested task or selected capability; it does not choose an unrelated external product.

## Install

```bash
harness install workspace            # the newest version, and what it depends on
harness install browser@^0.5        # a version range
harness list                         # what is installed (--available: the registry's)
harness remove workspace
```

Installing a package also installs what it needs to run: the environments of its
services and benchmarks, their sources and model weights. `harness install --update`
updates packages to the newest version in their range, `harness list --available QUERY`
finds one by name, summary or what it provides, and `harness list NAME` shows what one
provides. Every command takes `--json`. `/packages` in the terminal provides the same package management. An installed package's own commands show
in `harness --help` once it is installed.

## Install on first use

You rarely need `harness install`. When a run needs something no installed package
provides (an environment, a skill, a benchmark, a service), The Harness looks it up in
the registry and installs the package that provides it, as `packages.auto_install`
says:

| Value | |
|---|---|
| `official` (default) | install packages from the official registry without asking |
| `ask` | ask first, in the app or the terminal |
| `off` | never: the run stops and says which package to install |

```toml
# ~/.harness/config.toml
[packages]
auto_install = "ask"
```

Automatic installation respects disabled packages, development sources and existing version ranges. If a stored choice cannot supply a capability, it reports the required repair or explicit selection. Updating a package does not enable it.

## Sources

A package can come from:

| Source | Example |
|---|---|
| the registry, with an optional version range | `workspace`, `browser@^0.5` |
| a git repository, at a ref, in a folder | `git:github.com/you/repo@main#packages/mine` |
| an archive URL | `https://example.com/mine-0.1.0.tar.gz` |
| a folder on this computer | `./mine` |

```bash
harness install ./mine --link        # use the folder where it is, while you develop it
```

## Trust

A package runs code on this computer with your access. Packages from the official
registry are trusted. Before installing one from anywhere else, The Harness shows what
it provides, which services it would start and which dependencies it would install, and
asks; `--yes` skips the question.

## A project's packages

To pin the packages a project uses, list them in a `harness.toml` at the project's
root:

```toml
# harness.toml
[packages]
computer = "^0.8"
mine = { source = "git:github.com/you/mine@v0.3", range = "^0.3" }
```

```bash
harness install                      # in the project: install them, and write harness.lock
harness install --project workspace  # add one to the project
```

`harness.lock` records the installed versions, checksums and sources; commit it with the project. Installing the declarations keeps compatible versions from the same registry in the lock; `--update --project` advances them. Mutable Git refs, URLs and local folders are checked again, so use immutable refs when you need reproducible source packages. Relative source paths are resolved from the folder containing `harness.toml`, including older `path:` records; `url:` archive records also remain usable. Installing the declarations preserves their source text and ranges.

Registry locks also work through mirrors that provide the same version and archive checksum. Missing or different locked content stops with an explicit update/named-install command, so a partial offline copy cannot silently downgrade the project. A named registry install clears an old development-source declaration; later installs keep that choice.

A project's packages are used only after you trusted the project, which
running `harness install` in it does. Without a project, your own packages are listed in
`~/.harness/config.toml`, under `[packages]`.

Every run records the packages it used, with their versions and checksums, in its lock
and its identity ([Configuration](/docs/configure/configuration/#the-files-that-describe-a-run)).

## Versions

A package version names the range of The Harness versions it works with, and one run
uses one version of each package. When two packages need versions that cannot go
together, the install stops and says which and why.

If an old browser installation requires computer 0.7, upgrade the pair with `harness install computer@^0.8 browser`; add `--project` for project packages. Updates consider the requirements of retained parents, including when replacing a dependency from a local folder. They refuse to change another package outside its recorded range; explicitly name it with a new range when you intend that change.

## Offline and private registries

`HARNESS_REGISTRY`, or `registry` under `[packages]`, points The Harness at another
registry, an https address or a folder:

```bash
export HARNESS_REGISTRY=/srv/harness-registry
harness install workspace
```

A registry is a folder with an `index.json` and one archive per version; a copy of the
official registry's folder works offline. [Write a package](/docs/extend/packages/)
describes how a package is made and published.

## Where they are kept

Installed versions are kept under `~/.cache/harness/packages/<name>/<version>-<sha>/`
and never changed once there. `harness remove` takes a package off your list (or the
project's, with `--project`).

Use `harness remove NAME --project` to remove a project dependency from both its declarations and lock. If you removed it by editing `harness.toml`, the same command removes its remaining lock entry before you install the other declarations.

Removing a package clears its installation record. Immutable cached files remain available to other projects and data directories sharing `HARNESS_HOME`; removal is not a global cache cleanup. Package mutation contention is reported immediately; an unanswered trust prompt does not hold the storage lock.
