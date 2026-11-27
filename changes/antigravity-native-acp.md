---
core: patch
external-agents: minor
app: patch
---

Native `acp:antigravity` CLI resolution, per-user install path discovery, and fresh Windows terminal `PATH`:

- Resolve built-in `AgentCli` entries with native `acp_args` (such as `Google · Antigravity CLI` via `agy acp`) directly inside `external-agents` (`agents()`, `agent_ready()`, `model_backend()`, `session_adapter()`, `agent_sign_in()`, `discover_sessions()`) without requiring a public ACP Registry entry or mismatched `acp:custom/` alias.
- Discover `agy` in its standard per-user install folder (`%LOCALAPPDATA%\agy\bin` on Windows, `~/.local/bin` / `~/.agy/bin` on macOS & Linux) even if installed while the desktop app is already running, and display the platform-specific one-line install command when missing.
- Refresh Windows terminal `PATH` from the Windows Registry (`HKLM` + `HKCU`) when opening or restarting a built-in terminal so newly installed CLIs work immediately on terminal restart.

### 中文

- 原生识别内置 ACP CLI（如 `Google · Antigravity CLI` 的 `agy acp`），`external-agents` 直接解析 `acp:antigravity`，不再依赖公开 ACP Registry 或错配的 `acp:custom/` 别名。
- 自动扫描用户级安装目录（Windows `%LOCALAPPDATA%\agy\bin`、macOS/Linux `~/.local/bin` 等），即使在应用运行期间新装 `agy` 无需重启也能立刻检测到，并在未安装时直接给出对应平台的一键安装命令。
- 在 Windows 上新建或重启内置终端时自动合并注册表最新 `PATH`，刚装好的命令行工具（如 `agy`）点一下终端重启即可直接运行，无需重启桌面端。
