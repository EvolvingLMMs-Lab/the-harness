---
title: "配置键"
---

英文参考由校验器使用的字典生成，中文版手动同步：文件中出现未列于此处的键会报错（开放的 `[runtime]` 除外）。路径相对于引用它的文件；文件可通过 `include` 引入其他文件（[配置运行](/docs/zh-cn/configure/configuration/)）。

<a id="the-agent"></a>

## Agent

`configs/default.toml`，以及任何包含它的 agent 文件

| 键 | 含义 |
| --- | --- |
| `description` | 一行说明，显示在 harness config 和运行查看器中 |
| `prompt` | 提示词：prompt pack 目录（按已启用的 skill 组装），或按顺序排列的文件；也可以按本体类型指定（robot = ...、desktop = ...） |
| `mode` | program（默认：模型编写程序）或 direct（每次调用执行一个动作） |
| `actions` | direct 模式：动作词汇表，"module:function"（text, allow_policy, allow_skills）-&gt; 一个 &lt;action&gt; 的程序；ValueError 说明该动作哪里不对 |
| `roles` | agent 使用的模型角色，可选 main、vlm、pointer、verifier（默认全部） |
| `skills` | layers = { learned, reactive, handlers }，或 names = [...]；enable = [...] 添加可选 skill，disable = [...] 移除 skill |
| `services` | segmenter、vision（vision skill 的通用感知）、policies = [...]、world_models = [...]、mcp = [...]（供 mcp skill 使用的 MCP 工具服务器）：skill 使用的服务 |
| `model` | 默认模型角色：模型文件名称（configs/models/&lt;name&gt;.toml），或内联角色配置 |
| `runtime` | 运行时设置：[runtime] 中的键 |
| `budget` | 每个 episode 的 max_model_calls（默认 30） |
| `desktop` | 计算机上的 agent（本体类型为 desktop 的 benchmark）：roles、skills、services、runtime 和 budget 覆盖上述设置（runtime 也覆盖模型文件中的设置） |
| `game` | 游戏中的 agent（本体类型为 game 的 benchmark）：roles、skills、services、runtime 和 budget 覆盖上述设置（runtime 也覆盖模型文件中的设置）；knowledge：agent 对这个游戏知道什么，"learned"（默认：不加载任何为它手写的 skill，连导入都不导入；它知道的都来自它的 library，runtime.library learn = "on" 时这个 library 会学习，runtime/learner.py）或 "handwritten"（可以加载参考基线为这个游戏手写的 skill） |

`[skills]`：`layers = { learned, reactive, handlers }`（默认 false、true、true），或 `names = [...]`；`disable = [...]` 移除 skill。`[services]`：`segmenter = "sam3"`、`policies = [...]`、`world_models = [...]`；每项为服务名称，或带有客户端覆盖键的 `{ service = "...", ... }`。`[budget]`：`max_model_calls`。

<a id="models"></a>

## 模型

`configs/models/<name>.toml`：每个角色一个表，另含 `[runtime]`（模型所需的设置，合并到 agent 配置中）和 `description`。

| 角色 | 用途 |
| --- | --- |
| `[main]` | 编写程序（direct 模式下则生成动作） |
| `[vlm]` | 在程序内回答图像问题（query_vlm），并在没有 pointer 时进行指点定位 |
| `[pointer]` | 开放词汇指点定位（point_to、localize） |
| `[verifier]` | 成功验证器相对于 main 的覆盖设置（verify、&lt;verify&gt;） |

<a id="keys-of-a-role"></a>

### 角色的配置键

| 键 | 含义 |
| --- | --- |
| `service` | 使用 deploy 中的服务替代托管模型：采用其客户端配置，再用本角色的键覆盖 |
| `backend` | openrouter（默认）或 openai_chat（任意兼容 OpenAI 的服务器） |
| `model` | 模型 ID |
| `base_url` | openai_chat：服务器 URL，例如 http://127.0.0.1:8800/v1 |
| `base_url_env` | openai_chat：存放服务器 URL 的环境变量；设置时覆盖 base_url |
| `api_key_env` | 存放密钥的环境变量（openrouter 默认使用 OPENROUTER_API_KEY） |
| `reasoning_effort` | openrouter：none、low、medium 或 high |
| `max_output_tokens` | 每次回复的 token 数，在 OpenRouter 上包含推理 token（默认 8192） |
| `max_tokens_key` | 该上限对应的请求字段（默认 max_tokens；OpenAI 较新的模型使用 max_completion_tokens） |
| `temperature` | 采样温度（默认采用供应商设置） |
| `stream` | 流式接收回复：模型思考时，失效连接会在读取超时内暴露 |
| `timeout_seconds` | 单次请求的读取超时（默认 300） |
| `retries` | 请求失败后的重试次数（默认 2） |
| `retry_seconds` | 从请求开始计时，在此时长内持续重试暂时性故障 |
| `extra_body` | 额外的请求字段（例如兼容 OpenAI 的服务器的 max_image_side） |
| `images` | 不能读图的模型写 false：不向它发送任何图像（默认：能读图） |
| `on_demand` | 解析按需服务时写入：broker 先启动该服务 |

<a id="runtime"></a>

## 运行时

agent 的 `[runtime]`（也可来自模型文件或实验覆盖项）。部分键由解析过程自行写入。

| 键 | 含义 |
| --- | --- |
| `agent_skills` | 应用：用户安装的 Agent Skills，格式为 {name: {description, path}}（skills/agent_skills） |
| `approvals` | {ask}，记录只询问敏感步骤还是每个程序。 |
| `bootstrap` | kernel 的会话工厂，格式为 "module:function"（默认使用程序运行时的工厂） |
| `cameras` | 由配置声明的持续画面：这些相机的图像随开场消息和每个程序的结果传给模型，如同评测的观测契约把它们交给策略。不写时模型每轮只收到文本，需要时自己看（look、watch） |
| `cell_timeout_seconds` | 单个程序的可选截止时间，受 episode 截止时间约束。 |
| `contract` | 观测契约（core/contract.py）：native（默认）、xpolicylab（机器人）或 screenshot（桌面） |
| `default_max_seconds` | 有界执行未指定 max_seconds 时采用的值 |
| `fixed_skills` | direct 模式：动作词表中的 locate、pick 和 place |
| `installed_skills` | 应用：用户安装的 Harness skill，按名称列出（提示词的 installed 区段，runtime/prompts.py） |
| `isolation` | 隔离运行程序（默认 true；"auto"：仅在用户命名空间可用时启用） |
| `keep_images` | 配合 runtime.cameras：在历史记录中保留最近多少轮的图像（默认 2）。不写 cameras 时，画面保留多久由模型说明（look(keep=)、pin=） |
| `viewer` | 由会话主机写入：主模型不能读图时，为它描述画面的模型角色（设置 model.vision）；没有时，这样的模型会被告知画面没有发送 |
| `knowledge` | 游戏知识："learned"（默认：agent 从空 library 开始学这个游戏；harness audit-run 会检查没有加载任何手写内容，benches/minecraft/audit.py）或 "handwritten"（可以加载参考基线手写的 skill、反射、读取器和库） |
| `label` | 运行查看器显示的配置名称 |
| `layers` | 由解析过程根据 [skills] layers 写入 |
| `library` | agent 学到的东西：[runtime.library] path = ...（相对路径，或 $HARNESS_HOME/ 下；layers = [...]）。uses = "learn"（默认：学习的运行把闭环的结果算作 library 条目的使用，runtime/memory.py）、"on"（冻结的 library 也算：练习）或 "off"。学习（runtime/learner.py）：learn = "off"（默认：冻结，和评测一样）或 "on"（运行中收下的条目在本次运行里就生效）；trigger = "passive"（执行任务的运行）或 "active"（学习环境的运行）；evidence = "test"（条目自带的测试在运行中就能把它收进来）或 "validated"（只有开发种子能收）；load = 条目被加载所需的最低证据档位（proposed、provisional、replayed、validated）；replay = true（每次运行开始时重测 provisional 条目）；reflect = true（每个 episode 结束后由反思提出一个条目）。主动学习的安排（runtime/active.py）：active_before = true（每个任务运行前先跑一次学习环境的运行），active_minutes = 1 到 240（那次运行的实机时间，默认 30） |
| `max_history_turns` | 首条消息之后最多保留的对话轮数 |
| `physical` | 本次运行在用户设置之上的物理输入策略（harness/physical.py）：{level, rules}；harness run EXPERIMENT 根据 --physical、--allow-app、--deny-app、--ask-app 设置它 |
| `privacy` | 本次运行中模型能知道用户哪些窗口的信息，在用户设置之上（harness/privacy.py）：{level, rules}；harness run EXPERIMENT 根据 --window-details 设置级别 |
| `max_wait_seconds` | 兼容旧配置。用显式超时限制程序等待。 |
| `mcp` | 由解析过程写入：MCP 服务器的客户端配置 |
| `actions` | 由解析过程写入：direct 模式的动作词汇表（agent 的 actions） |
| `mode` | 由解析过程根据 agent 的 mode 写入 |
| `observer` | 显式参考观察的设置，控制画面尺寸、推理强度和最大输出。调用与其他模型请求共用 Thought 队列。 |
| `pointer` | 由解析过程写入：pointer 角色的客户端配置 |
| `policies` | 由解析过程写入：学习型策略的客户端配置 |
| `policy_progress_seconds` | 学习型策略运行时，若上次 locate 跟踪的所有物体在此秒数内均未移动 3 cm，也会结束运行；每半个窗口测量一次（默认无：仅在停滞时结束） |
| `post_policy_calls` | 使用学习型策略时：交出的任务首次运行后的模型调用次数，随后策略运行至 episode 结束（0：立即继续运行；默认无：不限制） |
| `python` | kernel 的解释器（默认与对话相同） |
| `reaction_delay_ms` | 从观测到据此决定的动作之间的时间，向上取整到整数个控制周期（runtime/tick.py）：开发和练习用 0（默认）；完整的游戏通关或录制 demo 用 150-200，即人的反应时间 |
| `reactive_budget_ms` | 每个控制周期内反应回调共用的时间（默认 5 毫秒） |
| `sandbox` | 只由 `harness run` 为主动运行写入：benchmark 的 [sandbox]（runtime/active.py），即它的 kernel 拿到的练习沙盒；任务运行从来没有 |
| `segmenter` | 由解析过程写入：分割器的客户端配置 |
| `vision` | 由解析过程写入：vision 服务的客户端配置 |
| `skills` | 由解析过程写入：已启用的 skill |
| `skills_dropped` | 由解析过程写入：被排除的 skill 及原因 |
| `strategy_first` | 使用学习型策略时：调用 start(strategy, kind) 前禁止运动（默认 false；由 agent 设置） |
| `strict_skills` | 在代码中构建、未列出 skill 的配置：缺少 skill 时失败，而非将其移除（resolve_for） |
| `task_descriptions` | 加入首条消息的任务描述目录（&lt;task&gt;.md），或 false |
| `think_interval` | 兼容旧配置。决策由事件触发。 |
| `think_while_acting` | 长程序运行期间可提前准备一次后续决策。默认开启，off 关闭前瞻。旧配置的 on_events 和 periodic 等同于 on。 |
| `thinking` | 主模型每次调用能想多久（runtime/conversation.py THINKING）：model（代码默认：用模型自己的设置）、none（关闭推理，回复最多 2000 token，并告诉模型简短思考）、low（推理强度最多 low，2000 token，提示相同）、medium（最多 medium，8000 token）或 high；模型本身设得更低就保留它自己的。agent 在游戏上用 low |
| `verifier` | 结束前用验证器检查成功与否（默认 true） |
| `vlm` | 由解析过程写入：vlm 角色的客户端配置 |
| `world_models` | 由解析过程写入：世界模型的客户端配置 |

<a id="experiments"></a>

## 实验

`configs/experiments/<name>.toml`

| 键 | 含义 |
| --- | --- |
| `description` | 一行说明 |
| `agent` | agent 文件（默认 configs/default.toml） |
| `model` | 模型角色：configs/models/ 中的名称（默认使用 agent 的设置） |
| `bench` | benches/&lt;name&gt;/bench.toml 定义的 benchmark（默认 robodojo） |
| `tasks` | benchmark 的任务，按其 bench.toml 中的 `tasks` 说明指定（RoboDojo：任务名、维度名、"moving"、"all"） |
| `seeds` | 列表，或 "0-49" 这样的范围（默认 [0]） |
| `layouts` | procedural 或 eval：开发 layout 或官方评测 layout |
| `layout_pack_seed` | eval layout：使用哪个官方评测包（0、1、2） |
| `dev_layout_dir` | 开发 layout 目录（默认 &lt;RoboDojo&gt;/harness_dev_layouts/arx_x5） |
| `deploy` | 用于解析的 deploy（否则使用 --deploy 或 $HARNESS_DEPLOY） |
| `strict` | 缺少 skill 或服务时失败，而非将其移除（eval layout 默认为 true） |
| `endpoint` | `harness program`：已运行的 worker |
| `timeout_seconds` | worker 请求超时（默认 600） |
| `budget` | 每个 episode 的 max_wall_seconds、max_cost_usd、max_model_calls；每个 suite 的 max_total_cost_usd |
| `worker` | benchmark 的 worker 选项：其 bench.toml [worker] 中的键 |
| `suite` | `harness run` 的选项（boot_timeout 等） |
| `overrides` | [overrides.agent] 和 [overrides.model]：仅对本实验生效的修改 |

<a id="deploys"></a>

## Deploy 文件

`configs/deploy/<machine>.toml`

| 键 | 含义 |
| --- | --- |
| `weights` | 服务权重目录的根路径（相对于此文件或使用绝对路径；默认 ~/.cache/harness/weights） |
| `state` | 所启动服务的 pid 文件和日志（默认 ~/.cache/harness/services） |
| `robodojo` | RoboDojo 源码目录（默认 $HARNESS_ROBODOJO_ROOT，其次为本仓库的 third_party/RoboDojo，再其次为 `harness install robodojo` 安装在 ~/.cache/harness 下的目录） |
| `xpolicylab` | XPolicyLab 源码目录（默认 &lt;robodojo&gt;/XPolicyLab） |
| `gpus` | 服务和模拟器可使用的 GPU |
| `gpu_memory_gb` | 每张 GPU 的显存（默认 24）；gpu = "auto" 据此规划 |
| `sim` | `harness run` 的模拟器 worker：gpus、workers_per_gpu、base_port |
| `benches` | [benches.&lt;name&gt;]：benchmark 在本机的设置，键来自其 bench.toml 的 `deploy`（OS-Omni：checkout、python、base_port、machines） |
| `services` | 本机运行的每个服务对应一个 [services.&lt;name&gt;]；未列出的服务关闭 |
| `broker_port` | 按需服务 broker 的监听位置（默认 8899） |
| `environments` | own（默认：每个服务和 benchmark 使用独立环境，首次使用时安装）或 project（全部使用 harness 自身的解释器，即源码目录的开发环境） |
| `reserved` | 按 GPU 编号记录已占用显存，单位 GB（"0" = 9.0）：放置时预留此空间（harness 的放置过程会在此写入模拟器和其他进程的显存占用） |

<a id="placement-of-a-service"></a>

### 服务的放置

deploy 文件中的 `[services.<name>]`。

| 键 | 含义 |
| --- | --- |
| `mode` | resident、on_demand、external 或 off（默认 resident） |
| `gpu` | GPU 编号，或 "auto"：选择对其 vram_gb 而言剩余空间最多的 GPU |
| `port` | 使用不同于清单的端口 |
| `url` | external 模式：服务地址 |
| `python` | 为它指定其他解释器 |
| `env` | 额外环境变量 |
| `swap` | on_demand：swap group；同组服务共享一张 GPU，每次仅加载一个 |
| `idle_seconds` | on_demand：连续这么长时间没有请求后停止服务 |

<a id="service-manifests"></a>

## 服务清单

`services/<name>.toml`

| 键 | 含义 |
| --- | --- |
| `kind` | 服务用途：segmenter、vision、pointer、vlm、llm、policy、world_model、kinematics 或 mcp |
| `summary` | 一行说明：模型及其来源 |
| `protocol` | 客户端通信方式：http、openai_chat、xpolicylab 或 mcp（默认 http） |
| `port` | 默认端口（deploy 可另行指定） |
| `vram_gb` | 实测 GPU 显存占用；用于放置和换入换出 |
| `load_seconds` | 启动后到可响应所需的时间（等待允许其三倍时间） |
| `command` | 启动 argv，支持 {python} {port} {weights} {repo} {robodojo} {xpolicylab} 等占位符（xpolicylab 协议下可选，用于替代 XPolicyLab 的 setup_policy_server.py） |
| `xpolicylab` | xpolicylab 协议：policy folder、ckpt_name、action_type（joint，或 ee：由 run_policy 通过 IK 求解的 link6 位姿）、action_dim、cwd、pythonpath、overrides |
| `env` | 进程的环境变量 |
| `python` | 解释器（默认 {python}：所属环境的解释器） |
| `environment` | 运行环境，首次需要时安装：包含 python、requirements、sources 等下述键的 [environment]，或与之共享环境的服务或 benchmark 名称 |
| `cwd` | 工作目录（默认 {repo}） |
| `client` | 提供给使用者的配置：url = "{url}"，以及模型可见的服务说明（description） |
| `weights` | [[weights]] 条目：deploy 权重根目录下的 dir 和一个来源（modelscope_model、modelscope_dataset、hf_model、hf_dataset、local），支持 include/exclude glob、数据集的 root，以及 parallel（同时下载的文件数，适合大量小文件）；随服务下载 |
| `needs_files` | 启动前必须存在的路径（由 harness doctor 和 up 检查） |
| `notes` | 运维人员需要了解的事项 |

<a id="environments"></a>

### 环境

服务清单或 benchmark 中的 `[environment]`：其运行环境，首次需要时安装到 `~/.cache/harness/envs/<name>/<hash>/`（[服务与环境](/docs/zh-cn/configure/services/)）。

| 键 | 含义 |
| --- | --- |
| `python` | Python 版本，例如 "3.11" |
| `requirements` | 固定版本的依赖，使用 pip 语法（"-r FILE" 指定某个源码中的文件） |
| `indexes` | 默认索引之外的软件包索引（例如 PyTorch 的 CUDA wheel） |
| `constraints` | 该环境每次安装都遵守的固定版本：harness 中的文件（environment/lock/pip-freeze.txt）或列表 |
| `sources` | 固定 commit 的源码及其安装方式：[{ source or repo + rev, nested, install, subdirectory, no_deps, flags }] |
| `commands` | 安装后按顺序执行的命令：argv 列表，或 { run, env, cwd }（会填入 {python}、{env}、{root}、{home} 及 {robodojo} 等源码路径） |
| `env` | 安装和命令使用的环境变量 |
| `overrides` | 优先于软件包声明的版本（如 isaacsim-kernel 的 websockets==12.0 与 17.1 冲突）：不加入约束，在安装后强制应用 |
| `imports` | 安装完成后必须可导入的模块（用于检查） |

<a id="sources"></a>

### 源码

环境 `sources` 中的一个条目：固定 commit 的源码，在 `~/.cache/harness/sources/` 下共享。

| 键 | 含义 |
| --- | --- |
| `source` | third_party/sources.toml 中的一个源码项（其 URL、revision 和嵌套源码） |
| `repo` | 或一个 git URL…… |
| `rev` | ……以及要检出的完整 commit |
| `nested` | 按 sources.toml 指定的 revision 获取的嵌套源码（默认无） |
| `install` | none（默认：仅检出）、editable 或 package |
| `subdirectory` | 安装源码中此子目录的内容 |
| `no_deps` | 安装时不安装依赖（依赖已列于 requirements） |
| `flags` | 其他 pip 参数，例如 --no-build-isolation |

<a id="skills"></a>

## Skill

`skills/<name>/skill.toml`

| 键 | 含义 |
| --- | --- |
| `name` | skill 名称，与目录名相同 |
| `summary` | 一行说明：skill 为程序提供的能力 |
| `layer` | base，或启用它的接口层：learned、reactive 或 handlers |
| `mixin` | 包含其方法的类，格式为 "module:Class"（例如 "skills.motion:Motion"） |
| `exports` | 程序可见的名称：mixin 的方法，或 exports(session) 返回的名称 |
| `interface` | 按本体覆盖 summary、mixin 和 exports |
| `required` | 永不移除：会话缺少它就无法运行（core） |
| `needs` | 必须全部可用的服务类型 |
| `needs_any` | 至少有一种可用即可的服务类型 |
| `requires` | 本 skill 的结果或文档所引用 API 所属的 skill；这些 skill 被移除时，本 skill 也会移除 |
| `conflicts` | 不能同时启用的 skill：它们导出了部分相同名称 |
| `optional` | 不随所属层启用：只有配置明确按名称启用时才提供 |
| `order` | 在会话方法解析和提示词中的顺序（数值较小者优先） |
| `embodiments` | 可运行的本体类型，选自 robot、desktop、game（默认 ["robot"]） |
| `requirements` | 用户安装的 skill：pip 依赖，安装到它自己的 .deps 目录 |
| `knowledge` | "handwritten"：为某个游戏手写的知识；agent 自己学这个游戏时（game.knowledge = "learned"）不给，连导入都不导入 |
| `probe` | 一个表：这个 skill 是其本体的 probe，学习环境的运行会启用它（runtime/active.py）；它导出 probe 和 probe_summary，表中的键是这种运行针对此本体的几行说明：try（probe() 测量什么）、skills（要写的基本 skill）和 drills（练习结果如何检查） |

<a id="benches"></a>

## Benchmark

`benches/<name>/bench.toml`（harness.bench），以及各 benchmark 接受的设置

| 键 | 含义 |
| --- | --- |
| `name` | benchmark 名称，与目录名相同（实验的 `bench`） |
| `summary` | 一行说明：benchmark 的内容 |
| `kind` | worker 驱动的本体类型（embodiments.KINDS） |
| `embodiment` | 用于观测契约的 embodiments/&lt;name&gt;（可选：未指定时仅支持 native 契约） |
| `factory` | worker 的环境工厂，格式为 "module:callable"（`python -m harness.core.worker --factory`） |
| `hooks` | 包含钩子的 Bench 子类，格式为 "module:Class"（默认 Bench） |
| `worker` | 接受的实验 [worker] 键：{key = "what it does"} |
| `environment` | worker 和 kernel 的运行环境，首次使用时安装（[environment] 的键） |
| `notes` | 运维人员需要了解的事项 |
| `sandbox` | 学习的主动运行的练习沙盒（runtime/active.py），任务运行从来没有：`what`（它是什么，给模型看）和 [sandbox.ops] {op = "它布置什么"}；没有 ops 就是没有沙盒（`what` 说明原因） |

<a id="run-as-a-benchmark"></a>

### 作为 benchmark 运行

bench.toml 中由 eval 包读取的键（harness_eval.bench）：把一个 bench 作为 benchmark 运行所需的内容

| 键 | 含义 |
| --- | --- |
| `tasks` | 用文字说明实验 `tasks` 条目的可选内容（供文档使用） |
| `deploy` | deploy 的 [benches.&lt;name&gt;] 表中的键：{key = "what it is"} |
| `source` | 首次使用时安装的源码：third_party/sources.toml 中的一项（deploy 的 robodojo 或 $HARNESS_&lt;NAME&gt;_ROOT 可替换为你自己的源码目录） |
| `nested` | 所需的嵌套源码 |
| `assets` | [[assets]] 条目与服务的 [[weights]] 相同，dir 位于源码目录下：安装时下载 |
| `needs_files` | 安装完成后必须存在的路径（{checkout}/...） |

### browser

在独立的无界面 Chrome 中搜索和浏览，不控制用户桌面。类型 `desktop`，本体 `computer`。
任务："free" 为用户提供的网页任务。

实验 `[worker]`：

| 键 | 含义 |
| --- | --- |
| `instruction` | 对话未提供指令时使用的任务 |
| `max_side` | 截图宽度上限；浏览器视口最多 1440 像素宽（默认 1920） |
| `step_limit` | 每个对话的浏览器输入步数上限（默认 300） |
| `settle_seconds` | 输入之后等待的秒数（默认 0.2） |
| `locale` | 向网站请求的语言，写成 en-US 这样的标签（navigator.language、Accept-Language、日期和数字；默认 system：本机的语言） |

### computer

本机：agent 在 worker 所在机器的桌面上执行你给出的任务。类型 `desktop`，本体 `computer`。任务："free" 表示无 benchmark 任务；指令由你提供（worker 的 `instruction`，或交互对话中的指令）。

实验 `[worker]`：

| 键 | 含义 |
| --- | --- |
| `instruction` | 对话中未给出任务时使用的任务（默认询问用户要做什么） |
| `monitor` | 开始时用哪块显示器：1 为主显示器（采用 mss 编号） |
| `follow` | 有多块显示器时，显示当前窗口所在的那块（默认 true） |
| `max_side` | 截图和命令坐标按比例缩放，使长边不超过此像素数（默认 1920） |
| `settle_seconds` | 输入一步后等待屏幕稳定的秒数（默认 0.5） |
| `step_limit` | 一个 episode 允许的输入步数（默认 300） |
| `image_format` | 截图格式为 "jpeg"（默认）或 "png" |
| `shield` | 桌面安全层的边界，覆盖本体设置 |
| `workspace` | "desktop"（默认：整个屏幕）、"apps"：一次一个窗口，在后台操作（Windows、macOS；X11 上的 Linux），或 "display"：独立显示屏，从不碰用户的屏幕（Linux 上是显示服务器；Windows 和 macOS 上是虚拟机） |
| `display_size` | 独立显示屏的尺寸，"宽x高"（默认 1280x800） |
| `display_backend` | 独立显示屏用什么："auto"（Linux 用显示服务器，Windows 和 macOS 用虚拟机）、"local" 或 "vm"（默认：设置 computer.display_backend） |
| `vm` | 独立显示屏的虚拟机：设置 computer.vm_* 的键（vm_image、vm_hypervisor、vm_memory、vm_cpus、vm_accel、vm_user），覆盖 app 的设置 |

### fakegame

一个从画面来玩的编出来的游戏（第一人称视角或横版平台跳跃），用来在没有真实游戏时开发学习功能。Kind `game`，embodiment `fakegame`。任务："fps"：在第一人称视角里走到红旗那里；"platformer"：走到横版关卡右端的旗子；前面加上 "practice"（"practice-fps"）：同一个世界，旗子更近。

实验的 `[worker]`：

| 键 | 含义 |
|---|---|
| `latency` | 从输入到显示它的那一帧之间的帧数（默认 2） |
| `ambient` | 自己会动的世界：飘动的云和闪烁的水塘（默认 false） |

### fakerobot

一对编出来的手臂，有一个头部相机和每只手上各一个相机，由 numpy 画出，用来在没有模拟器时开发机器人上的学习功能。Kind `robot`，embodiment `fakerobot`。任务："pick"：举起红色方块；"place"：把红色方块放到绿色方格上。

实验的 `[worker]`：

| 键 | 含义 |
|---|---|
| `shield` | 覆盖本体设置的机器人 shield 设置（max_joint_jump_rad、max_cartesian_jump_m、workspace） |

### minecraft

本机上的 Minecraft Java 1.16.1：agent 从 harness 自己实例的窗口像素出发，用键盘和鼠标游玩，遵守 MCSR 速通规则。类型 `game`，本体 `minecraft`。任务："rsg" 为随机种子的 Any% Glitchless，从新世界开始直到进入末地返回传送门；"free" 为无任务，指令由你提供；"s1" ... "s9" 为全程的练习分段（木头和石器、铁、传送门、堡垒遗迹的珍珠、要塞的烈焰棒、回到要塞环、扔眼、传送门房间、打龙），每段在开发实例的世界里用命令设好起点，由游戏计分（benches/minecraft/practice.py）。

实验 `[worker]`：

| 键 | 含义 |
| --- | --- |
| `instruction` | 任务指令，替换 bench 自带的指令（"free"：询问用户） |
| `step_limit` | 一个 episode 允许的输入数（默认 100000） |
| `image_format` | 画面格式为 "png"（默认）或 "jpeg" |
| `launch` | worker 启动时若没有游戏窗口，就启动实例（默认 true） |
| `world_timeout` | new_world() 等待世界加载的秒数（默认 120） |
| `fairness` | 公平上限的档位，"off"、"human" 或 "strict"（默认用本体的：human） |
| `see` | knowledge = "handwritten" 时：把世界画面里读出的线索放进状态（see.py：前方的岩浆和火；默认 true） |
| `keep_inventory` | 练习分段：玩家死亡时保留身上的东西（默认 false，与正式全程一样） |
| `anonymous` | 练习分段：指令里不说出游戏的名字（也不提 F3），就像玩家不知道自己拿到的是什么游戏；目标里的物品名照常保留（默认 false：说出游戏名，就像玩家知道自己买的是什么） |
| `vision` | 对每一帧运行视觉模型，结果放进状态的 see["vision"]（vision/model.py）：true 表示用 release 的权重（第一次使用时下载：python -m minecraft_reference.vision.model install），或给一个 ONNX 文件的路径（默认 false） |
| `knowledge` | agent 对这个游戏知道什么："learned"（默认：worker 不替它读任何游戏内容，也不导入这些读取器：agent 只从像素学这个游戏）或 "handwritten"（minecraft-reference 包的基线：worker 替它读 HUD 和 F3、画面线索、视觉模型和世界记忆的 Minecraft 类别） |
| `perception` | 旧选项。通过 knowledge = handwritten 与 vision 选择参考感知。 |

### osomni

OS-Omni Live v1 的 Linux 桌面和 Web 任务，在 Ubuntu VM 上运行，每台 VM 一个 worker。类型 `desktop`，本体 `ubuntu`。任务：任务 ID、任务类别（"linux"、"web"）或 "all"；procedural layout 使用开发任务，eval 使用保留评测任务（benches/osomni/tasks.py）。

实验 `[worker]`：

| 键 | 含义 |
| --- | --- |
| `snapshot` | 每个 episode 开始时恢复的 VM 快照（os_omni_v3_ready） |
| `capture_end_state` | 归档 episode 修改的虚拟机文件（end_state.tar.gz） |
| `max_steps_cap` | 将任务步数上限限制为最多此输入步数 |
| `report_step_limit` | 告知 agent 步数上限（OS-Omni 的 agent 不会获知；默认 false） |
| `settle_seconds` | 输入一步后等待屏幕稳定的秒数（默认 0.3） |
| `shield` | 桌面安全层的边界，覆盖本体设置 |

Deploy `[benches.osomni]`：

| 键 | 含义 |
| --- | --- |
| `checkout` | OS-Omni 源码目录（默认 $HARNESS_OSOMNI_ROOT，否则使用 third_party/OS-Omni） |
| `python` | 运行 worker 的 OS-Omni 环境解释器 |
| `base_port` | 第一个 worker 的端口（默认 8790） |
| `machines` | VM 列表，每台对应一个 worker：[{ runtime_url, qmp_socket }] |

### osworld

OSWorld 的 Ubuntu 任务（test_nogdrive），在 OSWorld 的 docker VM 上运行，每台 VM 一个 worker。类型 `desktop`，本体 `osworld`。任务："all"、领域（"chrome"、"os" 等）或 "<领域>.<id>"；procedural layout 使用开发任务，eval 使用保留评测任务（benches/osworld/tasks.py）。

实验 `[worker]`：

| 键 | 含义 |
| --- | --- |
| `max_steps_cap` | episode 的输入步数最多为此值（OSWorld 的步数上限按其 agent 的模型回复计数，与预算的 max_model_calls 对应） |
| `settle_seconds` | 输入一步后等待屏幕稳定的秒数（默认 0.3） |
| `ready_seconds` | 任务初始化后、第一张截图前等待 VM 稳定的秒数（默认 60，与 OSWorld 的运行器一致） |
| `evaluate_delay_seconds` | 评测器运行前等待的秒数（默认 20，与 OSWorld 的运行器一致） |
| `shield` | 桌面安全层的边界，覆盖本体设置 |

Deploy `[benches.osworld]`：

| 键 | 含义 |
| --- | --- |
| `checkout` | OSWorld 源码目录（默认 $HARNESS_OSWORLD_ROOT，否则使用 third_party/OSWorld） |
| `python` | 运行 worker 的 OSWorld 环境解释器 |
| `vm` | docker provider 以只读方式启动的 VM 镜像（Ubuntu.qcow2） |
| `vms` | 同时运行的 VM 数，每台对应一个 worker（默认 1） |
| `base_port` | 第一个 worker 的端口（默认 8890） |

### robodojo

RoboDojo 在双臂 ARX X5（Isaac Lab）上的 42 个任务，每个 worker 在一张 GPU 上运行一个任务。类型 `robot`，本体 `arx_x5`。任务：任务名、维度名（Memory 等）、"moving"（移动目标任务）或 "all"。

实验 `[worker]`：

| 键 | 含义 |
| --- | --- |
| `record_video` | 在每个 episode 的 videos/ 中为每个相机保存一个 MP4（默认 false） |
| `ground_truth` | 将模拟器中的物体位姿写入 truth/&lt;task&gt;.jsonl，仅供分析（默认 false） |
| `shield` | 运动安全层的限制，覆盖本体设置 |

### robotwin

RoboTwin 2.0 在双臂 Aloha-AgileX（SAPIEN）上的 50 个任务，每个 worker 在一张 GPU 上运行一个任务。类型 `robot`。任务：任务名或 "all"（其 50 个任务，取自官方各任务的步数上限）。

实验 `[worker]`：

| 键 | 含义 |
| --- | --- |
| `task_config` | RoboTwin 的任务配置（默认 demo_randomized） |
| `seed_cache_dir` | 有效 seed 的缓存位置（默认 &lt;RoboTwin&gt;/harness_seeds） |

<a id="prompt-packs"></a>

## Prompt pack

`prompts/<pack>/pack.toml`。只有 `<!-- if: a, b -->` 标记指定的每个 skill 或特性都启用时，才保留该区段内的文本（`<!-- else -->`、`<!-- end -->`；标记可嵌套）。特性：`measured_gripper`、`step_limit`、`channels`、`think_while_acting`、`vision_service`。

| 键 | 含义 |
| --- | --- |
| `sections` | 按顺序列出的 pack 文件：{ file, skills = [...]（其中任一 skill 启用时包含）, optional = true（允许缺失） } |
| `undocumented` | pack 未说明的导出名称（文档检查跳过它们） |
