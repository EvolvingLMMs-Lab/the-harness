---
title: "包"
description: "安装、更新和删除包；首次使用时自动安装；用 lock 文件固定项目的包；信任和离线 registry。"
---

pip/npm 只安装 The Harness 小巧的 core。**包**是环境及配套 skill 的交付层，也提供 benchmark 和模型服务：

- `computer`：应用和窗口，含 browser 工作区。
- `browser`：在后台浏览器里操作网站，属于 computer 工作范畴。
- `workspace`：在绑定的工作目录里操作项目文件和进程。
- `robot`：机器人；Settings 中的 `robot.mode` 选择该包的栈——默认 **Fast**；**Max 为 TBD**（[机器人模式](/docs/zh-cn/extend/integrations/#机器人模式)）；目前还不在公开 registry 里。

[包目录](https://harness.lmms-lab.com/packages/)列出了官方包，每个都附有 README。

安装 core 不替用户预选外部 app 或 agent。自动安装解决任务或用户所选能力实际需要的包，不替用户选择无关的外部产品。

## 安装

```bash
harness install workspace            # the newest version, and what it depends on
harness install browser@^0.4        # a version range
harness list                         # what is installed (--available: the registry's)
harness remove workspace
```

安装一个包时，也会安装它运行所需的东西：它的服务和 benchmark 的环境、它们的源码和模型权重。`harness install --update`
把包更新到其范围内的最新版本，`harness list --available QUERY` 按名字、摘要或提供的内容查找包，`harness list NAME` 显示一个包提供什么。每条命令都接受 `--json`。
app 的 **Settings → Packages** 页面和终端对话里的 `/packages` 可以做同样的事。已安装的包自己的命令会在安装后出现在 `harness --help` 里。

## 首次使用时安装

你很少需要运行 `harness install`。当一次运行需要某个已安装的包都不提供的东西（环境、skill、benchmark、服务）时，The Harness
会在 registry 中查找，并按照 `packages.auto_install` 的设置安装提供它的包：

| 值 | |
|---|---|
| `official`（默认） | 从官方 registry 安装包，不询问 |
| `ask` | 先询问，在 app 或终端中 |
| `off` | 从不安装：运行停止，并说明要安装哪个包 |

```toml
# ~/.harness/config.toml
[packages]
auto_install = "ask"
```

## 来源

包可以来自：

| 来源 | 示例 |
|---|---|
| registry，可附带版本范围 | `workspace`、`browser@^0.4` |
| git 仓库，指定 ref 和其中的文件夹 | `git:github.com/you/repo@main#packages/mine` |
| 压缩包 URL | `https://example.com/mine-0.1.0.tar.gz` |
| 这台电脑上的文件夹 | `./mine` |

```bash
harness install ./mine --link        # use the folder where it is, while you develop it
```

## 信任

包在这台电脑上以你的权限运行代码。来自官方 registry 的包是可信的。从其他任何地方安装包之前，The Harness
会显示它提供什么、会启动哪些服务、会安装哪些依赖，并询问你；`--yes` 跳过这个问题。

## 项目的包

要固定一个项目使用的包，把它们列在项目根目录的 `harness.toml` 中：

```toml
# harness.toml
[packages]
computer = "^0.5"
mine = { source = "git:github.com/you/mine@v0.3", range = "^0.3" }
```

```bash
harness install                      # in the project: install them, and write harness.lock
harness install --project workspace  # add one to the project
```

`harness.lock` 记录每个包的确切版本、校验和与来源；把它和项目一起提交，在那里运行 `harness install`
的每个人都会得到相同的包。只有在你信任了项目之后，项目的包才会被使用；在项目中运行 `harness install` 即表示信任。没有项目时，你自己的包列在
`~/.harness/config.toml` 的 `[packages]` 下。

每次运行都会在它的 lock 和 identity 中记录它使用的包，以及它们的版本和校验和（[配置](/docs/zh-cn/configure/configuration/#描述一次运行的文件)）。

## 版本

包的版本会注明它适用的 The Harness 版本范围，一次运行对每个包只使用一个版本。当两个包需要的版本无法共存时，安装会停止，并说明是哪些包以及原因。

## 离线和私有 registry

`HARNESS_REGISTRY` 或 `[packages]` 下的 `registry` 让 The Harness 使用另一个 registry，可以是一个 https 地址或一个文件夹：

```bash
export HARNESS_REGISTRY=/srv/harness-registry
harness install workspace
```

registry 是一个文件夹，包含一个 `index.json` 和每个版本一个压缩包；官方 registry 文件夹的副本可以离线使用。
[编写包](/docs/zh-cn/extend/packages/)介绍了包如何制作和发布。

## 存放位置

已安装的版本保存在 `~/.cache/harness/packages/<name>/<version>-<sha>/` 下，放入后不再改动。`harness remove`
把包从你的列表中移除（加 `--project` 时从项目的列表中移除），当没有其他地方使用时，它存储的版本也会被删除。
