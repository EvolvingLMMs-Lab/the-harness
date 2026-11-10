---
title: "环境"
---

harness 本身是标准库 Python，用 npm 或 pip 安装：`npm install -g @lmmslab/harness` 或 `pip install the-harness`，或在检出副本中 `pip install -e .`。运行所需的其他一切都在第一次用到时安装，也可以用 `harness install <name>` 提前安装：每个服务和每个 benchmark 在 `~/.cache/harness/envs/` 下各有一个自己的环境（`HARNESS_HOME` 可改变位置），按其清单（`services/<name>.toml`、`benches/<name>/bench.toml`）中的 `[environment]` 表构建。

本目录存放固定版本的核心（`constraints.txt`：browser benchmark 的环境，以及导出的 XPolicyLab 策略的 `install.sh`）。服务和 benchmark 的环境共用的内容在 local-models 包的 `environment/` 中：

| 文件 | 用途 |
| --- | --- |
| `lock/pip-freeze.txt` | 每个服务和 benchmark 的环境安装时遵守的固定版本（`constraints = "environment/lock/pip-freeze.txt"`） |
| `requirements-skills.txt` | 导出的 XPolicyLab 策略的 `install.sh` 装进 RoboDojo 策略环境的内容：解析型和学习型 skill 所需的软件包 |
| `cuda_toolkit.sh` | 编译 cuRobo 所用的 CUDA 12.8 构建工具链（RoboDojo 和 RoboTwin 的环境） |

RoboTwin 的两处源码修改和它自己的 cuRobo 构建属于 robotwin 包（`environment/robotwin_edits.py`、`environment/robotwin_curobo.sh`）。

每次安装都遵守这些固定版本，因此任何服务或 benchmark 都无法改变 torch、numpy、Isaac Sim 或 websockets 的版本：无法在约束下安装的软件包会安装失败，而不是升级核心组件。环境目录以决定安装内容的一切（其表和固定版本，不含注释）的哈希命名，因此修改某个固定版本后，用到它的环境会在下次运行需要时重新构建，其他环境保持不变。

文档站不是 Python 项目：它是具有独立 lock 的 Deno 项目（`docs/deno.json`、`docs/deno.lock`；参见 `docs/README.md`）。

<a id="changing-a-pin-or-adding-a-dependency"></a>
## 修改固定版本或添加依赖

服务或 benchmark 的依赖写进其清单的 `requirements`；固定版本写进 `lock/pip-freeze.txt`。用 `harness install <name>` 安装，运行一次用到它的任务，然后把清单和固定版本一起提交。

<a id="one-interpreter-for-everything"></a>
## 一个解释器运行一切

`HARNESS_ENVIRONMENTS=project`（或 deploy 中的 `environments = "project"`）除了权重什么都不安装：每个服务和 worker 都在 harness 自己的解释器中运行。它用于某个环境已经装好一切的机器，不是一种安装方式；这样的机器还要自己设置那些环境原本会设置的变量，例如 RoboDojo 的 worker 需要的 `OMNI_KIT_ACCEPT_EULA=YES`。

<a id="known-deviations-from-upstream"></a>
## 与上游的已知差异

- `isaacsim-kernel` 声明了 `websockets==12.0`，只有 Kit 的资源搜索扩展用到它；无头仿真不会加载这些扩展。XPolicyLab 策略服务器需要 websockets 13+ 的 asyncio API，因此 RoboDojo 的环境用 17.1 覆盖它（`benches/robodojo/bench.toml` 中的 `overrides`）。
