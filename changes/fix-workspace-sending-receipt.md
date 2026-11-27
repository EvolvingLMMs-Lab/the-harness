---
core: patch
workspace: patch
agent: patch
---

Fix `KeyError: 'executed'` when workspace sending-approval refuses a command, narrow `gh release*` patterns, and honor Full Access mode:

- Include `"executed": False`, `"action_id"`, and `"shield"` in `WorkspaceSession._tick()` when refusing a `[sending]` command (`packages/workspace/harness_workspace/session.py`), and use defensive `reply.get("executed", True)` in `src/harness/runtime/tick.py:834`.
- Narrow `gh release*` in `packages/workspace/spaces/workspace.toml` to mutating subcommands (`create`, `edit`, `delete`, `upload`) so read-only `gh release list` / `gh release view` are not falsely refused.
- Forward `granted: ["*"]` for owner turns running in `full` (Full Access) permission mode so commands like `gh pr create` succeed without approval refusal when Full Access is explicitly enabled.

### 中文

- 修复工作区拦截 `[sending]` 对外命令时因缺少 `"executed"` / `"shield"` 字段触发 `tick.py` `KeyError: 'executed'` 崩溃的问题。
- 将 `workspace.toml` 的 `gh release*` 规则收窄为 `create / edit / delete / upload`，不再误拦只读的 `gh release list` / `gh release view`。
- 在用户显式开启「完整权限（`full`）」模式时，自动向后台任务传递 `granted: ["*"]`，放行 `gh pr create` 等命令。
