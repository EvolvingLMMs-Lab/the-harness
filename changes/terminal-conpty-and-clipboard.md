---
core: patch
agent: minor
app: minor
---
Added native Windows 10/11 ConPTY (`CreatePseudoConsole`) via pure stdlib `ctypes` and full terminal copy/paste (`Ctrl+V` / `Ctrl+Shift+V` / `Cmd+V` / `Shift+Insert`, `Ctrl+C` on selection, right-click copy/paste); upgraded Google's default CLI source from legacy Gemini CLI to Antigravity CLI (`agy`); added Back/Forward/Reload navigation history to the Browser panel and removed hardcoded localhost chips from its blank start page; split the composer controls into a clean two-tier bar so the Send button is never clipped when the right panel is open; and added first-class SSH remote projects (`~/.ssh/config` host picker, remote SSH terminal, and remote Files browsing).
<!-- zh -->
新增基于纯标准库 `ctypes` 的 Windows 10/11 原生 ConPTY（`CreatePseudoConsole`）交互终端与完整复制粘贴快捷键（`Ctrl+V` / `Ctrl+Shift+V` / `Shift+Insert`、选中即 `Ctrl+C` 复制、右键复制/粘贴）；将 Google 默认 CLI 模型来源从旧版 Gemini CLI 切换为 `Google · Antigravity CLI`（`agy`）；浏览器面板补齐标准「后退 / 前进 / 刷新」历史导航并移除空白页多余的 `localhost` 预设项；将输入框控件拆分为清爽双层结构（模型/思考强度与权限/项目分离），彻底杜绝右侧栏展开时挤压或遮挡发送按钮；项目体系新增一级 **SSH 远程项目**（自动读取 `~/.ssh/config` 主机列表、远程 SSH 交互终端与远程文件浏览）。
