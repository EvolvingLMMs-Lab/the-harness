---
title: "用 CLI 运行"
description: "用 harness run 从脚本做一个任务，以 JSON 读取它的答案或事件，并用 harness run rpc 从另一个程序驱动对话。"
---

`harness` 用来和 agent 对话。要从脚本或另一个程序使用它，有两个命令可以做同样的事，而不需要在屏幕上显示对话。

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
