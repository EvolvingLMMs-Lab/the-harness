---
title: "编写反应规则"
description: "规则：一个条件、一个优先级和一个程序，不询问模型就启动；事实；事件 handler。"
---

有事情需要决定时才调用模型，这需要几秒钟。有些事情等不了那么久。**规则**处理这些情况：规则不经过模型，根据 agent 看到的内容做出判断，并立即行动。

一次运行由一个模型和它启动的**单元**组成。模型写的程序是一个单元，程序用 `spawn` 启动的代码和规则的程序也是单元。单元并排运行，各有自己的输出和结果。除非有规则要求，否则没有任何东西按时间运行：没有设置按时间判断的规则的任务根本没有时钟。

程序可以设置规则，agent 可以学到它们（[边工作边学习](/docs/zh-cn/learn/while-working/)），包也可以附带它们。核心程序 API 提供 `set_reflex`、`when`、`watch`、`on`、`drop_reflex`、`facts` 和 `run_controller`。

## 一条规则

```python
def refill():
    open_valve()
    facts.set("refills", facts.get("refills", 0) + 1)

set_reflex("refill", lambda view: view["level"] < 0.2, refill,
           ends=lambda view: view["level"] > 0.8,
           priority=5, min_seconds=2, again_seconds=10)
```

`set_reflex(name, when, do=None, ends=None, priority=0, reads=None, every=None,
min_seconds=0, again_seconds=0, while_holds=False, raises=None)` 设置一条自己行动的规则，即反射：

- **when**：`when(view)` 变为成立时，规则开始。
- **do**：规则开始时启动的程序，作为具有该规则**优先级**的单元运行。优先级高的单元会从优先级低的单元手里接管环境（[见下](#优先级)）。
- **ends**：`ends(view)` 变为成立时，规则自己的程序被结束。没有 `ends` 而设置了 `while_holds=True` 时，`when(view)` 不再成立就结束程序。两者都没有时，程序运行到自己结束。
- **min_seconds** 是程序开始后至少持续的时间，**again_seconds** 是程序结束后规则再次开始前要等的时间。开始和结束的条件是分开的，这两个时间让规则不会在边界上来回切换。
- 规则的程序设置的规则只在该程序运行期间存在。顶层有几条规则，每个程序带着只在它运行时才有意义的规则：运行时的单元就是决策树。顺序和分支是程序自己的代码。

这就是全部词汇。没有节点类型，也没有规划器：模型负责规划，规则负责执行。

### 规则何时被判断

规则说明它读取什么，在这些内容变化时被判断：

```python
set_reflex("door", lambda view: view["facts"].get("door") == "open", go_through, reads="facts.door")
set_reflex("vent", lambda view: view["pressure"] > 3, vent, every=0.5)
```

- `reads` 用点分隔的键写明规则读取 view 的哪些部分。不写时，状态或事实每次变化都会判断该规则。
- `every` 改为按时间判断，每隔这么多秒一次（`True`：按环境自己的频率）。默认周期和最短周期由环境给出。

### 没有程序的规则

规则也可以只发出事件或结束某个东西，就像 guard 那样：

```python
when(lambda view: view["level"] > 0.95, "stop", name="no_overflow")
watch("battery.charge", low=0.1, event="LOW_BATTERY", stops=False)
set_reflex("jam", lambda view: view["jammed"], raises="JAMMED")
drop_reflex("no_overflow")           # drop_reflex() 清除所有规则
```

- `when(predicate, action, name=None, stops=True)`：`predicate(view)` 成立时，结束正在运行的执行。`action` 是 `stop`、`hold`、环境自己的动作，或要发出的事件名。设置 `stops=False` 时它只发出事件，其他一切照常进行。
- `watch(signal, low=None, high=None, event=None, name=None, stops=True)` 在一个数值（view 的一个点分隔键，或 view 的一个函数）超出范围时做同样的事。事件默认为 `<SIGNAL>_OUT_OF_RANGE`。
- `set_reflex(name, when, raises="NAME")` 在开始时发出该事件。`when` 也可以返回要发出的 `Event`，或返回 `{"stop_entry": unit.id}` 来结束那个单元。

会结束执行的规则在执行的每一步被判断。

## 事实

`facts` 是这次运行所知道的、共享的内容：一个小的命名值存储，程序读写它，条件通过 `view["facts"]` 读取它。

```python
facts.set("door", "open")
facts.get("door", "closed")
facts.drop("door")
```

值是普通数据（数字、文本、列表、字典）。把进度记在事实里：被结束后又重新启动的程序就能从已完成的地方继续，而不是从头开始。

## 感知量

条件只读视图、不做调用，所以它只看得到环境报上来的东西。当环境能在自己那边运行代码时（游戏里的
bot、页面里的脚本），模型可以定义环境还要报什么：感知量是一段有名字的、用环境自己的语言写的代码，
环境每次报告状态时把它算出来。

```python
sense("edge_ahead", "...环境自己语言的代码...")        # {"value": ..., "error": ...}
set_reflex("edge", lambda view: view["sensed"]["edge_ahead"], step_back)
get_state()["sensed"]["edge_ahead"]                    # 程序里读到的是同一个值
senses()                                               # 已定义的感知量，含代码和当前值
drop_sense("edge_ahead")
```

同一个定义同时供条件和程序使用，判断也和原来一样快：条件被判断时，值已经在状态里。

worker 在 profile 里声明 `"senses": True` 并提供 `sense`、`senses`、`drop_sense`
三个方法（`core/worker.py`），它的状态里就带有 `"sensed"`。具身类型在 `prompt_features` 里列出
`senses`，它的提示词说明代码用什么语言、能用到什么。

## 优先级

每个单元都有优先级。模型的程序是 0，规则的程序取规则的优先级，用 `spawn(fn, priority=...)` 启动的代码取自己的优先级，没写时取启动它的单元的优先级。

优先级高的单元需要环境时，优先级低的单元的执行在当前位置结束，带着事件 `PREEMPTED` 和它已经做了的事；高优先级单元持有环境，直到自己结束。模型会立即得知，和每个到达它的事件一样（等待结束，正在进行的调用被重新发起）：哪条规则接管了环境、从哪个程序手里、以及当时的状态。接下来做什么由模型决定：再做一次同样的调用，或者做别的。它在此期间启动的东西排在高优先级单元之后，等它结束再继续。

只有明确要求的单元，harness 才会自己重新启动被打断的调用：`spawn(fn, restart=True)`。高优先级单元结束后，它的调用被重新发起，其结果说明重启了几次：`result.restarts`。优先级相同的单元轮流进行，先来的先做。环境把输入划分为通道时，各单元在自己占用的通道上同时行动。

### 能暂停的环境

环境如果能把一个调用正在做的事保持住、之后让它继续，就在 worker 的 profile 里声明 `"pauses": True`，并提供 `pause` 和 `resume` 两个方法（`core/worker.py`）。在这样的环境里，低优先级的调用不会结束：环境让它停在原地，高优先级单元行动，等该单元结束，这个调用接着进行。它所在的程序也接着进行，模型不会被询问。于是一次反应只花它本身的时间，长程序和守护它的反射可以并存。trace 里记录 `call_paused` 和 `call_resumed`。`uninterruptible()` 照常有效，要求了 `restart=True` 的单元仍然被重新启动。具身类型在 `prompt_features` 里列出 `pauses`，提示词据此说明适用哪一种。

## 树

一条一条设置的规则彼此互不知道。树把它们放进同一个结构里，和游戏角色的行为树一样：

```python
def step_back(): ...
def refill(): ...
def work(): ...

subtree("keep_clear", branch(lambda view: view["distance"] < 0.2, do(step_back)))

tree(select(
    ref("keep_clear"),
    branch(lambda view: view["level"] < 0.2, do(refill), ends=lambda view: view["level"] > 0.8),
    do(work),
))
```

| 节点 | 作用 |
| --- | --- |
| `select(a, b, ...)` | 第一个没有失败的子节点持有环境。排在正在运行的子节点之前的某个子节点不再失败时，由它接管，原来运行的那个被结束。 |
| `sequence(a, b, ...)` | 子节点一个接一个。有一个失败它就失败；被外部结束后，从第一个子节点重新开始。 |
| `branch(begins, child, ends=None, min_seconds=0, again_seconds=0, while_holds=False)` | 从 `begins(view)` 成立起运行子节点，带有规则的其余条件。 |
| `do(program)` | 叶子：把程序作为一个单元启动。程序正常结束时成功。 |
| `check(condition)` | 叶子：条件成立时成功。 |
| `raise_event(name)` | 叶子：向模型发出一个事件，它所在的分支每开始一次发一次。 |
| `ref(name, **arguments)` | 用 `subtree(name, node)` 命名的那一部分，出现在每个引用它的地方。`node` 可以是一个根据参数生成这一部分的函数。 |

`tree(root, name="tree", priority=1, every=None)` 设置一棵树，替换同名的树。

- **节点的位置就是它的优先级。** 树内部没有任何数字。树的程序以树的 `priority` 持有环境（1：高于模型自己的程序；模型的程序被接管时会被告知）。
- **共享。** 放在树的某一部分之上的条件，对它下面的一切都成立。被多个行为使用的部分只需在一处修改：重新定义一个子树，所有使用它的地方一起改变。
- **自己运行。** 同一时间只有一条分支在运行。被接管的部分会被结束（它的程序被取消），树再次被判断时自己回到那条分支：进度要记在 facts 里。树自己的程序结束时只做记录，不会引起对模型的调用。
- **模型会被告知的事。** 某个叶子的程序失败了而树里没有别的部分接手（事件 `BRANCH_FAILED`，在该叶子再次成功之前只告知一次）；模型自己的某个程序被打断；某棵树被一个不可打断的程序挡住。
- 树和规则一样被判断：状态或 facts 每次变化时、它的某个程序结束时，或者每 `every` 秒。程序失败的叶子 2 秒内不会再被启动。

`reflexes()` 列出规则和树，每棵树带着它的节点以及各节点上一次的结果。`drop_reflex("tree")` 移除一棵树并结束它启动的东西。

### 不被打断的程序

模型的程序优先级是 0，所以优先级更高的规则会从它手里接管环境。动作不能被中途打断的程序先说明这一点：

```python
uninterruptible()
leave_the_danger()
```

从这次调用到程序结束，不管优先级多少，任何规则的程序和其他单元都不会从它手里接管环境。期间条件成立的规则不会行动：程序结束后重新判断，条件仍然成立才行动；模型会被告知一次该规则被挡住（事件 `HELD_BACK`），它可以取消这个程序让规则行动。仍然会结束这个程序的：取消它、它的调用到时限、结束执行的规则、episode 结束。两个这样的程序轮流进行。

`reflexes()` 按优先级从高到低列出现有的规则及其优先级。

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
