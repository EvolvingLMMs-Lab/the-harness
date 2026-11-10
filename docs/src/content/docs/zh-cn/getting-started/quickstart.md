---
title: "快速开始"
description: "从安装到在你自己的电脑上完成一个任务：连接模型，给出任务，在它工作时补充消息，然后回放。"
---

这一页带你从刚装好走到完成一个任务。agent 在它自己的后台浏览器里工作（对话开始时由你选择），从不碰你的鼠标、键盘或窗口。你需要 Python 3.11 或更新版本、Google Chrome，以及一个模型 provider 的 key。示例使用 [OpenRouter](https://openrouter.ai/)，一个 key 就能用大多数模型；[模型和 provider](/docs/zh-cn/configure/models/) 里的任何 provider 用法都一样。

## 1. 安装并连接模型

```bash
npm install -g @lmmslab/harness   # 或： pip install the-harness
harness
```

第一次运行会问三件事：

```text
Which model should the agent use? (the key stays in ~/.harness/config.toml, readable by you only)
   1. OpenRouter  (one key for most models)
   ...
Provider [1-11, default 1 OpenRouter]:
Model [deepseek/deepseek-v4.1-flash]:
OPENROUTER_API_KEY:
```

按回车保留建议的值，然后粘贴你的 key。The Harness 会向 provider 核对 key，保存这些回答，然后打开对话。下面的任务在网页上进行，agent 以文本读取页面，需要时再看画面；能读图的模型两样都能做。

## 2. 给它一个任务

输入：

```text
Go to python.org and find the newest stable Python release. Tell me its version
and the date it was released.
```

每个新对话都会先问在哪里工作：不用环境（只对话）、项目文件夹、后台浏览器、后台应用、你的桌面或独立显示环境。这里选**后台浏览器**。下次会高亮你上一次的选择，按回车即可。第一次时，The Harness 会安装 `browser` 包和它的环境，需要一点时间；之后的任务会立即开始。

它工作时，对话会逐步填满。每行前面是它来自 agent 的哪个部分：`model` 表示模型说的话和它写的程序，`e0` 表示这些程序的运行过程，`env` 表示浏览器。按 **ctrl+t** 在对话上方显示时间轴：一行是模型，一行是它的程序。模型那一行每次调用一个块，两次调用之间是空的；两行同时有块时，说明程序在运行的同时，模型正在考虑下一步。

## 3. 在它工作时补充消息

在它回答之前，输入：

```text
Also give me the link to the release notes.
```

你的消息会立即送到模型。正在运行的程序继续运行，agent 在下一步会考虑你的消息。如果想让它停下，按 **Esc**（它在下一步暂停），输入 `/continue` 继续；想换任务，直接说就行。详见[中途插话和接手](/docs/zh-cn/use/interrupt/)。

完成后，它会回答并等待你的下一条消息。输入另一个任务，或按两次 **Ctrl+C** 离开；对话会留在 session host 里，直到你用 `/end` 结束它。

## 4. 从脚本做一个任务

```bash
harness run "What is the newest stable Python release? Answer with its version only." -p --workspace browser
```

`harness run` 做一个任务然后结束；`-p` 只打印答案，`--json` 把每个事件打印为一行 JSON。更多内容见[用 CLI 运行](/docs/zh-cn/use/cli/)。

## 5. 回看运行

使用 `harness replay RUN` 查看终端记录，或加上 `--json` 查看原始事件。

## 下一步

- [在终端里使用](/docs/zh-cn/use/terminal/)：终端里的按键、会话和子 agent。
- [让它学会一个环境](/docs/zh-cn/learn/learn-an-environment/)：让 agent 先学会一个应用或游戏，再在里面工作。
- [权限和隐私](/docs/zh-cn/configure/permissions/)：在让 agent 使用你自己的桌面之前阅读。
