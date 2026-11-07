"""Explicit cloud coding sessions. Each provider exposes only its public operations."""

from base64 import b64encode
import json
import os
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from harness.sdk import Credentials, data

from .session import Session


def part(value):
    return quote(str(value), safe="")


def blocks(content):
    if isinstance(content, str):
        return content
    return "\n".join(str(item.get("text") or "") for item in content or [] if isinstance(item, dict)
                     and item.get("type") in ("text", "output_text", "input_text"))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class Provider:
    controls = {}
    prefix = ""
    stream_suffix = None

    def __init__(self, settings):
        self.settings = settings
        name = settings.get("credential") or self.credential
        secret = Credentials(data()).secret(name) or os.environ.get(name)
        if not secret:
            raise ValueError(f"the {name} credential is required")
        self.headers = {"Authorization": "Bearer " + secret}
        self.configure_headers(secret)
        self.opener = build_opener(NoRedirect())
        self.identifier = None

    def configure_headers(self, secret):
        pass

    def need(self, name):
        value = self.settings.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"set {name} in the cloud adapter configuration")
        return value

    def call(self, path, payload=None, *, method=None, headers=None):
        body = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
        given = {"Accept": "application/json", **self.headers, **(headers or {})}
        if body is not None:
            given["Content-Type"] = "application/json"
        request = Request(self.origin + path, data=body, headers=given, method=method)
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise RuntimeError("cloud response exceeded the 8 MiB limit")
                return json.loads(raw) if raw else {}
        except HTTPError as error:
            raise RuntimeError(f"cloud provider returned HTTP {error.code}") from None
        except (URLError, TimeoutError):
            raise RuntimeError("cloud connection failed; the provider may already have received the request") from None

    def path(self, identifier=None):
        return self.prefix + "/" + part(identifier or self.identifier)

    def create(self, text):
        raise NotImplementedError

    def detail(self):
        return self.call(self.path())

    def stream_path(self):
        return self.path() + self.stream_suffix if self.stream_suffix else None

    def stream(self, path, cursor, stop):
        headers = {**self.headers, "Accept": "text/event-stream",
                   **({"Last-Event-ID": cursor} if cursor and isinstance(self, Cursor) else {})}
        request = Request(self.origin + path, headers=headers)
        with self.opener.open(request, timeout=10) as response:
            fields, size = {}, 0
            while not stop.is_set() and (line := response.readline(1024 * 1024 + 1)):
                size += len(line)
                if size > 1024 * 1024:
                    raise ValueError("cloud stream frame exceeded 1 MiB")
                if not line.strip():
                    if fields.get("data"):
                        value = json.loads(fields["data"])
                        if isinstance(value, dict):
                            yield fields.get("id"), fields.get("event"), value
                    fields, size = {}, 0
                else:
                    key, _, value = line.decode("utf-8", "replace").rstrip("\r\n").partition(":")
                    if key in ("data", "event", "id"):
                        fields[key] = (fields[key] + "\n" if key == "data" and key in fields else "") + value.lstrip(" ")

    def list(self, cursor=None):
        response = self.call(self.prefix + ("?" + urlencode({"after": cursor}) if cursor else ""))
        return response.get("data", []), response.get("next_cursor")

    def snapshot(self):
        detail = self.detail()
        return self.status(detail.get("status")), [], self.artifacts(detail), []

    def artifacts(self, detail):
        return [{"url": detail["url"]}] if isinstance(detail.get("url"), str) else []

    @staticmethod
    def status(value):
        state = str(value or "").lower()
        if state in ("failed", "error", "session_failed"):
            return "ERROR"
        if state in ("completed", "finished", "stopped", "cancelled", "canceled", "terminated", "archived"):
            return "FINISHED"
        if state in ("idle", "blocked", "waiting_for_user", "waiting_for_user_input"):
            return "IDLE"
        return "RUNNING"


class EventProvider(Provider):
    controls = {"send": True, "steer": True, "cancel_turn": True}
    stream_suffix = "/events/stream"

    def list(self, cursor=None):
        response = self.call(self.prefix + ("?" + urlencode({self.page_parameter: cursor}) if cursor else ""))
        return response.get("data", []), (response.get("next_page") or response.get("last_id")
                                          if response.get("has_more") else None)

    def send_event(self, event):
        return self.call(self.path() + "/events", {"events": [event]})

    @staticmethod
    def message(text):
        return {"type": "user.message", "content": [{"type": "text", "text": text}]}

    def send(self, text, steer=False):
        return self.send_event(self.message(text))

    def cancel(self):
        return self.send_event({"type": "user.interrupt"})

    def answer(self, identifier, accepted):
        return self.send_event({"type": "user.tool_confirmation", "tool_use_id": identifier,
                                "result": "allow" if accepted else "deny"})

    def snapshot(self):
        detail = self.detail()
        # Backfill is authoritative. Use event IDs to deduplicate when polling overlaps.
        response = self.call(self.path() + "/events")
        events = response.get("data", [])
        messages, approvals = [], []
        for event in events:
            identifier = event.get("id")
            if not identifier:
                continue
            kind = event.get("type")
            if kind == "agent.message" and (text := blocks(event.get("content"))):
                messages.append((identifier, text))
            if kind in ("agent.tool_use", "agent.mcp_tool_use") and event.get("requires_confirmation") is True:
                approvals.append((identifier, str(event.get("name") or "tool"), event.get("input") or {}))
            if kind == "user.tool_confirmation":
                approvals = [item for item in approvals if item[0] != event.get("tool_use_id")]
        state = self.status(detail.get("status"))
        return state, messages, self.artifacts(detail), approvals if state == "IDLE" else []


class Claude(EventProvider):
    origin, prefix, credential = "https://api.anthropic.com", "/v1/sessions", "ANTHROPIC_API_KEY"
    page_parameter = "after_id"

    def configure_headers(self, secret):
        self.headers = {"x-api-key": secret, "anthropic-version": "2023-06-01",
                        "anthropic-beta": "managed-agents-2026-04-01"}

    def create(self, text):
        response = self.call(self.prefix, {"agent": self.need("agent_id"),
                                          "environment_id": self.need("environment_id"),
                                          "initial_events": [self.message(text)]})
        return response["id"]


class Qoder(EventProvider):
    origin, prefix, credential = "https://api.qoder.com", "/api/v1/cloud/sessions", "QODER_ACCESS_TOKEN"
    page_parameter = "page"

    def create(self, text):
        response = self.call(self.prefix, {"agent": self.need("agent_id"), "environment_id": self.need("environment_id")})
        return response["id"]

    def started(self, text):
        self.send(text)


class OpenAI(Provider):
    origin, prefix, credential = "https://api.openai.com", "/v1/agents/sessions", "OPENAI_API_KEY"
    controls = {"send": True, "steer": True, "cancel_turn": True}
    stream_suffix = "/events?stream=true"

    def configure_headers(self, secret):
        self.headers["OpenAI-Beta"] = "agents=v1"
        self.items_after = None

    def create(self, text):
        environment = self.settings.get("environment")
        if not isinstance(environment, dict) or environment.get("type") not in ("none", "openai_hosted"):
            raise ValueError("configure an OpenAI-hosted environment or explicitly select type none")
        response = self.call(self.prefix, {"agent": {"model": self.need("model")}, "environment": environment,
                                          "input": text})
        return response["id"]

    def send(self, text, steer=False):
        from uuid import uuid4

        self.call(self.path() + "/events", {"events": [{"type": "agent.session.input.message",
                  "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}]}]},
                  headers={"Idempotency-Key": str(uuid4())})

    def cancel(self):
        self.call(self.path() + "/events", {"events": [{"type": "agent.session.input.cancel"}]})

    def snapshot(self):
        detail = self.detail()
        query = {"order": "asc", "limit": 100}
        if self.items_after:
            query["after"] = self.items_after
        rows = self.call(self.path() + "/items?" + urlencode(query)).get("data", [])
        if rows and rows[-1].get("id"):
            self.items_after = rows[-1]["id"]
        messages = [(item["id"], text) for item in rows if item.get("id") and item.get("role") == "assistant"
                    and (text := blocks(item.get("content")))]
        return self.status(detail.get("status")), messages, self.artifacts(detail), []


class Copilot(Provider):
    origin, prefix, credential = "https://api.github.com", "/agents/tasks", "GITHUB_TOKEN"

    def configure_headers(self, secret):
        self.headers["X-GitHub-Api-Version"] = "2026-03-10"
        self.headers["Accept"] = "application/vnd.github+json"

    def create(self, text):
        repository = self.need("repository").split("/")
        if len(repository) != 2 or not all(repository):
            raise ValueError("repository must be OWNER/REPO")
        path = "/agents/repos/" + "/".join(map(part, repository)) + "/tasks"
        return self.call(path, {"prompt": text, "base_ref": self.need("ref")})["id"]

    def list(self, cursor=None):
        response = self.call(self.prefix + "?" + urlencode({"page": cursor or 1, "per_page": 50}))
        rows = response.get("tasks", []) if isinstance(response, dict) else response
        return rows, str(int(cursor or 1) + 1) if len(rows) == 50 else None

    def snapshot(self):
        detail = self.detail()
        artifacts = [{"url": detail["html_url"]}] if detail.get("html_url") else []
        for item in detail.get("artifacts") or []:
            number = (item.get("data") or {}).get("id")
            if item.get("type") == "pull" and number:
                artifacts.append({"url": f"https://github.com/{self.need('repository')}/pull/{number}"})
        return self.status(detail.get("state")), [], artifacts, []


class Jules(Provider):
    origin, prefix, credential = "https://jules.googleapis.com", "/v1alpha/sessions", "JULES_API_KEY"
    controls = {"send": True}

    def configure_headers(self, secret):
        self.headers = {"X-Goog-Api-Key": secret}

    def create(self, text):
        context = {"source": self.need("source"), "githubRepoContext": {"startingBranch": self.need("ref")}}
        options = {"requirePlanApproval": self.settings.get("require_plan_approval") is True}
        return self.call(self.prefix, {"prompt": text, "sourceContext": context, **options})["name"].split("/")[-1]

    def send(self, text, steer=False):
        self.call(self.path() + ":sendMessage", {"prompt": text})

    def list(self, cursor=None):
        result = self.call(self.prefix + "?" + urlencode({"pageToken": cursor} if cursor else {}))
        return result.get("sessions", []), result.get("nextPageToken")

    def snapshot(self):
        detail = self.detail()
        state = str(detail.get("state", "")).lower()
        activities = self.call(self.path() + "/activities").get("activities", [])
        messages = []
        for item in activities:
            identifier = item.get("name") or item.get("id")
            if identifier and (message := (item.get("agentMessaged") or {}).get("agentMessage")):
                messages.append((identifier, message))
        artifacts = self.artifacts(detail)
        artifacts.extend({"url": item["pullRequest"]["url"]} for item in detail.get("outputs") or []
                         if (item.get("pullRequest") or {}).get("url"))
        # The documented approvePlan action always approves the latest plan. An old
        # Harness card could otherwise approve a newer plan between lookup and action.
        return ("IDLE" if state == "awaiting_plan_approval" else self.status(state)), messages, artifacts, []


class Cursor(Provider):
    origin, prefix, credential = "https://api.cursor.com", "/v1/agents", "CURSOR_API_KEY"
    controls = {"send": True, "steer": True, "cancel_turn": True}

    def configure_headers(self, secret):
        self.headers["Authorization"] = "Basic " + b64encode((secret + ":").encode()).decode()
        self.run = None

    def create(self, text):
        result = self.call(self.prefix, {"prompt": {"text": text}, "autoCreatePR": False,
                                        "repos": [{"url": self.need("repository"), "startingRef": self.need("ref")}]})
        self.run = (result.get("run") or {}).get("id")
        return result["agent"]["id"]

    def send(self, text, steer=False):
        result = self.call(self.path() + "/runs", {"prompt": {"text": text}, **({"delivery": "steer"} if steer else {})})
        self.run = (result.get("run") or {}).get("id") or result.get("runId") or self.run

    def cancel(self):
        if not self.run:
            raise ValueError("Cursor has no active run ID")
        self.call(self.path() + "/runs/" + part(self.run) + "/cancel", {})

    def list(self, cursor=None):
        result = self.call(self.prefix + ("?" + urlencode({"cursor": cursor}) if cursor else ""))
        return result.get("agents", []), result.get("nextCursor")

    def stream_path(self):
        return self.path() + "/runs/" + part(self.run) + "/stream" if self.run else None

    def snapshot(self):
        detail = self.detail()
        agent = detail.get("agent") or detail
        self.run = agent.get("latestRunId") or self.run
        if not self.run:
            return self.status(agent.get("status")), [], self.artifacts(agent), []
        result = self.call(self.path() + "/runs/" + part(self.run))
        run = result.get("run") or result
        messages = [(self.run, run["result"])] if isinstance(run.get("result"), str) else []
        artifacts = self.artifacts(agent)
        artifacts.extend({"url": row["prUrl"]} for row in (run.get("git") or {}).get("branches") or []
                         if row.get("prUrl"))
        state = self.status(run.get("status"))
        return ("IDLE" if state == "FINISHED" else state), messages, artifacts, []


class Devin(Provider):
    origin, credential = "https://api.devin.ai", "DEVIN_API_KEY"
    controls = {"send": True, "cancel_turn": True, "cancel_scope": "session"}

    def configure_headers(self, secret):
        self.prefix = "/v3/organizations/" + part(self.need("organization")) + "/sessions"

    def create(self, text):
        result = self.call(self.prefix, {"prompt": text})
        return result.get("session_id") or result["id"]

    def send(self, text, steer=False):
        self.call(self.path() + "/messages", {"message": text})

    def cancel(self):
        self.call(self.path() + "/terminate", {}, method="POST")

    def list(self, cursor=None):
        result = self.call(self.prefix + ("?" + urlencode({"cursor": cursor}) if cursor else ""))
        return result.get("items", result.get("sessions", [])), result.get("next_cursor")

    def snapshot(self):
        detail = self.detail()
        messages = [(row["id"], row["message"]) for row in detail.get("messages") or []
                    if row.get("id") and row.get("type") == "devin_message" and isinstance(row.get("message"), str)]
        artifacts = self.artifacts(detail)
        artifacts.extend({"url": row["url"]} for row in detail.get("pull_requests") or [] if row.get("url"))
        return self.status(detail.get("status_enum") or detail.get("status")), messages, artifacts, []


PROVIDERS = {"claude": Claude, "openai": OpenAI, "copilot": Copilot, "jules": Jules,
             "cursor": Cursor, "devin": Devin, "qoder": Qoder}


class CloudSession(Session):
    def __init__(self, directory, name, provider):
        super().__init__(directory, name, None)
        self.provider = provider
        self.stop = threading.Event()
        self.io = threading.Lock()
        self.seen = set()
        self.artifacts = []
        project = next((provider.settings[key] for key in ("repository", "source", "project") if key in provider.settings),
                       name)
        self.session_metadata.update(project=project, source="cloud", ref=provider.settings.get("ref"),
                                     account_scope=provider.settings.get("account_scope"))
        self.identifier_to_observe = None

    def open(self, text, files):
        if files or not (text.strip() or self.identifier_to_observe):
            raise ValueError("a cloud session needs a prompt; use provider-owned files and repositories")
        with self.lock:
            if self.ended:
                return
            if text:
                self.begin(text)
        self.provider.identifier = self.identifier_to_observe or self.provider.create(text)
        with self.lock:
            self.session_metadata["external_id"] = self.provider.identifier
            self.identity_changed()
            if self.ended:
                return
            if not self.identifier_to_observe:
                self.controls.update(self.provider.controls)
        if not self.identifier_to_observe and hasattr(self.provider, "started"):
            self.provider.started(text)
        if self.provider.stream_path() is not None or isinstance(self.provider, Cursor):
            threading.Thread(target=self._stream, name="cloud-events", daemon=True).start()
        failures = 0
        while not self.stop.is_set():
            try:
                with self.io:
                    snapshot = self.provider.snapshot()
            except (RuntimeError, ValueError):
                failures += 1
                if failures == 3:
                    self.trace.emit("external_connection", connected=False, reason="cloud status unavailable")
            else:
                if failures >= 3:
                    self.trace.emit("external_connection", connected=True)
                failures = 0
                self.apply_snapshot(*snapshot)
            self.stop.wait(min(15, 2 + failures * 2))

    def _stream(self):
        cursor, previous = None, None
        while not self.stop.is_set():
            path = self.provider.stream_path()
            if path != previous:
                cursor, previous = None, path
            if path:
                try:
                    for identifier, kind, value in self.provider.stream(path, cursor, self.stop):
                        if path != self.provider.stream_path():
                            break
                        cursor = identifier or cursor
                        with self.lock:
                            if self.ended:
                                return
                            self._progress(path, identifier, kind or value.get("type"), value)
                except HTTPError as error:
                    if error.code == 410:
                        cursor = None
                    elif error.code in (401, 403, 404):
                        return  # polling remains the source of truth
                except (URLError, OSError, ValueError):
                    pass
            self.stop.wait(3)

    def _progress(self, path, identifier, kind, value):
        stable = value.get("id") or identifier
        key = ("stream", path, stable, kind)
        if stable and key in self.seen:
            return
        if stable:
            self.seen.add(key)
        text = value.get("delta") if kind == "agent.session.turn.output_text.delta" else (
            value.get("text") if kind == "assistant" else None)
        if isinstance(text, str) and text:
            self.trace.emit("external_message_chunk", text=text[:16384], external_event=stable)
        elif isinstance(kind, str) and ("tool" in kind or "status" in kind):
            self.trace.emit("external_activity", kind=kind, external_event=stable)

    def apply_snapshot(self, status, messages, artifacts, approvals):
        with self.lock:
            if self.ended:
                return
            if self.identifier_to_observe:
                approvals = []
            for identifier, text in messages:
                key = ("message", identifier)
                if key not in self.seen:
                    self.seen.add(key)
                    self.trace.emit("agent_message", text=text, external_event=identifier,
                                    replay=bool(self.identifier_to_observe))
            if artifacts != self.artifacts:
                self.artifacts = artifacts
                self.trace.emit("external_artifacts", artifacts=artifacts)
            if status in ("FINISHED", "ERROR"):
                self.end(status)
                self.stop.set()
            elif approvals:
                for identifier, name, parameters in approvals:
                    key = ("approval", identifier)
                    if key not in self.seen:
                        self.seen.add(key)
                        if not self.pending:
                            self.state("RUNNING", "cloud action requested")
                        self.offer(identifier, json.dumps({"tool": name, "input": parameters}, ensure_ascii=False),
                                   {"allow_once": "allow", "reject_once": "deny"},
                                   lambda choice, identifier=identifier: self.provider.answer(identifier, choice == "allow"))
                if self.pending and self.status != "WAITING_FOR_CONFIRMATION":
                    self.state("WAITING_FOR_CONFIRMATION", "approval")
                elif not self.pending and self.status != "IDLE":
                    self.state("IDLE", "message")
            elif status != self.status:
                if self.pending:
                    self.cancel_permissions()
                self.state(status, "message" if status == "IDLE" else "cloud agent working")

    def send_message(self, text, files=()):
        self._send(text, files, False)

    def steer(self, text, files=()):
        self._send(text, files, True)

    def _send(self, text, files, steer):
        if files or not text.strip():
            raise ValueError("write a cloud message without local attachments")
        with self.lock:
            if self.ended or not self.controls.get("send") or self.pending:
                raise ValueError("the cloud session cannot take a message now")
            if self.status != "IDLE" and not (steer and self.controls.get("steer")):
                raise ValueError("wait for the cloud turn or use its steering operation")
            with self.io:
                self.provider.send(text, steer)
            if self.status == "IDLE":
                self.begin(text)
            else:
                self.trace.emit("user_message", text=text, sender="user", steer=True)

    def cancel(self):
        with self.lock:
            if self.ended or not self.controls.get("cancel_turn"):
                raise ValueError("this provider does not support cancellation")
            self.cancel_permissions()
            with self.io:
                self.provider.cancel()
            self.trace.emit("external_cancel_requested")

    def close_transport(self):
        self.stop.set()

    def set_model(self, model=None, reasoning_effort=None):
        raise ValueError("configure the provider's model before creating the cloud session")


def configured_provider(name, settings):
    provider = PROVIDERS.get(name.removeprefix("cloud:"))
    if provider is None or not isinstance(settings, dict):
        raise ValueError("choose a configured cloud provider")
    if not isinstance(settings.get("account_scope"), str) or not settings["account_scope"].strip():
        raise ValueError("set an account_scope label for the configured cloud credentials")
    return provider(settings)


def cloud_list(provider, cursor=None):
    rows, next_cursor = provider.list(cursor)
    return {"sessions": [{key: row[key] for key in ("id", "session_id", "name", "title", "status", "state", "url")
                          if key in row} for row in rows], "nextCursor": next_cursor}
