---
core: minor
agent: minor
---
A reply can be read while the agent writes it, the turn in progress can be stopped (its model call is cut off and its task cancelled; what was done stands), and the messages that wait behind it can be edited, removed, cleared, sent now or held. Chats can be renamed, pinned, archived, deleted and searched. In the API (`/api/agent/chat`, `queue`, `stop`, `chats`), in Python (`Agent.chat`, `queue`, `stop`, `send_now`, `rename_chat` and the others) and on the command line (`harness agent say`, `queue`, `stop`, `chats`). `harness agent say` and `Agent.say` now go into the identity's one queue in the session host; with `--session`, `--model`, `--workspace` or `--folder` they keep the earlier form.
<!-- zh -->
agent 正在写的回复可以边写边读；正在进行的回合可以停下（模型调用被取消、任务被取消，已经做完的保留）；排在后面的消息可以改、删、清空、立即发送或按住。对话可以改名、置顶、归档、删除和搜索。API（`/api/agent/chat`、`queue`、`stop`、`chats`）、Python（`Agent.chat`、`queue`、`stop`、`send_now`、`rename_chat` 等）和命令行（`harness agent say`、`queue`、`stop`、`chats`）都能做。`harness agent say` 和 `Agent.say` 现在进入这个身份在后台服务里的同一个队列；带 `--session`、`--model`、`--workspace` 或 `--folder` 时保持原来的形式。
