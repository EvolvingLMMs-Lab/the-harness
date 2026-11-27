"""Use only the public task API; no TaskRun or host implementation internals."""
from urllib.parse import quote
from harness.sdk import Host
from harness.sdk import RemoteConversation


class Refused(ValueError):
    """A task the safety layer refused before it started (the outcome "refused")."""


class Tasks:
    def __init__(self, host=None, *, model=None, effort=None, workspace="auto", folder=None, approval=None, on_event=None,
                 identity=None, runtime=None):
        self._host = host
        self.identity = identity
        self.extra = dict(runtime or {})
        # guard() -> why a task may not start (the safety layer), or None.
        self.guard = None
        self.model, self.effort, self.workspace, self.folder = model, effort, workspace, folder
        self.approval, self.on_event = approval, on_event

    @property
    def host(self):
        if self._host is None:
            self._host = Host.connect()
        return self._host

    def submit(self, goal, *, library=None, granted=None):
        why = self.guard() if self.guard is not None else None
        if why:
            raise Refused(why)
        runtime = {**self.extra, **self.runtime(), **({"granted": list(granted)} if granted else {})}
        return self.host.task(goal, self.workspace, folder=self.folder, model_entry=self.model,
                              reasoning_effort=self.effort, library=library,
                              runtime=runtime or None).run

    def runtime(self) -> dict:
        """What a task submitted for the identity carries: whose it is, and the spending account
        its model calls are charged to (checked before each one)."""
        if self.identity is None:
            return {}
        return {"identity": self.identity.id, "account": str(self.identity.account().directory)}

    def resume(self, run, text):
        RemoteConversation(self.host.url, self.host.token, run).send_message(text)

    def cancel(self, run):
        RemoteConversation(self.host.url, self.host.token, run).close()

    def status(self, run):
        task = RemoteConversation(self.host.url, self.host.token, run)
        task.describe()
        return task.status

    def observe(self, run, after=-1):
        task = RemoteConversation(self.host.url, self.host.token, run)
        answer, over = "", False
        for row in task.records(after=after):
            after = row["seq"]
            if self.on_event:
                self.on_event(row)
            if row["event"] in ("finish", "agent_message"):
                answer = row.get("text", "")
            if row["event"] == "turn_result" and not over:
                # Its turn is over (an answer, a limit, an error): the task ends here, as
                # harness run "task" ends; its session can be continued by its id.
                over = True
                task.close()
            if row["event"] == "state":
                status = row.get("status")
                if status == "WAITING_FOR_CONFIRMATION":
                    request = row.get("request") or {}
                    if self.approval is None:
                        return {"run": run, "after": after, "status": "waiting_approval", "request": request}
                    accepted, reason = self.approval(request)
                    task.confirm(accepted, reason, request_id=request.get("id"))
        meta = self.host.get("/api/meta?run=" + quote(run))
        return {"run": run, "after": after, "status": "ended", "answer": answer,
                "summary": meta.get("summary"), "evidence": "/api/events?run=" + quote(run)}
