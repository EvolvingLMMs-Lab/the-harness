---
core: patch
---
The model is not told the pace of its replies while the environment says the agent cannot act (its state has `can_act` false): nothing stands waiting for the model then. The same word of the environment is what keeps the tree of reflexes from being judged, now read from the state by default.
<!-- zh -->
环境表示智能体现在不能行动时（状态里 `can_act` 为 false），不再告诉模型上一次回复的节奏：这时没有东西在等模型。反射树不被判断用的是同一个信号，现在默认从状态里读取。
