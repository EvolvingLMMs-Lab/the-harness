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
        from harness.runtime.execution.entries import current_entry, Cancelled
        owner = current_entry()
        def cancelled():
            return owner is not None and any(entry._cancel.is_set() for entry in owner.lineage())
        identifier = uuid.uuid4().hex
        answer = None
        with control._answered:
            control._mcp_calls.add(identifier)
        try:
            spans.note("mcp_request", id=identifier, method=method,
                       entry=owner.id if owner is not None else None, **detail)
            answer = control.wait_answer(identifier, stop=lambda: cancelled() or
                                         (owner is None and control.message_arrived()))
        finally:
            with control._answered:
                control._mcp_calls.discard(identifier)
                control._answers.pop(identifier, None)
            if answer is None:
                spans.note("mcp_cancel", id=identifier)
        if cancelled():
            raise Cancelled(f"entry {owner.id} was cancelled")
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
        result = self._mcp_request("call", tool=tool, arguments=arguments)
        for item in result.get("content", []):
            if item.get("type") == "image" and item.get("data") and item.get("mimeType"):
                self._attachments.append({"caption": f"MCP {tool}",
                    "image_url": f"data:{item['mimeType']};base64,{item['data']}"})
        return result
