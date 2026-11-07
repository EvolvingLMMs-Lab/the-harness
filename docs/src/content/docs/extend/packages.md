---
title: "Write a package"
description: "Bundle skills, an environment, experiments, services or Agent Skills into a package others can install."
---

A **package** is a folder with a `package.toml`. Everything The Harness can do beyond
its core comes in one: an environment and its worker, skills and their prompts,
reactive rules, experiments, model services, Agent Skills, settings, even CLI commands.
You install a package from the registry, a git repository, an archive or a folder
([Packages](/docs/configure/packages/)).

## package.toml

```toml
[package]
name = "mine"
version = "0.1.0"
summary = "Save and export documents in the editors this team uses"
harness = ">=1.0,<2"              # the versions of The Harness it works with
depends = { computer = "^1.0" }   # other packages, by name and range
platforms = ["windows", "macos", "linux"]
license = "MIT"
homepage = "https://github.com/you/mine"

[provides]
commands = { mine-report = "mine.report:main" }   # adds `harness mine-report`
```

| Key | |
|---|---|
| `name` | lowercase letters, digits and hyphens |
| `version` | `MAJOR.MINOR.PATCH`; a published version never changes |
| `summary` | one line: what it lets the agent do |
| `harness` | the range of The Harness versions it works with (default: any) |
| `depends` | other packages it needs, by name and version range |
| `platforms` | `windows`, `macos`, `linux` (default: all) |
| `homepage`, `license` | for people |

## Workspace providers

Register a host module in `package.toml`:

```toml
[provides]
host = "my_package.host"
```

Its `Workspaces(directory, settings)` implements `harness.sdk.WorkspaceProvider`.
`kinds` declares its names; `accepts` selects a provider for binding inputs; `kind`
chooses its default. `bind` validates inputs and returns worker options plus metadata,
including any inheritance from a parent conversation. `bench`, `tree`, `builtin_skills`
and `extra_skills` supply the environment configuration. `acquire`, `of`, `release` and
`close` own resources. Managed execution and presentation are optional capabilities.

The host discovers every installed provider, rejects duplicate kinds and routes calls.
It neither starts a native process nor installs a computer backend as a fallback. Install
the desired package first; ambiguous defaults require `--workspace KIND`. Backend settings
belong in the package's `settings.toml`. Shared lease accounting is available as
`WorkerPool`; browser transports, project roots and process cleanup stay in their packages.
Environment-independent skills may declare `embodiments = ["*"]`; this resolves against
installed kinds, so a new environment does not require editing core skill manifests.

## What it provides

Everything else is found by its place in the folder:

```text
mine/
├── package.toml
├── README.md                  shown on the package's page
├── CHANGELOG.md
├── skills/<name>/             skills: skill.toml, __init__.py, prompt.md
├── agent-skills/<name>/       Agent Skills: SKILL.md and its files
├── embodiments/<name>/        environments the agent can act in: embodiment.toml
├── benches/<name>/            tasks and their worker: bench.toml
├── services/<name>.toml       model services
├── experiments/<name>.toml    experiments: harness run <name>
├── profiles/<name>.toml       agent configurations
├── prompts/                   prompt text for its environments
├── settings.toml              sections of the app's settings
├── config_keys.toml           configuration keys it reads, with what each does
└── tests/                     its tests
```

`[provides]` may also list names of what the folders contain, to say what the package
is for. The registry indexes all of it, which is how a run finds the package that
provides an environment, a skill or a service it lacks.

## Pages of its own

A package with a page names a host module in `package.toml`, and the session host
serves what that module declares beside the app:

```toml
[provides]
host = "harness_mine.host"
```

```python
# harness_mine/host.py
pages = {"/mine": "mine.html"}    # ui/static/mine.html at /mine
```

The page's other files are at `/static/mine/<file>` (`ui/static/<file>` of the package,
subfolders included). `/` stays the app's page; when the app is not installed, it is the
page of the first package that declares `/`. A page opens with the session key in its
address (`?token=...`), which the server keeps in a cookie for the page's requests.

The same module may give the page an API of its own, at `/api/<package>/<name>`:

```python
def inbox(server, data):          # data: a GET's query, a POST's JSON body
    return {"topics": []}         # answered as JSON

api = {"inbox": inbox}            # GET or POST /api/mine/inbox
```

Its routes take the same session key as the rest of the session host's API; a
`ValueError` or `KeyError` answers 400 with its text. The core's own routes come first.

A frontend may start the assistant's conversations with a profile of its own: skills
only those conversations have, and text added to their system prompt.

```python
profiles = {"mine": Path(__file__).parent.parent / "profiles" / "mine.toml"}
```

```toml
# profiles/mine.toml
description = "Conversations the mine page starts"
skills = ["report"]        # optional skills of the package; off in every other conversation
prompt = "../prompts/mine.md"
```

`POST /api/app/conversations {text, profile: "mine"}` starts one; a conversation started
without it has neither the skills nor the prompt.

## The SDK

A package's Python code imports only `harness.sdk`, the standard library, its own
modules, the packages it depends on, and third-party modules it declares. `harness.sdk`
is the stable interface for packages: sessions and skills, events and traces, the
`ClosedLoop` class, embodiments and benches, service clients, settings and paths. Its
incompatible changes come only with a new major version of The Harness, so a package
that names `harness = ">=1.0,<2"` keeps working through 1.x.

## Develop it

```bash
harness install ./mine --link    # use the folder in place: edits apply to the next run
harness list mine                # what The Harness found in it
```

Write tests in `tests/` the way the core's are written: they run with the package
installed in a clean home folder before a release.

## Publish it

- **From git**: push the folder to a repository and share the source,
  `git:github.com/you/repo@v0.1.0#mine`. Anyone can install it with `harness install`
  after confirming what it provides.
- **As an archive**: a `.tar.gz` of the folder at an https address.
- **In a registry**: a registry is a folder with an `index.json` and one archive per
  version, served over https or used locally with `HARNESS_REGISTRY`. The official
  registry lists the packages maintained with The Harness; to propose one, open an issue
  in its repository.

The [package directory](https://harness.lmms-lab.com/packages/) shows each official
package's README, so write it for someone who installs the package: what it does, what
it needs outside Python, how to use it, its settings and its limits.
