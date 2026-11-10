"""Unchosen computer preferences cannot silently start a workspace. Where a conversation
works is chosen per conversation (test_environment_choice.py); computer.mode is only the
computer kind that choice highlights."""
import asyncio
import io
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest import mock

import helpers
from harness import cli
from harness.settings import ChoiceRequired, Settings, read, write
from harness.host import Host
from harness.host.tasks import TaskHost, TaskServer, PoolPlace
from harness_computer.host import Workspaces
from harness_computer.first_use import require, for_workspace


class FirstUseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = Settings(self.root)
        self.computer = Workspaces(self.root, self.settings)
        self.addCleanup(self.computer.close)

    def missing(self, call, section, key):
        with self.assertRaises(ChoiceRequired) as found:
            call()
        self.assertEqual((found.exception.choice['section'], found.exception.choice['key']), (section, key))
        return found.exception.choice

    def test_preselected_kind_is_read_without_saving_or_starting_anything(self):
        self.assertEqual(self.settings.get()['computer']['mode'], 'browser')
        self.assertEqual(self.computer.kind(), 'browser')
        self.assertEqual(read(self.root), {})
        self.assertFalse(self.computer.pool.workers)

    def test_saved_and_command_line_modes_do_not_ask(self):
        self.assertEqual(self.computer.kind('desktop'), 'desktop')
        self.assertEqual(read(self.root), {})  # per-task choice is not a global preference
        self.settings.update({'computer': {'mode': 'apps'}})
        self.assertEqual(self.computer.kind(), 'apps')
        self.assertEqual(self.computer.kind('browser'), 'browser')

    def test_invalid_saved_mode_is_never_offered_as_the_users_choice(self):
        write(self.root, {'computer': {'mode': 'removed-mode'}})
        self.assertIn(self.computer.kind(), self.computer.kinds())
        with mock.patch.dict(os.environ, {'HARNESS_DATA': str(self.root)}):
            app = TaskHost(self.root)
            self.addCleanup(app.close)
            self.assertIsNone(app.environments()['selected'])

    def test_desktop_decisions_are_independent_and_persist(self):
        self.missing(lambda: for_workspace(self.settings, 'desktop'), 'physical', 'level')
        self.settings.update({'physical': {'level': 'never'}})
        self.missing(lambda: for_workspace(self.settings, 'desktop'), 'privacy', 'level')
        self.settings.update({'privacy': {'level': 'none'}})
        for_workspace(Settings(self.root), 'desktop')
        for_workspace(Settings(self.root), 'apps')

    def test_background_browser_does_not_ask_for_physical_input(self):
        for_workspace(self.settings, 'browser')
        self.assertNotIn('physical', read(self.root))

    def test_runtime_overrides_are_explicit_but_not_remembered(self):
        runtime = {'physical': {'level': 'never'}, 'privacy': {'level': 'none'}}
        for_workspace(self.settings, 'desktop', runtime)
        self.assertNotIn('physical', read(self.root))
        self.missing(lambda: for_workspace(self.settings, 'desktop'), 'physical', 'level')

    def test_recording_defaults_off_without_a_first_use_question(self):
        for_workspace(self.settings, 'browser')
        self.assertEqual(self.settings.get()['computer']['record_screen'], 'off')
        self.assertEqual(read(self.root), {})
        self.settings.update({'computer': {'record_screen': 'on'}})
        for_workspace(self.settings, 'browser')
        self.assertEqual(self.settings.get()['computer']['record_screen'], 'on')

    def test_rules_alone_do_not_select_a_global_input_policy(self):
        self.settings.update({'physical': {'rules': [{'level': 'never', 'app': 'private-app'}]}})
        self.missing(lambda: for_workspace(self.settings, 'desktop'), 'physical', 'level')

    def test_http_reports_choice_without_creating_task_then_remembers_selection(self):
        with mock.patch.dict(os.environ, {'HARNESS_DATA': str(self.root), 'OPENROUTER_API_KEY': 'test-no-network'}):
            app = TaskHost(self.root)
            self.addCleanup(app.close)
            server = TaskServer(('127.0.0.1', 0), app, token='test')
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            host = Host(f'http://127.0.0.1:{server.server_port}', 'test')
            with mock.patch.object(app, 'config') as config, mock.patch.object(app.packages, 'ensure') as ensure:
                choice = self.missing(lambda: host.task('inspect desktop'), 'session', 'environment')
                self.assertTrue(choice['options'])
                self.assertEqual(list(app.conversations_dir.iterdir()), [])
                config.assert_not_called()
                ensure.assert_not_called()
                # Naming the desktop for this conversation saves no preference and still
                # needs the user's own answer on their real mouse and keyboard.
                self.missing(lambda: host.task('inspect desktop', 'desktop'), 'physical', 'level')
                self.assertNotIn('computer', read(self.root))
                config.assert_not_called()
                ensure.assert_not_called()

    def test_child_cannot_allocate_unselected_desktop(self):
        app = SimpleNamespace(workspaces=SimpleNamespace(require_choices=self.computer.require_choices,
                                                        bind=mock.Mock(), acquire=mock.Mock()))
        place = PoolPlace(app, None, ['desktop'], True)
        child = SimpleNamespace(config=SimpleNamespace(runtime={}))
        self.missing(lambda: place.begin(child, 'desktop', None), 'physical', 'level')
        app.workspaces.bind.assert_not_called()
        app.workspaces.acquire.assert_not_called()

    def test_cli_empty_answer_does_not_accept_a_default(self):
        choice = self.missing(lambda: require(self.settings, 'privacy', 'level'), 'privacy', 'level')
        host = mock.Mock()
        with mock.patch('harness.host.Host.connect', return_value=host), \
                mock.patch('builtins.input', side_effect=['', '99', '1']), \
                mock.patch('sys.stderr', io.StringIO()):
            cli._choose_first_use(choice)
        host.post.assert_called_once_with('/api/app/settings', {'privacy': {'level': 'none'}})

    def test_cli_cancel_leaves_settings_unselected(self):
        choice = self.missing(lambda: require(self.settings, 'privacy', 'level'), 'privacy', 'level')
        with mock.patch('harness.host.Host.connect') as host, mock.patch('builtins.input', return_value='q'), \
                mock.patch('sys.stderr', io.StringIO()):
            with self.assertRaises(cli.UsageError):
                cli._choose_first_use(choice)
        host.assert_not_called()
        self.assertEqual(read(self.root), {})

    def test_json_and_noninteractive_runs_report_missing_choice_without_prompting(self):
        choice = self.missing(lambda: require(self.settings, 'privacy', 'level'), 'privacy', 'level')
        for flags, tty in ((['--json'], True), ([], False)):
            with self.subTest(flags=flags), mock.patch('harness.cli._ready_model'), \
                    mock.patch('harness.cli._starter', return_value=mock.Mock(side_effect=ChoiceRequired(choice))), \
                    mock.patch('harness.cli._choose_first_use') as choose, \
                    mock.patch('sys.stdin.isatty', return_value=tty), \
                    mock.patch('sys.stdout.isatty', return_value=tty), \
                    mock.patch('sys.stderr', io.StringIO()) as errors:
                self.assertEqual(cli.main(['run', 'inspect desktop', *flags]), 2)
                self.assertIn('choice_required', errors.getvalue())
                choose.assert_not_called()


class TuiChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_placeholder_then_cancel_does_not_save(self):
        from harness.tui.chat import Chat
        choice = {'section': 'computer', 'key': 'mode', 'title': 'Where?',
                  'options': [{'value': 'browser', 'label': 'Background browser'}]}
        async def view(coroutine):
            return await coroutine
        chat = SimpleNamespace(_view=view, _host=mock.Mock())
        with mock.patch('harness.tui.chat.views.choose', side_effect=[0, None]) as choose:
            self.assertFalse(await Chat._choose_first_use(chat, choice))
        self.assertEqual(choose.await_count, 2)
        chat._host.assert_not_called()

    async def test_explicit_pick_is_saved_to_host(self):
        from harness.tui.chat import Chat
        host = mock.Mock()
        choice = {'section': 'physical', 'key': 'level', 'title': 'Input?',
                  'options': [{'value': 'never', 'label': 'Never'}]}
        async def view(coroutine):
            return await coroutine
        chat = SimpleNamespace(_view=view, _host=lambda: host)
        with mock.patch('harness.tui.chat.views.choose', return_value=1):
            self.assertTrue(await Chat._choose_first_use(chat, choice))
        host.post.assert_called_once_with('/api/app/settings', {'physical': {'level': 'never'}})


if __name__ == '__main__':
    unittest.main()
