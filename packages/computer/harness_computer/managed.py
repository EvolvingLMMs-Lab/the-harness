"""Host-only access to one exclusive desktop or browser worker."""

from contextlib import contextmanager
from copy import deepcopy

from harness.sdk import Observation, WorkerRejected


class HostWorkspace:
    """Serialize private worker calls and validate receipts against the lease and cursor.

    Only the trusted scheduler and host lifecycle may hold this object. A kernel message
    is a proposal, and cannot be forwarded directly to any of these methods.
    """

    def __init__(self, worker, transport):
        self._worker = worker
        self._transport = transport
        self._lease = worker._lease
        self._process = worker.process
        self._run = worker.run
        self._episode = None
        self._step = None

    @contextmanager
    def lease_guard(self):
        worker = self._worker
        with worker._approval_lock:
            yield (worker._lease is self._lease and worker.process is self._process and worker.run == self._run
                   and self._run is not None and worker.status == "ready" and worker.alive())

    def retire(self):
        with self.lease_guard() as live:
            if live:
                worker = self._worker
                worker.status, worker.error = "error", "worker input delivery could not be verified"
                self._process.kill()
                self._process.wait()

    def _require_live(self, live):
        if not live:
            raise PermissionError("The host workspace lease has ended")

    def _send(self, method, arguments, *, timeout=120):
        # The caller holds the lease through validating the receipt or retiring the worker.
        try:
            return self._transport.request(method, arguments, timeout=timeout)
        except WorkerRejected:
            raise
        except Exception:
            self.retire()
            raise RuntimeError("The private worker result is unverified") from None

    def tools(self):
        with self.lease_guard() as live:
            self._require_live(live)
            return self._send("describe", {})["tools"]

    def reset(self, task, seed):
        with self.lease_guard() as live:
            self._require_live(live)
            if self._episode is not None:
                raise RuntimeError("A host workspace has only one episode")
            try:
                observation = Observation(**self._send("reset", {"task": task, "seed": seed}))
                if (not isinstance(observation.episode_id, str) or not observation.episode_id
                        or type(observation.step) is not int or observation.step != 0):
                    raise ValueError("Invalid reset cursor")
            except Exception:
                self.retire()
                raise
            self._episode, self._step = observation.episode_id, observation.step
            return observation

    def _check_episode(self, arguments):
        if self._episode is None or arguments.get("episode_id") != self._episode:
            raise PermissionError("The request is outside the host workspace episode")

    def _check_tick(self, arguments):
        self._check_episode(arguments)
        if type(arguments.get("step")) is not int or arguments["step"] != self._step:
            raise ValueError("The request is outside the host workspace cursor")

    def _receipt(self, receipt, action_id=None):
        state = receipt.get("state") if isinstance(receipt, dict) else None
        step = state.get("step") if isinstance(state, dict) else None
        if (type(step) is not int or step not in (self._step, self._step + 1)
                or type(receipt.get("executed")) is not bool
                or (receipt["executed"] and step == self._step)
                or (action_id is not None and receipt.get("action_id") != action_id)):
            raise RuntimeError("The private worker delivery receipt is invalid")
        self._step = step
        return receipt

    def _tick(self, arguments):
        self._check_tick(arguments)
        try:
            return self._receipt(self._send("call", {"name": "tick", "arguments": arguments}),
                                 arguments.get("action_id"))
        except Exception:
            self.retire()
            raise

    def call(self, name, **arguments):
        """An ordinary host call, including idle and guard ticks and workspace side operations."""
        with self.lease_guard() as live:
            self._require_live(live)
            if name == "tick":
                if "execution_id" in arguments:
                    raise ValueError("Attributed ticks must use the host approval dispatcher")
                return self._tick(arguments)
            if "episode_id" in arguments:
                self._check_episode(arguments)
            return self._send("call", {"name": name, "arguments": arguments})

    def deliver(self, action_id, execution_id, command, cameras):
        """Assign identity only to a single action admitted by the trusted tick."""
        with self.lease_guard() as live:
            self._require_live(live)
            arguments = {"episode_id": self._episode, "step": self._step, "execution_id": execution_id,
                         "action_id": action_id, "command": deepcopy(command),
                         "cameras": list(cameras) if cameras else None}
            return self._tick(arguments), arguments

    def retry_approved(self, arguments):
        """Deliver the host's claimed action once, at the current worker cursor."""
        with self.lease_guard() as live:
            self._require_live(live)
            if type(arguments["step"]) is not int or arguments["step"] != self._step:
                return None
            self._check_episode(arguments)
            receipt = self._transport.request("sensitive_approval", {"op": "retry", **arguments}, timeout=5)
            return self._receipt(receipt, arguments["action_id"]) if receipt is not None else None

    def approval_receipt(self, arguments):
        """Read a receipt without repeating an action whose delivery is uncertain."""
        with self.lease_guard() as live:
            self._require_live(live)
            self._check_episode(arguments)
            query = {name: arguments[name] for name in ("episode_id", "execution_id", "action_id", "request_id")}
            receipt = self._transport.request("sensitive_approval", {"op": "receipt", **query}, timeout=5)
            return self._receipt(receipt, arguments["action_id"]) if receipt is not None else None

    def cancel_approval(self, request_id, tick):
        with self.lease_guard() as live:
            if live:
                self._check_episode(tick)
                arguments = {"op": "cancel", "request_id": request_id, "episode_id": tick["episode_id"],
                             "execution_id": tick["execution_id"]}
                try:
                    self._transport.request("sensitive_approval", arguments, timeout=5)
                except (OSError, RuntimeError, ValueError, TypeError, KeyError):
                    pass  # The worker also expires its pending request.

    def dispatcher(self, conversation, kind):
        from .dispatch import ManagedDispatch

        return ManagedDispatch(conversation, self, kind)

    def program_command(self, options):
        """Provide the isolated proposal kernel command for this workspace."""
        from .linux_program import program_command

        return program_command(options)

    def close(self):
        """The session host owns release, after receipt handling."""
