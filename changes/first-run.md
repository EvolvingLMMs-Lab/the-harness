---
core: minor
agent: minor
app: minor
external-agents: minor
---
The first run is the same in the terminal and in the app, and no longer needs an API key: it lists what on this computer can be the model (Claude Code or Codex signed in here, which run under your own plan; a provider's key found in the environment or kept before; a local model; or a key you type), asks the one you choose for one word, and keeps it only when it answers. A key that works is kept in the credentials file even when it came from the shell's environment. The identity `default` exists from the first start on. `harness setup` runs the first run again, `harness model` changes the model, `harness model --list` prints what was found. Calls of an agent under your plan count against the identity's daily calls, not its dollars. The old numbered questions of the terminal's first run are gone.
<!-- zh -->
首次引导在终端和 app 里是同一套流程，并且不再必须有 API key：它列出这台电脑上能当模型用的东西（已登录的 Claude Code 或 Codex，用你自己的订阅；环境变量或凭据里已有的 key；本机模型；或者现在填一个 key），让你选的那个回答一个词，答得出来才保存。能用的 key 即使来自 shell 的环境变量也会写进凭据文件。`default` 身份从第一次启动起就存在。`harness setup` 重新走一遍首次引导，`harness model` 换模型，`harness model --list` 打印发现的来源。订阅下的 agent 调用计入身份的每日调用次数，不计入美元额度。终端首次运行原来的编号问答已移除。
