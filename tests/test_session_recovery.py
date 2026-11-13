"""Interrupted sessions preserve history, recover streams and select recent activity."""

from contextlib import redirect_stderr
from http.client import IncompleteRead
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from harness.core.episodes import Follow, read_records
from harness.core.trace import Trace
from harness.host import client, http, sessions
from harness.host.tasks import TaskHost
from harness import providers


class TraceRecoveryTests(unittest.TestCase):
    def recover(self, tail, expected):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "events.jsonl"
            prefix = b'{"seq":0,"event":"state","status":"RUNNING"}\n'
            path.write_bytes(prefix + tail)
            trace = Trace(directory, append=True)
            record = trace.emit("state", status="IDLE")
            self.assertTrue(path.read_bytes().startswith(prefix))
            records = read_records(directory)
            self.assertEqual([row["seq"] for row in records], list(range(expected + 1)))
            self.assertEqual(record["seq"], expected)
            self.assertEqual(Follow(directory).next(), records)
            if expected == 2:
                self.assertEqual(records[1]["text"], "kept")

    def test_truncated_json_tail_is_removed_before_appending(self):
        self.recover(b'{"seq":1,"event":"model_reply","text":"part', 1)

    def test_truncated_utf8_tail_is_removed_before_appending(self):
        self.recover(b'{"seq":1,"text":"\xe4\xb8', 1)

    def test_valid_unterminated_event_is_preserved(self):
        self.recover(b'{"seq":1,"event":"model_reply","text":"kept"}', 2)

    def test_complete_corruption_is_reported_without_modifying_history(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            original = b'{"seq":0}\ninvalid\n{"seq":1'
            path.write_bytes(original)
            with self.assertRaises(json.JSONDecodeError):
                Trace(path.parent, append=True)
            self.assertEqual(path.read_bytes(), original)


class SessionHistoryTests(unittest.TestCase):
    def test_orphan_open_summary_is_interrupted_and_closed_endings_stay_distinct(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            index = directory / "index.jsonl"
            index.write_text(json.dumps({"id": "abc123", "run": "run", "directory": str(directory),
                                         "created": 1, "agent": "main"}) + "\n")
            for status, opened, expected in [("finished", True, "INTERRUPTED"),
                                             ("error", True, "INTERRUPTED"),
                                             ("finished", False, "FINISHED"),
                                             ("closed", False, "FINISHED"),
                                             ("error", False, "ERROR"),
                                             ("interrupted", False, "INTERRUPTED"),
                                             (None, False, "INTERRUPTED")]:
                with self.subTest(status=status, opened=opened):
                    (directory / "summary.json").write_text(json.dumps({"status": status, "open": opened}))
                    row, = sessions.history(index)
                    self.assertEqual(row["status"], expected)
                    self.assertFalse(row["live"])

    def registry(self, root):
        registry = sessions.Sessions(index=root / "index.jsonl")
        for run, created in [("older", 10), ("newer", 20)]:
            directory = root / run
            directory.mkdir()
            (directory / "events.jsonl").write_text('{"seq":0}\n')
            conversation = SimpleNamespace(directory=directory, instruction=run, status="IDLE",
                                           send_message=Mock(), resume=Mock())
            with patch.object(sessions.time, "time", return_value=created):
                registry.add(run, conversation)
        return registry

    def handler(self, registry):
        handler = SimpleNamespace(server=SimpleNamespace(conversations=registry), _json=lambda _: None)
        handler._conversation = lambda body: http.Handler._conversation(handler, body)
        return handler

    def test_background_trace_events_never_override_last_user_message(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            # The older background run writes after the user's message to the foreground run.
            with patch.object(sessions.time, "time", return_value=30):
                http.Handler.post_conversations_message(self.handler(registry), {"run": "newer", "text": "follow up"})
            Trace(root / "older", append=True).emit("state", status="RUNNING")
            os.utime(root / "older" / "events.jsonl", (100, 100))
            os.utime(root / "newer" / "events.jsonl", (25, 25))
            server = SimpleNamespace(conversations=registry)
            app = object.__new__(TaskHost)
            with patch.object(http.runs, "read_records", side_effect=AssertionError("scanned trace")):
                self.assertEqual(app.resume(server), "newer")
            # The same choice survives a host restart using only the existing index.
            server.conversations = sessions.Sessions(index=root / "index.jsonl")
            with patch("harness.runtime.task.run.saved", return_value={"messages": []}):
                app.start = Mock(return_value="resumed")
                self.assertEqual(app.resume(server), "resumed")
                self.assertEqual(app.start.call_args.kwargs["resume"]["run"], "newer")

    def test_resuming_older_session_marks_it_latest_despite_background_events(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            app = object.__new__(TaskHost)
            server = SimpleNamespace(conversations=registry)
            with patch.object(sessions.time, "time", return_value=40):
                self.assertEqual(app.resume(server, "older"), "older")
            os.utime(root / "newer" / "events.jsonl", (100, 100))
            self.assertEqual(app.resume(server), "older")
            row = next(row for row in sessions.history(registry.index) if row["run"] == "older")
            self.assertGreaterEqual(row["last_interaction"], 40)
            self.assertEqual(row["created"], 10)

    def test_legacy_index_falls_back_to_creation_without_scanning_machine_activity(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            rows = [json.loads(line) for line in registry.index.read_text().splitlines()]
            for row in rows:
                row.pop("last_interaction", None)
            # A legacy background sub-agent's creation also is not a user interaction.
            older = next(row for row in rows if row["run"] == "older")
            rows.append({**older, "agent": "a1", "parent": "main", "run": "older/a1", "created": 1000})
            registry.index.write_text("".join(json.dumps(row) + "\n" for row in rows))
            os.utime(root / "older" / "events.jsonl", (100, 100))
            server = SimpleNamespace(conversations=sessions.Sessions(index=registry.index))
            app = object.__new__(TaskHost)
            app.start = Mock(return_value="resumed")
            with patch("harness.runtime.task.run.saved", return_value={}), \
                    patch.object(http.runs, "read_records", side_effect=AssertionError("scanned trace")):
                self.assertEqual(app.resume(server), "resumed")
            self.assertEqual(app.start.call_args.kwargs["resume"]["run"], "newer")

    def test_reconnect_preserves_creation_and_records_user_resume(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            registry["older"].status = "FINISHED"
            row = next(row for row in registry.sessions() if row["run"] == "older")
            conversation = SimpleNamespace(directory=root / "older", instruction="older", status="IDLE")
            with patch.object(sessions.time, "time", return_value=40):
                registry.reconnect(row, conversation)
            row = next(row for row in sessions.history(registry.index) if row["run"] == "older")
            self.assertEqual((row["created"], row["last_interaction"]), (10, 40))

    def test_paused_conversation_resume_marks_user_interaction(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            with patch.object(sessions.time, "time", return_value=50):
                http.Handler.post_conversations_resume(self.handler(registry), {"run": "older"})
            self.assertEqual(registry.describe(registry.session_of("older")[0])["last_interaction"], 50)
            registry["older"].resume.assert_called_once()

    def test_rejected_message_does_not_advance_interaction(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            registry["older"].send_message.side_effect = ValueError("closed")
            with self.assertRaisesRegex(ValueError, "closed"):
                http.Handler.post_conversations_message(self.handler(registry), {"run": "older", "text": "rejected"})
            self.assertEqual(registry.describe(registry.session_of("older")[0])["last_interaction"], 10)

    def test_activity_write_failure_keeps_successful_message_receipt_and_retries(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            receipt = []
            handler = self.handler(registry)
            handler._json = receipt.append
            with patch.object(registry, "_write", side_effect=OSError("disk full")), \
                    redirect_stderr(io.StringIO()) as errors:
                http.Handler.post_conversations_message(handler, {"run": "older", "text": "accepted"})
            self.assertEqual(receipt, [{"ok": True}])
            registry["older"].send_message.assert_called_once_with("accepted", files=())
            self.assertIn("disk full", errors.getvalue())
            with patch.object(registry, "_write", wraps=registry._write) as write:
                http.Handler.post_conversations_message(handler, {"run": "older", "text": "next"})
            self.assertEqual(write.call_count, 1)
            row = max(sessions.history(registry.index), key=lambda row: row["last_interaction"])
            self.assertEqual(row["run"], "older")

    def test_many_same_session_messages_update_memory_without_growing_index(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            initial = registry.index.read_bytes()
            with patch.object(registry, "_write", wraps=registry._write) as write:
                for timestamp in range(30, 130):
                    with patch.object(sessions.time, "time", return_value=timestamp):
                        http.Handler.post_conversations_message(self.handler(registry), {"run": "newer", "text": "next"})
            self.assertEqual(write.call_count, 0)
            self.assertEqual(registry.index.read_bytes(), initial)
            self.assertEqual(registry.describe(registry.session_of("newer")[0])["last_interaction"], 129)

    def test_each_session_switch_persists_so_a_b_a_order_survives_restart(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.registry(root)
            with patch.object(registry, "_write", wraps=registry._write) as write:
                for run, timestamp in [("older", 30), ("newer", 31), ("older", 32)]:
                    with patch.object(sessions.time, "time", return_value=timestamp):
                        http.Handler.post_conversations_message(self.handler(registry), {"run": run, "text": "next"})
            self.assertEqual(write.call_count, 3)
            row = max(sessions.history(registry.index), key=lambda row: row["last_interaction"])
            self.assertEqual((row["run"], row["last_interaction"]), ("older", 32))


class SessionDetailsTests(unittest.TestCase):
    def test_metadata_only_details_do_no_trace_read_or_format_work(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "events.jsonl").write_text('{"seq":0,"event":"user_message","text":"hello"}\n')
            for count in (0, -1):
                with self.subTest(lines=count), patch.object(http.runs, "read_records") as read, \
                        patch.object(http, "TextTranscript") as printer:
                    result = []
                    handler = SimpleNamespace(_session=lambda _: {"agents": [{"directory": str(directory)}]},
                                              _json=result.append)
                    http.Handler.get_sessions_show(handler, {"id": ["session"], "lines": [str(count)]})
                    self.assertEqual(result[0]["agents"][0]["lines"], [])
                    read.assert_not_called()
                    printer.assert_not_called()

    def test_positive_line_limit_keeps_last_formatted_lines(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "events.jsonl").write_text("".join(json.dumps({"seq": seq, "event": "user_message",
                                                                        "text": text}) + "\n"
                                                             for seq, text in enumerate(("first", "second"))))
            result = []
            handler = SimpleNamespace(_session=lambda _: {"agents": [{"directory": str(directory)}]},
                                      _json=result.append)
            with patch.object(http.runs, "read_records", wraps=read_records) as read:
                http.Handler.get_sessions_show(handler, {"lines": ["1"]})
            self.assertEqual(len(result[0]["agents"][0]["lines"]), 1)
            self.assertIn("second", result[0]["agents"][0]["lines"][0])
            self.assertEqual(read.call_count, 1)


class HostProviderReadinessTests(unittest.TestCase):
    def test_custom_provider_without_key_can_be_checked_and_saved_by_host(self):
        app = object.__new__(TaskHost)
        app.directory = Path("/unused")
        app.credentials, app.models = Mock(), Mock(return_value=[])
        settings = {"provider": "custom", "model": "local", "base_url": "http://127.0.0.1:1234/v1"}
        provider = providers.PROVIDERS["custom"]
        # requires_key is supplied by the coordinated provider fix; isolate its contract here.
        with patch.object(providers, "check", return_value=settings), \
                patch.object(providers, "requires_key", return_value=False, create=True), \
                patch.object(providers, "reach", return_value={"ok": True}) as reach, \
                patch.object(providers, "save") as save, \
                patch("harness.model_list.entry", return_value={"id": "local"}), \
                patch.dict(os.environ, {provider.key_env: ""}):
            self.assertEqual(app.set_model(settings), {"ok": True})
        reach.assert_called_once_with(settings, "")
        save.assert_called_once_with(app.directory, settings)
        app.credentials.save.assert_not_called()

    def test_keyless_provider_readiness_and_required_provider_missing_key(self):
        app = object.__new__(TaskHost)
        app.directory = Path("/unused")
        app.credentials = Mock()
        app.credentials.status.return_value = {"set": False, "source": None}
        for required, expected in [(False, True), (True, False)]:
            with self.subTest(required=required), \
                    patch("harness.model_list.select", return_value={"provider": "custom"}), \
                    patch.object(providers, "requires_key", return_value=required, create=True):
                self.assertEqual(app.llm()["ready"], expected)

    def test_readiness_identity_uses_enabled_model_and_supports_acp(self):
        app = object.__new__(TaskHost)
        app.directory, app.credentials = Path("/unused"), Mock()
        chosen = {"provider": "acp:local", "model": "small", "base_url": None}
        with patch("harness.model_list.select", return_value=chosen), \
                patch.object(providers, "requires_key", return_value=False, create=True):
            self.assertEqual(app.llm(), {**chosen, "key_env": None, "key": {"set": True, "source": None}, "ready": True})
        app.credentials.status.assert_not_called()

    def test_no_enabled_model_is_not_ready_even_if_saved_provider_is_keyless(self):
        app = object.__new__(TaskHost)
        app.directory, app.credentials = Path("/unused"), Mock()
        app.credentials.status.return_value = {"set": False, "source": None}
        with patch("harness.model_list.select", return_value=None), \
                patch.object(providers, "load", return_value={"provider": "custom"}), \
                patch.object(providers, "requires_key", return_value=False, create=True):
            self.assertFalse(app.llm()["ready"])

    def test_model_selection_conflict_reports_not_ready_without_hiding_other_errors(self):
        class SelectionError(ValueError):
            pass

        app = object.__new__(TaskHost)
        app.directory = Path("/unused")
        with patch("harness.model_list.SelectionError", SelectionError, create=True), \
                patch("harness.model_list.select", side_effect=SelectionError("fix config.toml or models.json")):
            state = app.llm()
        self.assertFalse(state["ready"])
        self.assertTrue(state["selection_error"])
        self.assertIn("models.json", state["detail"])
        self.assertIsNone(state["provider"])
        self.assertIsNone(state["model"])
        with patch("harness.model_list.SelectionError", SelectionError, create=True), \
                patch("harness.model_list.select", side_effect=ValueError("corrupt models.json")):
            with self.assertRaisesRegex(ValueError, "corrupt models.json"):
                app.llm()

    def test_explicit_model_can_recover_invalid_default_without_hiding_corrupt_config(self):
        class SelectionError(ValueError):
            pass
        class Selected(Exception):
            pass

        app = object.__new__(TaskHost)
        app.directory = Path("/unused")
        app.kind = lambda kind: "none"
        app.settings = Mock()
        app.settings.get.return_value = {"model": {"checker": "old", "vision": "old", "reasoning_effort": "high"}}
        chosen = {"provider": "custom", "model": "local", "base_url": "http://127.0.0.1:1234/v1"}
        with patch("harness.model_list.SelectionError", SelectionError, create=True), \
                patch.object(providers, "load", side_effect=SelectionError("unknown configured provider")), \
                patch("harness.model_list.reads_images", return_value=True), \
                patch.object(providers, "model_file", side_effect=Selected) as model_file:
            with self.assertRaises(Selected):
                app.config(choice=chosen)
            self.assertEqual(model_file.call_args.args[0], chosen)
            with self.assertRaisesRegex(SelectionError, "unknown configured provider"):
                app.config()
        with patch("harness.model_list.SelectionError", SelectionError, create=True), \
                patch.object(providers, "load", side_effect=ValueError("corrupt config.toml")):
            with self.assertRaisesRegex(ValueError, "corrupt config.toml"):
                app.config(choice=chosen)
        app.settings.get.side_effect = ValueError("invalid advanced setting")
        with self.assertRaisesRegex(ValueError, "invalid advanced setting"):
            app.config(choice=chosen)

    def test_start_returns_the_actionable_not_ready_detail(self):
        app = object.__new__(TaskHost)
        app.llm = Mock(return_value={"ready": False, "detail": "choose an enabled model in models.json"})
        with self.assertRaisesRegex(ValueError, "choose an enabled model in models.json"):
            app.start(SimpleNamespace(), "do work", workspace="none")
        app.llm.assert_called_once()

    def test_config_uses_selected_model_provider_and_drops_other_provider_overrides(self):
        app = object.__new__(TaskHost)
        app.directory = Path("/unused")
        app.kind = lambda kind: "none"
        app.settings = Mock()
        app.settings.get.return_value = {"model": {"checker": "old", "vision": "old", "reasoning_effort": "high"}}
        configured = {"provider": "openrouter", "model": "old", "base_url": None}
        chosen = {"provider": "custom", "model": "local", "base_url": "http://127.0.0.1:1234/v1"}
        class Selected(Exception):
            pass
        with patch("harness.model_list.select", return_value=chosen), \
                patch("harness.model_list.reads_images", return_value=True), \
                patch.object(providers, "load", return_value=configured), \
                patch.object(providers, "model_file", side_effect=Selected) as model_file:
            with self.assertRaises(Selected):
                app.config()
        self.assertEqual(model_file.call_args.args, (chosen, app.directory, {"reasoning_effort": "high"}))

    def test_required_provider_missing_key_is_not_contacted(self):
        app = object.__new__(TaskHost)
        settings = {"provider": "custom", "model": "model"}
        with patch.object(providers, "check", return_value=settings), \
                patch.object(providers, "requires_key", return_value=True, create=True), \
                patch.object(providers, "reach") as reach, \
                patch.dict(os.environ, {providers.PROVIDERS["custom"].key_env: ""}):
            self.assertEqual(app.set_model(settings), {"ok": False, "detail": "no key"})
        reach.assert_not_called()


class StreamRecoveryTests(unittest.TestCase):
    def remote(self):
        return client.RemoteConversation("http://example.invalid", "unused", "run")

    def test_eof_read_timeout_and_refusal_share_bounded_backoff(self):
        class TimeoutResponse(io.BytesIO):
            def __next__(self):
                raise TimeoutError("read timed out")

        for mode in ("EOF", "TIMEOUT", "REFUSED", "TRUNCATED"):
            with self.subTest(mode=mode):
                clock = [0.0]
                waits, opens = [], []

                def opening(*args, **kwargs):
                    opens.append(kwargs["headers"]["Last-Event-ID"])
                    if len(opens) > 10:
                        raise AssertionError("unbounded reconnect loop")
                    if mode == "REFUSED":
                        raise URLError("refused")
                    if mode == "TRUNCATED":
                        raise IncompleteRead(b"", 10)
                    return TimeoutResponse() if mode == "TIMEOUT" else io.BytesIO()

                def sleeping(delay):
                    waits.append(delay)
                    clock[0] += delay

                with patch.object(client, "open_url", opening), patch.object(client.time, "sleep", sleeping), \
                        patch.object(client.time, "monotonic", lambda: clock[0]), \
                        patch.object(client, "GONE_SECONDS", 0.7):
                    with self.assertRaises(client.HostGone):
                        list(self.remote().records())
                self.assertEqual(waits, [0.1, 0.2, 0.4])
                self.assertEqual(len(opens), 4)

    def test_record_and_keepalive_restore_health_and_resume_sequence(self):
        clock = [0.0]
        waits, after = [], []
        replies = iter([b"", b': keep-alive\n\n',
                        b'event: record\ndata: {"seq":8,"event":"state","status":"IDLE"}\n\n',
                        b'event: end\ndata: {}\n\n'])

        def opening(*args, **kwargs):
            after.append(kwargs["headers"]["Last-Event-ID"])
            return io.BytesIO(next(replies))

        def sleeping(delay):
            waits.append(delay)
            clock[0] += delay

        remote = self.remote()
        with patch.object(client, "open_url", opening), patch.object(client.time, "sleep", sleeping), \
                patch.object(client.time, "monotonic", lambda: clock[0]), \
                patch.object(client, "GONE_SECONDS", 0.15):
            records = list(remote.records(after=4))
        self.assertEqual([row["seq"] for row in records], [8])
        self.assertEqual(remote.status, "IDLE")
        self.assertEqual(after, ["4", "4", "4", "8"])
        self.assertEqual(waits, [0.1, 0.1, 0.1])

    def test_stop_cancels_backoff_without_reopening(self):
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = True
        with patch.object(client, "open_url", return_value=io.BytesIO()) as opening:
            self.assertEqual(list(self.remote().records(stop=stop)), [])
        self.assertEqual(opening.call_count, 1)
        stop.wait.assert_called_once_with(client.RETRY_SECONDS)

    def test_stop_on_keepalive_yields_no_record(self):
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        with patch.object(client, "open_url", return_value=io.BytesIO(b": keep-alive\n\n")):
            self.assertEqual(list(self.remote().records(stop=stop)), [])
        stop.wait.assert_not_called()

    def test_stop_wins_over_hostgone_after_a_failed_read(self):
        stop = Mock()
        stop.is_set.side_effect = [False, False, False, True]
        stop.wait.return_value = False
        with patch.object(client, "open_url", side_effect=lambda *a, **k: io.BytesIO()) as opening, \
                patch.object(client.time, "monotonic", side_effect=[0, 100]):
            self.assertEqual(list(self.remote().records(stop=stop)), [])
        self.assertEqual(opening.call_count, 2)

    def test_already_stopped_stream_never_opens_connection(self):
        stop = Mock()
        stop.is_set.return_value = True
        with patch.object(client, "open_url") as opening:
            self.assertEqual(list(self.remote().records(stop=stop)), [])
        opening.assert_not_called()

    def test_http_rejection_is_not_retried(self):
        error = HTTPError("http://example.invalid", 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}'))
        with patch.object(client, "open_url", side_effect=error) as opening:
            with self.assertRaisesRegex(client.RemoteError, "bad key"):
                list(self.remote().records())
        self.assertEqual(opening.call_count, 1)


class HostPackageManagementTests(unittest.TestCase):
    def setUp(self):
        import sys
        from harness import paths
        from harness.packages.registry import publish

        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.registry = self.root / "registry"
        self.registry.mkdir()
        self.original_path = sys.path[:]
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), self.original_path))
        environment = patch.dict(os.environ, {"HARNESS_HOME": str(self.root / "cache"),
                                               "HARNESS_DATA": str(self.root / "data"),
                                               "HARNESS_REGISTRY": str(self.registry),
                                               "HARNESS_PACKAGE_ROOTS": ""})
        environment.start()
        self.addCleanup(environment.stop)
        checkout = patch.object(paths, "CHECKOUT", False)
        checkout.start()
        self.addCleanup(checkout.stop)
        paths.packages_changed()
        self.addCleanup(paths.packages_changed)
        self.publish = publish
        self.modules = []
        self.addCleanup(lambda: [sys.modules.pop(name, None) for name in self.modules])
        self.app = TaskHost(self.root / "data")
        self.addCleanup(self.app.close)

    def package(self, name, *, workspace=False, requirements=False):
        folder = self.root / "sources" / name
        folder.mkdir(parents=True)
        manifest = f'[package]\nname = "{name}"\nversion = "0.1.0"\nsummary = "Local test package"\n'
        if workspace:
            module = "harness_" + name.replace("-", "_") + ".host"
            self.modules.extend([module, module.partition(".")[0]])
            module_folder = folder / module.partition(".")[0]
            module_folder.mkdir()
            (module_folder / "__init__.py").touch()
            manifest += f'[provides]\nhost = "{module}"\nworkspaces = ["{name}"]\n'
            (module_folder / "host.py").write_text('''from harness.host.workspaces import WorkspaceProvider
class Workspaces(WorkspaceProvider):
    def __init__(self, directory, settings):
        self.python_calls = 0
    def kinds(self): return ("''' + name + '''",)
    def kind(self, requested=None, text=None): return "''' + name + '''"
    def bench(self, kind): return "none"
    def tree(self, tree, kind): return tree
    def acquire(self, run, kind, **waiting): raise AssertionError("unexpected acquire")
    def builtin_skills(self, kind): return ("conversation",)
    def python(self, kind, log=print):
        import sys
        self.python_calls += 1
        return sys.executable
    def close(self): pass
''')
        (folder / "package.toml").write_text(manifest)
        if requirements:
            skill = folder / "skills" / "package-skill"
            skill.mkdir(parents=True)
            (skill / "skill.toml").write_text('name = "package-skill"\nsummary = "Test skill"\n'
                                               'mixin = "skills.package_skill:Mixin"\nexports = ["package_call"]\n'
                                               'embodiments = ["none"]\nrequirements = ["local-test-only==1"]\n')
        self.publish(self.registry, folder, log=lambda _: None)
        # Publishing changes the fixture registry after the manager may have cached it.
        self.app.packages._registry = None

    def test_empty_host_lists_catalog_and_installs_first_workspace_without_restart(self):
        self.package("first-workspace", workspace=True)
        self.assertEqual(self.app.workspaces.providers(), ())
        self.assertEqual(self.app.packages_state()["packages"], [])
        self.assertEqual(self.app.packages.registry.search("first-workspace")[0]["name"], "first-workspace")
        result = self.app.install_packages({"source": "first-workspace"})
        self.assertEqual(result["installed"][0]["name"], "first-workspace")
        self.assertEqual(result["packages"][0]["name"], "first-workspace")
        self.assertEqual(self.app.kind(), "first-workspace")
        self.assertIn("first-workspace", self.app.workspaces.kinds())
        self.assertIn("conversation", [skill["name"] for skill in result["skills"]])
        self.assertEqual(self.app.workspaces.provider("first-workspace").python_calls, 0)

    def test_multiple_providers_do_not_block_package_catalog_or_install(self):
        for name in ("first-workspace", "second-workspace"):
            self.package(name, workspace=True)
            self.app.install_packages({"source": name})
        with self.assertRaisesRegex(ValueError, "select --workspace"):
            self.app.kind()
        self.assertEqual(len(self.app.packages_state()["packages"]), 2)
        self.package("plain-package")
        result = self.app.install_packages({"source": "plain-package"})
        self.assertEqual(len(result["packages"]), 3)
        self.assertTrue(all(provider.python_calls == 0 for provider in self.app.workspaces.providers()))

    def test_kernel_is_requested_only_for_actual_skill_requirements(self):
        self.package("requirements-package", requirements=True)
        with patch("subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "select --workspace"):
                self.app.install_packages({"source": "requirements-package"})
        run.assert_not_called()
        self.assertEqual(self.app.packages_state()["packages"], [])
        self.package("first-workspace", workspace=True)
        self.app.install_packages({"source": "first-workspace"})
        provider = self.app.workspaces.provider("first-workspace")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            self.app.install_packages({"source": "requirements-package"})
        self.assertEqual(provider.python_calls, 1)
        self.assertIn("pip", run.call_args.args[0])

    def test_invalid_configuration_still_surfaces_for_an_unambiguous_workspace(self):
        self.package("first-workspace", workspace=True)
        self.app.install_packages({"source": "first-workspace"})
        with patch.object(self.app, "kind", side_effect=ValueError("invalid configured workspace")):
            with self.assertRaisesRegex(ValueError, "invalid configured workspace"):
                self.app.packages_state()

    def test_optional_custom_key_added_after_host_start_is_loaded(self):
        from harness import model_list, settings

        providers.save(self.app.directory, {"provider": "custom", "model": "local",
                                            "base_url": "http://127.0.0.1:1234/v1"})
        row, = model_list.models(self.app.directory)
        settings.change(self.app.directory, lambda values: values.setdefault("keys", {}).update(HARNESS_LLM_API_KEY="new-test-key"))
        class ReachedEnvironment(Exception):
            pass
        with patch.dict(os.environ, HARNESS_LLM_API_KEY=""), \
                patch.object(self.app, "environment", side_effect=ReachedEnvironment):
            with self.assertRaises(ReachedEnvironment):
                self.app.start(SimpleNamespace(), "hello", workspace="none", model_entry=row["id"])
            self.assertEqual(os.environ["HARNESS_LLM_API_KEY"], "new-test-key")


if __name__ == "__main__":
    unittest.main()
