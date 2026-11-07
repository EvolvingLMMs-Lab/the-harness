"""Project skills on shared execution, event and interruption semantics."""
from harness.sdk import EpisodeCore, ProgramFinished


class ProcessReceipt:
    def __init__(self, session, receipt):
        self.session, self.receipt = session, receipt
        self.identifier = receipt["result"]["process_id"]

    def ready(self):
        self.receipt["result"] = self.session.env.call(
            "process", episode_id=self.session.episode_id, process_id=self.identifier)
        if self.receipt["result"]["ready"]:
            if reference := self.receipt["result"].get("evidence"):
                self.receipt["evidence"] = reference
            return True
        return False

    def finish(self, episode, step):
        if episode != self.session.episode_id:
            raise RuntimeError("process receipt belongs to another episode")
        self.receipt["state"] = dict(self.session.state)
        return self.receipt

    def cancel(self, reason):
        self.session.env.call("cancel", episode_id=self.session.episode_id,
                              process_id=self.identifier, reason=reason)


class WorkspaceSession(EpisodeCore):
    embodiment = "workspace"

    def _tick(self, command, cameras=None, action_id=None):
        receipt = self.env.call("tick", episode_id=self.episode_id, step=self.state["step"],
                                command=command, action_id=action_id)
        self.state = receipt["state"]
        return receipt

    def _dispatch_action(self, action_id, command, cameras=None):
        receipt = self._tick(command, action_id=action_id)
        if command["type"] == "run" and receipt["result"].get("status") == "running":
            return ProcessReceipt(self, receipt)
        return receipt

    def _base_command(self, state):
        return None

    def _reactive_view(self, state, tick):
        return dict(state)

    def _sample(self, state):
        return {"step": state["step"]}

    def _outside(self, region, state):
        return False

    def close(self):
        try:
            super().close()
        finally:
            if "release" not in self.env.host_controls:
                self.env.call("release", episode_id=self.episode_id)


class WorkspaceSkills:
    def _operation(self, command):
        trace = self._execute(command["type"], command,
                              lambda state, step: command if step == 0 else None,
                              max_seconds=command.get("timeout", self.default_max_seconds),
                              region=None, until=None)
        return trace.result

    def read_file(self, path, offset=0, limit=12000):
        """Read a UTF-8 window with next_offset, total bytes and whole-file sha256."""
        return self._operation(dict(type="read", path=path, offset=offset, limit=limit))

    def write_file(self, path, text, expected=None):
        """Replace a UTF-8 file atomically, requiring its last-read hash (None creates)."""
        return self._operation(dict(type="write", path=path, text=text, expected=expected))

    def run_command(self, command, cwd=".", timeout=120, env=None):
        """Run argv or shell text in the target. Nonzero exit is data. Fresh cwd/env.

        This execution owns the process; interruption cancels it. Read complete output
        using read_output(process_id). Project interpreters belong to the target.
        """
        return self._operation(dict(type="run", command=command, cwd=cwd, timeout=timeout, env=env))

    def start_process(self, command, cwd=".", timeout=120, env=None):
        """Start an explicit task-owned service. Survives this program, not task release."""
        return self._operation(dict(type="start", command=command, cwd=cwd, timeout=timeout, env=env))

    def process_status(self, process_id):
        return self._operation(dict(type="status", process_id=process_id))

    def read_output(self, process_id, offset=0, limit=12000):
        return self._operation(dict(type="output", process_id=process_id, offset=offset, limit=limit))

    def cancel_process(self, process_id):
        """Request stop and report what the worker actually confirmed."""
        return self._operation(dict(type="cancel", process_id=process_id))

    def get_state(self):
        self._observe()
        return dict(self.state)

    def get_observation(self):
        return {"state": self.get_state(), "images": {}}

    def finish(self, summary=""):
        raise ProgramFinished(summary)

    def _wrap_up(self):
        return []

    __wrap_up__ = _wrap_up
