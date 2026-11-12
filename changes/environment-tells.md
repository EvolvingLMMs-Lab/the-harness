---
core: minor
---
An environment can tell the model what happens in it by itself. A run has an entry for it, `TaskRun.tell(kind, detail, views=...)`: the event reaches the model at once (a wait ends, a call in flight is asked again), with the pictures given beside its text. A worker whose profile says `"tells": True` is given where to tell (`tell_to`), and its `tell(kind, detail, views)` posts there and returns at once; `BenchWorker` has both. Nothing is read on time for it, and workers that do not say `tells` behave as before. The listener is on the run's own computer.
<!-- zh -->
环境可以把自己发生的事情告诉模型。运行为此保留了一个入口 `TaskRun.tell(kind, detail, views=...)`：事件立刻到达模型（等待结束，在途的调用重新询问），给出的图片出现在事件文字旁边。profile 里写着 `"tells": True` 的 worker 会被告知往哪里说（`tell_to`），它的 `tell(kind, detail, views)` 把事件投递过去并立刻返回；`BenchWorker` 两者都有。不为此按时间读取任何东西，没有声明 `tells` 的 worker 行为与之前相同。监听只在运行所在的这台电脑上。
