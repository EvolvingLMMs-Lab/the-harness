---
title: "在终端里使用"
description: "终端聊天：输入和发送、它做事时显示什么、批准、全部快捷键和命令、自定义按键，以及每种终端需要什么。"
---

```bash
harness
```

`harness` 在你的终端里打开一个对话，也可以通过 SSH 使用。用过 Claude Code 的话，你已经会用了：The Harness 有同样功能的地方，按键、命令和它们的名字都一样。第一次运行会问用哪个模型（[安装](/docs/zh-cn/getting-started/install/#连接模型)）；之后对话打开，输入框上方是版本、模型和目录，在你发出消息之前什么都不会开始。

## 输入和发送

| 要做的事 | 按键 |
|---|---|
| 发送消息 | Enter |
| 换行 | Shift+Enter、Ctrl+J、Alt+Enter，或者 `\` 加 Enter |
| 粘贴多行 | 直接粘贴：粘贴不会触发发送。超过三行或 800 个字符时显示成 `[Pasted text #1 +120 lines]`，发送时带上全文 |
| 附上剪贴板里的图片 | Windows 上 Alt+V，其它系统 Ctrl+V：显示成 `[Image #1]` |
| 附上文件 | `@` 加路径（Tab 补全） |
| 在这里运行一条命令并把输出交给 agent | `!command`（`!!command` 只运行） |
| 运行对话的命令 | `/` 加名字：列表随输入过滤，Tab 或 Enter 选中 |
| 查看按键 | 在空的输入框里按 `?` |

Ctrl+J 和 `\` 加 Enter 在任何终端里都能换行。Shift+Enter 取决于终端：见[终端](#终端)。

输入框像 shell 的命令行那样编辑：Ctrl+A、Ctrl+E 到行首、行尾，Ctrl+K、Ctrl+U 删到行尾、行首，Ctrl+W 删到前一个空白，Ctrl+Y 贴回刚才删掉的内容，Alt+Y 在更早删掉的内容里轮换，Alt+B、Alt+F 移动一个词，Alt+D、Alt+Backspace（或 Ctrl+Backspace）删除一个词，Ctrl+_ 撤销。一个词是一串字母和数字，所以在 `src/utils/foo.ts` 里 Alt+B 依次停在 `ts`、`foo`、`utils`、`src`；Ctrl+W 一次删掉整个路径。这些编辑键不能改绑。

上下键先在草稿的各行之间移动。到第一行或最后一行，才翻你在这个目录里发过的消息，包括以前的会话；连续两次相同的消息只记一条。用 Ctrl+C 或 Esc Esc 清掉的草稿，按上键能找回。Ctrl+R 搜索所有目录的消息：边打边匹配，再按 Ctrl+R 找更早的，Tab 或 Esc 留下这条继续编辑，Enter 直接发送，Ctrl+C 回到原来输入的内容。

## 它在做事的时候

输入框上方有一行说明它在做事、已经多久、怎么停下。回复随它写出来而出现。

- **Esc** 停下这一回合。已经做完的保留。
- **这时发出的消息会排队。** 排队的消息列在输入框上方，回合结束后按顺序发出，按 Esc 之后也一样。在输入框第一行按**上键**把它们取回输入框里修改。**Ctrl+Enter** 停下这一回合，立刻发出排队的消息。
- **Ctrl+C** 停下这一回合；没有在做事时清空输入，再按一次退出。**Ctrl+D** 在有文字时删除光标后的字符；输入框为空时按第二次退出。
- **Ctrl+O** 打开详细记录：每一步的全部内容，带时间、每次调用用的模型和 token 数、程序的代码和完整输出。打开时显示最近几个回合，Ctrl+E 显示全部。`q`、Esc、Ctrl+C 或 Ctrl+O 关闭。
- **Ctrl+T** 打开时间线：每个独立做事的部分一行，上方是时间轴。`+`、`-` 缩放，`0` 显示整次运行。
- **Shift+Tab** 在批准档位之间切换（`approvals.programs`：每次都问、每个对话问一次、允许、不允许）。当前档位显示在输入框下方。
- **Alt+P** 换模型，不清空已经输入的内容。

退出对话不会停掉 agent。退出时会说明这一点，以及怎么回来（`harness`）、怎么停掉它（`harness host stop`）。

输入框下方：左边是提示，右边是身份和它今天的花费、模型。再下一行是批准档位，以及对话用了模型上下文的多少。agent 的一步是一行（`▸ Program 3 · ok · 2.1 s`），其余的在详细记录里。

## 批准

有一步要等你决定时，对话在输入框上方提问：它要做什么、为什么要等你、有哪些回答。

```text
● Approval needed
  git push origin main
  It waits for you because it is a step of the kind "send" · A7 · cancelled in 30 min if nobody answers

  Do you want to proceed?
  ❯ 1. Yes
    2. No
  Enter to answer · esc to decline · tab to add a note
```

用上下键移动后按 Enter，或者直接按数字。Esc 等于拒绝。Tab 打开一行补充说明，不管回答是哪个都会带上；再按 Tab 关闭。提问占用按键期间，你正在输入的内容会先放到一边，回答之后回来。`/approve` 和 `/deny` 用命令回答。哪些步骤要等你，见[权限](/docs/zh-cn/configure/permissions/)。

## 快捷键

| 快捷键 | 作用 |
|---|---|
| Enter | 发送 |
| Shift+Enter、Ctrl+J、Alt+Enter、`\` Enter | 换行 |
| 上、下（Ctrl+P、Ctrl+N） | 在草稿里移动；然后翻历史；上键取回排队的消息 |
| Ctrl+R | 搜索历史 |
| Tab | 接受补全；在批准提示里，打开补充说明 |
| Esc | 停下这一回合；关闭列表或按键面板；在批准提示里，拒绝 |
| Esc Esc | 清空输入（上键找回） |
| Ctrl+C | 停下这一回合；清空输入；按两次退出 |
| Ctrl+D | 删除光标后的字符；输入框为空时按两次退出 |
| Ctrl+Enter、Ctrl+X Ctrl+S | 停下这一回合，立刻发出排队的消息 |
| Ctrl+L | 重画终端 |
| Ctrl+O | 详细记录 |
| Ctrl+T | 时间线 |
| Shift+Tab | 下一个批准档位 |
| Alt+P | 换模型 |
| Ctrl+S | 暂存输入；输入框为空时取回（发送之后也会自动回来） |
| Ctrl+G、Ctrl+X Ctrl+E | 用你的编辑器编辑输入（`VISUAL`、`EDITOR`） |
| Alt+V（Windows）、Ctrl+V | 附上剪贴板里的图片 |
| Ctrl+Z | 挂起回到 shell（Windows 上没有） |
| Ctrl+A、Ctrl+E、Ctrl+K、Ctrl+U、Ctrl+W、Ctrl+Y、Alt+Y、Alt+B、Alt+F、Alt+D、Ctrl+_ | 行内编辑 |
| 空输入框里的 `?` | 按键面板 |

在 macOS 上，Alt 开头的快捷键需要打开“Use Option as Meta Key”（Terminal），或者把 Option 设成“Esc+”（iTerm2）。

占满整个终端的列表（`/model`、`/resume`、`/config`、`/sessions`、`/library` 等）都用同一套键：上下（Ctrl+P、Ctrl+N）、PageUp、PageDown、Home、End，Enter 选中，Esc 关闭；在选择器里打字过滤，`?` 显示这一屏的键。

## 命令

| 命令 | 作用 |
|---|---|
| `/help` | 它是什么、快捷键、命令和技能 |
| `/clear [name]`（`/reset`、`/new`） | 开一个不带当前内容的新对话；当前对话继续，给了 `name` 就以它命名 |
| `/resume [conversation]`（`/continue`） | 接着以前的对话：指定的那个，或者从列表里选 |
| `/sessions` | 正在运行的会话，或一个身份的各个对话：切换到其中一个 |
| `/rename <name>` | 给当前对话改名 |
| `/model [model]`（`/models`） | 切换到指定的模型，或者从列表里选；列表最后一行用来编辑模型列表 |
| `/effort [level]` | 模型的推理强度 |
| `/login`、`/logout` | 添加或移除一个模型来源：本机已登录的 agent、提供商的 key、本机模型 |
| `/status [stop]`（`/host`） | 版本、模型、身份、提供商和后台服务是否有应答；`stop` 停掉后台服务 |
| `/usage [week \| raise DOLLARS]`（`/cost`、`/stats`） | 这个身份今天花了多少、今天的额度 |
| `/context` | 对话用了模型上下文的多少 |
| `/config [key=value ...]`（`/settings`） | 设置，或者直接设一项：`/config terminal.editor_mode=vim` |
| `/permissions`（`/allowed-tools`） | 批准规则 |
| `/keybindings` | 打开你的快捷键文件 |
| `/terminal-setup` | 让 Shift+Enter 在 VS Code、Cursor、Windsurf、Alacritty 或 Zed 里换行 |
| `/memory [N]`（`/instructions`） | 指令文件（`AGENTS.md`）和它记住的东西；`N` 打开对应的文件 |
| `/skills` | 它有的技能；每个技能也是一条命令 `/名字` |
| `/library` | 它学到的东西：技能、反射树、记忆 |
| `/agents [on]` | 这个对话的子 agent；`on` 允许它启动子 agent |
| `/init` | 让 agent 写这个项目的 `AGENTS.md` |
| `/diff` | 编程会话的改动 |
| `/copy [N]` | 复制最近一条回复（倒数第 N 条）；有代码块时可以选其中一块 |
| `/export [file]` | 把对话导出成纯文本：写到文件，或者选择复制或保存 |
| `/doctor` | 检查这次安装 |
| `/update`、`/version` | 有没有新版本；当前版本 |
| `/stop`（`/pause`、`/cancel`） | 停下这一回合，和 Esc 一样 |
| `/queue [text \| list \| edit N text \| rm N \| clear]`（`/q`） | 让一条消息排队；列出、修改或去掉排队的消息 |
| `/bg <prompt>`（`/background`） | 让它在另一个对话里做一件事，当前对话不受影响 |
| `/approve [app \| session \| always]`、`/deny [why]`（`/reject`） | 回答等你决定的事 |
| `/calendar`、`/channels`（`/platforms`）、`/timeline`、`/transcript` | 这个身份的一周、它的渠道、时间线、详细记录 |
| `/environment`、`/packages`（`/plugin`）、`/experiment`、`/learn`、`/steer`、`/terminal`、`/answer`、`/merge`、`/handoff`、`/import`、`/end` | 对话在哪里工作、扩展包，以及与其它 agent 的会话和实验相关的命令 |
| `/exit`（`/quit`、`/detach`） | 退出；正在运行的继续 |

不是命令的名字会得到 `Unknown command: /name`，有相近的命令时一并给出。

## 自定义按键

`/keybindings` 打开数据目录（`~/.harness`）里的 `keybindings.json`，没有时先按默认值生成。格式和 Claude Code 的快捷键文件一样：一个 `bindings` 数组，每一块有 `context` 和一张“按键 → 动作”的表；值写 `null` 表示解绑。保存后立即生效，不用重启。

```json
{
  "bindings": [
    {
      "context": "Chat",
      "bindings": {
        "ctrl+k": "chat:newline",
        "ctrl+s": null,
        "ctrl+x ctrl+k": "command:clear"
      }
    }
  ]
}
```

| 上下文 | 动作 |
|---|---|
| `Global` | `app:interrupt`（Ctrl+C）、`app:exit`（Ctrl+D）、`app:toggleTranscript`、`app:toggleTimeline`、`app:redraw` |
| `Chat` | `chat:submit`、`chat:newline`、`chat:cancel`、`chat:sendNow`、`chat:clearInput`、`chat:cycleMode`、`chat:modelPicker`、`chat:undo`、`chat:externalEditor`、`chat:stash`、`chat:imagePaste`、`history:search`、`history:previous`、`history:next`，以及对应任意命令的 `command:<name>` |
| `Autocomplete` | `autocomplete:accept`、`autocomplete:dismiss`、`autocomplete:previous`、`autocomplete:next` |
| `Confirmation` | `confirm:yes`、`confirm:no`、`confirm:previous`、`confirm:next`、`confirm:addNote` |
| `HistorySearch` | `historySearch:next`、`historySearch:accept`、`historySearch:cancel`、`historySearch:execute` |
| `Transcript` | `transcript:exit`、`transcript:toggleShowAll` |
| `Help` | `help:dismiss` |
| `Select` | `select:next`、`select:previous`、`select:pageUp`、`select:pageDown`、`select:first`、`select:last`、`select:accept`、`select:cancel` |

一个按键是用 `+` 连起来的修饰键（`ctrl`、`shift`、`alt` 或 `meta`、`cmd`）加一个键：一个字符，或者 `escape`、`enter`、`tab`、`space`、`up`、`down`、`left`、`right`、`pageup`、`pagedown`、`home`、`end`、`backspace`、`delete`、`f1` 到 `f12`。组合键是用空格隔开的几个按键。Ctrl+C 和 Ctrl+D 不能改绑；Ctrl+M、Ctrl+I、Ctrl+[、Ctrl+H 也不能，终端把它们当作 Enter、Tab、Escape、Backspace 发送。文件里的错误（读不出来的 JSON、拼错的修饰键、不存在的上下文或动作）会在对话里说明；能读出来的绑定照常生效。

想在输入框里用 Vim 的键，在 `/config` 里把 `terminal.editor_mode` 设成 `vim`：Esc 进入 NORMAL 模式，Enter 仍然发送。

## 终端

Shift+Enter 能不能到达对话取决于终端。Ctrl+J 和 `\` 加 Enter 始终可用。

| 终端 | Shift+Enter |
|---|---|
| Windows Terminal、Windows 控制台 | 可用 |
| iTerm2、WezTerm、Ghostty、Kitty、Warp、foot、Alacritty 0.16 及以后、xterm | 可用：对话启动时请终端上报带修饰键的按键，结束时恢复原状 |
| VS Code、Cursor、Windsurf、Zed、0.16 之前的 Alacritty | 运行一次 `/terminal-setup`：它往终端自己的配置里加一条 Shift+Enter 绑定（先备份文件；已有的绑定保持原样） |
| tmux | 在上面几行的终端里，往 `~/.tmux.conf` 加上 `set -s extended-keys on` 和 `set -as terminal-features 'xterm*:extkeys'` |
| GNOME Terminal、Apple Terminal、JetBrains IDE | 不可用：用 Ctrl+J、`\` 加 Enter，或者在 Apple Terminal 里打开“Use Option as Meta Key”后用 Option+Enter |

## 让它继续运行

**后台服务**在 `/exit`、关闭终端或 SSH 断开之后继续运行对话。重新打开 `harness`，用 `/resume` 或 `/sessions` 回去。`/status` 显示后台进程；`/status stop` 停掉它和其中的对话。

`harness --continue` 打开你最近发过消息或恢复过的对话；`harness --resume ID` 明确选一个。已结束的会话带着它的消息和事实在新的内核里恢复（[会话](/docs/zh-cn/use/sessions/)）。只跑一个脚本任务时用 `harness run "task"`（[CLI](/docs/zh-cn/use/cli/)）。

app 的 agent 的对话在打开时会问在哪里工作：不带环境、一个项目目录、后台浏览器或应用、桌面，或者单独的显示器。Enter 确认高亮的选项；`/environment` 为下一个对话选择，`/config` 里的 `session.environment` 可以让它不再问，`--workspace KIND` 只对这一次生效（[CLI 工作区](/docs/zh-cn/use/cli/)）。
