---
title: "桌面应用"
description: "在 Windows、macOS 或 Linux 上安装 The Harness 桌面应用，第一次打开时越过未签名提示，让它开机继续运行，以及如何卸载。"
---

桌面应用把 The Harness 需要的一切装在一个安装包里：自带的 Python 运行时、Harness 本身，以及带托盘图标的窗口。你不需要装 Python。开发者照旧用 `pip install the-harness`（见[安装](/docs/zh-cn/getting-started/install/)）。窗口里有什么、有哪些按键，见[应用](/docs/zh-cn/use/app/)。

从[最新发布](https://github.com/EvolvingLMMs-Lab/the-harness/releases/latest)下载对应系统的安装包：

| 系统 | 文件 |
|---|---|
| Windows | `The.Harness_X.Y.Z_x64-setup.exe`（或 `.msi`） |
| macOS（Apple 芯片） | `The.Harness_X.Y.Z_aarch64.dmg` |
| Linux | `The.Harness_X.Y.Z_amd64.AppImage` 或 `The.Harness_X.Y.Z_amd64.deb` |

## 第一次打开：未签名提示

安装包暂未做代码签名，所以第一次打开时系统会提示。只会出现一次。

**Windows。** Microsoft Defender SmartScreen 显示"Windows 已保护你的电脑"，发布者为未知。点 **更多信息**，确认文件是 `The.Harness_…_x64-setup.exe`，再点 **仍要运行**。

**macOS。** 打开 `.dmg`，把 **The Harness** 拖进 **应用程序**。第一次打开时 macOS 说无法验证开发者。点 **完成**，打开 **系统设置 › 隐私与安全性**，滚到关于 The Harness 的那条消息，点 **仍要打开**，再输入密码确认。它第一次在登录时启动，macOS 还会提示"已添加后台项目"，那就是下面说的登录项。

**Linux。** AppImage 要先加上可执行权限（`chmod +x The.Harness_*.AppImage`），并需要 FUSE 2（Ubuntu 上是 `libfuse2`）。`.deb` 用 `sudo apt install ./The.Harness_X.Y.Z_amd64.deb` 安装，并带上 `harness` 命令。

## 开机后继续运行

安装包默认打开"登录时启动"，和 Ollama 一样，所以重启电脑后你的 agent 会自己接着运行。登录项用的是系统自己的机制：

| 系统 | 登录项 |
|---|---|
| Windows | 计划任务"The Harness host"；不允许建计划任务时，改为"启动"文件夹里的启动项 |
| macOS | LaunchAgent，`~/Library/LaunchAgents/com.lmms-lab.harness.host.plist` |
| Linux | systemd 用户服务 `harness-host.service` |

托盘菜单的 **开机时启动** 和设置项 `agent.autostart` 显示这个登录项是否存在，并可以开关它。在终端里：

```bash
harness host install     # 登录时启动
harness host status      # 系统里现在是否会启动
harness host uninstall   # 不再登录时启动
```

如果你在系统自己的设置里删掉了这个登录项，The Harness 里也显示为关。

在 Linux 服务器上，用户服务要在没有人登录时也运行，需要打开 linger；没打开时 `harness host install` 会提示：

```bash
sudo loginctl enable-linger "$USER"
```

## 托盘

关掉窗口后 The Harness 留在托盘里（macOS 上是菜单栏）。托盘菜单有 **打开 The Harness**、**暂停**（agent 不再被唤醒、不再动作；渠道保持连接，期间发生的事在恢复后处理）、**开机时启动** 和 **退出**（进行中的动作以"已取消"结束，之后 agent 停止，直到你打开应用或再次登录）。只有你必须决定或知道的事才发系统通知：等你批准的请求、花费到达额度、失败或结果未知的动作，以及渠道登录过期。

## 更新

应用从 GitHub Releases 自动更新。每个更新在安装前都用 The Harness 的更新密钥校验，这和代码签名是两回事。

## 不开窗口安装

只能通过 SSH 连接的电脑：

```bash
# Linux（.deb），之后以拥有这个 agent 的用户运行
sudo apt install ./The.Harness_X.Y.Z_amd64.deb
harness host install
sudo loginctl enable-linger "$USER"
```

```powershell
# Windows：为当前用户安装，并打开登录时启动
.\The.Harness_X.Y.Z_x64-setup.exe /S
```

## 卸载

按系统删除应用的方式卸载（Windows：**设置 › 应用**；macOS：把它从 **应用程序** 移到废纸篓；Linux：`sudo apt remove the-harness`，或删掉 AppImage）。在 macOS 和 Linux 上先运行 `harness host uninstall` 删掉登录项。你的数据留在 `~/.harness/`，和 `pip uninstall` 一样。
