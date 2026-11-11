---
title: "配置"
description: "一个属于你的配置文件、一个可选的项目配置文件，以及描述一次运行的文件：它们各在哪里、哪一个优先，以及最常改的选项。"
---

The Harness 读取一个属于你的文件 `~/.harness/config.toml`，在项目中还读取该项目的
`harness.toml`。这两个文件可以从空文件开始。每个新对话都要选择在哪里工作；真实键鼠权限、其他窗口信息和屏幕录像在首次涉及时需要明确选择。内部配置默认值不视为用户同意。

## config.toml

`harness` 第一次运行时写入它，内容是你选的模型和密钥。app 的 **Settings** 页面和终端界面也会修改它，你也可以手动编辑：

```toml
[model]
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash"
reasoning_effort = "low"

[keys]
OPENROUTER_API_KEY = "sk-or-..."

[limits]
max_steps = 60                     # steps per task
max_minutes = 120                  # minutes per conversation

[session]
environment = "ask"                # ask where each new conversation works

[computer]
mode = "browser"                   # the computer kind that choice highlights first

[physical]
level = "ask_once_app"             # when the agent may use your mouse and keyboard

[[physical.rules]]
level = "never"
app = "wechat"

[packages]
auto_install = "official"          # install the packages a task needs, from the official registry
```

| 节 | |
|---|---|
| `[model]` | provider 和模型，以及它的高级设置（[模型和 provider](/docs/zh-cn/configure/models/)） |
| `[keys]` | 你的 provider 和连接器的密钥，按其变量名存放；这个文件只有你能读取 |
| `[packages]` | 首次使用时安装、registry、你安装的包（[包](/docs/zh-cn/configure/packages/)） |
| `[general]` | 语言、主题、通知 |
| `[limits]` | 每个对话的步数、分钟数和金额，sub-agent 层数，每一步之前是否询问 |
| `[session]` | 新对话在哪里工作，是否带子 agent |
| `[environments]` | agent 什么时候可以在对话中取用另一个环境（[权限与隐私](/docs/zh-cn/configure/permissions/#取用另一个环境)） |
| `[computer]` | 首先高亮的电脑环境、显示器、截图尺寸、同时工作的对话数 |
| `[physical]`、`[privacy]` | 鼠标和键盘，以及模型能了解到你的窗口的哪些信息（[权限和隐私](/docs/zh-cn/configure/permissions/)） |
| `[personal]` | agent 应当了解的关于你的信息，用你自己的话写 |
| `[data]` | 对话保留多久 |

## 对话在哪里工作

每个新对话都要选择环境。选项来自已安装的包：

| 环境 | `--workspace` | |
|---|---|---|
| 不用环境 | `none` | 只对话：模型和已连接的工具。不启动工作进程，也不给模型任何画面 |
| 项目文件夹 | `project` | 在你指定的一个文件夹里读写文件、运行命令；没有屏幕 |
| 后台浏览器 | `browser` | 隔离的浏览器，不带你的登录状态 |
| 后台应用 | `apps` | 你的应用程序，不占用你的屏幕 |
| 你的桌面 | `desktop` | 你的屏幕，以及设置允许范围内的鼠标和键盘 |
| 独立显示环境 | `display` | 它自己的显示器或虚拟机 |

`session.environment` 决定怎么选：

| 取值 | |
|---|---|
| `ask`（默认） | 每个对话开始时询问；高亮你上一次的选择，回车即确认 |
| `last` | 沿用上一次的选择，不询问 |
| 某一种环境，如 `none` 或 `browser` | 总是用它 |

所有前端都有这个选择：终端里开场的选择和 `/environment`，app 里模型旁边的选择器，命令行的 `--workspace` 和 `--folder`，Python 里的 `workspace=`。没有人可问的场合（脚本、Python 接口）遇到 `ask` 时，任务不会启动，错误信息会指出该用哪个参数：不会替你选。`computer.mode` 只是在你还没有选过时，首先高亮的那一种电脑环境。

对话并不局限在这个环境里。某一步需要别的环境时，agent 会请求取用，见[取用另一个环境](/docs/zh-cn/configure/permissions/#取用另一个环境)。

[设置参考](/docs/zh-cn/reference/settings/)列出了每个键、它的取值和默认值。修改从下一个对话开始生效；权限级别和工作区数量立即生效。

## 项目的 harness.toml

含有 `harness.toml` 的文件夹就是一个项目。它列出项目使用的包，在那里运行
`harness install` 会在它旁边写入 `harness.lock`，这样参与这个项目的每个人都得到同样的包：

```toml
[packages]
computer = "^1.0"
mine = { source = "git:github.com/you/mine@v0.3", range = "^0.3" }
```

## 哪一个优先

从低到高：默认值、`config.toml`、项目的 `harness.toml`、环境变量，以及单条命令的选项（例如 `harness run --workspace
browser "task"`），后者只对那一次运行有效。

## 环境变量

| 变量 | |
|---|---|
| `OPENROUTER_API_KEY`, ... | 某个 provider 的密钥，代替 `[keys]` |
| `HARNESS_DATA` | `config.toml`、对话和库所在的位置（默认 `~/.harness`） |
| `HARNESS_HOME` | 包、环境和权重所在的位置（默认 `~/.cache/harness`） |
| `HARNESS_REGISTRY` | 另一个包 registry：一个 https 地址或本地文件夹 |
| `HARNESS_CHROME_PATH` | 后台浏览器使用的 Chrome 可执行文件，代替已安装的 Google Chrome |
| `HARNESS_HOST_IDLE` | 没有打开任何内容时 session host 保持运行的秒数（默认 1800） |

## 描述一次运行的文件

benchmark 和其他重复进行的运行，用 TOML 文件描述它们运行什么；这些文件由包提供，你也可以自己写：一个
**agent**（它的 prompt、skill 和运行时设置）、一个**模型文件**（每个角色由哪个模型担任）和一个**实验**（一个环境、它的任务和
seed、一个 episode 的预算，以及对 agent 和模型的修改）。每一层覆盖它前面的一层，命令的选项最后生效：

```toml
#:schema https://harness.lmms-lab.com/docs/schema/experiment.json
description = "my game, five seeds, a cheaper model"
bench = "mygame"
tasks = ["play"]
seeds = "0-4"
model = "deepseek-flash"

[budget]
max_model_calls = 40               # per episode
max_cost_usd = 0.5                 # per episode
max_total_cost_usd = 5             # the whole run

[overrides.agent.runtime]
verifier = false                   # do not check the result with a second model

[overrides.model.main]
reasoning_effort = "low"
```

第一行让能为 TOML 读取 JSON schema 的编辑器（Taplo，或 Even Better TOML 扩展）补全并解释每个键。
[配置键](/docs/zh-cn/reference/configuration/)参考列出了所有键，benchmark 包的 README 说明它如何运行自己的实验。

每次运行都把这些文件解析成一个 **lock**：其中包含决定它计算什么的一切（版本、prompt、skill、模型角色、运行时设置、包），
不包含它在哪里运行。lock 的哈希就是这次运行的 **identity**，记录在它的 `manifest.json` 中：identity
相同的两次运行，运行的是同一套配置。
