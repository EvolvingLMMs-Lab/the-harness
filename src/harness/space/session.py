"""The session of a conversation in a space entered by its address (the core's kind `space`).

Such a space has no skills of its own: its programs act through its vocabulary
(harness.space.vocabulary), and its events reach the tree of reflexes as any space's do
(runtime/execution/session.py). Nothing ticks: an action is a verb, and its outcome is the
space's.
"""

from harness.runtime.execution.session import EpisodeCore
from harness.space.vocabulary import functions

KIND = "space"


class SpaceSession(EpisodeCore):
    """The episode core over a space, with the space's verbs as functions."""

    embodiment = KIND

    def __init__(self, options, *, environment=None):
        super().__init__({**options, "space": True}, environment=environment)
        added = functions(self.env, self.env.vocabulary())
        self.namespace.update(added)

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


def create_environment(**options):
    """The bench's worker factory (benches/space): none. A space is not a worker; it is entered
    by its address (SpaceEnvironment.connect, workspace "space")."""
    raise ValueError("a space is entered by its address (--space ADDRESS), not started as a worker")
