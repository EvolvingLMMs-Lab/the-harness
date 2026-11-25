"""Identities: a fixed id and a display name, the identity folder and key pair, migration
from the earlier layout (originals kept, an earlier version still opens them), several
identities and the current one, the life lock, character cards."""
import base64
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
from unittest import TestCase, mock
import zlib

import helpers  # noqa: F401  (source paths)
sys.path.insert(0, str(helpers.ROOT / "packages" / "agent"))
from harness_agent import cards, keys, state
from harness_agent.state import Identity, IdentityError


def png_card(path, card, keyword="chara"):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
    text = keyword.encode() + b"\0" + base64.b64encode(json.dumps(card).encode())
    Path(path).write_bytes(cards.PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
                           + chunk(b"tEXt", text) + chunk(b"IDAT", zlib.compress(b"\0\0")) + chunk(b"IEND", b""))


class KeyTests(TestCase):
    def test_rfc8032_vector_and_round_trip(self):
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        self.assertEqual(keys.public_key(seed).hex(),
                         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        self.assertEqual(keys.sign(seed, b"").hex()[:32], "e5564300c360ac729086e2cc806e828a")
        seed, public = keys.generate()
        signature = keys.sign(seed, "身份".encode())
        self.assertTrue(keys.verify(public, "身份".encode(), signature))
        self.assertFalse(keys.verify(public, b"other", signature))


class IdentityTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "agents"
        self.addCleanup(self.temp.cleanup)

    def test_new_identity_layout_and_key_outside_its_folder(self):
        identity = state.create("work", display="工作助手", root=self.root)
        for name in ("IDENTITY.md", "SOUL.md", "USER.md", "MEMORY.md", "identity.json", "memory", "library", "sessions"):
            self.assertTrue((identity.directory / name).exists(), name)
        config = json.loads((identity.directory / "identity.json").read_text(encoding="utf-8"))
        self.assertEqual((config["schema"], config["format"], config["id"]), (1, 2, "work"))
        self.assertNotIn("seed", json.dumps(config))
        stored = json.loads((self.root / ".keys" / "work.json").read_text(encoding="utf-8"))
        self.assertEqual(keys.public_key(base64.b64decode(stored["seed"])), identity.public_key)
        self.assertTrue(keys.verify(identity.public_key, b"hello", identity.sign(b"hello")))
        self.assertTrue(identity.fingerprint.startswith("SHA256:"))
        self.assertNotIn("fingerprint", identity.to_dict())
        self.assertEqual(identity.name, "工作助手")

    def test_rename_changes_the_display_name_only(self):
        identity = state.create("work", root=self.root)
        identity.rename("小助手 · 二号")
        again = Identity("work", root=self.root, create=False)
        self.assertEqual((again.id, again.name), ("work", "小助手 · 二号"))
        self.assertEqual(state.identities(self.root), ["work"])
        self.assertIn("小助手 · 二号", again.persona())
        with self.assertRaises(ValueError):
            identity.rename("two\nlines")

    def test_identities_do_not_see_each_others_memory(self):
        one, two = state.create("one", root=self.root), state.create("two", root=self.root)
        one.remember("PR language", "English", source="s1", expected=0)
        self.assertEqual(Identity("one", root=self.root).memory()["entries"]["PR language"]["text"], "English")
        self.assertEqual(two.memory()["entries"], {})
        index = (one.directory / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("PR language", index)
        self.assertIn("(private)", index)
        with self.assertRaisesRegex(ValueError, "1200"):
            one.remember("long", "x" * 1201, source="s1", expected=1)
        one.remember("PR language", None, source="s1", expected=1)
        self.assertEqual(one.memory()["entries"], {})

    def test_migration_keeps_originals_and_the_earlier_version_still_opens(self):
        old = self.root / "default"
        (old / "sessions" / "s1").mkdir(parents=True)
        (old / "library").mkdir()
        original = {"schema": 1, "id": "default", "created": 1.0, "instructions": "Answer briefly."}
        (old / "identity.json").write_text(json.dumps(original), encoding="utf-8")
        before = (old / "identity.json").read_bytes()
        memory = {"schema": 1, "revision": 3, "entries": {"editor": {"text": "vim", "source": "s1", "updated": 2.0},
                                                          "名字": {"text": "叫我小林", "source": "s1", "updated": 3.0}}}
        (old / "memory.json").write_text(json.dumps(memory, ensure_ascii=False), encoding="utf-8")
        (old / "sessions" / "s1" / "state.json").write_text(json.dumps({"schema": 1, "identity": "default",
                                                                         "messages": []}), encoding="utf-8")
        identity = Identity("default", root=self.root)
        self.assertIn("Answer briefly.", (old / "SOUL.md").read_text(encoding="utf-8"))
        self.assertIn("Answer briefly.", identity.persona())
        migrated = identity.memory()
        self.assertEqual(migrated["revision"], 3)
        self.assertEqual(migrated["entries"]["名字"]["text"], "叫我小林")
        self.assertEqual(migrated["entries"]["editor"]["scope"], "private")
        self.assertEqual(json.loads((old / "memory.json").read_text(encoding="utf-8")), memory)
        config = json.loads((old / "identity.json").read_text(encoding="utf-8"))
        # What the earlier version checks and reads is unchanged.
        self.assertEqual((config["schema"], config["id"], config["instructions"]), (1, "default", "Answer briefly."))
        self.assertEqual((old / "identity.v1.json").read_bytes(), before)
        self.assertEqual([row["session"] for row in identity.sessions()], ["s1"])
        # Opening again migrates nothing twice.
        identity.remember("third", "x", source="s2", expected=3)
        self.assertEqual(Identity("default", root=self.root).memory()["revision"], 4)

    def test_personal_settings_not_imported_go_to_user_and_soul(self):
        data = Path(self.temp.name) / "data"
        data.mkdir()
        (data / "config.toml").write_text('[personal]\nabout = "I am a teacher"\ninstructions = "Be gentle"\n',
                                          encoding="utf-8")
        old = Path(self.temp.name) / "home" / "agents" / "default"
        old.mkdir(parents=True)
        (old / "identity.json").write_text(json.dumps({"schema": 1, "id": "default", "created": 1.0,
                                                       "instructions": "Be gentle"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"HARNESS_DATA": str(data), "HARNESS_HOME": str(Path(self.temp.name) / "home")}):
            identity = Identity("default")
        self.assertIn("I am a teacher", (old / "USER.md").read_text(encoding="utf-8"))
        self.assertEqual((old / "SOUL.md").read_text(encoding="utf-8").count("Be gentle"), 1)
        self.assertIn("I am a teacher", identity.persona())

    def test_resolve_never_guesses_between_several(self):
        self.assertEqual(state.resolve(root=self.root), "default")  # none yet: default is made
        self.assertEqual(state.resolve(root=self.root), "default")  # the only one
        state.create("work", root=self.root)
        with self.assertRaisesRegex(IdentityError, "several identities"):
            state.resolve(root=self.root)
        self.assertEqual(state.resolve(root=self.root, ask=lambda found: found[-1]), "work")
        self.assertEqual(state.resolve("default", root=self.root), "default")
        with self.assertRaisesRegex(IdentityError, "no identity 'nobody'"):
            state.resolve("nobody", root=self.root)
        state.use("work", root=self.root)
        self.assertEqual(state.resolve(root=self.root), "work")
        state.delete("work", root=self.root)
        self.assertIsNone(state.current(self.root))
        self.assertFalse((self.root / ".keys" / "work.json").exists())

    def test_clone_takes_persona_and_skills_not_memory(self):
        source = state.create("one", root=self.root)
        (source.directory / "SOUL.md").write_text("# Soul\n\nDry humour.\n", encoding="utf-8")
        (source.library / "skills").mkdir()
        (source.library / "skills" / "rerun_failed.py").write_text("def rerun_failed():\n    pass\n", encoding="utf-8")
        source.remember("secret", "only mine", source="s", expected=0)
        clone = state.create("two", source="one", root=self.root)
        self.assertIn("Dry humour.", clone.persona())
        self.assertTrue((clone.library / "skills" / "rerun_failed.py").exists())
        self.assertEqual(clone.memory()["entries"], {})
        self.assertNotEqual(clone.public_key, source.public_key)

    def test_character_card_png_and_json(self):
        card = {"spec": "chara_card_v3", "spec_version": "3.0",
                "data": {"name": "小雪", "description": "A snow fox.", "personality": "Curious",
                         "system_prompt": "Stay in character.", "first_mes": "ignored", "scenario": "ignored"}}
        png = Path(self.temp.name) / "card.png"
        png_card(png, card, "ccv3")
        identity = state.create("fox", card=png, root=self.root)
        self.assertEqual(identity.name, "小雪")
        soul = (identity.directory / "SOUL.md").read_text(encoding="utf-8")
        self.assertIn("A snow fox.", soul)
        self.assertIn("Stay in character.", soul)
        self.assertNotIn("ignored", soul)
        self.assertEqual((identity.directory / "avatar.png").read_bytes(), png.read_bytes())
        self.assertIn("Avatar: avatar.png", (identity.directory / "IDENTITY.md").read_text(encoding="utf-8"))
        plain = Path(self.temp.name) / "v2.json"
        plain.write_text(json.dumps({"spec": "chara_card_v2", "data": {"name": "Ann", "personality": "Calm"}}),
                         encoding="utf-8")
        self.assertEqual(state.create("ann", card=plain, root=self.root, display="安").name, "安")
        empty = Path(self.temp.name) / "empty.png"
        png_card(empty, {"x": 1}, "other")
        with self.assertRaisesRegex(ValueError, "without a character card"):
            state.create("none", card=empty, root=self.root)
        self.assertNotIn("none", state.identities(self.root))


HOLD = """
import sys, time
sys.path[:0] = {paths!r}
from harness_agent.state import Identity
Identity("work", root={root!r}).live()
print("holding", flush=True)
time.sleep(60)
"""


class LifeLockTests(TestCase):
    def test_one_identity_lives_in_one_host(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp) / "agents")
            state.create("work", root=root)
            paths = [str(Path(helpers.ROOT) / "src"), str(Path(helpers.ROOT) / "packages" / "agent")]
            other = {**os.environ, "HARNESS_DATA": str(Path(temp) / "other-data")}
            holder = subprocess.Popen([sys.executable, "-c", HOLD.format(paths=paths, root=root)], env=other,
                                      stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "holding")
                identity = Identity("work", root=root)
                with mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(temp) / "data")}):
                    with self.assertRaisesRegex(IdentityError, "alive in another host"):
                        identity.live()
                with mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(temp) / "other-data")}):
                    self.assertTrue(identity.live()["attached"])  # a frontend of the same host
            finally:
                holder.kill()
                holder.wait()
                holder.stdout.close()
            deadline = time.time() + 10
            while True:  # the system lets go of a dead holder's lock
                try:
                    with mock.patch.dict(os.environ, {"HARNESS_DATA": str(Path(temp) / "data")}):
                        claimed = identity.live()
                    break
                except IdentityError:
                    if time.time() > deadline:
                        raise
                    time.sleep(0.1)
            self.assertFalse(claimed["attached"])
            state.release(identity)


class CommandTests(TestCase):
    def run_agent(self, home, *words):
        environment = {**os.environ, "HARNESS_HOME": str(home), "HARNESS_DATA": str(Path(home) / "data"),
                       "PYTHONPATH": os.pathsep.join([str(Path(helpers.ROOT) / "src"),
                                                      str(Path(helpers.ROOT) / "packages" / "agent")]),
                       "PYTHONUTF8": "1"}
        code = "import sys; from harness_agent.cli import main; sys.exit(main(sys.argv[1:]))"
        return subprocess.run([sys.executable, "-c", code, *words], env=environment, capture_output=True, text=True,
                              encoding="utf-8", stdin=subprocess.DEVNULL)

    def test_commands_and_the_earlier_form(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(self.run_agent(home, "new", "default").returncode, 0)
            made = self.run_agent(home, "new", "work", "--name", "工作助手", "--json")
            self.assertEqual(json.loads(made.stdout)["name"], "工作助手")
            several = self.run_agent(home, "about")
            self.assertEqual(several.returncode, 2)
            self.assertIn("several identities", several.stderr)
            earlier = self.run_agent(home, "hello there")
            self.assertIn("harness agent say", earlier.stderr)
            self.assertIn("several identities", earlier.stderr)
            self.assertEqual(self.run_agent(home, "use", "work").returncode, 0)
            about = json.loads(self.run_agent(home, "about", "--json").stdout)
            self.assertEqual((about["id"], about["current"]), ("work", True))
            self.assertNotIn("fingerprint", about)
            self.assertIn("fingerprint", json.loads(self.run_agent(home, "--json", "about", "-v").stdout))
            listed = json.loads(self.run_agent(home, "list", "--json").stdout)
            self.assertEqual([row["id"] for row in listed], ["default", "work"])
            self.assertEqual(self.run_agent(home, "delete", "work").returncode, 2)  # nobody to ask
            self.assertEqual(self.run_agent(home, "delete", "work", "--yes").returncode, 0)
            self.assertEqual(self.run_agent(home, "about", "--json").returncode, 0)  # the only one again


class TerminalTests(TestCase):
    def test_terminal_conversations_carry_the_identity(self):
        from harness import cli
        args = cli.parser(False).parse_args(["--identity", "work"])
        self.assertEqual(args.identity, "work")
        start = cli._starter(args)
        start.identity = {"id": "work", "name": "工作", "runtime": {"identity": "work"}}
        with mock.patch.object(cli, "_task", return_value=("host", "conversation")) as task,                 mock.patch("harness.model_list.select", return_value={"id": "m", "provider": "openrouter", "name": "m"}):
            start("hello")
        self.assertEqual(task.call_args.kwargs["runtime"], {"identity": "work"})

    def test_terminal_asks_and_names_the_identity(self):
        from harness import cli
        args = cli.parser(False).parse_args([])
        seen = {}

        def hook(name, ask):
            seen["picked"] = ask(["default", "work"])
            return {"id": seen["picked"], "name": "工作", "runtime": {"identity": seen["picked"]}}
        with mock.patch("harness.extensions.first", return_value=hook), mock.patch("builtins.input", return_value="2"):
            identity = cli._identity(args)
        self.assertEqual((seen["picked"], identity["name"]), ("work", "工作"))
        from harness.tui.chat import Chat
        chat = Chat.__new__(Chat)
        chat.identity = identity
        self.assertEqual(chat._identity_part(), "工作 (work)")


class HostApiTests(TestCase):
    def test_a_frontend_manages_identities(self):
        from harness_agent import host
        with tempfile.TemporaryDirectory() as home,                 mock.patch.dict(os.environ, {"HARNESS_HOME": home, "HARNESS_DATA": str(Path(home) / "data")}):
            host.identity_change(None, {"action": "new", "id": "work", "name": "工作"})
            host.identity_change(None, {"action": "new", "id": "play"})
            with self.assertRaises(IdentityError):
                host.memory(None, {})  # several, none chosen: a frontend names one
            host.identity_change(None, {"action": "use", "id": "play"})
            self.assertEqual(host.memory(None, {})["entries"], {})
            rows = host.identity_change(None, {"action": "rename", "id": "work", "name": "小林"})
            self.assertEqual([(row["id"], row["name"], row["current"]) for row in rows],
                             [("play", "play", True), ("work", "小林", False)])
            self.assertEqual([row["id"] for row in host.identity_change(None, {"action": "delete", "id": "play"})],
                             ["work"])
            with self.assertRaises(ValueError):
                host.identity_change(None, {"action": "steal", "id": "work"})


class SdkTests(TestCase):
    def test_agent_is_the_packages(self):
        from harness import sdk
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"HARNESS_HOME": home, "HARNESS_DATA": str(Path(home) / "data")}):
            Agent = sdk.Agent
            work = Agent.new("work", name="工作")
            self.assertEqual((work.id, work.name), ("work", "工作"))
            self.assertEqual(Agent().id, "work")
            Agent.new("play")
            with self.assertRaises(IdentityError):
                Agent()
            Agent.use("play")
            self.assertEqual(Agent().id, "play")
            self.assertEqual([row["id"] for row in Agent.list()], ["play", "work"])
