---
core: minor
---
The core prompt is less than half as long. It keeps what every reply needs: how to reply, how to work, and one line for each call. The details of the tree of reflexes (every setting of a node) and of units (waits, what the model is told and in what order, units of its own, who has the environment) are in two pages that a program reads on demand, `guide("tree")` and `guide("units")`. A page that was read is given again after a summary of the conversation. `reflex_method()` still works and returns `guide("tree")`.
<!-- zh -->
核心提示词缩短到不到原来的一半，只留每次回复都用得上的内容：怎么回复、怎么工作、每个调用一行。反射树的细节（节点的每一项设置）和单元的细节（等待、会被告知什么及顺序、自己启动的单元、谁占用环境）放进两页按需读的说明里：`guide("tree")` 和 `guide("units")`。读过的页在对话被摘要之后会重新给一遍。`reflex_method()` 仍然可用，返回的就是 `guide("tree")`。
