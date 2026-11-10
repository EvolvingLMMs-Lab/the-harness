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

### `made_ahead`

```python
def made_ahead(messages: list[dict]) -> bool
```

一个请求是否是程序运行时发出的调用（runtime/conversation.py AHEAD_RUNNING，或再看一次：THINK_RUNNING）：它的最后一条消息以程序正在运行的消息结尾。

### `ScriptedChat`

```python
class ScriptedChat
    __init__(replies: list[str], ahead: bool=False)
```

按顺序回放固定回复，用于不调用模型的流程检查。程序运行时发出的调用以 &lt;wait&gt; 回答，不占用回复（`waits` 计数），
所以脚本就是每个程序之后的回复，不管模型提前想了哪些程序；`ahead=True` 时这些调用也取下一条回复。

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

agent 可以启动子 agent（runtime/agents.py）：各自是独立的对话，有自己的 `parent` 和 `depth`，花费随时沿树计入上层预算（charge_up）。子 agent 的 &lt;finish&gt; 或预算用完就是它的结束，结果交回父 agent；它不带代码块的回复是问父 agent 的问题。对话进入某个 session 之后（`identity`），它的 trace 里每条记录都注明归属：{"who": {session, agent, parent}}。

评测 episode 以无用户交互的对话运行：Conversation.run 从重置运行至结束，行为不变。

交互模式（GUI）仅在用户参与处不同：不含块的回复是给用户的消息，&lt;finish&gt; 结束模型当前轮次而非 episode；两者都等待用户下一条消息。环境结束、预算耗尽或用户关闭时，episode 才结束。

每次模型调用都是一个单元，一次思考（Thought），在自己的线程上：启动它的是 TRIGGERS 的一行，它的回复能做什么是 OUTPUTS 的一行。两个程序之间，循环等待一次思考；程序运行时（runtime.think_while_acting，分级：off、on、on_events、periodic），思考在程序旁边回来：

- "ahead"：程序一开始，就有一次思考考虑它之后的事。回复写明它预期程序留下什么（&lt;assume&gt;condition&lt;/assume&gt;，由 kernel 在程序的变量和输出上检查，不调用模型）以及下一个块；&lt;wait&gt; 则带着结果再问一次。可能结束任务的程序没有这种思考（_reads_first）。
- "news"、"interval"（on_events、periodic）：长程序运行时再看一次：有新情况进来时（世界记忆里一种新的东西、guard 或反射的第一次触发、失败的条目、skill 的一步、以事件结束或运行过久的一次执行、子 agent 结束；合并处理），或 runtime.think_interval 秒内没有新情况时。
- "message"：程序运行时，一条给模型的消息（用户的或父 agent 的）立即成为一次思考；不边想边做时，程序自己的代码在下一步带着 USER_MESSAGE 停下。正在生成的回复被放到一边（model_preempted），带着这条消息再问一次，新请求在它之上追加内容。

ON_BACK 说明程序运行期间回来的回复做什么：暂不做事、在程序旁边运行（一个不动任何东西的块），或让程序在下一步停下、接着运行这条回复。AT_END 说明程序结束时它的去向：被使用、等待、作废或检查。程序运行时最多只有一次思考在进行，触发会合并，一条消息会作废回复尚未被使用的思考。summary["decisions"] 按触发统计调用，程序运行期间做出的回复再按其去向统计；再看一次计入调用预算。

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

暂停：运行中的程序在下一执行步停止；在 resume() 或收到消息之前不再调用模型。

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
def heard(text: str, *, escalation=False, agent_report=False) -> None
```

给模型下次再看的新情况（_look_while）：模型不再看时、或在两个程序之间（它会读程序的结果）什么都不做。

#### `invalidate_lookahead`

```python
def invalidate_lookahead() -> None
```

作废待采用的前瞻结果。

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
