"""An old running host cannot bypass a new client's execution contract."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import helpers
from harness.host import Host, _same_code, identity, installed_packages
from harness.host.server import HostServer
from harness.packages import Packages


class UpgradeTests(unittest.TestCase):
    def old(self, running=True):
        return mock.Mock(state={'version': '0.78.2', 'source': 'old-checkout', 'running': running})

    def test_busy_old_host_rejects_new_work_without_stopping_sessions(self):
        host = self.old()
        with self.assertRaisesRegex(RuntimeError, 'New tasks were not submitted'):
            _same_code(host, mock.Mock())
        host.stop.assert_not_called()
        host.post.assert_not_called()

    def test_read_only_connection_can_still_manage_old_sessions(self):
        host = self.old()
        with mock.patch('harness.host.read_address'), mock.patch('harness.host._reachable', return_value=host):
            self.assertIs(Host.connect(start=False), host)
        host.stop.assert_not_called()

    def test_host_appearing_inside_start_lock_is_also_checked(self):
        host = self.old()
        with mock.patch('harness.host.read_address'), \
                mock.patch('harness.host._reachable', side_effect=[None, host]), \
                mock.patch('harness.host._start_lock', return_value=nullcontext()), \
                mock.patch('harness.host._spawn') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'New tasks were not submitted'):
                Host.connect()
            spawn.assert_not_called()

    def test_idle_old_host_can_be_replaced(self):
        host = self.old(False)
        with mock.patch('harness.host.wait_until', return_value=True):
            self.assertIsNone(_same_code(host, mock.Mock()))
        host.stop.assert_called_once_with()

    def test_failed_shutdown_cannot_start_second_host(self):
        host = self.old(False)
        with mock.patch('harness.host.wait_until', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'no replacement'):
                _same_code(host, mock.Mock())

    def test_current_host_reused(self):
        host = mock.Mock(state={**identity(), 'running': True})
        self.assertIs(_same_code(host, mock.Mock()), host)
        host.stop.assert_not_called()


class PackageChangeTests(unittest.TestCase):
    """A host loads the packages once: one installed, removed or updated by another process
    (harness install, remove) reaches new conversations through a new host."""

    loaded = ['computer 0.5.14 /cache/packages/computer/0.5.14-a']

    def current(self, running=False, packages=None):
        return mock.Mock(state={**identity(), 'running': running,
                                'packages': self.loaded if packages is None else packages})

    def test_an_idle_host_of_other_packages_is_replaced(self):
        host, log = self.current(), mock.Mock()
        with mock.patch('harness.host.installed_packages', return_value=[]), \
                mock.patch('harness.host.wait_until', return_value=True):
            self.assertIsNone(_same_code(host, log))
        host.stop.assert_called_once_with()
        self.assertIn('restarting the session host', log.call_args.args[0])

    def test_a_busy_host_of_other_packages_goes_on(self):
        host, log = self.current(running=True), mock.Mock()
        with mock.patch('harness.host.installed_packages', return_value=[]):
            self.assertIs(_same_code(host, log), host)
        host.stop.assert_not_called()
        self.assertIn('until its sessions end', log.call_args.args[0])

    def test_a_package_list_that_cannot_be_read_keeps_the_host(self):
        host = self.current()
        with mock.patch('harness.host.installed_packages', side_effect=ValueError('config.toml: bad TOML')):
            self.assertIs(_same_code(host, mock.Mock()), host)
        host.stop.assert_not_called()

    def test_a_host_of_the_installed_packages_is_reused(self):
        host = self.current()
        with mock.patch('harness.host.installed_packages', return_value=list(self.loaded)):
            self.assertIs(_same_code(host, mock.Mock()), host)
        host.stop.assert_not_called()

    def test_the_installed_packages_are_the_users_enabled_ones_in_name_order(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'config.toml').write_text(
                '[packages.installed.workspace]\nversion = "0.2.1"\npath = "/p/workspace"\n\n'
                '[packages.installed.browser]\nversion = "0.5.1"\npath = "/p/browser"\n\n'
                '[packages.installed.game]\nversion = "0.5.1"\npath = "/p/game"\nenabled = false\n',
                encoding='utf-8')
            self.assertEqual(installed_packages(Path(directory)),
                             ['browser 0.5.1 /p/browser', 'workspace 0.2.1 /p/workspace'])

    def test_a_package_the_host_adds_itself_counts_as_loaded_and_a_removal_does_not(self):
        server = SimpleNamespace(loaded=['a 1 /a'], app=SimpleNamespace(directory='.'))
        with mock.patch('harness.host.server.installed_packages', return_value=['a 1 /a', 'b 1 /b']):
            HostServer._packages_changed(server)
        self.assertEqual(server.loaded, ['a 1 /a', 'b 1 /b'])
        for now in (['b 1 /b'], ['a 2 /a2', 'b 1 /b']):
            with mock.patch('harness.host.server.installed_packages', return_value=now):
                HostServer._packages_changed(server)
            self.assertEqual(server.loaded, ['a 1 /a', 'b 1 /b'])

    def test_a_change_of_packages_tells_who_asked(self):
        packages, told = Packages('.'), mock.Mock()
        packages.on_change = told
        with mock.patch('harness.packages.manager.activate') as activate:
            packages.changed()
        activate.assert_called_once_with(packages)
        told.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
