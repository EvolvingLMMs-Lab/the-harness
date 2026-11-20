---
core: minor
---
A node of the tree can say that its program uses no channel of the environment (`set_reflex(..., claims=[])`): it acts on nothing itself (it sets a fact, or a rule that other code reads), so it takes the environment from nobody, keeps no later node waiting, and runs beside everything for as long as its situation lasts.
<!-- zh -->
反射树的节点可以声明它的程序不占用环境的任何通道（`set_reflex(..., claims=[])`）：它自己不做动作（只设一个 fact，或者设一条别的代码会读的规则），所以不从任何人手里拿走环境，不让后面的节点等待，在它的情况持续期间和其他一切并行。
