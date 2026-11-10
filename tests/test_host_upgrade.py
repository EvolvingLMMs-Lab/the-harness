"""An old running host cannot bypass a new client's execution contract."""
from contextlib import nullcontext
import unittest
from unittest import mock
import helpers
from harness.host import Host, _same_code, identity


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


if __name__ == '__main__':
    unittest.main()
