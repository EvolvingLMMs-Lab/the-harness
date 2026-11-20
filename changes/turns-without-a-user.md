---
core: minor
---
A run nobody talks to has the same turns as a conversation with a user. The model's answer ends its turn; while a program it started still runs, the run goes on and the program's end starts the next turn, and the run ends with an answer given when none runs any more. Before, the first answer ended the run and cancelled what was running. The run's limits (the model's calls, the wall time) cover all its turns. A reply in plain text is always the answer: a reply that only says what the model will do next is no longer sent back as a format error.
<!-- zh -->
没有用户的运行和有用户的会话使用同一套轮次规则。模型的答案结束这一轮；它启动的程序还在运行时，运行继续，程序结束会开启下一轮；没有程序在运行时给出的答案才结束整个运行。以前第一条答案就结束运行并取消正在运行的程序。运行的上限（模型调用次数、时长）覆盖它的所有轮次。纯文字回复一律是答案：只说“接下来要做什么”的回复不再被当作格式错误退回。
