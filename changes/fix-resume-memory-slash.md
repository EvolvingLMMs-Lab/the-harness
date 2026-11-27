---
harness: patch
agent: patch
app: patch
---

### English

- **Resume interrupted sub-tasks from their saved checkpoint**: `TaskApp.resume()` now supports resuming background agent tasks directly by their `conversations/<run>` directory, `Life._recover_interrupted()` and `Life.close()` preserve resumable `interrupted_task` checkpoints (with last completed step labels) without emitting false `[WinError 10061]` network error cards or duplicate outcomes, and typing `继续` / `continue` (or clicking the **Continue** button on interrupted/failed turns) resumes the interrupted sub-task directly instead of restarting the whole original prompt.
- **Full Memory entry viewing & editing**: `Identity._index()` no longer hard-truncates `MEMORY.md` entries mid-word at 100 characters, and `/api/app/rules` + Customizations › Rules now list every `memory/*.md` entry for full reading, editing, and deletion with automatic `MEMORY.md` index rebuilds.
- **Restore `/` slash command and `@` file mention popups**: Removed `overflow: hidden` on `.pg-compose` that was clipping `.pg-ac` completely, preloaded identity skills for `/` completion, expanded built-in slash commands (`/continue`, `/new`, `/stop`, `/memory`), and added artifact + empty-project hints to `@` mentions.

### 中文

- **支持小任务断点续跑与重启优雅收尾**：`TaskApp.resume()` 支持按 `conversations/<run>` 目录直接恢复后台子任务的 `conversation.json` 断点；`Life.close()` 与 `_recover_interrupted()` 保留可续跑的 `interrupted_task`（含已完成步骤摘要）且不再因关停服务产生 `[WinError 10061]` 假网络报错或重复结果卡片；输入「继续」或点击中断/失败卡片上的 **「继续」** 按钮会直接续跑中断的小任务，不再把最初整条大指令重发一遍。
- **完整查看与编辑 Memory 记忆条目**：修复 `MEMORY.md` 索引在 100 字符处把单词拦腰截断的问题，并在「自定义 › 规则」中直接列出 `memory/*.md` 全部完整记忆条目（支持查看、编辑、删除并自动同步索引）。
- **修复输入框 `/` 命令与 `@` 文件引用弹层不可见**：移除 `.pg-compose` 上误裁切 `.pg-ac` 弹层的 `overflow: hidden`，启动时预加载已学会技能，补全 `/continue`、`/new`、`/stop`、`/memory` 等常用命令，并让 `@` 支持引用当前对话的方案文档与未绑定项目提示。
