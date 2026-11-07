---
title: "机器人与 worker"
---

## `harness.core.remote`

与独立 Python 环境中的 worker 通信的 JSON/HTTP 传输。

这是框架自身的协议，不是 RoboDojo/XPolicyLab 原生协议。集成方必须在 worker 侧实现 Environment。

### `RemoteEnvironment`

```python
class RemoteEnvironment
    __init__(endpoint: str, timeout: float=120.0, *, approval_key=None, host_controls=(), relay=None)
```

通过 HTTP（POST /rpc）访问 worker，若设置 $HARNESS_WORKER_TOKEN，则将其作为 bearer token。worker 错误以 RuntimeError 抛出，不重试任何请求：超时的运动可能已经执行。

#### `tools`

```python
def tools() -> list[dict]
```

worker 的工具 schema。检查协议版本并读取名称，也用于确认 worker 可响应。

#### `reset`

```python
def reset(task: str, seed: int) -> Observation
```

以 `seed` 启动 `task` 的 episode，并返回首个观测。

#### `execute`

```python
def execute(action: Action, episode_id: str, step: int) -> Transition
```

在观测（`episode_id`、`step`）上执行 `action`；worker 拒绝过期的二元组。返回到下一观测的状态转移。

#### `call`

```python
def call(name: str, **arguments)
```

调用环境特有的 worker 方法。

#### `managed_call`

```python
def managed_call(name, *, approval_key, **arguments)
```

带宿主签名发送 worker 控制调用。

#### `sensitive_approval`

```python
def sensitive_approval(op, *, approval_key, **arguments)
```

通过签名协议查看、撤销或重试一个待审批请求，也可查询已有回执。

#### `close`

```python
def close() -> None
```

无操作：worker 归启动它的进程所有。

## `harness.core.worker`

串行 worker 将所有模拟器操作保持在服务线程上。

worker 是一个本体的进程：它在本体的安全层（runtime/shield.py CommandShield）之后提供worker 协议（WORKER_METHODS），安全层在每条命令驱动任何东西之前对它作出判断。session 骨架（runtime/episode.py EpisodeCore）对它别无他求。

### `BenchWorker`

```python
class BenchWorker
```

benchmark 的 worker 共用的部分（一个 mixin）：把调用分派给它的 `_call_<name>` 方法；tick 之外的输入一律拒绝（tick 由它的 shield 检查）；state 调用；observe 所取视图的检查；一次 tick 的外层结构；以及每个 episode 只能领取一次的令牌（OutcomeToken）之后的评测结果。

worker 设置 `methods`（它的调用）、LABEL（消息里它的名字）、INPUT（"input"，机器人为 "motion"）和 VIEWS（它有的视图）；持有 `_cursor`（EpisodeCursor）；定义 `_state()`、`_ended()` 和 `_evaluate()`（评测结果，只问一次）。它的 reset 调用 `new_outcome()`。

#### `tools`

```python
def tools()
```

#### `execute`

```python
def execute(action, episode_id, step)
```

#### `call`

```python
def call(name, arguments)
```

#### `views`

```python
def views(cameras) -> list
```

observe 被要求的视图（不指定时为 VIEWS 的全部）；这个 worker 没有的视图报 ValueError。

#### `tick_begins`

```python
def tick_begins(episode_id, step) -> None
```

一次 tick 的检查：episode 和步数是当前的，episode 仍在进行。

#### `tick_refused`

```python
def tick_refused(decision) -> dict
```

shield 拦下了这条命令：什么都没有执行。

#### `acted`

```python
def acted(act, on_error=None)
```

执行一次 `act()`，然后进入下一步。它抛出异常时，输入可能已经到达环境：episode 不能从没人观察到的状态继续，因此游标失效（这一步不会再发送），并由 `on_error(error)` 记录。

#### `tick_executed`

```python
def tick_executed(decision, episode_id, cameras=None, **result) -> dict
```

一次已执行 tick 的结果；`cameras` 要求时附上执行之后的视图。

#### `new_outcome`

```python
def new_outcome() -> None
```

新的 episode：一个新的令牌（core/codec.py OutcomeToken），还没有询问评测结果。

### `WorkerAPI`

```python
class WorkerAPI
    __init__(environment, contract=None, *, approval_key=None, approval_from_stdin=False, host_pipe=False)
```

单个环境的 worker RPC 方法：describe、reset、execute 和 call。跟踪当前观测，确保不执行过期或重放动作；若指定观测 contract，则用它过滤结果。

相关标识为 `call`、`managed_control_calls`。

#### `dispatch`

```python
def dispatch(method: str, arguments: dict, *, approval_proof='')
```

支持托管审批的 worker 在 managed_control_calls 中声明需要签名的 call 名称。一次 RPC 的结果：`describe`（协议版本、名称、工具、方法）、`reset`、`execute`（仅当前 episode 和 step）或 `call`（环境自身的方法）。未知方法会报错。

### `create_server`

```python
def create_server(environment, host='127.0.0.1', port=8765, token=None, contract=None, *, approval_key=None, approval_from_stdin=False)
```

使用 WorkerAPI 响应 POST /rpc 的 HTTP 服务器（尚未开始服务），每次一个请求。指定 `token` 时（非回环地址必需），请求须携带 bearer token；错误以状态 400 和 {"error": ...} 返回。

### `parser`

```python
def parser()
```

worker 的参数（python -m harness.core.worker、harness serve）。

### `main`

```python
def main(argv=None) -> int
```

python -m harness.core.worker --factory module:callable：在独立的 Python 进程中提供一个 worker（机器人、模拟器、这台电脑）；suite 和电脑的工作区启动的就是它，eval 包的 harness serve 也是。

## `harness.embodiments`

本体：描述机器人或计算机本身，与运行如何连接它无关。

embodiments/&lt;name&gt;/embodiment.toml 保存策略无需询问模拟器即可获知的本体信息。`kind`（KINDS，默认 robot）决定驱动它的 session（runtime/episode.py）、可运行的 skill（skill 的 `embodiments`）及必需的键。

机器人文件包含关节组和限制、手臂安装位置、指尖偏移、夹爪宽度和读数、控制频率、规划器限制、相机标定（头部相机固定于世界坐标系，腕部相机固定于 link6）、XPolicyLab 协议动作键及安全层默认值。模拟器 worker 在 profile 中实时报告相同信息；XPolicyLab 连接器和受契约限制的 worker 从此处读取。计算机（desktop）文件包含屏幕和输入步频率；游戏文件包含窗口屏幕、可按的键及静止步频率。

KINDS 包含核心所知的各类型间全部差异；新增类型需要此处一个条目、session 类、skill（skill 的 `embodiments`）、提示词和 benchmark（benches/&lt;name&gt;/bench.toml 的 `kind`）。

### `Kind`

```python
class Kind
```

本体类型。worker 在 profile 中报告类型（`kind`，默认 robot）。

### `contracts`

```python
def contracts() -> dict
```

{name: {"kind", "filter", "summary"}}: the observation contracts the packages register in
their contracts.toml, one table per contract:

    [xpolicylab]
    kind = "robot"
    filter = "harness_robodojo.contract:XPolicyLabContract"
    summary = "what RoboDojo's official client hands a policy"

A filter is a class taking the embodiment, whose apply(method, arguments, result) gives
what a worker method returned as the contract shows it (core/worker.py).

### `contract_filter`

```python
def contract_filter(name: str, embodiment: dict)
```

The filter a worker of `embodiment` is served with under the contract `name`: None for
native (everything is reported); a registered contract's filter otherwise.

### `embodiment_path`

```python
def embodiment_path(name) -> Path
```

按名称（`embodiments/<name>/embodiment.toml`）或路径获取本体文件；未知名称会报错。

### `embodiment_kind`

```python
def embodiment_kind(data: dict) -> str
```

本体树或 worker profile 的类型（默认 robot）；未知类型会报错。

### `load_embodiment`

```python
def load_embodiment(name) -> dict
```

本体的配置树（名称或路径，见 embodiment_path）；须包含对应类型（KINDS）的键：机器人需要 name、control_hz、groups、arm_bases 和 cameras。

### `profile`

```python
def profile(embodiment: dict) -> dict
```

机器人本体对应的 worker profile（模拟器 worker 实时报告的内容），用于无模拟器的连接。
