---
title: "编写反应规则"
description: "规则：一个条件、一个优先级和一个程序，不询问模型就启动；事实；事件 handler。"
---

有事情需要决定时才调用模型，这需要几秒钟。有些事情等不了那么久。**规则**处理这些情况：规则不经过模型，根据 agent 看到的内容做出判断，并立即行动。

一次运行由一个模型和它启动的**单元**组成。模型写的程序是一个单元，程序用 `spawn` 启动的代码和规则的程序也是单元。单元并排运行，各有自己的输出和结果。除非有规则要求，否则没有任何东西按时间运行：没有设置按时间判断的规则的任务根本没有时钟。

程序可以设置规则，agent 可以学到它们（[边工作边学习](/docs/zh-cn/learn/while-working/)），包也可以附带它们。核心程序 API 提供 `rule`、`when`、`watch`、`on`、`clear_rules`、`facts` 和 `run_controller`。

## 一条规则

```python
def refill():
    open_valve()
    facts.set("refills", facts.get("refills", 0) + 1)

rule(lambda view: view["level"] < 0.2, refill,
     ends=lambda view: view["level"] > 0.8,
     priority=5, name="refill", min_seconds=2, again_seconds=10)
```

`rule(begins, program=None, ends=None, priority=0, name=None, reads=None, every=None,
min_seconds=0, again_seconds=0, while_holds=False, raises=None)`：

- **begins**：`begins(view)` 变为成立时，规则开始。
- **program**：规则开始时启动的程序，作为具有该规则**优先级**的单元运行。优先级高的单元会从优先级低的单元手里接管环境（[见下](#优先级)）。
- **ends**：`ends(view)` 变为成立时，规则自己的程序被结束。没有 `ends` 而设置了 `while_holds=True` 时，`begins(view)` 不再成立就结束程序。两者都没有时，程序运行到自己结束。
- **min_seconds** 是程序开始后至少持续的时间，**again_seconds** 是程序结束后规则再次开始前要等的时间。开始和结束的条件是分开的，这两个时间让规则不会在边界上来回切换。
- 规则的程序设置的规则只在该程序运行期间存在。顶层有几条规则，每个程序带着只在它运行时才有意义的规则：运行时的单元就是决策树。顺序和分支是程序自己的代码。

这就是全部词汇。没有节点类型，也没有规划器：模型负责规划，规则负责执行。

### 规则何时被判断

规则说明它读取什么，在这些内容变化时被判断：

```python
rule(lambda view: view["facts"].get("door") == "open", go_through, reads="facts.door")
rule(lambda view: view["pressure"] > 3, vent, every=0.5)
```

- `reads` 用点分隔的键写明规则读取 view 的哪些部分。不写时，状态或事实每次变化都会判断该规则。
- `every` 改为按时间判断，每隔这么多秒一次（`True`：按环境自己的频率）。默认周期和最短周期由环境给出。

### 没有程序的规则

规则也可以只发出事件或结束某个东西，就像 guard 那样：

```python
when(lambda view: view["level"] > 0.95, "stop", name="no_overflow")
watch("battery.charge", low=0.1, event="LOW_BATTERY", stops=False)
rule(lambda view: view["jammed"], raises="JAMMED")
clear_rules("no_overflow")           # clear_rules() 清除所有规则
```

- `when(predicate, action, name=None, stops=True)`：`predicate(view)` 成立时，结束正在运行的执行。`action` 是 `stop`、`hold`、环境自己的动作，或要发出的事件名。设置 `stops=False` 时它只发出事件，其他一切照常进行。
- `watch(signal, low=None, high=None, event=None, name=None, stops=True)` 在一个数值（view 的一个点分隔键，或 view 的一个函数）超出范围时做同样的事。事件默认为 `<SIGNAL>_OUT_OF_RANGE`。
- `rule(begins, raises="NAME")` 在开始时发出该事件。`begins` 也可以返回要发出的 `Event`，或返回 `{"stop_entry": unit.id}` 来结束那个单元。

会结束执行的规则在执行的每一步被判断。

## 事实

`facts` 是这次运行所知道的、共享的内容：一个小的命名值存储，程序读写它，条件通过 `view["facts"]` 读取它。

```python
facts.set("door", "open")
facts.get("door", "closed")
facts.drop("door")
```

值是普通数据（数字、文本、列表、字典）。把进度记在事实里：被结束后又重新启动的程序就能从已完成的地方继续，而不是从头开始。

## 优先级

每个单元都有优先级。模型的程序是 0，规则的程序取规则的优先级，用 `spawn(fn, priority=...)` 启动的代码取自己的优先级，没写时取启动它的单元的优先级。

优先级高的单元需要环境时，优先级低的单元的执行在当前位置结束，带着事件 `PREEMPTED` 和它已经做了的事；高优先级单元持有环境，直到自己结束。模型会立即得知，和每个到达它的事件一样（等待结束，正在进行的调用被重新发起）：哪条规则接管了环境、从哪个程序手里、以及当时的状态。接下来做什么由模型决定：再做一次同样的调用，或者做别的。它在此期间启动的东西排在高优先级单元之后，等它结束再继续。

只有明确要求的单元，harness 才会自己重新启动被打断的调用：`spawn(fn, restart=True)`。高优先级单元结束后，它的调用被重新发起，其结果说明重启了几次：`result.restarts`。优先级相同的单元轮流进行，先来的先做。环境把输入划分为通道时，各单元在自己占用的通道上同时行动。

## Handler

```python
covered = []

def remember_cover(trace):
    if trace.event.detail.get("reason") == "covered":
        covered.append(trace.event.kind)
        return True
    return False

on("SKILL_ERROR", remember_cover)
```

`on(event, handler)` 在一次执行以该事件结束时调用 `handler(trace)`。返回 `True`（或不返回）表示已处理；返回 `False` 则把它交给模型。Handler 与规则共用预算和限制。程序可以根据 handler 记录的状态行动。

## 控制器

`run_controller(fn, until=None, max_seconds=None)` 在每一步应用 `fn(view)` 返回的命令，用于视觉伺服和其他快速回路。它是一次有界执行：规则对它生效，它以一个事件结束。

## 规则要守的规则

条件和控制器必须快，不能打开文件、使用网络、启动进程、睡眠或调用模型。它们共用每个周期的一份预算 `runtime.reactive_budget_ms`（默认 5 ms）。违反这些规则会产生 `REACTIVE_FAULT` 事件，该规则被移除。规则的程序是普通代码，没有这些限制。

每条命令仍然要通过环境自己的检查，不管是谁写的，格式错误或超出范围的命令都会被拒绝。延迟发送的命令在发出前可以被否决。一旦发出，它的回执属于发出它的那次执行。回执丢失不会引起自动重试。

## 在 skill 中

Skill 用同样的 `rule`、`when`、`watch` 和 `on` 在会话的反应层 `self.reactive` 上注册规则：

```python
class Footing:
    def keep_footing(self):
        """End whatever moves when the ground ahead is gone."""
        self.reactive.when(lambda view: view["ground_ahead"] is False, "stop", name="no_gap")
```

## 在包中

包可以把环境的规则作为 skill 附带（其函数在会话开始时设置规则），也可以作为 library 的 reactive 条目附带。设置 `knowledge = "learned"` 时，agent 不带包里手写的规则启动，而是学习自己的规则（[让它学习一个环境](/docs/zh-cn/learn/learn-an-environment/)）。
