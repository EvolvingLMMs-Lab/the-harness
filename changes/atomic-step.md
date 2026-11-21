---
core: minor
---
`atomic(seconds=5)` wraps a step of a program that must not be interrupted: no node of the tree takes the environment during it, and past its seconds the nodes may again. The prompt says to wrap only that step, as small as it can be.
<!-- zh -->
`atomic(seconds=5)` 包住程序里不能被打断的一步：期间树上没有节点接管环境，超过秒数后节点又可以接管。提示里写明只包这一步，越小越好。
