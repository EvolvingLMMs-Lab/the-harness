---
title: "Connect MCP servers and Agent Skills"
description: "Give the agent the tools of an MCP server, and know-how written as Agent Skills."
---

Two standard formats extend the agent without writing a skill:

- An **MCP server** (Model Context Protocol) gives it tools: web pages as text, a
  folder's files, GitHub, a search engine, your own service.
- An **Agent Skill**, a folder with a `SKILL.md`, gives it know-how: instructions and
  files it reads when a task needs them.

## Connect without an app

Installing core does not preselect an external app, agent or MCP server. Task-required Harness packages still install automatically by default. For a server you have selected and
installed, add an explicit connection to `~/.harness/config.toml`:

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

For HTTP use `transport = "http"` and `url` instead of `command` and `args`. Optional
`env`, `headers`, `fields` and `secrets` use the same connection settings as custom app
connectors. Secret placeholders resolve in the host. `allowed_tools` grants exact names;
`["*"]` explicitly grants the whole server. `tools_off` overrides grants. Server annotations
do not grant access. `read_only_tools` remains supported for reviewed read operations.

For custom connections, the host rechecks current settings before dispatch, including
after a shared-resource wait. Disabling or removing a connection, disabling a tool, or
removing a grant applies to existing tasks. Connection/credential changes reject the old
client and require a new task; new grants do not expand an existing task's authority.
An operation already authorized and dispatched is not rolled back by a later revocation.

Calls sharing a `resource` serialize across tasks in the same host; independent resources
can advance concurrently. Without an explicit resource, the connection id is the resource.
There are at most 16 pending MCP host requests per task. This is host-local coordination,
not a cross-process lock on the external application.

`mcp_call()` returns the complete MCP result, including `content`, `structuredContent`,
`isError` and metadata. Images in content are attached to the next model observation.
Inspect native errors and receipts. A transport failure after dispatch means the outcome
is unknown; it is never automatically replayed. Task traces retain original results and
late receipts. Cancelling a caller prevents queued dispatch; it does not claim to undo an
already dispatched remote effect. Owned stdio processes close with the task.

## MCP servers in the app

**Settings → Connectors** adds a server:

- **From the list**: Fetch (web pages as text; needs [uv](https://docs.astral.sh/uv/)),
  Filesystem (one folder; needs Node.js), GitHub (a personal access token), Brave
  Search (an API key; needs Node.js), Playwright (a browser of its own; needs Node.js),
  Notion (an integration token; needs Node.js).
- **Your own server**: the command that starts it on this computer (stdio), or its URL
  (HTTP), with its environment variables or headers. A command is added only after you
  confirm it.

**Tools** starts the server and lists its tools; switch off the ones the agent should not
use. Keys and tokens stay under `[keys]` in `~/.harness/config.toml`. The agent's programs reach
the servers through The Harness, which adds the keys, and never see them.

The app allows reviewed read tools from the Fetch, Filesystem and Brave Search catalog
connectors. For Brave Search, this covers web and local search. Custom connectors and
other catalog tools can still be listed, but a listed tool can be refused before any
approval prompt. Server annotations such as `readOnlyHint` do not grant permission. When adding a custom connector through the API, the operator may set `read_only_tools` to the names they reviewed.

On Linux the catalog Filesystem connector can create a new file through `write_file`. The host binds the actual target under the configured folder and shows its full path with the content hidden. After approval it creates the file once. Existing files, symbolic links and changed parent directories are refused. Other writes stay disabled. A lost result is never resent automatically.

:::caution
A server's tools run with whatever access the server has. A filesystem or shell server
hands the agent's programs the files and processes they cannot otherwise reach, so
connect only servers whose tools you would let the agent use on any task.
:::

## MCP servers in a run

An experiment gives its agent MCP tools through the `mcp` skill and a service that runs
the server over HTTP:

```toml
[overrides.agent.services]
mcp = ["mcp-units"]

[overrides.agent.skills]
enable = ["mcp"]
```

Programs then call:

```python
tools = mcp_tools()
mcp_call("convert", value=3, from_unit="m", to_unit="cm")
```

A server is a service like any other ([Services](/docs/configure/services/)): a manifest
of kind `mcp` names how to start it and its port, and a deploy can place it on another
computer. The `mcp-example` package contains a small server and its manifest to start
from. A stdio server can instead use the explicit host connection above; programs do not launch it themselves.

For a read-only extension, declare the exact MCP tool names you have reviewed in the
trusted service manifest's `client.read_only_tools` list. The bundled `mcp-units`
manifest declares `convert` this way. This policy applies to the server your deploy
actually runs or connects to. For example, the manifest can contain the following table.

```toml
[client]
url = "{url}/mcp"
read_only_tools = ["convert"]
```

An unannotated tool on that list can run. Every other experiment MCP tool is refused
before approval, even if it appears in `mcp_tools()`.

## Agent Skills

An Agent Skill is a folder with a `SKILL.md`, the format Claude's and OpenAI's skills
use:

```markdown
---
name: expense-report
description: Fill in the company's expense report form from receipts.
---

Open the form at https://example.com/expenses ...
```

The agent sees each skill's name and description in its prompt, and reads its
instructions and files with `read_skill(name)` when a task needs them. It needs no code.

To add one in the app, choose **Settings → Packages → Add** and give a folder, a `.zip`,
the URL of a `.zip`, or a git URL; a GitHub folder URL takes that folder only, for
example `https://github.com/anthropics/skills/tree/main/skills/pdf`. From the terminal:

```bash
harness install ./expense-report
```

A package ships Agent Skills in its `agent-skills/<name>/SKILL.md` folders
([Write a package](/docs/extend/packages/)).
