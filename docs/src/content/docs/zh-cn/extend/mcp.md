---
title: "接入 MCP 服务器和 Agent Skills"
description: "把 MCP 服务器的工具，以及写成 Agent Skills 的操作知识，交给 agent。"
---

有两种标准格式可以扩展 agent，而无需编写 skill：

- **MCP 服务器**（Model Context Protocol）给它工具：以文本形式获取网页、一个文件夹中的文件、GitHub、搜索引擎、你自己的服务。
- **Agent Skill** 是一个包含 `SKILL.md` 的文件夹，给它操作知识：任务需要时它读取的说明和文件。

## 从命令行连接

```bash
harness mcp add --transport http notes https://mcp.example.com/mcp
harness mcp add --header "Authorization: Bearer TOKEN" search https://search.example.com/mcp
harness mcp add --env API_KEY=... files -- npx -y @example/files-server /data
harness mcp list
harness mcp test files          # connects once and lists its tools
harness mcp get files
harness mcp disable files       # off without removing it; enable switches it on again
harness mcp remove files
```

一个服务器就是一个名字加一个 URL（streamable HTTP），或者在 `--` 之后给出一条在这台电脑上启动的命令（stdio）。`--env` 和 `--header` 的值和你的凭据存在一起，任何地方都不会列出。你添加的服务器，agent 可以调用它的全部工具；`--tools a,b` 只授权这几个。`harness mcp test NAME` 会说明服务器为什么没有应答、该怎么办。app 的 **Settings → Connectors** 做同样的事，Python 也一样：

```python
from harness.sdk import connectors

connectors.mcp_add("notes", url="https://mcp.example.com/mcp")
print(connectors.mcp_test("notes")["tools"])
```

`harness mcp serve` 是反过来的方向：把 The Harness 自己作为 MCP 服务器给别的客户端用（[在编辑器里使用](/docs/zh-cn/extend/editors/)）。

说 Agent Client Protocol 的外部 agent 用同样的方式管理：`harness agents list`（`--registry`：连 ACP Registry 里的一起列出）、`harness agents add NAME`、`harness agents add NAME -- COMMAND ARGS`（你自己的命令）、`harness agents test NAME`（启动它并让它回答一个词）、`harness agents remove NAME`。

## 不安装 app 也能连接

安装 core 不预选外部 app、agent 或 MCP 服务器；任务需要的 Harness 包仍默认自动安装。`harness mcp add` 写下的就是
`~/.harness/config.toml` 里的一个连接，你也可以手写：

```toml
[[connectors]]
id = "my-tools"
transport = "stdio"
command = "/absolute/path/to/server"
args = []
allowed_tools = ["inspect", "act"]
resource = "shared-target"
timeout_seconds = 60
```

HTTP 使用 `transport = "http"` 和 `url`，替代 `command`、`args`。可选的 `env`、`headers`、
`fields`、`secrets` 与 app 自定义连接配置相同，密钥占位符只在 host 解析。
`allowed_tools` 授权确切工具名；`["*"]` 是显式授权整个服务器；`tools_off` 优先拒绝。
服务器注解不授予权限，`read_only_tools` 继续支持已审查的只读操作。

同一 host 中，共用 `resource` 的调用跨任务串行，独立资源可并行；未指定时以连接 id 为资源。
每个任务最多同时持有 16 个 MCP host 请求。这是 host 内协调，不是跨进程的应用锁。

`mcp_call()` 返回完整 MCP 结果，包括 `content`、`structuredContent`、`isError` 和元数据。
content 中的图像自动附加到下一次模型观察。检查原生错误和回执；派发后的传输错误表示结果未知，
不会自动重放。trace 保存原始结果和迟到回执。取消调用方阻止排队中的派发，不宣称撤销已派发的远端副作用。
任务结束时回收自身启动的 stdio 进程。

对于自定义连接，host 在派发前重新读取当前授权，共享资源排队结束后也会复核。
关闭或删除连接、禁用工具、移除授权对已运行任务同样生效。连接或凭据变更会拒绝旧
客户端继续调用，需要新任务；新增授权不会扩大旧任务的权限。撤权不撤销此前已授权
并派发的操作。

## 在 app 中添加 MCP 服务器

**Settings → Connectors** 用于添加服务器：

- **From the list**：Fetch（以文本形式获取网页；需要 [uv](https://docs.astral.sh/uv/)）、Filesystem（一个文件夹；需要
  Node.js）、GitHub（一个个人访问 token）、Brave Search（一个 API key；需要 Node.js）、Playwright（一个独立的浏览器；需要
  Node.js）、Notion（一个集成 token；需要 Node.js）。
- **Your own server**：在这台电脑上启动它的命令（stdio），或它的 URL（HTTP），以及它的环境变量或请求头。命令要经你确认后才会添加。

**Tools** 会启动服务器并列出它的工具；关掉 agent 不应使用的那些。密钥和 token 保存在 `~/.harness/config.toml` 的
`[keys]` 下。agent 的程序通过 The Harness 访问服务器，由 The Harness 附上密钥，程序本身永远看不到密钥。

App 允许调用目录中 Fetch、Filesystem 和 Brave Search 连接器经过审查的只读工具。Brave Search 支持网页搜索和本地搜索。
自定义连接器和目录中的其他工具仍可列出，但列出的工具也可能在弹出审批提示前被拒绝。服务器提供的 `readOnlyHint` 等注解不能授予调用权限。 添加自定义连接器时，可信操作者可以通过 `read_only_tools` 指定已审查的工具名。

在 Linux 上，App 目录中的 Filesystem 连接器可以通过 `write_file` 创建新文件。宿主先绑定配置目录内的实际目标，显示完整路径并隐藏内容。批准后由宿主创建一次，已存在的文件、符号链接和变化的父目录会被拒绝。其他写入保持关闭。丢失回执时不会自动重发。

:::caution
服务器的工具以服务器拥有的权限运行。文件系统或 shell 服务器会把 agent 的程序原本接触不到的文件和进程交给它们，所以只接入那些你愿意让
agent 在任何任务中使用其工具的服务器。
:::

## 在一次运行中使用 MCP 服务器

实验通过 `mcp` skill 和一个以 HTTP 方式运行该服务器的服务，为它的 agent 提供 MCP 工具：

```toml
[overrides.agent.services]
mcp = ["mcp-units"]

[overrides.agent.skills]
enable = ["mcp"]
```

之后程序可以这样调用：

```python
tools = mcp_tools()
mcp_call("convert", value=3, from_unit="m", to_unit="cm")
```

服务器和其他服务一样是一个服务（[服务](/docs/zh-cn/configure/services/)）：一份种类为 `mcp` 的清单写明如何启动它以及它的端口，deploy
文件可以把它放到另一台电脑上。`mcp-example` 包里有一个小服务器及其清单，可以从它开始。只支持 stdio 的服务器也可以使用上面的显式 host 连接，程序本身不启动服务器。

要接入只读扩展，请在可信服务清单的 `client.read_only_tools` 列表中填写经过审查的 MCP 工具的确切名称。
内置的 `mcp-units` 清单以这种方式声明了 `convert`。该策略适用于部署实际运行或连接的服务器。服务清单可以包含以下配置。

```toml
[client]
url = "{url}/mcp"
read_only_tools = ["convert"]
```

列表中的工具即使没有服务器注解也可以调用。实验中的其他 MCP 工具会在审批前被拒绝，即使它们出现在 `mcp_tools()` 的结果中。

## Agent Skills

Agent Skill 是一个包含 `SKILL.md` 的文件夹，也就是 Claude 和 OpenAI 的 skill 所用的格式：

```markdown
---
name: expense-report
description: Fill in the company's expense report form from receipts.
---

Open the form at https://example.com/expenses ...
```

agent 在它的 prompt 中看到每个 skill 的名字和描述，并在任务需要时用 `read_skill(name)` 读取它的说明和文件。它不需要代码。

要在 app 中添加一个，选择 **Settings → Packages → Add**，然后给出一个文件夹、一个 `.zip`、一个 `.zip` 的 URL 或一个 git
URL；GitHub 文件夹的 URL 只取那一个文件夹，例如 `https://github.com/anthropics/skills/tree/main/skills/pdf`。在终端中：

```bash
harness install ./expense-report
```

包在它的 `agent-skills/<name>/SKILL.md` 文件夹中附带 Agent Skills（[编写包](/docs/zh-cn/extend/packages/)）。

### 身份的技能来源

agent 身份有它自己的技能，也可以从**技能来源**拿别处写好的技能：这台电脑上的一个文件夹或一个 `SKILL.md`、一个仓库（`github:OWNER/REPO[#FOLDER]`、`git:URL`），或者一个压缩包、一个 `SKILL.md` 的地址。一个来源可以带一个技能，也可以带多个（里面每个带 `SKILL.md` 的文件夹）。

```bash
harness skills test github:anthropics/skills      # what it holds, without taking anything
harness skills add github:anthropics/skills#skills/pdf
harness skills sources                            # the sources and the skills each brought
harness skills update                             # read them again; new skills are taken in
harness skills remove pdf                         # the source, and the skills it brought (--keep keeps them)
harness skills                                    # the identity's skills, with their evidence
```

从来源拿进来的东西是别人写的：每个技能以**提议**（proposed）的证据等级进入，作为模型可以读的说明；它带的程序要等在这里自测通过才会被使用。共享库（`$HARNESS_HOME/libraries`，`harness install` 作为 library 装来的）和来源列在一起，只读。在 Python 里：`Agent.skill_sources()`、`skill_source_add(source)`、`skill_source_test(source)`、`skill_source_remove(id)`。
