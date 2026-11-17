---
core: patch
---
An event told at once (priority `now`) no longer sets aside a call that is answering another event told at once: events of one urgency do not interrupt each other's answer, the later comes with the next call. A reflex node that tells each failure at once had failed, acted and failed again every few seconds, and each failure set aside the call answering the last one, so the model never answered while the body died. The node's own place in the queue had also overridden the rule that an event the call is already answering does not set it aside.
<!-- zh -->
立即告知（优先级 `now`）的事件，不再打断正在回应另一件立即告知事件的模型调用：同一紧急程度的事件互不打断，后来的随下一次调用告知。之前一个反射节点每次失败都立即告知，几秒内反复失败、动作、再失败，每次失败都把回应上一次失败的调用作废，身体被打死时模型一次都没回应上。节点自己设定的队列位置也覆盖了"正在回应的同一事件不打断"的规则。
