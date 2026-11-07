---
title: "JSON 输出"
description: "harness run、inspect、runs 和 doctor 输出的 JSON，suite 保存的文件，以及其他命令的 JSON 输出。"
---

脚本读取的就是这些内容。下面每份文档都带 `schema_version`，表示它自身格式的版本。同一版本内只会新增字段；
删除字段、改名或改变字段含义都会提升版本。读取方忽略不认识的字段，在依赖其他字段之前先检查
`schema_version`。这些表格列出了命令写出的每个字段；某个版本改动了字段，也会同时改动对应的表格。

其他命令输出不带版本的 JSON（[其他 JSON 输出](#其他-json-输出)），所有命令都以同样的方式报告错误（[错误](#错误)）。

类型以 `?` 结尾表示可以是 `null`。标为*可选*的行只在部分情况下出现。时间除非另有说明，都是 UTC 的 ISO 8601 格式；
花费的单位是美元。

## suite.json

`OUTPUT/suite.json`，由 `harness run` 在开始时写入，之后每个加入该 suite 的进程也会写入。版本 2 新增了 `invocation`；
版本 1 的文件（或没有 `schema_version` 的文件）仍可读取，并可用原参数续跑。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 2 |
| `episodes` | 列表 | 请求的 episode，包括写入这个输出目录的所有运行 |
| `episodes[].task` | 字符串 | 任务 |
| `episodes[].seed` | 整数 | 请求的 seed（layout） |
| `legacy_selection` | 对象? | 版本 1 的文件只有任务和 seed 的并集时设置：其中的 `tasks` 和 `seeds` 是候选，而不是确认的请求配对 |
| `invocation` | 对象? | `harness run --resume` 重复执行的命令行；suite 不是通过命令行写入时（Python API）为 `null` |
| `invocation.experiment` | 字符串? | 实验文件的绝对路径；`null` 表示没有实验文件，只用了 `--tasks` |
| `invocation.agent` | 字符串? | `--agent`，是文件时为绝对路径 |
| `invocation.model` | 字符串? | `--model`：`configs/models/` 中的名称，或绝对路径 |
| `invocation.sets` | 列表 | 各个 `--set KEY=VALUE`，保持原顺序 |
| `invocation.tasks` | 列表 | 展开后的任务名（`all`、维度和 moving 都已解析）；多次运行共用一个输出目录时，是它们全部的任务 |
| `invocation.seeds` | 列表 | 展开并排序后的 seed；多次运行时，是它们全部的 seed |
| `invocation.strict` | 布尔? | `--strict` / `--no-strict`；`null` 表示默认 |
| `invocation.deploy` | 字符串? | `--deploy`，没有则取当时的 `$HARNESS_DEPLOY`，是文件时为绝对路径；`null` 表示自动放置 |
| `invocation.script` | 对象? | `--script`；`null` 表示由模型回答 |
| `invocation.script.path` | 字符串 | 脚本回复的绝对路径 |
| `invocation.script.sha256` | 字符串 | 脚本回复的哈希，与 `execution.script_sha256` 相同；回复改变后续跑会被拒绝 |
| `invocation.max_total_cost_usd` | 数? | `--max-total-cost-usd` |
| `invocation.rerun_errors` | 布尔 | 创建这条记录的运行的 `--rerun-errors`；`--resume --rerun-errors` 只对那一次运行有效 |
| `invocation.gpus` | 列表? | 最近一次运行的 `--gpus`；`null` 表示用 deploy 的设置 |
| `invocation.workers_per_gpu` | 整数? | 最近一次运行的 `--workers-per-gpu` |
| `invocation.base_port` | 整数? | 最近一次运行的 `--base-port` |
| `invocation.workspaces` | 整数? | 最近一次运行的 `--workspaces` |
| `run` | 字符串? | 实验文件 |
| `agent` | 字符串 | agent 名称 |
| `agent_id` | 字符串 | agent identity |
| `execution` | 对象 | suite 扩展时不能改变的设置；续跑时会比较 |
| `execution.agent_id` | 字符串 | agent identity |
| `execution.bench` | 字符串 | benchmark |
| `execution.layout_source` | 字符串 | `procedural`、`dev` 或 `eval` |
| `execution.layout_pack_seed` | 整数? | 评测 layout 包 |
| `execution.dev_layout_dir` | 字符串? | 开发 layout 目录 |
| `execution.worker` | 对象 | benchmark 的 worker 选项 |
| `execution.budget` | 对象 | 每局预算 |
| `execution.budget.max_model_calls` | 整数? | 每局模型调用次数 |
| `execution.budget.max_wall_seconds` | 数? | 每局墙钟时间 |
| `execution.budget.max_cost_usd` | 数? | 每局花费 |
| `execution.script_sha256` | 字符串? | 脚本回复的哈希；`null` 表示由模型回答 |
| `legacy_unchecked_fields` | 列表 | 旧 suite 没有记录的执行设置字段，因此它早先的 episode 没有按这些字段核查 |
| `agent_version` | 字符串 | harness 的版本 |
| `deploy` | 字符串? | deploy 名称 |
| `tasks` | 列表 | 到目前为止请求过的全部任务 |
| `seeds` | 列表 | 到目前为止请求过的全部 seed |
| `layout_source` | 字符串 | 同 `execution.layout_source` |
| `layout_pack_seed` | 整数? | 同 `execution.layout_pack_seed` |
| `started` | 字符串 | suite 创建时的本地时间（`YYYY-MM-DD HH:MM:SS`） |

## .running

`OUTPUT/.running`，有 `harness run` 进程在处理该 suite 时存在。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 1 |
| `processes` | 列表 | 每个正在运行的进程一项；进程结束时删除自己的那一项 |
| `processes[].host` | 字符串 | 主机名 |
| `processes[].pid` | 整数 | 进程号 |
| `processes[].started` | 字符串 | 启动时间 |
| `processes[].boot_id` | 字符串? | 主机的 boot id（Linux），避免把上一次开机时的 pid 当成仍在运行 |

## run --dry-run

`harness run --dry-run`（也可与 `--resume` 一起用）：将要启动的运行。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 1 |
| `dry_run` | 布尔 | `true` |
| `output` | 字符串 | suite 目录的绝对路径 |
| `invocation` | 对象 | `suite.json` 将要记录的内容（字段同上） |
| `experiment` | 字符串? | 实验文件 |
| `agent` | 字符串 | agent 名称 |
| `agent_version` | 字符串 | harness 的版本 |
| `execution` | 对象 | 同 `suite.json` |
| `model` | 字符串? | 主模型 |
| `tasks` | 列表 | 任务 |
| `seeds` | 列表 | seed |
| `selected_episodes` | 整数 | 任务 × seed，不考虑续跑和 layout 替换 |
| `strict` | 布尔 | 缺少 skill 或服务时是否拒绝运行 |
| `skills` | 列表 | 启用的 skill |
| `skills_dropped` | 对象 | skill 名称 → 停用原因 |
| `services` | 列表 | 运行用到的服务 |
| `max_total_cost_usd` | 数? | 本次运行的 suite 花费上限 |
| `resume` | 对象 | 已有的输出目录对这次运行意味着什么 |
| `resume.existing_suite` | 布尔 | `suite.json` 已存在 |
| `resume.unchecked_legacy_fields` | 列表 | 已有 suite 没有记录的执行设置字段 |
| `resume.rerun_errors` | 布尔 | 以错误结束的 episode 会重跑 |
| `resume.policy` | 字符串 | 已完成和未完成的 episode 如何处理 |
| `readiness` | 字符串 | 预览没有检查的内容 |

## run and outcome.json

`harness run` 结束时输出、并写入 `OUTPUT/outcome.json` 的内容。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 1 |
| `output` | 字符串 | suite 目录的绝对路径 |
| `result` | 字符串 | `complete`、`errors`、`incomplete`、`budget_exhausted` 或 `interrupted` |
| `exit_code` | 整数 | `result` 对应的退出状态：0、3、4、5、130 |
| `interrupted` | 布尔 | 运行被 Ctrl-C 停止 |
| `started` | 字符串 | 本进程启动时间 |
| `ended` | 字符串 | 结束时间 |
| `tasks` | 列表 | 本次运行的任务 |
| `seeds` | 列表 | 本次运行的 seed |
| `requested_episodes` | 整数 | 本次运行的任务 × seed |
| `finished_episodes` | 整数 | 其中已完成或以错误结束的 |
| `counts` | 对象 | 本次运行的 episode 按状态计数 |
| `counts.completed` | 整数 | 有 summary，成功与否都算 |
| `counts.error` | 整数 | 以错误结束 |
| `counts.incomplete` | 整数 | 已开始，没有 summary |
| `counts.missing` | 整数 | 没有开始 |
| `counts.unreadable` | 整数 | 记录损坏 |
| `episodes` | 列表 | 本次运行中没有正常完成的 episode |
| `episodes[].task` | 字符串 | 任务 |
| `episodes[].seed` | 整数 | 请求的 seed |
| `episodes[].actual_seed` | 整数? | 实际为它运行的 layout（不稳定的 layout 会被替换） |
| `episodes[].state` | 字符串 | `error`、`incomplete`、`missing` 或 `unreadable` |
| `episodes[].status` | 字符串? | summary 中的状态 |
| `episodes[].error` | 字符串? | 错误 |
| `worker_failures` | 列表 | 失败的 worker |
| `worker_failures[].slot` | 整数 | worker 槽位 |
| `worker_failures[].task` | 字符串 | 它服务的任务 |
| `worker_failures[].stage` | 字符串 | `start`、`restart` 或 `episode` |
| `worker_failures[].reason` | 字符串 | 原因 |
| `budget` | 对象 | suite 花费上限 |
| `budget.max_total_cost_usd` | 数? | 上限 |
| `budget.spent_usd` | 数 | 本次运行的花费 |
| `budget.reached` | 布尔 | 已达到上限 |
| `budget.skipped` | 列表 | 因上限而没有开始的 episode |
| `budget.skipped[].task` | 字符串 | 任务 |
| `budget.skipped[].seed` | 整数 | seed |
| `cost_usd` | 数 | 本次运行的模型和 verifier 花费 |

## inspect

`harness inspect OUTPUT --json`。只读取文件，不做任何修改。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 1 |
| `suite_schema_version` | 整数 | `suite.json` 的 `schema_version`（没有时为 1） |
| `output` | 字符串 | suite 目录的绝对路径 |
| `observed_at` | 字符串 | 读取时间 |
| `evidence_updated` | 字符串 | 读到的最新文件的时间 |
| `liveness` | 字符串 | `running`、`stale`、`unknown` 或 `stopped` |
| `processes` | 列表 | `.running` 中的各项（字段同上） |
| `last_outcome` | 对象? | 最后结束的那次运行（`outcome.json`） |
| `last_outcome.exit_code` | 整数 | 它的退出状态 |
| `last_outcome.result` | 字符串 | 它的结果 |
| `last_outcome.ended` | 字符串 | 结束时间 |
| `agent` | 字符串? | agent 名称 |
| `agent_version` | 字符串? | harness 的版本 |
| `agent_id` | 字符串? | agent identity |
| `bench` | 字符串? | benchmark |
| `layout_source` | 字符串? | layout |
| `layout_pack_seed` | 整数? | 评测 layout 包 |
| `execution` | 对象 | 同 `suite.json`（没有时为 `{}`） |
| `invocation` | 对象? | 同 `suite.json` |
| `experiment` | 字符串? | 实验文件 |
| `deploy` | 字符串? | deploy 名称 |
| `selection_exact` | 布尔 | 记录了确切的请求配对（不是旧格式的并集） |
| `requested_episodes` | 整数 | 请求的 episode 数 |
| `candidate_episodes` | 整数 | 请求的加上旧格式候选的 episode 数 |
| `counts` | 对象 | episode 按状态计数 |
| `counts.completed` | 整数 | 有 summary，成功与否都算 |
| `counts.error` | 整数 | 以错误结束 |
| `counts.incomplete` | 整数 | 已开始，没有 summary |
| `counts.missing` | 整数 | 已请求，没有开始 |
| `counts.unknown` | 整数 | 旧格式候选，没有目录 |
| `counts.unreadable` | 整数 | 记录损坏 |
| `episodes` | 列表 | 每个请求的或候选的 episode |
| `episodes[].task` | 字符串 | 任务 |
| `episodes[].seed` | 整数 | 请求的 seed |
| `episodes[].requested` | 布尔 | `false` 表示旧格式候选 |
| `episodes[].actual_seed` | 整数? | 实际为它运行的 layout；等待新 layout 时为 `null` |
| `episodes[].state` | 字符串 | `completed`、`error`、`incomplete`、`missing`、`unknown` 或 `unreadable` |
| `episodes[].status` | 字符串? | summary 中的状态 |
| `episodes[].success` | 布尔? | summary 中的成功与否 |
| `episodes[].cost_usd` | 数? | summary 中的花费 |
| `episodes[].error` | 字符串? | 错误，或记录无法读取的原因 |
| `episodes[].directory` | 字符串，可选 | episode 目录，layout 确定后才有 |
| `episodes[].reason` | 字符串，可选 | 为什么还没有 layout |
| `recorded_cost_usd` | 数 | 当前 summary 中的花费 |
| `summaries_without_cost` | 整数 | 没有可用花费的当前 summary 数 |
| `cost_scope` | 字符串 | `recorded_cost_usd` 涵盖的范围 |
| `legacy_unchecked_fields` | 列表 | 同 `suite.json` |
| `warnings` | 列表 | 无法读取或无法确认的内容 |
| `next_steps` | 对象 | 后续命令 |
| `next_steps.report` | 字符串 | `harness report OUTPUT` |
| `next_steps.view` | 字符串 | `harness view OUTPUT` |
| `next_steps.resume` | 字符串 | `harness run --resume OUTPUT`；没有 `invocation` 的 suite 则说明如何手动续跑 |

## runs

`harness runs [ROOT] --json`：ROOT 下的 suite，最新证据在前。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 1 |
| `root` | 字符串 | runs 目录的绝对路径 |
| `suites` | 列表 | 每个 suite 一个对象：`inspect` 的字段，去掉 `schema_version`、`episodes`、`execution` 和 `invocation`；无法读取的 suite 只有 `output`、`error` 和 `evidence_updated` |

## doctor

`harness doctor [SERVICE ...] --json`：本机能否运行 deploy 的服务。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 1 |
| `deploy` | 字符串 | deploy 名称 |
| `ok` | 布尔 | 没有发现问题（退出状态 0） |
| `problems` | 列表 | 阻止运行的问题，每条一句话 |
| `notes` | 列表 | 运行时会自行处理的事（安装、复用端口），每条一句话 |
| `gpus` | 列表? | 本机的 GPU；`null` 表示没有找到 |
| `gpus[].index` | 整数 | GPU 编号 |
| `gpus[].name` | 字符串 | 型号 |
| `gpus[].used_gb` | 数 | 已用显存 |
| `gpus[].total_gb` | 数 | 显存 |
| `services` | 列表 | 检查的服务，即 `harness status --json` 的各行 |
| `installed` | 列表 | 服务，已安装或未安装 |
| `installed[].name` | 字符串 | 名称 |
| `installed[].what` | 字符串 | `service` |
| `installed[].installed` | 字符串 | `yes` 或 `no` |
| `installed[].environment` | 字符串，可选 | 它的环境目录，或它使用哪个解释器 |
| `installed[].environment_installed` | 布尔，可选 | 它的环境已安装 |
| `installed[].missing_files` | 列表，可选 | 仍缺少的权重、源码或资产 |
| `installed[].note` | 字符串，可选 | 为什么不需要安装（外部服务） |
| `packages` | 列表 | 已安装的扩展包，与 `harness list --json` 的行相同 |
| `packages[].name` | 字符串 | 扩展包名称 |
| `packages[].version` | 字符串 | 已安装的版本 |
| `packages[].scope` | 字符串 | `user`（你自己的）或 `project`（项目 harness.lock 里的） |
| `packages[].source` | 字符串 | 来源：`registry`、`registry:<address>`、`git:...`、`url:...`、`path:...`、`migrated:addons` |
| `packages[].path` | 字符串 | 安装后的文件夹 |
| `packages[].link` | 布尔 | 直接使用原位置的文件夹（`harness install --link`） |
| `packages[].enabled` | 布尔 | 运行时会用到它 |
| `packages[].trusted` | 布尔 | 允许它在这台电脑上运行代码 |
| `packages[].summary` | 字符串 | 一句话：它让 agent 能做什么 |
| `packages[].provides` | 对象 | 它提供的内容，按种类列出：`{"skills": [...], "embodiments": [...], ...}` |
| `packages[].problem` | 字符串，可选 | 它无法加载的原因 |
| `to_install` | 列表 | 运行前会先安装的东西（`harness install` 可以现在就装） |

## doctor EXPERIMENT

`harness doctor EXPERIMENT --json`（也可加 `--model`、`--set`、`--tasks`、`--seeds`、`--agent`、`--strict`、`--gpus`）：
本机能否按配置运行这个实验。`counts.missing` 不为 0 时退出状态为 1。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 1 |
| `experiment` | 字符串? | 实验文件；`null` 表示没有（只给了 `--tasks`） |
| `deploy` | 字符串 | deploy 名称 |
| `agent` | 字符串 | agent 名称 |
| `version` | 字符串 | harness 的版本 |
| `identity` | 字符串 | agent 的 identity，与 `harness run --dry-run` 报告的相同 |
| `model` | 字符串? | 主模型 |
| `bench` | 字符串 | benchmark |
| `tasks` | 列表 | 任务名 |
| `seeds` | 列表 | seed |
| `ok` | 布尔 | 没有缺失（退出状态 0） |
| `counts` | 对象 | 每种状态各有几项 |
| `counts.ready` | 整数 | 就绪 |
| `counts.will_install` | 整数 | 第一次运行时安装 |
| `counts.missing` | 整数 | 缺失 |
| `checks` | 列表 | 每项检查一行 |
| `checks[].check` | 字符串 | `python`、`skill`、`service`、`weights`、`benchmark`、`simulator`、`gpu` 或 `key` |
| `checks[].name` | 字符串 | 检查的对象：skill、服务、benchmark、GPU 编号或环境变量 |
| `checks[].status` | 字符串 | `ready`、`will_install` 或 `missing` |
| `checks[].detail` | 字符串 | 查到的情况；绝不包含 key 的值 |
| `checks[].fix` | 字符串，可选 | 补救的命令或设置（每个不是 ready 的项都有） |
| `skills_off` | 对象 | 配置关掉的 skill：名称 → 原因 |
| `gpus` | 列表? | 本机的 GPU；`null` 表示没有找到 |
| `gpus[].index` | 整数 | GPU 编号 |
| `gpus[].name` | 字符串 | 型号 |
| `gpus[].used_gb` | 数 | 已用显存 |
| `gpus[].total_gb` | 数 | 显存 |
| `to_install` | 列表 | 第一次运行时安装的东西（`harness install` 可以现在就装） |

## 其他 JSON 输出

以下命令在加 `--json` 时（或始终）输出 JSON，不带 `schema_version`：它们的结构随命令而定，不同版本之间可能改变。

| 命令 | 输出内容 |
| --- | --- |
| `harness list --json` | 每个已安装的包一行（`--available`：registry 中的每个包一行）；`harness list NAME --json` 输出一个包及它提供的内容 |
| `harness replay RUN --json` | 这次运行的 trace 记录，每条一个 JSON 行（[事件和 trace](/docs/zh-cn/reference/traces/)） |
| `harness library ls --json` | 每个库一行 |
| `harness library show LIBRARY --json`、`harness library show RUN --json` | 统一记忆格式的条目（`scope`、`kind`、`name`、`text`、`where`、`evidence`、`source`、`seen`、`version`、`cells`）：一个库的，或一次运行的记忆后接它的库的 |
| `harness config --json` | 解析后的 agent：`agent`、`agent_version`、`identity`、`main`、`runtime`、`placement`、`lock`；对实验还有它的任务、seed、layout 和 strict 设置 |
| `harness library show LIBRARY --json` | `{"directory", "version", "entries"}` |
| `harness config --json` | 解析后的 agent：`agent`、`version`、`identity`、`main`、`runtime`、`placement`、`lock`；对实验还有它的任务、seed、layout 和 strict 设置 |
| `harness services --json` | 每个服务一行：`service`、`kind`、`protocol`、`port`、`vram_gb`、`summary` |
| `harness up --json`、`harness status --json` | deploy 的每个服务一行：它在哪里运行，是否有响应 |
| `harness report RUNS --json` | 这些运行的 episode 的分数表 |
| `harness audit-run RUN --json` | 审计报告，与 `audit.json` 相同 |

## 错误

命令失败时向标准错误输出一行 JSON，并以非零状态退出。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `error` | 字符串 | 命令行有误时为 `usage: ...`（退出状态 2）；否则为错误的类型和消息，例如 `ValueError: limits.max_steps is between 1 and 1000`（退出状态 1） |

Ctrl-C 以退出状态 130 结束命令。
