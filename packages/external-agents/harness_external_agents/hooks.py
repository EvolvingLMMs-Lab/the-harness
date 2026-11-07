"""Opt-in forwarding for already observed terminal sessions."""

import json
from pathlib import Path
import sys
import threading

from harness.sdk import Host, atomic_write, home

from .observe import ObservedSession


def scopes():
    path = home() / "external-agent-hooks.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def set_scope(provider, folder, enabled):
    folder = str(Path(folder).resolve(strict=True))
    saved = scopes()
    projects = set(saved.get(provider, []))
    (projects.add if enabled else projects.discard)(folder)
    saved[provider] = sorted(projects)
    atomic_write(home() / "external-agent-hooks.json", json.dumps(saved, indent=2), private=True)


def dispatch(provider):
    # The native hook keeps its own prompt when Harness is unreachable or declines.
    try:
        raw = sys.stdin.buffer.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            return
        item = json.loads(raw)
        event = item.get("hook_event_name")
        if event not in ("PermissionRequest", "Notification", "Stop") or not item.get("cwd"):
            return
        folder = str(Path(item["cwd"]).resolve())
        if folder not in scopes().get(provider, []):
            return
        host = Host.connect(start=False)
        if host is None:
            return
        result = host.post("/api/external-agents/hook", {"provider": provider, "event": event, "cwd": folder,
                           "session": item.get("session_id"), "tool": item.get("tool_name"),
                           "input": item.get("tool_input"), "native_request": item.get("tool_use_id")}, timeout=40)
        choice = result.get("choice")
        if choice in ("allow", "deny"):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                                     "decision": {"behavior": choice}}}))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return


def receive(server, body):
    provider, cwd = body.get("provider"), body.get("cwd")
    if cwd not in scopes().get(provider, []):
        return {}
    session = next((item for item in server.conversations.copy().values()
                    if isinstance(item, ObservedSession) and item.follow and not item.ended
                    and item.provider == provider and item.session_metadata["cwd"] == cwd
                    and item.session_metadata["external_id"] == body.get("session")), None)
    if session is None:
        return {}
    if body.get("event") in ("Notification", "Stop"):
        with session.lock:
            session.trace.emit("external_notice", name=body["event"], source="terminal_hook")
        return {}
    if body.get("event") != "PermissionRequest" or not isinstance(body.get("tool"), str):
        return {}
    result, done = {}, threading.Event()

    def reply(choice):
        if choice in ("allow", "deny") and cwd in scopes().get(provider, []):
            result["choice"] = choice
        done.set()

    description = json.dumps({"tool": body["tool"], "input": body.get("input")}, ensure_ascii=False)
    if len(description) > 24_000:
        return {}
    identifier = session.offer(body.get("native_request") or body["tool"], description,
                               {"allow_once": "allow", "reject_once": "deny"}, reply, seconds=28)
    if not done.wait(30) and identifier:
        session.expire(identifier)
    return result
