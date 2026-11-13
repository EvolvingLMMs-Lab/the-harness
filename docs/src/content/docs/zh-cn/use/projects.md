---
title: 在项目中工作
description: 用原生 Harness，在明确绑定的项目中完成 coding 及其他文件、进程任务。
---

workspace 包让 Harness 自己的 agent 操作项目文件和进程，仍然使用模型编写的 Python 程序与有界执行。

```sh
harness install workspace
harness run "Reproduce the parser bug, fix it and run focused checks" --folder ./project
```

在源码 checkout 中可用 `harness install ./packages/workspace --link` 安装本地包。目录必须已经存在。除非显式指定外部 `--agent`，`--folder` 会选择原生项目工作区；也可写 `--agent harness`。CLI 在客户端解析绝对路径，host 必须能够访问它。host API 同样接受 `folder`、`workspace="project"` 与 `agent="harness"`。这不会自动创建 git worktree、安装项目依赖或替你选择测试命令。

在终端和 app 里，对话开始时选择**项目文件夹**并填写文件夹；在仓库目录里启动时会预填当前目录。项目没有屏幕。任务需要看到什么（比如改过的页面渲染成什么样）时，agent 会请求在同一个对话里取用浏览器或你的桌面（[取用另一个环境](/docs/zh-cn/configure/permissions/#取用另一个环境)）；你拒绝的话，它会继续并说明没能确认的部分。

## 读取、修改与验证

项目的[说明文件](/docs/zh-cn/configure/instructions/)（`AGENTS.md` 或 `CLAUDE.md`）随对话的第一条消息给出；`/init` 可以让 agent 写一份。模型读取工具链配置，复现故障、修改文件，再在目标环境中测试。Python 控制程序可调用：

```python
current = read_file("src/parser.py")
updated = current["text"].replace("old expression", "new expression")
print(write_file("src/parser.py", updated, expected=current["sha256"]))
check = run_command([".venv/bin/python", "-m", "pytest", "tests/test_parser.py"], timeout=120)
print(check["exit_code"], check["output"])
```

读取返回 UTF-8 字节窗口，默认 12,000、最多 64,000 字节，包含 `next_offset`、`bytes`、`truncated` 和整个文件的 hash。替换大文件前须读全。`write_file` 仅在创建文件时接受 `expected=None`；hash 不符时返回 `error="conflict"`，不替换文件。原子替换与乐观 hash 检查不构成对外部编辑器的事务。文件 API 将路径限制在项目内，命令则拥有当前 OS 用户的权限。

参数列表直接启动程序；字符串在 POSIX 上用 `/bin/sh -c`，Windows 上用 PowerShell。每次调用都有自己的 `cwd`（相对于根目录）与新环境。文件会保留，shell 的 `cd` 和 `export` 不跨命令保留。应使用项目实际的解释器与依赖；控制程序的 `sys.executable` 和 import 属于 Harness，不一定属于目标项目。

目标只自动继承一小组 OS 环境变量，以及显式 `env` 覆盖，不自动继承控制程序的 PYTHONPATH 或模型凭据。这是**可信本地执行**，不是 OS 沙箱：命令可以访问其他文件、联网、调用用户的工具。它不会自动识别敏感 shell 操作并请求审批。需要逐段检查时使用程序审批；需要更强隔离时，给 worker 单独的 OS 权限边界。

## 进程、证据与结束

`run_command(..., timeout=120)` 通过现有调度器等待实际回执。`start_process(...)` 立即返回进程 ID；用 `process_status(id)`、`read_output(id, offset=0, limit=12000)` 和 `cancel_process(id)` 检查或停止它。每条命令都有大于零、不超过 3,600 秒的墙钟期限。

回执区分 `running`、`exited`、`cancelled`、`timeout` 和 `session_closed`，保留退出码与耗时。非零退出是正常结果，不是传输错误。预览是最后 6,000 字节；完整 stdout/stderr 合流与最终 JSON 回执保留在会话的 `artifacts` 目录，可以分页读取预览遗漏的内容。控制程序 print 输出仍有原有的独立大小限制。丢失传输回执时不会自动重试。

回答结束一轮，会话关闭前仍保留工作区。`harness run` 在这一轮之后关闭会话：回答，或结束这一轮的上限。即使控制程序被杀，host 仍负责释放进程。POSIX 清理覆盖进程组，主动脱离到其他 session 的进程不在保证内；Windows 在父进程仍存活时使用尽力而为的 `taskkill /T /F`，不能保证回收已脱离的后代。取消不回滚已经修改的文件。

项目子 agent 继承同一根目录，各自拥有进程和输出；不会自动得到独立 checkout，必须协调修改。仍可委派到已安装的其他工作区。没有绑定项目的父会话不能凭空授予子 agent 一个项目。

命令成功退出、模型给出回答、独立验证任务完成，是三个不同事实。工作区不自动给出成功评分。预算耗尽保持可见，不会变成成功声明；CLI 在耗尽调用预算且没有答案时失败退出，不再无限等待。

## 资源与证据边界

操作数据返回给调用程序；成功执行事件持续写入轨迹，模型收到事件计数和最多 32 条最近的非正常事件，不重复收到所有文件全文。
程序输出持续记录为 `program_output`，每个程序最多输出 1 MiB 字符，模型看到其中最多 30,000 字符；超过时看到保存它的文件和开头 2,000 字符。超限明确报错，后续决策仍可运行。

`run_command` 的进程归当前 execution；`start_process` 显式创建归任务所有的服务，可跨程序存活，在任务释放时清理。
最多并行 16 个进程，每个进程最多保留 16 MiB 合并输出，超限请求停止并报告 `output_limit`。
进程输出和证据共用 256 MiB 的预留预算。不可变 JSON 内容按哈希保存在 `artifacts/evidence`，`index.jsonl` 关联请求、动作身份与终态；重复内容复用字节。
动作前证据空间不足会阻止执行；动作后不足会使游标失效，不能重试可能已经发生的动作。

`limits.target_workers` 限制原生 worker lease，默认 4；浏览器和显示环境仍使用 computer 的专用资源上限。
没有跨资源的隐式事务或回滚。清理未确认、证据不完整必须明确报告；worker 丢失不能证明所有脱离进程组的后代已经停止。
