"""The Harness in spaces: the Agent Space Protocol on the core's side.

Every environment the runtime acts in is a space (state, laws, participants), entered through
the protocol: `environment.SpaceEnvironment` is the runtime's environment as a participant;
`translate` serves any worker as a space, unchanged, beside it. Outcomes are typed
(agent_space.End, agent_space.Reason): done, refused, failed, cancelled or unknown, one for
every action, and an action ID sent again does not act again.
"""

from agent_space import End, Outcome, Reason, ReasonCode

PROTOCOL_VERSION = 0

__all__ = ["End", "Outcome", "PROTOCOL_VERSION", "Reason", "ReasonCode"]
