---
title: "Episode 运行时"
---

## `harness.runtime.messages`

模型的消息：对话（runtime/conversation.py）就本体以及它运行的每个程序告诉模型的内容。每种本体类型的文本（EMBODIMENT_TEXT），消息里的状态和相机图像，程序的反馈（状态、输出、事件、skill 的回合报告、状态和步数），另一个单元的结束，以及一次请求保留的历史（prune_images、window）。

### `image_parts`

```python
def image_parts(images: dict, cameras) -> list[dict]
```

`images` 中属于 `cameras` 的图像，每张前面有一行写着相机名称。

### `attachment_parts`

```python
def attachment_parts(paths, limit: int=100000) -> list[dict]
```

用户附在消息里的文件，作为内容片段，每个前面有一行写着它的名字：图片原样给出，文件夹给出其中的名字，其他文件给出文本（最多 `limit` 个字符）。

### `state_text`

```python
def state_text(state: dict, embodiment: str='robot', steps: bool=True) -> str
```

展示给模型的状态；没有 `steps` 时（worker 不公开其步数预算：profile 的 steps_shown 为 false）不显示步数。

### `cell_feedback`

```python
def cell_feedback(result: dict, number: int, hz: float | None=None, embodiment: str='robot', steps: bool=True) -> str
```

模型运行的程序 `number` 反馈给它的内容：状态、输出和错误、结束它的事件、执行、skill 的回合报告、状态和步数。它写明是哪个程序，因为程序并排运行，一个程序的结果可能在下一个程序的代码之后才到达模型。

### `unit_feedback`

```python
def unit_feedback(result: dict) -> str
```

一个已结束、且不是模型程序的单元（程序 spawn 的代码、子 agent）告诉模型的内容：它如何结束、打印了什么、返回了什么。

### `unit_text`

```python
def unit_text(identifier: str, unit: dict, printed: bool = True) -> str
```

模型得知的一个正在运行的单元（{"name", "kind", "started"}：runtime/task/run.py）；`printed` 为真时，在 host 能于单元运行期间得知其输出的地方，还说明它上一次打印是多久以前（它的 "printed"：时间，还没打印过则为 None）。

### `steps_text`

```python
def steps_text(state: dict, hz: float | None) -> str
```

已用的环境步数，以及在报告了 episode 上限时剩余的步数（Z2 每轮都显示两者）：每个运动 tick 都计入上限。

### `prune_images`

```python
def prune_images(messages: list[dict], keep: int) -> None
```

只在最后 `keep` 条用户消息中保留图像。

### `window`

```python
def window(messages: list[dict], turns: int | None) -> list[dict]
```

第一条消息（指令和初始画面）加上最后 `turns` 轮 assistant/user 交换。程序状态保存在 kernel 中，因此较早的轮次可以从提示词中移除而不丢失变量。

## `harness.runtime.kernel`

在独立进程中持久运行的 Python kernel，用于执行模型编写的程序。

宿主通过 stdin 发送程序，并从私有文件描述符读取 JSON 消息，因此程序打印的内容无法破坏协议。kernel 命名空间由初始化函数 `module:function` 提供，它接收 JSON 选项并返回具有以下成员的 session 对象：

    namespace: dict       names visible to programs
    drain() -&gt; dict       what the unit that calls it gathered (attachments, events, state)
    close() -&gt; None

每个程序都作为一个单元运行（runtime/execution/entries.py）：在同一个命名空间里有自己的线程，有自己的输出、事件、图片和结果，与已在运行的单元并排。对程序的回复立刻返回：程序在宿主给的宽限时间内结束时是它的结果，否则是 {"status": "running", "unit": id}；比回复活得久的单元的结果，以及其他每个单元（spawn 的代码、子 agent）的结束，是一条 `unit_end` 消息。宿主可以取消一个单元、暂停全部单元并恢复。

托管 kernel（一个隔离进程，其程序只能提议操作）使用同一套协议：由同一个循环为它服务，它的提议与各单元的消息并行传送。宿主对它的话一概不轻信：runtime/execution/managed.py 逐条准入提议，并保存每个单元做过的事。

kernel 导入过的 Harness 包模块会以 `modules` 通知发给宿主：就绪时先发 bootstrap 导入的，之后每个单元结束时和关闭时发新导入的。trace 记录这次运行加载了哪些代码。

### `kernel_python`

```python
def kernel_python(runtime: dict) -> str
```

episode 的 kernel 所用的解释器。

### `repo_modules`

```python
def repo_modules() -> list[str]
```

这个进程已导入的源码包（REPO_PACKAGES）模块，排好序。

### `PlainSession`

```python
class PlainSession
    __init__(options=None)
```

提供空命名空间的引导函数，用于测试和调试。

#### `drain`

```python
def drain()
```

没有可返回的内容：普通 session 不收集附件或事件。

#### `close`

```python
def close()
```

无资源需要释放。

### `KernelDied`

```python
class KernelDied(RuntimeError)
```

kernel 进程启动失败、未运行或未及时响应（此时会被终止）。

### `sandbox_available`

```python
def sandbox_available() -> bool
```

本机是否支持运行 kernel 沙箱（util-linux unshare，使用用户、挂载和 PID 命名空间）。

### `Kernel`

```python
class Kernel
    __init__(bootstrap: str, options: dict, *, python: str=sys.executable, cwd: str | None=None, env: dict | None=None, log_path: Path | None=None, start_timeout: float=300.0, on_span=None, managed=None, managed_launcher=None)
```

宿主侧句柄。每个 kernel 的生命周期对应一个 episode。

托管工作区提供对其提议的准入（`managed`：runtime/execution/managed.py Admission）和用于创建上下文管理器的启动函数。启动函数接收准入对象的选项，返回供 kernel 进程使用的命令和文件描述符。

#### `start`

```python
def start(code: str, grace: float, timeout: float | None=None, *, name: str | None=None, announce=None) -> dict
```

把 `code` 作为名为 `name` 的单元启动，最多 `grace` 秒后返回 kernel 的回复：单元在此之前结束时是它的结果（状态 ok、error、escalated、episode_ended 或 finished，截断后的 stdout、error、seconds，以及该单元收集的内容：attachments、events、state、usage），否则是 {"status": "running", "unit"}：它的结果之后作为 `unit_end` 消息交给 on_span。两者都带 `cell`，即这个 kernel 给该程序的编号，程序发出之前会先用 `announce(cell)` 告知。`timeout` 秒后 kernel 取消该单元。kernel 未运行、已退出或没有回复时抛出 KernelDied。

#### `run`

```python
def run(code: str, timeout: float) -> dict
```

把 `code` 作为单元运行并等待它的结果（见 start），最多 `timeout` 秒，之后 kernel 取消它。

#### `load_library`

```python
def load_library(phase, entries=(), *, timeout=120)
```

宿主用同一入口准备、提交或丢弃一批固定的库修订。提交成功后返回当前启用的版本。

#### `pause`

```python
def pause() -> None
```

暂停模型的各单元：每个单元在下一执行步或等待处停下，在 resume() 之前什么都不行动（runtime/execution/control.py）；kernel 已不在运行时什么都不做。托管 kernel 的提议在此期间被宿主拒绝。

#### `resume`

```python
def resume() -> None
```

暂停结束。

#### `cancel`

```python
def cancel(unit: str | None=None) -> None
```

取消单元 `unit`（None：模型的每个单元）；它的结束以其结果或一条 `unit_end` 消息的形式到来。

#### `answer`

```python
def answer(identifier, value) -> None
```

回复运行中程序以通知形式发出的请求（runtime/control.py）；kernel 不再运行时无操作。

#### `agent_ended`

```python
def agent_ended(agent, report, *, cancelled=False) -> None
```

告诉 kernel 某个子 agent 已结束，并附上它的报告（它的单元随之结束，runtime/execution/entries.py）；kernel 已不在运行时什么都不做。

#### `kill`

```python
def kill()
```

若 kernel 进程仍在运行则终止它。

#### `close`

```python
def close()
```

请求 kernel 关闭 session 并退出（30 s 内未退出则强制终止），随后关闭管道和日志。

### `format_error`

```python
def format_error(error: BaseException) -> str
```

仅保留程序栈帧及抛出异常的栈帧的 traceback。

### `restore_api`

```python
def restore_api(namespace: dict, api: dict) -> list[str]
```

恢复程序重新绑定或删除的 session API 名称，并按排序返回这些名称（否则模型自定义的 `def pick(m): ...` 会破坏后续所有 skill 调用）。

### `main`

```python
def main(argv=None)
```

kernel 进程：使用 JSON `--options` 从 `--bootstrap` 创建 session，然后执行 stdin 读取的单元，直到收到关闭请求或输入结束。

## `harness.runtime.episode`

episode 核心：每个本体的 kernel session 所采用的 session 骨架。

kernel session 连接 worker，保存它报告的状态、skill 的模型客户端（VLM、pointer、验证器、分割器）和 episode 事件，以及模型的各单元（runtime/execution/entries.py），并在它的 tick 上运行这些单元的有界执行（runtime/tick.py）：每一步询问反应层里会叫停的规则、检查终止条件，再向 worker 发送一条命令，worker 的安全层放行或拒绝它。执行以事件结束；非正常事件交给回应它的规则（on()），没有谁回应的事件结束该单元并到达模型。单元为模型收集的东西（图片、事件、画面）是它自己的：它的 box。

一个本体（机器人、计算机、游戏）是一个在安全层（runtime/shield.py CommandShield）之后提供 worker 协议（core/worker.py WORKER_METHODS）的 worker，加上一个继承 EpisodeCore 的 session，后者说明每步命令是什么、如何送到 worker（_tick），保持现状的命令（_base_command），反应代码观测什么（_reactive_view），命令何时超出执行范围（_outside），trace 采样什么，以及自身处理的 guard 动作。有通道时，它还要说明命令如何占用通道、tick 如何合并各部分（_plan、_merge、_still、_admit、_channels_of、_channel_of_reason）。kernel session 类由本体 session 与该类型所有 skill 的 mixin 组成（session_class()）；命名空间包含本次运行启用 skill 的导出名称（runtime/skills.py）。

引导：harness.runtime.kernel --bootstrap harness.runtime.episode:create_session；选项：{"endpoint", "episode_id", "embodiment", "skills", "reactive_budget_ms", "reaction_delay_ms", "observer", "default_max_seconds", "max_wait_seconds", "vlm", "pointer", "verifier", "segmenter", "vision", "mcp", "library", "agent_skills"}，以及本体自己的选项（机器人的："policies"、"world_models"、"strategy_first"、"policy_progress_seconds"，harness_robot/session.py）。

### `EpisodeCore`

```python
class EpisodeCore
    __init__(options, *, environment=None)
```

每个本体和 skill 所依赖的 session 骨架：worker 连接及 profile、状态、模型客户端、反应层（规则、事实、对事件的回应），以及各单元和 tick 上的有界执行。本体的 session 继承此类（参见模块 docstring）；其 `namespace` 包含已启用 skill 的导出名称。

#### `show`

```python
def show(what, caption='')
```

把一个观测（它的每张图）或一个 RGB 数组（例如裁剪出的一块）附到你收到的下一条消息上。

#### `drain`

```python
def drain()
```

调用它的单元产生的内容，用于它的结果（kernel 在程序结束时调用它，runtime/execution/kernel.py）：它的附件、事件和画面（随后清空）、状态、模型用量，以及已启用 skill 的回合报告。

#### `close`

```python
def close()
```

结束模型的各单元，停止 tick，并关闭与 worker 的连接。

#### `set_reflex`

```python
def set_reflex(name, when, do=None, *, ends=None, priority=0, reads=None, every=None, min_seconds=0.0, again_seconds=0.0, while_holds=False, raises=None)
```

名为 `name` 的反射：when(view) 变为成立时，do() 作为具有 `priority` 的单元启动，它会从优先级较低的单元手里接管 embodiment；ends(view) 变为成立时（或设置了 while_holds 而 begins(view) 不再成立时），该程序被结束，但不早于 `min_seconds`；程序结束 `again_seconds` 之后它才可以再次开始。它的程序设置的规则只在该程序运行期间存在。没有程序时，它发出事件 `raises`，或 begins 返回的东西：一个 Event，或用 {"stop_entry": unit.id} 结束那个单元。它读取的 view 的各部分变化时判断它（`reads`：点分键，如 "facts.door"；不写：任何变化），或每隔 `every` 秒判断一次（True：按环境的频率）。view 以 view["facts"] 提供这次运行的事实；(view, state) 形式的条件还会得到一个它自己的字典。返回它的名称。

#### `run_controller`

```python
def run_controller(fn, until=None, max_seconds=None)
```

每步运行 `fn(view)`，直到它返回空值或满足停止条件。

### `Facts`

```python
class Facts
    __init__(changed=None)
```

这次运行所知道的、共享的内容：命名的值，程序读写它们，规则的条件读取它们（view 的 "facts"）。被结束后又重新启动的程序从它们继续。值是普通数据（JSON 能表示的内容）；每次变化是一条 `fact` 记录，读取事实的规则随之被判断。

#### `set`

```python
def set(name, value)
```

把事实 `name` 设为 `value`；返回该值。

#### `get`

```python
def get(name, default=None)
```

事实 `name`，或 `default`。

#### `drop`

```python
def drop(name)
```

忘掉事实 `name`；返回它原先是否存在。

#### `view`

```python
def view() -> dict
```

此刻的事实，作为一个独立的字典。

### `Execution`

```python
class Execution(ClosedLoop)
```

一次有界执行，作为一个闭环：确认这次运行允许它行动（_refuses），在 tick 上做它的各步，检查它是否正常结束。只试一次（可能已经执行过的动作从不被悄悄重试）；每个异常都结束程序；它的 span 就是它的记录。trace 在 Result 的 detail["trace"] 里（没有通过确认时没有 trace，只有原因和提示）。

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

#### `report`

```python
def report(number, what, ok, seconds, reason)
```

### `image_role`

```python
def image_role(config: dict | None, role: str)
```

回答图像问题的模型角色（vlm、pointer、verifier）：其配置指定的类（[class] "module:Class"，某个包的：config/agent.py image_roles）的实例；没有配置或类时为 None。

### `service_client`

```python
def service_client(config: dict)
```

episode 的程序使用的某个服务的客户端（分割器、视觉服务）：服务清单指定的类（[client] class，"module:Class"），传入它的 url、超时和按需启动设置。

### `session_class`

```python
def session_class(embodiment: str='robot', knowledge: str | None=None)
```

将本体类型的 session 与该类型所有 skill 的 mixin 组合（本次运行启用的 skill 仅决定命名空间；一个 skill 的方法可调用另一个 skill）。knowledge 为 "learned"（agent 自己学的游戏）时，不含为游戏手写的 skill，它们的模块也从不导入。

### `create_session`

```python
def create_session(options)
```

kernel 引导：创建 options["embodiment"] 的 session（默认 robot）。

## `harness.runtime.input`

需要用户先批准的 worker 步骤：worker 在用户真实的鼠标和键盘上执行步骤的 session（电脑的，或本机上游戏的）可能遇到物理输入策略，该策略会把某一步留待用户批准。worker 会带着请求拒绝这一步；session 通过主机把请求交给用户（一条 physical_request 记录；对话在每个前端询问并把答复送回，runtime/control.py），把答复交给 worker，并在用户允许后再次发送这一步。每一步如何送达、发送了什么，作为 input 记录交给主机，由 trace 保存。

在这一切之前，敏感步骤（core/approval.py：它的目标涉及凭据、付款、发送、删除或无法撤销的事）无论策略如何都会在这里等用户：同样的请求，带着它的 sensitive 类型，答复只对这一步有效。

### `PhysicalInput`

```python
class PhysicalInput
```

worker 在用户真实鼠标和键盘上执行步骤的 session：敏感步骤和物理输入策略要求用户批准的步骤会交给用户（ask_physical）；策略拦下的步骤在用户允许后再发送一次。session 的 _send(command, cameras) 向 worker 发送一步。

#### `ask_physical`

```python
def ask_physical(request)
```

通过宿主把请求交给用户，并把用户的答复交给 worker（敏感步骤除外：它的答复只对那一步有效）：{"accept", "remember", "reason"}；无人答复时（没有可询问的宿主；程序已暂停）返回 None。

### `input_sent`

```python
def input_sent(command) -> dict
```

一步发出的内容，用于它的 `input` 通知：命令除类型外的字段（游戏状态输入按住的键和按钮、指针移动），输入的文字只记长度。

## `harness.runtime.shield`

每条命令生效前执行的固定、非学习式检查。

安全层运行在环境 worker 中，与执行模型代码的进程隔离，程序无法修改它，学到的任何东西也到不了它：它是本体的一部分。各本体的安全层具有相同接口，即核心的接口（CommandShield）：根据实测状态判断命令，原样放行或附带原因拒绝；不缩短、裁剪或改写命令，否则程序无法得知自身命令有错。tick 的 `shield` 字段为其 ShieldResult。下面依次是机器人、计算机和游戏的安全层，各占一节：它们随各自的本体而定。

下方 Shield 是机器人的安全层。它接收绝对关节位置命令；worker 提供正向运动学时，也检查对应末端位置。它只拦截错误命令。拒绝情形包括：

- 格式错误的命令（长度错误、值不是有限数）；
- 关节超出限制或末端超出工作空间边界，且越界程度
  大于机器人当前状态（接触可能将实测关节或手略微推到界外；保持当前位置或移回界内并非错误）；
- 跳变：相对于上一条通过的命令和实测状态，手臂关节均超过 max_joint_jump_rad，或末端均超过
  max_cartesian_jump_m。真实运动一个控制 tick 的位移远小于此；跳变通常来自另一分支的 IK 解、错误坐标系中的目标或发散控制器。平滑命令序列不会因实际手臂滞后而被拒绝；从当前手臂位置发出的命令（保持、下一 skill 的首个路点、后退）也不会因上一条命令的位置被拒绝。

速度和加速度不由安全层负责：skill 自行安排运动时序，实体机器人控制器执行自身的速率限制。

DesktopShield 面向计算机。它检查一次输入步（DESKTOP_COMMANDS），拒绝未知命令、字段或按键、屏幕外坐标、键盘无法输入的文本，以及超出范围的滚动、等待或拖动。发往某个窗口的一步（带 `window` 字段）坐标在该窗口的画面里，由 worker 检查；元素动作（act）指明元素编号和它的一个动作。多个 agent 共用一台计算机时，它还会拒绝进入其他 agent 所拥有窗口的步骤（owner()：coordination.py 中全机范围的窗口归属），并为该 agent 认领无主的窗口。

末尾的 GameShield 面向游戏。它检查一次通用输入（GAME_COMMANDS：GameScientist 动作协议，屏幕像素坐标），按该协议拒绝未知命令、字段、按键或按钮、屏幕外坐标、越界的持续时间、等待、相对移动或滚动，以及过多或重复的按键。本体还可以封锁游戏规则禁止的按键（它的 `blocked` 表：按键及对应规则，例如速通时 Minecraft 的聊天键和暂停键）。声明了通道的游戏（它的 [channels]：哪些键、按钮、指针用法和滚轮同一时间归谁）还接受 state 输入，即 kernel 的 tick 每个周期从各条目按住的东西合并出的那一条（runtime/tick.py），按通道逐个检查。公平上限（[shield.fairness]，分档：FAIRNESS）限制人能做到的程度：每秒按鼠标键的次数、每个周期的视角转动、同时按下的键数。输入到文本框的文字（text 输入，或 state 在负责打字的通道上的 `text`）只有在游戏声明了 [shield.text] 时才放行：检查它的字符、长度，以及当前读到的界面是否在它列出的界面之中（Minecraft：配方书的搜索框，在那里字母属于文本框，而不是按键，例如被屏蔽的 T），并且它必须单独输入：同一次输入里不能按下或松开任何键。

### `ShieldResult`

```python
class ShieldResult
```

一条命令的判定："pass" 时原样保留命令；"rejected" 时不返回命令，并给出原因（失败检查及比较值）。命令由本体定义，例如机器人的关节向量。

#### `to_dict`

```python
def to_dict() -> dict
```

将结果转为普通字典，作为 tick 的 `shield` 字段。

### `CommandShield`

```python
class CommandShield(Protocol)
```

任意本体的 worker 安全层：根据实测状态（`current`）及 worker 已知的其他信息（`context`，如机器人正向运动学）固定检查每条命令，原样放行或附带原因拒绝。

#### `reset`

```python
def reset() -> None
```

清除 episode 中此前命令建立的状态。

#### `check`

```python
def check(command, current, **context) -> ShieldResult
```

对 `command` 的判定。

### `finite`

```python
def finite(*values) -> bool
```

每个值是否都是有限数（bool 不算数）。

### `in_screen`

```python
def in_screen(x, y, screen=None) -> dict | None
```

(x, y) 不是画面 `screen`（[width, height]）上的点的原因，或 None。点是两个有限数，0 &lt;= x &lt; width 且 0 &lt;= y &lt; height（像素 x 覆盖 [x, x + 1)）；不给 `screen` 时只检查数值（窗口的画面，由 worker 掌握）。

### `bounded`

```python
def bounded(name, value, low, high, *, integer=False) -> dict | None
```

`value` 超出范围的原因，或 None：所有安全层共用的一条范围规则，一个有限数（字段计数时为 int：`integer`），且 low &lt;= value &lt;= high。

### `reject`

```python
def reject(reason: dict) -> ShieldResult
```

对 `reason` 的拒绝（没有命令通过）。

## `harness.runtime.control`

除启动程序外，宿主对 kernel 各单元的请求。

kernel 进程在独立线程读取宿主请求，因此单元运行期间也能收到请求。暂停（用户暂停对话）让模型的每个单元停下：有界执行在下一步以 USER_PAUSED 结束（runtime/execution/session.py），等待则抛出该事件（runtime/execution/entries.py），在宿主恢复之前什么都不行动。给模型的消息在这里不停止任何东西：它是给模型的事件，而模型的这一轮属于它自己（runtime/task/run.py）。回复（answer）是宿主对单元以通知形式发来的请求的答复（用户对物理输入请求的答复，runtime/safety/input.py）：单元等待该答复，或等到暂停。子 agent 结束时，宿主会告知，它的单元随之结束（runtime/execution/entries.py）。

### `request_pause`

```python
def request_pause() -> None
```

让模型的各单元停下：每个单元在下一执行步或等待处停下。

### `resume`

```python
def resume() -> None
```

暂停结束：各单元可以再次行动。

### `pause_requested`

```python
def pause_requested() -> bool
```

模型的各单元是否处于暂停。

### `wake_waiters`

```python
def wake_waiters()
```

唤醒正在等待宿主回复的程序。

### `answer`

```python
def answer(identifier, value) -> None
```

宿主对请求 `identifier` 的答复。

### `wait_answer`

```python
def wait_answer(identifier, poll: float | None=None, stop=None, *, deadline: float | None=None, interruptible=True)
```

等待宿主回复、中断或单调时钟到达显式截止时间。

### `worker_call`

通过会话宿主转发 worker 调用。

```python
def worker_call(send, arguments, timeout)
```

### `think`

```python
def think(role, text='', *, images=(), system=None, entry=None, frame=None, stop=None, **detail)
```

代表 kernel 中的执行条目向会话宿主请求一次模型调用。

### `stopped`

```python
def stopped(skill: str='program')
```

单元的等待被用户的暂停打断时的类型化升级。

### `on_agent_ended`

```python
def on_agent_ended(listener, remove: bool=False) -> None
```

宿主告知某个子 agent 结束时调用 listener(agent, report)（`remove`：不再调用）。

### `agent_ended`

```python
def agent_ended(agent, report, *, cancelled=False) -> None
```

宿主告知子 agent `agent` 已结束，附上它的报告。
