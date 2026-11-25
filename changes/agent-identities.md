---
core: minor
agent: minor
---
Agent identities: each has a fixed id and a display name in any language, a folder with
`SOUL.md`, `IDENTITY.md`, `USER.md` and its memory, and a key pair. `harness agent
new/use/list/about/rename/delete/say/memory` manage them, `harness --identity ID` runs the
terminal chat as one, and `harness.sdk.Agent` does the same in Python. With several
identities and none chosen, a terminal asks and a script fails. One identity lives in one
host at a time. Earlier identities are migrated on first opening and every original file is
kept, so the earlier version still opens them. `harness agent "TEXT"` becomes `harness
agent say "TEXT"`; the earlier form works for one release.
<!-- zh -->
agent 身份：每个身份有不可改的 id 和任意语言的显示名，一个包含 `SOUL.md`、`IDENTITY.md`、`USER.md` 和记忆的文件夹，以及一对密钥。用 `harness agent new/use/list/about/rename/delete/say/memory` 管理，`harness --identity ID` 让终端对话以某个身份运行，Python 里用 `harness.sdk.Agent`。多个身份且未选定时，终端会询问、脚本会报错。一个身份同一时间只在一个 host 里活着。旧身份第一次打开时迁移，原文件全部保留，旧版本仍能打开。`harness agent "一句话"` 改为 `harness agent say "一句话"`，旧写法在一个版本内仍可用。
