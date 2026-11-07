---
title: "会话和子 agent"
description: "从所有前端同时进行多个对话，用子 agent 拆分任务，在任何地方审批，预算对整棵树生效。"
---

一个**会话**就是与 agent 的一个对话：你的任务、它的 trace 和它的工作区。一台电脑上可以同时运行很多会话。每个会话是一棵树：它的主 agent，以及 agent 为了同时处理任务的各个部分而启动的**子 agent**。所有前端（终端、app、Python）启动、列出、加入、审批和结束的都是同一批会话。

## 外部 coding 会话

启用 `external-agents` 包并配置可信的适配器。从终端或 Python
启动的会话共用项目列表和 trace。

```sh
harness agents update
harness agents ls
harness agents install ACP_REGISTRY_ID
harness run "检查此仓库" --agent acp:ACP_REGISTRY_ID --folder . --isolation worktree
harness sessions ls --all --kind acp --project .
```

用 `harness agents add NAME -- COMMAND ARGS` 配置本机 ACP server，用
`harness agents add --terminal NAME -- COMMAND ARGS` 配置终端 CLI。
Registry 列表区分目录、平台发行件和本机安装状态。ACP 操作按 v1 握手和
实际返回的配置开放，agent 使用自己的认证和进程权限。可选的
`--share-mcp-tool project_info` 或 `--share-mcp-tool project_diff` 只把指定
只读工具授予本次 ACP 会话，最长 30 分钟。worktree 用于隔离 Git 改动。

用 `harness sessions import claude-code PATH.jsonl` 或
`harness sessions import codex PATH.jsonl` 导入选定的日志，附加 `--follow`
可跟进追加记录。旧控制者退出后，可用
`harness sessions reconnect ID --agent ACP_ADAPTER --released` 尝试按原 ID
恢复。适配器必须支持原会话及目录。用 `harness sessions handoff ID AGENT "交接上下文"`
会创建关联的新会话。向云端交接时先检查发送的上下文。
对于支持发现的 ACP 适配器，先用 `harness sessions discover ACP_ADAPTER --folder .`
选出原 ID，再用 `harness sessions observe ACP_ADAPTER EXTERNAL_ID --folder .`
将它加入索引，随后可尝试恢复。

托管 worktree 可用 `harness sessions diff ID` 检查。关闭会话并提交其改动后，
`harness sessions merge ID` 可快进合并回原来的干净分支。`harness sessions discard ID`
会移除该 worktree 及其中未提交的改动。

用 `harness agents configure-cloud PROVIDER SETTINGS.json` 配置云端。设置文件
存账号作用域、仓库和 ref 或环境，凭据从指定环境变量或 Harness 凭据存储取得。
`harness sessions discover cloud:PROVIDER` 列出可访问的外部 ID，
`harness sessions observe cloud:PROVIDER EXTERNAL_ID` 以只读方式跟进。
云端操作因厂商而异，七个适配器均处于待实测的实验阶段。

## session host

每个用户有一个后台进程，即 **session host**，运行所有前端的会话。第一个需要它的前端会自己启动它。它只在本机上监听，每次启动都用一个新的 key；当没有打开的会话、并且 30 分钟内没有任何请求时，它就会退出。关闭终端或浏览器标签页不会结束会话。

在 `harness` 里，`/host` 显示 host 是否在运行、它的地址、进程、版本和打开的会话；`/host stop` 让它退出，并结束在其中打开的会话。

## 查看和控制会话

在 `harness` 里，`/sessions` 列出正在运行的会话，每个 agent 列在它的会话下面，带着状态和花费；选一个就切换过去，和它对话。在那里：

| 命令 | |
|---|---|
| `/approve`、`/reject [why]` | 回应它的 agent 在等待的东西 |
| `/pause`、`/continue` | 在下一步停下，继续 |
| `/end` | 结束它 |
| `/resume` | 以前的对话，包括已经结束的 |

每个 agent 的状态是运行中、空闲（这一轮结束了）、已暂停、已完成，或者它在等待的东西：你对一步的批准、你对使用鼠标和键盘的批准、一条消息、一个空闲的工作区，或轮到它使用鼠标和键盘。花费一列汇总每个 agent 的模型调用次数和金额。app 的侧栏显示同一棵树（[在终端里使用](/docs/zh-cn/use/terminal/)）。

## 并行运行

每个会话在自己的工作区里工作。`config.toml` 中 `[computer]` 下的 `workspaces`（或 **设置 → 电脑**）设置同时工作的数量，默认四个；`displays` 设置其中最多几个可以是独立显示屏，默认两个。超过这个数量时，新会话会结束等你最久的那个会话，或者等到有会话结束。

后台浏览器和独立显示屏从不使用你的鼠标和键盘，所以可以自由地并行运行。需要真实鼠标和键盘的会话轮流使用它们，每次一步，你一碰它们就立即让出。每个 agent 只在它自己的窗口里工作：一个 agent 正在操作的窗口，其他 agent 不能使用。

## 审批

agent 在等待的东西可以从任何前端回应：app 里的卡片、`harness` 输入框上方的选项（或在 `/sessions` 之后用 `/approve`），或 Python 里的 `host.approve()`。agent 会等待：

- **一个敏感步骤**，总是如此：涉及凭据、付款、发送、删除或无法撤销的操作的步骤。回答只对这一步有效；
- **一个程序**，当 `approvals.ask` 是 `programs` 时（app 里的 **动手前先问我**）；
- **鼠标和键盘**，当你的权限设置要求先询问时。回答可以保留：仅这一步、这个会话里的这个应用、这个会话里的所有应用，或者一直有效；
- **一条消息**，当 agent 问了你问题时。

详见[权限](/docs/zh-cn/configure/permissions/#审批)。

子 agent 的问题会交给启动它的 agent，由那个 agent 回答或转而问你。

## 子 agent

agent 可以把任务的一部分交给同时工作的子 agent，每个子 agent 在自己的工作区里，然后等待它们的结果。在 app 里，每个对话都开启了这个功能。**设置 → 权限与限额 → 子 agent 层数** 决定可以嵌套多深：0 表示不用子 agent，1（默认）表示对话的 agent 可以启动子 agent，但子 agent 不能再启动，2 表示子 agent 也可以再启动子 agent。

agent 在它的程序里这样做：

| 调用 | |
|---|---|
| `delegate(task, workspace="new", budget=None, model=None)` | 启动一个有自己任务的子 agent；返回它的 id |
| `wait_agents(ids=None, timeout=None)` | 等到每个子 agent 结束或提出问题；返回每个的状态、结果、问题和花费 |
| `send_agent(id, text)` | 回答它的问题，或给它更多工作 |
| `cancel_agent(id)` | 停止它；返回它的报告 |

- **工作区**：`"new"` 是与父 agent 同类的新工作区，`"browser"` 或 `"desktop"` 是该类型的新工作区，`"share"` 在父 agent 等待期间把它占用的窗口交给子 agent。
- **模型**：同一 provider 的另一个模型，用于更便宜或更强的子 agent。
- 子 agent 看不到父 agent 的对话，只看到自己的任务。它在完成、预算用尽或被取消时结束，并报告结果。

## 预算

一个会话对模型调用次数、分钟数和金额都有上限（**设置 → 权限与限额**，或实验的 `[budget]`）。子 agent 的预算 `{"calls", "cost",
"seconds"}` 最多是父 agent 剩下的额度，它花掉的部分会随时记到父 agent 头上，沿着树一直向上到会话。无论有多少个 agent，一个会话的花费都不会超过它的上限。

## 从 Python 使用

```python
from harness.host import Host

host = Host.connect()                       # starts the host when it does not run
conversation = host.start(experiment="computer", workspace="display",
                          instruction="Find the cheapest train to Boston on Friday.")
for record in conversation.records():       # the trace's records as they are written
    print(record["event"])
    if record["event"] == "outcome":
        break
host.stop_session(conversation.session)
```

`conversation` 有 `send_message`、`pause`、`resume`、`confirm` 和 `close`；`host.sessions()` 列出打开的会话，`session.agents()` 列出会话里的 agent。更多内容见[使用 Python API](/docs/zh-cn/extend/python-api/)。

## 保存位置

| 位置 | 内容 |
|---|---|
| `~/.harness/conversations/` | 每个对话：trace、截图，每个子 agent 一个文件夹 |
| `~/.harness/host/` | 正在运行的 host 的地址和 key（只有你能读），以及已结束的会话 |
