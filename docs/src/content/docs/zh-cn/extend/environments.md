---
title: "接入一种环境"
description: "接入一个 agent 能观察和操作的新环境：一个通过 HTTP 提供它的 worker、它属于哪种 embodiment，以及一个任务 bench。"
---

agent 可以在任何它能观察和操作的环境中工作：一个应用、一个网站、一个游戏、一个模拟器、一个机器人。The Harness 通过
**worker** 访问每个环境：worker 是一个通过 HTTP 提供环境的进程，在每一步执行之前检查它，并且自己保管分数。要添加一个环境，你编写它的
worker 并说明它是哪种环境；agent 的 skill 无需修改就能在上面工作。

## 三个部分

| 部分 | 说明什么 | 文件 |
|---|---|---|
| **worker** | 如何观察环境并在其上操作 | 一个 Python 类和一个工厂函数 |
| **embodiment** | 它是哪种环境（`desktop`、`browser`、`game`、`robot`）以及它的基本信息：屏幕尺寸、控制方式、控制频率、限制 | `embodiments/<name>/embodiment.toml` |
| **bench** | 它的任务、一次运行如何启动它的 worker、一次运行如何计分 | `benches/<name>/bench.toml` |

种类决定 agent 得到哪些 skill：`game` 得到截图、按键和鼠标、通道和反射；`desktop` 得到窗口、无障碍接口和输入；`robot`
得到运动、运动学和控制器。选择与你的环境最接近的种类，agent 针对该种类的 prompt 和 skill 就会适用。

## 1. worker

worker 是一个对象，具有 `reset(task, seed)` 以及它所属种类的调用。每个 worker 都响应以下调用：

| 调用 | 返回 |
|---|---|
| `profile` | 静态信息：种类、控制频率、屏幕或相机、限制 |
| `state` | 当前状态 |
| `tick` | 一步：命令、检查的结论、新状态 |
| `observe` | 状态和图像 |
| `claim_outcome`、`outcome` | episode 的结果，只给运行看，从不给 agent 看 |

游戏 worker 以 `game` 种类定义的形式接收输入（一个控制周期内的按键、按钮和鼠标移动），并以图像形式返回画面。
[worker 协议](/docs/zh-cn/reference/worker-protocol/)给出了每种种类的每个调用。

```python
# mygame/worker.py
class MyGame:
    def reset(self, task="play", seed=0):
        ...                                  # start the level; return the first observation

    def call(self, name, arguments):
        return getattr(self, name)(**arguments)

    def profile(self):
        return {"kind": "game", "name": "mygame", "control_hz": 20,
                "screen": {"width": 1280, "height": 720}}

    # state, tick, observe, claim_outcome, outcome ...


def create_environment(**options):
    return MyGame(**options)
```

`fakegame` bench 是一个用 numpy 绘制的虚构游戏，是一个完整的小型 worker，可以阅读和照抄。

## 2. 提供服务

```bash
harness serve --factory mygame.worker:create_environment --port 8765
```

worker 开始监听后会打印一行它的地址。它一次只响应一个请求，且只响应这台电脑；要把它提供给另一台电脑，设置
`HARNESS_WORKER_TOKEN`，此后每个请求都必须带上它。

## 3. 检查每一步

每条命令在执行之前都要通过 worker 自己的检查。检查拒绝属于 bug 的命令（格式错误、超出范围、任何控制器都不会做出的跳变），除此之外什么都不改：它从不截断、缩短或减慢命令。agent
写的或学到的任何东西都不能关掉它。游戏的检查还包含公平性上限，例如一个周期内视角最多能转多少，使 agent 的玩法是人也能做到的。使用你所属种类的检查，并在
embodiment 中设置它的限制。

## 4. bench

```toml
# benches/mygame/bench.toml
name = "mygame"
summary = "My game, played from its pixels"
kind = "game"
embodiment = "mygame"
factory = "mygame.worker:create_environment"
tasks = "\"play\": reach the end of the first level"

[environment]                       # the worker's own Python environment
python = "3.12"
requirements = ["pillow==12.1.1", "numpy==2.4.4"]
imports = ["PIL", "numpy"]
```

有了 bench，`harness run` 会为每个任务和 seed 在独立的环境中自行启动 worker，并为结果计分：

```toml
# experiments/mygame.toml
description = "My game, first level"
bench = "mygame"
tasks = ["play"]
seeds = [0, 1, 2]
```

```bash
harness run experiment experiments/mygame.toml --dry-run
```

bench 还可以用 Python 提供钩子，满足它的任务所需：展开任务组、每个 worker 的选项、同时并行运行多少个。

## 5. 发布

把 worker、embodiment、bench、它的实验以及为它写的 skill 放进一个包（[编写包](/docs/zh-cn/extend/packages/)）。之后需要这个环境的运行会自行安装这个包，agent
也可以在其中工作之前先[学会这个环境](/docs/zh-cn/learn/learn-an-environment/)。
