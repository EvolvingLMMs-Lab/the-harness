---
core: minor
---
Conversations read instruction files, as Codex and Claude Code do: yours, `~/.harness/AGENTS.md`, and the project's, from its root (the nearest folder with `.git`) down to the conversation's folder, one per directory: `AGENTS.override.md`, `AGENTS.md`, or `CLAUDE.md`, then that directory's `CLAUDE.local.md`. `@path` imports another file. Settings `instructions.load`, `.files`, `.root_markers`, `.max_bytes` (32768) and `.exclude` say what is read; `harness --bare` and `harness run --bare` read none.
<!-- zh -->
对话会像 Codex 和 Claude Code 那样读取说明文件：你自己的 `~/.harness/AGENTS.md`，以及项目的说明文件，从项目根（最近的含 `.git` 的文件夹）一直读到对话所在的文件夹，每个目录读一个：`AGENTS.override.md`、`AGENTS.md` 或 `CLAUDE.md`，再加上该目录的 `CLAUDE.local.md`。`@path` 可以引入另一个文件。设置项 `instructions.load`、`.files`、`.root_markers`、`.max_bytes`（32768）和 `.exclude` 决定读取哪些；`harness --bare` 和 `harness run --bare` 一个都不读。
