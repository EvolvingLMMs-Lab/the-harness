---
core: minor
---
A program can ask the model at the point where only the model can judge: decide(question, show) waits for the model's <answer> and returns it, so what depends on how things are then is decided then, not written in advance. A <wait> now carries its check, a program that only reads (<wait>60<check>...</check></wait>): it runs when the wait ends and the model is told what it printed; a wait without a check is refused, and nothing in a check acts.
<!-- zh -->
程序可以在只有模型才能判断的地方当场问模型：decide(question, show) 会等模型用 <answer> 回答再返回，要看当时情况才能定的事就在当时定，不再提前写死。<wait> 现在必须带上检查，一段只读的程序（<wait>60<check>...</check></wait>）：等待结束时执行，并把输出告诉模型；没有检查的 wait 会被拒绝，检查里不能做任何动作。
