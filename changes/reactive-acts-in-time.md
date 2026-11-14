---
core: minor
---
The core prompt says what the tree of reflexes is for: to act in time, because the model's reply takes seconds. A node's answer is an action that takes effect within the time its situation leaves; telling the model is for what no action is known for, or beside acting. A node that tells can end what runs too (`set_reflex(name, when, "EVENT", ends=True)`): the execution ends with that event. The model is told how many nodes of the tree only tell it, and the tree's line is left out of a turn when nothing in the tree changed and there is nothing of that kind to say.
<!-- zh -->
核心提示词说明了反射树的用途：及时行动，因为模型回复一次要好几秒。节点的应对是一个在这种情况留出的时间内生效的动作；告诉模型只用于还不知道该用什么动作的情况，或者在动手之外。告诉模型的节点也可以让正在运行的东西结束（`set_reflex(name, when, "EVENT", ends=True)`）：那次执行以这个事件结束。会告诉模型树里有几个节点只是告诉它、自己不动手；树里什么都没变、也没有这类情况可说时，这一轮就不写树的那一行。
