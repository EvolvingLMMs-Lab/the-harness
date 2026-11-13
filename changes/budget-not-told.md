---
core: minor
---
The model is no longer told with every call what the run has left (its model calls, its environment steps, its live time): the host keeps the limits and ends the turn at them. A run that needs the countdown, such as a benchmark whose episodes are a few dozen calls, sets `runtime.tell_budget = "always"` to get it as before. The reflection prompt no longer says anything that belongs to one game.
<!-- zh -->
不再每次调用都告诉模型这次运行还剩多少（模型调用次数、环境步数、练习时间）：上限由宿主执行，到了就结束这一轮。需要倒计时的运行，例如单局只有几十次调用的评测，设置 `runtime.tell_budget = "always"` 即可恢复原来的告知。反思提示词里不再有属于某一个游戏的内容。
