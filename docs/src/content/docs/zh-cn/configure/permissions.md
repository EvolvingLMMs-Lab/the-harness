---
title: "权限和隐私"
description: "agent 何时可以使用你真实的鼠标和键盘、它会了解到你的哪些窗口信息、它向模型 provider 发送什么，以及你的数据保存在哪里。"
---

在你自己电脑上工作的 agent 可以接触到你的应用、账户和文件。本页的设置决定它能走多远。每项设置都是分级的：一个适用于所有情况的级别，以及为某个应用、窗口、操作类型、会话或
agent 另设级别的规则。它们保存在 `~/.harness/config.toml` 中；app 中它们位于 **Settings → Mouse and keyboard** 和 **Settings → Permissions
and limits**。

首次运行桌面或后台应用任务前，需要明确选择真实键鼠权限和其他窗口信息范围，没有直接回车就接受的默认答案；取消则不启动任务。已有明确配置及本次任务参数继续生效。电脑任务还会单独询问是否保存屏幕录像。

## 鼠标和键盘

agent 的一步操作通过以下三种方式之一到达窗口，按顺序尝试：

1. **语义**：通过窗口的无障碍树，例如按下按钮或设置字段的值。
2. **定向**：只发送给那个窗口的输入，或发送给它启动的浏览器的输入。
3. **物理**：你真实的鼠标和键盘。

前两种不会动你的鼠标、键盘和焦点。**物理输入级别**决定何时可以使用第三种。后台浏览器和独立显示环境永远不需要它。

| 级别 | 在 app 中 | |
|---|---|---|
| `never` | Don't | 需要它的步骤会被拒绝，并告诉 agent 原因 |
| `ask_each` | Ask me every time | 每一步之前都询问 |
| `ask_once_app` | Ask me the first time in each app | 在本次会话中，每个应用第一次使用时询问 |
| `ask_once_session` | Ask me once per chat | 在本次会话中第一次使用时询问 |
| `when_idle` | Only while I'm away | 只在你离开电脑一会儿之后才使用，你一碰电脑就停止 |
| `allow` | Go ahead | 允许，但仍和其他 agent 轮流使用，并且仍然让着你 |

### 规则

规则为电脑的一部分设置级别，可以按应用（进程名，支持 glob）、窗口标题、操作类型（`pointer`、`drag`、`keyboard`、`clipboard`、`foreground`）、会话或
agent 指定。匹配的规则中最具体的一条优先。

```toml
# ~/.harness/config.toml
[physical]
level = "ask_once_app"

[[physical.rules]]
level = "never"
app = "wechat"

[[physical.rules]]
level = "never"
app = "bank*"

[[physical.rules]]
level = "when_idle"
app = "figma"
action = "drag"
idle_seconds = 10

[[physical.rules]]
level = "ask_each"
action = "clipboard"
```

当级别要求询问时，这一步会等待，会话会询问你：哪个应用、哪个窗口，以及 agent 想在那里做什么。你的回答可以保留到：这一步、本次会话中的这个应用、本次会话中的所有应用，或者永远（写成设置中的一条规则）。

### 修改它

在 `harness` 里用 `/settings`，在 app 里用 **Settings → Mouse and keyboard**，或者直接编辑 `config.toml`：worker 每次在级别和规则变化时都会重新读取。eval 包的实验可以只为一次运行指定它们（`harness run EXPERIMENT
--physical LEVEL`，`--allow-app`、`--ask-app` 和 `--deny-app` 在你的规则之后添加规则）。

### 你优先

| 设置 | 默认值 | |
|---|---|---|
| `physical.yield_on_user_input` | 开 | 你使用电脑时，步骤会等待 |
| `physical.idle_seconds` | 2 | 你离开电脑多久之后 `when_idle` 才会操作 |
| `physical.max_hold_seconds` | 3 | 一个 agent 占用鼠标和键盘多久后交给下一个 |
| `physical.corner_stop` | 开 | 把指针推到屏幕角落会停止 agent |

## 取用另一个环境

对话从你选的环境开始。某一步在那里做不了时，agent 可以请求在同一个对话里取用另一个环境：项目任务要看页面渲染成什么样，就取用浏览器或你的桌面；桌面任务要运行命令，就取用一个项目文件夹。它会说明理由，询问里会显示这个理由：

```text
it wants to do something that waits for you (another environment): use Your desktop
    why: to check how the changed page renders
```

`environments.attach` 是对所有环境生效的级别，规则可以为某一种环境另设级别：

| 级别 | |
|---|---|
| `never` | 拒绝；agent 继续用自己的环境，并说明没能确认的部分 |
| `ask_each` | 每次都问 |
| `ask_once_session`（默认） | 每个对话里每种环境第一次时询问 |
| `allow` | 不询问，直接取用 |

```toml
[environments]
attach = "ask_once_session"

[[environments.rules]]
level = "never"
kind = "desktop"
```

- 如果你已选择跳过确认（`physical.level = "allow"`，写在设置里，或某次运行用 `--physical allow`），就不再询问。`never` 级别仍然拒绝。
- 无论是否询问，每次取用的环境、理由和放行方式都会显示在对话里、画在时间轴上，并写进 trace。
- 没有人可问的场合（脚本、Python 接口）而级别要求询问时，请求会被拒绝并说明原因。不会等待，也不会默默放行。
- 取用你的桌面不等于拿到你的鼠标和键盘：用到它们的每一步仍由上面的真实键鼠级别决定。
- 取用的环境计入同样的工作区上限，agent 归还或对话结束时释放。

## 它会了解到你的哪些窗口信息

为了找到方向，模型可能会被告知 agent 没有自己打开的窗口。**窗口详情**级别决定告知多少：

| 级别 | 模型了解到 |
|---|---|
| `none` | 你的窗口的任何信息都不告知 |
| `presence` | 有其他窗口存在 |
| `apps` | 它们属于哪些应用 |
| `titles` | 它们的标题 |

```toml
[privacy]
level = "apps"

[[privacy.rules]]
level = "none"
app = "bank*"
```

在 `harness` 里用 `/settings`，或在 app 的 **Settings** 里修改级别和它的规则。

## 审批

worker 或工具会标记涉及凭据、付款、发送、删除或其他不可撤销的操作。网页地址本身不会让导航操作变成敏感操作。
由宿主管理的操作可以逐次批准。普通 worker 拒绝敏感动作时，该步骤结束。无人值守时拒绝敏感操作。

`approvals.ask = "programs"` 也会要求每个程序先得到批准。应用输入框旁的 **Ask before acting** 只为当前对话设置此策略。
被拒绝的操作不会执行，agent 会看到拒绝理由。

Claude Code 和 Codex 子 agent 可以操作各自工作区中的文件，并继承父对话的批准策略。它们无法使用 shell 或外部连接器。

## 限额

**Settings → Permissions and limits** 限制一个对话能花费多少：每个任务的步数、每个对话的分钟数和金额，以及它最多能启动几层子
agent。子 agent 从父 agent 的预算中支出（[会话](/docs/zh-cn/use/sessions/#预算)）。

## 什么会离开你的电脑

agent 拍下的每张截图都会随请求发送给模型 provider，所以屏幕上的任何内容 provider 都能看到。关闭任务不需要的内容，或者给 agent
一个后台浏览器或独立显示环境。除此之外不会发送任何东西：对话、截图、设置和密钥都留在这台电脑上。

| 位置 | 内容 |
|---|---|
| `~/.harness/conversations/` | 每个对话：它的 trace、截图和标题 |
| `~/.harness/config.toml` | 你的模型、密钥、设置和规则，只有你能读取 |
| `~/.harness/host/` | session host 的地址和密钥，只有你能读取 |

**Settings → Data** 显示你的对话占用的空间，可以导出一个对话、删除早于若干天的对话，或全部删除。

## 程序在隔离中运行

agent 的程序在一个单独的进程中运行：它只能读取 Python 和 The Harness 本身，只能写入一个新建的工作文件夹，不能启动进程，只能连接它的
skill 用到的服务；你的主目录不在它的访问范围内。这些检查让程序远离你的数据；它们不是防范蓄意逃逸的沙箱。你安装的 skill
或包以你的权限运行，这就是 The Harness 在安装官方 registry 之外的包之前会询问的原因（[包](/docs/zh-cn/configure/packages/#信任)）。

### 隔离工作区

在具备 Bubblewrap、系统 Python 和 libseccomp 的非 root Linux 上，通过终端的 `--managed-workspace` 或 App 的隔离工作区选项启用。此模式使用单独显示或浏览器，工作区没有外网访问，只开放列出的同步技能调用。工作区启动或握手失败时，会话报错。普通外接 worker 的敏感拒绝仍是终态。

部署者可以通过 `HARNESS_BWRAP` 指定绝对路径，供系统 PATH 之外的 Bubblewrap 使用。可执行文件及其父目录必须由 root 或宿主用户持有，且其他用户不可写。已有的 `HARNESS_CHROME_PATH` 和 `HARNESS_XVFB` 可以指定工作区的浏览器和显示程序。

已投递但丢失回执时，宿主只查询已有结果。无法确认时显示「结果未知」，不重发。
