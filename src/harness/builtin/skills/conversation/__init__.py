"""What every program of a conversation without an environment has: finish(), the (empty)
state and show(). There is nothing to act on; the connected tools are the mcp skill's."""

from harness.runtime.events import ProgramFinished


class Conversation:
    def finish(self, summary=""):
        """End the task now with `summary` as the answer."""
        raise ProgramFinished(summary)

    def _wrap_up(self):
        return []

    __wrap_up__ = _wrap_up

    def get_state(self):
        """The state: there is no environment, so only the step count."""
        return dict(self.state)

    def get_observation(self):
        """Nothing to see: {"state", "images": {}}."""
        return {"state": dict(self.state), "images": {}}
