---
core: minor
---
A condition of a reflex that fails no longer removes its node and the nodes under it. One that raises does not hold that once and is judged again the next time; one that is too slow three times in a row stays in the tree and is not judged until the node is set again. The model is told what went wrong once for each reason, and the node's line says how often. A trial of a node whose condition raises says so in its result.
<!-- zh -->
反射的条件出故障时，不再把这个节点和它下面的节点删掉。条件抛异常，这一次算不成立，下一次照常判断；连续三次太慢，节点留在树里但暂停判断，重新设这个节点后恢复。每种原因只告诉模型一次，节点的状态行里写出次数。节点试验时条件抛异常，试验结果里会写明。
