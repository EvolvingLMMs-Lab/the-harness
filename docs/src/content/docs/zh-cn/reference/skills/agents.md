---
title: "agents"
---

把任务的一部分交给同时工作的子 agent，每个子 agent 有自己的工作区，然后等它们的结果。

- **层**: base（可选：仅在配置启用时提供）
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 否
- **Mixin**: `skills.agents:Agents`
- **清单**: `skills/agents/skill.toml`

## Functions

会话宿主提供的接口。

### `delegate`

会话宿主提供的接口。

```python
def delegate(task, workspace='new', budget=None, model=None, agent=None, multi_turn=False)
```

相关标识为 `task`、`workspace`、`budget`、`model`、`agent`、`multi_turn=True`、`send_agent`。

### `wait_agents`

会话宿主提供的接口。

```python
def wait_agents(ids=None, timeout=None)
```

相关标识为 `ids`、`timeout`。

### `send_agent`

会话宿主提供的接口。

```python
def send_agent(agent, text)
```

相关标识为 `agent`。

### `cancel_agent`

会话宿主提供的接口。

```python
def cancel_agent(agent)
```

相关标识为 `agent`。
