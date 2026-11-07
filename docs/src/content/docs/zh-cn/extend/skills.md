---
title: "编写 skill"
description: "使用 agent 已有的 skill，然后编写你自己的：一份清单、几行 Python，以及一个检查自身结果的闭环。"
---

**skill** 是 agent 的程序可以调用的一组函数，例如 `click`、`press`、`read_page` 或 `probe_inputs`，再加上告诉模型如何使用它们的文字。skill
随核心和包一起提供；你可以打开或关闭它们，也可以自己编写。

## 使用 skill

每个 skill 都列在 [skill 参考](/docs/zh-cn/reference/skills/)中，附有它的函数以及模型读到的关于它们的说明。一个 skill
可能因为配置没有包含它而关闭，也可能因为它需要这台电脑没有运行的服务而关闭；一次运行的 `manifest.json` 列出它拥有的 skill，以及其他 skill 关闭的原因。要修改一次运行的 skill：

```toml
[overrides.agent.skills]
enable = ["agents", "checklist"]
disable = ["verify"]
```

在 app 中，**Settings → Packages** 为新的对话打开或关闭某个包的 skill。

agent 在它的程序中调用 skill。大多数函数以**有界执行**的方式运行：它们在有限的时间内动作，受已设置的 guard 和反应规则约束，并以一个事件结束（`COMPLETED`，或使它们停下的原因），程序可以处理这个事件，也可以把它交给模型。

## 你自己的 skill

下面这个 skill 在 `desktop` embodiment（你的电脑）上用 Ctrl+S 保存文档，并检查是否已保存。一个 skill 是一个文件夹：

```text
savefile/
├── skill.toml
├── __init__.py
└── prompt.md
```

`skill.toml` 说明它是什么：

```toml
name = "savefile"
summary = "Save a document with Ctrl+S and check that it was saved."
layer = "base"
mixin = "skills.savefile:SaveFile"
exports = ["save_file"]
embodiments = ["desktop"]
```

`__init__.py` 包含函数，它们是一个类的方法，这个类被混入 agent 的会话，所以它们可以在 `self` 上调用其他 skill 的函数。这里函数把会话交给一个闭环（见下文），闭环的关键字参数会成为它的属性：

```python
from harness.sdk import ClosedLoop

class Save(ClosedLoop):
    def unsaved(self):
        return any(row["id"] == self.window and "*" in row["title"]
                   for row in self.session.windows())

    def confirm(self):
        return self.unsaved() or "nothing to save"

    def do(self):
        self.session.press("ctrl", "s", window=self.window)
        self.session.wait(0.5)

    def check(self):
        return not self.unsaved() or "the title still shows unsaved changes"

class SaveFile:
    def save_file(self, window):
        return Save(session=self, window=window)
```

`prompt.md` 是模型读到的关于它的说明，skill 打开时会加入系统 prompt：

```markdown
save_file(window) -> result   save the document in a window (an id of windows()) and
                              check that it was saved; result.ok, result.reason
```

## 闭环

`ClosedLoop` 是 skill 执行一个动作并确认它确实发生的方式，适用于任何环境。继承它并填写各个步骤：

| 步骤 | |
|---|---|
| `confirm()` | 每次尝试之前：目标符合预期时返回 `True`，否则返回不应执行的原因 |
| `do()` | 动作 |
| `check()` | 动作之后：世界按预期改变时返回 `True`，否则返回原因 |
| `recover(reason)` | 检查失败后、两次尝试之间：重新观察，退一步 |

每个步骤返回 `True` 或一个原因；抛出 `Stop(reason)` 会立即结束循环。`tries`（默认 3）和 `max_seconds`（默认 30）为它设定上限。调用这个类会运行循环，并返回一个带有
`ok`、`reason`、`tries`、`seconds` 和 `detail` 的结果。每次尝试结束都会作为新消息告知模型，模型可以在 skill
运行期间重新观察。agent 在学习时为自己编写的 skill 也是闭环（[边工作边学习](/docs/zh-cn/learn/while-working/)）。

## 试一试

把这个文件夹放进一个包（[编写包](/docs/zh-cn/extend/packages/)），并从它所在的位置安装，这样你的修改会立即生效：

```bash
harness install ./my-package --link
harness list my-package       # what The Harness found in it: savefile
harness run "Write a line in Notepad and save it." --workspace apps
```

[时间轴](/docs/zh-cn/use/replay/#时间轴)在程序的泳道上显示每次 `save_file` 调用，trace 记录每次尝试。

## 清单

| 键 | |
|---|---|
| `name` | skill 的名字 |
| `summary` | 一行，显示在列表中 |
| `layer` | `base` 表示 agent 直接使用的 skill；`reactive`、`handlers` 和 `learned` 表示其他类型 |
| `mixin` | `module:Class`，其方法会成为函数的那个类 |
| `exports` | 程序可以调用的函数 |
| `embodiments` | 它适用的环境类型：`desktop`、`browser`、`game`、`robot` |
| `needs`、`needs_any` | 它运行所必需的服务类型（全部，或其中之一） |
| `requires` | 它使用的其他 skill |
| `requirements` | 它需要的 Python 包，安装到它自己的文件夹中 |
| `order` | 它在 skill 中的位置，在会话中和在 prompt 中 |
| `optional` | 默认关闭，除非配置打开它 |

[配置键参考](/docs/zh-cn/reference/configuration/)列出了每个键。

## 需要模型的 skill

调用一个自己运行的模型（例如分割模型）的 skill，在 `needs` 中写明服务类型，并通过会话的客户端调用它。skill
本身仍是普通的 Python；模型的重量级依赖属于服务，服务会在一次运行第一次使用这个 skill 时获得自己的环境（[服务](/docs/zh-cn/configure/services/)）。服务不可用时，skill
会被关闭，它的文字也会从 prompt 中移除。

## Agent Skills

包含 `SKILL.md` 的文件夹（Agent Skills 格式）不需要代码：agent 看到它的名字和描述，在任务需要时读取它的说明和文件。
[接入 MCP 服务器和 Agent Skills](/docs/zh-cn/extend/mcp/) 介绍了它们。
