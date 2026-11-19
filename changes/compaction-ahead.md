---
core: minor
---
The summary that compacts a conversation is written ahead: once the context reaches runtime.compact_arm_tokens (default 70% of compact_at_tokens) it is asked for in the background, beside the model's own calls, and put in at the limit, keeping the messages that came after it was asked for. The conversation waits only for what a summary not yet back has left, and writes one at the limit only where none was asked for or it failed. A long run used to stop for 43 to 70 s at each of its compactions.
<!-- zh -->
压缩对话用的摘要会提前写好：上下文达到 runtime.compact_arm_tokens（默认是 compact_at_tokens 的 70%）时，就在后台、与模型自己的调用并行地请求摘要，到达上限时换上，并保留请求摘要之后新增的消息。对话只会等一份还没写完的摘要剩下的时间；只有没有提前请求、或者提前请求失败时，才在上限处当场写一份。以前长时间的运行每次压缩都要停 43 到 70 秒。
