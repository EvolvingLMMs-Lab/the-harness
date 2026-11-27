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
              "execution": {"skill": "run", "event": {"kind": "COMPLETED"}}})
        seen({"seq": 41, "event": "execution_event",
              "execution": {"skill": "output", "event": {"kind": "COMPLETED"}}})
        seen({"seq": 42, "event": "execution_event",
              "execution": {"skill": "write", "event": {"kind": "SKILL_ERROR"}}})
        seen({"seq": 5, "event": "execution_event",
              "execution": {"skill": "click", "ok": False,
                            "event": {"kind": "SHIELD_REJECTED", "detail": {"reasons": [{"check": "user_input", "reason": "busy"}]}}}})
        seen({"seq": 6, "event": "error", "message": "transient error"})

        recs = chats.read("main")
        steps = [r for r in recs if r.get("event") == "task_step"]
        self.assertEqual([s["kind"] for s in steps], ["status", "think", "cell", "skill", "skill", "error"])
        self.assertEqual((steps[3]["label"], steps[3]["ok"]), ("run", True))
        self.assertEqual((steps[4]["label"], steps[4]["ok"]), ("write", False))
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

    def test_quiet_workspace_events_and_local_markdown_artifacts(self):
        from harness_agent.life import Life

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        identity_dir = Path(tmp.name) / "agents" / "default"
        identity_dir.mkdir(parents=True)
        identity = SimpleNamespace(directory=identity_dir, id="default")
        chats = agent_chats.Chats(identity)

        # 1. Quiet folder.changed event must NOT increment unread
        chats.ensure("place-proj1", kind="place", title="proj1", place="proj1")
        chats.record("place-proj1", "event", quiet=True, kind="folder.changed", place="proj1", data={})
        self.assertEqual(chats.meta("place-proj1").get("unread", 0), 0)

        # 2. write_artifact writes .md under sessions/<chat>/artifacts/, rejects traversal, and is readable via app_host
        life = object.__new__(Life)
        life.chats = chats
        res = life.write_artifact("main", {
            "name": "implementation_plan.md",
            "title": "UI Upgrade Plan",
            "summary": "Four-layer minimal plan.",
            "content": "# UI Upgrade Plan\n\n- Step 1\n- Step 2\n",
            "request_approval": True,
        })
        self.assertTrue(res["ok"])
        self.assertEqual(res["name"], "implementation_plan.md")
        art_path = Path(res["path"])
        self.assertTrue(art_path.is_file())
        self.assertEqual(art_path.parent, chats.folder("main") / "artifacts")

        with self.assertRaises(ValueError):
            life.write_artifact("main", {"name": "../escape.md", "content": "nope"})

        recs = [r for r in chats.read("main") if r.get("event") == "artifact"]
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]["request_approval"])
        self.assertEqual(recs[0]["title"], "UI Upgrade Plan")

        # Verify app_host.artifacts & app_host.artifact endpoints
        srv = SimpleNamespace(background={})
        with mock.patch.object(app_host, "_identity_row", return_value={"id": "default", "folder": str(identity_dir)}):
            listed = app_host.artifacts(srv, {"identity": "default", "chat": "main"})
            self.assertEqual([a["name"] for a in listed["artifacts"]], ["implementation_plan.md"])
            got = app_host.artifact(srv, {"identity": "default", "chat": "main", "name": "implementation_plan.md"})
            self.assertIn("# UI Upgrade Plan", got["text"])
            with self.assertRaises(ValueError):
                app_host.artifact(srv, {"identity": "default", "chat": "main", "name": "../escape.md"})

    def test_reboot_recovery_clears_orphaned_pending_task_and_allows_stop(self):
        import json
        from harness.runtime.decision.model import ChatReply
        from harness_agent.life import Life
        from harness_agent.session import Interrupted, Session
        from harness_agent.state import Identity, read as state_read, save as state_save

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        identity = Identity("default", root=tmp.name)

        # 1. Simulate a hard reboot mid-task: state.json has a dead pending.run and life-state.json
        #    has an already-started owner job + an unstarted waiting job.
        sess_dir = identity.session("main")
        state_save(sess_dir / "state.json", {
            "schema": 1, "identity": "default",
            "messages": [{"role": "user", "content": "open a pr"}],
            "summary": "", "pending": {"run": "conversations/dead-reboot-run", "after": -1},
            "usage": {"model_calls": 1, "cost_usd": 0.0},
        })
        state_save(identity.directory / "life-state.json", {
            "paused": False, "paused_own": False, "day": "2026-11-27", "asleep_since": None, "held": [],
            "queue": [
                {"id": "job-started", "kind": "owner", "chat": "main", "text": "open a pr", "started": True},
                {"id": "job-waiting", "kind": "owner", "chat": "main", "text": "next task"},
            ],
            "waiting": {},
        })

        class ReplyModel:
            def complete(self, system, messages, **kwargs):
                return ChatReply(text=json.dumps({"action": "reply", "text": "recovered ok"}), usage={})

        class DeadTasks:
            def __init__(self):
                self.entered = threading.Event()
                self.stop_seen = threading.Event()

            def status(self, run):
                raise ValueError(f"this server runs no session {run}")

            def cancel(self, run):
                raise ValueError("this server does not run that conversation")

            def submit(self, goal, **kwargs):
                return "run-live"

            def observe(self, run, after=-1, *, stop=None):
                self.entered.set()
                if stop is not None:
                    stop.wait(5.0)
                    if stop.is_set():
                        self.stop_seen.set()
                        return {"run": run, "after": after, "status": "cancelled", "answer": ""}
                return {"run": run, "after": after, "status": "ended", "answer": "done"}

        # Life.start() clears the orphaned pending run and does NOT duplicate the started job.
        life = Life(identity, model=lambda *a, **kw: ReplyModel(), tasks=lambda row: DeadTasks(),
                    is_run_alive=lambda run_id: False)
        life.start()
        self.addCleanup(life.close)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if any(r.get("event") == "reply" for r in life.chats.read("main")):
                break
            time.sleep(0.05)
        st_after = state_read(sess_dir / "state.json", {})
        self.assertIsNone(st_after["pending"])
        user_texts = [r.get("text") for r in life.chats.read("main") if r.get("event") == "user"]
        self.assertNotIn("open a pr", user_texts)
        self.assertIn("next task", user_texts)
        outcomes = [r for r in life.chats.read("main") if r.get("event") == "outcome" and r.get("run") == "conversations/dead-reboot-run"]
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["end"], "cancelled")

        # 2. Direct Session.turn() also recovers gracefully when pending.run disappeared on the host.
        sess_dir2 = identity.session("chat-dead")
        state_save(sess_dir2 / "state.json", {
            "schema": 1, "identity": "default", "messages": [], "summary": "",
            "pending": {"run": "conversations/gone-run", "after": -1},
            "usage": {"model_calls": 0, "cost_usd": 0.0},
        })
        dead = DeadTasks()
        s = Session(identity, ReplyModel(), dead, session="chat-dead")
        ans = s.turn("继续")
        self.assertEqual(ans, "recovered ok")
        self.assertIsNone(s.state["pending"])

        # 3. Interrupting a running Session._observe() wakes Tasks.observe(stop=...) immediately.
        class TaskThenReply:
            def complete(self, system, messages, **kwargs):
                return ChatReply(text=json.dumps({"action": "task", "goal": "long work"}), usage={})

        s2 = Session(identity, TaskThenReply(), dead, session="chat-stop")
        err_holder = []

        def run_turn():
            try:
                s2.turn("start")
            except Interrupted as exc:
                err_holder.append(exc)

        t = threading.Thread(target=run_turn)
        t.start()
        self.assertTrue(dead.entered.wait(3.0), "observe() should have started")
        s2.interrupt("owner clicked stop")
        t.join(timeout=3.0)
        self.assertFalse(t.is_alive(), "Session.interrupt() must unblock Tasks.observe() immediately")
        self.assertTrue(dead.stop_seen.is_set())
        self.assertEqual(len(err_holder), 1)
        self.assertIsNone(s2.state["pending"])
        self.assertEqual((s2.state.get("interrupted_task") or {}).get("run"), "run-live")

    def test_interrupted_subtask_resumes_directly_on_continue_and_clean_close(self):
        """Typing '继续' after an interrupted sub-task resumes that exact run_id checkpoint,
        and Life.close() during an active task does not emit a false network error card."""
        import json
        from harness.runtime.decision.model import ChatReply
        from harness_agent.life import Life
        from harness_agent.session import Session
        from harness_agent.state import Identity, read as state_read, save as state_save

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        identity = Identity("default", root=tmp.name)
        sess_dir = identity.session("chat-resume")
        state_save(sess_dir / "state.json", {
            "schema": 1, "identity": "default", "messages": [
                {"role": "user", "content": "修一下然后开个pr"},
                {"role": "assistant", "content": json.dumps({"action": "task", "goal": "Fix two UI bugs"})},
                {"role": "user", "content": "Action result: {\"status\": \"ended\", \"summary\": \"fixed\"}"},
                {"role": "assistant", "content": json.dumps({"action": "task", "goal": "Push branch and open PR"})},
            ],
            "summary": "",
            "pending": {"run": "conversations/subtask-2", "after": 12, "goal": "Push branch and open PR"},
            "usage": {"model_calls": 2, "cost_usd": 0.0},
        })
        from harness_agent.chats import Chats
        chats = Chats(identity)
        chats.ensure("chat-resume", kind="new", title="resume test")
        chats.record("chat-resume", "action", verb="task", goal="Push branch and open PR")
        chats.record("chat-resume", "task_step", kind="cell", number=4, code="# Run git push")

        class ResumableTasks:
            def __init__(self):
                self.resumed = []
                self.observed = []
                self.submitted = []

            def submit(self, goal, **kwargs):
                self.submitted.append(goal)
                return "conversations/new-run"

            def resume_run(self, run, text):
                self.resumed.append((run, text))
                return run, 12

            def observe(self, run, after=-1, *, stop=None):
                self.observed.append((run, after))
                return {"run": run, "after": 18, "status": "ended", "answer": "PR #999 opened",
                        "summary": {"status": "completed", "text": "PR #999 opened"}}

            def status(self, run):
                raise RuntimeError("not found")

            def cancel(self, run):
                pass

        class ReplyModel:
            def complete(self, system, messages, **kwargs):
                return ChatReply(text=json.dumps({"action": "reply", "text": "已从断点继续并完成 PR #999"}), usage={})

        tasks_runner = ResumableTasks()
        life = Life(identity, model=lambda *a, **k: ReplyModel(), tasks=lambda place=None: tasks_runner,
                    is_run_alive=lambda run_id: False)
        life.start()
        try:
            st = state_read(sess_dir / "state.json", {})
            self.assertIsNone(st["pending"])
            self.assertEqual(st["interrupted_task"]["run"], "conversations/subtask-2")
            self.assertEqual(st["interrupted_task"]["goal"], "Push branch and open PR")
            self.assertTrue(any("#4 # Run git push" in s for s in st["interrupted_task"].get("steps_done") or []))
            interrupted_rows = [r for r in life.chats.read("chat-resume") if r.get("event") == "interrupted"]
            self.assertEqual(interrupted_rows[-1].get("resumable_run"), "conversations/subtask-2")
        finally:
            life.close()

        # Now user types "继续": Session directly resumes conversations/subtask-2 without submitting a new big task.
        s = Session(identity, ReplyModel(), tasks_runner, session="chat-resume")
        ans = s.turn("继续")
        self.assertIn("PR #999", ans)
        self.assertEqual(len(tasks_runner.resumed), 1)
        self.assertEqual(tasks_runner.resumed[0][0], "conversations/subtask-2")
        self.assertEqual(tasks_runner.observed, [("conversations/subtask-2", 12)])
        self.assertEqual(tasks_runner.submitted, [])
        self.assertIsNone(s.state.get("interrupted_task"))

        # Clean shutdown test: Life.close() while a task throws ConnectionRefusedError must not log an error card.
        entered = threading.Event()
        release_err = threading.Event()

        class ShutdownDropTasks(ResumableTasks):
            def observe(self, run, after=-1, *, stop=None):
                entered.set()
                if stop is not None:
                    stop.wait(2.0)
                release_err.wait(0.2)
                raise ConnectionRefusedError("[WinError 10061] connection refused")

        class TaskModel:
            def complete(self, system, messages, **kwargs):
                return ChatReply(text=json.dumps({"action": "task", "goal": "work during update"}), usage={})

        life2 = Life(identity, model=lambda *a, **k: TaskModel(), tasks=lambda place=None: ShutdownDropTasks())
        life2.start()
        life2.say("main", "do work")
        self.assertTrue(entered.wait(3.0))
        life2.close()
        release_err.set()
        err_rows = [r for r in life2.chats.read("main") if r.get("event") == "error"]
        self.assertEqual(err_rows, [], "Host shutdown should never record a red network error card")

    def test_memory_index_and_full_memory_entries_crud(self):
        """MEMORY.md does not cut mid-word at 100 chars, and /api/app/rules exposes full memory/*.md CRUD."""
        from types import SimpleNamespace
        from unittest import mock
        from harness_agent.state import Identity
        from harness_app.host import rules

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        agents_dir = Path(tmp.name) / "agents"
        with mock.patch.dict(os.environ, {"HARNESS_HOME": tmp.name}):
            identity = Identity("default", root=agents_dir)
            long_text = (
                "The local workspace holds local documents and design specifications for the owner; "
                "always follow project conventions, keep changes minimal, and never truncate important context mid-word."
            )
            identity.remember("owner_conventions", long_text, source="main", expected=0)
            index_md = (identity.directory / "MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("owner_conventions", index_md)
            self.assertIn("never truncate important context mid-word.", index_md)

            fake_life = SimpleNamespace(identity=identity, chats=SimpleNamespace(meta=lambda chat: {}), places={})
            fake_server = SimpleNamespace(background={"agent": SimpleNamespace(lives={"default": fake_life})})
            got = rules(fake_server, {"identity": "default"})
            by_scope_name = {(f["scope"], f["name"]): f for f in got["files"]}
            self.assertTrue(by_scope_name[("persona", "MEMORY.md")].get("readonly"))
            mem_files = [f for f in got["files"] if f["scope"] == "memory"]
            self.assertEqual(len(mem_files), 1)
            self.assertEqual(mem_files[0]["title"], "owner_conventions")
            self.assertIn(long_text, mem_files[0]["text"])

            # Edit memory entry via /api/app/rules and confirm MEMORY.md rebuilds automatically.
            updated_body = mem_files[0]["text"].replace("never truncate important context mid-word.", "updated cleanly!")
            rules(fake_server, {"identity": "default", "scope": "memory", "file": mem_files[0]["name"], "text": updated_body})
            self.assertIn("updated cleanly!", (identity.directory / "MEMORY.md").read_text(encoding="utf-8"))

            # Delete memory entry via /api/app/rules and confirm it disappears from both memory/ and MEMORY.md.
            rules(fake_server, {"identity": "default", "scope": "memory", "file": mem_files[0]["name"], "action": "delete"})
            got_after = rules(fake_server, {"identity": "default"})
            self.assertEqual([f for f in got_after["files"] if f["scope"] == "memory"], [])
            self.assertNotIn("owner_conventions", (identity.directory / "MEMORY.md").read_text(encoding="utf-8"))

    def test_composer_autocomplete_css_and_commands(self):
        """Composer must not clip .pg-ac popups with overflow: hidden, and includes /continue & /memory."""
        root = Path(__file__).resolve().parents[1]
        css = (root / "packages" / "app" / "ui" / "static" / "app.css").read_text(encoding="utf-8")
        self.assertNotIn(".pg-compose { margin: 0 16px 4px; padding: 10px 12px 8px; position: relative; min-width: 0; overflow: hidden;", css)
        self.assertIn("overflow: visible;", css)
        composer_js = (root / "packages" / "app" / "ui" / "static" / "js" / "composer.js").read_text(encoding="utf-8")
        self.assertIn("'/continue'", composer_js)
        self.assertIn("'/memory'", composer_js)
