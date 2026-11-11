---
title: "事件与反应层"
---

## `harness.runtime.events`

事件：一次运行中的信号，汇总在一份目录里。

执行的事件（Event）结束每一次有界执行，并交给回应它的规则（on()）；没人回应的事件结束运行它的单元，并到达模型（Escalation）。trace 记录（EVENTS）是运行写进 trace 的内容（core/trace.py），时间线、overlay、回放和导出的视频都由它绘制。一族记录是同一个 kind，用 action 区分（library），由 record_kind() 读取。

相关标识为 `action`。

### `Event`

```python
class Event
```

执行结束的原因：事件类型（上述内置类型或 guard 自定义动作）、来源（skill、guard、"shield"、"environment"）、详情及发生时的机器人步数。

#### `to_dict`

```python
def to_dict() -> dict
```

将事件转为普通字典。

### `input_refusal`

```python
def input_refusal(receipt, step)
```

从输入回执提取通道冲突或安全检查拒绝事件。动作执行成功时返回空值。

### `ExecutionTrace`

```python
class ExecutionTrace
```

一次有界执行做了什么，以及为何结束。

#### `ok`

```python
def ok() -> bool
```

执行是否正常结束（COMPLETED 或 PREDICATE_SATISFIED）。

#### `ticks`

```python
def ticks() -> int
```

执行消耗的机器人步数。

#### `to_dict`

```python
def to_dict() -> dict
```

将 trace 转为普通字典，包含 `ok`。

### `Escalation`

```python
class Escalation(Exception)
    __init__(trace: ExecutionTrace)
```

没有 handler 解决的事件，会结束当前程序。

### `ProgramFinished`

```python
class ProgramFinished(Exception)
    __init__(summary: str='')
```

程序调用了 finish()：自身检查表明任务完成。episode 结束，不再调用模型。

### `EpisodeEnded`

```python
class EpisodeEnded(Exception)
    __init__(trace: ExecutionTrace)
```

程序运行期间，环境终止或截断了 episode。

### `record_kind`

```python
def record_kind(record: dict) -> tuple[str, str | None]
```

trace 记录的 kind，以及一族记录（library）的 action。

### `step_of`

```python
def step_of(start: dict, end: dict, call: str | None=None) -> dict
```

把一次执行的 span_start 和 span_end（泳道 "skill"）当作它所属 skill 的一步，形状同 skill_step 记录（core/spans.py step），读者因此把两者同样看待。

## `harness.runtime.reactive`

规则：在某个条件上开始、发出事件或结束某个东西的规则，以及事件的 handler。

### `ReactiveFault`

```python
class ReactiveFault(Exception)
    __init__(source: str, reason: str)
```

反应代码违反规则（禁止操作、异常、超时、信号缺失或不是有限数值）：source 指定规则，reason 描述原因。

### `call_reactive`

```python
def call_reactive(source: str, function: Callable, *args, budget_seconds: float) -> Any
```

在审计限制和时间预算下运行一个反应函数。

### `read_signal`

```python
def read_signal(observation: dict, signal_name: str | Callable, source: str, budget_seconds: float) -> float
```

被监测信号的值：observation 中的点分键（列表项用索引），或接收观测、按反应代码方式运行的可调用对象；否则抛出 ReactiveFault，来源为 source。

### `Rule`

```python
class Rule
```

一条规则：它何时开始的条件（`begin(view, state)`），可选的何时结束的条件（`end`），它的优先级，以及它启动的程序（`program`），该程序作为具有这个优先级的单元运行；还可以有开始后至少持续的时间（`min_seconds`）和再次开始前要等的时间（`again_seconds`）。没有程序时，它发出一个事件（`action`：事件名，或条件返回的 Event），结束一个单元（条件返回 {"stop_entry": id}），或在设置了 `stops` 时结束其作用范围内的执行。它读取的 view 的各部分（`reads`：点分键；None：任何部分）变化时判断它，或每隔 `every` 秒判断一次。`on`：它改为该类事件的 handler。`owner`：它随之存在的单元（模型，或设置它的那条规则的程序）。

#### `does`

```python
def does() -> str
```

#### `describe`

```python
def describe() -> dict
```

它引发的事件报告的关于它的信息。

### `ReactiveLayer`

```python
class ReactiveLayer
    __init__(budget_seconds: float, actions=(STOP, HOLD))
```

一个 kernel session 的规则（见 Rule）。`min_period`：按时间判断的规则可以要求的最短周期；`period`：没写周期时得到的周期（环境给出的上限和默认值）；`owner()`：新规则随之存在的单元。

#### `guards`

```python
def guards() -> dict[str, Rule]
```

#### `rule`

```python
def rule(begin: Callable, program: Callable | None=None, *, name: str | None=None, priority=0, ends: Callable | None=None, min_seconds=0.0, again_seconds=0.0, while_holds=False, reads=None, every=None, raises: str | None=None, stops=False, action: str | None=None, on: str | None=None, kind: str='rule', **detail) -> Rule
```

登记一条规则（见 Rule）；同名规则在原位被替换。

#### `when`

```python
def when(predicate: Callable, action: str, name: str | None=None, stops: bool=True) -> Rule
```

没有程序的规则：predicate 成立时，结束其作用范围内的执行（`stops`），或发出事件 `action` 并让它们继续。

#### `watch`

```python
def watch(signal_name, low=None, high=None, event=None, name=None, stops=True) -> Rule
```

对 view 中一个超出 [low, high] 的数值做同样的事。

#### `on`

```python
def on(event, handler) -> Rule
```

用 handler(trace) 处理一个事件；返回 False 时把它继续交出去。

#### `remove`

```python
def remove(name) -> None
```

#### `clear_owner`

```python
def clear_owner(owner: str) -> None
```

单元 `owner` 已结束：随它存在的规则移除。

#### `clear`

```python
def clear(names=None, does=(STOPS, RAISES, STARTS)) -> None
```

按名称清除匹配的规则，或清除所有匹配的规则。

#### `evaluate`

```python
def evaluate(observation: dict, scope=None) -> Rule | None
```

第一条会结束 `scope`（其规则看着这次执行的各单元）内的执行、且条件此刻成立的规则：在执行的每一步判断。

#### `next_due`

```python
def next_due(now) -> float | None
```

距离下一条按时间判断的规则到期还有多少秒（已到期为 0）；没有这样的规则时为 None。

#### `reads_changes`

```python
def reads_changes() -> bool
```

是否有规则在状态变化时被判断。

#### `due`

```python
def due(view_of, now, stamp) -> list
```

此刻要判断的规则，优先级高的在前：周期已到的按时间判断的规则、所读内容已变化的规则（`stamp` 标识此刻的状态和事实；`view_of()` 给出 view），以及程序已结束的规则。

#### `advance`

```python
def advance(rule, view, now, start)
```

在 `view` 上判断 `rule`：它没有程序而开始时，返回条件的返回值（由调用方发出事件或结束单元），否则返回 None。它的程序用 `start(rule)` 启动；最短时间过后，它的结束条件（或设置了 while_holds 时开始条件不再成立）结束该程序。

#### `answer`

```python
def answer(lineage, trace, acting, faulted=None) -> bool
```

把事件先交给最近的 handler。

#### `answers`

```python
def answers(owner) -> dict
```

单元 `owner` 的 handler：{event kind: rule}。

### `period`

```python
def period(budget_seconds)
```

为同一控制周期内运行的回调设置共享时间预算。

### `fault_event`

```python
def fault_event(fault, step, **detail)
```

把反应回调的故障转换为 REACTIVE_FAULT 事件。

### `emit`

```python
def emit(tree, owner, skill, event, *, notice=False)
```

把事件交给登记的单元。通知会记入程序结果，但无人处理时也不会中止执行。

### `judge`

```python
def judge(session, tree)
```

在 session 此刻的 view 上判断它到期的规则（ReactiveLayer.due）：开始的规则把它的程序作为具有其优先级的单元启动，或发出它的事件，或结束条件指明的单元；结束条件成立的规则结束它的程序。
