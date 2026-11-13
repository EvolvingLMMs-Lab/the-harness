---
title: "说明文件"
description: "AGENTS.md：你和项目要告诉每个对话的事，读取方式和 Codex、Claude Code 一样。"
---

说明文件是一份 Markdown，每个对话在开始任务之前都会读它。里面可以写项目怎么构建和测试、有哪些约定、改动完成前要检查什么，也可以写你喜欢的工作方式。The Harness 像 Codex 那样读取 `AGENTS.md`；为 Claude Code 写的仓库（`CLAUDE.md`）不用改也能用。

## 读取哪些文件

- **你自己的：** `~/.harness/AGENTS.md`；如果 `~/.harness/AGENTS.override.md` 有内容，就读它。你发起的每个对话都会读，不管在哪里工作。
- **项目的：** 从项目根一直读到对话所在的文件夹。
  - 项目根是往上最近的、含有 `.git` 的文件夹；找不到时只读这个文件夹本身。
  - 每个目录读 `AGENTS.override.md`、`AGENTS.md`、`CLAUDE.md` 中第一个有内容的。
  - 目录里的 `CLAUDE.local.md` 接在它后面读。
  - 项目根以上的都不读。
- **文件夹下面的：** 某个子目录有自己的说明文件时，程序第一次在那里读写文件或运行命令，模型会在下一次调用时收到它，每个对话只给一次。

离文件夹越近的文件排得越靠后，它的规则优先于更上层的。没有文件夹的对话（桌面、浏览器、游戏）只读你自己的。实验和基准测试一个都不读。

## 模型看到什么

这些文件放在对话第一条消息的开头、任务之前，每份前面标出它的路径：

```
# AGENTS.md instructions for /home/you/project

<INSTRUCTIONS>
(from ~/.harness/AGENTS.md)
...

--- project-doc ---

(from AGENTS.md)
...
</INSTRUCTIONS>
```

对话压缩上下文后它们仍然保留。文件夹下面的说明文件在压缩之后，程序再碰到时会重新告知。新对话会把所有文件重新读一遍，所以修改从下一个对话开始生效。

## 引入和注释

- 文件里的 `@path` 会引入另一个文件。路径相对于写这一行的文件，`~` 表示你的主目录。
- 最多连续引入四层。代码片段或代码块里的 `@` 只是文字。
- 只引入项目根或 `~/.harness` 里面的文件；别处的引入保留为文字，并会提醒你。
- 单独占行的 HTML 注释会被去掉，写给人看的备注不会进入模型的上下文。

## 大小

你自己的和项目的各有 `instructions.max_bytes`（32768 字节）：

- 超过上限的那个文件会被截断，它后面的文件不再读取。
- 文件夹下面按需读取的文件，超过 40,000 字符的部分会被截掉。
- 超过 4 MiB 的文件不读。

有内容被截断时，模型会被告知用 `read_file` 读剩下的部分，你也会在对话里看到提醒。

## 查看和编辑

- **终端对话：** 对话开始时显示 `instructions: AGENTS.md, ... (6.2 KB)`。
  - `/instructions` 列出读到的文件；`/instructions N` 用编辑器打开第 N 个。
  - `/init` 让 agent 写项目的 `AGENTS.md`；已经有的话，它会先说要改哪里，问过你再改。
- **命令行：** `harness instructions [FOLDER]` 说明在那里开始的对话会读哪些文件，以及其他文件为什么没读；加 `--json` 输出同样内容的 JSON。
- **Trace：** 每个对话都会记一条 `instructions` 记录，`harness run --json`、App 和 Python API 都会和其他记录一起收到。

## 设置

在 `~/.harness/config.toml` 的 `[instructions]` 下，或在 `/settings` 里：

| 键 | 默认值 | 作用 |
| --- | --- | --- |
| `instructions.load` | `all` | `all`：你自己的和项目的；`user`：只读你自己的；`off`：都不读 |
| `instructions.files` | `AGENTS.override.md, AGENTS.md, CLAUDE.md` | 每个目录依次尝试的文件名 |
| `instructions.root_markers` | `.git` | 用来识别项目根的标记；留空则只读文件夹本身 |
| `instructions.max_bytes` | `32768` | 开始时读取的字节数，你自己的和项目的各算各的；`0`：都不读 |
| `instructions.exclude` | 无 | 永远不读的文件，用路径模式表示，例如 `*/vendor/*/AGENTS.md` |

`harness --bare` 和 `harness run --bare` 在这次对话里不读任何说明文件。

你委派的 agent（例如 Claude Code 或 Codex）会读它们自己的说明文件，The Harness 不会把自己的说明转给它们。
