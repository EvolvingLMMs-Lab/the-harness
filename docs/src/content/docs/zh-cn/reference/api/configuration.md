---
title: "配置"
---

## `harness.config`

配置：可包含其他文件的 TOML 文件，路径相对于引用它的文件，支持 `--set key.path=value` 覆盖。

配置层，后者优先（configs/README.md）：

    code defaults            the values the code uses when a file names none
    default.toml             the agent: prompt, skills, services, runtime, budget, and
                             its default model (other agent files may include it)
    models/&lt;name&gt;.toml       model roles: main, vlm, pointer, verifier (an API model or a
                             service), plus the runtime settings a model needs
    experiments/&lt;name&gt;.toml  the agent with a model on a benchmark: tasks, seeds,
                             layouts, budgets, worker options, overrides
    --model, --set           the command line

configs/deploy/&lt;machine&gt;.toml 指定服务运行位置（local-models 包）。密钥保存在环境变量中，不写入这些文件。

### `read_toml`

```python
def read_toml(path: Path) -> dict
```

将单个 TOML 文件读取为配置树，不加载 include 引用的文件。

### `deep_merge`

```python
def deep_merge(base: dict, override: dict) -> dict
```

用 `override` 覆盖 `base`：表按键合并，其他值直接替换。

### `load_layered`

```python
def load_layered(path, _seen=()) -> dict
```

读取 TOML 文件，先按顺序合并 `include = [...]` 引用的文件，再用当前文件中的配置覆盖合并结果；路径配置统一转为绝对路径。

### `parse_set`

```python
def parse_set(text: str) -> tuple[list[str], object]
```

将 `a.b.c=value` 解析为 (["a", "b", "c"], value)；值按 TOML 读取（数字、true、"text"、[1, 2]、{k = 1}），无效 TOML 则作为普通字符串。

### `apply_sets`

```python
def apply_sets(tree: dict, sets) -> dict
```

返回 `tree` 的副本，按顺序写入 `--set` 条目。条目可为 `key.path=value` 字符串或已解析的 (keys, value) 对；路径中缺少的表会创建，如果路径经过的节点不是表，则报错。

### `route_openrouter`

```python
def route_openrouter(tree, environ=os.environ)
```

按需将 harness 中所有 OpenRouter 模型指向另一个基础 URL。

适用于 `backend = "openrouter"` 且未设 `base_url`（即默认 openrouter.ai），或 `base_url` 指向 openrouter.ai 的每个模型配置：

- OPENROUTER_BASE_URL（如 https://my-proxy.example/api/v1）替换 URL；
  密钥仍从模型的 `api_key_env`（OPENROUTER_API_KEY）读取。
- OPENROUTER_RELAY_URL 将 URL 替换为 scripts/openrouter_relay.py 的地址，并
  从 OPENROUTER_RELAY_TOKEN 读取密钥。

同时设置两者会报错。自托管服务器和其他供应商的模型配置不受影响。改写后的配置进入运行快照，因此每次运行都会记录实际调用的 URL。

### `dumps`

```python
def dumps(data: dict, comment: str='') -> str
```

把一棵树写成 TOML 文件：先写值，再写表，表的列表写成 [[...]]；None 不写（TOML 没有 null）。这是唯一的 TOML 写入器：用户配置、包列表与锁文件、模型文件和选项文件都用它。

### `toml_key`

```python
def toml_key(name) -> str
```

一个键的 TOML 写法：能用裸键时用裸键，否则加引号。

### `toml_value`

```python
def toml_value(value) -> str
```

一个值的 TOML 写法（内联表和数组，其中的 None 不写）。

## `harness.config.agent`

agent 配置：针对一台机器解析的评测对象。

只有一个 agent：configs/default.toml。它指定 prompt pack、skill（按接口层或名称）、skill 所需服务（分割器、策略、世界模型）、运行时设置、预算和默认模型角色。其他 agent 文件可包含它并修改部分键；实验可覆盖任意键。

模型角色来自 configs/models/&lt;name&gt;.toml 模型文件（agent 的 `model`、实验的 `model` 或 `--model NAME`）：

    [main]                          the model that writes programs
    backend = "openrouter"
    model = "x-ai/grok-4.7"
    [vlm]                           questions about images (and pointing without a pointer)
    service = "qwen3-vl-8b"         a role may be a service of the deploy ...
    timeout_seconds = 300           ... with its own settings on top
    [pointer]
    service = "molmo2"
    [verifier]                      overrides on top of main (the success verifier)
    [runtime]                       settings the model needs (context window, ...)

针对 deploy 解析 agent，得到对话的主模型、运行时、提示词和 lock：lock 包含所有决定运行计算结果的内容，不包含运行位置（URL、GPU、端口）。lock 记录 agent 的 VERSION，其哈希即配置的 identity；结果和导出的 XPolicyLab 策略都会注明它。

### `ResolvedAgent`

```python
class ResolvedAgent
```

针对一个 deploy 解析的 agent：对话的主模型、验证器、运行时和提示词，episode 的模型调用预算，以及 lock 和 identity（lock 的 sha256 前 16 个十六进制字符）。`base_prompt` 是未加入自改进库内容的提示词。

### `TaskConfig`

```python
class TaskConfig
```

单个任务的配置：worker endpoint、主模型和验证器、运行时设置、提示词、seed 和每个 episode 的预算。task_config 从已解析的 agent 构建此配置；对话运行它。

#### `snapshot`

```python
def snapshot() -> dict
```

episode 清单和 experiment.json 中记录的配置（除 `path` 和 `base_prompt` 外的全部内容；lock 记为 `agent_lock`；仅本体类型不是默认 robot 时记录，以保持机器人记录兼容）。

### `model_services`

```python
def model_services(runtime: dict, roles: dict) -> dict
```

kernel 中 skill 调用的模型和服务器：VLM、pointer、分割器、vision、策略、世界模型，以及成功验证器（模型 `roles` 的 {**main, **verifier}；直接控制模式无验证器）。

### `image_roles`

```python
def image_roles(services: dict) -> dict
```

`services`（model_services）中回答图像问题的模型角色（vlm、pointer、verifier），各自带上向它们提问的类（由某个包的 host 模块给出：perception 的 vision_model），episode 在 kernel 中构建它们；没有这样的包时为 None。

### `resolve_for`

```python
def resolve_for(runtime: dict, roles: dict, embodiment: str='robot') -> Resolution
```

按此运行时配置运行时（对话的运行、eval 包的运行）启用的 skill：resolve_agent 解析出的 `runtime.skills`；在代码中构建、没有这一项的配置，则取其接口层的 skill（runtime.layers 覆盖 LAYER_DEFAULTS）中能以其服务和模型 `roles`（{"main", "verifier"}）在该本体类型上运行的，runtime.strict_skills 使被移除的 skill 成为错误。

### `model_names`

```python
def model_names() -> list[str]
```

按名称列出 configs/models/ 中的模型文件。

### `config_keys`

```python
def config_keys() -> dict
```

agent 的 [runtime] 键及各自的作用：RUNTIME_KEYS，以及扩展包在各自 config_keys.toml 里说明的键（"runtime.<key>" = "它做什么"）。

### `agent_file`

```python
def agent_file(value) -> Path
```

agent 文件：一个路径，或者某个 profile 的名字（核心或扩展包里的 configs/profiles/&lt;name&gt;.toml，例如 robodojo）。

### `model_path`

```python
def model_path(name) -> Path
```

模型文件：configs/models/ 中的名称，或 .toml 文件路径。

### `load_model`

```python
def load_model(source) -> dict
```

模型角色：模型文件名或路径（含 include），原样使用的树，或 None 对应的 {}。

### `resolve_agent`

```python
def resolve_agent(agent=None, *, model=None, deploy=None, strict: bool=False, name: str | None=None, runtime_overrides: dict | None=None, embodiment: str='robot', channels: bool=False, package_paths=(), frozen_identity: bool=False) -> ResolvedAgent
```

针对 `deploy`（Deploy、名称，或 None 表示 $HARNESS_DEPLOY）和本体类型（benchmark 的类型，决定 skill 和提示词），解析 agent（路径或已合并的树；默认 configs/default.toml），模型角色来自 `model`（模型名、路径或树；默认 agent 自身的 `model`）。

strict：agent 指定但无法在本机运行的服务或 skill 会报错，而非被排除。runtime_overrides（实验对 agent 的修改）在模型文件的运行时设置之后应用。channels：benchmark 的本体声明了通道（提示词的 `channels` 特性）。

### `package_lock`

```python
def package_lock(used=()) -> dict
```

根据 `used` 中的路径选取实际使用的包及依赖。当前进程使用的扩展包的 {name: version}（paths.packages()）：lock 的一部分。

### `package_content`

```python
def package_content(root: Path) -> str
```

计算本地包的文件路径和内容摘要，跳过依赖目录及缓存。

### `overridden_agent`

```python
def overridden_agent(overrides: dict | None=None, *, agent=None, model=None, deploy=None, strict: bool=False, embodiment: str='robot', channels: bool=False, package_paths=(), frozen_identity: bool=False) -> ResolvedAgent
```

agent 文件（默认 configs/default.toml）应用 `overrides`（{"agent": ..., "model": ...}，实验或对话做的修改）之后、模型角色取自 `model`（默认 agent 自己的）、针对 `deploy` 解析的结果（resolve_agent）。

### `task_description`

```python
def task_description(runtime: dict, task: str) -> str
```

agent 使用任务描述时，返回该任务的描述（RoboDojo wiki 配方）。

### `task_config`

```python
def task_config(agent: ResolvedAgent, task: str, seeds, *, budget: dict | None=None, endpoint: str | None=None, timeout_seconds: float=600.0, path: Path | None=None)
```

已解析的 agent 在 `task` 上用 `seeds` 运行时的配置（TaskConfig），受每个 episode 的 `budget`（max_model_calls、max_wall_seconds、max_cost_usd）约束，连接位于 `endpoint` 的 worker。

## `harness_eval.experiments`

实验：configs/experiments/&lt;name&gt;.toml 描述的、在 benchmark 上配合某个模型运行的 agent。

    agent = "../my-agent.toml"              optional: the agent file (default configs/default.toml)
    model = "grok-low"                      optional: configs/models/&lt;name&gt;.toml (default the agent's)
    bench = "robodojo"                      a bench of benches/&lt;name&gt;/bench.toml
    tasks = ["general_pickup"]              as the bench takes them (its bench.toml `tasks`)
    seeds = [0]
    layouts = "procedural"                  procedural (development) | eval
    layout_pack_seed = 0                    eval: which official pack
    deploy = "mine"                         optional; else --deploy or $HARNESS_DEPLOY
    strict = true                           default: true for eval layouts
    endpoint = "http://127.0.0.1:8771"      `harness program`: a worker that already runs

    [budget]                                per episode, and for the whole suite
    max_wall_seconds = 5400
    max_cost_usd = 4.0
    max_total_cost_usd = 20.0

    [worker]                                options of the bench's worker (its bench.toml `worker`)
    record_video = false

    [overrides.agent]                       changes to the agent for this experiment
    runtime.keep_images = 1
    [overrides.model]                       changes to the model roles
    main.reasoning_effort = "low"

`--set key.path=value` 写入这棵树；`--set agent.a.b=v` 和 `--set model.a.b=v` 写入 overrides，`--set model=NAME`（或 `--model NAME`）选择模型文件。

### `is_experiment`

```python
def is_experiment(tree: dict) -> bool
```

判断加载的文件是否为实验（指定 bench、tasks、seeds、layouts 或 agent），而非 agent 文件。

### `Experiment`

```python
class Experiment
```

已加载的实验：应用 --set 后的树、针对 deploy 解析的 agent、展开的任务和 seed，以及实验的预算、worker 和 suite 选项。`task_config` 提供单个任务的 driver 配置。

#### `task_config`

```python
def task_config(task: str | None=None, seeds=None, endpoint: str | None=None)
```

单个任务的 driver 配置（默认实验中的第一个任务）。

### `load_experiment`

```python
def load_experiment(path=None, *, tree: dict | None=None, deploy=None, sets=(), tasks=None, seeds=None, strict: bool | None=None, model=None, frozen_identity: bool | None=None) -> Experiment
```

读取实验文件或树（均无则为空实验，即默认 agent 在 RoboDojo 开发 layout 上运行），应用 --set，并针对 deploy（参数、文件的 `deploy` 或 $HARNESS_DEPLOY）解析 agent。`model`（模型名或文件）替换实验中的模型。
