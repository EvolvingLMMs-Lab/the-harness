---
title: "Worker 协议"
description: "harness 和 worker 之间的 HTTP 协议：它的方法、每类 worker 响应的调用，以及每个 worker 都遵守的规则。"
---

worker 是 agent 作用的对象，比如模拟器、机器人、这台电脑的桌面、后台浏览器、游戏，在自己的进程中通过 HTTP
提供服务。agent 的程序和 episode driver 作为客户端访问它；worker 在执行每一步之前都会检查它，并且不对外公开分数。

```bash
harness serve --factory benches.robotwin.runtime:create_environment --port 8765
harness serve --factory benches.computer.runtime:create_environment --options worker.toml
harness serve --factory benches.robodojo.runtime:create_environment --contract xpolicylab --embodiment arx_x5
```

| 选项 | 作用 |
|---|---|
| `--factory module:callable` | 创建环境的可调用对象；必需 |
| `--options FILE` | 一个 TOML 文件，其中的键作为关键字参数传给工厂 |
| `--host`, `--port` | 监听地址（默认 `127.0.0.1`、`8765`） |
| `--contract` | 客户端能看到什么：`native`（默认，全部）、`xpolicylab`、`screenshot`（[contract](#contract)） |
| `--embodiment` | contract 从中读取标定的 embodiment；使用 contract 时必需 |
| `--exit-with-stdin` | 标准输入关闭后退出，这样 worker 会随启动它的进程一起结束 |

开始监听后，它打印一行 `{"worker": NAME, "address": [HOST, PORT]}`。它一次处理一个请求。默认只监听回环接口；
绑定其他接口需要 `$HARNESS_WORKER_TOKEN`，此后每个请求都必须以 `Authorization: Bearer TOKEN` 发送它（设置了这个变量时，客户端会发送）。

## 请求

```text
POST /rpc   {"method": "...", "arguments": {...}}   ->   200 {"result": ...}
                                                    ->   400 {"error": "ValueError: ..."}
```

其他路径返回 404，token 缺失或错误返回 401，超过 32 MiB 的请求体会被拒绝。客户端从不重试请求：超时的一步可能已经执行了。

| 方法 | 参数 | 结果 |
|---|---|---|
| `describe` | | `{protocol_version: 1, name, tools, snapshot_restore: false, methods}`：`tools` 是 worker 的工具 schema，`methods` 是 `call` 接受的名称。客户端会拒绝其他协议版本 |
| `reset` | `task`, `seed` | 第一个观测：`{episode_id, step, instruction, state, images}`（图像为 data URL） |
| `execute` | `episode_id`, `step`, `action`（`{name, arguments}`） | 在当前观测上执行一个动作：`{observation, reward, success, terminated, truncated, info, videos}`。在 reset 之前、episode 结束之后，以及 `(episode_id, step)` 不是当前值时都会被拒绝 |
| `call` | `name`, `arguments` | 环境自己的某个方法的结果（[下文](#调用)）；未知名称是错误 |

## 调用

agent 的运行时通过 `call` 驱动 worker。每个 worker 都响应通用的调用；每类 worker 还有自己的调用。

### 每个 worker

| 名称 | 参数 | 结果 |
|---|---|---|
| `profile` | | 静态信息：embodiment 的类型和名称、控制频率（`control_hz`）、相机或屏幕、安全层（shield）选项、步数上限、它如何被驱动（`max_hz`、`step_seconds`：[下文](#每个-worker-都遵守的规则)）；机器人还有关节组、动作限制、机械臂基座、夹爪常量和规划器限制 |
| `state` | `episode_id` | 当前状态：`step`、`ended`，以及 embodiment 自己的状态（机器人的关节位置和末端执行器位姿，`[x, y, z, qw, qx, qy, qz]`，环境坐标系；桌面的屏幕） |
| `tick` | `episode_id`, `step`, `command`，可选 `cameras` | 一步：`{executed, shield: {verdict, command, reasons}, state[, observation]}`。带 `cameras` 时，一并返回这一步之后的画面 |
| `observe` | `episode_id`, `cameras`，可选 `image_format`, `quality` | `{state, images}`（data URL）；机器人还有 `intrinsics`、`camera_to_world`（OpenCV 约定）和 `image_size` |
| `claim_outcome` | `episode_id` | 结果的 token，由 driver 在 reset 之后每个 episode 领取一次 |
| `outcome` | `token` | `{success, reward, process_score, terminated, truncated, steps, ...}`；只凭 token 读取 |

### 机器人和模拟器

| 名称 | 参数 | 结果 |
|---|---|---|
| `tick` | `command`：绝对关节目标；可选 `source`（`policy` 表示学习型策略的动作） | 同上 |
| `fk` | `command`（关节） | `{arm: end-effector pose}` |
| `ik` | `episode_id`, `arm`, `pose` | 从当前关节出发求解的 `{success, joints}` |
| `plan` | `episode_id`, `arm`, `pose` 或 `joints`, `raw` | 按控制频率的 `{success, waypoints}`（`raw`：规划器自己的路径） |
| `policy_obs` | `episode_id` | 评测客户端交给学习型策略的观测（RoboDojo） |
| `action_spec` | | 每条机械臂的安装位姿、关节限位和速度限制；控制频率（RoboDojo） |

### 桌面、应用和 display

| 名称 | 参数 | 结果 |
|---|---|---|
| `tick` | `command`：一步，见下文 | 同上；到达电脑的一步还会说明是怎样到达的（`delivery`：`mechanism`、`status`、应用和窗口） |
| `windows` | `episode_id` | 窗口列表（id、应用、标题、画面大小、是否最小化、是否由 agent 启动），以及 agent 正在其中工作的窗口 |
| `elements` | `episode_id`, `window`, `role`, `text`, `limit` | 窗口的无障碍元素：id、角色、名称、值、矩形、动作、状态，以及同样内容的大纲文本行（`outline`） |
| `use_screen` | `episode_id`, `index` | 从现在起在显示器 `index` 上操作，或重新跟随活动窗口（`null`） |
| `hand_back` | `episode_id` | 你接管之后把电脑交还了 |
| `physical` | `op`：`identify`、`check`、`answer`、`status` | 这个 worker 的 episode 的物理输入策略：这些步骤属于谁，一步会遇到什么，你对请求的回答，现在谁持有输入 |
| `preview` | `max_side` | 供实时画面使用的屏幕小图；不执行也不计数任何操作 |

桌面的一步（`command`）是以下之一：

| `type` | 字段 |
|---|---|
| `click` | `x`, `y`, `button`（`left`、`right`）, `count`（1、2）, `window` |
| `drag` | `x`, `y`, `to_x`, `to_y`, `duration_ms`, `window` |
| `scroll` | `x`, `y`, `direction`（`up`、`down`、`left`、`right`）, `amount`, `window` |
| `type` | `text`, `window` |
| `key` | `keys`（最多同时按 4 个）, `window` |
| `wait` | `ms` |
| `act` | `element`, `action`（`click`、`invoke`、`toggle`、`select`、`expand`、`collapse`、`set_value`、`scroll_into_view`）, `value` |
| `use_window` | `window`，可选 `visible` |
| `launch` | `app`、`args`，可选 `visible` |
| `noop` | |

坐标是屏幕坐标；带 `window`（例如 `w2` 这样的 id）时，坐标位于该窗口的画面中。

声明支持 `action_ids` 的 worker 会在 tick 回执中返回同一个动作 ID。选择窗口和启动应用
通过 `result.window` 返回选中的窗口。浏览器提供当前文档中的元素，并在文档就绪时返回
`page_ready` 标识。

可信宿主启动的 worker 可以声明 `managed_approval`。控制调用需要宿主认证。敏感输入被拒绝后，
worker 可以为该动作生成审批请求。再次交付时，worker 核对原始执行、动作、命令、摄像头和实时目标。
请求 ID 本身没有授权效力。此模式拒绝启动应用，也拒绝向无法确定的目标交付敏感输入。
面向用户的审批依赖宿主接入。

worker 也可独立声明 `authenticated_controls`：`managed_control_calls` 需要可信宿主的证明，但这不表示它实现了敏感操作审批 UI。`program_control_calls` 是其中允许宿主代当前程序调用的子集，其余控制只属于宿主。项目 worker 保护 tick、cancel 和 release，release 属于宿主的租约生命周期。现有桌面的敏感审批检查保持独立，不变。

### 其他

| Worker | 它自己的调用 |
|---|---|
| 后台浏览器 | 桌面的调用，以及 `page_text`（`episode_id`, `offset`, `limit`）：页面的可见文本和链接 |
| 游戏（Minecraft） | `physical`、`hand_back`、`new_world`（新世界，即玩家的 reset）、`show_seed`、`world`（世界地图的操作：`things`、`thing`、`forget_thing`、`summary`） |
| OSWorld | `declare_infeasible`：任务无法完成的判定，它的不可完成任务按此评分 |
| 有练习沙盒的 benchmark（bench.toml 的 [sandbox]：Minecraft 的练习、虚构机器人） | `sandbox`（`episode_id`、`op` 及其参数）：布置一个场景，只在任务学习变体（`-learn`，主动运行的）的 episode 里可用；其他 episode 一律拒绝 |

## 每个 worker 都遵守的规则

- **episode 和步。** `tick` 和 `execute` 指明它们所针对的 episode 和计算时的步；过时的会被拒绝，且绝不会执行。
  可能已执行的一步绝不会被静默重试。
- **安全层在 worker 中运行。** 每条命令在到达机器人或电脑之前都会被检查：机器人的关节限位和运动范围，桌面一步的字段、坐标、
  按键和文本，游戏的输入。程序无法绕过它。被拒绝的一步返回 `executed: false` 和安全层给出的原因。
- **结果受保护。** 只有 token 的持有者（driver）可以读取它；程序和模型永远看不到它。
- **如何被驱动。** profile 说明环境能被驱动得多快，而不是 harness 运行哪一种时钟：`step_seconds` 是它的一次 `tick` 持续的时间（模拟器前进一个控制周期：执行的时间上限按它的步数计算）；`max_hz` 是它每秒最多接受的命令数（世界按真实时间持续运行：此时由 agent 的运行时为执行的各个周期定速）。两者都没有时，它答复多快就驱动多快，时间按墙钟计算。没有东西运行时不发送任何命令：每个周期都需要输入的环境要有一条按时间判断的规则（[编写反应规则](/docs/zh-cn/extend/reactive-rules/)）。仍然写着 `clock` 的 profile 按该模式原来的含义读取：`steps`（或未写）即 `step_seconds = 1 / control_hz`，`wall` 即 `max_hz = control_hz`，`events` 即两者都没有。

## contract

contract 把每个结果过滤为评测交给策略的内容，这样开发时的运行看到的就是被评测的 agent 将会看到的内容。profile 中写明它（`observation_contract`）。

| Contract | 客户端看到什么 |
|---|---|
| `native` | worker 报告的全部内容 |
| `xpolicylab` | XPolicyLab 官方客户端交给策略的内容：夹爪取其最后一次命令值（`gripper_feedback: "commanded"`），内参和 `camera_to_world` 来自 embodiment 的标定，profile 和状态中没有步数上限，没有任务名 |
| `screenshot` | 只有桌面的指令和屏幕：状态只保留 `step`、`ended` 和 `screen`；没有任务、track 或步数上限 |

## 实现

| 工厂 | Worker |
|---|---|
| `benches.computer.runtime:create_environment` | 这台电脑：桌面、在后台运行的它的应用，或它自己的一个 display |
| `benches.browser.runtime:create_environment` | 后台浏览器 |
| `benches.minecraft.runtime:create_environment` | Minecraft |
| `benches.robodojo.runtime:create_environment` | RoboDojo，每个进程一个任务（[Benchmark](/docs/zh-cn/extend/environments/)） |
| `benches.robotwin.runtime:create_environment` | RoboTwin 2.0，每个进程一个任务 |
| `benches.osworld.runtime:create_environment` | OSWorld |
| `benches.osomni.runtime:create_environment` | OS-Omni |
| `harness.connectors.xpolicylab.Bridge` | 不由 `harness serve` 提供：XPolicyLab 连接器，一个以 XPolicyLab 客户端作为机器人的 worker |

要编写自己的 worker，见[接入一种环境](/docs/zh-cn/extend/environments/)。
