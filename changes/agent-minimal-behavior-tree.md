---
agent: minor
---
The resident agent now starts with a minimal 23-node behaviour tree (`format: 2`) that routes
desktop yield, approvals, login expiry, sleep notices, owner turns, calendar, intentions, event
backlogs, quiet review, dreaming and morning briefs through one visible tree with canonical
extension slots (`learned_reactive`, `learned_proactive`), governed `tree_evolve` self-updating,
and automatic demotion of failing learned nodes.
<!-- zh -->
常驻 agent 现在默认内置一套 23 节点的最小初始行为树（`format: 2`），将桌面让权、审批提醒、渠道登录过期、睡眠通知、主人直达、日历、意图、事件积压、静默回看、午夜做梦与晨报统一收口到同一棵可见的行为树里；提供 `learned_reactive` 与 `learned_proactive` 两个规范扩展挂点，支持受内核保护与证据闸门约束的 `tree_evolve` 自主演化以及连续失败节点自动降级。
