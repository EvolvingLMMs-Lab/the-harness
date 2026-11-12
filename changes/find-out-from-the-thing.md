---
core: minor
---
An environment can name the folders that hold what it gives the agent to act with (a worker's profile: `"references": [path, ...]`): the documentation and source of the libraries its programs call. Programs may read them, and the model is told where they are with its first message. The core prompt says that what the agent is given to act with is part of what is there: before relying on something it did not make, it finds out from the thing itself what it does, what it assumes and what it leaves to the agent, not from what it remembers of it.
<!-- zh -->
环境可以说明它交给 agent 使用的东西放在哪些目录（worker 的 profile：`"references": [path, ...]`）：程序所调用的库的文档和源码。程序可以读这些目录，模型在第一条消息里得知它们的位置。核心提示词说明：交给 agent 使用的东西也是“现有的东西”的一部分；在依赖一个不是自己做的东西之前，要从它本身弄清它做什么、默认假设什么、哪些留给 agent 决定，而不是凭对它的印象。
