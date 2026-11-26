"""The channel of an install (harness/channel.py): what the stable channel and the dev channel
each call their app, data, login item and port; what the installers' build puts into a dev
build (tools/installers/build.py), and the dev channel's update file (latest.py)."""
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import helpers
from harness import channel, cli, paths
from harness.host import login


def tool(name):
    spec = importlib.util.spec_from_file_location(f"installers_{name}", helpers.ROOT / "tools" / "installers" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Runtime(unittest.TestCase):
    """An installer's runtime in a temporary folder: this Python taken as its runtime/python."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.runtime = Path(folder.name) / "runtime"
        (self.runtime / "python").mkdir(parents=True)
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(paths.HOME_ENV, None)
        os.environ.pop(paths.DATA_ENV, None)
        prefix = mock.patch.object(sys, "prefix", str(self.runtime / "python"))
        prefix.start()
        self.addCleanup(prefix.stop)
        channel._marker.cache_clear()
        self.addCleanup(channel._marker.cache_clear)

    def mark(self, text):
        (self.runtime / "channel").write_text(text, encoding="utf-8")
        channel._marker.cache_clear()


class ChannelTests(Runtime):
    def test_an_install_without_a_channel_file_is_stable_and_keeps_its_names(self):
        from harness import __version__

        self.assertEqual((channel.name(), channel.product(), channel.version()), ("stable", "The Harness", __version__))
        self.assertEqual((channel.tag("harness"), channel.port(8780)), ("harness", 8780))
        self.assertEqual(paths.data(), Path("~/.harness").expanduser().resolve())
        self.assertEqual(paths.home(), Path("~/.cache/harness").expanduser().resolve())
        self.assertEqual(cli.version_line(), f"harness {__version__}")

    def test_a_checkout_or_a_pip_install_is_stable_whatever_lies_beside_it(self):
        self.mark("dev\n0.87.0-dev.412\n")
        with mock.patch.object(sys, "prefix", str(self.runtime.parent / "venv")):
            channel._marker.cache_clear()
            self.assertEqual(channel.name(), "stable")

    def test_the_dev_channel_has_its_own_names_data_port_and_version(self):
        self.mark("dev\n0.87.0-dev.412\n")
        self.assertEqual((channel.name(), channel.product(), channel.version()), ("dev", "The Harness Dev", "0.87.0-dev.412"))
        self.assertEqual((channel.tag("harness"), channel.tag("com.lmms-lab.harness", "."), channel.port(8780)),
                         ("harness-dev", "com.lmms-lab.harness.dev", 8781))
        self.assertEqual(paths.data(), Path("~/.harness-dev").expanduser().resolve())
        self.assertEqual(paths.home(), Path("~/.cache/harness-dev").expanduser().resolve())
        self.assertEqual(cli.version_line(), "harness-dev 0.87.0-dev.412 (dev channel)")

    def test_the_folders_given_in_the_environment_win_on_any_channel(self):
        self.mark("dev\n0.87.0-dev.412\n")
        os.environ[paths.DATA_ENV] = str(self.runtime / "data")
        os.environ[paths.HOME_ENV] = str(self.runtime / "home")
        self.assertEqual((paths.data(), paths.home()), ((self.runtime / "data").resolve(), (self.runtime / "home").resolve()))

    def test_a_file_that_names_no_channel_is_taken_as_stable(self):
        for text in ("", "../elsewhere\n", "Dev\n", "dev-2\n"):
            self.mark(text)
            self.assertEqual(channel.name(), "stable", text)

    def test_each_channel_has_a_login_item_of_its_own(self):
        self.assertEqual((login.NAME, login.LABEL, login.UNIT),
                         ("The Harness host", "com.lmms-lab.harness.host", "harness-host.service"))
        self.mark("dev\n0.87.0-dev.412\n")
        try:
            dev = importlib.reload(login)
            named = (dev.NAME, dev.LABEL, dev.UNIT)
        finally:
            # the module as every other test has it: read again on the stable channel
            (self.runtime / "channel").unlink()
            channel._marker.cache_clear()
            importlib.reload(login)
        self.assertEqual(named, ("The Harness Dev host", "com.lmms-lab.harness.dev.host", "harness-dev-host.service"))
        self.assertEqual(login.NAME, "The Harness host")


class TerminalCommandTests(Runtime):
    """The app's terminal command (packages/app/harness_app/shell.py) on each channel."""

    def test_the_dev_channels_command_and_shell_have_its_names(self):
        sys.path.insert(0, str(helpers.ROOT / "packages" / "app"))
        self.addCleanup(sys.path.remove, str(helpers.ROOT / "packages" / "app"))
        from harness_app import shell

        self.assertEqual((shell.PRODUCT, shell.BINARY, shell.COMMAND), ("The Harness", "the-harness", "harness"))
        self.mark("dev\n0.87.0-dev.412\n")
        try:
            dev = importlib.reload(shell)
            named = (dev.PRODUCT, dev.BINARY, dev.COMMAND, dev.LINK.name)
            # another install of the same channel says its build after its name, its channel last
            answer = mock.Mock(returncode=0, stdout="harness-dev 0.87.0-dev.400 (dev channel)\n")
            with mock.patch("subprocess.run", return_value=answer):
                asked = dev._version(self.runtime / "elsewhere" / "harness-dev")
        finally:
            (self.runtime / "channel").unlink()
            channel._marker.cache_clear()
            importlib.reload(shell)
        self.assertEqual(named, ("The Harness Dev", "the-harness-dev", "harness-dev", "harness-dev"))
        self.assertEqual(asked, "0.87.0-dev.400")


class BuildTests(Runtime):
    def setUp(self):
        super().setUp()
        self.build = tool("build")
        os.environ.pop("TAURI_SIGNING_PRIVATE_KEY", None)

    def test_a_stable_build_puts_only_the_version_and_the_key_over_the_configuration(self):
        config = self.build.configuration()
        self.assertEqual(set(config), {"version", "plugins", "bundle"})
        self.assertEqual(config["version"], self.build.version())
        self.assertEqual(set(config["plugins"]["updater"]), {"pubkey"})
        self.assertEqual(set(config["bundle"]), {"createUpdaterArtifacts"})

    def test_a_dev_build_is_an_app_of_its_own(self):
        shell = self.runtime.parent / "shell"
        (shell / "src-tauri" / "linux").mkdir(parents=True)
        (shell / "src-tauri" / "linux" / "harness").write_bytes(
            (self.build.SHELL / "src-tauri" / "linux" / "harness").read_bytes())
        with mock.patch.object(self.build, "SHELL", shell):
            config = self.build.configuration("dev", 412)
        core = self.build.version()
        self.assertEqual((config["version"], config["productName"], config["mainBinaryName"], config["identifier"]),
                         (f"{core}-dev.412", "The Harness Dev", "the-harness-dev", "com.lmms-lab.harness.dev"))
        self.assertEqual(config["plugins"]["updater"]["endpoints"],
                         ["https://github.com/EvolvingLMMs-Lab/the-harness/releases/download/dev/latest.json"])
        # its own icon, every file of which is in the repository
        self.assertEqual(config["bundle"]["icon"][-1], "icons/dev/icon.ico")
        for icon in [*config["bundle"]["icon"], config["bundle"]["windows"]["nsis"]["installerIcon"]]:
            self.assertTrue((self.build.SHELL / "src-tauri" / icon).is_file(), icon)
        # its own terminal command in the .deb, not the stable one's
        files = config["bundle"]["linux"]["deb"]["files"]
        self.assertEqual(files, {"/usr/bin/harness": None, "/usr/bin/harness-dev": "target/channel/harness-dev"})
        script = (shell / "src-tauri" / "target" / "channel" / "harness-dev").read_text(encoding="utf-8")
        self.assertIn('["/usr/bin/the-harness-dev", "--host"]', script)
        self.assertIn('"/usr/lib/The Harness Dev/runtime/python/bin/python3" -m harness', script)

    def test_what_the_build_names_a_channel_is_what_the_harness_derives_at_run_time(self):
        self.mark("dev\n0.87.0-dev.412\n")
        called = self.build.names("dev")
        self.assertEqual((called["product"], called["command"], called["binary"], called["identifier"]),
                         (channel.product(), channel.tag("harness"), channel.tag("the-harness"),
                          channel.tag("com.lmms-lab.harness", ".")))

    def test_a_dev_build_needs_its_number_and_its_signature(self):
        with self.assertRaises(SystemExit) as refused:
            self.build.build_version("dev", None)
        self.assertIn("--build-number", str(refused.exception))
        with mock.patch.object(self.build, "configuration", return_value={"bundle": {"createUpdaterArtifacts": False}}), \
                mock.patch.object(self.build, "run") as run, self.assertRaises(SystemExit) as unsigned:
            self.build.tauri("x86_64-pc-windows-msvc", "nsis", "dev", 412)
        self.assertIn("always signed", str(unsigned.exception))
        run.assert_not_called()


class MacUpdateNameTests(unittest.TestCase):
    def test_the_mac_update_bundle_is_named_by_its_architecture_on_both_channels(self):
        build = tool("build")
        for product in ("The Harness", "The Harness Dev"):
            with tempfile.TemporaryDirectory() as folder:
                macos = Path(folder) / "macos"
                macos.mkdir()
                (macos / f"{product}.app.tar.gz").write_bytes(b"bundle")
                (macos / f"{product}.app.tar.gz.sig").write_text("signature", encoding="utf-8")
                build.name_mac_update(Path(folder), "aarch64-apple-darwin")
                self.assertEqual(sorted(path.name for path in macos.iterdir()),
                                 [f"{product}_aarch64.app.tar.gz", f"{product}_aarch64.app.tar.gz.sig"])
                build.name_mac_update(Path(folder), "x86_64-pc-windows-msvc")  # not a Mac: nothing changes
                self.assertEqual(len(list(macos.iterdir())), 2)


class LatestTests(unittest.TestCase):
    def test_the_dev_channels_update_file_names_its_own_signed_bundles(self):
        latest = tool("latest")
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            signed = ("The Harness Dev_0.87.0-dev.412_x64-setup.exe", "The Harness Dev_aarch64.app.tar.gz",
                      "The Harness Dev_0.87.0-dev.412_amd64.AppImage")
            for name in signed:
                (folder / name).write_bytes(b"bundle")
                (folder / f"{name}.sig").write_text(f"signature of {name}\n", encoding="utf-8")
            (folder / "The Harness Dev_0.87.0-dev.412_amd64.deb").write_bytes(b"unsigned")
            found = latest.latest("0.87.0-dev.412", folder, "https://example.test/releases/download/dev/",
                                  "The Harness Dev")
        self.assertEqual((found["version"], found["notes"]), ("0.87.0-dev.412", "The Harness Dev 0.87.0-dev.412"))
        self.assertEqual(set(found["platforms"]), {"windows-x86_64", "windows-x86_64-nsis", "darwin-aarch64",
                                                   "linux-x86_64", "linux-x86_64-appimage"})
        windows = found["platforms"]["windows-x86_64"]
        self.assertEqual(windows["url"],
                         "https://example.test/releases/download/dev/The.Harness.Dev_0.87.0-dev.412_x64-setup.exe")
        self.assertEqual(windows["signature"], "signature of The Harness Dev_0.87.0-dev.412_x64-setup.exe")


class PathLinkTests(unittest.TestCase):
    def test_a_dangling_junction_or_symlink_is_replaced_without_file_exists_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_target = root / "old"
            new_target = root / "new"
            old_target.mkdir()
            new_target.mkdir()
            link = root / "links" / "harness"
            link.parent.mkdir(parents=True)
            if os.name == "nt":
                import _winapi

                _winapi.CreateJunction(str(old_target), str(link))
                old_target.rmdir()
                self.assertFalse(link.exists())
                with mock.patch.object(Path, "symlink_to", side_effect=OSError("no symlink privilege")):
                    paths._link(new_target, link)
            else:
                link.symlink_to(old_target, target_is_directory=True)
                old_target.rmdir()
                self.assertFalse(link.exists())
                paths._link(new_target, link)
            self.assertEqual(link.resolve(), new_target.resolve())


if __name__ == "__main__":
    unittest.main()
