---
title: "Space"
description: "agent 工作的每个地方都是一个 space，经 Agent Space Protocol 进入：核心怎样进入、结果说明什么、事件怎样到达反射、怎样选择 space。"
---

agent 工作的每个地方都是一个 **space**：项目文件夹、这台电脑的桌面、后台浏览器、一个
benchmark、聊天渠道里的一个群。space 有状态、决定每个动作得到什么结果的定律，以及参与者（agent、人、
别的 agent）。The Harness 通过一个开放协议进入每个 space：[Agent Space Protocol](https://github.com/agent-space-protocol/agentspaceprotocol)
（ASP），用它的 Python SDK，这是核心唯一的依赖（和核心一样只用标准库）。

四层各在原位：语言模型、程序和学到的策略通过 space 的动词行动，反应层回应 space 推来的事件，
安全层仍在环境的边界上（worker 的 shield，或自己说协议的 space 的定律）。tick 仍然协调它们。

## 协议的承诺

space 满足三条性质，参与者只通过协议就能检验（`agent-space check`）：

- **自洽**：观察到的东西说得通，并写明什么时候确认的。
- **完备**：每个带 ID 的动作恰好得到一个终结结果，同一个 ID 再发不会做两次。
- **有记录**：动作、结果和事件按序号追加进记录。

结果是五种之一，agent 据此决定等、重试还是换办法：

| 结果 | 含义 |
|---|---|
| done（完成） | 发生了；给出结果 |
| refused（拒绝） | 什么都没发生（没有权限、参数不对、依据的观察过期、shield 拦下） |
| failed（失败） | 做了但没做成；列出已经发生的效果 |
| cancelled（取消） | 按要求停下了；列出停下之前的效果 |
| unknown（不确定） | 可能发生也可能没发生：写明知道的部分和没确认的部分 |

程序拿到完成的动作的结果；其他结果抛出 `ActionFailed`，它的 `outcome.end` 和
`outcome.reason.code` 说明是哪种、为什么。

## 核心怎样进入 space

| space | 怎样进入 |
|---|---|
| worker（workspace、computer、browser、一个 benchmark） | **转换层**在 worker 旁边把它原样包成 space；对话以主人身份进入，它的程序以成员身份进入 |
| 自己说协议的 space（聊天渠道的账号、inspector 的测试 space、房间） | 按地址：`--workspace space --space ws://...` |

转换层（`python -m harness.space.translate`）把 worker 协议对应到 space：shield 放行的一步是完成，
被拦下的是拒绝并带原因，worker 出错时输入可能已经到达环境的一步是不确定；依据过去观察的一步作为
过期被拒绝；评分只给评测者角色；worker 自己告诉的事成为事件。包在 `spaces/<name>.toml` 里声明它的
worker 的 space 提供什么（[环境](/docs/zh-cn/extend/environments/#它自己的-space)）：动词、动词的效果
类别（read、change、send、spend、irreversible），以及由一步组成的动词，比如项目文件夹的 `run`，
它持续到命令结束。

## 事件和反应

space 推来的东西先到 agent 这一侧，最后才到模型：

1. **记录。** 每个事件成为对话 trace 里的一条 `space_event` 记录，带协议版本和 space 的序号
   （[Trace](/docs/zh-cn/reference/traces/)）。
2. **反射。** 事件种类可以作为反射的条件：`set_reflex("greet", "chat.message", program)` 在这种事件
   到来时运行 `program(event)`。agent 自己的在场产生的事件不触发任何东西。
3. **模型。** 没有反射接住的事件留在记录里，除非 agent 出厂就有的三条反应之一叫醒模型：

| 反应（`runtime.reactions`） | 什么时候 |
|---|---|
| `addressed` | 针对 agent 的事件（点名或提到它、回复它、环境告诉它的事） |
| `failed` | 结果是失败或不确定、且没有模型的程序在等的动作（反射的动作） |
| `approval` | 动作在等同意：提醒主人 |

每条都可以关掉（`runtime.reactions = {addressed = "off"}`），都不能删除。

## 按词汇行动

没有专门技能的 space 只通过它的词汇使用，就像把 MCP 服务器的工具交给模型：每个动词是程序里的
一个函数 `namespace.verb(object, **args)`，模型的上下文里每个动词一行（参数、效果类别和简介），
再加上事物的种类和事件。`observe()` 给出结构，`space_page(name)` 在程序需要时给出词汇里的一页
说明。有专门技能的 space（桌面、项目文件夹）照用它们的技能，按词汇的命名空间找到。

## 选择 space

```bash
harness run "turn the lamp on" --space ws://127.0.0.1:7777
harness --workspace space --space ws://127.0.0.1:7900
```

在 Python 里是 `Host.task(text, space="ws://...")`。包可以提供自己的 space：
`python -m harness.space.serve NAME` 运行它（聊天渠道就是这样的 space：
[写一个聊天渠道](/docs/zh-cn/extend/channels/)），人可以用 inspector 的 `agent-space tui ADDRESS` 进入同一个 space 并行动。
