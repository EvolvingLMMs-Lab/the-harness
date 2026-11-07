"""The Harness as an MCP server: `harness mcp` gives Claude Code, Codex, Cursor and other
MCP clients tools that run tasks in the user's session host and follow them (server.py)."""

from .server import McpServer, TOOLS, http_server, serve_stdio

__all__ = ["McpServer", "TOOLS", "http_server", "serve_stdio"]
