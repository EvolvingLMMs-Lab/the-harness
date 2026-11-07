# The Harness for Claude Code

A Claude Code plugin that lets Claude Code use The Harness: an agent that sees a screen
and acts on this computer's desktop and applications, in a browser, or in a game.

It bundles:

- the MCP server `harness` (`harness mcp`): run tasks, start, steer and stop sessions,
  observe a session's screen, read its timeline, list and install packages, and list the
  library;
- two skills: `act-with-the-harness` and `follow-harness-sessions`;
- two commands: `/harness <task>` and `/harness-sessions [session]`.

## Install

1. Install The Harness and its MCP server package, and set up a model once:

   ```bash
   pip install the-harness
   harness install mcp-server
   harness
   ```

2. In Claude Code, add this repository as a plugin marketplace and install the plugin:

   ```text
   /plugin marketplace add EvolvingLMMs-Lab/the-harness
   /plugin install the-harness@the-harness
   ```

Without the plugin, the MCP server alone is `claude mcp add harness -- harness mcp`.
Approvals (the user's real mouse and keyboard, or "ask before acting") are given in The
Harness's own app or terminal, never by Claude Code.
