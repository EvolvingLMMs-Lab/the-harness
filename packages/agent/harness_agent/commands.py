"""Unified slash command registry, discovery, and prompt expansion.

Single source of truth shared across Desktop/Web App, TUI, and channels.
Covers three first-principles primitives aligned with Claude Code, Antigravity,
Codex, Cursor, and ACP v1:

1. Action      Deterministic host/UI command (no model tokens; handled by frontend/TUI).
2. Workflow    Built-in high-leverage agent workflow (/goal, /learn, /plan, /grill-me,
               /schedule, /review, /init, /boost, /teamwork), plus identity skills
               (SKILL.md) and project/user custom Markdown commands
               (.harness/commands, .claude/commands, .cursor/commands) with
               $ARGUMENTS / $1..$9 expansion.
3. Passthrough Native commands advertised by an external ACP agent via
               `available_commands_update`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
from typing import Any

from harness.sdk import home as harness_home


COMMAND_RE = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9_.:-]*)(?:\s+(.*))?$", re.S)
VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,80}$")
VALID_MODES = frozenset({"plan", "ask", "auto", "full"})
MAX_CUSTOM_FILES = 100
MAX_CUSTOM_BYTES = 32_768
MAX_SCAN_DEPTH = 3


@dataclass(frozen=True)
class ExpandedCommand:
    """Result of expanding a leading `/command [args]` for the model."""

    name: str
    kind: str  # "workflow" | "skill" | "custom"
    args: str
    prompt: str
    mode: str | None = None
    source: str = ""


# ── Built-in Workflow Templates (aligned with Antigravity + Claude Code + Codex) ──

BUILTIN_WORKFLOWS: tuple[dict[str, Any], ...] = (
    {
        "name": "goal",
        "group": "workflow",
        "icon": "bolt",
        "title_en": "Goal loop",
        "title_zh": "目标闭环执行",
        "description_en": "Execute relentlessly with verifiable checks until the goal is achieved",
        "description_zh": "设定可验证验收标准，自动排查修复直到目标彻底达成",
        "arg_hint_en": "<goal>",
        "arg_hint_zh": "<目标>",
        "needs_arg": True,
        "keywords": "goal loop autonomous overnight verify 目标 长任务 闭环 验收",
        "template": (
            "[Slash command: /goal]\n"
            "Goal: $ARGUMENTS\n\n"
            "Operating mode (persistent goal execution):\n"
            "1. Define clear, objective, verifiable completion criteria before making changes.\n"
            "2. Break work into concrete milestones and keep progress visible (update a plan/progress artifact when the task spans multiple steps).\n"
            "3. Work autonomously end-to-end: when a command, build, or test fails, diagnose the root cause, fix it, and re-verify without stopping prematurely to ask trivial check-in questions.\n"
            "4. Only pause to ask the user if you hit a genuine ambiguity, missing credential, or irreversible external action.\n"
            "5. Do not declare completion until every acceptance criterion has been verified with real execution evidence."
        ),
    },
    {
        "name": "learn",
        "group": "workflow",
        "icon": "plugins",
        "title_en": "Persist learning",
        "title_zh": "沉淀经验与技能",
        "description_en": "Turn corrections or workflows from this chat into a durable skill, memory, or rule",
        "description_zh": "将当前对话中的纠正、偏好或流程沉淀为可复用的技能、记忆或规则",
        "arg_hint_en": "[topic or lesson]",
        "arg_hint_zh": "[主题或要记住的内容]",
        "needs_arg": False,
        "keywords": "learn remember skill rule memory 沉淀 学习 记住 技能 规则 记忆",
        "template": (
            "[Slash command: /learn]\n"
            "Focus: $ARGUMENTS\n\n"
            "Persist reusable knowledge from this conversation into The Harness's durable storage:\n"
            "1. Review recent user corrections, recurring preferences, non-obvious setups, or solved workflows in this chat (prioritizing the Focus above if provided).\n"
            "2. Choose the right durable destination:\n"
            "   - Reusable multi-step procedure -> save or update a SKILL.md skill in this identity's skills library.\n"
            "   - Project-specific convention, build/test command, or architecture rule -> update the project's AGENTS.md.\n"
            "   - User preference or cross-project fact -> save into long-term memory.\n"
            "3. Keep what you write concise, specific, and actionable (no vague platitudes or duplicate entries).\n"
            "4. Report clearly what you persisted and the exact file/entry updated."
        ),
    },
    {
        "name": "plan",
        "group": "workflow",
        "icon": "plan",
        "title_en": "Plan mode",
        "title_zh": "规划模式",
        "description_en": "Switch to read-only Plan mode and produce a step-by-step implementation plan",
        "description_zh": "切换只读规划模式；带任务参数时直接产出可审查的分步实施方案",
        "arg_hint_en": "[task]",
        "arg_hint_zh": "[规划任务]",
        "needs_arg": False,
        "mode": "plan",
        "keywords": "plan architecture spec readonly 计划 规划 方案 设计",
        "template": (
            "[Slash command: /plan]\n"
            "Task to plan: $ARGUMENTS\n\n"
            "Operating mode (read-only architectural planning):\n"
            "1. Inspect the relevant codebase, contracts, and existing patterns before proposing changes.\n"
            "2. Do not modify project source files or run side-effectful commands while planning.\n"
            "3. Produce a concise, first-principles implementation plan (files to touch, data flow, edge cases, minimal verification criteria) and save it as a reviewable plan artifact when appropriate.\n"
            "4. Highlight only genuine decisions or tradeoffs that need the user's input before execution."
        ),
    },
    {
        "name": "grill-me",
        "group": "workflow",
        "icon": "chat",
        "title_en": "Grill me on plan",
        "title_zh": "深度需求拷问",
        "description_en": "Interview me relentlessly to resolve ambiguities and design decisions before coding",
        "description_zh": "写代码前通过高密度问答逐一敲定模糊需求、边界条件与架构权衡",
        "arg_hint_en": "<idea or design>",
        "arg_hint_zh": "<想法或设计>",
        "needs_arg": True,
        "keywords": "grill interview requirements clarify design 拷问 访谈 需求 澄清 权衡",
        "template": (
            "[Slash command: /grill-me]\n"
            "Topic: $ARGUMENTS\n\n"
            "Run a sharp, structured design interview before any implementation:\n"
            "1. Inspect existing code/context first so you never ask questions you can answer directly from the repo.\n"
            "2. Ask 3-5 high-leverage, concrete questions covering unclear requirements, failure modes, boundaries, and architectural tradeoffs (offer a recommended default for each).\n"
            "3. Wait for the user's answers, follow up on remaining gaps if needed, and finish with a crisp confirmed decision summary ready for implementation."
        ),
    },
    {
        "name": "schedule",
        "group": "workflow",
        "icon": "calendar",
        "title_en": "Schedule task",
        "title_zh": "定时调度任务",
        "description_en": "Schedule a one-shot or recurring task on the identity calendar",
        "description_zh": "在日历中创建一次性或每日/每周定时自动执行的任务",
        "arg_hint_en": "<when> <task>",
        "arg_hint_zh": "<时间/频率> <任务>",
        "needs_arg": True,
        "keywords": "schedule cron timer automation loop calendar 定时 调度 周期 提醒 自动化",
        "template": (
            "[Slash command: /schedule]\n"
            "Schedule request: $ARGUMENTS\n\n"
            "Set up a scheduled execution on this identity's Calendar:\n"
            "1. Parse the desired trigger time/cadence (one-shot time, daily, or weekly) and exact task prompt from the request.\n"
            "2. If time or recurrence is ambiguous, ask one brief clarifying question before creating it.\n"
            "3. Record the planned entry on the identity's calendar (kind='task' or 'reminder', with repeat='daily'/'weekly' when recurring) so The Harness wakes automatically when due.\n"
            "4. Confirm the scheduled title, next run time, and recurrence briefly."
        ),
    },
    {
        "name": "review",
        "group": "workflow",
        "icon": "log",
        "title_en": "Code review",
        "title_zh": "代码审查",
        "description_en": "Review uncommitted changes, branch diff, or a PR for bugs and regressions",
        "description_zh": "审查未提交改动、分支差异或指定 PR 的缺陷、安全边界与回归风险",
        "arg_hint_en": "[scope or PR]",
        "arg_hint_zh": "[范围或 PR]",
        "needs_arg": False,
        "keywords": "review pr diff audit bug security 审查 代码 评审 检查",
        "template": (
            "[Slash command: /review]\n"
            "Scope: $ARGUMENTS\n\n"
            "Perform a rigorous engineering code review:\n"
            "1. Inspect the relevant git diff (uncommitted changes by default, or the specified commit range / branch / PR).\n"
            "2. Focus on real issues: correctness bugs, edge cases, race conditions, security/access-control flaws, contract mismatches, and missing tests for changed behavior.\n"
            "3. Report findings ordered by severity with exact file paths, line numbers, concrete impact, and minimal recommended fixes. Skip style nitpicks.\n"
            "4. If no blocking issues are found, explicitly state what you verified and any remaining verification gaps."
        ),
    },
    {
        "name": "init",
        "group": "workflow",
        "icon": "file",
        "title_en": "Init AGENTS.md",
        "title_zh": "初始化 AGENTS.md",
        "description_en": "Scan the workspace and create or refine the project's AGENTS.md guide",
        "description_zh": "扫描项目结构与构建测试约定，生成或增量完善项目 AGENTS.md",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "init agents claude md setup guide 初始化 项目规范",
        "template": (
            "[Slash command: /init]\n"
            "Additional guidance: $ARGUMENTS\n\n"
            "Create or refine the project's AGENTS.md:\n"
            "1. Inspect the repository layout, build/lint/test commands, package manifests, architecture boundaries, and any existing AGENTS.md or CLAUDE.md.\n"
            "2. Write (or incrementally improve) a concise, high-signal AGENTS.md capturing real commands, conventions, invariants, and gotchas verified from the codebase.\n"
            "3. Do not invent commands or bloat the file with generic advice; keep every line directly useful to future coding sessions."
        ),
    },
    {
        "name": "boost",
        "group": "workflow",
        "icon": "bolt",
        "title_en": "Deep boost mode",
        "title_zh": "深度攻坚模式",
        "description_en": "Deep first-principles analysis, multi-angle planning, and strict verification",
        "description_zh": "复杂研发/调研：第一性根因分析、多视角权衡与端到端严格验证",
        "arg_hint_en": "<complex task>",
        "arg_hint_zh": "<复杂任务>",
        "needs_arg": True,
        "keywords": "boost deep think thorough research verify 深度 攻坚 复杂 分析 验证",
        "template": (
            "[Slash command: /boost]\n"
            "Task: $ARGUMENTS\n\n"
            "Operating mode (deep engineering & verification):\n"
            "1. Start from first principles: verify the real runtime behavior and root cause directly before designing changes.\n"
            "2. Evaluate design alternatives against mature reference products and pick the minimal, bottom-up solution covering the broadest cases.\n"
            "3. Implement cleanly without workarounds or duplicated state.\n"
            "4. Validate with minimal, high-signal end-to-end checks (real execution/runtime behavior, not superficial mocks) and cross-check for regressions before concluding."
        ),
    },
    {
        "name": "teamwork",
        "group": "workflow",
        "icon": "plugins",
        "title_en": "Parallel teamwork",
        "title_zh": "多代理协作",
        "description_en": "Split a large project into parallel sub-tasks and integrate verified results",
        "description_zh": "将大型任务拆分为并行子任务协作推进，最后统一汇总验收",
        "arg_hint_en": "<project>",
        "arg_hint_zh": "<大型任务>",
        "needs_arg": True,
        "keywords": "teamwork swarm parallel subagent multi 协作 并行 多代理 拆分",
        "template": (
            "[Slash command: /teamwork]\n"
            "Project: $ARGUMENTS\n\n"
            "Operating mode (parallel decomposed execution):\n"
            "1. Decompose the project into clear, non-overlapping workstreams with explicit ownership and done criteria.\n"
            "2. Execute independent research, implementation, or verification tracks in parallel where supported (using sub-agents or background tasks when available).\n"
            "3. Integrate outputs cleanly, resolve cross-cutting interfaces, and run unified end-to-end verification across the combined result."
        ),
    },
)


# ── Built-in Action Catalog (deterministic UI/host commands, aligned with Claude Code / Codex / TUI) ──

BUILTIN_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "compact",
        "aliases": (),
        "group": "action",
        "icon": "context",
        "title_en": "Compact context",
        "title_zh": "压缩上下文",
        "description_en": "Summarize earlier turns to free context window (optional focus instructions)",
        "description_zh": "将早期对话压缩为摘要以释放上下文（可选指定保留重点）",
        "arg_hint_en": "[focus]",
        "arg_hint_zh": "[保留重点]",
        "needs_arg": False,
        "keywords": "compact summarize context shrink 压缩 上下文 摘要",
    },
    {
        "name": "new",
        "aliases": ("clear", "reset"),
        "group": "action",
        "icon": "edit",
        "title_en": "New chat",
        "title_zh": "新建对话",
        "description_en": "Start a fresh conversation",
        "description_zh": "开始一段全新对话",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "new clear reset fresh 新建 清空 重置 对话",
    },
    {
        "name": "continue",
        "aliases": (),
        "group": "action",
        "icon": "play",
        "title_en": "Continue",
        "title_zh": "断点续跑",
        "description_en": "Continue an interrupted task from its saved checkpoint",
        "description_zh": "继续未完成的任务（断点续跑）",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "continue resume checkpoint 继续 续跑",
    },
    {
        "name": "stop",
        "aliases": ("cancel",),
        "group": "action",
        "icon": "stop",
        "title_en": "Stop turn",
        "title_zh": "停止当前回合",
        "description_en": "Interrupt the running turn and keep work done so far",
        "description_zh": "立即中止当前执行回合",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "stop cancel abort interrupt 停止 取消 中断",
    },
    {
        "name": "rename",
        "aliases": (),
        "group": "action",
        "icon": "edit",
        "title_en": "Rename chat",
        "title_zh": "重命名对话",
        "description_en": "Set a new title for this conversation",
        "description_zh": "修改当前对话标题",
        "arg_hint_en": "<title>",
        "arg_hint_zh": "<新标题>",
        "needs_arg": True,
        "keywords": "rename title 重命名 标题",
    },
    {
        "name": "rewind",
        "aliases": ("undo",),
        "group": "action",
        "icon": "arrowLeft",
        "title_en": "Rewind",
        "title_zh": "回退消息",
        "description_en": "Undo back to an earlier turn (optionally restoring workspace files)",
        "description_zh": "回退到前第 N 条消息（可选恢复工作区文件）",
        "arg_hint_en": "[N]",
        "arg_hint_zh": "[步数]",
        "needs_arg": False,
        "keywords": "rewind undo revert checkpoint 回退 撤销 撤回",
    },
    {
        "name": "model",
        "aliases": ("models",),
        "group": "action",
        "icon": "model",
        "title_en": "Switch model",
        "title_zh": "切换模型",
        "description_en": "Choose model, effort, context window, and fast mode",
        "description_zh": "切换模型、思考强度、上下文窗口与快速模式",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "model switch provider 模型 切换",
    },
    {
        "name": "effort",
        "aliases": (),
        "group": "action",
        "icon": "sliders",
        "title_en": "Reasoning effort",
        "title_zh": "思考强度",
        "description_en": "Set reasoning effort level for this chat",
        "description_zh": "设置当前对话的思考强度（如 low / medium / high / xhigh）",
        "arg_hint_en": "[level]",
        "arg_hint_zh": "[档位]",
        "needs_arg": False,
        "keywords": "effort thinking reasoning 思考 强度 推理",
    },
    {
        "name": "mode",
        "aliases": (),
        "group": "action",
        "icon": "shield",
        "title_en": "Execution mode",
        "title_zh": "切换权限模式",
        "description_en": "Switch permission mode: plan, ask, auto, or full",
        "description_zh": "切换执行权限模式（plan / ask / auto / full）",
        "arg_hint_en": "[plan|ask|auto|full]",
        "arg_hint_zh": "[模式]",
        "needs_arg": False,
        "keywords": "mode permission 权限 模式",
    },
    {
        "name": "ask",
        "aliases": (),
        "group": "action",
        "icon": "shield",
        "title_en": "Ask mode",
        "title_zh": "询问模式",
        "description_en": "Confirm before edits and commands",
        "description_zh": "操作前逐项确认",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "ask confirm approve 询问 确认",
    },
    {
        "name": "auto",
        "aliases": (),
        "group": "action",
        "icon": "shield",
        "title_en": "Auto mode",
        "title_zh": "自动模式",
        "description_en": "Auto-execute inside workspace, confirm high-risk actions",
        "description_zh": "工作区内自动执行，高风险操作确认",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "auto workspace 自动",
    },
    {
        "name": "full",
        "aliases": (),
        "group": "action",
        "icon": "bolt",
        "title_en": "Full Access",
        "title_zh": "完整权限",
        "description_en": "Execute all actions without approval prompts",
        "description_zh": "免审批直接执行全部操作",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "full yolo bypass 完整 权限",
    },
    {
        "name": "project",
        "aliases": ("where",),
        "group": "action",
        "icon": "folder",
        "title_en": "Switch project",
        "title_zh": "切换项目",
        "description_en": "Bind a local folder, git worktree, or SSH remote workspace",
        "description_zh": "切换或打开本地文件夹、Worktree 或 SSH 远程项目",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "project folder ssh worktree 项目 目录 工作区",
    },
    {
        "name": "diff",
        "aliases": (),
        "group": "action",
        "icon": "changes",
        "title_en": "Review diff",
        "title_zh": "查看代码改动",
        "description_en": "Open the Changes / Diff review pane for this workspace",
        "description_zh": "打开当前工作区的审查与代码改动面板",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "diff changes git review 改动 差异",
    },
    {
        "name": "context",
        "aliases": (),
        "group": "action",
        "icon": "context",
        "title_en": "Context usage",
        "title_zh": "上下文占用",
        "description_en": "Inspect token breakdown across messages, rules, skills, and tools",
        "description_zh": "查看当前上下文各部分 Token 占用拆解",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "context tokens window breakdown 上下文 占用",
    },
    {
        "name": "usage",
        "aliases": ("cost", "stats"),
        "group": "action",
        "icon": "sliders",
        "title_en": "Usage & cost",
        "title_zh": "用量与费用",
        "description_en": "Open spending, token usage, and daily budget settings",
        "description_zh": "查看花费、用量统计与每日额度",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "usage cost spend budget stats 用量 费用 账单",
    },
    {
        "name": "status",
        "aliases": (),
        "group": "action",
        "icon": "overview",
        "title_en": "Session status",
        "title_zh": "当前状态",
        "description_en": "Show version, active model, permission mode, and workspace info",
        "description_zh": "查看版本、当前模型、权限模式与工作区状态",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "status info version health 状态 信息",
    },
    {
        "name": "memory",
        "aliases": (),
        "group": "action",
        "icon": "context",
        "title_en": "Memory",
        "title_zh": "长期记忆",
        "description_en": "View and edit long-term memory entries",
        "description_zh": "查看和编辑长期记忆",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "memory remember 记忆",
    },
    {
        "name": "rules",
        "aliases": (),
        "group": "action",
        "icon": "log",
        "title_en": "Rules",
        "title_zh": "规则与人设",
        "description_en": "View and edit AGENTS.md, project rules, and persona files",
        "description_zh": "查看和编辑全局规则、项目规则与人设文件",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "rules agents instructions persona 规则 人设",
    },
    {
        "name": "skills",
        "aliases": (),
        "group": "action",
        "icon": "plugins",
        "title_en": "Skills",
        "title_zh": "技能库",
        "description_en": "Browse, install, or manage skills",
        "description_zh": "浏览、安装与管理技能",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "skills plugins 技能 插件",
    },
    {
        "name": "mcp",
        "aliases": (),
        "group": "action",
        "icon": "plugins",
        "title_en": "MCP servers",
        "title_zh": "MCP 服务器",
        "description_en": "Manage connected MCP servers and tools",
        "description_zh": "管理已连接的 MCP 服务器与工具",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "mcp servers tools 工具 服务",
    },
    {
        "name": "calendar",
        "aliases": (),
        "group": "action",
        "icon": "calendar",
        "title_en": "Calendar",
        "title_zh": "日历与日程",
        "description_en": "Open scheduled tasks, reminders, and activity calendar",
        "description_zh": "打开定时任务、提醒与活动日历",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "calendar schedule agenda 日历 日程",
    },
    {
        "name": "export",
        "aliases": (),
        "group": "action",
        "icon": "file",
        "title_en": "Export chat",
        "title_zh": "导出对话",
        "description_en": "Download this conversation as Markdown",
        "description_zh": "将当前对话导出为 Markdown 文件",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "export markdown download 导出",
    },
    {
        "name": "copy",
        "aliases": (),
        "group": "action",
        "icon": "copy",
        "title_en": "Copy last reply",
        "title_zh": "复制上条回复",
        "description_en": "Copy the latest assistant response to clipboard",
        "description_zh": "将最新一条助手回复复制到剪贴板",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "copy clipboard 复制",
    },
    {
        "name": "settings",
        "aliases": ("config", "permissions"),
        "group": "action",
        "icon": "settings",
        "title_en": "Settings",
        "title_zh": "设置",
        "description_en": "Open application and agent settings",
        "description_zh": "打开应用与权限设置",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "settings config permissions preferences 设置 配置 权限",
    },
    {
        "name": "customizations",
        "aliases": (),
        "group": "action",
        "icon": "sliders",
        "title_en": "Customizations",
        "title_zh": "自定义中心",
        "description_en": "Manage skills, rules, memory, behavior tree, and MCP",
        "description_zh": "打开自定义中心（技能、规则、记忆、行为树、MCP）",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "customizations plugins skills rules 自定义 中心",
    },
    {
        "name": "help",
        "aliases": (),
        "group": "action",
        "icon": "keyboard",
        "title_en": "Help & shortcuts",
        "title_zh": "帮助与快捷键",
        "description_en": "Show keyboard shortcuts and available slash commands",
        "description_zh": "查看快捷键与可用斜杠命令速查",
        "arg_hint_en": "",
        "arg_hint_zh": "",
        "needs_arg": False,
        "keywords": "help shortcuts commands 帮助 快捷键 命令",
    },
)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse lightweight YAML frontmatter (`--- ... ---`) without external deps."""
    head: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        lines = text.splitlines()
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is not None:
            key: str | None = None
            block: str | None = None
            for line in lines[1:end_idx]:
                if line[:1] in (" ", "\t") and key:
                    piece = line.strip()
                    joined = "\n" if block == "|" else " "
                    head[key] = (head[key] + joined + piece) if head[key] else piece
                    continue
                k, sep, v = line.partition(":")
                if not sep or not k.strip() or k.lstrip().startswith("#"):
                    continue
                key = k.strip().lower()
                val = v.strip()
                block = val[:1] if val[:1] in (">", "|") and val.strip(">|+-0123456789 ") == "" else None
                head[key] = "" if block else val.strip('"').strip("'")
            body = "\n".join(lines[end_idx + 1 :])
    return head, body.strip()


def _first_line(body: str) -> str:
    for line in body.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:120]
    return ""


def _scan_markdown_commands(root: Path, *, scope: str) -> list[dict[str, Any]]:
    """Scan `<root>/**/*.md` for Claude Code / Cursor / Harness custom commands."""
    if not root.is_dir():
        return []
    try:
        base = root.resolve()
    except OSError:
        return []
    found: list[dict[str, Any]] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and len(found) < MAX_CUSTOM_FILES:
        cur, depth = stack.pop()
        try:
            entries = sorted(cur.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            if len(found) >= MAX_CUSTOM_FILES:
                break
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            try:
                resolved = entry.resolve()
                if base not in resolved.parents:
                    continue
            except OSError:
                continue
            if entry.is_dir():
                if depth < MAX_SCAN_DEPTH:
                    stack.append((entry, depth + 1))
                continue
            if not entry.is_file() or entry.suffix.lower() != ".md":
                continue
            try:
                raw = entry.read_bytes()[: MAX_CUSTOM_BYTES + 1]
                if len(raw) > MAX_CUSTOM_BYTES or b"\x00" in raw[:4096]:
                    continue
                text = raw.decode("utf-8", errors="replace")
            except OSError:
                continue
            meta, body = parse_frontmatter(text)
            if not body:
                continue
            if meta.get("user-invocable", "").lower() in ("false", "0", "no"):
                continue
            rel = entry.relative_to(root).with_suffix("")
            derived = ":".join(part.strip().lower().replace(" ", "-") for part in rel.parts if part.strip())
            name = (meta.get("name") or derived).strip().lstrip("/")
            if not VALID_NAME_RE.fullmatch(name):
                continue
            arg_hint = meta.get("argument-hint", "").strip()
            mode = meta.get("mode", "").strip().lower()
            desc = meta.get("description", "").strip() or _first_line(body)
            found.append({
                "name": name,
                "kind": "custom",
                "group": "custom",
                "icon": "command",
                "title_en": name,
                "title_zh": name,
                "description_en": desc,
                "description_zh": desc,
                "arg_hint_en": arg_hint,
                "arg_hint_zh": arg_hint,
                "needs_arg": bool(arg_hint and arg_hint.startswith("<")),
                "mode": mode if mode in VALID_MODES else None,
                "source": scope,
                "path": str(resolved),
                "template": body,
                "keywords": f"{name} {desc} {scope}",
            })
    return found


def _user_command_roots() -> list[tuple[Path, str]]:
    """Global user command directories (Harness, Claude Code, Cursor)."""
    user_home = Path.home()
    roots = [
        (harness_home() / "commands", "user:harness"),
        (user_home / ".harness" / "commands", "user:harness"),
        (user_home / ".claude" / "commands", "user:claude"),
        (user_home / ".cursor" / "commands", "user:cursor"),
    ]
    seen: set[str] = set()
    out: list[tuple[Path, str]] = []
    for path, scope in roots:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            out.append((path, scope))
    return out


def _project_command_roots(folder: Path | None) -> list[tuple[Path, str]]:
    if folder is None or not folder.is_dir():
        return []
    return [
        (folder / ".harness" / "commands", "project:harness"),
        (folder / ".claude" / "commands", "project:claude"),
        (folder / ".cursor" / "commands", "project:cursor"),
    ]


def _skill_commands(identity, skills: list[dict] | None = None) -> list[dict[str, Any]]:
    """Convert active identity skills (SKILL.md) into invocable slash commands."""
    rows: list[dict[str, Any]] = []
    skills_root = identity.directory / "skills"
    listed = list(skills) if skills is not None else []
    seen: set[str] = set()
    for row in listed:
        if not isinstance(row, dict) or row.get("archived") or row.get("evidence") == "undone":
            continue
        name = str(row.get("name") or "").strip()
        if not VALID_NAME_RE.fullmatch(name) or name in seen:
            continue
        sdoc = skills_root / name / "SKILL.md"
        meta: dict[str, str] = {}
        body = ""
        if sdoc.is_file() and not sdoc.is_symlink():
            try:
                raw = sdoc.read_text(encoding="utf-8", errors="replace")[:MAX_CUSTOM_BYTES]
                meta, body = parse_frontmatter(raw)
            except OSError:
                meta, body = {}, ""
        if meta.get("user-invocable", "").lower() in ("false", "0", "no"):
            continue
        desc = str(row.get("description") or meta.get("description") or _first_line(body) or "").strip()
        arg_hint = meta.get("argument-hint", "").strip()
        mode = meta.get("mode", "").strip().lower()
        template = body or f"Use the `{name}` skill to handle this request."
        seen.add(name)
        rows.append({
            "name": name,
            "kind": "skill",
            "group": "custom",
            "icon": "plugins",
            "title_en": name,
            "title_zh": name,
            "description_en": desc or f"Skill: {name}",
            "description_zh": desc or f"技能：{name}",
            "arg_hint_en": arg_hint,
            "arg_hint_zh": arg_hint,
            "needs_arg": bool(arg_hint and arg_hint.startswith("<")),
            "mode": mode if mode in VALID_MODES else None,
            "source": "skill",
            "template": f"[Skill: /{name}]\n{template}",
            "keywords": f"{name} {desc} skill 技能",
        })
    return rows


def _acp_command_rows(acp_commands: list[dict] | tuple[dict, ...] | None, *, agent_label: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in acp_commands or ():
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip().lstrip("/")
        if not VALID_NAME_RE.fullmatch(name) or name in seen:
            continue
        seen.add(name)
        desc = str(raw.get("description") or "").strip()
        inp = raw.get("input") if isinstance(raw.get("input"), dict) else {}
        hint = str(inp.get("hint") or "").strip()
        rows.append({
            "name": name,
            "kind": "acp",
            "group": "acp",
            "icon": "command",
            "title_en": name,
            "title_zh": name,
            "description_en": desc or (f"{agent_label} command" if agent_label else "ACP command"),
            "description_zh": desc or (f"{agent_label} 命令" if agent_label else "ACP 原生命令"),
            "arg_hint_en": hint,
            "arg_hint_zh": hint,
            "needs_arg": bool(hint),
            "source": f"acp:{agent_label}" if agent_label else "acp",
            "keywords": f"{name} {desc} acp {agent_label}".strip(),
        })
    return rows


def _render_template(template: str, args: str) -> str:
    """Substitute $ARGUMENTS and positional $1..$9 placeholders cleanly."""
    args_clean = args.strip()
    has_placeholder = "$ARGUMENTS" in template or bool(re.search(r"\$[1-9]\b", template))
    rendered = template.replace("$ARGUMENTS", args_clean or "(none specified)")
    if re.search(r"\$[1-9]\b", rendered):
        try:
            tokens = shlex.split(args_clean) if args_clean else []
        except ValueError:
            tokens = args_clean.split() if args_clean else []

        def _repl(match: re.Match[str]) -> str:
            idx = int(match.group(1)) - 1
            return tokens[idx] if 0 <= idx < len(tokens) else ""

        rendered = re.sub(r"\$([1-9])\b", _repl, rendered)
    if not has_placeholder and args_clean:
        rendered = f"{rendered.rstrip()}\n\nUser request:\n{args_clean}"
    return rendered.strip()


def discover(
    identity,
    *,
    folder: Path | None = None,
    skills: list[dict] | None = None,
    acp_commands: list[dict] | tuple[dict, ...] | None = None,
    agent_label: str = "",
) -> list[dict[str, Any]]:
    """Return the unified slash command catalog for a chat (without raw template bodies)."""
    # Precedence for prompt/custom overrides: project > user > skill > builtin workflow > builtin action.
    by_name: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []

    def _put(item: dict[str, Any], *, override: bool = False) -> None:
        key = item["name"].lower()
        if key in by_name:
            if not override:
                return
            by_name[key] = item
        else:
            by_name[key] = item
            ordered_keys.append(key)

    for row in BUILTIN_WORKFLOWS:
        _put({**row, "kind": "workflow", "source": "builtin"})
    for row in BUILTIN_ACTIONS:
        _put({**row, "kind": "action", "source": "builtin"})
    for row in _skill_commands(identity, skills):
        _put(row, override=True)
    for root, scope in _user_command_roots():
        for row in _scan_markdown_commands(root, scope=scope):
            _put(row, override=True)
    for root, scope in _project_command_roots(folder):
        for row in _scan_markdown_commands(root, scope=scope):
            _put(row, override=True)

    group_rank = {"workflow": 0, "action": 1, "custom": 2, "acp": 3}
    public_fields = (
        "name", "aliases", "kind", "group", "icon",
        "title_en", "title_zh", "description_en", "description_zh",
        "arg_hint_en", "arg_hint_zh", "needs_arg", "mode", "source", "keywords",
    )
    merged = [by_name[k] for k in ordered_keys]
    merged.sort(key=lambda item: group_rank.get(item.get("group", "custom"), 2))

    # Append ACP-advertised native commands in their own group (skipping exact duplicates of local entries).
    existing = {item["name"].lower() for item in merged}
    for row in _acp_command_rows(acp_commands, agent_label=agent_label):
        if row["name"].lower() not in existing:
            merged.append(row)

    out: list[dict[str, Any]] = []
    for item in merged:
        clean = {k: item[k] for k in public_fields if k in item and item[k] is not None}
        if "aliases" in clean:
            clean["aliases"] = list(clean["aliases"])
        out.append(clean)
    return out


def expand(
    text: str,
    *,
    identity,
    folder: Path | None = None,
    skills: list[dict] | None = None,
) -> ExpandedCommand | None:
    """If `text` starts with a known workflow, skill, or custom Markdown command,
    return its expanded model prompt + optional mode override. Otherwise return None."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    match = COMMAND_RE.match(stripped)
    if not match:
        return None
    cmd_name = match.group(1).lower()
    args = (match.group(2) or "").strip()

    # Precedence: project custom > user custom > skill > built-in workflow.
    candidates: dict[str, dict[str, Any]] = {}
    for row in BUILTIN_WORKFLOWS:
        candidates[row["name"].lower()] = {**row, "kind": "workflow", "source": "builtin"}
    for row in _skill_commands(identity, skills):
        candidates[row["name"].lower()] = row
    for root, scope in _user_command_roots():
        for row in _scan_markdown_commands(root, scope=scope):
            candidates[row["name"].lower()] = row
    for root, scope in _project_command_roots(folder):
        for row in _scan_markdown_commands(root, scope=scope):
            candidates[row["name"].lower()] = row

    hit = candidates.get(cmd_name)
    if hit is None:
        return None
    # Bare `/plan` without arguments is a mode switch (handled by UI/TUI), not a blank plan turn.
    if hit["name"] == "plan" and hit["kind"] == "workflow" and not args:
        return None
    template = str(hit.get("template") or "").strip()
    if not template:
        return None
    prompt = _render_template(template, args)
    mode = hit.get("mode") if hit.get("mode") in VALID_MODES else None
    return ExpandedCommand(
        name=hit["name"],
        kind=hit["kind"],
        args=args,
        prompt=prompt,
        mode=mode,
        source=str(hit.get("source") or ""),
    )
