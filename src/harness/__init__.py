"""The Harness: a coding agent as a generalist robot policy. No simulator imports here."""

# The one version: the core's. A lock records it with the versions of the packages that
# ran and the hash of the whole lock (the agent's identity, config/agent.py).
__version__ = "0.85.1"

# A checkout's packages import beside the harness (paths.py).
from . import paths as _paths  # noqa: E402,F401
