---
agent: minor
app: minor
external-agents: minor
core: minor
---
Add a unified slash command architecture across Desktop/Web App and TUI aligned with Claude Code, Antigravity, Codex, Cursor, and ACP: built-in workflows (`/goal`, `/learn`, `/plan [task]`, `/grill-me`, `/schedule`, `/review`, `/init`, `/boost`, `/teamwork`), full argument-aware action commands (`/compact [focus]`, `/rename <title>`, `/rewind [N]`, `/effort [level]`, `/diff`, `/context`, `/usage`, `/status`, `/memory`, `/rules`, `/skills`, `/mcp`, `/calendar`, `/export`, `/copy`, `/settings`, `/help`), automatic discovery of `SKILL.md` and `.harness/commands` / `.claude/commands` / `.cursor/commands` Markdown commands with `$ARGUMENTS` expansion, and live ACP `available_commands_update` passthrough.
<!-- zh -->
新增统一斜杠命令架构（桌面端/Web 端与终端 TUI 共用单一后端内核），对齐 Claude Code、Antigravity、Codex、Cursor 与 ACP 标准：内置高频工作流命令（`/goal`、`/learn`、`/plan [任务]`、`/grill-me`、`/schedule`、`/review`、`/init`、`/boost`、`/teamwork`）、全量带参动作命令（`/compact [保留重点]`、`/rename <标题>`、`/rewind [N]`、`/effort [档位]`、`/diff`、`/context`、`/usage`、`/status`、`/memory`、`/rules`、`/skills`、`/mcp`、`/calendar`、`/export`、`/copy`、`/settings`、`/help`），自动发现 `SKILL.md` 及 `.harness/commands` / `.claude/commands` / `.cursor/commands` 自定义命令并支持 `$ARGUMENTS` 后端静默展开，同时透传外部 ACP Agent 广告的原生命令。
