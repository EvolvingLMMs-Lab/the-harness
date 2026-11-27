"""The session host's command search path on startup."""

import os
import unittest
from unittest.mock import patch

import helpers  # noqa: F401  (puts the checkout on the path)
from harness.host import server


class HostPathTests(unittest.TestCase):
    def start(self, platform, path):
        env = {} if path is None else {"PATH": path}
        with patch.object(server.sys, "platform", platform), patch.dict(os.environ, env, clear=True):
            with patch.object(server, "serve", side_effect=lambda **_: os.environ.get("PATH")):
                return server.main([])

    def test_macos_gui_path_gains_both_homebrew_locations(self):
        system = os.pathsep.join(("/usr/bin", "/bin", "/usr/sbin", "/sbin"))
        self.assertEqual(self.start("darwin", system), os.pathsep.join((system, "/opt/homebrew/bin", "/usr/local/bin")))

    def test_macos_preserves_command_precedence_and_does_not_repeat_entries(self):
        path = os.pathsep.join(("/custom/bin", "/usr/local/bin", "/opt/homebrew/bin", "/usr/bin"))
        self.assertEqual(self.start("darwin", path), path)

    def test_macos_without_path_keeps_system_commands_available(self):
        self.assertEqual(self.start("darwin", None), os.pathsep.join((os.defpath, "/opt/homebrew/bin", "/usr/local/bin")))

    def test_other_platforms_keep_their_path(self):
        for platform, path in (("linux", "/custom/bin:/usr/bin"), ("win32", r"C:\Windows;C:\Tools")):
            with self.subTest(platform=platform):
                self.assertEqual(self.start(platform, path), path)
