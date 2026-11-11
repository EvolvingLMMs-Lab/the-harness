---
core: patch
external-agents: patch
---
An ACP agent used as the model keeps its session across a run: a call that only drops an old picture, leaves out a reply that was not kept, or changes part of the system prompt goes on in the same session instead of sending the whole conversation again. The agent's process ends when the conversation ends or the model is changed. A model or reasoning effort the agent cannot set is now an error instead of being ignored: write `"default"` to take the agent's own.
<!-- zh -->
把 ACP agent 当作模型时，一次运行内会持续使用同一个会话：只是去掉了旧图片、丢弃了未采用的回复、或系统提示局部变化的调用，不再重发整个对话。对话结束或更换模型时，agent 的进程随之结束。agent 无法设置的模型或推理档位现在会报错，不再被忽略；填 `"default"` 表示使用 agent 自己的选择。
