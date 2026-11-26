---
core: minor
agent: minor
app: minor
---
Desktop installers for Windows (.exe, .msi), macOS (.dmg) and Linux (AppImage, .deb) carry
their own Python runtime, so The Harness installs without Python. The app's window closes into
a tray icon (open, pause, start at login, quit), raises system notifications only for
approvals, the spending limit, failed or unknown actions and an expired channel login, and
updates itself from GitHub Releases. `harness host install`, `harness host uninstall` and
`harness host status` start the session host at login with the system's own login item (a
scheduled task on Windows, a LaunchAgent on macOS, a systemd user service on Linux), which the
installers turn on; the new setting `agent.autostart` shows and switches the same item.
<!-- zh -->
Windows（.exe、.msi）、macOS（.dmg）和 Linux（AppImage、.deb）的桌面安装包自带 Python 运行时，没有 Python 也能装好 The Harness。应用窗口关掉后留在托盘（打开、暂停、开机时启动、退出），只为等待批准、花费到达额度、失败或结果未知的动作、渠道登录过期发系统通知，并从 GitHub Releases 自动更新。`harness host install`、`harness host uninstall`、`harness host status` 用系统自己的登录项（Windows 计划任务、macOS LaunchAgent、Linux systemd 用户服务）让 session host 登录时启动，安装包默认打开；新设置 `agent.autostart` 显示并开关同一个登录项。
