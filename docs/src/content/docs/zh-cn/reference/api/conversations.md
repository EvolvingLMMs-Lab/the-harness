---
title: "对话"
---

## `harness.runtime.chat`

高层使用的多轮文本补全。

Chat Completions 通过带 `base_url` 的 `openai_chat` 支持 OpenRouter 和自托管的 OpenAI 兼容服务器（vLLM、SGLang）。消息使用 harness 内容片段（`input_text`、`input_image`）。

### `add_usage`

```python
def add_usage(total: dict, usage: dict) -> None
```

把 `usage`（一次调用的或一个合计）按 USAGE 的键逐项加到 `total` 上。

### `ChatReply`

```python
class ChatReply
```

一次补全：文本、用量（输入和输出 token、供应商报告时的美元费用、finish_reason）、供应商响应 ID，以及含重试在内的请求耗时秒数。

### `effort_fields`

```python
def effort_fields(backend: str, base_url, model: str, effort, max_tokens: int) -> dict
```

把 `effort`（none、low、medium、high）写成这家服务商读取的请求字段；未设置时返回 {}。OpenAI、Gemini、Ollama 及其他 OpenAI 兼容服务器使用 OpenAI 的 reasoning_effort。

### `chat_url`

解析指定模型提供方的 Chat Completions 地址。

```python
def chat_url(provider, base_url)
```

### `chat_part`

把一段内容转换为 Chat Completions 接口接受的格式。

```python
def chat_part(part)
```

### `ChatModel`

```python
class ChatModel
    __init__(config: dict, transport=None)
```

单个模型角色（MODEL_KEYS）的 Chat Completions 客户端：OpenRouter 或 OpenAI 兼容服务器。openrouter 后端从环境变量读取密钥；`transport` 可替代 HTTP 调用（用于测试）。

#### `payload`

```python
def payload(system: str, messages: list[dict]) -> dict
```

请求体：将 `system` 和 harness 消息转换为聊天消息，加入输出上限和 extra_body 字段；OpenRouter 还包含用量统计和推理设置。

#### `streams_text`

```python
def streams_text() -> bool
```

complete() 能否在回复流式到达时交出其中的文字（on_text）。

#### `complete`

```python
def complete(system: str, messages: list[dict], on_text=None, *, cancellation=None) -> ChatReply
```

在 `system` 下对 `messages` 进行一次补全，先通过 broker 启动按需服务。失败请求会重试（`retries` 次，或直到经过 `retry_seconds`），HTTP 429 之外的客户端错误除外；最后一次失败以 RuntimeError 抛出。流式输出时（streams_text），`on_text(kind,
text)` 在回复（"text"）和推理（"reasoning"）的每一段到达时收到它。

### `urllib_transport`

```python
def urllib_transport(url, headers, payload, timeout, *, cancellation=None)
```

POST 一次 chat completion 请求，返回提供方的响应。

### `sse_transport`

```python
def sse_transport(url, headers, payload, timeout, on_text=None, *, cancellation=None)
```

POST 流式聊天补全，将各数据块组装为非流式响应格式。`timeout` 限制每次读取，因此 keep-alive 注释会重置它。
`on_text(kind, text)` 在每一段到达时收到它（ChatModel.complete）。

### `scripted_models`

```python
def scripted_models(script) -> dict
```

脚本化 episode 的模型：`script` 为回复列表，或 scripts/replay_script.py 写出的 {"replies": [...], "verifier": [...]}；无验证器记录时，验证器回答 YES。

### `still_running`

```python
def still_running(messages: list[dict]) -> bool
```

最后一个内容片段是否说明某个程序仍在运行、且没有别的东西到达模型。

### `ScriptedChat`

```python
class ScriptedChat
    __init__(replies: list[str], waits: bool=True)
```

按顺序回放固定回复，用于不调用模型的流程检查。程序仍在运行时回来的一轮以 &lt;wait&gt; 回答，不占用回复（`waits` 计数），所以脚本就是每个程序的结果之后的回复；`waits=False` 时每次调用都取下一条回复。

#### `complete`

```python
def complete(system: str, messages: list[dict]) -> ChatReply
```

下一条脚本回复（耗尽后返回 `<finish>` 块），用量为零。

## `harness.runtime.conversation`

将一个 episode 表示为用户、主模型和 episode 之间的对话。

以对象形式表示运行时唯一的循环，即模型的循环，参考 OpenHands 的 Conversation：trace（events.jsonl）是仅追加的类型化记录日志（EVENTS），可重建模型可见的历史（rebuild_messages）；对话有执行状态（STATUSES），客户端（GUI、终端）订阅其 trace。

其他线程可发送消息（下次模型调用时送达）、暂停（运行中的程序在下一执行步停止）、回复确认请求或关闭对话。

桌面 worker 的物理输入策略（harness/physical.py）可能在某一步使用用户真实的鼠标和键盘之前询问用户：运行中的程序发出请求（runtime/desktop.py），对话像等待程序的批准一样等待用户批准（WAITING_FOR_CONFIRMATION，一条 physical_request 记录），由 confirm() 回复，并说明要记住什么（这一步、这个应用、这个 session、始终）。它的 session 和 agent（`identity`，由 sessions 注册表设置，host/sessions.py）以及本次运行的策略（runtime.physical）在重置后传给 worker。

agent 可以启动子 agent（runtime/agents.py）：各自是独立的对话，有自己的 `parent` 和 `depth`，花费随时沿树计入上层预算（charge_up）。子 agent 的每一轮是启动它的模型的一个单元：它的回答（或这一轮的上限）结束这一轮，结果交回父 agent；之后它带着自己的历史空闲着，send_agent() 让它继续。对话进入某个 session 之后（`identity`），它的 trace 里每条记录都注明归属：{"who": {session, agent, parent}}。

评测 episode 以无用户交互的对话运行：Conversation.run 从重置运行至结束，行为不变。

一轮是模型从开始它的东西（指令、消息、单元的结束、事件）到它的回答之间的工作：不含块的纯文本回复就是回答（&lt;finish&gt; 和程序里的 finish() 与它相同）。上限（模型调用次数和时间属于这一轮，费用属于对话）、错误、取消和环境结束也会结束一轮。每一轮以一条 turn_result 记录结束，之后对话处于 IDLE，保留消息、kernel 的命名空间、规则、facts 和环境；回答之后仍在运行的单元继续运行，到达模型的东西开始下一轮。只有用户或 host 关闭对话（或 kernel 死掉）才结束对话；没有用户的调用方（评测）在第一轮之后结束它。

一次运行从一个模型开始。模型写的每个程序都作为 kernel 里的一个独立单元运行（runtime/execution/kernel.py）：模型的这一轮立刻回来，程序在很短的宽限时间内结束时带着它的结果，否则带着它的句柄，结果在该单元结束时到达模型。自己到达模型的东西（消息、事件、单元的结束、宿主的告知）都是同一个队列里带优先级的通知（runtime/decision/notices.py）：`now` 把在它之前做出的回复放到一边（model_preempted），`next` 随下一次调用送达，`later` 在模型下一次等待之后送达。每次调用由同一处告知模型（_deliver）：它上一条回复的结果、通知、现在的情况。模型可以回复 &lt;wait&gt;（可带秒数）：等待期间不发起调用，它启动的某个单元结束、有消息或事件到达、或时间到时等待结束。回答结束这一轮；这次运行和它的单元继续。每次模型调用是一次思考（Thought）：启动它的是 TRIGGERS 的一行，它的回复能做什么是 OUTPUTS 的一行。

runtime.thinking 限定主模型的每次调用（THINKING）：推理强度和回复的 token 至多为某一级别的上限；在 "none" 和 "low" 级别还会告诉模型简短思考。

### `confirmation_policy`

```python
def confirmation_policy(given: str | None=None) -> str
```

App、终端对话和 RPC 共用同一套程序确认策略。前端可以用 `given` 为当前对话指定策略，否则使用设置里的 `approvals.ask`。

### `rebuild_messages`

```python
def rebuild_messages(records) -> list[dict]
```

按 trace 重建截至最后回复的主模型历史：每次请求新增的内容（从上次回复之后起，替换它所替换的最后几条消息），减去随后丢弃的格式错误轮次，再加最后回复（程序运行时发出的调用如果回复没有用上，则不算）。图像裁剪和历史窗口按请求应用（runtime/messages.py 的 prune_images、window），因此同样裁剪后的重建列表与对话本身一致。

### `Closed`

```python
class Closed(Exception)
```

用户在等待期间关闭了对话。

### `think`

```python
def think(chat, system: str, messages: list, *, role='reflection', trigger='reflect', trace=None)
```

离线提案与会话内反思使用相同的调度入口。

### `Conversation`

```python
class Conversation
    __init__(config, seed: int, directory, *, chat=None, verifier=None, environment=None, interactive: bool=False, confirmation: str='never', instruction: str | None=None, agents=None, parent=None, memory=None)
```

以 `seed` 运行 `config.task` 的一个 episode，trace 和文件位于 `directory`。`chat`、`verifier` 和 `environment` 替代配置的模型和 worker。`interactive` 表示用户参与（见模块 docstring）；`confirmation` 为 CONFIRMATION_POLICIES 之一；`instruction` 用用户指令替换任务指令（评测结果仍按原任务评分）。`agents`（runtime/agents.py）负责启动它的程序要求的子 agent；`parent`：启动它的那个 agent。

#### `send_message`

```python
def send_message(text: str, sender: str='user', files=()) -> None
```

用户消息（`sender` 为 "parent" 时，是启动它的 agent 发来的）：立即记录，下次模型调用时发送。`files`：用户附上的文件路径（此时读取：messages.attachment_parts）。

#### `pause`

```python
def pause() -> None
```

暂停：模型的每个单元在下一执行步或等待处停下，它的任何东西都不再行动；在 resume() 或收到消息之前不再调用模型。

#### `resume`

```python
def resume() -> None
```

暂停后继续。

#### `set_model`

```python
def set_model(model: str | None=None, reasoning_effort: str | None=None) -> dict
```

从下一次调用起换主模型（同一服务商的另一个 id）或思考强度（EFFORTS，"" 为服务商默认；仍受 runtime.thinking 限制）：写一条 model_changed 记录。返回现在的模型和强度。

#### `waiting_for`

```python
def waiting_for() -> str | None
```

对话正在等待用户批准的内容（当它是物理输入时）。

#### `approval_id`

```python
def approval_id()
```

正在等待的请求 ID。

#### `confirm`

```python
def confirm(accept: bool, reason: str='', remember: str | None=None, *, request_id=None) -> None
```

批准（accept）或拒绝等待确认的程序，或等待物理输入的步骤；对后者，remember 决定答复保留多久：仅这一步（once，默认）、这个应用或这个 session（app、session），或作为设置中的一条规则（always）。

#### `close`

```python
def close() -> None
```

结束 episode：等待时立即结束，否则在下一步边界结束。

#### `request_worker_approval`

```python
def request_worker_approval(due)
```

保留原动作并向 worker 验证待审批请求。

#### `finish_worker_approval`

```python
def finish_worker_approval(pending, *, episode_id, step)
```

在原动作的投递边界领取一次决定和回执。

#### `cancel_worker_approval`

```python
def cancel_worker_approval(pending=None, *, reason)
```

取消尚未领取的 worker 请求。

#### `start`

```python
def start() -> threading.Thread
```

在独立线程上运行 episode 并返回该线程。

#### `heard`

```python
def heard(text: str, source: str | None=None) -> None
```

这个模型的某个单元向它提问（子 agent 的问题）：这是给模型的事件，会唤醒它。（单元的结束以其结果的形式到达它。）

#### `queue_library_revision`

```python
def queue_library_revision(item, proof)
```

将带有可信宿主证明的精确修订排入下一个安全启用边界。

#### `charge_up`

```python
def charge_up() -> None
```

把这个子 agent 自上次以来的花费计入父 agent（并继续向上）。

#### `seconds_left`

```python
def seconds_left() -> float
```

episode 还剩的墙钟时间（max_wall_seconds）：计入它运行的时间，不计等待用户的时间；开始前是全部预算。

#### `run`

```python
def run() -> dict
```

运行 episode 至结束并返回摘要（状态、评测结果、模型调用、token、费用、耗时），与 trace 和清单一起写入目录。错误以 status "error" 结束 episode，而非抛出异常。

## `harness.core.spans`

Span：episode 各部分的工作时间，用于运行时间线。

span 表示某组件为某项工作花费的一段实际时间：主模型回复、程序运行、skill 的有界执行、一次服务调用。以 `span_start` 记录开始，以相同 ID 的 `span_end` 记录结束。某个条目运行的代码的 span 写明这个条目（`entry`，runtime/entries.py）；条目本身以 `entry_start` 和 `entry_end` 记录开始和结束。宿主部分（对话）自行写入 trace；kernel 进程通过其安装的 sink 写入（runtime/kernel.py），宿主收到后追加到 trace。无 sink 时不产生开销，也不记录。

span 的 `lane` 表示工作的是哪一类部分（PARTS）。时间轴并不是每类一条泳道：core/lanes.py 从记录里读出泳道，每个条目一条（另有模型、verifier、环境），随它们开始和结束出现、消失。

### `note`

```python
def note(kind: str, **detail) -> None
```

程序运行期间立即向宿主发送 `kind` 类型的通知（用户可见的计划）；无 sink 时无操作。

### `step`

```python
def step(skill: str, number: int, what: str, ok: bool, seconds: float | None=None, reason: str | None=None, of: int | None=None, library=None) -> None
```

报告 skill 计划里的一步结束了（第 `number` 步，共 `of` 步，做了什么、做成没有、用了几秒、为什么没做成）：一条 skill_step 记录，是模型在程序运行时下次再看的新情况（runtime/conversation.py）；验证测试的记录带有 `testing` 字段。无 sink 时无操作。

### `in_test`

```python
def in_test()
```

当前是否在验证测试中。

### `testing`

```python
def testing(active=True)
```

将验证测试的结果与正式运行统计分开。

### `record`

```python
def record(op: str, **detail) -> None
```

立即向宿主发送一条 span 以外的记录 `op`（条目的开始或结束，带 `detail`）；无 sink 时无操作。

### `set_entry`

```python
def set_entry(entry)
```

此线程此后记录的 span 写明 `entry`（条目 id；None：不写）；返回之前写明的那个。

### `current_entry`

```python
def current_entry()
```

返回当前线程记录的条目标识。

### `connected`

```python
def connected() -> bool
```

通知能否送达宿主（kernel 已安装 sink）。

### `set_sink`

```python
def set_sink(sink) -> None
```

从此将每条 span 记录发送到 `sink(record)`（None 表示不记录）。

### `current`

```python
def current()
```

当前线程所在 span 的 id（不在任何 span 中时为 None）。

### `under`

```python
def under(parent)
```

块内记录的 span 以 `parent`（来自 current() 的 span id，或 None）为父 span：用于另一个线程为某个 span 运行的代码（tick 运行 skill 的各步）。

### `span`

```python
def span(lane: str, name: str, **detail)
```

将块内代码记录为部分 `lane`（PARTS）上名为 `name`、带 `detail` 的 span。通过 yield 提供一个字典，写入其中的条目（如事件类型、状态）会保存在 span 的结束记录中。如果异常从代码块中抛出，会先记入 span，再继续向外抛出。
