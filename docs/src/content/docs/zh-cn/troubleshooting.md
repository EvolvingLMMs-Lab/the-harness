---
title: "排错"
description: "日志在哪里、harness doctor 检查什么、如何重置、按错误信息列出的常见错误，以及如何报告 bug。"
---

## 先运行 harness doctor

```bash
harness doctor                 # this computer: Python, packages, services, GPUs, keys
harness doctor computer        # what one experiment needs here
harness doctor --json          # the same for a bug report
```

每项检查的结果是 `ready`、`will_install`（第一次运行时会安装）或 `missing`，缺失的项会附带修复它的那一行命令。在 app 中，**Settings → About → Run
harness doctor** 显示同样的内容。

## 日志在哪里

| 日志 | 内容 |
|---|---|
| `~/.harness/logs/host.log` | session host：会话的开始和结束、工作区、它发起的安装 |
| `~/.cache/harness/logs/install-<name>.log` | 包的环境或服务的安装 |
| `~/.cache/harness/logs/<service>.log` | 模型服务运行期间的日志 |
| 一次运行的 `kernel.log` | agent 的程序：它们的输出和错误 |
| 一次运行的 `events.jsonl` | 发生的一切，逐条记录（[事件和 trace](/docs/zh-cn/reference/traces/)） |
| 一次运行输出中的 `suite.log` | `harness run`：worker、episode、错误 |

在 app 中，**Settings → About → Logs** 打开这个文件夹。对话自己的文件在 `~/.harness/conversations/` 下；`harness replay CONVERSATION`
打印它做了什么。

## 重置

| 目的 | 做法 |
|---|---|
| 停止所有正在运行的东西 | 在 `harness` 里输入 `/host stop`（结束 session host 和其中打开的会话），服务用 `harness down` |
| 重建一个环境 | 删除它在 `~/.cache/harness/envs/` 下的文件夹；下一次运行会重新构建 |
| 重装一个包 | `harness remove NAME`，然后 `harness install NAME` |
| 恢复默认设置 | 从 `~/.harness/config.toml` 中删除你改过的节（保留 `[model]` 和 `[keys]`） |
| 忘掉一个密钥 | 从 `~/.harness/config.toml` 的 `[keys]` 下删掉它那一行，或 unset 该变量 |
| 从零开始 | 删除 `~/.harness/` 和 `~/.cache/harness/`（这会删除你的对话） |

## 常见错误

### `NAME: its environment did not install (...); see .../install-NAME.log`

无法为包、工作区或服务构建环境。日志的最后几行会说明原因：通常是下载失败（代理或镜像：pip 自己的设置适用），或缺少某个 Python 版本（安装
[uv](https://docs.astral.sh/uv/)，它会获取该版本，或者把 `python3.11` 放进你的
`PATH`）。修复后重新运行；构建了一半的环境会被替换。

### `KernelDied: Kernel failed to start`

运行 agent 程序的进程无法启动。错误信息中的 traceback 会指出导入失败的模块；它运行所在的环境缺少某个依赖。重建那个环境（见[重置](#重置)），如果问题再次出现，请报告。

### `... is not set (export it, or keep it in [keys] of the configuration file)`

缺少模型的密钥。设置错误信息中指出的变量（[模型和 provider](/docs/zh-cn/configure/models/)），或在 app 中重新连接模型。只在某一个
shell 中 export 的密钥，从另一个 shell 启动的 session host 是看不到的：在 `harness` 里输入 `/host stop`，然后从有这个密钥的 shell 重新启动。

### provider 返回 401、402 或 429

401：密钥错误或已被吊销。402：账户没有余额。429：请求过多；The Harness 会暂停后重试，一次运行在用完重试次数后放弃。每种情况都会在对话中显示为一条错误，附带
provider 自己的信息。

### `Could not start background Chrome. An installed Google Chrome is required`

后台浏览器需要 Google Chrome。安装它，或者让 `HARNESS_CHROME_PATH` 指向另一个 Chrome 或 Chromium 可执行文件。

### `browser workspaces (...) are not available on this machine` 及类似错误

app 会隐藏这台电脑无法运行的工作区，**Settings → Computer** 会说明每种工作区需要什么：后台浏览器需要 Chrome，Linux
上在后台运行应用需要 X11 会话，独立显示环境需要显示服务器或虚拟机镜像。

### `no X display: DISPLAY is not set`

在 Linux 上，桌面需要一个 X11 会话。通过 SSH 或在服务器上时，使用后台浏览器或独立显示环境，它们会启动自己的显示。

### macOS：屏幕是黑的，或者点击没有反应

在 **System Settings → Privacy & Security** 中，为运行 `harness` 的终端或 app 允许 **Screen Recording** 和
**Accessibility**，然后重新启动它。

### `waiting for a workspace: 4 of 4 in use`

所有工作区都在使用中。结束一个对话，或者调高 `[computer]` 下的 `workspaces`（app 中的 **Settings → Computer → Conversations working at once**）。

### `missing or wrong session key`

HTTP API 客户端必须携带 session host 的 token，不要分享该密钥。

### `out of GPU memory`

某个模型服务，或某个上下文很长的自托管语言模型，用完了 GPU 显存。对于语言模型，The Harness 会少发送一些历史轮次并继续。对于服务，在
deploy 文件中把它放到另一块 GPU 上，或者把它改为按需（[服务](/docs/zh-cn/configure/services/)）。

### `harness run --resume` 拒绝执行，退出状态为 2

参数与 suite 记录的参数不同。只有运行位置可以改变（`--gpus`、`--workers-per-gpu`、`--base-port`、`--workspaces`），并且可以加上
`--rerun-errors`；实验改变了就需要一个新的 `--output`。

### agent 反复做同样的事，或者没有回答就结束了

试试更强的模型，或更高的 `reasoning_effort`：小模型在长任务中容易失去头绪。用更具体的话描述任务，或者把它拆开。时间轴显示它做了什么、什么时候做的（[查看和回放运行](/docs/zh-cn/use/replay/)）。

## 报告 bug

在
[github.com/EvolvingLMMs-Lab/the-harness/issues](https://github.com/EvolvingLMMs-Lab/the-harness/issues)
提一个 issue，附上：

- 你做了什么、你期望什么、实际发生了什么；
- `harness doctor --json`；
- 显示错误的那段日志末尾；
- 如果可以分享，附上这次运行的文件夹，或 app 中该对话的 **⋯ → Export**。

附上之前先检查一遍：trace 中包含 agent 拍下的截图和它读到的文字。密钥从不写入 trace 或日志。
