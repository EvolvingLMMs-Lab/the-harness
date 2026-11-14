"""JSON/HTTP transport to a worker in a separate Python environment.

This is the framework's protocol, not a benchmark's own.
An integration must implement Environment on the worker side.
"""

import os
from urllib.error import HTTPError
from urllib.parse import urlparse

from harness.runtime.safety.approval import WORKER_APPROVAL_HEADER, worker_approval_proof
from .contracts import Action, Observation, Transition
from .http import post_json


class RemoteEnvironment:
    """A worker reached over HTTP (POST /rpc), with the bearer token from
    $HARNESS_WORKER_TOKEN when it is set. A worker error is raised as a RuntimeError, and
    no request is retried: a motion that timed out may have executed."""

    name = "remote"

    def __init__(self, endpoint: str, timeout: float = 120.0, *, approval_key=None, host_controls=(), relay=None):
        url = urlparse(endpoint)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("Worker endpoint must be an HTTP(S) URL without embedded credentials")
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.token = os.environ.get("HARNESS_WORKER_TOKEN")
        self.approval_key = approval_key
        self.host_controls = frozenset(host_controls)
        self.program_controls = frozenset()
        self.relay = relay

    def _call(self, method: str, **arguments):
        if method == "call" and arguments["name"] in self.host_controls and self.approval_key is None:
            if self.relay is None:
                raise RuntimeError("Worker control requires a host connection")
            return self.relay(arguments, self.timeout)
        return self._request(method, arguments, approval_key=self.approval_key)

    def _request(self, method, arguments, *, approval_key=None):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        request = {"method": method, "arguments": arguments}
        if approval_key:
            headers[WORKER_APPROVAL_HEADER] = worker_approval_proof(approval_key, request)
        # Deliberately no automatic retry: a timed-out motion may have executed.
        try:
            result = post_json(self.endpoint + "/rpc", request, headers, self.timeout)
        except HTTPError as error:
            with error:
                detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Worker HTTP {error.code}: {detail}") from error
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]

    def tools(self) -> list[dict]:
        """The worker's tool schemas. Checks its protocol version and takes its name; it
        also serves as the check that a worker answers."""
        description = self._call("describe")
        if description["protocol_version"] != 1:
            raise ValueError("Unsupported worker protocol version")
        if self.approval_key:
            if not (description.get("authenticated_controls") or description.get("managed_approval")) or not description.get("managed_control_calls"):
                raise RuntimeError("Worker did not enable authenticated controls")
            self.host_controls = frozenset([*description["managed_control_calls"], "sensitive_approval"])
            self.program_controls = frozenset(description.get("program_control_calls", ())) & self.host_controls
        self.name = description["name"]
        return description["tools"]

    def reset(self, task: str, seed: int) -> Observation:
        """Start an episode of `task` with `seed` and return its first observation."""
        return Observation(**self._call("reset", task=task, seed=seed))

    def execute(self, action: Action, episode_id: str, step: int) -> Transition:
        """Execute `action` on the observation (`episode_id`, `step`); the worker rejects a
        stale pair. Returns the transition to the next observation."""
        return Transition.from_dict(self._call(
            "execute", action=action.to_dict(), episode_id=episode_id, step=step,
        ))

    def call(self, name: str, /, **arguments):
        """Invoke an environment-specific worker method. The method's name is positional, so
        that a method may have an argument called `name` of its own."""
        return self._call("call", name=name, arguments=arguments)

    def managed_call(self, name, /, *, approval_key, **arguments):
        """Send one worker control call with the trusted host's proof."""
        return self._request("call", {"name": name, "arguments": arguments}, approval_key=approval_key)

    def sensitive_approval(self, op, *, approval_key, **arguments):
        """Host only: inspect a worker request, retry after assent, or cancel the request.

        The host supplies its key directly. The proof authenticates the request without putting the key in
        the RPC body, and the generated program never needs a copy of the key or proof.
        """
        return self._request("sensitive_approval", {"op": op, **arguments}, approval_key=approval_key)

    def close(self) -> None:
        """Nothing: the worker belongs to the process that launched it."""
        # Worker lifecycle is explicitly owned by its launching process.
        pass
