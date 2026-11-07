---
title: "事件与反应层"
---

## `harness.runtime.events`

事件：一次运行中的信号，汇总在一份目录里。

执行的事件（Event）结束每一次有界执行，并沿条目树向上交给回应它的规则（on()）；没人回应的事件以 Escalation 升级给模型。trace 记录（EVENTS）是运行写进 trace 的内容（core/trace.py），时间线、overlay、回放和导出的视频都由它绘制。一族记录是同一个 kind，用 action 区分（library），由 record_kind() 读取。

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

反应层：在一个控制周期之内、不经模型做出反应的规则。

规则（Rule）是关于 session 所见及其自身状态的纯函数 decide(view, state)。它的输出是：什么都没有、让它看着的执行停下、一个事件，或在通道上的一个动作；回应是针对结束了一次执行的事件的规则。guard（when、watch）、反射（reflex）和事件的 handler（on）都是规则。规则在审计钩子下运行，钩子禁止文件、网络和进程操作，并受每个 tick 的时间预算限制；违规就是 REACTIVE_FAULT。

tick 在一个周期的每个阶段询问这一层：执行决定它的这一步之前，询问会叫停的规则（evaluate）；在挂钟上询问 guard（watch）；条目做出决定之后，询问做动作的规则（act）。一个动作是这个周期它需要的通道的输入：


在它占用的通道上，这个周期略去条目的输入；不带 "take" 时，它的键和按钮被加上去（辅助）。优先级高的先；每条规则都能看到这个周期到目前为止要发出的东西（view["out"]）。它动作期间，trace 里有一个 kind 为 "reflex" 的条目代表它。

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

被监测信号的值：observation 中的点分键（列表项用索引，如 left_ee.2），或接收观测、按反应代码方式运行的可调用对象；否则抛出 ReactiveFault，来源为 source。

### `Rule`

```python
class Rule
```

一条规则：decide(view, state) -&gt; 它的输出，种类由 does 说明："stop"（truthy：action 让它看着的执行停下）、"event"（truthy：它所属条目的一个事件 action，其余一切照常继续）、"act"（None 或一个动作）、"answer"（对 kind 为 on 的事件调用 decide(trace, state)：不为 False 即解决事件；它在事件所在处运行，可以做动作，因此钩子和预算都不适用）。priority 给一个周期内的规则排序（相同时按设置顺序）；owner 是设置它的条目，会叫停的规则看着这个条目及其下面各条目的执行；除做动作的规则外，每条规则随它的条目一起结束。

#### `describe`

```python
def describe() -> dict
```

它引发的事件（或 reflex_state）报告的关于它的信息。

### `ReactiveLayer`

```python
class ReactiveLayer
    __init__(budget_seconds: float, actions=(STOP, HOLD))
```

session 的规则（见 Rule），每条限制在 budget_seconds 内运行；owner() 给出此刻设置的规则属于哪个条目。taken：上个周期动作占用的通道，skill 读取它来区分反射做的事和自己做的事。

#### `guards`

```python
def guards() -> dict[str, Rule]
```

#### `reflexes`

```python
def reflexes() -> dict[str, Rule]
```

#### `rule`

```python
def rule(decide: Callable, does: str, name: str | None=None, priority=0, action: str | None=None, on: str | None=None, kind: str='rule', **detail) -> Rule
```

设置并返回一条规则；同名规则在原位被替换。默认名称为 <kind>_<n>。

#### `when`

```python
def when(predicate: Callable, action: str, name: str | None=None, stops: bool=True) -> Rule
```

在 predicate(observation) 成立时触发的 guard：action（stop、hold、open_gripper 或事件名）让它看着的东西停下，stops 为 False 时只引发它的事件。

#### `watch`

```python
def watch(signal_name, low=None, high=None, event=None, name=None, stops=True) -> Rule
```

在信号（read_signal）低于 low 或高于 high 时触发的 guard；默认事件为 <SIGNAL>_OUT_OF_RANGE。

#### `reflex`

```python
def reflex(name, control, priority='survival') -> Rule
```

一条做动作的规则：每个周期 `control(view)` -&gt; 一个动作或 None。

#### `on`

```python
def on(event, handler) -> Rule
```

调用它的条目对 event 类事件的回应：handler(trace) 为 True 或 None 时解决事件，为 False 时让它继续向上（同一类事件后设置的替换先前的）。

#### `remove`

```python
def remove(name) -> None
```

#### `clear_owner`

```python
def clear_owner(owner: str) -> None
```

条目 `owner` 已结束：它的规则移除，但它的动作规则保留。

#### `clear`

```python
def clear(names=None, does=(STOPS, RAISES)) -> None
```

移除指定规则（忽略未知名称），或移除所有做 does 中某一项的规则（默认：guard）。

#### `evaluate`

```python
def evaluate(observation: dict, scope=None) -> Rule | None
```

第一条会叫停且触发的规则，按优先级；给了 scope（条目 id）时，只看这些条目的规则和不属于任何条目的规则。

#### `firing`

```python
def firing(observation: dict, stopping=True, *, outputs=False)
```

触发的每个 guard；stopping 为 False 时只看那些只盯着的 guard。

#### `decide`

```python
def decide(view, session)
```

这个周期的动作：([(rule, part)], {channel: rule name} taken, [faults])；channels_of(part) 给出一个动作的通道。出错的规则会被移除。

#### `answer`

```python
def answer(lineage, trace, acting, faulted=None) -> bool
```

把 trace 的事件交给 lineage 中各条目（id，最近的在前）的回应，每个都在 acting(id) 内运行：第一个不为 False 的回应解决它。

#### `answers`

```python
def answers(owner) -> dict
```

条目 `owner` 的回应：{event kind: rule}。

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

把事件交给登记条目。通知会记入程序结果，但无人处理时也不会中止执行。

### `apply`

```python
def apply(session, tree, *, busy=False, goal=None, channels=())
```

处理观察阶段的规则结果，或在合并输入时收集反射动作。
