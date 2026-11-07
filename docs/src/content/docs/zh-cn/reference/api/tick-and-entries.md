---
title: "Tick 与条目"
---

## `harness.runtime.tick`

常驻 tick：按控制频率驱动 kernel session 本体的循环。

每个周期，tick 先取观测，让正在运行的执行做出决定（它们的 guard、until、范围和时间上限），把它们和反应层做的事合并成一条命令，再发给 worker，由 worker 的安全层放行或拒绝。tick 从不等待慢的工作（模型、VLM、感知模型）；它只管时钟、条目的调度和通道的合并，一个周期内做出反应的东西属于反应层（runtime/reactive.py）。

这里的条目是程序条目：一次有界执行（EpisodeCore._bounded），它是一个生成器，每步 yield 一条命令，接收 worker 的回复，最后返回它的 trace。每一步都以它所属的树上条目的身份运行（runtime/entries.py）；如果这个条目被取消，或者根程序有要交给模型的事件，执行在下一步就结束。在 tick 上运行的代码（控制器）原地把它的条目跑完。

没有通道时，本体是一份资源：各执行轮流运行，先启动的先跑。有通道时（游戏的键、按钮、指针和滚轮，embodiment.toml [channels]），每个执行同时前进，各用它的命令所用的通道，tick 把它们和各条目按住的东西（key_down）合并成每个周期一条命令（session 的 _merge）。伸手去拿别的条目已占用、正在驱动或按住的通道的条目收到 CHANNEL_CONFLICT；占用持续到放开或条目结束，条目按住的东西在它结束时松开。没人有的通道处于默认状态。tick 用它自己的一份安全层检查合并后的命令：被拒绝的部分算作放进它的那个执行或按住者被拒绝，其余部分照常发出。

时钟由 worker profile 的 clock 决定："steps"（默认；worker 的 tick 就是时钟，没有东西运行时不发送任何东西）或 "wall"（世界按真实时间运行：tick 自己维持控制频率，每个周期刷新状态，没有东西运行时发送保持命令，guard 也照样盯着：runtime/reactive.py watch）。

反应延迟（runtime.reaction_delay_ms，向上取整到整数个周期）让决定在队列中等到期，就像手跟随眼睛；到期之前发出保持命令。有通道时，命令做完的执行依据最新的回复决定下一条命令。

### `delay_ticks`

```python
def delay_ticks(reaction_delay_ms, hz) -> int
```

一个决定在发出前等待的控制周期数：`reaction_delay_ms` 按 `hz` 的周期向上取整。

### `Tick`

```python
class Tick
    __init__(session)
```

一个 kernel session 的 tick（参见模块 docstring）：`run(steps)` 在其上运行一个程序条目，`start()` 开始保持 wall 时钟的本体，`stop()` 结束它。`ticks` 统计已发送的步数。

#### `start`

```python
def start()
```

从现在开始运行：没有条目运行时，wall 时钟的本体每个周期都会被保持（steps 时钟只为条目运行 tick）。

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

在 tick 上运行执行，返回执行记录或抛出执行错误。

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

条目：kernel session 里同时运行的东西，组成一棵树；以及每次执行都以之运行的闭环（ClosedLoop）。

agent 的程序是根条目 e0。程序可以用 spawn(fn, name, claims=...)（skills/entries）启动更多条目：每个条目在自己的线程上运行 fn，是启动它的那个条目的子条目；子 agent（delegate()，runtime/agents.py）是类型为 "agent" 的条目。spawn 返回的句柄可以等这个条目（wait）、停掉它及其子条目（cancel）、给它发消息（send），它的代码用 receive() 读取。条目的每条记录都写明它自己和它的父条目（对话再加上 session 和 agent）。

事件沿树向上交：一次执行的事件先交给运行它的条目的回应（on()，runtime/reactive.py），再交给它父条目的回应，直到根；guard 看着设置它的条目以及它下面各条目的执行。失败的条目（抛出异常、有没人回应的事件）是一个 ENTRY_FAILED 事件，交给正在等它的人，否则从它的父条目往上交。没人回应的事件到达模型：正在运行的程序在 harness 下一次到达的地方（一步、wait、receive、spawn）或结束时以 Escalation 收到它。一个条目的子条目随它结束；根的子条目跨程序继续运行。

没有通道时，不同条目的执行在 tick 上轮流运行，claims 只被记录下来。有通道时它们同时运行，各用各的通道：条目在 spawn 时或之后（claim）占用通道，直到放开或结束；伸手去拿别的条目已有通道的条目收到 CHANNEL_CONFLICT（在 spawn 时它就以此失败）。上层条目的占用会把通道留给它下面的条目。

### `user_message`

```python
def user_message(skill: str, parameters: dict | None=None) -> ExecutionTrace
```

一条给模型的消息让什么停下了，它的 trace（runtime/control.py）。

### `current_entry`

```python
def current_entry()
```

返回当前线程上的执行条目。主程序返回 None。

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

session 树上的一个条目（见模块说明）：它的 `id`、`name`、`kind`（"root"，spawn 出来的代码为 "program"，子 agent 为 "agent"）、启动它的条目（`parent`）、它的 `claims`、它的 `status`（running、done、failed、cancelled），结束后还有它的函数的返回值（`result`）或失败原因（`error`）。

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

#### `send`

```python
def send(message)
```

给这个条目发一条消息，它的代码用 receive() 读取（子 agent：回答它的问题，或者再交给它一些事）。

#### `cancel`

```python
def cancel(timeout=5.0)
```

停掉这个条目以及它启动的条目（先停它们）：它正在运行的执行在下一步结束，它所在的 wait 或 receive 抛出异常，不进入 harness 的代码在片刻之后就地中断。返回它的状态。

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

一个 kernel session 的条目（见模块说明）。

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

在 `entry`（默认：调用者的条目）的代码里抛出它必须为之停下的东西：它被取消，或者对根来说，一个要交给模型的事件。

#### `interruption`

```python
def interruption(entry, take=True)
```

`entry` 的代码现在必须为之停下的东西（见 check），或 None；`take` 为 False 时根的事件继续留着。根的代码还会为一条给模型的消息停下（runtime/control.py），带 USER_MESSAGE 事件。

#### `spawn`

```python
def spawn(fn, name=None, claims=None) -> Entry
```

把 fn() 作为调用者条目下的一个新条目运行（见模块说明）。

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

调用者启动的子 agent 的条目（delegate）。

#### `agent_ended`

```python
def agent_ended(agent, report, *, cancelled=False) -> None
```

一个子 agent 结束了（对话告诉 kernel，runtime/kernel.py）：它的条目也随之结束，除非它是正常完成的，否则算失败。

#### `deliver`

```python
def deliver(entry, trace) -> bool
```

把 `trace` 的事件交给 `entry` 及其上面各条目的 handler；没人处理的交给模型。返回是否有 handler 解决了它。

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

#### `begin_program`

```python
def begin_program() -> None
```

一个程序开始：没有程序运行时到达模型的事件让它立即结束（它是在不知道这个事件的情况下写的）。

#### `end_program`

```python
def end_program() -> None
```

一个程序结束：它运行期间到达模型、而它没有遇到的事件就是它的结束。

#### `drain`

```python
def drain() -> list[dict]
```

每个程序之后模型会知道的条目：正在运行的，以及上次 drain 之后结束的（根除外）。

#### `close`

```python
def close(timeout=2.0) -> None
```

session 关闭：每个条目都被取消。

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
