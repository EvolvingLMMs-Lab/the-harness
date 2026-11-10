# Changelog

## 0.2.1

- The package summary and the help of `harness mcp` say who it is for: apps, editors and agents that are MCP clients.

## 0.2.0

- `run_task` and `start_session` accept an explicit project folder and task budget. Workspace names come from installed providers, without a product allowlist or automatic installation. Requires Harness 0.78 or later.

## Unreleased (S7)

- A session that waits for approval says the user approves it in the app or with /approve in the terminal chat (`harness sessions` is gone).

## 0.1.0

- First release: `harness mcp`, The Harness as an MCP server on stdio or streamable HTTP
  (127.0.0.1), with the tools run_task, list_sessions, start_session, send_message,
  stop_session, get_session, observe_screen, read_events, list_packages, install_package
  and list_library. A session that waits for the user's approval is reported, never
  approved: the user approves it in a harness frontend.
