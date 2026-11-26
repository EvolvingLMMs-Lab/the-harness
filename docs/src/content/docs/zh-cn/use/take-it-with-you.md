---
title: "带走身份"
description: "把 agent 身份作为包或角色卡分享，领养别人分享的身份，用口令备份，搬到另一台电脑，以及从 OpenClaw 或 Hermes 把 agent 带过来。"
---

身份是一个文件夹（[保留 agent 身份](/docs/zh-cn/use/identities/)），所以可以带走。五条命令覆盖这些事，在 app（设置 › 数据）和 Python（`harness.sdk.Agent`）里含义相同：

| 命令 | 做什么 | 它的密钥和凭据 |
|---|---|---|
| `harness agent share ID --to PLACE` | 分享人设、头像、技能和反应 | 永远不带 |
| `harness agent adopt SOURCE` | 用别人分享的身份新建一个身份 | 新的密钥 |
| `harness agent backup ID` | 完整备份，用口令加密 | 带上，加密 |
| `harness agent restore FILE` | 在这台电脑上恢复备份 | 恢复回来 |
| `harness agent retire ID` | 搬走后在这台电脑上停下它 | 留着，不再使用 |

## 分享身份

```sh
harness agent share default --to github:you/yu-agent
```

包里有人设（`SOUL.md`、`IDENTITY.md`）、头像、技能及其程序和测试，以及你或它加上的反应。记忆和 `USER.md`（它对你的了解）默认不带，加 `--with-memory` 才带。私钥、渠道凭据、模型 key、对话、日历和花费记录永远不带。

发送之前，命令逐个文件打印所有将要公开的文字，然后问 `Publish? [y/N]`。这台电脑上的位置换成名字（你的主目录换成 `~`），反应里提到的群换成占位符，比如 `<group>`。只要其中出现模型 key 或渠道 token，分享就停下，并说明是哪个文件。检查过输出的脚本可以给 `--yes`。

`--to` 和 [`harness share`](/docs/zh-cn/learn/while-working/) 接受的写法一样：

- `github:OWNER/REPO` 或 `github:OWNER/REPO#FOLDER`：它新建的仓库默认是**私有**的，给 `--public` 才公开。
- `git:URL#FOLDER`：任何 git 远端。
- `USER@HOST:FOLDER`：用 scp 复制的归档。
- 这台电脑上的文件夹或 `.tar.gz` 文件。

包的 `package.toml` 声明 `[provides] identity`，README 里写着领养它的那一行命令。

### 角色卡

```sh
harness agent share default --card --to yu.png
harness agent share default --card --to yu.json
```

`--card` 写出一张只有名字和人设的 Character Card V3：JSON，或者嵌在头像 PNG 里（身份文件夹里需要有 `avatar.png`）。技能、反应和记忆不进角色卡。

## 领养身份

```sh
harness agent adopt github:friend/study-buddy
harness agent adopt ./study-buddy.tar.gz --id buddy
harness agent adopt card.png
```

领养得到的是一个**新身份**：新的 id（取自它的名字，或用 `--id` 指定）、新的密钥对，以及身份文件夹里记着来源的 `adopted.json`。别人的技能是你还不了解的程序，所以领养来的技能一律从*提议*开始，在它自己的测试在你的电脑上通过之前，它的程序不会被使用：

```sh
harness agent adopt --test --identity buddy
```

测试通过的技能变为*自测通过*，从此可以使用；失败或没有测试的仍是提议。领养来的反应一开始都是**停用**的，在 设置 › 学到的东西 或用 `harness library` 逐个启用。角色卡提供名字、人设（`SOUL.md`），PNG 角色卡还提供头像；其他字段忽略。

## 备份和恢复

```sh
harness agent backup default -o yu.harness-backup
```

备份包含整个身份：人设、记忆、对话、学习库、反应、日历、花费记录、它的私钥和这个身份的渠道凭据。模型 key 是所有身份共用的，只有加 `--with-keys` 才带上。它会两次询问口令；脚本设置 `HARNESS_BACKUP_PASSPHRASE`。请把文件保管好：拿到文件和口令的人就能成为这个身份。

文件只用标准库加密：scrypt 由口令和随机盐派生两把密钥，计数器模式的 HMAC-SHA256 负责加密，覆盖整个文件的 HMAC-SHA256 校验值在解密之前先检查。口令错误或文件被改动时整个拒绝，什么也不写。

```sh
harness agent restore yu.harness-backup
```

恢复时询问口令，用相同的 id 和相同的密钥放回身份，补上备份里有、这台电脑还没有的模型 key，并列出需要重新登录的渠道。这里已经有同 id 的身份时会拒绝，除非给 `--replace`；原来那个会保留在 `agents/.ID.before-restore-TIME`。

## 搬到另一台电脑

两台电脑之间没有协调者，所以搬家是一次明确的操作：

1. 在旧电脑上：`harness agent backup default -o yu.harness-backup`。
2. 在新电脑上：`harness agent restore yu.harness-backup`，然后重新登录它的渠道。很多聊天渠道同一账号只能在一处在线，所以旧电脑的连接会掉线。
3. 在旧电脑上：`harness agent retire default`。

retire 会在身份文件夹里写下 `retired.json`。常驻服务不再启动它，正在运行的主机会暂停它，之后在那台电脑上再打开它（`harness agent`、`harness --identity`、app、`Agent("default")`）都会提示它已搬走。它的文件保留。在那台电脑上恢复一份备份就能把它带回来。

如果只是想换模型：在 设置 › 模型 里给这个身份选另一个模型，或者直接告诉它；`/model` 只改一个对话的模型。人设、记忆、技能和反应都不变。

## 从 OpenClaw 或 Hermes 带过来

```sh
harness agent import openclaw
harness agent import hermes ~/.hermes/profiles/coder
```

不给文件夹时，它读取两者各自存放 agent 的位置：OpenClaw 的工作区（`OPENCLAW_WORKSPACE_DIR`，否则 `~/.openclaw/workspace`）和 Hermes 的 profile（`HERMES_HOME`，否则 `~/.hermes`）。第一次打开 app 时的"带过来"做的是同一件事。

| 来源 | 人设 | 记忆 | 技能 |
|---|---|---|---|
| OpenClaw | `SOUL.md`、`IDENTITY.md`（名字）、`AGENTS.md`（作为指示写进 `SOUL.md`）、`USER.md` | `MEMORY.md` 和 `memory/*.md` | `skills/*/SKILL.md` |
| Hermes | `SOUL.md`、`profile.yaml`（显示名）、`memories/USER.md` | `memories/MEMORY.md` | `skills/**/SKILL.md` |

记忆成为 `memory/` 里的条目，私人范围，每条最多 1200 个字符。技能以*提议*身份进来。配置、`.env`、`auth.json`、OpenClaw 的 `credentials/` 和 Hermes 的平台状态从不读取，所以不会带来任何渠道 token 或 key，同一个 token 也不会同时被两个 agent 使用。完成后它会建议先停掉原来的 agent（`openclaw gateway stop`、`hermes gateway stop`），再把它的渠道接到新身份上。

## 在 Python 里

```python
from harness.sdk import Agent

yu = Agent("default")
yu.share("./shared", confirm=lambda preview: True)
yu.backup("yu.harness-backup", "a long passphrase")
buddy = Agent.adopt("github:friend/study-buddy", test=True)
Agent.restore("yu.harness-backup", "a long passphrase")
```

`share` 只有在 `confirm(preview)` 返回真时才发送；预览的 `texts` 列出每一段公开的文字。

## 早期版本的数据

这个版本第一次打开你的数据时会保留每一个原文件，所以退回早期版本仍然能用：

| 早期数据 | 去向 |
|---|---|
| `agents/ID/identity.json` 里的 instructions | `SOUL.md`；`identity.json` 保留早期版本读取的内容 |
| `agents/ID/memory.json` | `memory/` 里每条一个文件，私人范围，索引在 `MEMORY.md` |
| `agents/ID/library/` | 原样成为这个身份的学习库 |
| `$HARNESS_HOME/libraries` 里的全局库 | 保持全局，作为共享库显示，只读 |
| 终端对话和 app 的对话 | 作为早期对话列在 `default` 下：只读，可以作为新对话继续 |
| `agents/ID/sessions` | 这个身份的早期对话 |
| `personal.about` 和 `personal.instructions` | `default` 的 `USER.md` 和 `SOUL.md` |
| `harness agent "一句话"` | `harness agent say "一句话"`；旧写法在一个版本内仍可用 |
