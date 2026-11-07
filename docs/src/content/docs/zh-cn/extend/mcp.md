---
title: "接入 MCP 服务器和 Agent Skills"
description: "把 MCP 服务器的工具，以及写成 Agent Skills 的操作知识，交给 agent。"
---

有两种标准格式可以扩展 agent，而无需编写 skill：

- **MCP 服务器**（Model Context Protocol）给它工具：以文本形式获取网页、一个文件夹中的文件、GitHub、搜索引擎、你自己的服务。
- **Agent Skill** 是一个包含 `SKILL.md` 的文件夹，给它操作知识：任务需要时它读取的说明和文件。

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
文件可以把它放到另一台电脑上。`mcp-example` 包里有一个小服务器及其清单，可以从它开始。只支持 stdio 的服务器以服务的形式运行在一个 HTTP
桥后面，因为 agent 的程序不能启动进程。

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
