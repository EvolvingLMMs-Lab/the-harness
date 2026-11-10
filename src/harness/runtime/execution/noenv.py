"""A conversation without an environment: the model, its programs and the connected tools.

The workspace kind `none` (host/workspaces.py) takes no worker: nothing is started, there
is no screen and no project. The task run and the kernel still speak the worker protocol,
so each of them gets a NoEnvironment of its own in its process, which answers it with an
empty state and no view. The kernel's session (NoSession) is the episode core with nothing
to send: programs compute, call the connected tools (MCP) and finish.
"""

import uuid

from harness.core.contracts import Observation
from harness.runtime.execution.session import EpisodeCore

KIND = "none"


class NoEnvironment:
    """The worker protocol of nothing: one episode, an empty state, no views, no outcome to score."""

    name = KIND
    timeout = 30.0
    approval_key = None
    host_controls = frozenset()
    program_controls = frozenset()

    def __init__(self, episode_id: str | None = None):
        self.episode_id = episode_id or uuid.uuid4().hex
        self.state = {"step": 0, "ended": False}

    def tools(self) -> list:
        return []

    def reset(self, task: str, seed: int) -> Observation:
        return Observation(self.episode_id, 0, "", dict(self.state))

    def call(self, name: str, **arguments):
        if name == "profile":
            return {"kind": KIND, "name": KIND, "benchmark": KIND, "clock": "events", "control_hz": 1,
                    "steps_shown": False}
        if name == "state":
            return dict(self.state)
        if name == "observe":
            return {"state": dict(self.state), "images": {}}
        if name == "claim_outcome":
            return {"token": self.episode_id}
        if name == "outcome":
            # Nothing scores a conversation: success None, which the frontends do not show.
            return {"success": None, "reward": None, "process_score": None, "steps": 0, "closed": True}
        if name == "tick":
            return {"executed": True, "shield": {"command": arguments.get("command"), "reasons": []},
                    "state": dict(self.state)}
        raise RuntimeError(f"There is no environment in this conversation: {name} needs one")

    def close(self) -> None:
        pass


def create_environment(options=None):
    """The bench's worker factory (benches/none): what a worker of nothing would serve."""
    return NoEnvironment()


class NoSession(EpisodeCore):
    """The episode core with no environment behind it."""

    embodiment = KIND

    def __init__(self, options, *, environment=None):
        super().__init__(options, environment=environment or NoEnvironment(options.get("episode_id")))

    def _base_command(self, state):
        return None

    def _tick(self, command, cameras=None):
        receipt = self.env.call("tick", command=command)
        self.state = receipt["state"]
        return receipt

    def _reactive_view(self, state, tick):
        return dict(state)

    def _outside(self, region, state):
        return False
