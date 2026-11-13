"""Offline preparation prepares the terminal without a model, workspace or registry download."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from harness import cli


class PrepareTests(unittest.TestCase):
    def test_terminal_only_preparation_needs_no_package_or_model(self):
        args = cli.parser(packages=False).parse_args(["install", "--tui", "--json"])
        packages = Mock()
        packages.project.return_value = None
        environment = SimpleNamespace(directory=Path("/prepared/tui"))
        with patch("harness.packages.Packages", return_value=packages), \
                patch("harness.packages.activate", return_value=packages), \
                patch("harness.bench.bench_specs", return_value={}), \
                patch("harness.services.placement.load_deploy", return_value=SimpleNamespace(services={})), \
                patch("harness.tui.environment", return_value=environment), \
                patch("harness.packages.environments.install") as install, \
                patch.object(cli, "output") as output:
            self.assertEqual(cli._install(args), 0)
        install.assert_called_once_with(environment, log=cli._note)
        packages.install.assert_not_called()
        self.assertEqual(output.call_args.args[0]["provisioned"], [
            {"name": "tui", "what": "frontend", "installed": True, "environment": "/prepared/tui"}])

    def test_terminal_preparation_is_not_silently_ignored_with_update(self):
        args = cli.parser(packages=False).parse_args(["install", "--tui", "--update"])
        with self.assertRaisesRegex(cli.UsageError, "--tui.*--update"):
            cli._install(args)


if __name__ == "__main__":
    unittest.main()
