# mcp-example

The `mcp-example` package is an example of a package that adds an MCP server as a connector: a small unit-conversion server whose one tool the agent's programs can call.

## Install

```bash
harness install mcp-example
```

It needs nothing outside Python.

## Use

The package adds the service `mcp-units`, an MCP server over streamable HTTP. Start it, then give an agent the server and the `mcp` skill:

```bash
harness up mcp-units
```

```toml
[services]
mcp = ["mcp-units"]

[skills]
enable = ["mcp"]
```

A program then lists and calls its tools:

```python
print(mcp_tools())
mcp_call("convert", value=3, from_unit="in", to_unit="cm")    # 7.62
```

In the app, add the running server under **Settings → Connectors → Your own server** with its URL, `http://localhost:8860/mcp`; **Tools** lists what it offers.

## What it provides

- **Service `mcp-units`**: an MCP server with one tool, `convert(value, from_unit, to_unit)`, between units of length (m, cm, mm, in), mass (kg, g, lb) and angle (rad, deg).
- **Skill `mcp`**: `mcp_tools()` lists every tool of the agent's MCP servers; `mcp_call(tool, **arguments)` calls one.

## Make your own

Copy the package and replace the server. Any MCP server with the streamable HTTP transport is added the same way: a service manifest of kind `mcp` with its command (or the URL of a server that already runs) and a `client` URL. A server that only speaks stdio runs behind an HTTP bridge as a service. See [Services](https://harness.lmms-lab.com/docs/configure/services/) and [Packages](https://harness.lmms-lab.com/docs/configure/packages/).

## Limits and known issues

An MCP server runs outside the programs' sandbox: whatever its tools reach, programs reach through `mcp_call`. Give an agent only servers whose tools are safe for any program to call.
