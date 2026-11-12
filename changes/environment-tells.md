---
core: minor
---
An environment can tell the model what happens in it by itself, as a message. A run has an entry for it, `TaskRun.tell(content)`: `content` is a string or a list of text and image parts, as conversations give content, and it reaches the model at once (a wait ends, a call in flight is asked again), read as "Message from the environment". A worker whose profile says `"tells": True` is given where to tell (`tell_to`), and its `tell(content)` posts there and returns at once; `BenchWorker` has both. Nothing is read on time for it, and workers that do not say `tells` behave as before. The listener is on the run's own computer.
<!-- zh -->
环境可以把自己发生的事情作为一条消息告诉模型。运行为此保留了一个入口 `TaskRun.tell(content)`：`content` 是一个字符串，或者像对话内容那样由文字和图片组成的列表，它会立刻到达模型（等待结束，在途的调用重新询问），模型读到的是"Message from the environment"。profile 里写着 `"tells": True` 的 worker 会被告知往哪里说（`tell_to`），它的 `tell(content)` 把消息投递过去并立刻返回；`BenchWorker` 两者都有。不为此按时间读取任何东西，没有声明 `tells` 的 worker 行为与之前相同。监听只在运行所在的这台电脑上。
