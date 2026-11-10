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
| `state` | harness | `status`：执行状态，为 `IDLE`（等待用户的下一条消息）、`RUNNING`、`PAUSED`、`WAITING_FOR_CONFIRMATION`、`FINISHED`、`ERROR` 之一；模型的一轮或 episode 结束时还有 `reason`（summary 的状态） |
| `reset` | environment | *展示。* `observation`：`episode_id`、`step`、`instruction`、`state`、`images`（data URL） |
| `user_message` | user | *展示。* `text`，用于模型的下一次调用；由父 agent 发送时还有 `sender` |
| `agent_message` | agent | *展示。* `text`：不带程序块的回复，即给用户的消息（或给父 agent 的问题） |
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
| `model_request` | harness | *展示。* `call`（从 0 开始）；`model` 和 `reasoning_effort`：这次调用发给谁；`reason`：`start`、`user`、`program_end`、`escalation`、`error`、`action`、`verify`、`format`、`empty`、`rejected`，对于程序运行期间发出的调用为 `ahead`（程序开始时）或 `think`（再看一次，带 `why`：`news` 或 `interval`，以及 `news`：来了什么）；程序运行期间还有 `program`（正在运行的程序的编号），为一条消息发出的调用还有 `message`；`total_messages`、`sent_messages`、`new_messages`（上一次调用之后新增的消息）；`context`（发送的每条消息一行：`role`、文本开头、`chars`、`images`、`omitted`）；`replaces`：`new_messages` 替换历史中最后几条消息 |
| `model_text` | agent | `call`、`kind`（`text` 或 `reasoning`）、`text`：流式回复的一段，调用进行期间每种最多每 0.3 秒一条；完整内容在 `model_reply` 中 |
| `model_reply` | agent | *展示。* `call`（从 1 开始）、原始 `text`、`usage`（`input_tokens`、`output_tokens`、`cost_usd`、`finish_reason`）、`response_id`、`seconds`，provider 返回时还有 `reasoning`；`presentation`，app 显示的回复：`kind`、`body`、`thought`、`assume`；用文字回复时 `kind` 为 `message`，没有可运行的内容时为 `invalid`。程序运行期间发出的调用还有 `ahead`（它最后怎样了，同 `ahead` 记录），再看一次的调用还有 `think`；只有用上的回复才属于历史 |
| `model_preempted` | harness | `call`、`back`（回复是否已回来；回来时还有它的 `text` 和 `usage`）、`seconds`：一条给模型的消息把这次调用的回复放到一边，模型带着这条消息被重新询问 |
| `empty_reply` | harness | `call`、`usage`、`seconds`、`reasoning`：没有正文的回复（只有推理，没有被截断）；模型立即被重新询问，不算格式错误，最多连续两次 |
| `protocol_error` | harness | *展示。* `message`、`truncated`；回复只说了模型要做什么时有 `announced`：回复没有有效的程序块，什么都没有运行，模型会被告知 |
| `malformed_dropped` | harness | `messages`：有效回复到来后，格式错误的往来从历史中移除 |
| `context_shortened` | harness | `history_turns`、`sent_messages`：模型服务器内存耗尽后，发送的历史轮数减少 |
| `verify` | environment | *展示。* `claim`、`answer`：verifier 对模型声明的回答 |

### 边做边想

当模型在程序运行期间思考时（`model.think_while_acting`），一次调用会在程序运行期间发出，这些记录说明它最后怎样了。

| 事件 | 来源 | 字段 |
|---|---|---|
| `ahead` | harness | `call`、`program`、`outcome`：`used`（程序没有事件就结束了，回复接着运行）、`discarded`（程序因事件或消息结束）、`waited`（回复是 `<wait>`）、`unused`（episode 或这一轮随程序一起结束）、`beside`（它在程序旁边运行）或 `replaced`（后来的一次再看引用了它）；`why`、`seconds`、`back`（回复是否已回来）；`assume`，回复预期程序留下的条件，以及 `held`，条件是否成立；在回来之前被放到一边时有 `cancelled`；再看一次的调用有 `think`；`error` |
| `side_program` | harness | `id`、`program`、`call`、`code`：对一条消息的回复不需要自己的一步，因此立即在正在运行的程序旁边运行 |
| `side_program_end` | harness | `id`、`status`、`error`、`escalation`：在旁边运行的程序如何结束 |
| `program_stopped` | harness | `program`、`call`、`why`：程序运行期间到达的消息的回复，或带 `<stop>` 的再看一次的回复，让程序在下一步停下 |

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
| `library` | harness | `action` 及其字段。`opened`：`version` 和加载的条目 `entries`（每个的 `id`、`name`、`sha256`、`evidence`、`source`、`summary` 和文本（代码只记录前 400 个字符）），即运行开始时的 library。`loaded`：`version`、`status`、`error`，库的代码在 kernel 中运行了。`used`：`uses`，学习中的运行每个 episode 结束后，库代码有多少次执行算作了条目的使用。`replayed`：`entries`、`status`、`error`，开始时，临时条目的测试重新运行了。`test`（来源为 `program`）：`entry`（它的类型）、`name`、`ok`、`seconds`、`reason`，一个条目在被提出之前运行了它自己的测试。`admitted`（*展示*）：`section`、`name`（条目的文件）、其字节的 `sha256`、`kind`、`evidence`（`proposed`、`provisional`、`replayed`、`validated`）、`admitted`（它是进入了库还是在等待）、`version_before`、`version`（之后）、`origin`（`model` 或 `reflection`）；`learned`：它是怎样学到的，`active` 或 `passive`。库的 `admissions.jsonl` 中有同样的一行。`rejected`：`kind`、`name`、`reason`，库拒绝了一个条目（库已冻结、名称不合法）。`promoted`：`key`、`evidence`（或 `failed`）、`why`，一个条目的证据改变了。较早的 trace 把每个 action 写成单独的一种记录（`library_loaded`、`library_admitted` 等） |

### 子 agent 和条目

| 事件 | 来源 | 字段 |
|---|---|---|
| `agent_delegated` | program | `agent`（它的 id）、`run`、`task`、`workspace`、`kind`、`budget`、`model`、`windows`（交给它的窗口）、`directory`：一个程序启动了子 agent |
| `agent_waited` | program | `agents`、`timeout`、`seconds`、`states`（之后每个 agent 的状态）：一个程序等待了子 agent |
| `agent_sent` | program | `agent`、`text`：一个程序给子 agent 发了消息 |
| `agent_cancelled` | program | `agent`：一个程序停止了子 agent |
| `agent_report` | harness | `agent`、`run`、`status`、`result`、`question`、`error`、`model_calls`、`cost_usd`、`seconds`、`directory`、`files`：一个子 agent 结束了 |
| `entry_start` | program | `id`（`e1`、`e2` ...）、`parent`（启动它的条目；`e0` 是 agent 的程序）、`name`、`kind`（`program`、`agent`、`reflex`）、`claims`、`agent`（子 agent 的 id）、`span`；反射还有 `why` |
| `entry_claims` | program | `id`、`claims`：条目在 `claim` 或 `release` 之后当前占用的通道 |
| `entry_end` | program | `id`、`status`（`done`、`failed`、`cancelled`）；失败时有 `error`，因事件失败时为 `event_kind` |

### 时间轴

| 事件 | 来源 | 字段 |
|---|---|---|
| `span_start` | harness | `id`、`lane`（部分的类型：`model`、`verifier`、`program`、`skill`、`service`、`env`）、`entry`（不是 agent 的程序时，运行的是哪个条目的代码）、`name`、`parent`（它运行时所在的 span：skill 的程序、服务调用的 skill），以及该部分的细节（skill 的 `parameters` 和 `tick`、模型调用的 `call` 和 `reason` 等）；`time` 是开始时间 |
| `span_end` | harness | `id`；`time` 是结束时间；skill 有 `event_kind` 和 `end_tick`（事件上报时有 `escalated`），程序有 `status`，模型调用有 `output_tokens`；抛出异常时有 `error` |
| `tick_periods` | program | 在墙钟上：它的控制周期运行得如何，包括周期数、目标、时长和组成部分，以及有多少个迟到 |

回放和 app 的时间轴泳道由这些 span 和条目读出。

### 结束

| 事件 | 来源 | 字段 |
|---|---|---|
| `policy_to_end` | program | `status`、`error`：策略运行之后的调用用完时，被移交的任务继续运行到结束 |
| `finish` | agent | `text`：任务被宣布完成；程序调用 `finish()` 时 `source` 为 `program`，episode 在 `policy_to_end` 之后被结束时为 `harness` |
| `wrap_up` | program | `status`、`error`、`events`：benchmark 的 episode 结束约定运行了 |
| `outcome` | environment | `outcome`：`success`、`reward`、`process_score`、`terminated`、`truncated`、`steps`，episode 结束后凭 token 读取；从不展示给模型 |
| `episode_video` | environment | `files`（相机 → 路径）：episode 的视频已写出 |
| `interrupted` | harness | 运行被中断了 |
| `error` | harness | `message`：episode 以错误结束 |
| `cleanup_error` | harness | `message`：关闭 episode 部分失败 |

## summary.json

| 键 | 内容 |
|---|---|
| `run`, `task`, `seed` | episode 的目录、任务和 seed |
| `status` | `finished`、`episode_ended`、`budget_exhausted`、`wall_time_exhausted`、`cost_exhausted`、`interrupted`、`error`；用户在 finish 之前结束对话时为 `closed` |
| `success`, `reward`, `process_score`, `steps` | 来自 outcome |
| `model_calls`, `verifier_calls`, `cells` | 主模型和 verifier 的调用次数，运行的程序数 |
| `input_tokens`, `output_tokens`, `cost_usd` | 主模型和 verifier，加上程序发起的视觉调用 |
| `agent_seconds`, `kernel_seconds`, `wall_seconds` | 模型调用用时、程序用时、总用时 |
| `decisions` | 按 `reason` 统计的模型调用（同 `model_request`）；程序运行期间发出的调用按回复的去向统计：`ahead_used`、`ahead_discarded`、`ahead_waited`、`ahead_unused` |
| `empty_replies` | 没有正文、立即重新询问的回复 |
| `ahead_set_aside` | 程序运行期间发出、回复没有用上的调用：不占这一轮的调用预算，每轮最多 `max_model_calls` 次 |
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
| `USER_PAUSED` | 用户暂停了；它总是上报给模型 |
| `USER_MESSAGE` | 有一条给模型的消息到了；它总是上报给模型，程序启动的条目继续运行 |
| `ENTRY_FAILED` | 程序启动的一个条目失败了（异常，或没有人处理的事件） |
| `CHANNEL_CONFLICT` | 一个条目试图使用另一个条目占用、驱动或保持的通道 |

上报给模型的事件携带整个执行：`skill`、`parameters`、`start_tick`、`end_tick`、`event`、`samples`（每 5 个 tick 的状态）。

## 执行反馈记录

`execution_event` 的嵌套 `execution` 字段记录有界执行的 `skill`、终止 `event`、`ticks` 和可选 `entry`。事件保留动作身份和证据引用，操作数据返回调用程序，不序列化进事件。
`program_output` 按顺序记录程序运行时的 `cell` 与文本片段。cell 回执包含有界预览与 `event_counts`；轨迹保留持续收到的记录。
