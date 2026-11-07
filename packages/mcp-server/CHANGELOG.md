# Changelog

## Unreleased (S7)

- A session that waits for approval says the user approves it in the app or with /approve in the terminal chat (`harness sessions` is gone).

## 0.1.0

- First release: `harness mcp`, The Harness as an MCP server on stdio or streamable HTTP
  (127.0.0.1), with the tools run_task, list_sessions, start_session, send_message,
  stop_session, get_session, observe_screen, read_events, list_packages, install_package
  and list_library. A session that waits for the user's approval is reported, never
  approved: the user approves it in a harness frontend.
