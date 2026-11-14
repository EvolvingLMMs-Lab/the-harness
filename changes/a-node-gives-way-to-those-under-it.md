---
core: patch
---
A reflex that tells the model and ends what runs (`do="EVENT", ends=True`) no longer ends the answer of a node under it: like every node, it has its turn only when no node under it, or before it at its place, is answering. A node under another has done its work when its situation is over, which includes the conditions of the nodes above it: a node that says only what distinguishes it within its parent's situation is no longer counted as failed because its own condition still holds once the parent's is over.
<!-- zh -->
“告诉模型并结束正在运行的东西”的反射（`do="EVENT", ends=True`）不再把它下面节点的应对结束掉：和所有节点一样，只有它下面、以及同一位置排在它前面的节点都没在应对时才轮到它。挂在别的节点下面的节点，处境过去了就算完成，这包括它上面节点的条件：只写了自己特有条件的子节点，不会因为父节点的处境过去后自己的条件还成立而被算作失败。
