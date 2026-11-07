---
title: "CLI"
---

`harness`（在源码目录中也可用 `python scripts/harness`）。每条命令输出 JSON 或表格；错误以 `{"error": ...}` 的形式写入 stderr，退出状态为 1。装好的扩展包会把自己的命令加进 `harness --help`。

| 命令 | 作用 |
| --- | --- |
| [`run`](#harness-run) | 在这台电脑上完成一个任务后结束（harness run "rename the photos by date"）；harness run rpc：让另一个程序驱动 agent |
| [`app`](#harness-app) | 打开应用：在窗口里和 agent 对话（第一次使用时安装 app 扩展包） |
| [`sessions`](#harness-sessions) | 管理会话宿主中的 coding 会话 |
| [`install`](#harness-install) | 安装扩展包（连同它依赖的包），或更新它们；以及包提供的服务和 bench |
| [`list`](#harness-list) | 已安装的扩展包；--available：registry 中的扩展包（QUERY 在其中搜索）；给出一个扩展包的名字：它提供什么 |
| [`remove`](#harness-remove) | 移除已安装的扩展包 |
| [`library`](#harness-library) | agent 学到的东西：所有 library，以及一个 library 的条目、它们的证据、测试和使用记录 |
| [`replay`](#harness-replay) | 在当前终端按原样回放一次运行 |
| [`doctor`](#harness-doctor) | 这台电脑能否运行 agent：Python、模型和它的 key、扩展包；或者检查服务，或者一个实验（eval 扩展包的：harness doctor EXPERIMENT --help） |

## harness run

在这台电脑上完成一个任务后结束（harness run "rename the photos by date"）；harness run rpc：让另一个程序驱动 agent

```text
usage: harness run [-h] [-p | --json] [--learn [MINUTES]]
                   [--physical {never,ask_each,ask_once_app,ask_once_session,when_idle,allow}]
                   [--allow-app APP] [--deny-app APP] [--ask-app APP]
                   [--window-details {none,presence,apps,titles}]
                   [--think {off,on,on_events,periodic}] [--think-interval SECONDS]
                   [--workspace {browser,desktop,apps,display,project}] [--vm-image IMAGE] [--agent AGENT]
                   [--folder FOLDER] [--isolation {folder,worktree}]
                   [--share-mcp-tool {project_info,project_diff}] [--managed-workspace]
                   task
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `task` |  | 一个任务，或用 rpc 启动 JSON Lines 协议 |
| `-p`, `--print` |  | 只打印 agent 的最终答案 |
| `--json` |  | 每条 trace 记录输出一行 JSON |
| `--learn` |  | 花指定分钟学习这个环境，把结果记入 library |
| `--physical` |  | 本次运行的实体输入级别 |
| `--allow-app` |  | 允许在指定应用中使用实体输入，可重复 |
| `--deny-app` |  | 禁止在指定应用中使用实体输入，可重复 |
| `--ask-app` |  | 在指定应用中使用实体输入前逐次询问，可重复 |
| `--window-details` |  | 本次运行中可观察到的其他窗口信息 |
| `--think` |  | 开启或关闭长程序期间的一次前瞻 |
| `--think-interval` |  | 兼容旧配置，当前由事件驱动 |
| `--workspace` |  | 后台浏览器、桌面、后台应用、独立显示或项目（需 `--folder`） |
| `--vm-image` |  | 独立显示的虚拟机镜像 |
| `--agent` |  | 选择接入的 coding agent。 |
| `--folder` |  | 绑定原生 Harness 或外部 agent 的本机项目目录。 |
| `--isolation` |  | 选用项目目录或 Git worktree。 |
| `--share-mcp-tool` |  | 向本次 ACP 会话授予一个只读项目工具。 |
| `--managed-workspace` |  | 在支持的 Linux 主机启用隔离工作区 |

harness run rpc：从 stdin 读 JSON 行（{"type": "prompt", "text"}，之后是 message、pause、continue、approve、reject、end），把 trace 的记录作为 JSON 行写到 stdout。


## harness sessions

查看或操作会话宿主管理的 coding 会话。

```text
usage: harness sessions [-h]
                        {ls,import,discover,observe,reconnect,show,stop,cancel,diff,merge,discard,attach,send,steer,terminal,config,approve,answer,handoff}
                        ...
```

### harness sessions ls

列出会话，可按项目或接入类别筛选。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--kind` |  | 筛选会话类别。 |
| `--project` |  | 筛选项目。 |
| `--all` |  | 包括已结束的历史会话。 |
| `--json` |  | 使用 JSON 输出。 |

```text
usage: harness sessions ls [-h] [--kind KIND] [--project PROJECT] [--all] [--json]
```

### harness sessions import

只读导入用户选定的原生会话日志。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `provider` |  | 原生会话提供方。 |
| `file` |  | 用户选择的日志文件。 |
| `--follow` |  | 跟进日志新增记录。 |

```text
usage: harness sessions import [-h] [--follow] {claude-code,codex} file
```

### harness sessions discover

查看适配器允许发现的原生会话。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `agent` |  | 选择接入的 coding agent。 |
| `--folder` |  | 指定本机项目目录。 |
| `--cursor` |  | 从指定发现游标继续。 |

```text
usage: harness sessions discover [-h] [--folder FOLDER] [--cursor CURSOR] agent
```

### harness sessions observe

索引已知 ID 的 ACP 会话，或只读跟进已知 ID 的云端会话。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `agent` |  | 选择接入的 coding agent。 |
| `external_id` |  | 供应商的原始会话 ID。 |
| `--folder` |  | 指定 ACP 会话的原项目目录。 |

```text
usage: harness sessions observe [-h] [--folder FOLDER] agent external_id
```

### harness sessions reconnect

在旧控制者退出后尝试恢复原生会话。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |
| `--agent` |  | 选择接入的 coding agent。 |
| `--released` |  | 确认前一个控制者已退出。 |

```text
usage: harness sessions reconnect [-h] [--agent AGENT] [--released] session
```

### harness sessions show

查看会话身份、状态、能力和近期记录。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |

```text
usage: harness sessions show [-h] session
```

### harness sessions stop

关闭宿主当前管理的会话。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |

```text
usage: harness sessions stop [-h] session
```

### harness sessions cancel

取消当前外部回合。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |

```text
usage: harness sessions cancel [-h] session
```

### harness sessions diff

查看所选会话的 Git 改动。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |

```text
usage: harness sessions diff [-h] session
```

### harness sessions merge

将已关闭会话的托管 worktree 快进合并到原分支。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |

```text
usage: harness sessions merge [-h] session
```

### harness sessions discard

移除已关闭会话的托管 worktree。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |

```text
usage: harness sessions discard [-h] session
```

### harness sessions attach

在终端打开并跟进指定会话。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |

```text
usage: harness sessions attach [-h] session
```

### harness sessions send

向已知会话发送下一条消息。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |
| `text` |  | 发送的文本。 |

```text
usage: harness sessions send [-h] session text
```

### harness sessions steer

把新指令交给正在运行的外部回合。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |
| `text` |  | 发送的文本。 |

```text
usage: harness sessions steer [-h] session text
```

### harness sessions terminal

发送文本给会话的 PTY。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |
| `text` |  | 发送的文本。 |

```text
usage: harness sessions terminal [-h] session text
```

### harness sessions config

选取适配器实际公布的模型、模式或其他配置值。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |
| `id` |  | 适配器公布的配置选项 ID。 |
| `value` |  | 配置值。 |

```text
usage: harness sessions config [-h] session id value
```

### harness sessions approve

按原始请求 ID 批准或拒绝待处理的操作。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |
| `request_id` |  | 原始请求 ID。 |
| `--agent` |  | 选择接入的 coding agent。 |
| `--reject` |  | 拒绝所指的审批请求。 |

```text
usage: harness sessions approve [-h] [--agent AGENT] [--reject] session request_id
```

### harness sessions answer

回答当前 agent 的表单，传入空值可拒绝。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |
| `request_id` |  | 原始请求 ID。 |
| `content` |  | JSON 表单内容。 |

```text
usage: harness sessions answer [-h] session request_id content
```

### harness sessions handoff

用用户选择的上下文启动新 agent，并关联原会话。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `session` |  | 宿主会话 ID。 |
| `agent` |  | 选择接入的 coding agent。 |
| `context` |  | 交接给目标 agent 的上下文。 |
| `--folder` |  | 指定本机项目目录。 |
| `--isolation` |  | 选用项目目录或 Git worktree。 |

```text
usage: harness sessions handoff [-h] [--folder FOLDER] [--isolation {folder,worktree}]
                                session agent context
```

## harness install

安装扩展包（连同它依赖的包），或更新它们；以及包提供的服务和 bench

```text
usage: harness install [-h] [--project] [--json] [--update] [--yes] [--link] [--deploy DEPLOY]
                       [names ...]
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `names` |  | 扩展包（registry 中的名称，可带版本范围；git 或压缩包 URL；本地文件夹）、服务和 bench |
| `--project` |  | 操作项目的扩展包（当前目录或上级目录中的 harness.toml 和 harness.lock），而不是你自己的 |
| `--json` |  |  |
| `--update` |  | 把指定的扩展包（默认：全部）更新到版本范围内的最新版本 |
| `--yes`, `-y` |  | 安装 registry 以外来源的扩展包时不再询问（它们会在这台电脑上运行代码） |
| `--link` |  | 本地文件夹：直接使用原位置，不复制一份（用于开发中的扩展包） |
| `--deploy` |  | 服务：放置它们的 deploy（默认 $HARNESS_DEPLOY） |

harness install minecraft；harness install robodojo@^0.1；harness install git:github.com/x/y@main#packages/z；harness install ./my-package --link；harness install --update（全部）；harness install sam3（一个服务）。在有 harness.toml 的文件夹里不带名称运行：按 harness.lock 安装项目的扩展包。

## harness list

已安装的扩展包；--available：registry 中的扩展包（QUERY 在其中搜索）；给出一个扩展包的名字：它提供什么

```text
usage: harness list [-h] [--available] [--project] [--json] [query]
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `query` |  |  |
| `--available` |  | 列出 registry 中的扩展包 |
| `--project` |  | 操作项目的扩展包（当前目录或上级目录中的 harness.toml 和 harness.lock），而不是你自己的 |
| `--json` |  |  |

## harness remove

移除已安装的扩展包

```text
usage: harness remove [-h] [--project] [--json] names [names ...]
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `names` |  |  |
| `--project` |  | 操作项目的扩展包（当前目录或上级目录中的 harness.toml 和 harness.lock），而不是你自己的 |
| `--json` |  |  |

## harness library

agent 学到的东西：所有 library，以及一个 library 的条目、它们的证据、测试和使用记录

```text
usage: harness library [-h] [--json] [{ls,show}] [path]
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `what` |  | ls（默认）：$HARNESS_HOME/libraries 下的所有 library；show LIBRARY：它的条目 |
| `path` |  | show：library 的目录，或它在 $HARNESS_HOME/libraries 下的名字 |
| `--json` |  | 输出 JSON |

## harness replay

在终端里回放运行；`--json` 输出原始事件。

```bash
harness replay RUN --json
```

## harness doctor

这台电脑能否运行 agent：Python、模型和它的 key、扩展包；或者检查服务，或者一个实验（eval 扩展包的：harness doctor EXPERIMENT --help）

```text
usage: harness doctor [-h] [--deploy DEPLOY] [--json] [names ...]
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `names` |  | 服务（默认：核心），或一个实验 |
| `--deploy` |  | 放置服务的 deploy（默认 $HARNESS_DEPLOY） |
| `--json` |  |  |

退出状态：0 没有缺失，1 有缺失，2 用法错误。
