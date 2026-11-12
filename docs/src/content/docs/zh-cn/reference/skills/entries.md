---
title: "entries"
---

把代码作为一个独立的单元启动：spawn、wait、cancel、send，带优先级；占用和放开通道。

- **层**: base
- **所需服务**: –
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 否
- **Mixin**: `skills.entries:Entries`
- **清单**: `skills/entries/skill.toml`

## 函数

### `spawn`

```python
def spawn(fn, name=None, claims=None, priority=None, restart=False)
```

让 fn() 和当前代码同时运行，作为一个独立的单元，返回它的句柄：.wait(timeout=None) 返回 fn 的返回值（它失败时抛出它的失败，即一个 ENTRY_FAILED 事件；被取消或超时则返回 None），.cancel() 结束它，.send(message) 给它发一条消息，它的代码用 receive() 读取，.state() 说明它现在的情况，.status 是 running、done、failed 或 cancelled。`name` 是它的标签（默认用 fn 的名字）。`priority`：它持有 embodiment 所用的优先级（默认：启动它的单元的优先级）；优先级高的单元让优先级低的单元的执行在当前位置结束，带着事件 PREEMPTED 和它已经做了的事，并持有环境直到自己结束；模型立即得知。写明 restart=True 时，较低的那次调用在高优先级单元结束后被重新启动。优先级相同的单元轮流进行，按开始的先后。`claims` 写它在 embodiment 声明了通道时要用的通道：它一直占着这些通道直到结束，结束时它在这些通道上按住的东西都会松开；如果其中有通道已被别的单元占着，它会立刻以 CHANNEL_CONFLICT 事件失败。这个单元属于模型：它以及它设置的规则和 handler 在启动它的程序结束后继续存在，随模型结束。失败的单元交给正在等它的人，否则交给 handler（on("ENTRY_FAILED", ...)）；每个单元的结束模型都会得知。

### `receive`

```python
def receive(timeout=None)
```

当前代码所在条目收到的最早一条消息（handle.send 发来的），最多等 `timeout` 秒（None：一直等）；没等到则返回 None。

### `entries`

```python
def entries(running=True)
```

到目前为止启动的单元的句柄（默认只列正在运行的，`running` 为 False 时全部列出），按启动先后；每个都有 .state()、.wait()、.cancel()、.send()；子 agent（delegate）的单元还有 .agent。

### `claim`

```python
def claim(*channels)
```

为当前代码所在的条目占用通道，直到它放开（unclaim）或结束；这期间别的条目不能用，它自己启动的条目可以用。返回 True；若其中有通道属于别的条目，CHANNEL_CONFLICT 事件交给这个条目的 handler 再往上（某个 handler 接下时返回 False）。

### `unclaim`

```python
def unclaim(*channels)
```

放开通道（不写则放开这个条目占的全部）：它的占用，以及它在这些通道上按住的键和按钮。

命名空间还包含：`channels`（常量及 skill 的 `exports(session)` 提供的名称）。
