---
title: "设置"
description: "~/.harness/config.toml 的键：每一节和每个键、它的取值和默认值，以及它的作用。"
---

你的设置保存在一个文件中：`~/.harness/config.toml`（设置了 `$HARNESS_DATA` 时为其中的 `config.toml`），和你的模型与密钥放在一起。`harness`
在第一次运行时写入它；app 的 **Settings** 页面和终端界面会修改它，你也可以手动编辑。文件中只保存改过的值；其他键都取默认值。保存的值如果不再通过检查，就回到默认值。

```toml
[model]
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash"
reasoning_effort = "low"

[keys]
OPENROUTER_API_KEY = "sk-or-..."

[limits]
max_steps = 30

[[physical.rules]]
level = "allow"
app = "code"
```

下面的每个键都写成 `section.key`：`limits.max_steps` 就是 `[limits]` 下的 `max_steps`。两个分级策略的规则是表的列表
（`[[physical.rules]]`、`[[privacy.rules]]`）。

`harness` 里的 `/settings` 列出每个键（包括包添加的），并修改其中一个；超出范围的值会被拒绝并给出原因。

## model 和 keys

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `model.provider` | [模型和 provider](/docs/zh-cn/configure/models/) 中的一个 provider（默认 `openrouter`） | 由谁提供模型 |
| `model.model` | provider 的模型 id（默认 `deepseek/deepseek-v4.1-flash`） | agent 使用的模型 |
| `model.base_url` | 一个地址（默认无） | provider 的另一个端点，例如代理；`custom` 必须设置 |
| `keys.<VARIABLE>` | 密钥 | 某个 provider 或连接器的密钥，按其变量名（`OPENROUTER_API_KEY`）存放；环境变量中的密钥优先 |

其他 `model` 键，即它的高级设置，列在下面的 [model](#model) 中。

## packages

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `packages.auto_install` | `official`、`ask`、`off`（默认 `official`） | 当任务需要某个已安装的包都不提供的东西时怎么做：从官方 registry 安装、先询问，或停止并说明要安装哪个包 |
| `packages.registry` | 一个 https 地址或一个文件夹（默认为空：官方 registry） | 包从哪里来；`HARNESS_REGISTRY` 优先 |

你安装的包和你信任的项目也保存在 `[packages]` 下；`harness install` 和 `harness remove` 修改它们（[包](/docs/zh-cn/configure/packages/)）。

### 修改何时生效

| 设置 | 生效时间 |
|---|---|
| `model`、`approvals`、`limits`、`personal`，以及决定一次对话的 `computer` 键（`mode`、`monitor`、`max_side`、`step_limit`、浏览器和虚拟机相关的键） | 下一次对话开始时；正在运行的对话保持它开始时的值 |
| `computer.workspaces`、`computer.chromes`、`computer.displays` | 立即：工作区池随之调整 |
| `physical`、`privacy` | 立即：每次修改后 worker 都会重新读取 |
| `general` | 在 app 的页面上立即生效；`open_browser` 在下次 app 启动时生效 |
| `data.keep_days` | 下次 app 启动时 |

物理输入和窗口详情的级别及其规则如何工作，见[权限和隐私](/docs/zh-cn/configure/permissions/)；设置页见[CLI 工作区](/docs/zh-cn/use/cli/)。

## general

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `general.language` | `system`、`zh`、`en`（默认 `system`） | app 页面的语言；`system` 跟随浏览器 |
| `general.theme` | `system`、`light`、`dark`（默认 `system`） | 浅色或深色页面；`system` 跟随电脑 |
| `general.open_browser` | `true`、`false`（默认 `true`） | app 启动时在浏览器中打开 app 的页面 |
| `general.notifications` | `true`、`false`（默认 `true`） | 页面在后台时，agent 提问或完成后发出通知 |

## model

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `model.reasoning_effort` | `default`、`low`、`medium`、`high`（默认 `default`） | 模型回答前推理的多少；`default` 保留 provider 的设置。推理越多越慢、花费越高 |
| `model.max_output_tokens` | 0 到 200000（默认 0） | 最长回复，单位为 token；0 保留 harness 的默认值 |
| `model.checker` | 文本，最多 200 个字符（默认为空） | 检查结果的同一 provider 的模型；为空时用模型本身 |
| `model.vision` | 文本，最多 200 个字符（默认为空） | 同一 provider 的能读图的模型，主模型不能读图时由它描述画面；为空时，这样的模型会被告知画面没有发送，依靠文本工作 |
| `model.think_while_acting` | `default`、`on` 或 `off` | 长程序运行期间可提前准备一次后续决策。旧配置的 `on_events` 和 `periodic` 等同于 `on`。 |
| `model.think_interval` | 0 到 600 秒 | 兼容旧配置。 |

## session

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `session.environment` | `ask`、`last` 或一种工作区（默认 `ask`） | 新对话没有指明环境时在哪里工作：`ask` 在每个对话开始时询问，并高亮上一次的选择；`last` 沿用上一次的选择，不询问；写一种环境（`none`、`project`、`browser`、`apps`、`desktop`、`display`）则总是用它。没有人可问时，`ask` 会报错并指出该用哪个参数 |
| `session.agents` | `off`、`on`（默认 `off`） | 新对话是否带子 agent：`off` 不加载它们的调用和提示词（可以在对话里打开，agent 也可以请你打开）；`on` 从一开始就加载，深度以 `limits.agent_depth` 为限 |

## environments

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `environments.attach` | `never`、`ask_each`、`ask_once_session`、`allow`（默认 `ask_once_session`） | 没有规则另行规定时，agent 什么时候可以在对话中取用另一个环境。无论是否询问，每次取用及其理由都会显示并记录。`physical.level = "allow"` 时不询问；`never` 仍然拒绝。立即生效 |
| `environments.rules` | `{level, kind}` 的列表（默认为空） | 为某一种环境（`desktop`、`apps`、`display`、`browser`、`project`）设的级别，优先于 `environments.attach`。立即生效 |

## approvals

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `approvals.ask` | `sensitive`、`programs`（默认 `sensitive`） | 敏感操作逐次批准。`programs` 也要求每个程序先得到批准。应用输入框旁的 **Ask before acting** 可覆盖单次对话的设置。旧的 `limits.ask_before_acting = true` 会作为 `programs` 读取 |

## limits

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `limits.max_steps` | 1 到 1000（默认 60） | 一个任务可用的模型调用次数 |
| `limits.max_minutes` | 1 到 1440（默认 360） | 一次对话可运行的分钟数 |
| `limits.agent_depth` | 0 到 4（默认 1） | agent 启动子 agent 的最大深度，子 agent 的步数和时间计入对话：0 不允许；1 对话的 agent 可以启动，它的子 agent 不可以；2 子 agent 也可以；依此类推 |

## computer

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `computer.mode` | `desktop`、`browser`、`apps`、`display`（默认 `browser`） | 在你还没有选过时，新对话的环境选择首先高亮的电脑环境（每个对话由 `session.environment` 询问）。`desktop` 控制这台电脑的屏幕、鼠标和键盘；`browser` 在隔离的无头 Chrome 中搜索和浏览，不带你的登录状态；`apps` 在后台使用这台电脑的应用程序，不占用你的屏幕，也不用你的鼠标和键盘（Windows、macOS、X11 上的 Linux）；`display` 在对话自己的、你看不到的显示器上运行应用程序（Linux：显示服务器；Windows 和 macOS：虚拟机） |
| `computer.monitor` | 1 到 16（默认 1） | 桌面模式：agent 开始时所在的显示器，1 是主显示器；之后它跟随活动窗口移到其他显示器 |
| `computer.max_side` | 640 到 3840（默认 1920） | 截图缩放到长边最多这么多像素；越小越便宜越快，越大越能看清小字 |
| `computer.step_limit` | 10 到 5000（默认 300） | 一次对话可执行的鼠标和键盘步数 |
| `computer.workspaces` | 1 到 16（默认 4） | 可同时工作的对话数，每个对话在自己的工作区中（一个后台浏览器、桌面）；超出的对话等待其他对话结束 |
| `computer.chromes` | 1 到 16（默认 1） | 后台浏览器共享的无头 Chrome 数量，每个对话在自己的上下文中（不共享登录状态或 cookie） |
| `computer.browser_windows` | `off`、`tiled`（默认 `off`） | `off`：后台浏览器是无头的；`tiled`：每个对话或 agent 的浏览器是一个窗口，平铺在屏幕上，便于观看或录制 |
| `computer.browser_display` | 文本，最多 40 个字符（默认为空） | `tiled`：窗口打开所在的 X display，例如 `:99`；为空表示这台电脑自己的屏幕 |
| `computer.browser_area` | `x,y,width,height`（默认 `0,0,1920,1080`） | `tiled`：窗口平铺所在的屏幕区域；宽和高大于 0 |
| `computer.record_screen` | `off`、`on`（默认 `off`） | `tiled`：为每次对话录制窗口所在的屏幕（`screen.mkv`，放在它的 trace 旁边，每一帧带有时间），供 [`harness replay`](/docs/zh-cn/use/replay/) 使用 |
| `computer.browser_locale` | 语言标签，例如 `en-US`，或 `system`（默认 `system`） | 后台浏览器向网站请求的语言（页面的 `navigator.language`、`Accept-Language`、日期和数字）；`system` 使用这台电脑的语言 |
| `computer.displays` | 0 到 16（默认 2） | 可同时运行的 display 工作区数（每个是一个显示服务器或一台虚拟机）；超出的新工作区等待 |
| `computer.display_backend` | `auto`、`local`、`vm`（默认 `auto`） | display 工作区运行在什么上：`auto` 在 Linux 上是显示服务器，在 Windows 和 macOS 上是虚拟机；`local` 是显示服务器（Linux）；`vm` 是虚拟机 |
| `computer.vm_image` | 文本，最多 200 个字符（默认为空） | display 工作区的虚拟机启动用的磁盘镜像：x86-64 桌面系统，格式为 qcow2、vmdk、vhdx、vdi、raw 或 live ISO，或 VMware 文件夹，在 macOS 上也可以是 Tart VM 文件夹。每个工作区运行在自己的一层之上，结束时删除；镜像本身永远不变 |
| `computer.vm_hypervisor` | `auto`、`qemu`、`vz`（默认 `auto`） | `auto`：QEMU，在 macOS 上对 Tart 文件夹或 raw 磁盘使用 Virtualization.framework；`qemu`；`vz`：macOS 的 Virtualization.framework |
| `computer.vm_memory` | 512 到 65536 MiB（默认 2048） | 每个 display 工作区虚拟机的内存 |
| `computer.vm_cpus` | 1 到 64（默认 2） | 每个 display 工作区虚拟机的处理器数 |
| `computer.vm_accel` | `hardware`、`any`（默认 `hardware`） | `hardware`：只使用系统的 hypervisor（Windows Hypervisor Platform、macOS、KVM）；`any`：没有时用软件模拟，慢很多 |
| `computer.vm_user` | 文本，最多 100 个字符（默认 `admin`） | 客户机屏幕共享使用的用户（Virtualization.framework 虚拟机）；密码为 `$HARNESS_VM_PASSWORD`，默认 `admin` |

## physical

agent 何时可以使用你真实的鼠标和键盘。发送给后台窗口的输入从不需要它；这个策略只决定需要它的步骤。

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `physical.level` | 级别，从最严到最松：`never`、`ask_each`、`ask_once_app`、`ask_once_session`、`when_idle`、`allow`（默认 `ask_once_app`） | 没有规则另作规定时的级别：从不；每一步之前询问；在每个应用中第一次时询问；每个会话询问一次；只在你不动电脑时，你一碰就停止；允许（仍然轮流使用输入，并让给你） |
| `physical.rules` | 最多 200 条规则的列表（默认无） | 每条规则 `{level, session, agent, app, window, action, idle_seconds}` 在其范围匹配时设定一个级别：一个会话、一个 agent、一个应用（进程名，或 `chrome*` 这样的 glob）、一个窗口（标题的一部分，或 glob）、一类动作（`pointer`、`drag`、`keyboard`、`clipboard`、`foreground`）。匹配的规则中最具体的生效：先看范围数量多少，再看范围更窄（窗口、应用、agent、会话、动作），最后看规则更靠后。包含多类动作的一步取最严的级别 |
| `physical.idle_seconds` | 0.0 到 600.0（默认 2.0） | `when_idle`：你不动电脑多少秒后 agent 才可以行动；规则可以带自己的值 |
| `physical.max_hold_seconds` | 0.5 到 60.0（默认 3.0） | agent 轮流使用输入时，每个最多占用这么久，然后交给下一个等待者 |
| `physical.yield_on_user_input` | `true`、`false`（默认 `true`） | 你使用鼠标或键盘时拒绝 agent 的步骤 |
| `physical.corner_stop` | `true`、`false`（默认 `true`） | 把指针移到屏幕一角会让 agent 停止 |

当某个级别需要询问时，你的回答可以只对这一步、这个应用、整个会话有效，或者永久有效（在
`physical.rules` 中添加一条规则）。

## privacy

模型能了解 agent 不拥有的窗口的哪些信息。agent 拥有它启动的或在其中工作的窗口，以及 display
工作区的每个窗口；对这些窗口，模型了解全部信息。

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `privacy.level` | 级别，从最严到最松：`none`、`presence`、`apps`、`titles`（默认 `presence`） | 没有规则另作规定时的级别：`none` 什么都不知道，连有其他窗口在前面都不知道；`presence` 只知道有其他窗口在前面；`apps` 还知道每个其他窗口的应用；`titles` 还知道它们的标题。在 desktop 工作区中，截图仍然显示你的屏幕 |
| `privacy.rules` | 最多 200 条规则的列表（默认无） | 每条规则 `{level, session, agent, workspace, app, window}` 在其范围匹配时设定一个级别：一个会话、一个 agent、一种工作区（`desktop`、`apps`、`display`）、一个应用（进程名，或 glob）、一个窗口（标题的一部分，或 glob）。匹配的规则中最具体的生效：先看范围数量多少，再看范围更窄（窗口、应用、工作区、agent、会话），最后看规则更靠后 |

## personal

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `personal.about` | 文本，最多 4000 个字符（默认为空） | agent 应该了解的关于你的信息；加入每一次新对话 |
| `personal.instructions` | 文本，最多 4000 个字符（默认为空） | 你希望 agent 如何工作；以你的原话加入每一次新对话 |

## data

| 键 | 取值（默认值） | 作用 |
|---|---|---|
| `data.keep_days` | 0 到 3650（默认 0） | app 启动时删除早于这么多天的对话；0 表示全部保留 |
