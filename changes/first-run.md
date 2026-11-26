---
core: minor
agent: minor
app: minor
external-agents: minor
---
The first run is the same in the terminal and in the app, and no longer needs an API key: it lists what on this computer can be the model (Claude Code, Codex, Gemini CLI or Grok signed in here, which run under your own plan, each listed with how to install or sign in to it when it is not ready, and every other agent of the ACP Registry under More agents; a provider's key found in the environment or kept before; a local model; or a key you type), asks the one you choose for one word, and keeps it only when it answers. A key that works is kept in the credentials file even when it came from the shell's environment. The identity `default` exists from the first start on. `harness setup` runs the first run again, `harness model` changes the model, `harness model --list` prints what was found. Calls of an agent under your plan count against the identity's daily calls, not its dollars. The desktop app brings the package that connects agents, so choosing one does not depend on what the public registry has. The old numbered questions of the terminal's first run are gone.
<!-- zh -->
首次引导在终端和 app 里是同一套流程，并且不再必须有 API key：它列出这台电脑上能当模型用的东西（已登录的 Claude Code、Codex、Gemini CLI 或 Grok，用你自己的订阅，没装或没登录的也列出来并写明怎么装、怎么登录，ACP Registry 里其余的 agent 在“更多 agent”里；环境变量或凭据里已有的 key；本机模型；或者现在填一个 key），让你选的那个回答一个词，答得出来才保存。能用的 key 即使来自 shell 的环境变量也会写进凭据文件。`default` 身份从第一次启动起就存在。`harness setup` 重新走一遍首次引导，`harness model` 换模型，`harness model --list` 打印发现的来源。订阅下的 agent 调用计入身份的每日调用次数，不计入美元额度。桌面 app 自带连接 agent 的扩展包，选 agent 不再取决于公开仓库里有什么。终端首次运行原来的编号问答已移除。
