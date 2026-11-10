"""Desktop has no background API, including at the worker boundary."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock
import helpers
from harness.settings import Settings
from harness_computer.host import Workspaces
from harness.runtime.decision.prompts import assemble_prompt
from harness.runtime.execution.skills import load_skills, namespace
from benches.computer.runtime import ComputerEnvironment


class DesktopModeTests(unittest.TestCase):
    def test_workspace_configuration_and_prompt_separate_background_tools(self):
        with tempfile.TemporaryDirectory() as root:
            provider = Workspaces(root, Settings(root))
            self.addCleanup(provider.close)
            # Configuration routing is independent of a machine's VM availability.
            provider.kind = lambda kind: kind
            for kind in ('desktop', 'apps', 'display', 'browser'):
                with self.subTest(kind=kind):
                    tree = provider.tree({'overrides': {'agent': {'prompt': {}}}}, kind)
                    skills = tree['overrides']['agent']['desktop']['skills']
                    enabled = ['desktop', *provider.extra_skills(kind)]
                    if kind == 'desktop':
                        self.assertIn('windowtools', skills['disable'])
                        self.assertIn('browser', skills['disable'])
                        self.assertNotIn('windowtools', enabled)
                    else:
                        self.assertIn('windowtools', enabled)
                    if kind != 'browser':
                        text = assemble_prompt(Path(tree['overrides']['agent']['prompt']['desktop']), enabled)
                        self.assertEqual('use_window(' in text, kind != 'desktop')
                        self.assertEqual('act(' in text, kind != 'desktop')

    def test_desktop_namespace_has_only_screen_input(self):
        known = load_skills()
        session = SimpleNamespace(embodiment='desktop', profile={})
        for name in known['desktop'].exports:
            setattr(session, name, mock.Mock())
        session.screen = (100, 100)
        session._wrap_up = mock.Mock()
        api = namespace(session, ['desktop'])
        self.assertTrue({'click', 'drag', 'press', 'type_text', 'get_observation'} <= api.keys())
        self.assertFalse({'windows', 'use_window', 'launch', 'elements', 'act'} & api.keys())
        session._input = mock.Mock()
        api['click'](10, 20)
        session._input.assert_called_with('click', {'type': 'click', 'x': 10, 'y': 20, 'button': 'left', 'count': 1})
        with self.assertRaises(TypeError):
            api['click'](10, 20, window='w1')
        for profile in ({'windows': True}, {'elements': True}):
            session.profile = profile
            background = namespace(session, ['desktop'])
            background['click'](10, 20, window='w1')
            self.assertEqual(session._input.call_args.args[1]['window'], 'w1')

    def test_managed_desktop_has_no_background_operations(self):
        from harness_computer.dispatch import DESKTOP, BROWSER
        self.assertFalse({'windows', 'use_window', 'elements', 'act'} & set(DESKTOP))
        self.assertTrue({'elements', 'act', 'navigate'} <= set(BROWSER))

    def test_desktop_rejects_window_commands_before_dispatch(self):
        worker = ComputerEnvironment.__new__(ComputerEnvironment)
        worker._workspace = 'desktop'
        worker._cursor = mock.Mock()
        worker._approvals = mock.Mock()
        worker._ended = lambda: False
        worker._managed_approval = False
        worker._refused = lambda reason: {'executed': False, 'reason': reason}
        worker._window_tick = mock.Mock(side_effect=AssertionError('background dispatch'))
        worker._workspace_tick = mock.Mock(side_effect=AssertionError('background launch'))
        commands = [{'type': name} for name in ('act', 'use_window', 'launch')]
        commands += [{'type': name, 'window': 'w1'} for name in ('click', 'key', 'type', 'drag', 'scroll')]
        for command in commands:
            with self.subTest(command=command):
                worker._shield = SimpleNamespace(check=lambda _: SimpleNamespace(command=command))
                result = worker._tick(SimpleNamespace(episode_id='test', step=0, command=command,
                                                      pending=None, execution_id=None), None)
                self.assertFalse(result['executed'])
                self.assertEqual(result['reason']['check'], 'workspace')
        for method in (worker._call_windows, worker._call_elements):
            with self.assertRaisesRegex(RuntimeError, 'not window tools'):
                method('test')

    def test_apps_still_dispatches_window_actions(self):
        worker = ComputerEnvironment.__new__(ComputerEnvironment)
        worker._workspace = 'apps'
        worker._cursor = mock.Mock()
        worker._approvals = mock.Mock()
        worker._ended = lambda: False
        worker._managed_approval = False
        worker._window_tick = mock.Mock(return_value='background delivered')
        command = {'type': 'act', 'element': 'e1'}
        worker._shield = SimpleNamespace(check=lambda _: SimpleNamespace(command=command))
        self.assertEqual(worker._tick(SimpleNamespace(episode_id='test', step=0, command=command,
                                                     pending=None, execution_id=None), None), 'background delivered')


if __name__ == '__main__':
    unittest.main()
