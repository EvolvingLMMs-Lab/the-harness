---
title: "保留 agent 身份"
description: "给 agent 一个长久的名字和人设，让多个身份互不相干，并选择某条命令或终端对话以哪个身份运行。"
---

**身份**是一个长久存在的 agent：它的名字、人设、关于你的记忆、对话和学到的东西。每个身份是一个你可以打开、编辑的文件夹。身份由可选的 `agent` 包提供，第一次使用 `harness agent` 时会自动安装。

## 第一个身份

第一个身份的 id 是 `default`。和它说话：

```sh
harness agent say "Remember that pull requests are written in English"
harness agent
```

`harness agent say` 是一轮对话；只输入 `harness agent` 会在终端里打开对话。旧写法 `harness agent "一句话"` 在一个版本内仍然可用，并提示改用 `say`。

## id 和名字

每个身份有一个 **id** 和一个**显示名**。id 由字母、数字、`_` 和 `-` 组成，是文件夹名，创建后不能改。显示名可以用任何语言，随时可改：

```sh
harness agent new work --name "工作助手"
harness agent rename "小林" --identity work
harness agent list
```

`harness agent new ID --from OTHER` 复制另一个身份的人设、技能和反应，不复制记忆和对话。`--card FILE` 读取角色卡（Character Card V3、V2 或 V1，`.png` 或 `.json`）：名字写进 `IDENTITY.md`，描述、性格和 system prompt 写进 `SOUL.md`，PNG 角色卡本身作为头像。角色卡的其他字段忽略。

## 命令作用于哪个身份

每条命令都只作用于一个身份。`--identity ID` 指定；不指定时用当前身份，当前身份由 `harness agent use ID` 选定。只有一个身份时就是它。有多个身份且都没选时不会去猜：在终端里命令会先问你用哪个，在脚本里会报错并说明要给什么。

```sh
harness agent use work
harness agent about
harness --identity work
```

装了 `agent` 包以后，`harness`（终端对话）也以某个身份运行：状态行显示身份的名字，它开始的每个对话都记为这个身份的对话。

## 身份文件夹

每个身份在 `$HARNESS_HOME/agents/ID/`（`~/.cache/harness/agents/ID/`）：

| 文件 | 内容 |
|---|---|
| `IDENTITY.md` | 显示名和头像 |
| `SOUL.md` | 性格、语气和界限，每轮开始时读取 |
| `USER.md` | 它对你的了解，每轮开始时读取 |
| `MEMORY.md`、`memory/` | 记忆：每条一个文件，外加索引 |
| `library/` | 它自己的学习库 |
| `sessions/` | 它的对话 |
| `identity.json` | 机器数据：公钥、模型选择和格式版本 |

`SOUL.md`、`USER.md` 和 `memory/` 里的文件可以用任何编辑器修改，下一轮就会读到。一条记忆最多 1200 个字符。身份之间默认什么都不共享：一个身份看不到另一个的记忆、对话和学习库。

每个身份还有一对密钥，环境用它来认出这个身份。私钥放在身份文件夹旁边，只有你能读，永远不会进入分享包。你不需要管理它；`harness agent about -v` 显示它的指纹。

## 一个身份只在一处活着

一个身份同一时间只在一个会话 host 里运行。同一台电脑、同一个数据目录下的第二个终端或 app 会接入同一个身份；在第一个还在运行时从另一个数据目录打开它会被拒绝，并说明是哪个进程、哪个目录占着它。那个进程结束后（包括崩溃），身份就空出来了。

## 旧版本的身份

新版本第一次打开旧版本的身份时，会把 instructions 移进 `SOUL.md`，把 `memory.json` 的每一条移进 `memory/`，标为私人。默认身份还没导入的设置（`personal.about` 和 `personal.instructions`）写进 `USER.md` 和 `SOUL.md`。不删除任何东西：`identity.json` 保留旧版本读取的内容（原文件另存为 `identity.v1.json`），`memory.json` 和对话保持原样，旧版本仍然能打开它们。退回旧版本后，它记得的是升级前记得的内容。

## 删除身份

```sh
harness agent delete work
```

它会列出将被删除的对话和记忆，并要求你输入 id 确认；脚本里用 `--yes`。删除会移除文件夹和密钥，无法撤销。

## 在 Python 里

`harness.sdk.Agent` 和命令一一对应：

```python
from harness.sdk import Agent

work = Agent.new("work", name="工作助手")
print(work.say("What do you remember about me?")["answer"])
Agent.use("work")
print(Agent().name, Agent.list())
```

不带 id 的 `Agent()` 是当前身份；有多个身份且都没选时会抛出异常。
