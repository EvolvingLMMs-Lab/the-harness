"""A conversation run elsewhere, driven from here (after OpenHands' RemoteConversation).

RemoteConversation talks to the session host (host/http.py) with the calls of a
local TaskRun (runtime/task/run.py): send_message, pause, resume, confirm,
close, and the trace records as they are written. So a script or a terminal on a
laptop drives an episode that runs where the worker and the models are, over an ssh
tunnel to the server's port. It is also how every frontend drives a session of the
session host (host/): `run` is then the session's id, or "<session>/<agent>".
"""

import json
from urllib.error import HTTPError
from urllib.parse import quote

from ..core.http import open_url, post_json, read_sse
from ..settings import ChoiceRequired


class RemoteError(RuntimeError):
    """The server refused a request; the message is its reason."""


class RemoteConversation:
    """The conversation `run` on the GUI server at `url` (http://host:port), with the
    session key `token`. `status` is the last status its records reported."""

    def __init__(self, url: str, token: str, run: str, timeout: float = 60.0, session: str | None = None):
        self.url = url.rstrip("/")
        self.token = token
        self.run = run
        self.timeout = timeout
        self.status = None
        self.agent = None
        # The session the conversation is an agent of (when the server said).
        self.session = session

    @classmethod
    def start(cls, url: str, token: str, **request) -> "RemoteConversation":
        """Start a conversation on the server: experiment, task, seed, model, endpoint,
        instruction, confirmation, sets (host/http.py start_conversation)."""
        answer = _call(url.rstrip("/"), token, "/api/conversations", request, timeout=600)
        return cls(url, token, answer["run"], session=answer.get("session"))

    def describe(self) -> dict:
        """The session this conversation belongs to, as the server lists it (its status,
        what it waits for, its agents); refreshes `status`."""
        row = _get(self.url, self.token, f"/api/sessions/show?id={quote(self.run)}&lines=0", self.timeout)
        selected = row.get("selected_agent")
        if selected is None:  # Hosts from before the session details named the selected agent.
            selected = next((item["id"] for item in row["agents"] if item["run"] == self.run),
                            self.run.partition("/")[2] or "main")
        self.agent = next((item for item in row["agents"] if item["id"] == selected), None)
        self.session = row["id"]
        if self.agent is not None:
            self.status = self.agent["status"]
        return row

    def memory(self) -> list[dict]:
        """What it remembers: this run's entries (what it saw and where) and its library's,
        in one format (runtime/task/context.py rows), as every frontend shows them."""
        return _get(self.url, self.token, f"/api/library?run={quote(self.run)}", self.timeout)["entries"]

    def _post(self, route: str, **body):
        return _call(self.url, self.token, f"/api/conversations/{route}", {"run": self.run, **body}, self.timeout)

    def send_message(self, text: str, files=()) -> None:
        """A message from the user, for the model's next call; `files`: paths it attaches."""
        self._post("message", text=text, **({"files": [str(path) for path in files]} if files else {}))

    def steer(self, text: str, files=()) -> None:
        """Redirect an active turn of an external session that supports steering."""
        self._post("steer", text=text, files=[str(path) for path in files])

    def cancel(self) -> None:
        """Cancel an external session's current turn."""
        self._post("cancel")

    def set_config(self, identifier: str, value) -> dict:
        """Select an advertised session configuration value."""
        return self._post("config", id=identifier, value=value)

    def answer(self, request_id: str, content: dict | None) -> None:
        """Answer the current external form, or decline it with None."""
        self._post("answer", request_id=request_id, content=content)

    def diff(self) -> dict:
        """Review the working changes in a Git-backed external session."""
        return self._post("diff")

    def merge(self) -> dict:
        """Fast-forward the original branch to a closed session's committed work."""
        return self._post("merge")

    def discard(self) -> dict:
        """Remove a closed session's managed worktree."""
        return self._post("discard")

    def terminal_input(self, text: str) -> None:
        """Send terminal input to a session started with an interactive PTY."""
        self._post("terminal", text=text)

    def handoff(self, agent: str, context: str, *, folder=None, isolation=None):
        """Start another agent with the context chosen by the user."""
        answer = self._post("handoff", agent=agent, context=context, folder=str(folder) if folder else None,
                            isolation=isolation)
        return RemoteConversation(self.url, self.token, answer["run"], self.timeout)

    def enable_agents(self) -> None:
        """Switch sub-agents on for this conversation (off unless session.agents is on): their
        calls load before its next program."""
        self._post("agents")

    def pause(self) -> None:
        """Pause at the next execution step."""
        self._post("pause")

    def resume(self) -> None:
        """Go on after a pause."""
        self._post("resume")

    def confirm(self, accept: bool, reason: str = "", remember: str | None = None,
                *, request_id: str | None = None) -> None:
        """Approve or reject the program waiting for confirmation, or the step waiting for
        physical input (remember: once, app, session, always)."""
        self._post("confirm", accept=bool(accept), reason=reason, **({"remember": remember} if remember else {}),
                   **({"request_id": request_id} if request_id else {}))

    def set_model(self, model: str | None = None, reasoning_effort: str | None = None) -> dict:
        """Another main model (an id of its provider) or reasoning effort from its next call on."""
        answer = self._post("model", **({"model": model} if model else {}),
                            **({"reasoning_effort": reasoning_effort} if reasoning_effort is not None else {}))
        return {"model": answer.get("model"), "reasoning_effort": answer.get("reasoning_effort")}

    def close(self) -> None:
        """End the episode."""
        self._post("close")

    def records(self, after: int = -1, stop=None):
        """The trace records after seq `after`, then each new one as it is written, until
        the episode's last record (a generator; a dropped connection is resumed). With
        `stop` (a threading.Event), it ends once the event is set, within the server's
        keep-alive interval."""
        while True:
            if stop is not None and stop.is_set():
                return
            ended = False
            try:
                with open_url(f"{self.url}/api/stream?run={quote(self.run)}", timeout=self.timeout,
                              headers={"X-Session-API-Key": self.token, "Last-Event-ID": str(after)}) as response:
                    for event, data in read_sse(response):
                        if stop is not None and stop.is_set():
                            return
                        if event == "end":
                            ended = True
                            break
                        if event == "record":
                            record = json.loads(data)
                            after = record["seq"]
                            if record["event"] == "state":
                                self.status = record["status"]
                            yield record
            except HTTPError as error:
                raise RemoteError(_reason(error)) from None
            except (TimeoutError, OSError):
                continue
            if ended:
                return


def _reason(error: HTTPError) -> str:
    try:
        return json.loads(error.read()).get("error") or str(error)
    except ValueError:
        return str(error)


def _get(url: str, token: str, path: str, timeout: float) -> dict:
    return json.loads(_fetch(url, token, path, timeout))


def _fetch(url: str, token: str, path: str, timeout: float) -> bytes:
    try:
        with open_url(url + path, headers={"X-Session-API-Key": token}, timeout=timeout) as response:
            return response.read()
    except HTTPError as error:
        raise RemoteError(_reason(error)) from None


def _call(url: str, token: str, path: str, body: dict, timeout: float) -> dict:
    try:
        return post_json(url + path, body, {"X-Session-API-Key": token}, timeout)
    except HTTPError as error:
        try:
            payload = json.loads(error.read())
        except ValueError:
            payload = {}
        finally:
            error.close()
        if error.code == 409 and isinstance(payload.get("choice_required"), dict):
            raise ChoiceRequired(payload["choice_required"]) from None
        raise RemoteError(payload.get("error") or str(error)) from None
