"""Aggregate Overview snapshot endpoint (`GET /api/app/overview`).

Combines real existing backend state for a chat into a single collapsible Overview panel:
- workspace (project, folder, git branch/dirty count; zero errors in non-git workspaces)
- tools (Review/Changes, Files, Terminal, Plugins/Customizations, plus Browser when active)
- background_tasks (running/queued turns, chat tasks, and active host sessions)
- goals (pending intentions, active tasks, and plan artifact checklist items)
- artifacts (local Markdown artifacts from `host.artifacts`)
- pull_requests (optional non-blocking cached local `gh` PR list; empty on non-git workspaces)
- context (token usage, mode, model, today's spend)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

_PR_CACHE_TTL = 60.0
_PR_CACHE: dict[str, tuple[float, list[dict]]] = {}
_PR_INFLIGHT: set[str] = set()
_PR_LOCK = threading.Lock()
_CHECKLIST_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.+?)\s*$")


def _one(body, key, default=None):
    val = body.get(key, default)
    return val[0] if isinstance(val, list) else val


def _git_quick(folder: Path, *args: str, timeout: float = 2.5) -> subprocess.CompletedProcess | None:
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        return subprocess.run(
            ["git", "-C", str(folder), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            **flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git_info(folder: Path | None) -> dict:
    if folder is None or not folder.is_dir():
        return {"is_git": False, "branch": "", "dirty_count": 0}
    inside = _git_quick(folder, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0 or inside.stdout.strip().lower() != "true":
        return {"is_git": False, "branch": "", "dirty_count": 0}
    br = _git_quick(folder, "branch", "--show-current")
    branch = br.stdout.strip() if br and br.returncode == 0 else ""
    st = _git_quick(folder, "status", "--porcelain")
    dirty = len([ln for ln in (st.stdout.splitlines() if st and st.returncode == 0 else []) if ln.strip()])
    return {"is_git": True, "branch": branch, "dirty_count": dirty}


def _fetch_prs_sync(folder: Path) -> list[dict]:
    if not shutil.which("gh"):
        return []
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        res = subprocess.run(
            ["gh", "pr", "list", "--limit", "5", "--json", "number,title,state,url,headRefName"],
            cwd=str(folder),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4.0,
            stdin=subprocess.DEVNULL,
            **flags,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return []
        rows = json.loads(res.stdout)
        if not isinstance(rows, list):
            return []
        return [
            {
                "number": r.get("number"),
                "title": str(r.get("title") or ""),
                "state": str(r.get("state") or "OPEN"),
                "url": str(r.get("url") or ""),
                "branch": str(r.get("headRefName") or ""),
            }
            for r in rows
            if isinstance(r, dict)
        ]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def _cached_prs(folder: Path | None, *, is_git: bool, fetcher=None) -> list[dict]:
    """Non-blocking cached PR lookup: returns cached rows immediately, refreshes in background."""
    if not is_git or folder is None:
        return []
    key = str(folder.resolve())
    now = time.monotonic()
    with _PR_LOCK:
        cached = _PR_CACHE.get(key)
        if cached and (now - cached[0]) < _PR_CACHE_TTL:
            return list(cached[1])
        if key not in _PR_INFLIGHT:
            _PR_INFLIGHT.add(key)

            def _refresh():
                try:
                    rows = (fetcher or _fetch_prs_sync)(folder)
                except Exception:
                    rows = []
                with _PR_LOCK:
                    _PR_CACHE[key] = (time.monotonic(), rows)
                    _PR_INFLIGHT.discard(key)

            threading.Thread(target=_refresh, name="overview-pr-refresh", daemon=True).start()
        return list(cached[1]) if cached else []


def _collect_background_tasks(server, life, chat_id: str) -> list[dict]:
    tasks: list[dict] = []
    seen: set[str] = set()
    if life is not None:
        # Running/queued jobs in this chat
        try:
            q = life.queue(chat_id)
            if isinstance(q, dict):
                running = q.get("running")
                if isinstance(running, dict):
                    tid = str(running.get("id") or f"run-{chat_id}")
                    seen.add(tid)
                    tasks.append({
                        "id": tid,
                        "title": str(running.get("text") or "Running turn")[:100],
                        "status": "running",
                        "kind": "turn",
                    })
                for item in q.get("queued") or ():
                    if isinstance(item, dict):
                        tid = str(item.get("id") or "")
                        if tid and tid not in seen:
                            seen.add(tid)
                            tasks.append({
                                "id": tid,
                                "title": str(item.get("text") or "Queued message")[:100],
                                "status": "queued",
                                "kind": "queue",
                            })
        except Exception:
            pass
        # Active sub-tasks recorded in this chat
        try:
            if callable(getattr(life, "task_rows", None)):
                for row in life.task_rows(chat_id) or ():
                    if not isinstance(row, dict):
                        continue
                    tid = str(row.get("run") or row.get("id") or row.get("goal") or "")
                    if tid in seen:
                        continue
                    seen.add(tid)
                    tasks.append({
                        "id": tid or f"task-{len(tasks)}",
                        "title": str(row.get("goal") or row.get("title") or tid)[:100],
                        "status": str(row.get("status") or row.get("end") or "running"),
                        "kind": "task",
                    })
        except Exception:
            pass
    # Active host conversations/sessions if server exposes them
    convs = getattr(server, "conversations", None)
    if convs is not None and callable(getattr(convs, "sessions", None)):
        try:
            for sess in convs.sessions() or ():
                if not isinstance(sess, dict):
                    continue
                status = str(sess.get("status") or "")
                if status.upper() in ("ENDED", "DONE", "CLOSED", "FAILED", "CANCELLED"):
                    continue
                tid = str(sess.get("id") or sess.get("run") or "")
                if tid and tid not in seen:
                    seen.add(tid)
                    tasks.append({
                        "id": tid,
                        "title": str(sess.get("title") or tid)[:100],
                        "status": status.lower() or "running",
                        "kind": "session",
                    })
        except Exception:
            pass
    return tasks


def _collect_goals(life, chat_id: str, artifacts_dir: Path | None) -> list[dict]:
    goals: list[dict] = []
    if life is not None:
        for item in getattr(life, "intentions", None) or ():
            if not isinstance(item, dict):
                continue
            if item.get("chat") not in (None, chat_id):
                continue
            if item.get("done") or item.get("cancelled"):
                continue
            text = str(item.get("about") or item.get("text") or item.get("goal") or "").strip()
            if text:
                goals.append({"text": text[:140], "done": False, "source": "intention"})
    # Parse markdown checklists from plan artifacts if present
    if artifacts_dir is not None and artifacts_dir.is_dir():
        for name in ("task.md", "implementation_plan.md"):
            art = artifacts_dir / name
            if not art.is_file() or art.is_symlink():
                continue
            try:
                for line in art.read_text(encoding="utf-8", errors="replace").splitlines()[:200]:
                    m = _CHECKLIST_RE.match(line)
                    if m:
                        goals.append({
                            "text": m.group(2).strip()[:140],
                            "done": m.group(1).lower() == "x",
                            "source": name,
                        })
            except OSError:
                continue
            if goals:
                break
    return goals[:20]


def _browser_is_active(life, chat_id: str, meta: dict) -> bool:
    if life is None:
        return False
    place_id = meta.get("place")
    places = getattr(life, "places", None) or {}
    if place_id and place_id in places:
        if getattr(places[place_id], "kind", None) == "browser":
            return True
    if any(getattr(pl, "kind", None) == "browser" for pl in places.values()):
        return True
    try:
        recent = life.chats.read(chat_id, after=0, limit=50)
        if any(str(r.get("verb") or "").startswith("browser.") for r in recent):
            return True
    except Exception:
        pass
    return False


def overview(server, body):
    """GET /api/app/overview?identity=<id>&chat=<chat>."""
    from . import host as app_host

    identity_arg = _one(body, "identity")
    chat_id = str(_one(body, "chat") or "main").strip() or "main"
    row = app_host._identity_row(server, identity_arg)
    identity_id = row["id"]
    life = app_host._life(server, identity_id)

    meta = {}
    if life is not None:
        try:
            meta = life.chats.meta(chat_id)
        except Exception:
            meta = {}

    folder = app_host._place_folder(server, identity_id, chat_id)
    git = _git_info(folder)
    place = (getattr(life, "places", None) or {}).get(meta.get("place")) if life is not None and meta.get("place") else None
    project_name = ""
    if place is not None:
        prow = getattr(place, "row", None) or {}
        project_name = str(prow.get("title") or prow.get("id") or "").removeprefix("folder · ").strip()
    if not project_name and folder is not None:
        project_name = folder.name

    try:
        artifacts_dir = app_host._artifacts_dir(server, identity_id, chat_id)
    except ValueError:
        artifacts_dir = None

    try:
        artifacts_list = app_host.artifacts(server, {"identity": identity_id, "chat": chat_id}).get("artifacts", [])
    except Exception:
        artifacts_list = []

    browser_active = _browser_is_active(life, chat_id, meta)
    tools = [
        {"id": "changes", "label": "Review / Changes", "available": bool(folder and git["is_git"]), "badge": git["dirty_count"]},
        {"id": "files", "label": "Files", "available": bool(folder)},
        {"id": "terminal", "label": "Terminal", "available": True},
        {"id": "plugins", "label": "Plugins", "available": True},
    ]
    if browser_active:
        tools.append({"id": "browser", "label": "Browser", "available": True, "active": True})

    ctx = {}
    if life is not None:
        try:
            ctx = life.context(chat_id) or {}
        except Exception:
            ctx = {}

    branch = (meta.get("copy") or {}).get("branch") or git["branch"]
    return {
        "identity": identity_id,
        "chat": chat_id,
        "workspace": {
            "project": project_name,
            "folder": str(folder) if folder else "",
            "branch": branch,
            "isolation": meta.get("isolation"),
            "is_git": git["is_git"],
            "dirty_count": git["dirty_count"],
        },
        "tools": tools,
        "background_tasks": _collect_background_tasks(server, life, chat_id),
        "goals": _collect_goals(life, chat_id, artifacts_dir),
        "artifacts": artifacts_list,
        "pull_requests": _cached_prs(folder, is_git=git["is_git"]),
        "context": {
            "used": int(ctx.get("used") or 0),
            "limit": int(ctx.get("limit") or 0),
            "mode": meta.get("mode") or "auto",
            "model": meta.get("model"),
        },
    }
