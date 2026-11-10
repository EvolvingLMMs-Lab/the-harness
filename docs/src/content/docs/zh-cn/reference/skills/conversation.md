---
title: "conversation"
---

不用环境的对话：它的状态、show() 和 finish()。

- **层**: base
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 是
- **Mixin**: `skills.conversation:Conversation`
- **清单**: `skills/conversation/skill.toml`

<a id="functions"></a>

## 函数

### `finish`

```python
def finish(summary="")
```

立即结束任务，`summary` 即回答。

### `get_state`

```python
def get_state()
```

状态：没有环境，只有步数。

### `get_observation`

```python
def get_observation()
```

没有可看的内容：`{"state", "images": {}}`。

### `show`

```python
def show(what, caption="")
```

把一张图（例如一幅图表）附到你收到的下一条消息里。
