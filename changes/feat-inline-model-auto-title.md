---
agent: patch
---

### English

- **Model-generated auto-titles for all backends (including ACP / external agents / local models) with zero extra calls**:
  - When a new chat still lacks a model-generated title (`title_source == "default"` or temporary rule-based `title_fallback == True`), `Life.notes()` asks the dialogue model to include a concise `"chat_title"` field (3–7 words, same language, ≤ 48 chars) inside its Turn-1 JSON action.
  - `Session._decide()` extracts `"chat_title"` (or `"title"` on `reply`/`task`, avoiding collision with `write_artifact`/`calendar`) and upgrades the chat title immediately via `Chats.set_auto_title(..., fallback=False)` before running long tasks, pushing updates over SSE with zero extra subprocesses or API calls.
  - Manual user renames (`title_source == "user"`) and existing model titles are never overwritten.

### 中文

- **全后端（含 ACP / 外部 Agent / 本地模型）零额外开销的模型自动取名**：
  - 当新对话尚未拥有模型生成的标题（`title_source == "default"` 或仅处于临时规则兜底 `title_fallback == True`）时，`Life.notes()` 在首轮提示模型于 JSON 动作中顺带附带精炼的 `"chat_title"` 字段（与用户同语言、3～7 词、≤ 48 字符）。
  - `Session._decide()` 拿到首轮 JSON 后立刻提取 `"chat_title"`（`reply`/`task` 也兼容 `"title"`，不与 `write_artifact`/`calendar` 冲突），在执行耗时任务前就通过 `Chats.set_auto_title(..., fallback=False)` 实时更新标题并通过 SSE 推送，无需为 ACP 额外拉起子进程或增加 API 调用。
  - 用户手动重命名（`title_source == "user"`）及已生成的模型标题永远不会被覆盖。
