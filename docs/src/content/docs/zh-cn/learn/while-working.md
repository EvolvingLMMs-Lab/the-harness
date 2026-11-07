---
title: "边做边学"
description: "agent 在普通运行中也会继续学习：它提出什么、条目如何被测试和接纳，以及如何为评测冻结 library。"
---

开启了学习的 agent 不会在任务开始后停止学习。工作时，模型可以为它的 library 提出一个条目（一条笔记、一条记忆、一个带测试的 skill、一条反应规则），每个 episode 结束后，一次简短的反思还会再提出一个。这就是**被动**学习。它使用与[主动运行](/docs/zh-cn/learn/learn-an-environment/)相同的 library 和相同的证据规则；只是触发方式不同。

## 开启

```toml
[overrides.agent.runtime.library]
path = "$HARNESS_HOME/libraries/my-app"   # or a path relative to this file
learn = "on"            # "off" (the default): read one frozen version, learn nothing
trigger = "passive"     # "active": a run whose goal is to learn
evidence = "test"       # "validated": only held-out runs admit; run entries wait
load = "proposed"       # the lowest evidence an entry needs to be loaded
replay = true           # test the provisional entries again when each run starts
reflect = true          # reflection after each episode proposes one entry
```

core task 用 `--library` 绑定学习库，用 `--learn-while-working` 明确开启写入。冻结运行只读取固定快照；用 `harness library show PATH` 检查条目。

## 条目如何进入 library

1. **提出。** 模型在程序里提出一个条目，代码类条目要附带测试：

   ```python
   library.propose("note", "save_shortcut", "Ctrl+S saves without a dialog in this editor.")
   library.propose("skill", "open_inventory", code, test)
   ```

2. **验证。** 可执行候选的源码、测试、附件和依赖固定为一个版本。可信宿主试跑通过后标记为 `provisional`。没有兼容的试跑环境时，候选保留在待验证状态。
3. **启用。** 内核在程序边界加载通过准入的版本。运行记录实际启用的版本。同名新版本验证失败或在发布前取消，当前版本继续使用。
4. **复测和评估。** 后续运行独立复测通过后可标记为 `replayed`。成对开发评估确认该版本实际启用并带来提升后，才标记为 `validated`。笔记和记忆保留观察来源，代码的自测结果可供修订时参考。

## 写成闭环的 skill

agent 编写的 skill 通常是一个**闭环**：确认目标、执行、检查世界是否发生了变化、重试或给出原因。agent 通过继承 `ClosedLoop` 来写：

```python
class open_inventory(ClosedLoop):
    """Open the inventory."""
    tries = 2

    def confirm(self):
        return "open already" if inventory_open() else True

    def do(self):
        press("e")

    def check(self):
        return True if inventory_open() else "no inventory after E"
```

调用 `open_inventory()` 返回一个结果，包含 `ok`、`reason`、`tries` 和 `seconds`。每次尝试结束对模型来说都是新情况，模型可以在 skill 运行期间重新查看。完整接口见[编写 skill](/docs/zh-cn/extend/skills/)。

## 记忆

一套接口同时管这一局看到了什么、在哪里（工作记忆），和以前的运行留下的东西（library）：

```python
remember("window", "the totals are in the last column", where="Quarterly report.xlsx")
remember("tree", where=(12, 64, -30))              # 位置：在附近再看到，就是同一棵树
remember("door", "the code is 4711", name="side_door", keep=True)   # 同时成为 library 条目
recall("totals column")                            # 这一局的记录和 library 的条目
recall(kind="tree", near=(0, 64, 0))               # 最近的在前
```

每个条目字段相同：`scope`（`run` 或 `library`）、`kind`、`name`、`text`、`where`、`evidence`、`source`、`version`。这一局的条目证据为 `seen`；library 条目是它的证据档位。这一局的记忆和它的子 agent 共用，每次改动都是 trace 里的一条 `world` 记录，`recall()` 找到了什么也有记录；每个程序结束后模型会在 "Memory:" 下先看到没有位置的笔记，再看到最近的地点。library 的记忆条目是这次运行开始时的那些，加上运行中收下的。用 `near` 按距离排序，用 `radius` 只查有位置的条目。不传这两个参数时，环境是否提供当前位置不会改变搜索范围。`keep=True` 和其他条目一样经过学习器，所以只在 library 学习时有效。`harness library show RUN`、`/library`、app 里对话菜单的 **记忆** 和 `conversation.memory()` 把一次运行的记忆和它开始时的 library 条目一起显示。旧 trace 可能只有清单里的条目名和版本。

## 使用记录

library 索引里每个条目的那一行带着它的证据：测试运行和使用记录。每结束一个 episode，这次运行自己的程序里条目闭环的每个结果（怎样结束的，失败时为什么；不含它的测试和重测）都算作这个条目的一次使用；`harness library show` 在测试旁边列出使用次数和成功率。使用记录是证据，不是条目，所以不改变 library 的版本。`uses = "learn"`（默认）在学习的运行中计数，`"on"` 在冻结的 library 上也计数（练习），`"off"` 不计。

## 为评测冻结

只有 agent 在运行期间没有变化，结果才可比较。评测时让 `learn` 保持关闭（默认）：运行只读取 library 的一个冻结版本，什么也不学。如果 library 在配置加载之后发生了变化，运行会拒绝启动 episode。

如果只想保留有帮助的条目，设置 `evidence = "validated"`：运行中学到的条目作为候选等待，只有当 library 加上这个条目后在留出任务上的得分比没有它时更高，它才会被接纳。

## 磁盘上的结构

```text
<library>/
├── notes/*.md  memory/*.md  skills/*.py  reactive/*.py
├── tests/<name>.py          a code entry's test
├── skills/<name>.files/     a skill's attachments, such as a small model it trained
├── candidates/              entries waiting for held-out validation
└── index.json               evidence, origin, tests, uses and history of every entry
```

library 就是一个普通文件夹：复制它，就能在另一台电脑上复用 agent 学到的东西；也可以让多个实验的 `path` 指向同一个 library。
