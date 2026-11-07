---
title: "mcp"
---

MCP 服务器工具（Model Context Protocol，流式 HTTP）：在程序中列出并调用。

- **层**: base（可选：仅在配置启用时提供）
- **所需服务**: mcp
- **依赖 skill**: –
- **冲突 skill**: –
- **永不移除**: 否
- **Mixin**: `skills.mcp:McpTools`
- **清单**: `skills/mcp/skill.toml`

<a id="functions"></a>

## 函数

### `mcp_tools`

```python
def mcp_tools()
```

agent 的 MCP 服务器提供的全部工具：[{"name", "server", "description", "input_schema"}]，名称可传给 mcp_call。不响应的服务器的工具会缺失；所有服务器都不响应时，McpError 说明原因。

### `mcp_call`

```python
def mcp_call(tool, /, **arguments)
```

以关键字参数作为输入通过会话宿主调用已启用的 MCP 工具；返回结构化结果或文本。工具错误会抛出 McpError。

<a id="what-the-model-reads"></a>

## 模型读到的内容

来自 RoboDojo prompt pack（`prompts/robodojo/`），启用所有 skill 和特性（额外启用 mcp）：

```text
  mcp_tools()                          every tool: name, server, description, input_schema
  mcp_call(tool, **arguments)          call one by its name; returns its structured result,
                                       or its text
```
