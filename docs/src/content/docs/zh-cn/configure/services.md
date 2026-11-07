---
title: "服务"
description: "在你自己的 GPU 上运行的模型服务：它们如何安装、启动、共享 GPU 和停止，以及如何自己放置它们。"
---

有些能力需要在你自己的硬件上运行的模型：分割模型、机器人的学习型策略、世界模型、本地语言模型。The Harness 把每个这样的模型作为一个
**服务**运行：一个独立的进程，在独立的环境中，agent 的 skill 通过 HTTP 调用它。服务由包提供；`harness services`
列出你拥有的服务。

你很少需要自己启动服务。一次运行开始时，The Harness 会找出 agent 的 skill 用到哪些服务，安装这台电脑上缺少的，并在它找到的
GPU 上启动它们。安装了提供服务的包之后，下面的命令用于手动操作：提前安装、在多次运行之间保持模型加载，或查看正在运行的内容。

## 命令

```bash
harness services              # every service: what it does, its port, the GPU memory it needs
harness doctor sam3           # whether it is installed, what is missing, the GPUs and their free memory
harness install sam3          # its environment, sources and weights, without starting it
harness fetch sam3            # only its weights
harness up sam3               # start it (without names: every resident service)
harness status                # where each runs and whether it answers
harness down sam3             # stop it (without names: everything harness up started)
```

`harness install` 在 `~/.cache/harness/envs/` 下构建服务指定的环境（它的 Python 版本、固定版本的依赖和源码），下载它的权重并检查是否完整，再检查它能否导入。已经匹配的环境保持不动。每次安装的日志在
`~/.cache/harness/logs/install-<name>.log`。

## 在哪里运行

不做任何配置时，The Harness 自己放置服务：GPU 上有空间时，服务是**常驻**的（加载一次并保持）；GPU 需要共享时，服务是**按需**的（skill
第一次调用时启动，空闲一段时间后停止）。没有 GPU 的电脑可以运行所有模型都是托管模型的 agent，或者通过 URL 访问在别处运行的服务。

要自己决定，写一个 **deploy 文件**，用 `--deploy FILE`（每条命令都接受）或 `HARNESS_DEPLOY` 传入：

```toml
# my-deploy.toml
[services.sam3]
gpu = 0                   # resident on GPU 0

[services.g05]
gpu = 1
mode = "on_demand"
swap = "policies"         # services of one swap group share GPU 1, one loaded at a time
idle_seconds = 600        # stopped after 10 minutes without a request

[services.openwam]
gpu = 1
mode = "on_demand"
swap = "policies"

[services.molmo2]
mode = "external"         # someone else runs it
url = "http://gpu-box.local:8830"
```

| 键 | |
|---|---|
| `gpu` | 它运行在哪块 GPU 上 |
| `mode` | `resident`（默认）、`on_demand` 或 `external` |
| `swap` | 一组共享一块 GPU 的按需服务，同一时间只加载一个 |
| `idle_seconds` | 按需服务在没有请求时保持运行多久 |
| `url` | 外部服务的地址 |
| `python`、`env` | 服务使用的另一个解释器，或环境变量 |

服务在哪里运行从来不属于一次运行的 identity：同一个 agent 配上同样的服务，在任何电脑上计算的都是同样的东西。

## 按需

按需服务由一个小的 **broker** 进程启动；当 deploy 文件中有按需服务时，`harness up`（或一次运行）会启动它。skill 在每次调用前询问
broker；broker 在服务没有运行时启动它，等到它响应，并在 `idle_seconds` 内没有请求后停止它。在同一个 swap group
中，启动一个服务会先停止其他服务。

## 日志和问题

每个服务把日志写到 `~/.cache/harness/logs/<name>.log`。`harness status` 显示每个服务是否响应。如果服务要启动时它的端口已经有响应，就直接使用已有的那个（另一次运行启动的，或手动启动的），而
`harness down` 只停止 `harness up` 启动的服务。

当一次运行无法启动它需要的服务时，agent 可能在没有那些依赖该服务的 skill 的情况下运行；`harness doctor EXPERIMENT` 和
`harness run --dry-run` 会列出将被去掉的 skill 及原因。`--strict` 让运行改为拒绝启动。
[排错](/docs/zh-cn/troubleshooting/)列出了常见错误。
