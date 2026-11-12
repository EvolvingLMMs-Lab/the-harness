---
title: "Tick 与条目"
---

## `harness.runtime.tick`

每个控制周期观测、判断规则并发出一条 worker 命令。

只有执行或按时间判断的规则需要时 tick 才存在：除非有单元要求，否则没有任何东西按时间驱动。本体是一份资源时，各执行轮流进行，并收到自己命令的回执。有通道时，各执行同时前进，在本地准入前把它们的输入与各单元按住的东西合并。延迟的动作在发出前保留它的准入和归属。worker 的安全层判断每一条发出的命令。

### `driving`

```python
def driving(profile) -> tuple
```

环境说明它能怎样被驱动：（每秒最多接受多少条命令，None：答复多快就多快；它的一步持续多长时间，None：它的时间按墙钟计）。取自 profile 的 `max_hz` 和 `step_seconds`；仍然写着 `clock` 的 profile 按该模式原来的含义读取：steps（或未写）即每一步持续 1 / control_hz；wall 即每秒最多 control_hz 条命令；events 即两者都没有。

### `delay_ticks`

```python
def delay_ticks(reaction_delay_ms, hz) -> int
```

一个决定在发出前等待的控制周期数：`reaction_delay_ms` 按 `hz` 的周期向上取整。

### `Preempted`

```python
class Preempted(Exception)
    __init__(by=None, priority=0)
```

在一次执行的各步等待某一步回复的地方抛出：优先级为 `priority` 的单元 `by` 接管本体。

### `Tick`

```python
class Tick
    __init__(session)
```

一个 kernel session 的 tick（参见模块 docstring）：`run(steps)` 在其上运行一次执行，`judge()` 让规则被判断，`stop()` 结束它。`ticks` 统计已发送的步数。`bound`：环境每秒最多接受的命令数（此时它的各周期被定速）；`step_seconds`：它的一步持续的时间（driving()）。

#### `judge`

```python
def judge()
```

让规则被判断：设置了一条规则、规则读取的内容变了，或某条规则的程序结束了。没有要判断的规则时什么都不做（没有规则，就没有 tick）。

#### `stop`

```python
def stop(timeout=5.0)
```

停止 tick；仍在运行的程序条目以错误结束。

#### `on_thread`

```python
def on_thread() -> bool
```

调用者是否运行在 tick 上（控制器、guard）。

#### `run`

```python
def run(steps)
```

在 tick 上运行这次执行并返回它的 trace，或抛出它的错误。`steps`：它的生成器，或生成它的函数。没有通道时，本体按优先级持有：优先级最高的单元的执行前进（相同时先来的先做），并让优先级较低的单元的执行在当前位置结束：带着 PREEMPTED 和它已经做了的事，模型立即得知（_preempt）。接管本体的单元持有它直到自己结束：较低的单元在此期间启动的东西等待，之后再继续。写明 restart=True 的单元，它的执行在那之后被重新启动（它的 trace 记下 `restarts` 次数）。

#### `known`

```python
def known(names) -> list
```

把 `names`（一个名字或一个列表）作为本体的通道名返回（本体没有声明的名字抛出 ValueError）。

#### `conflicts`

```python
def conflicts(entry, names, *, claiming=False) -> dict
```

{通道: 占着它的条目的 id}：`names` 中 `entry` 现在不能用的通道，即别的条目正在驱动或按住它，或已经占用它（`entry` 上层条目的占用会把通道留给下面的条目）。

#### `claim`

```python
def claim(entry, names) -> dict
```

`entry` 占用通道 `names`，直到放开或结束：返回拿不到的那些 {通道: 占着它的条目 id}（这时一个也不占），否则返回 {}。

#### `release`

```python
def release(entry, names=None) -> None
```

`entry` 放开通道 `names`（None：它有的全部）：它的占用，以及它在这些通道上按住的键和按钮，下一个周期松开。

#### `let_go`

```python
def let_go(entries) -> None
```

`entries` 按住的键和按钮在下一个周期松开；它们的占用保留（守卫叫停了它们在做的事，runtime/episode.py）。

#### `board`

```python
def board() -> dict
```

现在每个通道在谁手里：{通道: {"entry", "how": claimed、driving 或 holding}}，没人有的为 None（处于默认状态）。

### `Refused`

```python
class Refused(Exception)
    __init__(reason: dict)
```

session 无法拆成各通道周期的命令（不属于任何通道的输入、不认识的命令）：它的 `reason`，与安全层的写法相同。

## `harness.runtime.entries`

一个 kernel session 的单元，以及有界的 ClosedLoop 执行。

一个 session 有一个模型（根条目）和它启动的单元：模型写的每个程序、程序 spawn 的每个函数、每个子 agent。单元有自己的输出、事件和图片（它的 box），以及自己的结果。单元启动的东西属于模型，而不属于该单元：它比启动它的程序活得久，随模型结束。事件经过各 handler；没人回应的事件到达模型，每个单元的结束也到达模型。

### `current_entry`

```python
def current_entry()
```

在当前线程上执行的条目；在所有单元之外时为 None。

### `Box`

```python
class Box
    __init__()
```

一个单元为模型收集的东西：它的输出（kernel 给它的写入器，其 recent(chars) 是最后打印的内容）、它展示和查看的图片，以及它各次执行的事件。

### `Cancelled`

```python
class Cancelled(BaseException)
```

条目被取消时在它的代码里抛出；它是 BaseException，这样程序里宽泛的 except 不会让它继续运行。

### `Entry`

```python
class Entry
    __init__(tree, identifier, name, kind, parent, claims=(), agent=None)
```

session 的一个单元（参见模块 docstring）：它的 `id`、`name`、`kind`（模型为 "root"，代码为 "program"，子 agent 为 "agent"）、它所属的模型（`parent`）、它的 `claims`、它的 `status`（running、done、failed、cancelled），以及结束后它的函数的返回值（`result`）或失败原因（`error`）。`cell` 是它作为模型程序的编号（spawn 的代码为 None），`rule` 是以它为程序的规则的名称（该程序设置的规则随它存在），`priority` 是它持有本体所用的优先级，`restart` 说明它被更高优先级单元结束的执行是否重新启动（runtime/tick.py；默认：以 PREEMPTED 结束），`box` 是它收集的东西，`outcome` 是它的代码如何结束（{"status": ok、error、escalated、episode_ended、finished 或 cancelled, ...}），`raised` 是出错时的异常。

#### `running`

```python
def running() -> bool
```

它是否还没有结束。

#### `lineage`

```python
def lineage() -> list
```

这个条目以及它上面的各个条目，直到根。

#### `state`

```python
def state() -> dict
```

程序和模型看到的这个条目。

#### `wait`

```python
def wait(timeout=None)
```

等到条目结束，最多等待 `timeout` 秒。传入 None 时等待完成事件。成功时返回函数结果，子 agent 返回其报告。条目失败时抛出带 ENTRY_FAILED 的 Escalation。条目已取消或在截止时仍在运行则返回 None，可用 `status` 区分。

#### `output`

```python
def output(chars=2000) -> str
```

这个单元到目前为止打印的内容：最后 `chars` 个字符（最多 30000），在它运行期间或结束之后都可以读。读取不会取走任何东西：它结束时，结果里仍有全部输出。什么都没打印的单元为 ""（子 agent 不在这里打印：它的报告就是它的结果）。

#### `send`

```python
def send(message)
```

给这个条目发一条消息，它的代码用 receive() 读取（子 agent：回答它的问题，或者再交给它一些事）。

#### `cancel`

```python
def cancel(timeout=5.0)
```

停止这个单元：它正在运行的执行在下一步结束，它所在的 wait 或 receive 抛出异常，没有回到 harness 的代码片刻之后在原地被中断。它启动的东西继续运行（它们属于模型）。返回它的状态。

#### `receive`

```python
def receive(timeout=None)
```

发给这个条目的最早一条消息，最多等 `timeout` 秒（None：一直等）；没等到则返回 None。

### `Tree`

```python
class Tree
    __init__(session)
```

一个 kernel session 的单元（参见模块 docstring）。每个单元结束时调用一次 `on_end(entry, handled)`（kernel 由此告诉模型，runtime/execution/kernel.py）；`new_output(entry)` 给新单元它的输出写入器。

#### `current`

```python
def current() -> Entry
```

调用代码所属的条目（不在其他条目里时是根）。

#### `acting`

```python
def acting(entry)
```

里面的代码属于 `entry`（tick 运行某个条目的执行的一步，某个条目的 handler 运行）。

#### `get`

```python
def get(identifier) -> Entry
```

条目 `identifier`（没有时是根）。

#### `under`

```python
def under(entry) -> list
```

`entry` 以及它下面的每个条目（它启动的、那些条目启动的……）。

#### `check`

```python
def check(entry=None) -> None
```

在 `entry`（默认：调用者）的代码里抛出它必须为之停下的东西：它被取消，或用户暂停。

#### `interruption`

```python
def interruption(entry, take=True)
```

`entry` 的代码现在必须为之停下的东西（见 check），或 None：用户暂停期间，模型的每个单元都停下（runtime/execution/control.py）。

#### `spawn`

```python
def spawn(fn, name=None, claims=None, *, cell=None, rule=None, priority=None, restart=False) -> Entry
```

把 fn() 作为模型的一个新单元运行（参见模块 docstring）；`cell`：它是模型的第几个程序；`rule`：它是那条规则的程序；`priority`：它自己的优先级（默认：启动它的单元的优先级）；`restart` 为 True：它被更高优先级单元结束的执行在那个单元结束后重新启动（默认：它在当前位置以 PREEMPTED 结束）。

#### `claim`

```python
def claim(names) -> bool
```

调用者的条目占用通道 `names`（见模块说明）：返回 True；若有通道属于别的条目且某个 handler 接下了 CHANNEL_CONFLICT 事件，返回 False，否则事件上报。

#### `release`

```python
def release(names=None) -> None
```

调用者的条目放开通道 `names`（None：它有的全部）：它的占用，以及它在这些通道上按住的键和按钮。

#### `channels`

```python
def channels() -> dict
```

现在每个通道在谁手里（{通道: {"entry", "how"}}，None：没人）；本体没有声明通道时为 {}。

#### `adopt_agent`

```python
def adopt_agent(agent, task) -> Entry
```

模型的代码启动的子 agent（delegate）的单元。

#### `agent_ended`

```python
def agent_ended(agent, report, *, cancelled=False) -> None
```

一个子 agent 结束了（对话告诉 kernel，runtime/kernel.py）：它的条目也随之结束，除非它是正常完成的，否则算失败。

#### `record_event`

```python
def record_event(trace, entry=None)
```

把执行事件加入程序结果，并在适用时记下条目 ID。

#### `raise_event`

```python
def raise_event(entry, trace, *, notice=False) -> None
```

把独立事件记入程序结果，并交给控制循环之外的 handler 处理。无人处理的通知会留在程序结果中，执行可以继续。

#### `handle`

```python
def handle(entry, trace) -> bool
```

把 `trace` 的事件交给 `entry` 对这类事件的回应，再交给它上面每个条目的（runtime/reactive.py answer）：第一个不返回 False 的回应解决它。

#### `running`

```python
def running() -> list
```

尚未结束的单元，先启动的在前（不含模型）。

#### `close`

```python
def close(timeout=2.0) -> None
```

session 关闭：模型结束，每个单元随之结束。

### `Result`

```python
class Result(dict)
```

闭环做了什么：{"ok", "reason", "tries", "seconds", "detail"}；ok 时为真。

### `Stop`

```python
class Stop(Exception)
```

在某一步中抛出：循环就此以这个原因结束（不再尝试）。

### `ClosedLoop`

```python
class ClosedLoop
    __init__(*args, **kwargs)
```

确认、执行、检查、重试、给出原因：一次有界执行，适用于任何动作场景；模型写的 skill 就是一个闭环，session 的 skill 的每次执行也是（runtime/episode.py Execution）。子类填写 confirm()（每次尝试之前：True，或不行动的原因）、do()、check()（之后：True，或为什么不行）和 recover(reason)（两次尝试之间）；一步可以抛出 Stop(reason)。用 skill 的参数调用（参数挂在 self 上），它最多运行 `tries` 次、最长 `max_seconds`，返回一个 Result；某一步中 `catches` 里的异常就是它的原因（episode 结束、finish() 和 PASS_ON 总是结束程序）。一步可以填写 `detail`。每次尝试的结束都会 report()：一条 skill_step 记录，也是程序运行期间给模型的消息。

#### `confirm`

```python
def confirm()
```


#### `do`

```python
def do()
```


#### `check`

```python
def check()
```


#### `recover`

```python
def recover(reason)
```


#### `report`

```python
def report(number: int, what: str, ok: bool, seconds: float, reason) -> None
```


#### `run`

```python
def run() -> Result
```
