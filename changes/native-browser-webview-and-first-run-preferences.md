---
core: minor
app: minor
---
Replace the iframe-based right-pane browser with a native Tauri 2 child WebView (`Window::add_child`) with real navigation sync and automatic overlay hiding, and add an explicit Preferences step (daily limit, autonomous mode, record retention, autostart) to first-run onboarding in both the desktop app and terminal.
<!-- zh -->
将右侧内置浏览器从裸 `<iframe>` 升级为 Tauri 2 原生子 WebView（`Window::add_child`），完整支持任意外网加载、地址栏双向同步与弹窗自动避让；并在桌面端与终端首次启动向导中新增“偏好设置”步骤（每日额度、自主运行、记录保留天数、开机自启）。
