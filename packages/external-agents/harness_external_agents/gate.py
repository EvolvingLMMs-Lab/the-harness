"""Claude Code's PreToolUse hook (agents.py): asks the sub-agent that runs Claude Code whether
one tool call may go on and prints Claude Code's decision.

Claude Code runs it before every tool call with the call on stdin ({tool_name, tool_input,
...}); the sub-agent's endpoint is in the environment Claude Code inherited
(HARNESS_GATE_URL, HARNESS_GATE_TOKEN). Anything that goes wrong refuses the call.
Standard library only.
"""

import json
import os
import sys
import urllib.request


def main() -> None:
    try:
        call = json.load(sys.stdin)
        request = urllib.request.Request(
            os.environ["HARNESS_GATE_URL"], method="POST",
            data=json.dumps({"tool_name": call.get("tool_name"), "tool_input": call.get("tool_input"), "cwd": call.get("cwd")}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['HARNESS_GATE_TOKEN']}"})
        # Straight to localhost: never through a proxy of the environment.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request) as response:
            verdict = json.load(response)
    except Exception as error:
        verdict = {"allow": False, "reason": f"the harness's gate could not be asked ({error}): refused"}
    if verdict.get("allow") is not True:
        print(str(verdict.get("reason") or "The harness refused this tool call"), file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "allow",
        "permissionDecisionReason": str(verdict.get("reason") or "")}}))


if __name__ == "__main__":
    main()
