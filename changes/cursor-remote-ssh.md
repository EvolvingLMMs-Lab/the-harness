---
core: minor
workspace: minor
agent: minor
app: minor
---
Implement end-to-end Cursor Remote-SSH parity: add a persistent stdlib-only SSH JSON-RPC bridge (`harness.core.ssh`) with recursive `~/.ssh/config` `Include` parsing and remote login-shell PATH hydration, add a first-class `ssh` workspace backend in `packages/workspace` (fixing `unsupported binding for none: ['folder']` on SSH tasks and loading remote `AGENTS.md`/`CLAUDE.md`), bring full SSH parity to Files, `@` Search, Git Review/Changes/Revert, Overview, and non-POSIX-safe PTY terminals, and upgrade the UI to a 2-step Connect Host -> Remote Folder Picker flow supporting arbitrary remote paths (e.g. `/pfs/...`) and directory symlinks.
<!-- zh -->
对照 Cursor Remote-SSH 从底向上重构端到端 SSH 能力：新增纯标准库持久 SSH JSON-RPC 桥（`harness.core.ssh`），支持递归解析 `~/.ssh/config` 的 `Include`、自动继承远端登录 shell 环境与全平台 shell 兼容；在 `packages/workspace` 中实现一等公民的 `ssh` 工作区（彻底解决 SSH 任务报错 `unsupported binding for none: ['folder']` 并支持读取远端 `AGENTS.md`/`CLAUDE.md`）；补齐 SSH 下的文件树、`@` 搜索、Git 审查/改动/撤销、概览分支与 PR 以及兼容 `fish`/`csh` 的远程交互终端；并将前端升级为“先连主机探测（含终端认证回退）→ 再浏览/直达任意远端目录（含 `/pfs/...` 与软链目录）”的二段式交互。
