---
title: "编写反应规则"
description: "guard、反射和事件 handler：在一个控制周期内做出反应、不询问模型的规则。"
---

有事情需要决定时才调用模型，这需要几秒钟。有些事情等不了那么久：机械臂快要撞上桌面、游戏里的怪物、点击过程中弹出的对话框。**反应规则**处理这些情况。规则每个控制周期（每秒几十次）运行一次，不经过模型，根据
agent 看到的内容做出判断，并立即行动。

共有三种：

| 种类 | 作用 | 设置方式 |
|---|---|---|
| **guard** | 监视，在条件成立时停止或发出事件 | `when`、`watch` |
| **反射** | 行动：接管某些通道的输入，或往其中添加输入 | `reflex` |
| **handler** | 响应正在运行的程序的事件 | `on` |

程序可以设置它们，agent 可以学到它们（[边工作边学习](/docs/zh-cn/learn/while-working/)），包也可以附带它们。在程序启动的任务内设置的规则属于那个任务。核心程序 API 提供 `when`、`watch`、`on`、`rule`、`clear_rules` 和 `run_controller`。

## Guard

```python
when(lambda view: view["see"].get("lava"), "stop", name="no_lava")
watch("hud.health", low=6, event="LOW_HEALTH", stops=False)
clear_rules("no_lava")           # clear_rules() 清除所有 guard 和观察规则
```

- `when(predicate, action, name=None, stops=True)` 在 `predicate(view)` 为真时触发。
  `action` 是 `stop`、`hold`、embodiment 自己的动作（机器人上的 `open_gripper`，游戏中的
  `back_off`），或要发出的事件名。
- `watch(signal, low=None, high=None, event=None, name=None, stops=True)` 在信号（view
  的一个点分隔键，或 view 的一个函数）超出范围时触发。事件默认为 `<SIGNAL>_OUT_OF_RANGE`。
- 会停止的 guard 结束它触发时所在的执行，并松开该执行按住的键。设置 `stops=False` 时它只发出事件，其他一切照常进行。

## 反射

反射会行动，而不只是监视。它是 view 的一个函数，返回空值，或者返回这个周期的输入：

```python
def jump_gaps(view):
    if view["see"].get("gap_ahead"):
        return {"keys": ["space"]}          # adds a jump to whatever is moving
    return None

def flee(view):
    if view["see"].get("creeper_near"):
        return {"keys": ["s"], "take": ["move"]}   # takes the move channel
    return None

reflex(jump_gaps, priority="assist")
reflex(flee, priority="hazard")
remove_reflex("flee")
reflex_state()                              # which reflexes run, and which act now
```

一次动作是一个周期内的 `{"keys", "buttons", "dx", "dy", "take"}`。带 `take` 时，在它行动期间，它替换正在运行的任务在这些通道上的输入；它停止的那个周期，任务的按键就会恢复。不带
`take` 时，它的按键会加到发出的输入中。优先级从高到低：`hazard`、`combat`、`survival`（默认）、`assist`。行动中的反射在行动期间，在时间轴上显示为单独的一条泳道。

反射运行在输入被划分为**通道**的 embodiment 上，例如游戏的移动、视角、双手和物品。

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

`on(event, handler)` 在程序的一次执行以该事件结束时调用 `handler(trace)`。返回 `True`（或不返回）表示已解决；返回
`False` 让它继续上报。在程序启动的任务内，handler 看到的是该任务以及它启动的任务的事件，并随该任务结束。Handler 与其他规则共享预算和限制，程序可根据它记录的状态执行动作。

## 机器人：控制器

在机器人上，`run_controller(fn, until=None, max_seconds=None, region=None, hz=None,
cameras=None)` 以固定频率运行 `fn(observation)`，并发送它返回的关节、末端执行器或夹爪目标，用于视觉伺服和其他快速循环。它是一次有界执行：guard
对它生效，它以一个事件结束。

## 规则的规则

在控制循环内运行的回调必须够快，且不能打开文件、使用网络、启动进程、休眠或调用模型。同一个控制周期里的回调共用 `runtime.reactive_budget_ms`（默认 5 毫秒）。违反规则的回调会产生 `REACTIVE_FAULT` 事件。控制循环之外收到事件时，handler 在登记它的任务作用域中运行。

规则产生的每条命令仍要经过环境自己的检查，格式错误或超出范围的命令会被拒绝。延迟发出的命令可以在发出前撤回。发出后，回执归原执行。回执丢失时，调度器不会自动重发。

## 在 skill 里

skill 在 session 的反应层 `self.reactive` 上登记规则：

```python
class Footing:
    def keep_footing(self):
        """Stop whatever moves when the ground ahead is gone."""
        self.reactive.rule(lambda view, state: view["see"].get("gap_ahead"), "stop",
                           name="no_gap", priority=400)
```

`rule(decide, does, name=None, priority=0, action=None, on=None)` 添加一条规则。`decide(view, state)` 返回假值表示什么也不做，否则规则执行 `does`：

| `does` | |
|---|---|
| `"stop"` | 停下它盯着的执行（`action`：`stop`、`hold` 或本体自己的动作） |
| `"event"` | 向设置它的任务发出事件 `action` |
| `"act"` | 返回这个周期的输入，和反射一样 |
| `"answer"` | 回应 `on` 类型的事件，和事件处理器一样 |

命名的优先级有 `hazard` 400、`combat` 300、`survival` 200、`assist` 100 和 `guard` 0。

## 在包中

包可以为它的环境附带规则：作为一个 skill，其函数在会话开始时设置这些规则；或者作为某个 library 的反应条目。设置
`knowledge = "learned"` 时，agent 启动时不带包中手写的规则，而是学习自己的规则（[让它学会一个环境](/docs/zh-cn/learn/learn-an-environment/)）。
