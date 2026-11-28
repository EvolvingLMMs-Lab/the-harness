---
core: patch
app: patch
---
Stop stealing foreground window focus (`the-harness --focus` -> `unminimize`/`show`/`set_focus`) when background tasks finish or need attention; keep non-intrusive OS desktop notifications and gentle taskbar/dock attention (`request_user_attention`) instead.
<!-- zh -->
移除后台任务完成或需要处理时自动调用 `--focus` 强抢前台窗口置顶的逻辑，改为仅通过系统桌面通知与不抢焦点的任务栏/Dock 温和提醒（`request_user_attention`）提示用户。
