---
core: patch
---
A library function called while a reflex's condition is judged no longer writes a step record per call. Those records counted against the condition's time budget: a condition built from several helper functions went over its 5 ms and was set aside with every node under it. A function called by a program still records its step, and the tree still notes the entry's use when its condition holds.
<!-- zh -->
在判断反射条件的过程中调用库函数，不再每调用一次就写一条步骤记录。这些记录的时间原本算进条件的时间预算：由几个辅助函数组成的条件会超出 5 毫秒，连同下面所有节点一起被搁置。程序调用的函数照常记录步骤；条件成立时，反射树仍会记下该条目被用到了一次。
