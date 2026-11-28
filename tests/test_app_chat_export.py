"""Offline contract tests for complete-history chat Markdown export.

Covers:
1. Server history contract (`Chats.read` and `GET /api/agent/chat?after=0&all=1`) for chats
   exceeding both the 500-record default poll window and the 800-record front-end cache.
2. End-to-end `packages/app/ui/static/js/export.js` execution against the live local HTTP
   server: earliest and latest text are both exported, and HTTP errors do not claim success.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest import TestCase, mock

import helpers  # noqa: F401

sys.path.insert(0, str(helpers.ROOT / "packages" / "app"))
sys.path.insert(0, str(helpers.ROOT / "packages" / "agent"))

from harness.host.http import Server  # noqa: E402
from harness_agent import host as agent_host  # noqa: E402
from harness_agent.chats import Chats  # noqa: E402
from harness_agent.state import Identity  # noqa: E402
from harness_app import host as app_host  # noqa: E402


def _node_binary() -> str | None:
    return os.environ.get("HARNESS_TEST_NODE") or shutil.which("node")


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


class AppChatExportTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.identity = Identity("default", root=self.root / "agents")
        self.chats = Chats(self.identity)
        self.chat_id = self.chats.new("Long History Export")

        # Write 950 records (> 500 server poll default AND > 800 front-end KEPT cache)
        # directly to events.jsonl for fast deterministic setup.
        folder = self.chats.folder(self.chat_id)
        folder.mkdir(parents=True, exist_ok=True)
        lines = []
        for seq in range(1, 951):
            if seq == 1:
                row = {"seq": seq, "event": "user", "time": 1000.0 + seq, "text": "EARLIEST_EXPORT_MARKER_SEQ_1"}
            elif seq == 950:
                row = {"seq": seq, "event": "reply", "time": 1000.0 + seq, "text": "LATEST_EXPORT_MARKER_SEQ_950"}
            elif seq % 2 == 1:
                row = {"seq": seq, "event": "user", "time": 1000.0 + seq, "text": f"turn user {seq}"}
            else:
                row = {"seq": seq, "event": "reply", "time": 1000.0 + seq, "text": f"turn reply {seq}"}
            lines.append(json.dumps(row, ensure_ascii=False))
        (folder / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.fake_life = SimpleNamespace(
            chats=self.chats,
            identity=self.identity,
            live={},
            context=lambda _c: {},
        )
        self.patch_ident = mock.patch.object(agent_host, "_identity", lambda _body: self.identity)
        self.patch_ident.start()

    def tearDown(self):
        self.patch_ident.stop()
        self.tmp.cleanup()

    def test_chats_read_complete_history_vs_default_tail(self):
        tail = self.chats.read(self.chat_id, after=0)
        self.assertEqual(len(tail), 500)
        self.assertEqual(tail[0]["seq"], 451)
        self.assertEqual(tail[-1]["seq"], 950)

        for full in (
            self.chats.read(self.chat_id, after=0, limit=None),
            self.chats.read(self.chat_id, after=0, limit=0),
        ):
            self.assertEqual(len(full), 950)
            self.assertEqual(full[0]["seq"], 1)
            self.assertEqual(full[0]["text"], "EARLIEST_EXPORT_MARKER_SEQ_1")
            self.assertEqual(full[-1]["seq"], 950)
            self.assertEqual(full[-1]["text"], "LATEST_EXPORT_MARKER_SEQ_950")

    def test_agent_chat_http_contract_and_end_to_end_js_export(self):
        srv = Server(("127.0.0.1", 0), self.root / "runs", token="test-token")
        srv.background = {"agent": SimpleNamespace(life=lambda _ident: self.fake_life)}
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        port = srv.server_address[1]
        try:
            # 1. Default poll stays tail-bounded to 500 records and omits `complete`
            st_def, _, body_def = _http_get(port, f"/api/agent/chat?identity=default&chat={self.chat_id}&after=0")
            self.assertEqual(st_def, 200)
            data_def = json.loads(body_def)
            self.assertEqual(len(data_def["records"]), 500)
            self.assertNotIn("complete", data_def)
            self.assertNotEqual(data_def["records"][0]["seq"], 1)

            # 2. Full history via all=1 and limit=0 returns all 950 records with complete=True
            for suffix in ("after=0&all=1", "after=0&limit=0"):
                st_all, _, body_all = _http_get(port, f"/api/agent/chat?identity=default&chat={self.chat_id}&{suffix}")
                self.assertEqual(st_all, 200)
                data_all = json.loads(body_all)
                self.assertTrue(data_all.get("complete"))
                self.assertEqual(len(data_all["records"]), 950)
                self.assertEqual(data_all["records"][0]["text"], "EARLIEST_EXPORT_MARKER_SEQ_1")
                self.assertEqual(data_all["records"][-1]["text"], "LATEST_EXPORT_MARKER_SEQ_950")

            # 3. Partial slice (after > 0) must NOT claim complete=True
            st_part, _, body_part = _http_get(port, f"/api/agent/chat?identity=default&chat={self.chat_id}&after=10&all=1")
            self.assertEqual(st_part, 200)
            data_part = json.loads(body_part)
            self.assertEqual(len(data_part["records"]), 940)
            self.assertNotIn("complete", data_part)

            # 4. Negative limit is rejected
            st_bad, _, _ = _http_get(port, f"/api/agent/chat?identity=default&chat={self.chat_id}&after=0&limit=-1")
            self.assertEqual(st_bad, 400)

            # 5. Helper script is served as static JS
            st_js, hdrs_js, body_js = _http_get(port, "/static/app/js/export.js", token="")
            self.assertEqual(st_js, 200)
            self.assertIn("text/javascript", {k.lower(): v for k, v in hdrs_js.items()}.get("content-type", ""))
            self.assertIn(b"exportChatMarkdown", body_js)

            # 6. End-to-end JS helper run against this live local HTTP server
            node = _node_binary()
            self.assertIsNotNone(node, "Node.js is required to validate export.js end-to-end")
            export_js_url = (helpers.ROOT / "packages" / "app" / "ui" / "static" / "js" / "export.js").resolve().as_uri()
            script = f"""
import assert from 'node:assert/strict'
import {{ exportChatMarkdown }} from {json.dumps(export_js_url)}

const base = 'http://127.0.0.1:{port}'
const chatId = {json.dumps(self.chat_id)}

async function fetchJson(url, token) {{
    const r = await fetch(url, {{ headers: token ? {{ 'X-Session-API-Key': token }} : {{}} }})
    const data = await r.json().catch(() => null)
    if (!r.ok) return {{ ok: false, status: r.status, error: (data && data.error) || r.statusText }}
    return {{ ok: true, data }}
}}

// Full export over HTTP includes earliest and latest text beyond 800-record cache
let downloaded = null
const toasts = []
const okRes = await exportChatMarkdown({{
    identity: 'default',
    chat: chatId,
    fetchHistory: async (identity, chat) => {{
        const got = await fetchJson(`${{base}}/api/agent/chat?identity=${{identity}}&chat=${{chat}}&after=0&all=1`, 'test-token')
        return got.ok ? got.data : null
    }},
    download: (md, filename) => {{ downloaded = {{ md, filename }} }},
    notify: (text, opts) => toasts.push({{ text, opts: opts || {{}} }}),
}})
assert.equal(okRes.ok, true)
assert.equal(okRes.count, 950)
assert.equal(downloaded.filename, 'Long_History_Export.md')
assert.ok(downloaded.md.includes('EARLIEST_EXPORT_MARKER_SEQ_1'))
assert.ok(downloaded.md.includes('LATEST_EXPORT_MARKER_SEQ_950'))
assert.ok(downloaded.md.indexOf('EARLIEST_EXPORT_MARKER_SEQ_1') < downloaded.md.indexOf('LATEST_EXPORT_MARKER_SEQ_950'))
assert.equal(toasts.length, 1)
assert.equal(toasts[0].opts.error, undefined)

// HTTP auth error (401) must NOT download or claim a successful full export
let errDownloaded = false
const errToasts = []
let lastErr = null
const errRes = await exportChatMarkdown({{
    identity: 'default',
    chat: chatId,
    fetchHistory: async (identity, chat) => {{
        const got = await fetchJson(`${{base}}/api/agent/chat?identity=${{identity}}&chat=${{chat}}&after=0&all=1`, 'wrong-token')
        if (!got.ok) {{ lastErr = got; return null }}
        return got.data
    }},
    lastError: () => lastErr,
    download: () => {{ errDownloaded = true }},
    notify: (text, opts) => errToasts.push({{ text, opts: opts || {{}} }}),
}})
assert.equal(errRes.ok, false)
assert.equal(errDownloaded, false)
assert.equal(errToasts.length, 1)
assert.equal(errToasts[0].opts.error, true)
assert.doesNotMatch(errToasts[0].text, /Exported conversation Markdown/)
"""
            proc = subprocess.run(
                [node, "--input-type=module", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, f"Node e2e export check failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2.0)

    def test_host_export_js_static_path_exists(self):
        self.assertTrue((app_host.STATIC / "js" / "export.js").is_file())


if __name__ == "__main__":
    import unittest

    unittest.main()
