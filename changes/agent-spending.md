---
core: minor
agent: minor
acp: patch
---
Each agent identity has a daily budget for model calls ($2 by default, reset at 0:00,
setting `agent.daily_budget`) and a daily cap on calls without a price (500, setting
`agent.daily_calls`), checked before every call it makes, in its dialogue and in the tasks
it starts. OpenRouter's reported cost counts; another provider's is estimated from `prices`
on its model entry; a local model costs nothing and counts against the call cap. At the
limit a call already made finishes, the model is not called again until 0:00, and programs
that run go on. `harness usage`, `/usage` and the status line of `harness` show what the
identity spent today; `harness usage --raise-today DOLLARS` raises today's budget only.
<!-- zh -->
每个 agent 身份有每日模型调用额度（默认 2 美元，0:00 重置，设置 `agent.daily_budget`）和没有价格的调用的每日次数上限（500 次，设置 `agent.daily_calls`），它的每次调用之前都会检查，包括对话里的和它启动的任务里的。OpenRouter 报告的费用按实计；其他 provider 按模型条目上的 `prices` 估算；本地模型不花钱，计入调用次数上限。到达额度时，已经发出的调用会做完，到 0:00 之前不再调用模型，正在运行的程序继续。`harness usage`、`/usage` 和 `harness` 的状态行显示身份今天花了多少；`harness usage --raise-today DOLLARS` 只提高今天的额度。
