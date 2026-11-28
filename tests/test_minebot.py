"""The minebot package without a game server, a download or a model: what it ships, how it
reads its settings, what it would install and start, and that it stops only what it started."""
import json
import os
from pathlib import Path
import struct
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import helpers
from harness.packages import archive, manifest

PACKAGE = helpers.ROOT / "packages" / "minebot"
sys.path.insert(0, str(PACKAGE))

from harness_minebot import config, ping, provision, stack, window  # noqa: E402


class Shipped(unittest.TestCase):
    """What goes into the package's file."""

    def setUp(self):
        self.files = [path.relative_to(PACKAGE).as_posix() for path in archive.files(PACKAGE)]

    def test_manifest_names_what_it_provides(self):
        package = manifest.load(PACKAGE)
        self.assertEqual(package.name, "minebot")
        self.assertEqual(package.provides["workspaces"], ("minebot",))
        self.assertEqual(package.provides["commands"], ("minebot",))
        self.assertEqual(package.provides["kinds"], ("botbody",))
        self.assertIn("mineflayer", package.provides["benches"])

    def test_nothing_of_the_game_is_shipped(self):
        # The one jar is the window mod, built from the source beside it: its classes are this package's.
        jars = [name for name in self.files if name.endswith(".jar")]
        self.assertEqual(jars, ["window/libs/harness-camera-0.1.0.jar"])
        import zipfile

        with zipfile.ZipFile(PACKAGE / jars[0]) as jar:
            classes = [name for name in jar.namelist() if name.endswith(".class")]
        self.assertTrue(classes and all(name.startswith("harness/camera/") for name in classes), classes)
        for name in self.files:
            lowered = name.lower()
            self.assertFalse(any(part in lowered for part in ("datapack", "loot_tables", "server.properties", "eula", "dig-rules")),
                             name)
            self.assertFalse(lowered.endswith((".mcfunction", ".mcmeta", ".dat", ".mca", ".nbt")), name)

    def test_the_disclaimer_is_in_what_people_read(self):
        text = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn("NOT AN OFFICIAL MINECRAFT PRODUCT", text)
        self.assertIn("NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT", text)

    def test_no_path_of_a_computer_is_in_a_file(self):
        for name in self.files:
            if name.endswith((".jar", "package-lock.json")):
                continue
            text = (PACKAGE / name).read_text(encoding="utf-8", errors="replace")
            for sign in ("C:\\Users", "C:/Users", "/home/", "/Users/"):
                self.assertNotIn(sign, text, name)

    def test_the_body_requires_only_what_its_lockfile_pins(self):
        lock = json.loads((PACKAGE / "body" / "package-lock.json").read_text(encoding="utf-8"))["packages"]
        declared = json.loads((PACKAGE / "body" / "package.json").read_text(encoding="utf-8"))["dependencies"]
        self.assertEqual(sorted(lock[""]["dependencies"]), sorted(declared))
        for name, row in lock.items():
            # Nothing is fetched over a login of its own (git over ssh), nor from anywhere but the registry and a pinned archive.
            self.assertNotIn("git+ssh", str(row.get("resolved")), name)
            if row.get("resolved"):
                # ... and from a project's own repository, never from a copy under someone's account.
                self.assertRegex(row["resolved"], r"^https://(registry\.npmjs\.org/|github\.com/PrismarineJS/)", name)
        for script in ("bridge.js", "body.js", "nav.js", "dig_rules.js"):
            text = (PACKAGE / "body" / script).read_text(encoding="utf-8")
            import re

            for required in re.findall(r"require\('([^'.][^']*)'\)", text):
                top = required.split("/")[0]
                if top in ("http", "fs", "path", "child_process", "events", "net", "perf_hooks"):
                    continue
                self.assertIn(top, declared, f"{script} requires {required}")


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(self.tmp.name) / "data"),
                                             "HARNESS_HOME": str(Path(self.tmp.name) / "home")})
        patch.start()
        self.addCleanup(patch.stop)

    def test_defaults_and_a_run_s_own_values(self):
        values = config.settings()
        self.assertEqual((values["host"], values["port"], values["auth"], values["window"]), ("127.0.0.1", 25565, "offline", "off"))
        values = config.settings({"host": "play.example.org", "port": "25570", "auth": "microsoft"})
        self.assertEqual((values["host"], values["port"], values["auth"]), ("play.example.org", 25570, "microsoft"))

    def test_a_value_a_setting_does_not_take_is_refused(self):
        for overrides in ({"port": "many"}, {"port": "70000"}, {"auth": "none"}, {"nothing": "1"}):
            with self.assertRaises(ValueError):
                config.settings(overrides)

    def test_a_command_of_the_server_s_owner(self):
        self.assertIsNone(config.command(""))
        self.assertEqual(config.command('python "my tools/new world.py" --seed 7'), ["python", "my tools/new world.py", "--seed", "7"])
        self.assertEqual(config.command('["C:\\\\tools\\\\world.exe", "new"]'), ["C:\\tools\\world.exe", "new"])
        with self.assertRaises(ValueError):
            config.command('[1, 2]')

    def test_the_command_port_s_password_is_never_a_setting(self):
        self.assertNotIn("rcon_password", config.schema())
        values = config.settings({"rcon_port": "25575"})
        with mock.patch.dict(os.environ, {config.RCON_PASSWORD: ""}):
            self.assertEqual(config.rcon(values), {})
        with mock.patch.dict(os.environ, {config.RCON_PASSWORD: "secret"}):
            self.assertEqual(config.rcon(values), {"MC_RCON_PORT": "25575", "MC_RCON_PASSWORD": "secret"})

    def test_the_worker_is_given_the_owner_s_commands_only_where_there_are_some(self):
        plain = stack.worker_options(config.settings({"username": "sam"}), instruction="Play.")
        self.assertEqual(plain["player"], "sam")
        self.assertFalse({"start_over", "keep_start", "kept_info"} & set(plain))
        hooked = stack.worker_options(config.settings({"start_over": "python world.py new", "keep_start": '["python", "world.py", "keep"]'}))
        self.assertEqual(hooked["start_over"], ["python", "world.py", "new"])
        self.assertEqual(hooked["keep_start"], ["python", "world.py", "keep"])

    def test_the_bridge_is_told_the_connection(self):
        values = config.settings({"host": "play.example.org", "port": "25570", "auth": "microsoft", "username": "sam@example.org"})
        env = stack.bridge_environment(values, "1.20.4", store=Path(self.tmp.name) / "store")
        self.assertEqual((env["MC_HOST"], env["MC_PORT"], env["MC_VERSION"], env["MC_AUTH"], env["MC_USER"]),
                         ("play.example.org", "25570", "1.20.4", "microsoft", "sam@example.org"))
        self.assertNotIn("VIEW_PORT", env)          # no window: the body does not wait for one
        self.assertNotIn("MINEBOT_DIG_RULES", env)  # no table of dig times comes with the package
        self.assertTrue(env["NODE_PATH"].endswith("node_modules"))
        self.assertIn("VIEW_PORT", stack.bridge_environment(config.settings({"window": "on"}), "1.16.1", store=Path(self.tmp.name)))


class Server:
    """Something that answers the game's server list ping with `answer`."""

    def __init__(self, answer):
        self.answer = json.dumps(answer).encode()
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(1)
        self.port = self.socket.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        connection, _ = self.socket.accept()
        with connection:
            connection.settimeout(5)
            connection.recv(4096)
            body = b"\x00" + ping._varint(len(self.answer)) + self.answer
            connection.sendall(ping._varint(len(body)) + body)
            time.sleep(0.2)

    def close(self):
        self.socket.close()


class Ping(unittest.TestCase):
    def test_the_server_says_its_version(self):
        server = Server({"version": {"name": "Paper 1.20.4", "protocol": 765}})
        self.addCleanup(server.close)
        answer = ping.status("127.0.0.1", server.port)
        self.assertEqual(answer["version"]["protocol"], 765)
        self.assertEqual(ping.game_version(answer), "1.20.4")

    def test_nothing_answers(self):
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        self.assertIsNone(ping.status("127.0.0.1", port, timeout=1))
        self.assertIsNone(ping.game_version(None))
        self.assertIsNone(ping.game_version({"version": {"name": "a proxy"}}))

    def test_no_server_and_no_version_is_said_plainly(self):
        with mock.patch.object(ping, "status", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "minebot.version"):
                stack.game_version({"version": "", "host": "127.0.0.1", "port": 1})
        self.assertEqual(stack.game_version({"version": "1.16.1", "host": "127.0.0.1", "port": 1}), "1.16.1")

    def test_a_varint_as_the_game_writes_it(self):
        self.assertEqual(ping._varint(0), b"\x00")
        self.assertEqual(ping._varint(300), b"\xac\x02")
        self.assertEqual(ping._varint(-1), b"\xff\xff\xff\xff\x0f")
        self.assertEqual(struct.pack(">H", 25565), b"\x63\xdd")


class Provision(unittest.TestCase):
    def test_a_release_for_every_system_the_package_runs_on(self):
        for system, cpu, expected in (("win32", "AMD64", "win-x64.zip"), ("win32", "ARM64", "win-arm64.zip"),
                                      ("linux", "x86_64", "linux-x64.tar.xz"), ("linux", "aarch64", "linux-arm64.tar.xz"),
                                      ("darwin", "x86_64", "darwin-x64.tar.gz"), ("darwin", "arm64", "darwin-arm64.tar.gz")):
            name, digest = provision.archive(provision.machine(system, cpu))
            self.assertTrue(name.endswith(expected), name)
            self.assertIn(provision.NODE, name)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_where_node_and_npm_are_in_a_release(self):
        with mock.patch.dict(os.environ, {"HARNESS_HOME": tempfile.gettempdir()}):
            self.assertEqual(provision.node(("windows", "x64")).name, "node.exe")
            self.assertEqual(provision.node(("linux", "x64")).parts[-2:], ("bin", "node"))
            self.assertEqual(provision.npm(("macos", "arm64")).parts[-5:], ("lib", "node_modules", "npm", "bin", "npm-cli.js"))
            # The libraries go beside the package, under a name the lockfile decides: never into the package.
            self.assertNotIn(str(PACKAGE), str(provision.modules_dir()))
            self.assertIn(provision.lock_hash(), provision.modules_dir().name)

    def test_what_was_downloaded_is_the_release_or_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "node.zip.part"

            class Response:
                def __init__(self):
                    self.chunks = [b"not the release", b""]

                def read(self, size):
                    return self.chunks.pop(0)

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            with mock.patch("urllib.request.urlopen", return_value=Response()):
                with self.assertRaisesRegex(RuntimeError, "not the release"):
                    provision._download("node.zip", "0" * 64, target, log=lambda message: None)
            self.assertFalse(target.exists())


class Parts(unittest.TestCase):
    """The package stops what it started, by its record, and nothing else."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(self.tmp.name) / "data")})
        patch.start()
        self.addCleanup(patch.stop)

    def test_started_recorded_stopped(self):
        sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
        mine = stack.start("bridge", sleeper, log="bridge.log")
        self.addCleanup(stack.end, mine)
        import subprocess

        other = subprocess.Popen(sleeper)   # the same command, not started by the package
        self.addCleanup(lambda: (other.kill(), other.wait()))
        self.assertTrue(stack.alive("bridge"))
        self.assertEqual(stack.record("bridge")["pid"], mine)
        said = []
        stack.down(said.append)
        self.assertEqual(said, [f"stopped bridge (process {mine})"])
        self.assertFalse(stack.alive("bridge"))
        self.assertIsNone(stack.record("bridge"))
        self.assertIsNone(other.poll())
        self.assertFalse(stack.stop("bridge"))     # nothing recorded: nothing stopped

    def test_a_port_something_else_has_is_named_with_its_setting(self):
        taken = socket.socket()
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        self.addCleanup(taken.close)
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        values = {"bridge_port": port, "worker_port": taken.getsockname()[1], "view_port": taken.getsockname()[1], "window": "off"}
        with self.assertRaisesRegex(RuntimeError, r"minebot\.worker_port"):
            stack.free_ports(values)
        stack.free_ports({**values, "worker_port": port})     # the window is off: its port is not asked for

    def test_frames_of_a_session_that_is_over_go(self):
        stack.frames_dir().mkdir(parents=True)
        (stack.frames_dir() / "f000000001.jpg").write_bytes(b"x")
        stack.down(lambda message: None)
        self.assertEqual(list(stack.frames_dir().glob("*.jpg")), [])


class Window(unittest.TestCase):
    MINE = "[General]\nInstanceType=OneSix\nname=mine\nJvmArgs=-Xmx1G\n[UI]\nshownNotifications=\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.launcher = self.root / "launcher.exe"
        self.launcher.write_bytes(b"")
        mine = self.root / "instances" / "mine"
        (mine / ".minecraft" / "mods").mkdir(parents=True)
        (mine / ".minecraft" / "saves" / "my world").mkdir(parents=True)
        (mine / ".minecraft" / "mods" / "my-mod.jar").write_bytes(b"mine")
        (mine / ".minecraft" / "options.txt").write_text("fov:0.0\n", encoding="utf-8")
        (mine / "instance.cfg").write_text(self.MINE, encoding="utf-8")
        (mine / "mmc-pack.json").write_text(json.dumps({"components": [
            {"uid": "net.minecraft", "version": "1.16.1"}, {"uid": "net.fabricmc.fabric-loader", "version": "0.16.14"}]}),
            encoding="utf-8")

    def test_an_instance_of_its_own_from_one_of_yours(self):
        target = window.setup(launcher=str(self.launcher), source="mine", instance="window", view_port=25566, log=lambda message: None)
        self.assertEqual(target, self.root / "instances" / "window")
        self.assertEqual([path.name for path in (target / ".minecraft" / "mods").iterdir()], [window.MOD.name])
        self.assertFalse((target / ".minecraft" / "saves").exists())           # your worlds stay yours
        self.assertTrue((target / ".minecraft" / "options.txt").is_file())
        text = (target / "instance.cfg").read_text(encoding="utf-8")
        # The launcher reads these in [General] only: none of them stands in another section.
        general, rest = text.split("[UI]")
        self.assertTrue(general.startswith("[General]\n"), text)
        self.assertIn("name=window\n", general)
        self.assertIn("JvmArgs=-Dharness.camera.server=127.0.0.1:25566\n", general)
        self.assertIn("OverrideJavaArgs=true\n", general)
        self.assertNotIn("JvmArgs", rest)
        self.assertEqual(text.count("JvmArgs="), 1)
        # Yours is as it was.
        mine = self.root / "instances" / "mine"
        self.assertEqual((mine / "instance.cfg").read_text(encoding="utf-8"), self.MINE)
        self.assertTrue((mine / ".minecraft" / "mods" / "my-mod.jar").is_file())
        # Again: the port changed, nothing is copied twice.
        window.setup(launcher=str(self.launcher), source="mine", instance="window", view_port=25577, log=lambda message: None)
        self.assertIn("JvmArgs=-Dharness.camera.server=127.0.0.1:25577\n", (target / "instance.cfg").read_text(encoding="utf-8"))

    def test_what_cannot_hold_the_mod_is_refused(self):
        other = self.root / "instances" / "newer"
        other.mkdir()
        (other / "instance.cfg").write_text("name=newer\n", encoding="utf-8")
        (other / "mmc-pack.json").write_text(json.dumps({"components": [{"uid": "net.minecraft", "version": "1.20.4"}]}), encoding="utf-8")
        for source, instance, words in (("newer", "window", "Fabric Loader"), ("none", "window", "no instance"), ("mine", "mine", "of its own")):
            with self.assertRaisesRegex(RuntimeError, words):
                window.setup(launcher=str(self.launcher), source=source, instance=instance, view_port=25566, log=lambda message: None)
        with self.assertRaisesRegex(RuntimeError, "no launcher"):
            window.setup(launcher=str(self.root / "nowhere.exe"), source="mine", instance="window", view_port=25566)


class Workspace(unittest.TestCase):
    def test_a_conversation_takes_the_body_and_the_host_gives_it_back(self):
        from harness_minebot import host

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(folder) / "data"), "HARNESS_HOME": str(Path(folder) / "home")}), \
                mock.patch.object(stack, "up", return_value=True) as up, mock.patch.object(stack, "down") as down, \
                mock.patch.object(stack, "worker_python", return_value=sys.executable), \
                mock.patch.object(stack, "alive", return_value=True):
            provider = host.Workspaces(Path(folder), None)
            self.assertEqual(provider.kinds(), ("minebot",))
            self.assertEqual(provider.bench("minebot"), "mineflayer")
            self.assertEqual(provider.tree({}, "minebot"), {"bench": "mineflayer"})
            self.assertFalse(provider.describe("minebot")["views"])   # no window: no pictures to look at
            worker = provider.acquire("run-1", "minebot", log=lambda message: None)
            self.assertEqual(worker.endpoint, "http://127.0.0.1:8796")
            self.assertEqual(worker.status, "ready")
            options = up.call_args.kwargs["options"]
            self.assertEqual(options["bridge"], "http://127.0.0.1:8791")
            self.assertNotIn("start_over", options)                 # the server's worlds are its owner's
            self.assertEqual(Path(up.call_args.kwargs["store"]), config.data_dir() / "store")
            provider.close()
            down.assert_called()

    def test_a_body_that_does_not_come_up_is_said_so(self):
        from harness_minebot import host

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(folder) / "data")}), \
                mock.patch.object(stack, "up", return_value=False), mock.patch.object(stack, "down"):
            provider = host.Workspaces(Path(folder), None)
            with self.assertRaisesRegex(RuntimeError, "did not come up"):
                provider.acquire("run-1", "minebot", log=lambda message: None)


if __name__ == "__main__":
    unittest.main()
