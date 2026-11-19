---
core: minor
---
Where the environment pauses and declares channels, units share it by channel: a unit takes only the channels it claims (a node says them with set_reflex claims=), pauses only the lower units that use one of them, and the others go on beside it. The environment is told which channels to pause and is given the commands of units that start together as one (session._combine).
<!-- zh -->
在会暂停、并且声明了通道（channel）的环境里，单元按通道共享环境：一个单元只占用它声明的通道（节点用 set_reflex 的 claims= 声明），只暂停用到这些通道的低优先级单元，其余单元在旁边照常运行。环境会被告知要暂停哪些通道，同一时刻启动的多个单元的命令会合并成一条交给它（session._combine）。
