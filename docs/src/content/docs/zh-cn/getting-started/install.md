---
title: "安装"
description: "用 npm、pip 或 uv 安装 The Harness，连接一个模型，用 harness doctor 检查本机，以及如何卸载。"
---

```bash
npm install -g @lmmslab/harness
```

或者用 pip：

```bash
pip install the-harness
```

或者，把它装在一个单独的环境里：

```bash
uv tool install the-harness
```

The Harness 需要 Python 3.11 或更新版本。它是一个小的纯 Python 包：没有 PyTorch，没有模型权重，也不依赖特定的环境。命令是 `harness`，Python 包也叫 `harness`。

## 连接模型

```bash
harness
```

第一次运行时会询问用哪个 provider 和模型，以及该 provider 的 key；它会向 provider 核对 key，并把这些回答保存在 `~/.harness/config.toml` 里，只有你能读取。然后它打开对话。环境变量里已有的 key（例如 `OPENROUTER_API_KEY`）会被直接找到，不需要再问。[模型和 provider](/docs/zh-cn/configure/models/) 列出了支持的 provider，以及之后如何更换模型。

## 检查本机

```bash
harness doctor
```

`harness doctor` 检查核心、是否已设置模型，以及已安装的包。每个缺少的项目都附带修复它的那一行。只要还有缺少的东西，它就以 1 退出；`--json` 以供脚本使用的格式输出同样的内容。

## 平台

| 系统 | 支持情况 |
|---|---|
| Windows | 全部支持；独立显示屏运行在虚拟机里 |
| macOS | 全部支持；独立显示屏运行在虚拟机里；系统询问时允许 **屏幕录制** 和 **辅助功能** |
| Linux | 全部支持；桌面需要 X11 会话（在 Wayland 上，请用后台浏览器或独立显示屏） |

后台浏览器需要安装 Google Chrome。需要 GPU 的机器人、仿真器和本地模型要求一块装有较新驱动的 NVIDIA GPU；其余的都可以在笔记本电脑上运行。

## 之后会安装什么

第一次安装只有核心。其余部分在任务第一次需要时才安装：

- **包。** 后台浏览器里的对话会安装 `browser`，桌面上的对话会安装 `computer`。[包](/docs/zh-cn/configure/packages/)里有决定安装前是否先询问的设置。
- **环境。** 需要 Python 库的包会有自己的环境，所以它们的依赖不会冲突。如果装了 [uv](https://docs.astral.sh/uv/)，The Harness 还会获取它们需要的 Python 版本。
- **模型权重**，用于在本机运行的模型，在它第一次启动时下载。

如果想提前安装，例如在断网之前：

```bash
harness install --tui computer browser
```

`--tui` 准备终端依赖，不启动对话；同名 benchmark 也会准备其 Python 环境。Chrome、系统权限、虚拟机和远程模型连接需要另外准备。只使用终端时可以单独运行 `harness install --tui`。向导发现已导出的 key 后，留空即可沿用；无需认证的 Custom 端点可以不填 key。

## 文件存放位置

| 文件夹 | 存放内容 | 用哪个变量改位置 |
|---|---|---|
| `~/.harness/` | `config.toml`（你的模型、key 和设置）、对话，以及 agent 学到的东西 | `HARNESS_DATA` |
| `~/.cache/harness/` | 包、环境、模型权重以及其他可以重建的东西 | `HARNESS_HOME` |

## 更新

```bash
npm install -g @lmmslab/harness@latest   # 或：pip install --upgrade the-harness
harness install --update
```

第一条命令更新核心，第二条把各个包更新到与之兼容的最新版本。

## 卸载

```bash
npm uninstall -g @lmmslab/harness   # 或：pip uninstall the-harness
```

这样会保留你的数据。要删除全部内容，还要删除 `~/.harness/` 和 `~/.cache/harness/`（或者 `HARNESS_DATA`、`HARNESS_HOME` 指向的文件夹）。

下一步：[快速开始](/docs/zh-cn/getting-started/quickstart/)。
