---
title: "用 CLI 运行"
description: "harness 命令：第一句话、打印模式、status、doctor、config、sessions 和 logs；用 harness run 做一个任务；用 harness run rpc 从另一个程序驱动对话。"
---

`harness` 用来和 agent 对话，照看它也用同一个命令：它接入了什么、它的设置、它的对话、它的日志。要从脚本或另一个程序使用任务引擎，`harness run` 和 `harness run rpc` 不需要在屏幕上显示对话。

## 日常的命令

```bash
harness                              # the chat
harness "explain this folder"        # the chat, started with that message
harness -p "what changed today?"     # answer and exit
git diff | harness -p "review this"  # what is piped in goes with the question
harness -c                           # go on with the most recent chat
harness -r "trip notes"              # go on with a chat, by its id or title; -r alone lists them
```

不是命令的词就是对话的第一句话。和某条命令只差一点的单个词会被当成打错了：`harness udpate` 打印 `Did you mean harness update?`，以退出状态 2 结束，什么都不启动。`harness --help` 用一屏列出所有命令，`harness COMMAND --help` 说明其中一条。

`-p`（`--print`）不显示对话界面，直接回答：agent 身份在它自己的一个新对话里接下这个问题（`-c`：在最近的对话里，`-r CHAT`：在指定的对话里），这一回合结束时命令结束，答出来了退出状态就是 0。`--output-format` 可以是 `text`（答案）、`json`（一个对象：`result`、`is_error`、`session_id`、`identity`）或 `stream-json`（这一回合的每条记录各一行，最后是那个对象）。`--model ENTRY` 让这个对话用模型列表里的另一个模型。Ctrl+C 停下这一回合。

| 命令 | |
|---|---|
| `harness status` | 一屏显示版本、模型、身份、会话宿主和接入的东西（`--json`） |
| `harness doctor` | 这台电脑缺什么，每一行带修法：Python、模型及其 key 或登录状态、会话宿主能否启动、被跳过的扩展包、这个终端里的 `harness` 是哪一个。什么都不缺时退出状态为 0，否则为 1（`--json`） |
| `harness setup`、`harness model` | 重新走一遍首次引导；只选模型 |
| `harness config show \| get KEY \| set KEY VALUE \| unset KEY \| edit \| path` | 设置，每一项的名字是 `section.key`（[设置](/docs/zh-cn/reference/settings/)）；`--identity ID` 读写一个 agent 身份自己的值；提供商的 key 用它的变量名设置（`harness config set OPENROUTER_API_KEY ...`），和凭据存在一起 |
| `harness sessions` | 身份的对话：`list`（`-q TEXT`、`--archived`）、`new`、`rename CHAT TITLE`、`pin`、`archive`、`delete`；以及任务的会话（`ls`、`show`、`stop`、`resume` 等） |
| `harness logs [NAME] [-n N] [-f]` | 一个日志的最后几行（默认是会话宿主的）；`harness logs list` 列出有哪些日志 |
| `harness host [status \| start \| stop \| restart \| install \| uninstall]` | 会话宿主：它怎么运行、启动或停止它、登录时启动它 |
| `harness usage`、`harness calendar`、`harness agent`、`harness library` | 一个身份的花费、日历、身份本身，以及它学到的东西（[身份](/docs/zh-cn/use/identities/)、[花费](/docs/zh-cn/use/spending/)） |
| `harness channels`、`harness mcp`、`harness agents`、`harness skills` | 它接入的东西；每一类都有 `list`、`add`、`remove` 和 `test`（[接入 MCP 服务器和 Agent Skills](/docs/zh-cn/extend/mcp/)） |
| `harness update` | 更新 The Harness 和已安装的扩展包 |
| `harness completion bash \| zsh \| fish` | 打印补全脚本：`harness completion bash >> ~/.bashrc` |

有两条扩展包的命令和上面的同名：`harness config EXPERIMENT` 是评测包的（一个实验解析后的配置），带服务名或 `--deploy` 的 `harness status` 是 `local-models` 包的（一个 deploy 的服务）。

选项写在命令之后，例如 `harness run "task" --model MODEL`。终端和 `harness run` 续接时都保留会话原来的模型、工作区和运行设置，不接受 `--model`、`--effort`、`--folder` 等新对话选项。打开终端后，`/effort LEVEL` 改变当前对话，`/model` 只选择新对话的模型。重新启动已结束的会话，需要它保存的模型条目仍处于启用状态。终端的 `--agent` 也不接受 `--model` 或 `--effort`；要给外部 agent 的单次任务指定推理强度，使用 `harness run "task" --agent NAME --effort LEVEL`。

## 一个任务：harness run

```bash
harness run "Rename the photos in ~/Pictures/trip by the date they were taken."
```

`harness run "task"` 把任务交给 agent，随过程打印对话，并随 agent 的这一轮结束：它回答了，或者某个上限或错误结束了这一轮。它回答了，退出码为 0；以错误结束或没有回答，退出码为 1；用法错误（包括还没设置模型、又没有终端可以询问）为 2；按 Ctrl-C 为 130。

| 选项 | |
|---|---|
| `-p`, `--print` | 只打印 agent 的答案 |
| `--json` | 把这次运行 trace 的每条记录在写出时打印为一行 JSON |
| `--continue`、`--session ID` | 这个任务是最近一次发送消息或续接的 session（或指定的那个）的下一轮，带着它的消息和 facts（见[轮次，以及之后继续](/docs/zh-cn/use/sessions/#turns-and-going-on-later)） |
| `--workspace none\|project\|browser\|desktop\|apps\|display` | 它在哪里工作：`none` 只对话（模型和已连接的工具，不启动任何东西）；`project` 在 `--folder` 指定的文件夹里工作。两者都没给时由设置 `session.environment` 决定：在终端里会在 stderr 上询问，并高亮你上一次的选择，回答被管道接走时也一样（`answer=$(harness run "task" -p)`）；没有终端或用了 `--json` 时，`ask` 会报错并指出这个参数，不会替你选 |
| `--folder PATH` | 项目任务的文件夹 |
| `--space ADDRESS` | 在这个地址的 space 里工作（任何说 Agent Space Protocol 的 space 的 `ws://` 或 `http://` URL；即 `--workspace space`）：agent 通过它的词汇行动（[Space](/docs/zh-cn/concepts/spaces/)） |
| `--agents` | 这个对话打开子 agent（默认关闭，除非 `session.agents` 为 `on`） |

```bash
version=$(harness run "What is the newest stable Python release? Answer with the version only." -p)
harness run "Summarize the open issues of github.com/EvolvingLMMs-Lab/the-harness." --json > events.jsonl
```

每行 JSON 是一条 trace 记录，包含 `seq`、`time`、`event` 以及该类记录的字段：模型的请求和回复、每个程序及其结果、每次 skill 调用、agent 的消息、状态变化。[事件和 trace](/docs/zh-cn/reference/traces/) 列出了全部记录。这次运行和任何对话一样保存在 `~/.harness/conversations/` 下，所以 `harness replay` 可以再次显示它。

当一步要等你时（敏感步骤、你的鼠标和键盘，或者 `approvals.ask = "programs"` 下的每个程序），`harness run` 会在终端里问 `Allow it?
[y/N]`；没有终端时它会拒绝并附上原因，agent 会读到。

必须先设置好模型：在终端里运行一次 `harness`，或者导出 provider 的 key。

## 从另一个程序进行对话：harness run rpc

```bash
harness run rpc
```

`harness run rpc` 启动一个由标准输入上的 JSON 行驱动的新对话，并把记录作为 JSON 行写到标准输出。输入关闭或对话结束时，它就结束。RPC 不接受 `--continue` 或 `--session`；续接已有对话请使用单任务形式的 `harness run`。后台输出不会改变 `--continue` 选择的目标，脚本也可以用 `--session ID` 明确指定。

| 输入（每行一个 JSON 对象） | |
|---|---|
| `{"type": "prompt", "text": "...", "files": ["..."]}` | 第一条开始对话；之后的是给它的消息（一轮的 `turn_result` 记录之后，消息开始它的下一轮）；`files`（可选）：附上的文件路径 |
| `{"type": "message", "text": "...", "files": ["..."]}` | 发给 agent 的消息，它会立即收到 |
| `{"type": "pause"}`, `{"type": "continue"}` | 在下一步停下、继续 |
| `{"type": "approve", "remember": "app"}` | 批准它在等待的东西；用你的鼠标键盘时，`remember`（可选）记住这个回答：`once`、`app`、`session` 或 `always` |
| `{"type": "reject", "reason": "..."}` | 拒绝，并说明原因（可选） |
| `{"type": "confirm", "accept": true, "reason": "", "remember": "app"}` | 批准或拒绝，同上 |
| `{"type": "end"}`, `{"type": "stop"}` | 结束对话 |

这些就是终端对话的命令（`/pause`、`/continue`、`/approve [app | session | always]`、
`/reject [why]`、`/end`），效果相同。

子 agent 的等待消息包含 `agent` 和 `request_id`。回复 `approve`、`reject` 或 `confirm` 时原样带回这两个字段。主 agent 的确认也可带上对应的 `request_id`。

| 输出 | |
|---|---|
| `{"type": "started", "run": "..."}` | 对话已开始 |
| `{"type": "waiting", "agent": "a1", "what": "...", "request_id": "..."}` | 子 agent 等待批准 |
| `{"type": "record", "record": {...}}` | 它的 trace 中的一条记录 |
| `{"type": "error", "message": "..."}` | 它无法接受的一行 |

一个用 Python 写的小驱动程序：

```python
import json
import subprocess

agent = subprocess.Popen(["harness", "run", "rpc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
agent.stdin.write(json.dumps({"type": "prompt", "text": "Find the opening hours of the city library."}) + "\n")
agent.stdin.flush()
for line in agent.stdout:
    message = json.loads(line)
    record = message.get("record", {})
    if record.get("event") == "agent_message":
        print(record["text"])
    if record.get("event") == "turn_result":      # the turn is over; another prompt would go on
        break
agent.stdin.write(json.dumps({"type": "stop"}) + "\n")
agent.stdin.close()
```

要启动和引导多个会话，或者跟进 app 和终端启动的对话，用 [Python API](/docs/zh-cn/extend/python-api/)。

## benchmark 和成组的任务

在一个 benchmark 的任务和 seed 上运行 agent、续跑这样的运行以及为它打分，这些功能随 benchmark 的包提供：安装相应的评测包，它在[包目录](https://harness.lmms-lab.com/packages/)上的 README 介绍了它的命令。
