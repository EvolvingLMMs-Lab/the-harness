---
external-agents: patch
core: patch
app: patch
---
Bypass Windows `.cmd` PowerShell launchers when an ACP agent ships a bundled `node.exe` + `index.js` (such as Cursor), preventing 20s stdin-pipe hangs in consoleless desktop GUI sessions and migrating existing legacy Cursor model entries seamlessly.
<!-- zh -->
修复 Windows 桌面端（无控制台 GUI 宿主）下 Cursor 的 `cursor-agent.cmd` 经由 PowerShell 启动导致 ACP 握手超时卡死的问题，直接启动其自带的 `node.exe` + `index.js`（启动提速一倍且零卡死），并同步迁移已保存聊天对旧括号模型 ID 的引用。
