---
title: "事件和 trace"
description: "一次运行留下的文件，以及其 trace 中的每一种记录。"
---

每次对话和每个 episode 都会留下一个目录：配置了什么（`manifest.json`），按顺序发生的每件事（`events.jsonl`，即
trace），以及如何结束（`summary.json`）。[`harness replay`](/docs/zh-cn/use/replay/)、app 和终端对话读取这些文件；
事后跟踪一次运行不需要其他任何东西。

## 一次运行的文件

### 一个 episode 或一次对话

| 文件 | 内容 |
|---|---|
| `manifest.json` | episode 运行时的配置、它的哈希、seed、worker 的 profile，以及代码的来源（[下文](#manifestjson)） |
| `events.jsonl` | trace：每行一条记录，发生时追加（[下文](#eventsjsonl)） |
| `summary.json` | episode 如何结束、花费了多少、调用情况如何（[下文](#summaryjson)）；它存在即表示 episode 已结束 |
| `kernel.log` | 运行 agent 程序的进程的输出 |
| `videos/` | `episode-<camera>.mp4`，每个相机一个，在 worker 录制视频时生成 |
| `screen.mkv`, `screen.json` | 对话所用的屏幕，在 `computer.record_screen` 打开时生成：视频、每一帧的墙钟时间，以及录制了什么（`video`、`display`、`area`、`fps`、`clock`、`start`、`stop`） |
| `agents/<id>/` | 子 agent 自己的目录，包含同样的文件 |
| `meta.json` | 只用于 app 的对话：app 显示的标题 |

agent 的程序写出的文件也放在同一目录中，和这些文件并列。

app 把它的对话保存在 `~/.harness/conversations/`（或 `$HARNESS_DATA` 下）。

### 多个 episode 的一次运行

`harness run` 把每个 episode 写到 `OUTPUT/<task>/seed-<n>/`，例如 `runs/dev/stack_bowls/seed-0/`。输出目录本身包含：

| 文件 | 内容 |
|---|---|
| `suite.json` | 请求的 episode、命令行，以及续跑时必须保持的设置（[JSON 输出](/docs/zh-cn/reference/cli-json/#suitejson)） |
| `outcome.json` | 最近一次 `harness run` 做了什么及其退出状态（[JSON 输出](/docs/zh-cn/reference/cli-json/#run-and-outcomejson)） |
| `.running` | 当前正在处理该 suite 的进程（[JSON 输出](/docs/zh-cn/reference/cli-json/#running)） |
| `suite.log` | 运行的日志行，每行带时间 |
| `workers/<name>.log` | 每个 worker 的输出 |
| `<task>/unstable.json` | `{unstable seed: the layout run in its place}`，让续跑时运行同样的替换 |
| `<task>/displaced.json` | `{requested seed: the layout run for it}`，用于这样的请求 layout：这个输出目录中较早的一次运行已经用它替换过一个不稳定的 layout |

`harness program` 针对一个已在运行的 worker 运行一个任务的各个 seed，它写出 `OUTPUT/<time>-<id>/seed-<n>/`，
并在旁边写出 `experiment.json`：配置、各 episode 的 summary、`success_rate`、`completed_cases` 和 `planned_cases`。

## manifest.json

| 键 | 内容 |
|---|---|
| `schema_version`, `kind` | `1`、`program` |
| `config` | `environment`、`version`（较早的 trace 中为 `agent_version`）、`main`（主模型的角色）、`runtime`、`verifier`、`system_prompt`、`task`、`seeds`、`max_model_calls`、`max_wall_seconds`、`task_description`、`max_cost_usd`、`agent_id`（agent 的 identity）、`agent_lock`、`placement`；不是机器人时还有 `embodiment` |
| `config_sha256` | `config` 的哈希 |
| `seed` | episode 的 seed |
| `embodiment_profile`, `embodiment_sha256` | reset 之后 worker 的 profile（不含任务特定的键）及其哈希 |
| `provenance` | Python 版本、git commit 以及检出的代码是否有改动、包的文件及其哈希，以及包的哈希 |
| `interactive` | 只出现在有用户参与的对话中：`confirmation`（`never` 或 `always`）和 `instruction`（用户的第一条消息，或 null） |
| `agent` | 只用于子 agent：它的 `session`、`agent`、`parent`、`depth`、`workspace` 和 `budget`（`calls`、`cost`、`seconds`） |

## events.jsonl

每行一个 JSON 对象。每条记录都有：

| 字段 | 内容 |
|---|---|
| `seq` | 记录的编号，从 0 开始：即它的 id |
| `time` | 墙钟时间，epoch 秒 |
| `event` | 记录的类型（见下表） |
| `source` | 来自谁：`user`、`agent`（主模型）、`program`（在 agent 的 kernel 中运行的代码）、`environment`（worker）或 `harness` |
| `who` | 对话进入会话之后：`{session, agent, parent}`，即这是谁的记录 |

以及该类型自己的字段。类型目录是 `harness.runtime.conversation.EVENTS`（每种都有来源、是否把内容展示给模型，以及一行说明）；
不在目录中的类型会被拒绝。下文标为*展示*的记录包含模型看到的内容，因此仅凭 trace 就能重建模型的历史
（`harness.runtime.conversation.rebuild_messages`）。

### 对话

| 事件 | 来源 | 字段 |
|---|---|---|
| `state` | harness | `status`：执行状态，为 `IDLE`（两轮之间：对话保留一切，等待开始下一轮的东西）、`RUNNING`、`PAUSED`、`WAITING_FOR_CONFIRMATION`、`FINISHED`、`ERROR` 之一；`reason`：一轮之后是这一轮怎样结束的（同 `turn_result`），对话结束时是 summary 的状态 |
| `reset` | environment | *展示。* `observation`：`episode_id`、`step`、`instruction`、`state`、`images`（data URL） |
| `user_message` | user | *展示。* `text`，用于模型的下一次调用；由父 agent 发送时还有 `sender` |
| `agent_message` | agent | *展示。* `text`：不带程序块的回复，即模型的回答，它结束这一轮 |
| `turn_result` | harness | 一轮的结束。`reason`：`answer`、`budget`（这一轮的模型调用次数）、`wall_time`（这一轮的时间）、`cost`（对话的上限）、`error`、`interrupted`、`episode_ended`，对话在这一轮进行中被结束时为 `closed`；`turn`（第几轮）、`session`、`model_calls`（这一轮内）、`cost_usd`（对话至今）、`seconds`、`result`（回答）、`error` |
| `resumed` | harness | *展示。* 对话在新进程里继续：恢复的 `messages` 条数、恢复的 `facts`、随旧进程消失的 `units` |
| `confirmation_request` | harness | `code`：一个程序在等待用户批准 |
| `confirmation` | user | *展示。* `accepted`、`reason`：用户批准或拒绝了等待中的程序 |
| `program_held` | harness | 模型回答时用户按了暂停：它的程序等待继续 |
| `program_dropped` | harness | `reason`（`user_message`）：被扣住的程序没有运行，被用户的消息取代 |
| `user_took_over` | harness | `window`：用户把自己的一个窗口切到了前台；对话暂停，直到用户交还电脑 |
| `workspace_reclaimed` | harness | `by`：这个对话在等待用户，app 把它结束了，好让另一个对话使用它的工作区 |
| `environment_attached` | harness | *展示。* `kind`、`label`、`why`（模型给出的理由）、`level`、`asked`、`skipped_confirmation`、`folder`：对话取用了另一个环境 |
| `environment_refused` | harness | *展示。* `kind`、`why`、`reason`、`level`、`asked`：取用另一个环境的请求被拒绝（设置不允许、用户拒绝，或没有人可问） |
| `environment_released` | harness | *展示。* `kind`、`label`、`reason`：归还了取用的环境 |
| `agents_enabled` | harness | *展示。* `enabled`、`asked_by`（`user` 或 `model`）、`why`：这个对话打开了子 agent，或用户没有同意 |
| `views` | program | `action`：`looked`（带 `program` 和 `views`：每个的 `camera`、`region`、`pin`）、`watch`、`unwatch`、`keep`、`unpin`：程序对模型所见画面的声明 |
| `stuck` | harness | `repeated`（`program` 或 `event`）、`what`：同一个程序或同一个未处理事件连续出现三次（交互式对话；只做记录） |
| `screen_recording` | harness | 对话所用的屏幕正在录制（`screen.mkv`、`screen.json`）：`video`、`display`、`area`、`fps`、`clock`、`start`、`stop`；无法录制时为 `error` |

### 模型调用

| 事件 | 来源 | 字段 |
|---|---|---|
| `thought_queued`、`thought_started`、`thought_cancelled`、`thought_exited` | agent | 记录 Thought ID、角色、触发原因、归属和输入版本。退出回执记录耗时和已知用量。 |
| `model_request` | harness | *展示。* `call`（从 0 开始）；`model` 和 `reasoning_effort`，调用发往哪里；`reason`：`start`、`user`、`program_end`、`program_running`（程序还在运行时这一轮就回来了）、`unit_end`（一个不是模型程序的单元结束了）、`wait_end`、`escalation`、`error`、`verify`、`format`、`empty`、`rejected`；`total_messages`、`sent_messages`、`new_messages`（上次调用之后新增的消息）；`context`（发送的每条消息一行：`role`、文本开头、`chars`、`images`、`omitted`）；`replaces`：`new_messages` 替换了历史中最后几条消息 |
| `model_text` | agent | `call`、`kind`（`text` 或 `reasoning`）、`text`：流式回复的一段，调用进行期间每种最多每 0.3 秒一条；完整内容在 `model_reply` 中 |
| `model_reply` | agent | *展示。* `call`（从 1 开始）、原始 `text`、`usage`（`input_tokens`、`output_tokens`、`cost_usd`、`finish_reason`）、`response_id`、`seconds`、provider 返回时的 `reasoning`；`presentation`，app 展示的回复：`kind`、`body`、`thought`；纯文字回复的 `kind` 为 `message`，什么都不能运行时为 `invalid` |
| `model_preempted` | harness | `call`、`back`（回复是否已返回；若已返回则带 `text` 和 `usage`）、`reason`：调用还在途中时有东西到达模型（一条消息、一个未处理的事件、一个以错误或事件结束的单元），这次回复被放在一边，模型重新被询问 |
| `empty_reply` | harness | `call`、`usage`、`seconds`、`reasoning`：没有正文的回复（只有推理，没有被截断）；模型立即被重新询问，不算格式错误，最多连续两次 |
| `protocol_error` | harness | *展示。* `message`、`truncated`；回复只说了模型要做什么时有 `announced`：回复没有有效的程序块，什么都没有运行，模型会被告知 |
| `malformed_dropped` | harness | `messages`：有效回复到来后，格式错误的往来从历史中移除 |
| `results_cleared` | harness | `results`、`idle_seconds`：服务商的缓存已冷之后的那次调用之前，除最近 5 个以外的程序结果被替换为 `[Old tool result content cleared]`；下一条 `model_request` 替换它之前的全部消息 |
| `compaction` | harness | `action`（`done`、`failed`）、`tokens`（上一次调用读到的上下文）；完成时有 `messages_before`、`messages` 和代替此前对话的 `summary`；下一条 `model_request` 替换它之前的全部消息 |
| `verify` | environment | *展示。* `claim`、`answer`：verifier 对模型声明的回答 |

### 单元与等待

模型写的每个程序都作为一个单元与其他单元并排运行。模型的这一轮立刻回来：程序在 `runtime.turn_grace_seconds` 内结束时带着它的结果，否则程序仍在运行。

| 事件 | 来源 | 字段 |
|---|---|---|
| `unit_end` | program | *展示。* `unit`、`name`、`kind`（程序 spawn 的代码或反射启动的程序为 `program`，子 agent 为 `agent`）、`status`（`ok`、`error`、`escalated`、`cancelled`、`episode_ended`、`finished`）、`error`、`escalation`、`stdout`、`returned`、`seconds`、`events`、`handled`（有 handler 处理了它的失败）：一个不是模型程序的单元结束了。程序的结束记在它的 `cell` 记录里 |
| `wait` | agent | `seconds`（最多持续多久）、`asked`（回复里写的秒数）：模型回复了 `<wait>` |
| `wait_end` | harness | *展示。* `why`：`unit`（模型启动的一个单元结束了）、`message`、`event`、`time` 或 `pause`；`seconds` |
| `rule` | program | `name`、`action`（`began`、`ended`）、`unit`、`priority`：反射树的一个节点启动了它的程序（`priority` 是它在树里的位置） |
| `fact` | program | `name`、`value`（开头部分）或 `dropped`：运行的一个事实变了 |
| `preempted` | program | 优先级更高的单元（`by`、`by_name`，是反射的程序时还有 `rule`，优先级为 `priority`）从某个单元（`unit`、`name`）的一次执行（`execution`）手里接管了环境；该执行以 `PREEMPTED` 结束，以 `restart=True` 启动的单元则之后被重新启动（`restart`）；模型会立即得知（紧随其后的 `escalation` 记录） |
| `held_back` | program | 某个反射（`rule`，优先级 `priority`）轮到了，但因为一个不可打断的单元（`by`、`by_name`）正持有环境而没有行动；那个单元结束后它会被重新判断；每条规则对每个单元只记一次；模型会立即得知（紧随其后的 `escalation` 记录） |

### 程序

| 事件 | 来源 | 字段 |
|---|---|---|
| `cell` | program | *展示。* `code`；`action`（直接模式：模型写出的动作）；`result`：`status`、`error`、`escalation`、`episode_ended`、`finish`、`stdout`、`seconds`、`events`（每次有界执行一条，[下文](#执行事件)）、`state`、`usage`、`report`（skill 的本轮报告：`text` 和它勾勒的相机 `images`）、`strategy`；`attachments`（数量） |
| `plan` | program | `steps`：用户看到的计划，以及哪些步骤已完成 |
| `skill_step` | program | `skill`、`step`、`of`、`what`、`ok`、`seconds`、`reason`：程序运行期间，skill 计划中的一步结束了；是模型下次再看时的新情况 |
| `guard` | program | `name`、`action`、`stops`：一个 guard 触发了，以及它是否停止所在的执行 |
| `model_changed` | user | `model`、`reasoning_effort`：从下一次调用起的主模型（POST /api/conversations/model） |
| `decision` | program | agent 这一轮请用户拍板的事（包里的 skill，提供决策工具）：`subject`、`question`、`options`、`default`（选项的下标）、`irreversible` |
| `stay_on_screen` | program | agent 在它的一轮结束时保留屏幕；聊天留在后面 |
| `world` | program | 这一局的记忆改变了（runtime/memory.py）：`action`（`remember`、`seen`、`forget`、`carried`；`recall`：`query`、`kind`、`near`、`radius` 和它找到的 id `found` 及返回的 `results`；`refused`：没人等着的请求失败了，`request` 和 `reason`）、`id`、`kind`、`name`、`text`、`where`、`space`、`by`（谁记下的）、`confidence`、`seen`、`version`（`carried`：这次运行接手的存储里已有的条目）；每个程序之后模型会收到一份摘要 |
| `program_permission` | harness | 程序在机器上的一步：`action`（`command`、`network`、`write`、`read`）、`key` 和 `what`（程序、主机或路径）、`level`、`allowed`、`asked`（是否问了用户），以及有的话 `sensitive` 和 `reason` |
| `web_search` | harness | `query` 和 `results`（条数），或 `error`：程序的一次 `search()` |
| `private_paths` | harness | `paths`：worker 的私有文件（它的 profile 中的 `private_paths`，例如游戏实例）；`guarded`：kernel 从启动起就拒绝程序访问的根目录 |
| `file_access` | program | `operation`（`open`、`os.listdir` 等）、`path`：程序试图打开或列出 worker 的某个私有文件；已被拒绝 |
| `modules` | harness | `loaded`：kernel 导入的 `skills` 和 `benches` 包中的模块，先是启动时导入的，之后是每个程序之后新导入的；`harness audit-run` 读取它们 |
| `kernel_died` | harness | `message`：kernel 进程死了 |

### 环境和输入

| 事件 | 来源 | 字段 |
|---|---|---|
| `input` | environment | 一步输入是怎样到达电脑的：`command`（它的类型）、`executed`、`sent`（它发出了什么：按键、按钮和指针移动；输入的文本只记录长度）、`mechanism`（`semantic`、`targeted` 或 `physical`）、`status`（`delivered`、`unverified`、`not_delivered`）、它到达的 `app` 和窗口 `title`、`waited`（等待输入锁的秒数） |
| `physical_request` | harness | `id`、`level`、`app`、`window`、`handle`、`actions`（以及原因，来自 `request_physical`）：一步需要用户真实的鼠标和键盘，物理输入级别要求先询问 |
| `physical_answer` | user | `id`、`accepted`、`remember`（`once`、`app`、`session`、`always`）、`reason`：用户对物理输入请求的回答 |
| `page_read` | environment | `text`、`links`、`url`、`title`、`offset`、`total_chars`、`next_offset`：返回给程序的可见网页文本和链接；程序打印的内容会到达模型 |

### 库

| 事件 | 来源 | 字段 |
|---|---|---|
| `library` | harness | `action` 及其字段。`opened`：`version` 和加载的条目 `entries`（每个的 `id`、`name`、`sha256`、`evidence`、`source`、`summary` 和文本（代码只记录前 400 个字符）），即运行开始时的 library。`loaded`：`version`、`status`、`error`，库的代码在 kernel 中运行了。`used`：`uses`，学习中的运行每个 episode 结束后，库代码有多少次执行算作了条目的使用。`replayed`：`entries`、`status`、`error`，开始时，临时条目的测试重新运行了。`test`（来源为 `program`）：`entry`（它的类型）、`name`、`ok`、`seconds`、`reason`，一个条目在被提出之前运行了它自己的测试。`admitted`（*展示*）：`section`、`name`（条目的文件）、其字节的 `sha256`、`kind`、`evidence`（`proposed`、`provisional`、`replayed`、`validated`）、`admitted`（它是进入了库还是在等待）、`version_before`、`version`（之后）、`origin`（`model` 或 `reflection`）；`learned`：它是怎样学到的，`active` 或 `passive`。库的 `admissions.jsonl` 中有同样的一行。`rejected`：`kind`、`name`、`reason`，库拒绝了一个条目（库已冻结、名称不合法）。`promoted`：`key`、`evidence`（或 `failed`）、`why`，一个条目的证据改变了。`admission`：`level`（`off`、`fixture`、`own_test`）、`allowed`（宿主允许的档位）、`physical`（worker 的 profile 所报告的），即这次运行里学到的代码如何被接纳。`trial_started`、`trial_observed`、`trial_pending`：`key`、`revision`，宿主运行条目自带测试时还有 `method` 为 `own_test`、`ok`、`seconds`、`error`、`stdout`；即两个程序之间对待验证提案的验证。`demoted`：`key`、`revision`、`ok`、`failed`，一个靠自带测试接纳的条目在使用中失败后退回了待验证。较早的 trace 把每个 action 写成单独的一种记录（`library_loaded`、`library_admitted` 等） |

### 子 agent 和条目

| 事件 | 来源 | 字段 |
|---|---|---|
| `agent_delegated` | program | `agent`（它的 id）、`run`、`task`、`workspace`、`kind`、`budget`、`model`、`windows`（交给它的窗口）、`directory`：一个程序启动了子 agent |
| `agent_waited` | program | `agents`、`timeout`、`seconds`、`states`（之后每个 agent 的状态）：一个程序等待了子 agent |
| `agent_sent` | program | `agent`、`text`：一个程序给子 agent 发了消息 |
| `agent_cancelled` | program | `agent`：一个程序停止了子 agent |
| `agent_report` | harness | `agent`、`run`、`status`、`result`、`question`、`error`、`model_calls`、`cost_usd`、`seconds`、`directory`、`files`：一个子 agent 结束了 |
| `entry_start` | program | `id`（`e1`、`e2` ...）、`parent`（`e0`，即模型：每个单元都属于它）、`name`、`kind`（`program`、`agent`）、`cell`（它是模型的第几个程序）、`rule`（它是哪条规则的程序）、`priority`、`claims`、`agent`（子 agent 的 id）、`span` |
| `entry_claims` | program | `id`、`claims`：单元在 `claim` 或 `release` 之后当前占用的通道 |
| `entry_end` | program | `id`、`status`（`done`、`failed`、`cancelled`）；失败时有 `error`，因事件失败时为 `event_kind` |

### 时间轴

| 事件 | 来源 | 字段 |
|---|---|---|
| `span_start` | harness | `id`、`lane`（部分的类型：`model`、`verifier`、`program`、`skill`、`service`、`env`）、`entry`（不是 agent 的程序时，运行的是哪个条目的代码）、`name`、`parent`（它运行时所在的 span：skill 的程序、服务调用的 skill），以及该部分的细节（skill 的 `parameters` 和 `tick`、模型调用的 `call` 和 `reason` 等）；`time` 是开始时间 |
| `span_end` | harness | `id`；`time` 是结束时间；skill 有 `event_kind` 和 `end_tick`（事件上报时有 `escalated`），程序有 `status`，模型调用有 `output_tokens`；抛出异常时有 `error` |
| `tick_periods` | program | 在墙钟上：它的控制周期运行得如何，包括周期数、目标、时长和组成部分，以及有多少个迟到 |

回放和 app 的时间轴泳道由这些 span 和单元读出。

### 结束

| 事件 | 来源 | 字段 |
|---|---|---|
| `policy_to_end` | program | `status`、`error`：策略运行之后的调用用完时，被移交的任务继续运行到结束 |
| `finish` | agent | `text`：以 `<finish>` 给出的回答（与纯文本回复相同）；程序调用 `finish()` 时 `source` 为 `program`，这一轮在 `policy_to_end` 之后被结束时为 `harness` |
| `wrap_up` | program | `status`、`error`、`events`：benchmark 的 episode 结束约定运行了 |
| `outcome` | environment | `outcome`：`success`、`reward`、`process_score`、`terminated`、`truncated`、`steps`，episode 结束后凭 token 读取；从不展示给模型 |
| `episode_video` | environment | `files`（相机 → 路径）：episode 的视频已写出 |
| `interrupted` | harness | 这一轮被取消，或运行被中断 |
| `error` | harness | `message`：这一轮（第一轮之前：对话）以错误结束 |
| `cleanup_error` | harness | `message`：关闭 episode 部分失败 |

## summary.json

| 键 | 内容 |
|---|---|
| `run`, `task`, `seed` | episode 的目录、任务和 seed |
| `status` | 最后一轮怎样结束：`finished`（回答）、`episode_ended`、`budget_exhausted`、`wall_time_exhausted`、`cost_exhausted`、`interrupted`、`error`；用户或 host 在一轮进行中结束对话时为 `closed`（在两轮之间关闭的对话保留最后一轮的状态） |
| `open` | 对话还在继续时，一轮结束时写下的 summary 里为 `true`；对话结束后没有这一项 |
| `success`, `reward`, `process_score`, `steps` | 来自 outcome |
| `model_calls`, `verifier_calls`, `cells` | 主模型和 verifier 的调用次数，运行的程序数 |
| `input_tokens`, `output_tokens`, `cost_usd` | 主模型和 verifier，加上程序发起的视觉调用 |
| `agent_seconds`, `kernel_seconds`, `wall_seconds` | 模型调用用时、程序用时、总用时 |
| `decisions` | 按 `reason` 统计的模型调用（同 `model_request`） |
| `empty_replies` | 没有正文、立即重新询问的回复 |
| `events_handled`, `events_escalated` | 在模型之下处理掉的执行事件，以及上报给模型的执行事件 |
| `guard_triggers` | 触发的 guard |
| `vision_calls`, `vision_cost_usd` | 程序发起的视觉调用 |
| `agents` | 有子 agent 运行时：`started`、`model_calls`、`cost_usd` |
| `strategy` | `start(strategy, kind)` 的选择：`strategy`（A、B、C）、`kind`、`policy`、`step`；被移交的任务运行后有 `policy_ran`；B 较晚移交时有 `after` |
| `error` | 状态为 `error` 时 |

## 执行事件

`cell.result.events` 为每次有界执行列出一条记录：

```json
{"skill": "move_eef", "event": {"kind": "COMPLETED", "source": "move_eef", "detail": {}, "tick": 22}, "ticks": 22}
```

| 类型 | 含义 |
|---|---|
| `COMPLETED`, `PREDICATE_SATISFIED` | 正常：程序继续运行，不需要 handler |
| `TIMEOUT` | 执行用完了 tick |
| `BLOCKED` | 运动的路径执行完了，但机械臂没有到达：接触或负载阻挡了它 |
| `GUARD_TRIGGERED`（或 guard 自己的事件名） | 一个 guard 触发了 |
| `REGION_EXIT` | 运动离开了允许的区域 |
| `SHIELD_REJECTED` | worker 的安全层（shield）拒绝了命令 |
| `REACTIVE_FAULT` | 一条反应规则失败了 |
| `SKILL_ERROR` | skill 抛出了异常 |
| `EPISODE_ENDED` | 环境结束了 episode |
| `USER_PAUSED` | 用户暂停：模型的每个单元都停下，模型会得知 |
| `PREEMPTED` | 优先级更高的单元从这次执行手里接管了环境，执行在当前位置结束（以 `restart=True` 启动的单元则被重新启动） |
| `ENTRY_FAILED` | 一个不是模型程序的单元失败了（异常，或没有人处理的事件） |
| `CHANNEL_CONFLICT` | 一个单元试图使用另一个单元占用、驱动或保持的通道 |

上报给模型的事件携带整个执行：`skill`、`parameters`、`start_tick`、`end_tick`、`event`、`samples`（每 5 个 tick 的状态）。

## 执行反馈记录

`execution_event` 的嵌套 `execution` 字段记录有界执行的 `skill`、终止 `event`、`ticks` 和可选 `entry`。事件保留动作身份和证据引用，操作数据返回调用程序，不序列化进事件。
`program_output` 按顺序记录程序运行时的 `cell` 与文本片段。cell 回执包含有界预览与 `event_counts`；轨迹保留持续收到的记录。
