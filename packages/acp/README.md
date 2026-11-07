# acp

The acp package makes The Harness an agent of the [Agent Client Protocol](https://agentclientprotocol.com) (ACP), so an editor such as Zed drives the agent on this computer from its agent panel. `harness acp` speaks ACP on stdin and stdout; the editor starts it and talks to it.

## Install

```bash
harness install acp
```

## Use with Zed

Add the agent to Zed's `settings.json`:

```json
{
  "agent_servers": {
    "The Harness": {
      "command": "harness",
      "args": ["acp"]
    }
  }
}
```

Then open a new thread with The Harness in the agent panel. Any other ACP client (JetBrains IDEs, Neovim with CodeCompanion, Emacs with agent-shell) starts the same command: `harness acp`.

## What it does

- Each thread is one conversation of the app's agent in your session host (started when it does not run): the first message starts it, later messages go to it. It is a session like any other, so `harness sessions` and the app list it too.
- While the agent works, the editor shows what it says, its thoughts, and a tool call for each program it runs with the program's result.
- When the agent waits for your approval (a program under ask-before-acting, or a step that uses your real mouse and keyboard under the physical-input policy), the editor asks you: Allow once or Reject. Nothing is approved without your answer.
- Stopping the thread in the editor closes the conversation.

`harness acp --workspace NAME` picks where tasks run, as `harness run --workspace` does (default `auto`). Logs go to stderr.

## Protocol

ACP version 1: `initialize`, `session/new`, `session/prompt` (text and resource links), `session/cancel`; the agent sends `session/update` (`agent_message_chunk`, `agent_thought_chunk`, `tool_call`, `tool_call_update`) and `session/request_permission`. A prompt ends with `end_turn` when the agent has answered, `cancelled` after a cancel and `refusal` when the conversation ends in an error. Loading earlier sessions, images, audio and the client's MCP servers are not supported.
