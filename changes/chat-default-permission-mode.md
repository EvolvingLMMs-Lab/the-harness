---
agent: patch
app: patch
---
New chats now inherit the configured default permission mode (`approvals.mode`) in the chat list, overview panel, composer, and plan-mode instructions instead of displaying `auto` when no per-chat override is set, and changing `approvals.mode` in Settings updates the composer and overview immediately.
<!-- zh -->
新建对话在未单独覆盖权限模式时，对话列表、概览面板、输入框和计划模式提示现在会正确继承默认权限模式（`approvals.mode`），不再固定显示为「自动」；在设置中修改默认权限模式时也会立即刷新输入框和概览显示。
