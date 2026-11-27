"""Real-contract backend tests for the 5-item App UI & backend polish rework:
(a) Persistent attachment serving (MIME, nosniff, report..v2.pdf allowed, SVG attachment
    disposition, traversal/symlink blocking), empty input_text omission in Session._with_files,
    and single-bundle offline KaTeX / vendor hygiene.
(b) First-turn auto-title: UI-created default titles ("New conversation", "新对话", explicit
    title_source="default"), dedicated one-shot non-thinking ChatModel config + spending charge
    (never borrowing shared Life._model), non-HTTP/ACP fallback, user race guard, and SSE push.
(c) Overview aggregate endpoint against REAL Life.context(), REAL Life.intend(), REAL
    life.sessions[chat].state["pending"], and server.conversations.sessions().
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
from harness.runtime.decision.model import ChatModel, ChatReply  # noqa: E402
from harness_agent import host as agent_host, titles  # noqa: E402
from harness_agent.chats import Chats  # noqa: E402
from harness_agent.life import Life  # noqa: E402
from harness_agent.session import Session  # noqa: E402
from harness_agent.state import Identity  # noqa: E402
from harness_app import host as app_host, overview as overview_mod  # noqa: E402


class _FakeModel:
    def __init__(self, reply_text="Reply from assistant"):
        self.reply_text = reply_text
        self.calls = 0

    def complete(self, system, messages, **kwargs):
        self.calls += 1
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

    # ── (a) Attachments edge cases, Session._with_files, and single-bundle offline KaTeX ──

    def test_attachment_serving_security_edge_cases_and_static_katex(self):
        chats = Chats(self.identity)
        chat_id = chats.new()
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        pdf_bytes = b"%PDF-1.4\n%test\n"
        svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

        png_row = chats.attach(chat_id, "diagram.png", png_bytes, "image/png")
        dots_row = chats.attach(chat_id, "report..v2.pdf", pdf_bytes, "application/pdf")
        svg_row = chats.attach(chat_id, "vector.svg", svg_bytes, "image/svg+xml")

        self.assertEqual(png_row["mime"], "image/png")
        self.assertEqual(png_row["size"], len(png_bytes))
        self.assertIn(f"/api/app/attachments/{png_row['id']}", png_row["url"])

        # Plant a secret outside files/ and unsafe index entries
        secret = self.identity.directory / "secret.txt"
        secret.write_text("TOP_SECRET", encoding="utf-8")
        files_dir = chats.folder(chat_id) / "files"
        idx_path = files_dir / "index.json"
        entries = json.loads(idx_path.read_text(encoding="utf-8"))
        entries.append({"id": "fescape0001", "name": "escape.txt", "mime": "text/plain", "file": "../../../secret.txt", "size": 10})
        entries.append({"id": "fslash00001", "name": "sub.txt", "mime": "text/plain", "file": "sub/secret.txt", "size": 10})

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
            # 1. Valid PNG attachment
            status, headers, body = _http_get(port, png_row["url"])
            self.assertEqual(status, 200)
            self.assertEqual(body, png_bytes)
            h_low = {k.lower(): v for k, v in headers.items()}
            self.assertEqual(h_low.get("content-type"), "image/png")
            self.assertEqual(h_low.get("x-content-type-options"), "nosniff")

            # 2. Legitimate filename containing '..' (report..v2.pdf) MUST succeed with 200
            st_dots, hdrs_dots, body_dots = _http_get(port, dots_row["url"])
            self.assertEqual(st_dots, 200)
            self.assertEqual(body_dots, pdf_bytes)
            self.assertEqual({k.lower(): v for k, v in hdrs_dots.items()}.get("content-type"), "application/pdf")

            # 3. SVG attachment MUST force Content-Disposition: attachment + sandboxed CSP + nosniff
            st_svg, hdrs_svg, body_svg = _http_get(port, svg_row["url"])
            self.assertEqual(st_svg, 200)
            self.assertEqual(body_svg, svg_bytes)
            h_svg = {k.lower(): v for k, v in hdrs_svg.items()}
            self.assertIn("attachment", h_svg.get("content-disposition", ""))
            self.assertIn("sandbox", h_svg.get("content-security-policy", ""))
            self.assertEqual(h_svg.get("x-content-type-options"), "nosniff")

            # 4. Path traversal, separators, and symlinks blocked with 403 + nosniff
            for bad_url in (
                "/api/app/attachments/..%2Fsecret.txt?identity=default",
                "/api/app/attachments/../../secret.txt?identity=default",
                f"/api/app/attachments/fescape0001?identity=default&chat={chat_id}",
                f"/api/app/attachments/fslash00001?identity=default&chat={chat_id}",
            ):
                st, hdrs, _ = _http_get(port, bad_url)
                self.assertEqual(st, 403, f"expected 403 for {bad_url}, got {st}")
                self.assertEqual({k.lower(): v for k, v in hdrs.items()}.get("x-content-type-options"), "nosniff")

            if sym_created:
                st, _, _ = _http_get(port, f"/api/app/attachments/fsym000001?identity=default&chat={chat_id}")
                self.assertEqual(st, 403)

            # 5. Missing valid ID -> 404
            st_404, _, _ = _http_get(port, f"/api/app/attachments/fmissing999?identity=default&chat={chat_id}")
            self.assertEqual(st_404, 404)

            # 6. Offline vendored single-bundle KaTeX + ESM Marked/DOMPurify + no test file under /static/
            for path, want_ct in (
                ("/static/app/vendor/katex/katex.min.css", "text/css"),
                ("/static/app/vendor/katex/katex.min.js", "text/javascript"),
                ("/static/app/vendor/katex/fonts/KaTeX_Main-Regular.woff2", "font/woff2"),
                ("/static/app/vendor/marked.js", "text/javascript"),
                ("/static/app/vendor/dompurify.js", "text/javascript"),
            ):
                st_s, hdrs_s, body_s = _http_get(port, path, token="")
                self.assertEqual(st_s, 200, path)
                self.assertGreater(len(body_s), 100)
                self.assertIn(want_ct, {k.lower(): v for k, v in hdrs_s.items()}.get("content-type", ""))
                if path.endswith(".js"):
                    self.assertNotIn(b"sourceMappingURL", body_s, f"dangling sourcemap in {path}")
                if path.endswith("katex.min.css"):
                    self.assertNotIn(b".woff)", body_s)
                    self.assertNotIn(b".ttf)", body_s)

            # Unminified katex.mjs and test file must NOT be served under /static/
            for gone_path in ("/static/app/vendor/katex/katex.mjs", "/static/app/js/markdown.test.mjs"):
                st_gone, _, _ = _http_get(port, gone_path, token="")
                self.assertEqual(st_gone, 404, f"{gone_path} should not be served")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_session_with_files_omits_empty_input_text(self):
        chats = Chats(self.identity)
        chat_id = chats.new()
        png_row = chats.attach(chat_id, "shot.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png")
        pdf_row = chats.attach(chat_id, "notes.pdf", b"%PDF-1.4\n", "application/pdf")
        sess = Session(self.identity, _FakeModel(), tasks=None, session=chat_id, chats=chats)

        # Image-only message (text == "") must omit empty input_text part
        img_only = sess._with_files([{"role": "user", "content": "", "files": [png_row]}])
        self.assertEqual(len(img_only), 1)
        parts = img_only[0]["content"]
        self.assertIsInstance(parts, list)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["type"], "input_image")

        # Verify real ChatModel.payload accepts image-only parts cleanly
        cm = ChatModel({"backend": "openai_chat", "base_url": "http://127.0.0.1:9", "model": "demo"})
        payload = cm.payload("sys", img_only)
        self.assertEqual(payload["messages"][1]["content"][0]["type"], "image_url")

        # File-only message (text == "") must produce clean string without leading blank lines
        file_only = sess._with_files([{"role": "user", "content": "", "files": [pdf_row]}])
        self.assertIsInstance(file_only[0]["content"], str)
        self.assertTrue(file_only[0]["content"].startswith("Files your owner attached"))

        # Text + image keeps both input_text and input_image
        both = sess._with_files([{"role": "user", "content": "Look at this", "files": [png_row]}])
        self.assertEqual([p["type"] for p in both[0]["content"]], ["input_text", "input_image"])

    # ── (b) Native Auto-Title: UI defaults, one-shot ChatModel + billing, non-HTTP fallback, race guard & SSE ──

    def test_auto_title_native_chatmodel_config_billing_and_non_http_fallback(self):
        # 1. Built-in HTTP provider config -> dedicated lightweight non-thinking ChatModel config
        http_cfg = {
            "backend": "openai_chat",
            "base_url": "http://127.0.0.1:9999/v1",
            "model": "gpt-4o-mini",
            "max_output_tokens": 8192,
            "reasoning_effort": "high",
            "stream": True,
            "retries": 3,
            "retry_seconds": 60,
            "timeout_seconds": 300.0,
            "prices": {"input": 0.15, "output": 0.60},
        }
        built = titles.build_title_model_config(http_cfg)
        self.assertIsNotNone(built)
        self.assertEqual(built["max_output_tokens"], 48)
        self.assertIsNone(built["reasoning_effort"])
        self.assertFalse(built["stream"])
        self.assertEqual(built["retries"], 0)
        self.assertIsNone(built["retry_seconds"])
        self.assertEqual(built["timeout_seconds"], 15.0)

        # 2. Non-HTTP / external-agent / ACP backend -> returns None (never spawns ACP session)
        self.assertIsNone(titles.build_title_model_config({"backend": "acp", "model": "claude-code"}))
        self.assertIsNone(titles.build_title_model_config({"backend": "external_agent", "model": "codex"}))

        # 3. Real one-shot ChatModel execution via transport + real spending.Account.charge billing
        captured = {}

        def stub_transport(url, headers, payload, timeout):
            captured["url"] = url
            captured["payload"] = payload
            captured["timeout"] = timeout
            return {
                "choices": [{"message": {"content": '"Optimize SQL Index"'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 6, "total_tokens": 48},
            }

        account = self.identity.account()
        before_calls = account.day()["calls"]
        raw = titles.complete_title_from_config(
            http_cfg,
            "Please help me optimize slow SQL queries",
            account=account,
            chat="chat-billing",
            transport=stub_transport,
        )
        self.assertEqual(titles.clean_title(raw or ""), "Optimize SQL Index")
        self.assertEqual(captured["payload"]["max_tokens"], 48)
        self.assertNotIn("stream", captured["payload"])
        self.assertNotIn("reasoning_effort", captured["payload"])
        self.assertEqual(captured["timeout"], 15.0)
        self.assertEqual(account.day()["calls"], before_calls + 1)

        # 4. Life._maybe_auto_title NEVER calls shared self._model(chat) on ACP/non-HTTP backend
        shared_model = _FakeModel()
        life = Life(
            self.identity,
            model=lambda *a, **k: shared_model,
            model_config=lambda name=None: {"backend": "acp", "model": "claude-code"},
        )
        chat_acp = life.chats.new("新对话")
        self.assertEqual(life.chats.meta(chat_acp)["title_source"], "default")
        self.assertTrue(life._maybe_auto_title(chat_acp, "请帮我优化数据库索引性能"))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and life.chats.meta(chat_acp)["title_source"] == "default":
            time.sleep(0.02)
        self.assertEqual(life.chats.meta(chat_acp)["title"], "优化数据库索引性能")
        self.assertEqual(life.chats.meta(chat_acp)["title_source"], "auto")
        self.assertEqual(shared_model.calls, 0, "shared chat model must NEVER be called for auto-title")

    def test_auto_title_ui_defaults_lifecycle_race_guard_and_sse(self):
        self.assertEqual(titles.fallback_title('"Please help me fix the login timeout bug"'), "fix the login timeout bug")
        self.assertEqual(titles.fallback_title("请帮我优化数据库索引性能"), "优化数据库索引性能")
        self.assertEqual(titles.clean_title('Title: "Fix KaTeX Rendering."'), "Fix KaTeX Rendering")

        life = Life(self.identity, model=lambda *a, **k: _FakeModel())
        life.alive = True

        # UI-created default titles (EN, ZH, and explicit title_source="default" via agent_host.new_chat)
        c_en = life.chats.new("New conversation")
        c_zh = life.chats.new("新对话")
        self.assertEqual(life.chats.meta(c_en)["title_source"], "default")
        self.assertEqual(life.chats.meta(c_zh)["title_source"], "default")

        fake_srv = SimpleNamespace(background={"agent": SimpleNamespace(life=lambda ident: life)})
        with mock.patch.object(agent_host, "_identity", lambda body: self.identity):
            created = agent_host.new_chat(fake_srv, {"identity": "default", "title": "Untitled", "title_source": "default"})
        self.assertEqual(life.chats.meta(created["chat"])["title_source"], "default")

        calls = []
        gate = threading.Event()
        gate.set()

        def model_title(seed):
            calls.append(seed)
            gate.wait(timeout=3.0)
            return '"Fix Login Timeout"'

        life.title_model_fn = model_title
        try:
            chat_id = life.chats.new("New conversation")
            self.assertEqual(life.chats.meta(chat_id)["title_source"], "default")

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
                    while len(sse_events) < 3:
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
            self.assertEqual(life.chats.meta(race_chat)["title"], "My Manual Name")
            self.assertEqual(life.chats.meta(race_chat)["title_source"], "user")
            self.assertFalse(life.chats.set_auto_title(race_chat, "Late Auto Title"))
        finally:
            life.alive = False
            life.chats.notify()
            srv.shutdown()
            srv.server_close()

    # ── (c) Overview aggregate endpoint against REAL Life.context(), Life.intend(), sessions & tasks ──

    def test_overview_endpoint_real_life_contracts_git_and_non_git(self):
        life = Life(self.identity, model=lambda *a, **k: _FakeModel())

        # 1. Non-git workspace folder
        plain_dir = self.root / "plain_workspace"
        plain_dir.mkdir()
        (plain_dir / "notes.txt").write_text("hello", encoding="utf-8")
        non_git_chat = life.chats.new("Plain Chat")
        life.chats.update(non_git_chat, place="folder-plain")
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

        git_chat = life.chats.new("Git Chat")
        life.chats.update(git_chat, place="folder-git")
        art_dir = life.chats.folder(git_chat) / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "implementation_plan.md").write_text(
            "# Upgrade Plan\n\n- [x] Backend endpoints\n- [ ] Frontend wiring\n",
            encoding="utf-8",
        )
        place_git = SimpleNamespace(kind="folder", row={"kind": "folder", "id": "folder-git", "title": "git_workspace", "folder": str(git_dir)})
        life.places = {"folder-plain": place_plain, "folder-git": place_git}

        # Populate REAL Life.intend() (writes `what` into `life.intentions`)
        res_intend = life.intend(git_chat, {"what": "Verify headless browser layout", "in_minutes": 15})
        self.assertIn("intended", res_intend)

        # Populate REAL session state for Life.context() (`input_tokens`, `window`) + pending task (`pending`)
        life.sessions[git_chat] = SimpleNamespace(
            state={
                "context": {"input_tokens": 18400, "output_tokens": 920, "window": 128000, "model": "gpt-4o"},
                "messages": [{"role": "user", "content": "hi"}],
                "pending": {"run": "run-live-1", "goal": "Audit CSS and KaTeX"},
            }
        )

        # Verify REAL Life.context() contract directly
        real_ctx = life.context(git_chat)
        self.assertEqual(real_ctx["input_tokens"], 18400)
        self.assertEqual(real_ctx["window"], 128000)

        fake_convs = SimpleNamespace(
            sessions=lambda: [
                {"id": "sess-active-1", "title": "Active host session", "status": "RUNNING"},
                {"id": "sess-ended-1", "title": "Finished host session", "status": "ENDED"},
            ]
        )
        server = SimpleNamespace(
            background={"agent": SimpleNamespace(life=lambda ident: life)},
            conversations=fake_convs,
        )

        with mock.patch.object(overview_mod, "_cached_prs", return_value=[]):
            snap_plain = app_host.overview(server, {"identity": "default", "chat": non_git_chat})
            self.assertFalse(snap_plain["workspace"]["is_git"])
            self.assertEqual(snap_plain["workspace"]["dirty_count"], 0)
            self.assertEqual(snap_plain["pull_requests"], [])
            self.assertEqual(snap_plain["artifacts"], [])
            plain_tools = {t["id"]: t for t in snap_plain["tools"]}
            self.assertFalse(plain_tools["changes"]["available"])
            self.assertTrue(plain_tools["files"]["available"])

            snap_git = app_host.overview(server, {"identity": "default", "chat": git_chat})
            self.assertTrue(snap_git["workspace"]["is_git"])
            self.assertEqual(snap_git["workspace"]["branch"], "main")
            self.assertGreaterEqual(snap_git["workspace"]["dirty_count"], 1)
            self.assertEqual(len(snap_git["artifacts"]), 1)
            self.assertEqual(snap_git["artifacts"][0]["name"], "implementation_plan.md")

            # REAL Life.context() -> used/limit/model; unset mode stays None (not hardcoded "auto")
            self.assertEqual(snap_git["context"]["used"], 18400)
            self.assertEqual(snap_git["context"]["limit"], 128000)
            self.assertEqual(snap_git["context"]["model"], "gpt-4o")
            self.assertIsNone(snap_plain["context"]["mode"])
            self.assertIsNone(snap_git["context"]["mode"])
            life.chat_change(git_chat, "mode", mode="full")
            snap_git_full = app_host.overview(server, {"identity": "default", "chat": git_chat})
            self.assertEqual(snap_git_full["context"]["mode"], "full")

            # REAL Life.intend() (`what`) + checklist goals
            goal_texts = [g["text"] for g in snap_git["goals"]]
            self.assertIn("Verify headless browser layout", goal_texts)
            self.assertIn("Backend endpoints", goal_texts)
            self.assertIn("Frontend wiring", goal_texts)

            # REAL session pending task + active host session (ended session excluded)
            task_ids = {t["id"]: t for t in snap_git["background_tasks"]}
            self.assertIn("run-live-1", task_ids)
            self.assertEqual(task_ids["run-live-1"]["title"], "Audit CSS and KaTeX")
            self.assertIn("sess-active-1", task_ids)
            self.assertNotIn("sess-ended-1", task_ids)

            tool_ids = [t["id"] for t in snap_git["tools"]]
            self.assertEqual(tool_ids[:4], ["changes", "files", "terminal", "plugins"])

    def test_auto_title_inline_model_title_upgrades_acp_fallback_and_respects_user_rename(self):
        """ACP/external-agent chats get real model-generated titles from Turn-1 JSON with zero extra calls."""
        class _AcpLikeModel:
            def __init__(self, payloads):
                self.payloads = list(payloads)
                self.systems = []

            def complete(self, system, messages, **kwargs):
                self.systems.append(system)
                return ChatReply(text=json.dumps(self.payloads.pop(0), ensure_ascii=False), usage={})

        # 1. ACP chat: fallback runs first (title_fallback=True), Life.notes() prompts for chat_title,
        #    and Turn-1 JSON upgrades the title cleanly before Turn-2 stops asking for chat_title.
        model = _AcpLikeModel([
            {"action": "reply", "text": "已定位原因。", "chat_title": "《排查 ACP 对话自动标题》"},
            {"action": "reply", "text": "第二轮回复。", "chat_title": "不应该覆盖的标题"},
        ])
        life = Life(
            self.identity,
            model=lambda *a, **k: model,
            tasks=lambda row=None: None,
            model_config=lambda name=None: {"backend": "acp", "model": "antigravity"},
        )
        chat_id = life.chats.new("新对话")
        self.assertTrue(life._maybe_auto_title(chat_id, "请帮我看看为什么 ACP 后端对话没有模型自动取名"))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and life.chats.meta(chat_id)["title_source"] == "default":
            time.sleep(0.02)
        meta_fb = life.chats.meta(chat_id)
        self.assertEqual(meta_fb["title_source"], "auto")
        self.assertTrue(meta_fb.get("title_fallback"))
        self.assertIn("chat_title", life.notes(chat_id))

        sess = life._session(chat_id)
        sess.turn("请帮我看看为什么 ACP 后端对话没有模型自动取名")
        meta_model = life.chats.meta(chat_id)
        self.assertEqual(meta_model["title"], "排查 ACP 对话自动标题")
        self.assertEqual(meta_model["title_source"], "auto")
        self.assertFalse(meta_model.get("title_fallback"))
        self.assertNotIn("chat_title", life.notes(chat_id))

        # Turn 2 must NOT overwrite the model-generated title even if the model repeats chat_title
        sess.turn("继续")
        self.assertEqual(life.chats.meta(chat_id)["title"], "排查 ACP 对话自动标题")

        # 2. Manual user rename wins over Turn-1 inline chat_title
        manual_model = _AcpLikeModel([{"action": "reply", "text": "好的", "chat_title": "Late Model Title"}])
        life2 = Life(self.identity, model=lambda *a, **k: manual_model, tasks=lambda row=None: None)
        chat_manual = life2.chats.new("New conversation")
        life2.chats.rename(chat_manual, "我的手动标题")
        self.assertNotIn("chat_title", life2.notes(chat_manual))
        life2._session(chat_manual).turn("hello")
        self.assertEqual(life2.chats.meta(chat_manual)["title"], "我的手动标题")
        self.assertEqual(life2.chats.meta(chat_manual)["title_source"], "user")

        # 3. write_artifact's own `title` field must NEVER be mistaken for chat title
        art_model = _AcpLikeModel([
            {"action": "write_artifact", "name": "plan.md", "title": "Artifact Document Heading", "content": "# Plan\nbody"},
            {"action": "reply", "text": "方案写好了。"},
        ])
        life3 = Life(self.identity, model=lambda *a, **k: art_model, tasks=lambda row=None: None)
        chat_art = life3.chats.new("新对话")
        life3._session(chat_art).turn("写一个重构方案")
        self.assertEqual(life3.chats.meta(chat_art)["title"], "新对话")
        self.assertEqual(life3.chats.meta(chat_art)["title_source"], "default")

    def test_sidebar_filter_ssh_list_and_docked_overview_ui(self):
        """Sidebar filter menu, vertical SSH host list, and desktop-docked Overview are wired cleanly."""
        root = Path(__file__).resolve().parents[1]
        static = root / "packages" / "app" / "ui" / "static"
        sidebar_js = (static / "js" / "sidebar.js").read_text(encoding="utf-8")
        composer_js = (static / "js" / "composer.js").read_text(encoding="utf-8")
        panel_js = (static / "js" / "panel.js").read_text(encoding="utf-8")
        css = (static / "app.css").read_text(encoding="utf-8")

        # 1. Sidebar filter menu & sort/group/mark-read actions
        self.assertIn("chats-filter", sidebar_js)
        self.assertIn("Mark All as Read", sidebar_js)
        self.assertIn("Sort Conversations", sidebar_js)
        self.assertIn("Group By", sidebar_js)

        # 2. SSH dialog uses vertical scrollable list (.ssh-list / .ssh-row), not wrapped preset pill cloud
        self.assertIn("class=\"ssh-list\"", composer_js)
        self.assertIn("class=\"ssh-row", composer_js)
        self.assertNotIn("presets ssh-hosts", composer_js)
        self.assertIn(".ssh-list {", css)

        # 3. Dual-state Right Side Panel vs Floating Overview (>= 1040px)
        self.assertIn("(min-width: 1040px)", panel_js)
        self.assertIn("overview.card", panel_js)
        self.assertIn("sidePanelOpen", panel_js)
        self.assertIn("@media (max-width: 1039px)", css)
        self.assertNotIn("border-radius: 0;", css.splitlines()[15])

    def test_sse_stream_pushes_idle_busy_and_queue_after_turn_finishes(self):
        """SSE /api/agent/stream must push busy=False and queue.running=None as soon as Life._over finishes."""
        life = Life(self.identity, model=lambda *a, **k: _FakeModel("Done!"), tasks=lambda row=None: None)
        life.start()
        srv, port = _start_server(self.root / "runs", {"default": life})
        events = []
        ready = threading.Event()
        idle_after_reply = threading.Event()

        def _read_sse():
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
            try:
                conn.request("GET", "/api/agent/stream?identity=default&chat=main&after=0",
                             headers={"X-Session-API-Key": "test-token"})
                resp = conn.getresponse()
                seen_reply = False
                while True:
                    line = resp.readline().decode("utf-8", errors="replace")
                    if not line:
                        break
                    if line.startswith("data: "):
                        ev = json.loads(line[6:])
                        events.append(ev)
                        if len(events) == 1:
                            ready.set()
                        if any(r.get("event") == "reply" for r in ev.get("records") or ()):
                            seen_reply = True
                        if seen_reply and ev.get("busy") is False and (ev.get("queue") or {}).get("running") is None:
                            idle_after_reply.set()
                            break
            except Exception:
                pass
            finally:
                conn.close()

        t = threading.Thread(target=_read_sse, daemon=True)
        t.start()
        try:
            self.assertTrue(ready.wait(3.0), "initial SSE snapshot not received")
            life.say("main", "hello")
            self.assertTrue(idle_after_reply.wait(5.0), f"SSE never pushed idle state after reply; events={events}")
        finally:
            life.close()
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2.0)

    def test_context_mention_resolver_and_picker_ui(self):
        """Structured @mentions (@rule:, @memory:, @chat:, @artifact:, @file:, @skill:) resolve into
        model context safely without mutating stored messages, and the UI opens a structured Browse menu."""
        from harness import paths as harness_paths

        class _CapturingModel:
            def __init__(self):
                self.seen_messages = []

            def complete(self, system, messages, **kwargs):
                self.seen_messages.append(messages)
                return ChatReply(text=json.dumps({"action": "reply", "text": "Got all context."}), usage={})

        global_home = self.root / "global_home"
        global_home.mkdir()
        (global_home / "AGENTS.md").write_text("GLOBAL_RULE_MARKER: always verify tests.", encoding="utf-8")

        proj = self.root / "demo_proj"
        (proj / "src").mkdir(parents=True)
        (proj / "AGENTS.md").write_text("PROJECT_RULE_MARKER: keep core stdlib only.", encoding="utf-8")
        (proj / "src" / "app.py").write_text("def greet():\n    return 'PROJECT_FILE_MARKER'\n", encoding="utf-8")
        (proj / "bin.dat").write_bytes(b"\x00\x01\x02BINARY")
        (self.root / "secret.txt").write_text("OUTSIDE_SECRET_DO_NOT_LEAK", encoding="utf-8")

        (self.identity.directory / "SOUL.md").write_text("PERSONA_SOUL_MARKER: be direct.", encoding="utf-8")
        (self.identity.directory / "MEMORY.md").write_text("MEMORY_INDEX_MARKER: user prefers Chinese.", encoding="utf-8")
        mem_dir = self.identity.directory / "memory"
        mem_dir.mkdir(exist_ok=True)
        (mem_dir / "style.md").write_text("---\nkey: \"style\"\n---\nMEMORY_ENTRY_MARKER: concise bullets.", encoding="utf-8")

        skill_dir = self.identity.directory / "skills" / "deploy_helper"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("---\nname: deploy_helper\ndescription: deploy\n---\nSKILL_BODY_MARKER: run check-pr.", encoding="utf-8")

        cap_model = _CapturingModel()
        life = Life(self.identity, model=lambda *a, **k: cap_model, tasks=lambda row=None: None)
        place_proj = SimpleNamespace(
            id="folder-demo",
            kind="folder",
            online=True,
            row={"kind": "folder", "id": "folder-demo", "title": "demo_proj", "folder": str(proj)},
        )
        life.places = {"folder-demo": place_proj}

        other_chat = life.chats.new("Prior Architecture Chat")
        life.chats.record(other_chat, "user", text="PRIOR_CHAT_USER_MARKER: why sqlite?")
        life.chats.record(other_chat, "reply", text="PRIOR_CHAT_REPLY_MARKER: zero-dep local persistence.")

        chat_id = life.chats.new("Mention Test Chat")
        life.chats.update(chat_id, place="folder-demo")
        art_dir = life.chats.folder(chat_id) / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "implementation_plan.md").write_text("# Plan\nARTIFACT_MARKER: ship picker.", encoding="utf-8")

        with mock.patch.object(harness_paths, "home", lambda: global_home):
            # 1. Resolve rules, memory, artifact, chat, file, folder, binary, and skill (including Chinese punctuation)
            ctx1 = life.resolve_mentions(
                chat_id,
                f"请参考 @rule:global/AGENTS.md，@rule:project/AGENTS.md @rule:persona/SOUL.md @memory:style.md @artifact:implementation_plan.md",
            )
            self.assertIn("GLOBAL_RULE_MARKER", ctx1)
            self.assertIn("PROJECT_RULE_MARKER", ctx1)
            self.assertIn("PERSONA_SOUL_MARKER", ctx1)
            self.assertIn("MEMORY_ENTRY_MARKER", ctx1)
            self.assertIn("ARTIFACT_MARKER", ctx1)

            ctx2 = life.resolve_mentions(
                chat_id,
                f"结合 @chat:{other_chat} @file:src/app.py @file:src @file:bin.dat @skill:deploy_helper",
            )
            self.assertIn("Prior Architecture Chat", ctx2)
            self.assertIn("PRIOR_CHAT_USER_MARKER", ctx2)
            self.assertIn("PRIOR_CHAT_REPLY_MARKER", ctx2)
            self.assertIn("PROJECT_FILE_MARKER", ctx2)
            self.assertIn("app.py", ctx2)
            self.assertIn("binary file", ctx2)
            self.assertIn("SKILL_BODY_MARKER", ctx2)

            ctx_mem_idx = life.resolve_mentions(chat_id, "看下 @memory:MEMORY.md")
            self.assertIn("MEMORY_INDEX_MARKER", ctx_mem_idx)

            # 2. Traversal / outside-root / malformed mentions must NEVER leak or raise
            bad_ctx = life.resolve_mentions(
                chat_id,
                "@file:../secret.txt @file:./../secret.txt @file:/ @file:/etc/passwd "
                "@memory:../SOUL.md @artifact:../state.json @rule:project/secret.txt",
            )
            self.assertEqual(bad_ctx, "")
            self.assertNotIn("OUTSIDE_SECRET_DO_NOT_LEAK", bad_ctx)

            # 3. Full Session.turn() injects resolved mention context into model payload while
            #    keeping stored state["messages"] and chat timeline clean.
            sess = life._session(chat_id)
            raw_user = "按 @rule:project/AGENTS.md 检查 @file:src/app.py"
            sess.turn(raw_user)
            self.assertEqual(len(cap_model.seen_messages), 1)
            sent_user = [m for m in cap_model.seen_messages[0] if m.get("role") == "user"][-1]
            self.assertIn("Referenced context (from @mentions", sent_user["content"])
            self.assertIn("PROJECT_RULE_MARKER", sent_user["content"])
            self.assertIn("PROJECT_FILE_MARKER", sent_user["content"])
            stored_user = next(m for m in sess.state["messages"] if m.get("role") == "user")
            self.assertEqual(stored_user["content"], raw_user)

        # 4. Frontend @ Context Mention Picker structure (Antigravity-style Browse menu, not raw file dump)
        root = Path(__file__).resolve().parents[1]
        static = root / "packages" / "app" / "ui" / "static"
        composer_js = (static / "js" / "composer.js").read_text(encoding="utf-8")
        panel_js = (static / "js" / "panel.js").read_text(encoding="utf-8")
        css = (static / "app.css").read_text(encoding="utf-8")
        self.assertIn("browseMenuItems", composer_js)
        self.assertIn("drill: '@rule:'", composer_js)
        self.assertIn("drill: '@chat:'", composer_js)
        self.assertIn("drill: '@memory:'", composer_js)
        self.assertIn("drill: '@artifact:'", composer_js)
        self.assertIn("drill: '@file:'", composer_js)
        self.assertIn("loadScopedMention", composer_js)
        self.assertIn("@file:${fv.dataset.path}", panel_js)
        self.assertIn(".ac-head {", css)
        self.assertIn(".ac-item.ac-back {", css)

    def test_workbench_first_principles_ssh_overview_search_and_tui_parity(self):
        """End-to-end verification of Layers 0–4: SSH overview/search parity, PR limit & diff stats,
        Row-1 Titlebar & Z-index stack, inset Overview card + bottom terminal drawer, 6-tab Customizations,
        responsive Calendar, and Terminal TUI parity (4-level mode, 3-opt approvals, @mentions, attachments)."""
        from types import SimpleNamespace
        from harness_app import host as app_host, overview as app_overview
        from harness.tui import agent as tui_agent
        from harness.tui.chat import Completions
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        # 1. Layer 1: SSH project recognized in overview() and place_search()
        life = Life(self.identity, model=lambda *a, **k: _FakeModel("ok"), tasks=lambda row=None: None)
        ssh_place = SimpleNamespace(kind="ssh", row={"id": "ssh-gpu", "kind": "ssh", "title": "ssh · gpu-box",
                                                     "target": "dev@gpu-box", "folder": "~/repo"})
        life.places["ssh-gpu"] = ssh_place
        ssh_chat = life.chats.new("SSH Session")
        life.chats.update(ssh_chat, place="ssh-gpu")
        srv = SimpleNamespace(lives={"default": life}, conversations=None)

        with mock.patch.object(app_host, "_identity_row", return_value={"id": "default", "folder": str(self.identity.directory)}), \
                mock.patch.object(app_host, "_life", return_value=life):
            snap = app_overview.overview(srv, {"identity": "default", "chat": ssh_chat})
            self.assertTrue(snap["workspace"]["ssh"])
            self.assertEqual(snap["workspace"]["project"], "gpu-box")
            self.assertIn("ssh://dev@gpu-box:~/repo", snap["workspace"]["folder"])
            tools = {t["id"]: t for t in snap["tools"]}
            self.assertTrue(tools["files"]["available"])
            self.assertTrue(tools["terminal"]["available"])
            self.assertFalse(tools["changes"]["available"])

            fake_proc = SimpleNamespace(returncode=0, stdout="d\t./src\nf\t./src/train.py\nf\t./README.md\n", stderr="")
            with mock.patch.object(app_host, "_ssh_exec", return_value=fake_proc):
                found = app_host.place_search(srv, {"identity": "default", "chat": ssh_chat, "q": "train"})
            self.assertTrue(found["ssh"])
            self.assertEqual([m["path"] for m in found["matches"]], ["src/train.py"])

        # 2. Layer 0/2/3: Row-1 Titlebar, monotonic Z-index tokens, inset Overview card, bottom terminal, 6-tab Customizations
        root = Path(__file__).resolve().parents[1]
        static = root / "packages" / "app" / "ui" / "static"
        tokens_css = (static / "tokens.css").read_text(encoding="utf-8")
        app_css = (static / "app.css").read_text(encoding="utf-8")
        titlebar_js = (static / "js" / "titlebar.js").read_text(encoding="utf-8")
        panel_js = (static / "js" / "panel.js").read_text(encoding="utf-8")
        cust_js = (static / "js" / "customizations.js").read_text(encoding="utf-8")
        cal_js = (static / "js" / "calendar.js").read_text(encoding="utf-8")
        chat_js = (static / "js" / "chat.js").read_text(encoding="utf-8")

        for tok in ("--z-titlebar: 15", "--z-settings: 20", "--z-drawer: 30", "--z-palette: 40",
                    "--z-dialog: 50", "--z-popover: 60", "--z-tooltip: 70", "--z-toast: 80"):
            self.assertIn(tok, tokens_css)
        self.assertIn(".pg-titlebar", titlebar_js)
        self.assertNotIn(".pg-win {", app_css)
        self.assertIn(".pg-term-drawer", app_css)
        self.assertIn("ov-card", panel_js)
        self.assertNotIn('class="kv"', panel_js)  # redundant Workspace KV table removed from Overview
        self.assertNotIn("ctx-meter", panel_js)
        self.assertIn("['memory', '记忆', 'Memory'", cust_js)
        self.assertIn("guardUnsaved", cust_js)
        self.assertIn("pc-views-sel", cal_js)
        self.assertIn("mention-pill", chat_js)
        self.assertNotIn('data-act="settings" data-arg="connectors"', chat_js)
        self.assertNotIn('data-act="settings" data-arg="learned"', chat_js)

        # 3. Layer 4: Terminal TUI parity (3-opt approvals, scope=session, artifact/task_step lines, @mentions, attachments)
        ask = tui_agent.approval_ask({"code": "A9", "what": "run tests", "verb": "shell"})
        self.assertEqual([o[0] for o in ask["options"]], ["once", "session", None])

        posted = []

        class _StubHost:
            def post(self, path, body):
                posted.append((path, body))
                if path == "/api/agent/attach":
                    return {"id": "att-1", "name": body["name"]}
                return {"ok": True}

            def get(self, path):
                return {"records": []}

        ac = tui_agent.AgentChat(_StubHost(), {"id": "default", "name": "Default"}, "c1", "New conversation")
        ac.pending["A9"] = {"code": "A9"}
        ac.confirm(True, request_id="A9", remember="session")
        self.assertEqual(posted[-1][0], "/api/agent/approvals")
        self.assertEqual(posted[-1][1]["scope"], "session")

        sample = self.root / "note.txt"
        sample.write_text("hello attach", encoding="utf-8")
        ac.send("see attached", [str(sample)])
        self.assertTrue(any(p == "/api/agent/attach" for p, _ in posted))
        say_body = next(b for p, b in posted if p == "/api/agent/say")
        self.assertEqual(say_body["files"], ["att-1"])

        art_lines = tui_agent.lines({"event": "artifact", "name": "plan.md", "title": "My Plan", "request_approval": True})
        self.assertTrue(any("My Plan" in t and "awaiting approval" in t for t, _ in art_lines))
        step_lines = tui_agent.lines({"event": "task_step", "kind": "cell", "number": 2, "code": "print(1)", "status": "ok"})
        self.assertTrue(any("#2 print(1)" in t for t, _ in step_lines))

        comp = [c.text for c in Completions().get_completions(Document("check @"), CompleteEvent())]
        for pref in ("rule:", "memory:", "chat:", "artifact:", "file:", "skill:"):
            self.assertIn(pref, comp)

        # 4. Full Context Breakdown Inspector (backend life.context() + frontend statusbar.js)
        mem_dir = self.identity.directory / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / "pref.md").write_text("Prefer concise output.", encoding="utf-8")
        ctx_data = life.context(ssh_chat)
        self.assertIn("breakdown", ctx_data)
        self.assertIn("details", ctx_data)
        self.assertGreater(ctx_data["breakdown"]["system_prompt"], 0)
        self.assertGreater(ctx_data["breakdown"]["memory_files"], 0)
        self.assertTrue(any(it["name"] == "memory/pref.md" for it in ctx_data["details"]["memory_files"]))
        sb_js = (static / "js" / "statusbar.js").read_text(encoding="utf-8")
        self.assertIn("openContextInspector", sb_js)
        self.assertIn('data-act="ctx-inspect"', sb_js)
        self.assertNotIn('data-act="ctx-compact"', sb_js)

        # 5. Untracked subdirectories enumerate real files (-uall), never phantom "?? dir/" with empty diff
        import subprocess
        git_repo = self.root / "untracked_dir_repo"
        git_repo.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
            subprocess.run(["git", *args], cwd=git_repo, check=True)
        (git_repo / "init.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=git_repo, check=True)
        (git_repo / "blog" / "post").mkdir(parents=True)
        (git_repo / "blog" / "post" / "a.html").write_text("<h1>Hi</h1>\n<p>Body</p>\n", encoding="utf-8")
        (git_repo / "blog" / "post" / "b.css").write_text("body { margin: 0; }\n", encoding="utf-8")
        gi = app_overview._git_info(git_repo)
        self.assertEqual(gi["dirty_count"], 2)
        self.assertEqual(gi["diff_added"], 3)
        st_map = app_host._git_status_map(git_repo)
        self.assertEqual(sorted(st_map.keys()), ["blog/post/a.html", "blog/post/b.css"])
