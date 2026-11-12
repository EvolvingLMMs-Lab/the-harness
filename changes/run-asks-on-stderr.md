---
core: patch
---
`answer=$(harness run "task" -p)` asks where to work on the terminal instead of failing, as the
answer goes to the pipe and the question to stderr; without a terminal the error is one line
for a person and JSON only for a program.
<!-- zh -->
`answer=$(harness run "task" -p)` 会在终端里询问在哪里工作，不再报错：回答进管道，问题走 stderr；
没有终端时，给人看的错误只有一行，只有程序读取时才输出 JSON。
