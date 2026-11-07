"""MCP tools configured and called by the conversation host."""

import uuid

from harness.core import spans
from harness.runtime.execution import control
from harness.sdk import McpError


class McpTools:
    def _mcp_request(self, method, **detail):
        from harness.runtime.reactive.rules import _restricted

        if getattr(_restricted, "active", False) or not spans.connected():
            raise McpError("An MCP call requires a running host program")
        identifier = uuid.uuid4().hex
        spans.note("mcp_request", id=identifier, method=method, **detail)
        answer = control.wait_answer(identifier, stop=control.message_arrived)
        if answer is None:
            raise control.stopped("mcp")
        if "error" in answer:
            raise McpError(answer["error"])
        return answer["value"]

    def mcp_tools(self):
        """List the host's enabled MCP tools and their input schemas."""
        return self._mcp_request("list")

    def mcp_call(self, tool, /, **arguments):
        """Call an enabled MCP tool through the conversation host."""
        return self._mcp_request("call", tool=tool, arguments=arguments)
