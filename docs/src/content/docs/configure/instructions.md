---
title: "Instruction files"
description: "AGENTS.md: what you and a project tell every conversation, read as Codex and Claude Code read it."
---

An instruction file is Markdown that every conversation reads before its task: how to
build and test a project, its conventions, what to check before a change is done, or
how you like to work. The Harness reads `AGENTS.md` as Codex does, and a repository
written for Claude Code (`CLAUDE.md`) works as it is.

## Which files are read

- **Yours:** `~/.harness/AGENTS.md`, or `~/.harness/AGENTS.override.md` when it has text.
  Every conversation you start reads it, wherever it works.
- **The project's:** from the project's root down to the folder the conversation works in.
  - The root is the nearest folder above that holds `.git`. Without one, only the folder itself is read.
  - In each directory the first of `AGENTS.override.md`, `AGENTS.md` and `CLAUDE.md` with text is read.
  - A directory's `CLAUDE.local.md` is read after it.
  - Nothing above the root is read.
- **Below the folder:** a directory with its own file is read when a program first reads,
  writes or runs something in it. The model gets it with its next call, once per
  conversation.

Files closer to the folder come later, so their rules win over broader ones. A
conversation with no folder (the desktop, the browser, a game) reads only yours.
Experiments and benchmarks read none.

## What the model sees

The files open the conversation's first message, before the task, each under its path:

```
# AGENTS.md instructions for /home/you/project

<INSTRUCTIONS>
(from ~/.harness/AGENTS.md)
...

--- project-doc ---

(from AGENTS.md)
...
</INSTRUCTIONS>
```

They stay when the conversation is compacted. Files from below the folder are told again
when a program touches them after a compaction. A new conversation reads them all again,
so an edit applies from the next one.

## Imports and comments

- `@path` in a file brings in another file. The path is relative to the importing file,
  and `~` stands for your home folder.
- Imports chain at most four deep. An `@` inside a code span or a code block is text.
- Only files inside the project's root or `~/.harness` are imported. Any other import is
  left as text, and you are told.
- HTML comments on lines of their own are left out, so notes for people stay out of the
  model's context.

## Size

Yours and the project's each have `instructions.max_bytes` (32768 bytes):

- A file that crosses the limit is cut, and the files after it are left out.
- A file read below the folder is cut at 40,000 characters.
- A file over 4 MiB is not read.

Where something is cut, the model is told to read the rest with `read_file`. You see a
warning in the conversation.

## See and edit them

- **Terminal chat:** the conversation shows `instructions: AGENTS.md, ... (6.2 KB)` when it starts.
  - `/instructions` lists the files it read; `/instructions N` opens one in your editor.
  - `/init` has the agent write the project's `AGENTS.md`. When one is there already,
    it says what it would change and asks first.
- **Command line:** `harness instructions [FOLDER]` says what a conversation there reads and
  why any other file is left out. `--json` gives the same as JSON.
- **Traces:** every conversation records an `instructions` record, which `harness run --json`,
  the app and the Python API receive with the rest.

## Settings

Under `[instructions]` in `~/.harness/config.toml`, or in `/settings`:

| Key | Default | What it does |
| --- | --- | --- |
| `instructions.load` | `all` | `all`: yours and the project's. `user`: yours only. `off`: none |
| `instructions.files` | `AGENTS.override.md, AGENTS.md, CLAUDE.md` | the names tried in each directory, in order |
| `instructions.root_markers` | `.git` | what marks the project's root; empty: the folder alone |
| `instructions.max_bytes` | `32768` | bytes read at the start, for yours and for the project's; `0`: neither |
| `instructions.exclude` | none | files never read, as path patterns, e.g. `*/vendor/*/AGENTS.md` |

`harness --bare` and `harness run --bare` read no instruction files for that
conversation.

Agents you delegate to, such as Claude Code or Codex, read their own instruction files;
the Harness does not pass its own to them.
