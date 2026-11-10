---
title: "在终端里使用"
description: "用 harness 在终端里与 agent 对话：对话、按键、命令、文件和 shell 命令、批准、会话和时间轴。"
---

```bash
harness
```

`harness` 在你的终端里打开一个与 agent 的对话，用法和编程 agent 的终端一样。它也可以通过 SSH 使用。第一次运行时会询问模型和它的 key（[安装](/docs/zh-cn/getting-started/install/#连接模型)）；在你发出第一条消息之前，什么都不会开始。

## 对话

对话直接打印在终端里，所以它留在终端的滚动记录中，可以选中、复制，离开之后也还在。对话下方是输入框和一行状态：agent 在做什么、模型、它的工作区和 session。

输入任务并按回车。每个新对话都会先问在哪里工作：不用环境（只对话）、项目文件夹、后台浏览器、后台应用、自己的桌面或独立显示环境。上一次的选择会被高亮，回车即确认；选项目文件夹时接着填写文件夹，在仓库目录里会预填当前目录。`/environment` 显示当前对话在哪里工作，并为下一个对话选择；`/settings` 里的 `session.environment` 可以让它不再询问（`last` 或某一种环境）。首次使用桌面或后台应用时，还会询问真实键鼠权限、其他窗口的信息范围；电脑任务也会询问是否保存屏幕录像。取消则不启动任务。这些选择会保存，之后可通过 `/settings` 修改。项目目录任务不会询问无关的桌面设置。`harness --workspace desktop`（或 `none`、`project`、`browser`、`apps`、`display`）为本次对话明确指定（[CLI 工作区](/docs/zh-cn/use/cli/) 介绍了这些环境）。

`--physical` 和 `--window-details` 是本次任务的明确选择，不改动保存的偏好。非交互/API 调用遇到缺失选择时返回 `choice_required`，不会静默代选；配置对应设置后再提交任务。子 agent 也不能进入尚未完成选择的电脑工作区。

对话里有你的消息、agent 的回答（Markdown）、它的思考（暗色），以及每个程序的一行摘要：`▸ Program 3 · ok · 2.1 s`。**Ctrl+O** 打开当前或最近一个程序的临时详情视图，再按一次（或 Esc）返回折叠聊天。详情不会永久追加到聊天历史；查看期间的新聊天输出在关闭后显示。子 agent 的行以它的名字开头，用它自己的颜色。

agent 工作时你发的消息会立刻送到它那里；它在下一步就会考虑（[打断和接管](/docs/zh-cn/use/interrupt/)）。

## 按键

| 按键 | |
|---|---|
| Enter | 发送 |
| Shift+Enter、Ctrl+J | 换行（也可以先输入 `\` 再按 Enter） |
| ↑ ↓ | 之前发过的消息 |
| Ctrl+R | 搜索它们 |
| Tab | 补全命令或文件 |
| Esc | 打断 agent：它在下一步停下，保留已经做完的事 |
| Esc Esc | 清空输入（内容留在历史里） |
| Ctrl+C | 打断 agent；它不在工作时清空输入；按两次离开 |
| Ctrl+D 两次 | 离开 |
| Ctrl+O | 打开程序详情；再按一次返回折叠聊天 |
| Ctrl+T | 时间轴 |
| ? | 按键列表（输入为空时） |

## 命令

输入 `/`，命令会随输入列出；Tab 或 Enter 选中一个。

| 命令 | |
|---|---|
| `/help` | 命令和按键 |
| `/new` | 新对话；当前显示的对话在 session host 里继续 |
| `/resume` | 选一个以前的对话并继续（已结束的对话会显示它做过什么，发消息会开一个新对话） |
| `/sessions` | 正在运行的 session 及其子 agent；切换到其中一个 |
| `/host`、`/host stop` | session host：它的地址、进程、版本和打开的 session；`stop` 结束它以及在其中运行的一切 |
| `/environment` | 这个对话在哪里工作，以及为下一个对话选择环境 |
| `/agents` | 打开子 agent：对当前对话生效；对话开始前则对下一个对话生效 |
| `/model` | 当前对话（从下一次调用起）和新对话用的模型（输入当前提供商的其他模型 id 也可以） |
| `/effort LEVEL` | 从下次调用起调整当前对话的推理强度 |
| `/experiment NAME [TASK [SEED]] [-- instruction]` | 在实验的 worker 上开始对话 |
| `/settings` | 所有设置，包括扩展包加的；Enter 修改一项 |
| `/packages` | 已安装的包和 registry 里的包；在一个包上按 Enter 显示它提供什么，并可以安装、更新、关闭或移除（先确认） |
| `/library` | agent 学到的东西：每个 library 的条目按类别列出，附证据等级；Enter 阅读一条及其历史 |
| `/pause`、`/continue` | 在下一步停下、继续 |
| `/approve [app \| session \| always]`、`/reject [why]` | 回应 agent 在等的事 |
| `/end` | 结束对话 |
| `/timeline` | 时间轴（Ctrl+T） |
| `/detach`、`/exit` | 离开；对话继续运行 |

`/resume`、`/sessions`、`/model`、`/settings`、`/packages`、`/library` 和时间轴会占满整个终端，关闭（Esc）后回到对话。

## 文件和 shell 命令

- `@` 加路径把文件附在消息里（Tab 补全路径）：agent 会拿到它的文本；图片就是图片本身；文件夹是其中的名字。
- `!命令` 在这里、当前目录下运行命令，显示输出，并把命令和输出交给 agent。
- `!!命令` 只运行它。

## 批准

当一步要等你时（敏感步骤、你的鼠标和键盘，或者 `approvals.ask = "programs"` 时的任何程序：[权限](/docs/zh-cn/configure/permissions/#审批)），选项会出现在输入框上方，在它要做的事和原因下面：

```text
it wants to click in Scratch (notes.txt - Scratch) with your mouse and keyboard
  why: click the Save button
❯ 1. allow this time
  2. Scratch is fine for this chat
  3. anything is fine for this chat
  4. always allow Scratch
  5. don't allow
```

按数字，或用 ↑ ↓ 移动再按 Enter。选"不允许"会请你写理由（它看得到；不写直接 Enter 也行）。"总是允许"会在你的设置里加一条规则（[权限](/docs/zh-cn/configure/permissions/)）。对敏感步骤，无论选哪一项，允许都只对这一步有效。

## 时间轴

**Ctrl+T** 全屏显示时间轴：每个独立工作的部分一行（模型、agent 的程序、程序启动的每个任务——缩进在启动它的那个下面——以及环境），上方是运行时间的坐标轴。`+` 和 `-` 缩放，`0` 显示整个运行，Esc 关闭。模型那一行和某个程序那一行同时有色块时，agent 在边想边做。[观看和回放一次运行](/docs/zh-cn/use/replay/) 有更多内容。

## 让它继续运行

每个对话都是 **session host** 里的一个 session，session host 是终端、app 和 Python 共用的后台进程。离开（Ctrl+C 两次、`/exit`）、关闭终端或 SSH 断开，对话都会继续运行。再次打开 `harness`，用 `/resume` 或 `/sessions` 回到它。第一个对话会自己启动 host；`/host` 显示它，`/host stop` 结束它。

多个对话可以同时工作，各自在自己的工作区里，一个 agent 也可以把任务分给子 agent（[使用 session 和子 agent](/docs/zh-cn/use/sessions/)）。

要在脚本里做一个任务而不打开对话，用 `harness run "task"`（[用 CLI 运行](/docs/zh-cn/use/cli/)）。第一次使用时，对话界面会把 prompt_toolkit 和 rich 安装到它自己的环境里；它们不是核心的依赖。
