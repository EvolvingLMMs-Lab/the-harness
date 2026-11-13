---
title: "Install"
description: "Install The Harness with npm, pip or uv, connect a model, check the computer with harness doctor, and remove it again."
---

```bash
npm install -g @lmmslab/harness
```

or with pip:

```bash
pip install the-harness
```

or, to keep it in an environment of its own:

```bash
uv tool install the-harness
```

The Harness needs Python 3.11 or newer. It is a small, pure-Python package: no
PyTorch, no model weights, no particular environment. The command is `harness`, and the
Python package is `harness`.

## Connect a model

```bash
harness
```

The first run asks which provider and model to use and for the provider's key, checks
the key with the provider, and keeps the answers in `~/.harness/config.toml`, readable
by you only. Then it opens the conversation. A key already in your environment, such as
`OPENROUTER_API_KEY`, is reused; when the provider selector asks for a key, leave it blank to keep the one found. Custom endpoints may leave the key empty when they do not require authentication. [Models and providers](/docs/configure/models/)
lists the providers and how to change the model later.

## Check the computer

```bash
harness doctor
```

`harness doctor` checks the core, whether a model is set up, and the installed packages.
Each missing item comes with the line that fixes it. It exits with 1 while anything is
missing, and `--json` prints the same for scripts.

## Platforms

| System | What works |
|---|---|
| Windows | everything; a display of its own runs in a virtual machine |
| macOS | everything; a display of its own runs in a virtual machine; allow **Screen Recording** and **Accessibility** when asked |
| Linux | everything; the desktop needs an X11 session (on Wayland, use a background browser or a display of its own) |

A background browser needs Google Chrome. Robots, simulators and local models that need
a GPU expect an NVIDIA GPU with a recent driver; everything else runs on a laptop.

## What installs later

The first install is only the core. The rest arrives the first time a task needs it:

- **Packages.** A conversation in a background browser installs `browser`, one on your desktop `computer`. [Packages](/docs/configure/packages/) has the
  setting that decides whether it asks first.
- **Environments.** A package that needs Python libraries gets an environment of its
  own, so their dependencies never conflict. With [uv](https://docs.astral.sh/uv/)
  installed, The Harness also fetches the Python versions they need.
- **Model weights**, for a model that runs on this computer, the first time it starts.

To prepare the terminal, packages and their worker environments before going offline:

```bash
harness install --tui computer browser
```

`--tui` prepares the terminal libraries without starting a conversation. The named benches prepare their Python environments too. This does not install Chrome, operating-system permissions, virtual machines or remote model access; prepare those separately for the workspace you will use. You can run `harness install --tui` alone for terminal-only use.

## Where things are kept

| Folder | Holds | Moved by |
|---|---|---|
| `~/.harness/` | `config.toml` (your model, keys and settings), conversations, and what the agent learned | `HARNESS_DATA` |
| `~/.cache/harness/` | packages, environments, model weights and other things that can be rebuilt | `HARNESS_HOME` |

## Update

```bash
npm install -g @lmmslab/harness@latest   # or: pip install --upgrade the-harness
harness install --update
```

The first command updates the core, the second the packages, to the newest versions
that work with it.

## Uninstall

```bash
npm uninstall -g @lmmslab/harness   # or: pip uninstall the-harness
```

This leaves your data. To remove everything, also delete `~/.harness/` and
`~/.cache/harness/` (or the folders `HARNESS_DATA` and `HARNESS_HOME` point to).

Next: [Quickstart](/docs/getting-started/quickstart/).
