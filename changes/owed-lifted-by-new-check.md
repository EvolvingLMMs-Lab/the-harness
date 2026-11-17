---
core: patch
---
After a program whose checks all held but whose result was not there, the next program is refused while it states only those checks. A program that states a new check now lifts that refusal even when its new check does not hold and it acts on nothing: it has found what was not checked. A run found a stray item on the cursor that way, and the program that then cleared it was refused because its own checks were the old ones.
<!-- zh -->
如果一个程序的检查全部成立、却没达到结果，下一个程序只要检查的还是这些，就会被拒绝运行。现在，只要某个程序提出了新的检查，即使这个新检查不成立、它什么都没做，这条拒绝也会解除：它已经找到了之前没检查的东西。之前一局里，模型正是这样发现光标上挂着一个东西；可接下来那个清掉它的程序，因为检查还是原来那几条，被拒绝了。
