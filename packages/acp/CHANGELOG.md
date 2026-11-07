# Changelog

## 0.1.1

- Editor approvals carry the original host request ID. A response to a stale sub-agent
  request cannot approve a newer request.

## 0.1.0

- First release: `harness acp` serves the agent on this computer to editors over the Agent Client Protocol (initialize, session/new, session/prompt, session/cancel). A prompt streams the agent's messages, its thoughts and a tool call for each program; what a session waits for the user's approval for is asked with session/request_permission.
