"""Contract & invariant tests for the product-ready workspace capabilities:
- Auto permission defaults, session-scoped approval memory (credentials excluded), per-chat execution modes
- Interactive PTY terminal lifecycle (open, input, output, resize, close)
- File explorer tree/file/search/changes/revert + path traversal & binary guards
- Worktree status, clean merge, conflict refusal (no dirty MERGING state), discard
- Explorer-style Behavior Tree full() & edit() + Rules API (Global/Project/Persona)
- Real-time chat SSE stream notifier
"""
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

for pkg in ("agent", "app"):
    path = str(helpers.ROOT / "packages" / pkg)
    if path not in sys.path:
        sys.path.insert(0, path)

from harness import paths as harness_paths, settings  # noqa: E402
from harness.problems import Problem  # noqa: E402
from harness.runtime.safety import permissions  # noqa: E402
from harness_agent import approvals as agent_approvals, chats as agent_chats, places as agent_places, reactions  # noqa: E402
from harness_agent import host as agent_host  # noqa: E402
from harness_app import host as app_host, terminal  # noqa: E402


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", **flags,
    )


def _init_repo(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    _git(folder, "init", "-q")
    _git(folder, "config", "user.name", "Test")
    _git(folder, "config", "user.email", "test@example.com")
    (folder / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "util.js").write_text("export const x = 1\n", encoding="utf-8")
    _git(folder, "add", ".")
    _git(folder, "commit", "-qm", "initial")
    return folder


class DefaultsAndApprovalsTests(TestCase):
    def test_auto_mode_defaults(self):
        self.assertEqual(settings.SCHEMA["approvals"]["mode"].default, "auto")
        self.assertEqual(settings.SCHEMA["approvals"]["programs"].default, "allow")
        self.assertEqual(permissions.DEFAULT_LEVEL, "allow")

    def test_four_level_execution_modes_and_hard_safety_floor(self):
        from harness_agent.life import Life
        from harness_agent.state import Identity

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {"HARNESS_DATA": tmp.name, "HARNESS_HOME": tmp.name}):
            life = Life(Identity("default"))
            chat = life.chats.new("Mode test")
            life.levels[chat] = "owner"

            # 1. Plan mode refuses mutations & sends, allows read
            life.chat_change(chat, "mode", mode="plan")
            self.assertEqual(life.check(chat, "files.read", effect="read")[0], "allow")
            self.assertEqual(life.check(chat, "files.write", effect="change")[0], "refuse")
            self.assertEqual(life.check(chat, "git.push", effect="send")[0], "refuse")

            # 2. Ask mode requires approval for mutations & sends, allows read
            life.chat_change(chat, "mode", mode="ask")
            self.assertEqual(life.check(chat, "files.read", effect="read")[0], "allow")
            self.assertEqual(life.check(chat, "files.write", effect="change")[0], "approve")
            self.assertEqual(life.check(chat, "git.push", effect="send")[0], "approve")

            # 3. Auto mode allows workspace mutations, asks on high-risk sends
            life.chat_change(chat, "mode", mode="auto")
            self.assertEqual(life.check(chat, "files.write", effect="change")[0], "allow")
            self.assertEqual(life.check(chat, "git.push", effect="send")[0], "approve")

            # 4. Full Access allows owner sends without prompt, NEVER bypasses login/credentials or non-owner
            life.chat_change(chat, "mode", mode="full")
            self.assertEqual(life.check(chat, "git.push", effect="send")[0], "allow")
            self.assertEqual(life.check(chat, "auth.login", effect="credentials")[0], "refuse")
            life.levels[chat] = "other"
            self.assertEqual(life.check(chat, "git.push", effect="send")[0], "refuse")

    def test_checkpoint_snapshot_and_chat_rewind(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        repo = _init_repo(Path(tmp.name) / "repo")
        # Pre-existing modified tracked file and pre-existing untracked file before turn 2
        (repo / "app.py").write_text("def greet():\n    return 'v1'\n", encoding="utf-8")
        (repo / "keep.txt").write_text("keep me\n", encoding="utf-8")
        cp = agent_places.snapshot_folder(repo)
        self.assertIsNotNone(cp)

        # Agent mutates tracked file and creates a new untracked file during turn 2
        (repo / "app.py").write_text("def greet():\n    return 'v2-bad'\n", encoding="utf-8")
        (repo / "created_later.txt").write_text("temp\n", encoding="utf-8")

        identity = SimpleNamespace(directory=Path(tmp.name) / "id")
        chats = agent_chats.Chats(identity)
        chat = chats.new("Rewind test")
        folder = chats.folder(chat)
        (folder / "state.json").write_text(
            '{"schema": 1, "identity": "default", "messages": [{"role":"user","content":"m1"},{"role":"assistant","content":"r1"},{"role":"user","content":"m2"},{"role":"assistant","content":"r2"}], "summary": "", "pending": null}',
            encoding="utf-8",
        )
        chats.record(chat, "user", text="m1", msg_index=0)
        chats.record(chat, "reply", text="r1")
        u2 = chats.record(chat, "user", text="m2", msg_index=2, checkpoint=cp)
        chats.record(chat, "reply", text="r2")

        rw = chats.rewind(chat, u2["seq"])
        self.assertEqual(rw["text"], "m2")
        self.assertEqual([r["event"] for r in rw["records"]], ["user", "reply"])
        self.assertEqual(len(chats.read(chat)), 2)
        import json as _json
        state = _json.loads((folder / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["messages"]), 2)

        restored = agent_places.restore_folder(repo, rw["checkpoint"])
        self.assertTrue(restored)
        self.assertIn("'v1'", (repo / "app.py").read_text(encoding="utf-8"))
        self.assertTrue((repo / "keep.txt").is_file())
        self.assertFalse((repo / "created_later.txt").exists())

    def test_session_scoped_approval_remembers_normal_verb_but_never_credentials(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        recorded = []
        chats = SimpleNamespace(record=lambda chat, ev, **k: recorded.append((chat, ev, k)))
        life = SimpleNamespace(
            identity=SimpleNamespace(id="default", name="Dev", directory=Path(tmp.name)),
            chats=chats,
            clock=time.time,
            closing=threading.Event(),
            stopping=lambda _chat: False,
            tell=lambda *a, **k: None,
            places={},
        )
        mgr = agent_approvals.Approvals(life)

        # 1. First ask blocks until answered with scope="session"
        result = {}
        def ask_once():
            result["first"] = mgr.ask("chat-1", "Push branch", verb="git.push", effect="send", timeout=5)
        t = threading.Thread(target=ask_once)
        t.start()
        deadline = time.time() + 3
        while not mgr.pending() and time.time() < deadline:
            time.sleep(0.02)
        code = mgr.pending()[0]["code"]
        mgr.answer(code, True, scope="session")
        t.join(timeout=3)
        self.assertEqual(result["first"][0], "approved")

        # 2. Second ask for same (chat, verb, effect) auto-approves immediately without pending
        state2, reason2 = mgr.ask("chat-1", "Push again", verb="git.push", effect="send", timeout=5)
        self.assertEqual(state2, "approved")
        self.assertIn("session", reason2)
        self.assertEqual(mgr.pending(), [])

        # 3. Credentials effect is NEVER remembered for session
        cred_result = {}
        def ask_cred():
            cred_result["first"] = mgr.ask("chat-1", "Use credentials", verb="auth.login", effect="credentials", timeout=5)
        t2 = threading.Thread(target=ask_cred)
        t2.start()
        deadline = time.time() + 3
        while not mgr.pending() and time.time() < deadline:
            time.sleep(0.02)
        code2 = mgr.pending()[0]["code"]
        mgr.answer(code2, True, scope="session")
        t2.join(timeout=3)
        self.assertEqual(cred_result["first"][0], "approved")
        # Ask again for credentials: must NOT auto-approve (it should create a pending item)
        t3 = threading.Thread(target=lambda: mgr.ask("chat-1", "Use credentials again", verb="auth.login", effect="credentials", timeout=5))
        t3.start()
        deadline = time.time() + 3
        while not mgr.pending() and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(mgr.pending()), 1)
        mgr.answer(mgr.pending()[0]["code"], False)
        t3.join(timeout=3)


class TerminalContractTests(TestCase):
    def test_pty_session_open_echo_resize_and_close(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        sess = terminal.open_session(tmp.name, cols=90, rows=24)
        self.addCleanup(lambda: terminal.close_session(sess.id))
        self.assertTrue(sess.alive)
        sess.resize(110, 30)
        self.assertEqual((sess.cols, sess.rows), (110, 30))
        marker = "HARNESS_PTY_CONTRACT_OK"
        sess.write(f"echo {marker}\r\n" if os.name == "nt" else f"echo {marker}\n")
        collected = ""
        cursor = 0
        deadline = time.time() + 10
        while time.time() < deadline:
            chunks, alive, _ = sess.read_after(cursor)
            for c in chunks:
                cursor = c["seq"]
                collected += base64.b64decode(c["data"]).decode("utf-8", errors="replace")
            if marker in collected:
                break
            time.sleep(0.05)
        self.assertIn(marker, collected)
        terminal.close_session(sess.id)
        self.assertFalse(sess.alive)


class WorkspaceFilesAndWorktreeTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.identity_dir = self.root / "agents" / "default"
        self.identity_dir.mkdir(parents=True)
        self.project = _init_repo(self.root / "repo")
        self.rows = [{"id": "default", "name": "Dev", "folder": str(self.identity_dir), "current": True}]
        self.agent_patch = mock.patch.object(
            app_host, "_agent", lambda name: (lambda server, body: self.rows) if name == "identities" else None
        )
        self.agent_patch.start()
        metas = {"chat-1": {"kind": "new", "place": "proj"}}
        places = {"proj": SimpleNamespace(kind="folder", row={"kind": "folder", "folder": str(self.project)})}
        life = SimpleNamespace(chats=SimpleNamespace(meta=lambda chat: metas.get(chat, {"kind": "main"})), places=places)
        self.server = SimpleNamespace(background={"agent": SimpleNamespace(life=lambda _id: life)})

    def tearDown(self):
        self.agent_patch.stop()
        self.tmp.cleanup()

    def test_tree_file_search_changes_revert_and_guards(self):
        # Modify tracked file, add untracked file & binary file
        (self.project / "app.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
        (self.project / "extra.txt").write_text("untracked\n", encoding="utf-8")
        (self.project / "blob.bin").write_bytes(b"\x00\x01\x02\x03")

        tree = app_host.place_tree(self.server, {"identity": "default", "chat": "chat-1", "path": ""})
        names = [e["name"] for e in tree["entries"]]
        self.assertIn("sub", names)
        self.assertIn("app.py", names)
        app_entry = next(e for e in tree["entries"] if e["name"] == "app.py")
        self.assertEqual(app_entry.get("status"), "M")

        sub = app_host.place_tree(self.server, {"identity": "default", "chat": "chat-1", "path": "sub"})
        self.assertEqual([e["path"] for e in sub["entries"]], ["sub/util.js"])

        # Path traversal rejected
        with self.assertRaises(ValueError):
            app_host.place_tree(self.server, {"identity": "default", "chat": "chat-1", "path": "../agents"})
        with self.assertRaises(ValueError):
            app_host.place_file(self.server, {"identity": "default", "chat": "chat-1", "path": "../agents/default"})

        # Text and binary reads
        py = app_host.place_file(self.server, {"identity": "default", "chat": "chat-1", "path": "app.py"})
        self.assertEqual(py["language"], "python")
        self.assertFalse(py["binary"])
        self.assertIn("hello", py["text"])
        binf = app_host.place_file(self.server, {"identity": "default", "chat": "chat-1", "path": "blob.bin"})
        self.assertTrue(binf["binary"])

        # Fuzzy @ search
        found = app_host.place_search(self.server, {"identity": "default", "chat": "chat-1", "q": "util"})
        self.assertEqual([m["path"] for m in found["matches"]], ["sub/util.js"])

        # Structured git changes + revert tracked & untracked
        changes = app_host.place_changes(self.server, {"identity": "default", "chat": "chat-1"})
        paths = {f["path"]: f for f in changes["files"]}
        self.assertIn("app.py", paths)
        self.assertIn("extra.txt", paths)
        self.assertGreaterEqual(paths["app.py"]["added"], 1)

        app_host.place_changes(self.server, {"identity": "default", "chat": "chat-1", "action": "revert", "path": "app.py"})
        self.assertIn("'hi'", (self.project / "app.py").read_text(encoding="utf-8"))
        app_host.place_changes(self.server, {"identity": "default", "chat": "chat-1", "action": "revert", "path": "extra.txt"})
        self.assertFalse((self.project / "extra.txt").exists())

    def test_worktree_status_merge_conflict_and_discard(self):
        identity = SimpleNamespace(directory=self.identity_dir)
        copy = agent_places.copy(identity, "chat-wt1", self.project)
        wt_folder = Path(copy["folder"])
        meta = {"copy": copy}
        (wt_folder / "feature.py").write_text("x = 42\n", encoding="utf-8")
        _git(wt_folder, "add", "feature.py")
        _git(wt_folder, "commit", "-qm", "add feature")

        st = agent_places.worktree_status(meta)
        self.assertTrue(st["is_worktree"])
        self.assertEqual(st["ahead"], 1)
        self.assertEqual(st["dirty"], 0)

        merged = agent_places.merge_copy(meta)
        self.assertTrue(merged["merged"])
        self.assertTrue((self.project / "feature.py").is_file())

        # Conflict handling: edit same line on both branches, verify clean abort + discard
        copy2 = agent_places.copy(identity, "chat-wt2", self.project)
        wt2 = Path(copy2["folder"])
        meta2 = {"copy": copy2}
        (wt2 / "app.py").write_text("def greet():\n    return 'branch'\n", encoding="utf-8")
        _git(wt2, "add", "app.py")
        _git(wt2, "commit", "-qm", "branch change")
        (self.project / "app.py").write_text("def greet():\n    return 'main'\n", encoding="utf-8")
        _git(self.project, "add", "app.py")
        _git(self.project, "commit", "-qm", "main change")

        with self.assertRaises(ValueError) as ctx:
            agent_places.merge_copy(meta2)
        self.assertIn("conflict", str(ctx.exception).lower())
        # Origin repo is NOT left in MERGING state
        self.assertFalse((self.project / ".git" / "MERGE_HEAD").exists())

        disc = agent_places.discard_copy(meta2)
        self.assertTrue(disc["discarded"])
        self.assertFalse(wt2.exists())

    def test_rules_read_and_write_global_project_and_persona(self):
        fake_home = self.root / "home"
        with mock.patch.object(harness_paths, "home", return_value=fake_home):
            got = app_host.rules(self.server, {"identity": "default", "chat": "chat-1"})
            scopes = {(f["scope"], f["name"]) for f in got["files"]}
            self.assertIn(("global", "AGENTS.md"), scopes)
            self.assertIn(("project", "AGENTS.md"), scopes)
            self.assertIn(("project", "CLAUDE.md"), scopes)
            self.assertIn(("persona", "SOUL.md"), scopes)

            app_host.rules(self.server, {"identity": "default", "chat": "chat-1", "scope": "global", "file": "AGENTS.md", "text": "Global rule\n"})
            app_host.rules(self.server, {"identity": "default", "chat": "chat-1", "scope": "project", "file": "AGENTS.md", "text": "Project rule\n"})
            self.assertEqual((fake_home / "AGENTS.md").read_text(encoding="utf-8"), "Global rule\n")
            self.assertEqual((self.project / "AGENTS.md").read_text(encoding="utf-8"), "Project rule\n")

            with self.assertRaises(ValueError):
                app_host.rules(self.server, {"identity": "default", "chat": "chat-1", "scope": "project", "file": "evil.py", "text": "x"})


class BehaviorTreeAndStreamTests(TestCase):
    def test_behavior_tree_full_hierarchy_and_edit(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        identity = SimpleNamespace(directory=Path(tmp.name))
        tree = reactions.Tree(identity)
        tree.add("low-power", {"fact": "battery", "below": 20}, None, about="Low battery mode")
        tree.add("warn-owner", {"event": "task.start"}, {"remind": "Plug in"}, under="low-power", about="Warn before heavy task")

        full = tree.full()
        folder = next(n for n in full["nodes"] if n["name"] == "low-power")
        self.assertTrue(folder["situation"])
        self.assertEqual([c["name"] for c in folder["children"]], ["warn-owner"])

        tree.edit("warn-owner", about="Updated warning", do={"remind": "Connect charger"})
        updated = tree.node("warn-owner")
        self.assertEqual(updated["about"], "Updated warning")
        self.assertEqual(updated["do"], {"remind": "Connect charger"})

        # Built-in node condition/action cannot be mutated
        with self.assertRaises(ValueError):
            tree.edit("named", when={"event": "x"})

    def test_chat_notifier_and_stream_callable(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        identity = SimpleNamespace(directory=Path(tmp.name))
        chats = agent_chats.Chats(identity)
        woke = threading.Event()

        def waiter():
            v0 = chats._version
            v1 = chats.wait_change(v0, timeout=3.0)
            if v1 > v0:
                woke.set()

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.05)
        chats.record("main", "user", text="hello")
        t.join(timeout=3.0)
        self.assertTrue(woke.is_set())
        self.assertIn("stream", agent_host.api)

    def test_first_run_identity_setup_replaces_untouched_default_and_persists_persona(self):
        from harness_agent import state as agent_state

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        fake_home = Path(tmp.name) / "home"
        fake_data = Path(tmp.name) / "data"
        fake_home.mkdir()
        fake_data.mkdir()
        with mock.patch.dict(os.environ, {"HARNESS_HOME": str(fake_home), "HARNESS_DATA": str(fake_data)}):
            agent_state.first()
            self.assertEqual(agent_state.identities(), ["default"])
            srv = SimpleNamespace(background={})
            listed = agent_host.identity_change(srv, {
                "action": "setup",
                "id": "default",
                "new_id": "jarvis",
                "name": "Jarvis",
                "soul": "Concise and rigorous.",
                "user": "Call me Alex.",
            })
            ids = [r["id"] for r in listed]
            self.assertEqual(ids, ["jarvis"])
            self.assertTrue(listed[0]["current"])
            self.assertEqual(listed[0]["name"], "Jarvis")
            folder = fake_home / "agents" / "jarvis"
            self.assertIn("Concise and rigorous.", (folder / "SOUL.md").read_text(encoding="utf-8"))
            self.assertIn("Call me Alex.", (folder / "USER.md").read_text(encoding="utf-8"))
            self.assertTrue((folder / "named.json").is_file())

            # Rename in-place (e.g. Chinese display name without changing ID)
            listed2 = agent_host.identity_change(srv, {"action": "setup", "id": "jarvis", "name": "小安"})
            self.assertEqual(listed2[0]["id"], "jarvis")
            self.assertEqual(listed2[0]["name"], "小安")

            # When default already has conversation history, setup must NOT delete default
            fake_home2 = Path(tmp.name) / "home2"
            fake_home2.mkdir()
            with mock.patch.dict(os.environ, {"HARNESS_HOME": str(fake_home2), "HARNESS_DATA": str(fake_data)}):
                agent_state.first()
                ev = fake_home2 / "agents" / "default" / "sessions" / "main" / "events.jsonl"
                ev.parent.mkdir(parents=True, exist_ok=True)
                ev.write_text('{"seq":1,"event":"user","text":"hi"}\n', encoding="utf-8")
                listed3 = agent_host.identity_change(srv, {
                    "action": "setup", "id": "default", "new_id": "nova", "name": "Nova",
                })
                self.assertEqual({r["id"] for r in listed3}, {"default", "nova"})
                cur = next(r for r in listed3 if r["current"])
                self.assertEqual(cur["id"], "nova")

    def test_terminal_console_decoder_handles_utf8_and_gbk_cleanly(self):
        from harness_app import terminal as app_terminal

        gbk_banner = "Microsoft Windows [版本 10.0]\r\n(c) Microsoft Corporation。保留所有权利。\r\n".encode("cp936")
        decoded = app_terminal._decode_console(gbk_banner, "cp936")
        self.assertIn("版本 10.0", decoded)
        self.assertIn("保留所有权利", decoded)
        self.assertNotIn("\ufffd", decoded)

        utf8_line = "中文 UTF-8 输出正常\n".encode("utf-8")
        self.assertEqual(app_terminal._decode_console(utf8_line, "cp936"), "中文 UTF-8 输出正常\n")

        mixed = gbk_banner + utf8_line
        decoded_mixed = app_terminal._decode_console(mixed, "cp936")
        self.assertIn("保留所有权利", decoded_mixed)
        self.assertIn("中文 UTF-8 输出正常", decoded_mixed)
        self.assertNotIn("\ufffd", decoded_mixed)

    def test_windows_conpty_interactive_shell(self):
        if os.name != "nt":
            return
        from harness_app import terminal as app_terminal

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        con = app_terminal._ConPty(["powershell.exe", "-NoLogo", "-NoProfile"], tmp.name,
                                   {**os.environ, "PYTHONUTF8": "1"}, 100, 28)
        self.addCleanup(con.close)
        got = bytearray()

        def reader():
            while True:
                chunk = con.read(4096)
                if not chunk:
                    break
                got.extend(chunk)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        deadline = time.time() + 10.0
        sent = False
        while time.time() < deadline:
            if not sent and len(got) > 20:
                time.sleep(0.5)
                con.write(b"echo CONPTY_UNIT_PASS\r")
                con.resize(120, 30)
                sent = True
            if b"CONPTY_UNIT_PASS" in got:
                break
            time.sleep(0.1)
        con.close()
        t.join(timeout=2.0)
        self.assertIn("CONPTY_UNIT_PASS", app_terminal._decode_console(bytes(got), app_terminal._oem_encoding()))

    def test_ssh_project_place_and_config_parser(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        cfg = Path(tmp.name) / "ssh_config"
        cfg.write_text(
            "# comment\nHost prod-gpu\n  HostName 10.2.3.4\n  User ubuntu\n  Port 2222\n\nHost *\n  ServerAliveInterval 60\n",
            encoding="utf-8",
        )
        hosts = agent_places.ssh_config_hosts(cfg)
        self.assertEqual(hosts, [{"host": "prod-gpu", "hostname": "10.2.3.4", "user": "ubuntu", "port": 2222}])

        identity = SimpleNamespace(directory=Path(tmp.name))
        row = agent_places.add(identity, "ssh", id="ssh-prod", host="ubuntu@10.2.3.4", port=2222, folder="/srv/app")
        self.assertEqual(row["kind"], "ssh")
        self.assertEqual(row["target"], "ubuntu@10.2.3.4")
        self.assertEqual(row["port"], 2222)
        self.assertEqual(row["folder"], "/srv/app")
        opened = agent_places.open_place(row, lambda *_: None)
        desc = opened.describe()
        self.assertTrue(desc["ssh"])
        self.assertEqual(desc["target"], "ubuntu@10.2.3.4")

    def test_task_live_steps_and_effort_forwarding(self):
        from harness_agent.life import Life
        from harness_agent.tasks import Tasks

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        identity = SimpleNamespace(directory=Path(tmp.name), id="default",
                                   settings_section=lambda *_: {}, settings=lambda: {})
        chats = agent_chats.Chats(identity)
        life = object.__new__(Life)
        life.chats = chats
        seen = life.task_rows("main")
        seen({"seq": 1, "event": "state", "status": "RUNNING", "reason": "preparing the workspace"})
        seen({"seq": 2, "event": "model_request", "call": 1, "model": "gemini-4-neon"})
        seen({"seq": 3, "event": "cell", "number": 1, "code": "import os\nprint(os.listdir('.'))",
              "result": {"status": "ok", "seconds": 0.42, "stdout": "README.md\nsrc\n"}})
        seen({"seq": 4, "event": "execution_event",
              "execution": {"skill": "shell", "ok": True, "event": {"kind": "COMPLETED"}}})
        seen({"seq": 5, "event": "execution_event",
              "execution": {"skill": "click", "ok": False,
                            "event": {"kind": "SHIELD_REJECTED", "detail": {"reasons": [{"check": "user_input", "reason": "busy"}]}}}})
        seen({"seq": 6, "event": "error", "message": "transient error"})

        recs = chats.read("main")
        steps = [r for r in recs if r.get("event") == "task_step"]
        self.assertEqual([s["kind"] for s in steps], ["status", "think", "cell", "skill", "error"])
        self.assertEqual(steps[2]["code"], "print(os.listdir('.'))")
        self.assertAlmostEqual(steps[2]["seconds"], 0.42)
        outcomes = [r for r in recs if r.get("event") == "outcome" and r.get("end") == "refused"]
        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0]["owner_input"])

        captured = {}

        class FakeHost:
            def task(self, goal, workspace, **kwargs):
                captured["goal"] = goal
                captured["workspace"] = workspace
                captured.update(kwargs)
                return SimpleNamespace(run="run-123")

        tasks = Tasks(FakeHost(), workspace="project", folder=str(tmp.name), model="acp:antigravity/neon", effort="low")
        run_id = tasks.submit("scan repo")
        self.assertEqual(run_id, "run-123")
        self.assertEqual(captured["model_entry"], "acp:antigravity/neon")
        self.assertEqual(captured["reasoning_effort"], "low")
