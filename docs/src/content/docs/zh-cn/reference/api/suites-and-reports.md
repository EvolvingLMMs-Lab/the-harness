---
title: "Suite 与报告"
---

## `harness_eval.suite`

在多个任务和 seed 上运行实验：`harness run EXPERIMENT.toml`。

一个 worker 运行一个任务，因此每个槽位为下一任务启动 worker，运行其 seed 后停止。benchmark（harness.sdk Bench）决定任务列表、槽位含义（deploy [sim] 的 GPU × workers_per_gpu，或 OS-Omni deploy 表中的 VM）及 worker 启动方式。已完成的 episode（存在 summary.json）被跳过，因此重新运行时可从未完成的 episode 继续。使用 `--workspaces N` 时，槽位改为本机的 N 个工作区（后台浏览器、隔离屏或虚拟机：Bench.workspace_slots），分摊每个任务的 seed；后台浏览器连到它们共用的无界面 Chrome（电脑设置的 `chromes`），各有自己的 context。结果写入 OUTPUT/&lt;task&gt;/seed-&lt;n&gt;/；用 `harness report OUTPUT` 汇总。运行期间，进程登记在 OUTPUT/.running 中（runs.liveness）；结束时把运行情况写入 OUTPUT/outcome.json，其中包含 `harness run` 的退出码（EXIT_CODES）。OUTPUT/suite.json 记录本次运行的命令行（`invocation`），因此 `harness run --resume OUTPUT` 不需要原来的参数就能续跑（recorded_invocation）。首个 episode 前，安装本机缺少且运行需要的内容（packages/provision.py），并启动常驻服务。

### `log`

```python
def log(output, message)
```

带时间打印 `message` 并追加到 OUTPUT/suite.log（每次一个槽位）。

### `expand_tasks`

```python
def expand_tasks(spec, benchmark='robodojo', layouts='procedural', deploy=None)
```

按顺序解析逗号分隔的任务表达式并去重：每项按 benchmark 的规则展开（其 bench.toml `tasks`），结合 benchmark 的 `deploy` 表。

### `expand_seeds`

```python
def expand_seeds(spec)
```

解析逗号分隔的 seed 及闭区间（"0-4,7"）。

### `worker_name`

```python
def worker_name(args, task, slot) -> str
```

worker-&lt;task&gt;；多个工作区同时跑同一个任务时再加 -&lt;slot&gt;。

### `worker_options`

```python
def worker_options(args, task, directory, slot=None)
```

将 `slot` 上 `task` 的 benchmark worker 选项写入 `<directory>/<worker_name>.toml` 并返回路径。

### `start_worker`

```python
def start_worker(args, task, gpu, port, output)
```

在槽位 `gpu` 上启动 `task` 的 worker，以独立进程组监听 `port`（日志：`workers/<worker_name>.log`），响应后返回进程。提前退出时抛出 RuntimeError；未及时就绪时先停止再抛出异常。

### `stop_worker`

```python
def stop_worker(process)
```

若 worker 进程组仍运行，则先发送 SIGINT，30 s 后发送 SIGKILL。

### `new_record`

```python
def new_record()
```

一次运行的各槽位在 episode 摘要之外报告的内容：worker 失败、因 suite 费用上限而跳过的 episode，以及通知槽位停止的事件。

### `done`

```python
def done(directory, rerun_errors)
```

存在摘要即视为 episode 完成；启用 rerun_errors 时，因错误结束的 episode（如供应商服务中断、worker 退出）会重新运行。

### `replacements`

```python
def replacements(task_dir, name='unstable')
```

&lt;task&gt;/unstable.json：{不稳定 seed: 替代它运行的 layout}，让续跑使用相同替代 layout，而非重试不稳定 layout。

&lt;task&gt;/displaced.json：{请求的 seed: 为它运行的 layout}，用于本输出目录中先前 suite 已将所请求 layout 用来替代其他不稳定 layout 的情况（原运行仍计入原所属任务）。

### `write_replacements`

```python
def write_replacements(task_dir, name, mapping)
```

原子写入 &lt;task&gt;/&lt;name&gt;.json：写入中途终止不能留下损坏 JSON 而影响续跑。

### `pack_size`

```python
def pack_size(args, task)
```

benchmark 可用于替换不稳定 layout 的 `task` layout 数量；无法确定数量时返回 None。

### `run_slot`

```python
def run_slot(args, slot, gpu, port, tasks, output, run, record=None)
```

一个槽位的循环：从队列取任务直到为空（一个任务，或一个任务和它分到的 seed）；每个任务启动 worker、运行尚未完成的 seed、停止 worker。RoboDojo eval 的不稳定 layout 用评测包中下一个未使用 layout 替换；其他 worker 错误则重启 worker；suite 达到费用上限后跳过剩余 episode。
worker 失败和被跳过的 episode 记入 `record`（new_record）；其停止事件一旦设置，槽位不再启动任何新内容。

### `run_active`

```python
def run_active(args, config, task_dir, seed, slot, output)
```

任务运行之前的主动学习（runtime/active.py），在库会学习并且要求这样做时进行：在第一个 seed 的环境上跑一次学习它的运行，放在 active-&lt;seed&gt;/ 下（只跑一次：已经跑完的不会重跑）。它的结果不算任务成绩。

### `experiment_for`

```python
def experiment_for(run, task, seeds)
```

实验中单个任务的 driver 配置。

### `suite_arguments`

```python
def suite_arguments(run, *, gpus=None, workers_per_gpu=None, base_port=None, rerun_errors=False, script=None, max_total_cost_usd=None, prepared=None, workspaces=None)
```

suite 设置依次来自运行配置、deploy 的 [sim]（或 benchmark 槽位，或本机的 `workspaces` 个工作区），最后为命令行。

### `preflight`

```python
def preflight(run, log=print)
```

任何 worker 启动前：安装运行所需且本机缺少的内容（install.prepare），启动未响应的常驻服务，检查外部服务响应，并启动按需服务 broker。返回 benchmark worker 和 kernel 的解释器（None 表示 harness 自身）、源码目录和环境变量；kernel 解释器写入 $HARNESS_KERNEL_PYTHON 供 driver 使用。

### `execution_settings`

```python
def execution_settings(run, script=None)
```

扩展 suite 的任务或 seed 时不可更改的设置。部署位置、worker 槽位和 suite 花费上限可以改变；
episode 预算、worker 选项和脚本回复会影响测量结果，因此必须保持一致。

### `script_hash`

```python
def script_hash(script)
```

脚本回复的哈希（None 表示由模型回答），与执行设置中记录的相同。

### `merge_invocation`

```python
def merge_invocation(previous, invocation)
```

一次运行加入或扩展 suite 时，suite.json 保留的 invocation：本次运行的参数，任务和 seed
取两者的并集（多个进程可以共用一个输出目录）。None 表示保留原来的 invocation。

### `recorded_invocation`

```python
def recorded_invocation(output)
```

OUTPUT/suite.json 记录的 `harness run` 参数，供 `harness run --resume` 使用。
没有 suite、suite 早于 `invocation`（错误信息中给出手动续跑的命令），或其 episode 不是
invocation 的任务 × seed（不同选择的运行共用了该目录：续跑会多出 episode）时，抛出 ValueError。

### `check_resume`

```python
def check_resume(output, settings, previous=None)
```

拒绝混合不兼容结果，并返回旧 suite 未记录的字段。在 preflight 前调用，并在持有 suite
元数据锁时再次调用。旧 suite 检查当时记录的 identity 和 layout；预览列出未能核查的字段。
下一次实际运行记录完整设置，同时保留历史上无法核查的字段列表。

### `preview`

```python
def preview(run, output, *, script=None, rerun_errors=False, max_total_cost_usd=None, invocation=None)
```

描述选中的实验，不安装依赖也不执行任务。配置已经解析完成（自动部署可能缓存其方案）。
这是配置预览，不是硬件或服务就绪检查。`invocation` 是这次运行将要记录的命令行（run_suite）。

### `metadata_lock`

```python
def metadata_lock(output)
```

持有 OUTPUT/suite.json.lock：多个进程可以共用一个输出目录（每张 GPU 一个）。

### `write_running`

```python
def write_running(output, entry, add=True)
```

把 `entry` 加入 OUTPUT/.running，或将其移除（没有进程剩下时删除该文件）。调用方须持有 metadata_lock。

### `outcome`

```python
def outcome(output, tasks, seeds, record, *, started, interrupted=False, max_total_cost_usd=None)
```

一次 `harness run` 对它所请求的 episode 做了什么（OUTPUT/outcome.json）。

episode 状态取 inspect_suite 的结果，但只限这些任务和 seed：共用同一输出目录的其他进程各自报告自己的部分。`result` 决定退出码（EXIT_CODES）。

### `stop_workers`

```python
def stop_workers()
```

停止本进程启动且尚未停止的所有 worker。

### `run_suite`

```python
def run_suite(run, output, *, invocation=None, **options)
```

将 `run` 的全部任务和 seed 运行结果写入 `output`（选项见 suite_arguments），并返回运行结果，同时写入 OUTPUT/outcome.json。Ctrl-C 会停止本次运行的 worker，并返回 result 为 "interrupted" 的结果。`invocation` 即 `harness run` 的参数，写入 suite.json，供 `harness run --resume` 使用（merge_invocation）。
