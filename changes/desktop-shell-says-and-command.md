---
core: patch
app: minor
---
When the desktop app cannot start, its window says why (the reason, what to do and the log, with Try again and Open the log) instead of staying on "Starting The Harness…", and a host that stops in the background raises a notification. The tray menu and the shell's notifications follow the app's language. The desktop app now brings the `harness` command for terminals, run by the app's own Python and already carrying the terminal chat's libraries: the Windows installers put it on the PATH and remove it on uninstall, macOS offers "Install 'harness' command in PATH" in the menu bar menu, and the installer's last page names another `harness` that comes first on the PATH and how to remove it.
<!-- zh -->
桌面应用启动不了时，窗口里直接说明原因、怎么办和日志位置，并带“重试”和“打开日志”，不再一直停在“正在启动”；后台服务在后台停掉时会发一条系统通知。托盘菜单和外壳发出的通知跟随应用的语言。桌面应用现在自带给终端用的 `harness` 命令，用应用自己的 Python 运行，并且已经带上终端聊天需要的库：Windows 安装包把它加进 PATH、卸载时移除，macOS 在菜单栏菜单里提供“在 PATH 中安装 harness 命令”；PATH 里如果已经有另一个排在前面的 `harness`，安装包的最后一页会指出它在哪里、怎么卸载。
