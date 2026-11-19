---
core: minor
---
A node of the tree gives the environment back as soon as its situation is over: its program is ended there, its work done (set_reflex while_holds=True, the default; False keeps it running until it returns). A node whose condition stopped holding, or whom a fact told to stand aside, used to keep the environment until its program returned.
<!-- zh -->
反射树的节点在它的情况结束时立刻交还环境：它的程序就此结束，算作完成（set_reflex 的 while_holds=True，默认如此；设为 False 则一直运行到程序返回）。以前条件已经不成立、或者 fact 已经让它让开的节点，会一直占着环境，直到它的程序自己返回。
