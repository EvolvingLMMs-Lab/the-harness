---
title: "服务"
---

## `harness.services.registry`

服务清单：skill 和 agent 调用的模型进程。

服务是一个可部署的模型服务器，由 services/&lt;name&gt;.toml 描述：

    kind = "segmenter"            segmenter | vision | pointer | vlm | llm | policy | world_model | kinematics
    summary = "..."
    protocol = "http"             http | openai_chat | xpolicylab
    command = ["{python}", "services/servers/serve_sam3.py", "--checkpoint", "{weights}/sam3/sam3.pt",
               "--port", "{port}"]
    port = 8810                   default port
    vram_gb = 7.2                 GPU memory it holds once loaded (measured)
    load_seconds = 60             start until it answers
    client = { url = "{url}" }    the kernel's or agent's config for it ({url}, {host}, {port})
    [environment]                 the environment it runs in, installed on first use
    python = "3.11"               (harness/packages/environments.py); {python} is its interpreter
    requirements = ["torch==2.7.0", ...]
    [[weights]]                   where its weights come from, downloaded with it
    dir = "sam3"
    modelscope_model = "facebook/sam3"

XPolicyLab 策略无需 command：[xpolicylab] 表指定策略目录、动作类型和覆盖项，服务器使用 XPolicyLab 自身的 setup_policy_server.py。服务的运行位置（GPU、端口、常驻或按需、或不运行）由 deploy 文件（deploy.py）负责，不由清单决定。

### `ServiceSpec`

```python
class ServiceSpec
```

加载后的服务清单（MANIFEST_KEYS）：`name` 为不含后缀的文件名，`path` 为文件路径。{python}、{port} 等占位符留给 deploy 填入。

### `load_services`

```python
def load_services(root: Path=SERVICES_ROOT) -> dict[str, ServiceSpec]
```

读取并校验 `root` 下的所有服务清单（*.toml），按名称返回。每个根目录只读取一次。

### `service`

```python
def service(name: str, root: Path=SERVICES_ROOT) -> ServiceSpec
```

服务 `name` 的清单；未知名称会报错。

## `harness.services.placement`

agent 指定的服务在哪里运行：由放置服务的包给出（local-models 包的 deploy：一个 deploy 文件，或 harness 在本机 GPU 上自己的放置）。没有这样的包时，这里不放置任何服务：agent 的角色使用托管模型，需要已放置服务的角色或服务被省去（strict 时报错）。config/agent.py 针对它解析 agent。仅使用标准库。

### `Unplaced`

```python
class Unplaced
```

没有任何东西放置时服务的运行方式：off。

### `NoDeploy`

```python
class NoDeploy
```

这里没有包放置服务：所有服务都是 off。

#### `automatic`

```python
def automatic() -> bool
```


#### `services`

```python
def services() -> dict
```


#### `placements`

```python
def placements() -> dict
```


#### `placement`

```python
def placement(name: str) -> Unplaced
```


#### `variables`

```python
def variables() -> dict
```


### `load_deploy`

```python
def load_deploy(name=None, **options)
```

放置服务的包加载的 deploy `name`（configs/deploy/ 中的名称、路径，None 表示 $HARNESS_DEPLOY）；没有这样的包时为 NoDeploy。

### `automatic`

```python
def automatic(names, **options)
```

harness 在本机为 `names` 自己做的放置（没有放置服务的包时为 NoDeploy）。

### `client_config`

```python
def client_config(deploy, name: str) -> dict | None
```

服务 `name` 的客户端在 `deploy` 上得到的配置（它的 url 和告诉模型的说明）；服务不在那里运行时为 None。

## `harness_local_models.deploy`

Deploy 文件：一台机器上各服务的运行位置。

configs/deploy/&lt;machine&gt;.toml 指定本机供项目使用的 GPU、权重位置和各服务运行方式（Git 忽略此处的机器文件，仅跟踪 example-*.toml）：

    weights = "/data/weights"         root of the services' weight directories
    state = "/data/harness-services"  pid files and logs of started services
    gpus = [2, 3, 4, 5]               GPUs services and simulators may use
    gpu_memory_gb = 24

    [sim]                             simulator workers of `harness run`
    gpus = [5]
    workers_per_gpu = 2

    [benches.osomni]                  a bench's own settings (its bench.toml `deploy` keys):
    checkout = "/data/OS-Omni"        here OS-Omni's checkout, environment and desktop VMs,
    python = "/data/OS-Omni/.venv/bin/python"                         one worker each
    machines = [{ runtime_url = "http://127.0.0.1:15001", qmp_socket = "/vm/qmp-1.sock" }]

    [services.sam3]
    gpu = 3                           a GPU index, or "auto" (fit by vram_gb)
    [services.molmo2]
    mode = "external"                 someone else runs it
    url = "http://10.0.0.7:8830"
    [services.openwam]
    mode = "off"

    [services.g05]
    gpu = 1
    mode = "on_demand"                started when a skill first calls it ...
    swap = "big"                      ... and sharing GPU 1 with the other services of
    [services.openwam]                its swap group, one loaded at a time
    gpu = 1
    mode = "on_demand"
    swap = "big"

deploy 未列出的服务关闭。模式：resident（由 `harness up` 启动并保持运行）、on_demand（skill 需要时由 broker 启动，空闲超过 idle_seconds 或同组其他服务被需要时停止；见 broker.py）、external（只有 URL）、off。放置不改变计算内容，只影响运行位置和时机；系统决定运行使用哪些服务。

未提供 deploy 文件时，harness 自动生成（automatic）：按 nvidia-smi 列出的 GPU 剩余显存，为一个模拟器 worker 预留空间后放置所需服务；能容纳则常驻，否则按 SWAP_LEVELS 置于同一按需 swap group。保存到 ~/.cache/harness/deploy/auto.toml，只要仍能放置所需全部服务就复用。

### `Placement`

```python
class Placement
```

一个服务在 deploy 上的运行方式（PLACEMENT_KEYS）。未列出的服务 mode 为 off；加载 deploy 时将 gpu = "auto" 替换为 GPU 编号。

### `Deploy`

```python
class Deploy
```

已加载的 deploy 文件：本机权重、状态和源码路径、GPU、模拟器设置，以及所列各服务的放置。无 deploy 文件（名称 "none"）时所有服务关闭。

#### `automatic`

```python
def automatic() -> bool
```

是否没有 deploy 文件，即由 harness 自行放置运行所需服务（automatic()）。

#### `services`

```python
def services() -> dict[str, ServiceSpec]
```

按名称返回 `services_root` 下每个服务清单，无论是否在本机运行。

#### `placement`

```python
def placement(name: str) -> Placement
```

服务 `name` 在本机的运行方式（文件未列出则 mode 为 off）；未知服务会报错。

#### `variables`

```python
def variables() -> dict
```

服务命令、设置和必需文件的占位符：python（当前进程解释器；launch() 为各服务提供所属环境的解释器）、repo、weights、robodojo、xpolicylab、xpolicylab_parent、state。

### `deploy_path`

```python
def deploy_path(name: str | os.PathLike | None) -> Path | None
```

由名称（configs/deploy/&lt;name&gt;.toml）或路径获取 deploy 文件；None 表示 $HARNESS_DEPLOY，未设置则没有 deploy 文件。

### `load_deploy`

```python
def load_deploy(name: str | os.PathLike | None=None, *, services_root: Path=SERVICES_ROOT) -> Deploy
```

`name` 对应的 deploy（见 deploy_path）；不存在时所有服务关闭，仅可用托管模型。

### `planned_memory`

```python
def planned_memory(deploy: Deploy) -> dict[int, float]
```

deploy 为每张 GPU 规划的显存：常驻服务累加，swap group 按最大成员计算（每次只加载一个）。

### `render`

```python
def render(value, variables: dict)
```

填充字符串中的 {name} 占位符（递归处理列表和字典）。

### `port`

```python
def port(deploy: Deploy, name: str) -> int
```

服务在本机监听的端口：优先使用放置设置，否则使用清单值。

### `url`

```python
def url(deploy: Deploy, name: str) -> str | None
```

客户端访问服务的地址；关闭时为 None。

### `client_config`

```python
def client_config(deploy: Deploy, name: str) -> dict | None
```

skill 或 agent 使用的服务配置（填好 URL 的清单 client 表）；deploy 不运行此服务时为 None。

### `launch`

```python
def launch(deploy: Deploy, name: str) -> tuple[list[str], dict, str]
```

启动此 deploy 中一个服务所需的 (argv, environment, working directory)。

### `weight_dirs`

```python
def weight_dirs(deploy: Deploy, name: str) -> list[Path]
```

deploy 权重根目录下的服务权重目录，每个 `[[weights]]` 条目一个。

### `missing_files`

```python
def missing_files(deploy: Deploy, name: str) -> list[str]
```

服务所需但本机缺失的文件。

### `package_folder`

```python
def package_folder(spec) -> str
```

服务的 {package}：清单所在的 services/ 属于哪个扩展包（或核心），就是那个文件夹。

### `fit`

```python
def fit(path: Path, head: dict, entries: dict, *, keep=(), comment: str='', log=print) -> Deploy
```

将 `head`（顶层键）和 `entries`（各服务放置）对应的 deploy 写入 `path` 并加载：全部能容纳时按条目设置，否则逐层将 SWAP_LEVELS 中的类型改为同一 swap group（"models"）中的按需服务。`keep` 中的服务保持条目指定的模式。

### `automatic`

```python
def automatic(names, *, gpu_rows=None, log=print) -> Deploy
```

harness 为服务 `names` 自动生成的 deploy（无 deploy 文件）：按本机当前 GPU 剩余显存放置，在空间最大的 GPU 上先预留一个模拟器 worker；能容纳则常驻，否则按 SWAP_LEVELS 按需加载。默认使用清单端口，除非该端口有非 harness 启动的进程响应。无 GPU 机器上需 GPU 的服务关闭。写入 ~/.cache/harness/deploy/auto.toml，只要仍能放置 `names` 的全部服务就复用。

## `harness_local_models.supervisor`

启动、停止并检查 deploy 的服务（`harness up`、`down`、`status`）。

每个服务作为独立进程组运行，日志位于 &lt;state&gt;/logs/&lt;name&gt;.log，记录位于 &lt;state&gt;/&lt;name&gt;.json（pid、端口、GPU、命令）。端口已响应的服务不处理：共享机器上它可能由手动或另一份源码启动，再启动副本只会因端口冲突失败。

### `listening`

```python
def listening(port: int, host: str='127.0.0.1', timeout: float=0.5) -> bool
```

`host`:`port` 是否接受 TCP 连接。

### `record`

```python
def record(deploy, name: str) -> dict | None
```

在本机启动的服务记录（`<state>/<name>.json`：pid、端口、GPU、argv、cwd、env、启动时间）；不存在或无法读取时返回 None。

### `status`

```python
def status(deploy, names=None) -> list[dict]
```

deploy 放置的每个服务（或 `names`）一行：模式、GPU、URL、端口是否响应，以及 harness up 启动的进程。

### `start`

```python
def start(deploy, name: str, *, wait: bool=True, log=print) -> dict
```

若端口尚未响应，启动一个常驻服务。返回其状态。

### `wait_ready`

```python
def wait_ready(deploy, name: str, process=None, timeout: float | None=None) -> None
```

等待服务 `name` 在其端口响应。`process`（或记录的 pid）先退出时抛出 RuntimeError；经过 `timeout` 秒后抛出 TimeoutError（默认 load_seconds 的三倍，至少 60）。

### `stop`

```python
def stop(deploy, name: str, *, grace: float=15.0, log=print) -> bool
```

停止 harness up 启动的服务（对进程组依次发送 SIGINT、SIGTERM、SIGKILL）。不处理其他方式启动的服务。

### `up`

```python
def up(deploy, names=None, *, log=print) -> list[dict]
```

同时启动常驻服务（全部或 `names`），随后等待各服务响应；deploy 含按需服务时启动 broker。

### `start_broker`

```python
def start_broker(deploy, log=print)
```

启动 deploy 的按需服务 broker；无按需服务或 broker 已运行时不操作。

### `down`

```python
def down(deploy, names=None, *, log=print) -> None
```

停止 harness up（或 broker）启动的服务；未指定名称时也停止 broker。

## `harness.services.broker`

按需服务，从客户端看：每次调用一个 deploy 按需运行的服务之前，ensure() 请 deploy 的 broker 让它响应（local-models 包的 broker 启动它、在共享 GPU 上换入换出，并在空闲时停止它）。服务使用期间，客户端最多每 CLIENT_INTERVAL 秒询问一次。

### `ensure`

```python
def ensure(config: dict | None, *, timeout: float=1800.0) -> None
```

调用服务前：若客户端配置为按需模式，则请求 broker 使其可响应（使用期间最多每 CLIENT_INTERVAL 秒一次）。
