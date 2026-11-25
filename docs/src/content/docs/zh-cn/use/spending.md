---
title: "限制身份的花费"
description: "每个 agent 身份都有每天的模型调用额度，以及没有价格的调用的每日次数上限；查看它花了多少，提高今天的额度。"
---

agent 身份每次调用模型都要花钱：在对话里、在它启动的任务里、在程序向模型提问时。每个身份都有一个**每日额度**，默认 2 美元，每一次这样的调用之前都会检查。每天在本地时间 0:00 重置。

## 一次调用花多少钱

- **OpenRouter** 会报告每次调用花了多少钱，以它为准。
- **其他 provider** 不报费用：在模型清单的条目里写上模型价格（`"prices": {"input": 0.27, "output": 1.1}`，每百万 token 的美元价格，见[模型和 provider](/docs/zh-cn/configure/models/)），就按 token 估算。
- **你电脑上**或本地网络里的模型（Ollama、vLLM 服务）算 0 美元。

没有价格的调用（本地模型的调用，或没写价格的 provider 的调用）改为计入身份的**每日调用次数**，默认 500 次。这样当天的钱用完后本地模型仍然能用，不报费用的 provider 也有上限。

## 到达额度时

额度用完时，已经发出的调用会做完并计入，即使结束时略超一点。之后到 0:00 之前不再调用模型：

- 对话的这一轮以“今天的花费额度已用完”结束；其中正在运行的程序和反应规则继续运行，结果留到下一轮；
- `harness agent say` 返回额度说明，退出码为 3。

## 查看花费

```sh
harness usage
harness usage --week --identity work
harness usage --json
```

显示今天的花费和额度、有价格和没有价格的调用次数，以及每个花了钱的对话和任务；加 `--week` 还显示最近七天。在终端对话里，`/usage` 显示同样的内容，状态行显示身份和它今天的花费，例如 `工作 (work) · today $0.46`。

## 提高或修改额度

```sh
harness usage --raise-today 5
harness usage --budget 3 --identity work
harness usage --calls 1000
```

`--raise-today` 只提高今天的额度，明天恢复为设置值。在终端对话里 `/usage raise 5` 效果相同。`--budget` 和 `--calls` 从现在起修改这个身份自己的上限。设置 `agent.daily_budget` 和 `agent.daily_calls`（[设置](/docs/zh-cn/reference/settings/#agent)）是所有没有自己上限的身份的上限。

OpenRouter 也可以给 key 本身设一个每日重置的上限，对所有使用这个 key 的东西生效。

## 在 Python 里

```python
from harness.sdk import Agent

work = Agent("work")
print(work.usage(week=True)["today"]["cost_usd"])
work.raise_today(5)
work.set_budget(3)
```
