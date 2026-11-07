---
title: "entries"
---

把程序的几部分作为一棵树上的条目同时运行：spawn、wait、cancel、send；事件沿树向上交；占用和放开通道。

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
def spawn(fn, name=None, claims=None)
```

让 fn() 和当前代码同时运行，作为当前条目下的一个新条目，返回它的句柄：.wait(timeout=None) 返回 fn 的返回值（它失败时抛出它的失败，即一个 ENTRY_FAILED 事件；被取消或超时则返回 None），.cancel() 停掉它以及它启动的条目，.send(message) 给它发一条消息，它的代码用 receive() 读取，.state() 说明它现在的情况，.status 是 running、done、failed 或 cancelled。`name` 是它的标签（默认用 fn 的名字）；`claims` 写它要用的通道（游戏的 CHANNELS；例如 ["move", "look"]）：它一直占着这些通道直到结束，结束时这些通道上的键和按钮都会松开；如果其中有通道已被别的条目占着，它会立刻以 CHANNEL_CONFLICT 事件失败。没有通道时，各条目的执行轮流使用 embodiment，按开始的先后。在 fn 里设的守卫（when、watch）和 handler（on）属于这个条目：它们看着这个条目的执行以及它启动的条目的执行，并随它结束。失败的条目交给正在等它的人，否则交给启动它的条目的 handler（on("ENTRY_FAILED", ...)），再往上；没人处理的才到你这里。这个程序启动的条目在程序结束后继续运行，每个程序之后你都会看到它们的情况；一个条目自己启动的条目随它结束。

### `receive`

```python
def receive(timeout=None)
```

当前代码所在条目收到的最早一条消息（handle.send 发来的），最多等 `timeout` 秒（None：一直等）；没等到则返回 None。

### `entries`

```python
def entries(running=True)
```

到目前为止启动的条目的句柄（默认只列正在运行的，`running` 为 False 时全部列出），按启动先后；每个都有 .state()、.wait()、.cancel()、.send()；子 agent（delegate）的条目还有 .agent。

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

<a id="what-the-model-reads"></a>

## 模型读到的内容

来自 RoboDojo prompt pack（`prompts/robodojo/`），启用所有 skill 和特性：

```text
  spawn(fn, name=None, claims=None)  run fn() beside your program as an entry on the channels
                                    it claims (CHANNELS: e.g. ["move"], ["look", "hands"]);
                                    returns its handle: .wait(timeout=None) returns what fn
                                    returned (raises its failure; None if cancelled or still
                                    running at the timeout), .cancel() stops it, .send(message)
                                    gives it a message, .state(), .status (running, done,
                                    failed, cancelled)
  receive(): what the entries sent and how they ended. More on entries below.
  entries(running=True)              the handles of the entries started so far
  claim(*channels), unclaim(*channels)   inside an entry: take channels for it, or let them go
  channels()                         who has each channel now
```
