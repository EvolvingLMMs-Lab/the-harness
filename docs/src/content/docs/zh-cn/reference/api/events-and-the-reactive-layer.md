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

反应层是一棵反射树（`runtime/reactive/tree.py`）；反应代码在限制和时间预算下被调用（`runtime/reactive/rules.py`）。

### `ReactiveFault`

```python
class ReactiveFault(Exception)
```

失败的反应代码，带来源和原因。

### `call_reactive`

```python
def call_reactive(source: str, function: Callable, *args, budget_seconds: float) -> Any
```

在审计限制和时间预算下运行一个反应函数。

### `period`

```python
def period(budget_seconds)
```

一个控制周期：其中的反应调用共用 `budget_seconds`。

### `Reflex`

```python
class Reflex
```

树的一个节点：名字 `name`；什么时候轮到它（`when`，看视图的条件）或它回应的事件（`event`）；它做什么：`do`（程序），或 `action`（要发出的事件，或环境里结束执行的动作），或都没有（组）；它挂在哪个节点下（`under`，None 为树顶）；它在所在位置的 `priority`；判断其条件的间隔 `every`（None：状态或事实变化时）；程序结束后再次开始前的 `again_seconds`。

### `Reflexes`

```python
class Reflexes
```

一个 kernel 会话的树。

#### `set`

```python
def set(name, when, do=None, *, under=None, priority=0, every=None, again_seconds=0.0) -> str
```

把节点 `name` 放进树里，取代同名节点。返回名字。

#### `drop`

```python
def drop(names=None) -> None
```

移除节点 `names`（一个名字或列表；None 为全部）及其下面的节点；它们启动的程序被结束。

#### `children`

```python
def children(name=None) -> list
```

`name` 下面的节点（None：树顶），靠前的在前。

#### `rank`

```python
def rank(node) -> float
```

节点的程序持有环境所用的优先级：比它所在那部分树的树顶节点的优先级高出不到 1 的一部分，在那里带程序的节点中越靠前高出越多。于是树的先后就是各单元优先级的先后，每个节点都在模型的程序（0）之上。

#### `listing`

```python
def listing(name=None) -> list
```

当前的树，靠前的在前：每个节点的名字、优先级、何时轮到、做什么、条件上次是否成立、程序是否在运行、启动过几次、上一次运行的结束报告，以及它下面的节点。

#### `evaluate`

```python
def evaluate(view) -> Reflex | None
```

第一个"结束执行"且此刻轮到的节点。

#### `answer`

```python
def answer(trace, start) -> bool
```

把事件交给第一个回应该事件种类且此刻轮到的节点：它的程序由 `start(node, program)` 启动，事件算作已回应。

#### `publish`

```python
def publish(staged) -> None
```

把一个库条目设置的节点（`stage()`）放进树里。

### `stage`

```python
def stage(layer, replacing)
```

加载库条目期间：它设置的节点收集在层的一份副本里，`publish()` 把它们放进树，取代 `replacing` 这些条目原先设置的节点。

### `fault_event`

```python
def fault_event(fault, step, **detail)
```

把反应代码的故障转换为 REACTIVE_FAULT 事件。

### `emit`

```python
def emit(tree, owner, skill, event, *, notice=False)
```

把事件交给登记的单元。通知会记入程序结果，但无人处理时也不会中止执行。

### `judge`

```python
def judge(session, tree)
```

在 session 此刻的 view 上判断它的树：轮到的节点把程序作为单元启动（优先级为它在树里的位置，完成条件是节点的条件不再成立），或发出它的事件；程序结束时情况还没过去或程序失败、且同一处后面没有节点接手时，发出带着程序报告的 REFLEX_FAILED。
