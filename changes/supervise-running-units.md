---
core: minor
---
The model can read what a running unit has printed so far: `output_of(unit)` with the unit's name (or `.output()` on its handle from `entries()`) gives the last characters (2000 by default, at most 4000) without taking them from the unit's result. When a wait is over, each running program is listed with how long ago it last printed, and the core prompt now says that work left running is the model's to supervise: check it before waiting again, and cancel it when it is not doing what was expected. A program in an isolated workspace still gives its output only when it ends.
<!-- zh -->
模型可以读取正在运行的单元到目前为止打印的内容：用单元的名字调用 `output_of(unit)`（或对 `entries()` 给出的句柄调用 `.output()`），得到最后的若干字符（默认 2000，最多 4000），并且不会从单元的结果里取走它们。一次等待结束时，每个正在运行的程序都会列出它上一次打印是多久以前；核心提示词现在说明，留下仍在运行的工作由模型自己看管：继续等待之前先检查，没有按预期进行时就取消。隔离工作区里的程序仍然只在结束时给出它的输出。
