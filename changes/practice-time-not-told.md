---
core: patch
---
A run that learns its environment is no longer told at its start how many minutes it has. With `runtime.tell_budget = "always"` the time left is still told with every call.
<!-- zh -->
学习环境的运行不再在开头被告知它有多少分钟。设置 `runtime.tell_budget = "always"` 时，剩余时间仍然每次调用都告知。
