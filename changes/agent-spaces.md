---
core: minor
workspace: minor
computer: minor
browser: minor
qq: minor
---
The Harness reaches every environment through the Agent Space Protocol: every action ends with
exactly one typed outcome (done, refused, failed, cancelled or unknown), an action sent again never
acts twice, and what an environment pushes goes into the trace and to the reflexes before it wakes
the model. Existing workers work unchanged behind a translation layer; workspace, computer and
browser declare their spaces. `--space ADDRESS` enters any space that speaks the protocol, and the
agent acts there through its vocabulary. The new `qq` package makes a QQ account a space (OneBot 11),
with group allowlists, owner binding and pairing codes. The core now depends on the protocol's
Python SDK, which needs only the standard library.
<!-- zh -->
The Harness 通过 Agent Space Protocol 和所有环境打交道：每个动作恰好得到一个有类型的结果（完成、拒绝、
失败、取消或不确定），重发的动作不会做两次，环境推来的东西先进记录和反射，再叫醒模型。现有的 worker
经转换层照常工作；workspace、computer 和 browser 声明了各自的 space。`--space ADDRESS` 进入任何说这个
协议的 space，agent 按它的词汇行动。新的 `qq` 包把一个 QQ 账号变成 space（OneBot 11），带群白名单、
主人绑定和配对码。核心现在依赖这个协议的 Python SDK，它只需要标准库。
