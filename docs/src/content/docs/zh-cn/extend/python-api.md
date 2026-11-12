---
title: "使用 Python API"
description: "启动并控制会话，在 trace 写入时读取它们，管理包，并在你自己的进程中运行一个 episode。"
---

app 和 CLI 能做的一切都可以在 Python 中完成。有三个入口：

| 模块 | 用途 |
|---|---|
| `harness.host` | session host 的会话，与所有其他前端共享 |
| `harness.packages` | 安装和列出包 |
| `harness.sdk` | 包所基于的接口：skill、`ClosedLoop`、事件、worker |

## 会话

```python
from harness.host import Host

host = Host.connect()                        # starts the session host when it does not run
conversation = host.start(
    experiment="computer",
    workspace="browser",
    instruction="Find the opening hours of the city library.",
)

for record in conversation.records():        # the trace's records, as they are written
    if record["event"] == "agent_message":
        print("agent:", record["text"])
    if record["event"] == "turn_result":     # the turn is over: an answer, a limit or an error
        break

conversation.send_message("And on Sundays?")   # the same conversation goes on
conversation.close()
```

`host.start` 接受 `experiment`、`task`、`seed`、`model`、`workspace`、`instruction`、`confirmation`（每个程序运行前询问）、`sets`（`--set`
项）和 `title`。它返回一个对话，具有：

| 方法 | |
|---|---|
| `send_message(text)` | 给 agent 的一条消息，agent 会立即收到；一轮结束之后，它开始下一轮 |
| `cancel()` | 结束正在进行的这一轮；对话等待下一条消息 |
| `pause()`、`resume()` | 在下一步停下，继续 |
| `confirm(accept, reason="", remember=None)` | 回答它正在等待的内容：一个程序，或鼠标和键盘（`remember`：`once`、`app`、`session`、`always`） |
| `close()` | 结束对话 |
| `records()` | trace 的记录，先给出旧的，然后在新记录到来时给出 |
| `describe()` | 它的会话：状态、它在等待什么、它的 agent |
| `memory()` | 它记得的东西：这一局的条目（看到了什么、在哪里）和它的 library 的条目，统一格式 |

host 列出并控制每个会话，无论是哪个前端启动的：

```python
for session in host.sessions():
    print(session.id, session.status, [agent["id"] for agent in session.agents()])

host.approve("3f9a")                          # what an agent of the session waits for
host.stop_session("3f9a")
host.conversation("3f9a/a1").send_message("Use the other account.")   # one of its agents
```

每条记录是一个字典，包含 `seq`、`time`、`event` 以及它所属类型的字段；
[事件和 trace](/docs/zh-cn/reference/traces/) 列出了所有类型。

## 包

```python
from harness import packages

packages.install(["workspace"])          # and what it depends on
packages.installed()                     # [{name, version, source, provides, ...}]
packages.search("robot")
packages.info("browser")
packages.update()
packages.remove(["workspace"])
```

与 `harness install`、`harness list` 以及其他包命令相同（[包](/docs/zh-cn/configure/packages/)）。

## 在你自己的进程中运行 episode

要把 agent 嵌入你自己的程序，不经过 session host，就在你的进程中运行一个对话：

```python
from pathlib import Path

from harness.runtime.task.run import TaskRun
from harness_eval.run import load_task_config

config = load_task_config("my-experiment.toml", task="play", seeds=[0])
conversation = TaskRun(config, 0, Path("runs/mine/seed-0"), interactive=True)
conversation.trace.subscribe(print)      # every record as it is written
conversation.start()                     # the episode runs on a thread of its own
conversation.send_message("Collect the coins first.")
conversation.close()
```

episode 随你的进程一起结束。

## 面向包：harness.sdk

包内的代码只通过 `harness.sdk` 导入 The Harness：会话和 skill 的约定、`ClosedLoop`、事件和 trace、embodiment 和
bench、服务客户端、设置和路径。它只会随新的主版本做不兼容的变更。
[编写 skill](/docs/zh-cn/extend/skills/) 和[编写包](/docs/zh-cn/extend/packages/)展示了它的用法，
[Python API 参考](/docs/zh-cn/reference/api/)记录了每个模块。
