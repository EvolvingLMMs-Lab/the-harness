"""Focused backend tests for the 5-item App UI & backend upgrade:
(a) Persistent attachment serving (MIME, nosniff, path-traversal/symlink blocking) + static KaTeX serving.
(b) First-turn auto-title single-trigger on default, clean fallback, user race guard, and SSE live update.
(c) Overview aggregate endpoint on git and non-git workspaces.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import TestCase, mock

import helpers  # noqa: F401

sys.path.insert(0, str(helpers.ROOT / "packages" / "app"))
sys.path.insert(0, str(helpers.ROOT / "packages" / "agent"))

from harness.host.http import Server  # noqa: E402
from harness_agent import host as agent_host, titles  # noqa: E402
from harness_agent.chats import Chats  # noqa: E402
from harness_agent.life import Life  # noqa: E402
from harness_agent.state import Identity  # noqa: E402
from harness_app import host as app_host, overview as overview_mod  # noqa: E402


class _FakeModel:
    def __init__(self, reply_text="Reply from assistant"):
        self.reply_text = reply_text

    def complete(self, system, messages, **kwargs):
        return SimpleNamespace(
            text=json.dumps({"action": "reply", "text": self.reply_text}),
            reasoning="",
            usage={},
        )


def _start_server(root: Path, lives: dict):
    srv = Server(("127.0.0.1", 0), root, token="test-token")
    srv.background = {"agent": SimpleNamespace(life=lambda ident: lives[ident])}
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def _http_get(port: int, path: str, token: str = "test-token"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {"X-Session-API-Key": token} if token else {}
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, dict(resp.getheaders()), body
    finally:
        conn.close()


def _http_post(port: int, path: str, payload: dict, token: str = "test-token"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Session-API-Key"] = token
        conn.request("POST", path, body=json.dumps(payload).encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, json.loads(body.decode("utf-8"))
    finally:
        conn.close()


class AppUiPolishTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.ident_dir = self.root / "agents" / "default"
        self.ident_dir.mkdir(parents=True)
        self.identity = Identity("default", root=self.root / "agents")
        self.identity_rows = [{"id": "default", "name": "Tester", "folder": str(self.identity.directory), "current": True}]
        self.patch_ident = mock.patch.object(
            app_host,
            "_agent",
            lambda name: (lambda server, body: self.identity_rows) if name == "identities" else None,
        )
        self.patch_ident.start()

    def tearDown(self):
        self.patch_ident.stop()
        self.tmp.cleanup()

    # ── (a) Persistent attachment serving + static KaTeX serving ──

    def test_attachment_serving_security_and_static_katex(self):
        chats = Chats(self.identity)
        chat_id = chats.new()
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        row = chats.attach(chat_id, "diagram.png", png_bytes, "image/png")

        self.assertEqual(row["mime"], "image/png")
        self.assertEqual(row["size"], len(png_bytes))
        self.assertIn(f"/api/app/attachments/{row['id']}", row["url"])

        # Plant a secret outside files/ and an index entry attempting directory escape
        secret = self.identity.directory / "secret.txt"
        secret.write_text("TOP_SECRET", encoding="utf-8")
        files_dir = chats.folder(chat_id) / "files"
        idx_path = files_dir / "index.json"
        entries = json.loads(idx_path.read_text(encoding="utf-8"))
        entries.append({"id": "fescape0001", "name": "escape.txt", "mime": "text/plain", "file": "../../../secret.txt", "size": 10})

        # Also attempt a symlink entry when OS permits symlink creation
        sym_created = False
        sym_path = files_dir / "fsym000001-link.txt"
        try:
            os.symlink(secret, sym_path)
            entries.append({"id": "fsym000001", "name": "link.txt", "mime": "text/plain", "file": sym_path.name, "size": 10})
            sym_created = True
        except OSError:
            sym_created = False
        idx_path.write_text(json.dumps(entries), encoding="utf-8")

        fake_life = SimpleNamespace(chats=chats, identity=self.identity, places={}, alive=True, live={}, context=lambda c: {}, queue=lambda c: {})
        srv, port = _start_server(self.root / "runs", {"default": fake_life})
        try:
            # 1. Valid same-origin attachment fetch
            status, headers, body = _http_get(port, row["url"])
            self.assertEqual(status, 200)
            self.assertEqual(body, png_bytes)
            h_low = {k.lower(): v for k, v in headers.items()}
            self.assertEqual(h_low.get("content-type"), "image/png")
            self.assertEqual(h_low.get("x-content-type-options"), "nosniff")

            # 2. Path traversal attempts blocked with 403 + nosniff
            for bad_url in (
                "/api/app/attachments/..%2Fsecret.txt?identity=default",
                "/api/app/attachments/../../secret.txt?identity=default",
                f"/api/app/attachments/fescape0001?identity=default&chat={chat_id}",
            ):
                st, hdrs, _ = _http_get(port, bad_url)
                self.assertEqual(st, 403, f"expected 403 for {bad_url}, got {st}")
                self.assertEqual({k.lower(): v for k, v in hdrs.items()}.get("x-content-type-options"), "nosniff")

            if sym_created:
                st, _, _ = _http_get(port, f"/api/app/attachments/fsym000001?identity=default&chat={chat_id}")
                self.assertEqual(st, 403)

            # 3. Missing valid ID -> 404
            st_404, _, _ = _http_get(port, f"/api/app/attachments/fmissing999?identity=default&chat={chat_id}")
            self.assertEqual(st_404, 404)

            # 4. Offline vendored KaTeX assets served with accurate MIME types
            for path, want_ct in (
                ("/static/app/vendor/katex/katex.min.css", "text/css"),
                ("/static/app/vendor/katex/katex.mjs", "text/javascript"),
                ("/static/app/vendor/katex/fonts/KaTeX_Main-Regular.woff2", "font/woff2"),
            ):
                st_s, hdrs_s, body_s = _http_get(port, path, token="")
                self.assertEqual(st_s, 200, path)
                self.assertGreater(len(body_s), 100)
                self.assertIn(want_ct, {k.lower(): v for k, v in hdrs_s.items()}.get("content-type", ""))
        finally:
            srv.shutdown()
            srv.server_close()

    # ── (b) Auto-title single-trigger, fallback, user race guard, and SSE live push ──

    def test_auto_title_lifecycle_fallback_race_guard_and_sse(self):
        # Clean fallback strips quotes, markdown, and filler prefixes in EN and ZH
        self.assertEqual(titles.fallback_title('"Please help me fix the login timeout bug"'), "fix the login timeout bug")
        self.assertEqual(titles.fallback_title("请帮我优化数据库索引性能"), "优化数据库索引性能")
        self.assertEqual(titles.clean_title('Title: "Fix KaTeX Rendering."'), "Fix KaTeX Rendering")

        life = Life(self.identity, model=lambda *a, **k: _FakeModel("Image shows an architecture chart"))
        life.alive = True
        calls = []
        gate = threading.Event()
        gate.set()

        def model_title(seed):
            calls.append(seed)
            gate.wait(timeout=3.0)
            return '"Fix Login Timeout"'

        life.title_model_fn = model_title
        try:
            chat_id = life.chats.new()
            self.assertEqual(life.chats.meta(chat_id)["title_source"], "default")

            # Start SSE client before triggering auto-title
            srv, port = _start_server(self.root / "runs", {"default": life})
            sse_events = []
            sse_ready = threading.Event()
            sse_done = threading.Event()

            def _read_sse():
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    conn.request("GET", f"/api/agent/stream?identity=default&chat={chat_id}&after=0",
                                 headers={"X-Session-API-Key": "test-token"})
                    resp = conn.getresponse()
                    while len(sse_events) < 2:
                        line = resp.readline().decode("utf-8", errors="replace")
                        if not line:
                            break
                        if line.startswith("data: "):
                            sse_events.append(json.loads(line[6:]))
                            if len(sse_events) == 1:
                                sse_ready.set()
                            if sse_events[-1].get("meta", {}).get("title") == "Fix Login Timeout":
                                sse_done.set()
                                break
                except Exception:
                    pass
                finally:
                    conn.close()

            sse_thread = threading.Thread(target=_read_sse, daemon=True)
            sse_thread.start()
            self.assertTrue(sse_ready.wait(timeout=3.0), "initial SSE snapshot not received")

            # Trigger first-turn auto-title on default chat
            self.assertTrue(life._maybe_auto_title(chat_id, "Please help me fix the login timeout bug"))
            self.assertTrue(sse_done.wait(timeout=3.0), f"SSE did not push auto-title; got={sse_events}")
            meta = life.chats.meta(chat_id)
            self.assertEqual(meta["title"], "Fix Login Timeout")
            self.assertEqual(meta["title_source"], "auto")
            self.assertEqual(len(calls), 1)

            # Second trigger must NOT run again once title_source == "auto"
            self.assertFalse(life._maybe_auto_title(chat_id, "Second turn message"))
            self.assertEqual(len(calls), 1)

            # User rename race guard: manual rename wins over slow in-flight auto-title
            race_chat = life.chats.new()
            gate.clear()
            self.assertTrue(life._maybe_auto_title(race_chat, "Slow first turn message"))
            life.chats.rename(race_chat, "My Manual Name")
            self.assertEqual(life.chats.meta(race_chat)["title_source"], "user")
            gate.set()
            time.sleep(0.15)
            # Even after worker completes, user title is never overwritten
            self.assertEqual(life.chats.meta(race_chat)["title"], "My Manual Name")
            self.assertEqual(life.chats.meta(race_chat)["title_source"], "user")
            self.assertFalse(life.chats.set_auto_title(race_chat, "Late Auto Title"))
        finally:
            life.alive = False
            life.chats.notify()
            srv.shutdown()
            srv.server_close()

    def test_new_chat_default_title_sources_and_auto_title(self):
        # Short greeting fallback must never strip to empty
        self.assertEqual(titles.fallback_title("你好"), "你好")
        self.assertEqual(titles.fallback_title("你好，请帮我"), "你好，请帮我")

        life = Life(self.identity, model=lambda *a, **k: _FakeModel("Reply"))
        life.alive = True
        life.title_model_fn = lambda seed: f"Auto: {seed}"
        srv, port = _start_server(self.root / "runs", {"default": life})
        try:
            # Localized placeholder titles and explicit title_source="default" enable auto-titling
            cases = [
                ({"identity": "default", "title": "新对话"}, "排查数据库连接池泄漏", "Auto: 排查数据库连接池泄漏"),
                ({"identity": "default", "title": "New conversation"}, "Debug login redirect", "Auto: Debug login redirect"),
                (
                    {"identity": "default", "title": "Nouvelle conversation", "title_source": "default"},
                    "Optimize build cache",
                    "Auto: Optimize build cache",
                ),
            ]
            for payload, seed, expected_title in cases:
                status, data = _http_post(port, "/api/agent/new_chat", payload)
                self.assertEqual(status, 200, data)
                chat_id = data["chat"]
                self.assertEqual(life.chats.meta(chat_id)["title_source"], "default", payload)
                self.assertTrue(life._maybe_auto_title(chat_id, seed))
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and life.chats.meta(chat_id)["title_source"] == "default":
                    time.sleep(0.02)
                meta = life.chats.meta(chat_id)
                self.assertEqual(meta["title"], expected_title)
                self.assertEqual(meta["title_source"], "auto")

            # Real custom titles keep title_source="user" and block auto-titling
            status, data = _http_post(port, "/api/agent/new_chat", {"identity": "default", "title": "Quarterly Planning"})
            self.assertEqual(status, 200, data)
            custom_chat = data["chat"]
            self.assertEqual(life.chats.meta(custom_chat)["title_source"], "user")
            self.assertFalse(life._maybe_auto_title(custom_chat, "Should not overwrite"))
            self.assertEqual(life.chats.meta(custom_chat)["title"], "Quarterly Planning")
        finally:
            life.alive = False
            life.chats.notify()
            srv.shutdown()
            srv.server_close()

    # ── (c) Overview aggregate endpoint on git & non-git workspaces ──

    def test_overview_endpoint_git_and_non_git_workspaces(self):
        chats = Chats(self.identity)

        # 1. Non-git workspace folder
        plain_dir = self.root / "plain_workspace"
        plain_dir.mkdir()
        (plain_dir / "notes.txt").write_text("hello", encoding="utf-8")
        non_git_chat = chats.new("Plain Chat")
        chats.update(non_git_chat, place="folder-plain")
        place_plain = SimpleNamespace(kind="folder", row={"kind": "folder", "id": "folder-plain", "title": "plain_workspace", "folder": str(plain_dir)})

        # 2. Real git workspace with one dirty file + Markdown plan artifact with checklist goals
        git_dir = self.root / "git_workspace"
        git_dir.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(git_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(git_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(git_dir), check=True, capture_output=True)
        (git_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=str(git_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(git_dir), check=True, capture_output=True)
        (git_dir / "README.md").write_text("# Demo updated\n", encoding="utf-8")

        git_chat = chats.new("Git Chat")
        chats.update(git_chat, place="folder-git")
        art_dir = chats.folder(git_chat) / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "implementation_plan.md").write_text(
            "# Upgrade Plan\n\n- [x] Backend endpoints\n- [ ] Frontend wiring\n",
            encoding="utf-8",
        )
        place_git = SimpleNamespace(kind="folder", row={"kind": "folder", "id": "folder-git", "title": "git_workspace", "folder": str(git_dir)})

        fake_life = SimpleNamespace(
            chats=chats,
            identity=self.identity,
            places={"folder-plain": place_plain, "folder-git": place_git},
            intentions=[],
            queue=lambda c: {"running": None, "queued": []},
            context=lambda c: {"used": 1200, "limit": 128000},
        )
        server = SimpleNamespace(background={"agent": SimpleNamespace(life=lambda ident: fake_life)})

        # Avoid spawning gh subprocess during unit test
        with mock.patch.object(overview_mod, "_cached_prs", return_value=[]):
            snap_plain = app_host.overview(server, {"identity": "default", "chat": non_git_chat})
            self.assertFalse(snap_plain["workspace"]["is_git"])
            self.assertEqual(snap_plain["workspace"]["dirty_count"], 0)
            self.assertEqual(snap_plain["pull_requests"], [])
            self.assertEqual(snap_plain["artifacts"], [])

            snap_git = app_host.overview(server, {"identity": "default", "chat": git_chat})
            self.assertTrue(snap_git["workspace"]["is_git"])
            self.assertEqual(snap_git["workspace"]["branch"], "main")
            self.assertGreaterEqual(snap_git["workspace"]["dirty_count"], 1)
            self.assertEqual(len(snap_git["artifacts"]), 1)
            self.assertEqual(snap_git["artifacts"][0]["name"], "implementation_plan.md")
            self.assertEqual(len(snap_git["goals"]), 2)
            self.assertTrue(snap_git["goals"][0]["done"])
            self.assertFalse(snap_git["goals"][1]["done"])
            tool_ids = [t["id"] for t in snap_git["tools"]]
            self.assertEqual(tool_ids[:4], ["changes", "files", "terminal", "plugins"])
