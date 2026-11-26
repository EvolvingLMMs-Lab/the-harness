"""Taking an identity with you: a shared package holds no key or credential and its preview
lists every public text; adopting gives a new identity whose skills are proposed and whose
reactions are off; a backup restored into another data directory carries on, a wrong
passphrase is refused; a retired identity says it moved; OpenClaw and Hermes agents come
over with persona, memory and skills and without tokens; earlier core chats are listed."""
import base64
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import zlib
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

MODEL_KEY = "sk-or-v1-modelkey-0123456789abcdef"
CHANNEL_TOKEN = "qq-access-token-5f3e2a1b9c"
GROUP = "98765432"
SKILL_CODE = "def add_one(value):\n    return value + 1\n"
SKILL_TEST = "assert add_one(1) == 2\n"


def png() -> bytes:
    """A 1x1 PNG."""
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0\xff\x00\x00")) + chunk(b"IEND", b""))


def everything(folder) -> bytes:
    return b"\n".join(path.read_bytes() for path in sorted(Path(folder).rglob("*")) if path.is_file())


class Take(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.folder.name)
        self.here = self.root / "here"
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": str(self.here), "HARNESS_DATA": str(self.here)})
        self.env.start()

    def tearDown(self):
        from harness_agent import state

        state._release_all()
        state._LIVES.clear()
        self.env.stop()
        self.folder.cleanup()

    def identity(self):
        """`yu`: persona, avatar, a skill with its test, a reaction naming a QQ group, a memory,
        a channel account with its token, and a model key on this computer."""
        from harness.sdk import Credentials
        from harness_agent import state
        from harness_agent.reactions import Tree

        Credentials(self.here).keep("OPENROUTER_API_KEY", MODEL_KEY)
        identity = state.create("yu", display="小鱼")
        (identity.directory / "SOUL.md").write_text(
            f"# Soul\n\nCalm and brief. Works in {identity.directory / 'work'}.\n", encoding="utf-8")
        (identity.directory / "avatar.png").write_bytes(png())
        skill = identity.directory / "skills" / "add_one"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: add_one\ndescription: adds one\n---\n\nAdd one.\n", encoding="utf-8")
        (skill / "program.py").write_text(SKILL_CODE, encoding="utf-8")
        (skill / "test.py").write_text(SKILL_TEST, encoding="utf-8")
        (skill / "origin.json").write_text(json.dumps({"chat": "main", "source": "learned"}), encoding="utf-8")
        tree = Tree(identity)
        tree.add("study group quiet", {"event": "qq.message", "match": {"group": GROUP}}, {"remind": f"{GROUP} is busy"},
                 about=f"a message in {GROUP} → remind the owner")
        identity.remember("pr language", "Pull requests are in English", source="main",
                          expected=identity.memory()["revision"])
        (identity.directory / "channels").mkdir()
        (identity.directory / "channels" / "qq-10001.json").write_text(json.dumps(
            {"identity": "yu", "dm": "pairing", "groups": {GROUP: "mention"}, "owner": "10001",
             "access_token": CHANNEL_TOKEN}), encoding="utf-8")
        (identity.directory / "places.json").write_text(json.dumps(
            [{"id": "qq-10001", "kind": "space", "title": "QQ 10001",
              "address": f"ws://127.0.0.1:3001?access_token={CHANNEL_TOKEN}"}]), encoding="utf-8")
        seed = json.loads((identity.root / ".keys" / "yu.json").read_text(encoding="utf-8"))["seed"]
        return identity, seed

    def shared(self, identity, **options):
        from harness_agent import take

        seen = []
        result = take.share(identity, str(self.root / "out"), confirm=lambda preview: seen.append(preview) or True,
                            log=lambda text: None, **options)
        unpacked = self.root / "unpacked"
        with tarfile.open(result["sent"]) as tar:
            tar.extractall(unpacked, filter="data")
        return result, seen[0], unpacked / "yu"

    def test_shared_package_has_no_key_or_credential_and_preview_lists_every_public_text(self):
        identity, seed = self.identity()
        result, preview, package = self.shared(identity)
        raw = everything(package)
        for secret in (seed, base64.b64decode(seed).hex(), MODEL_KEY, CHANNEL_TOKEN, GROUP, "Pull requests are in English"):
            self.assertNotIn(secret.encode(), raw, secret)
        # Places of this computer become names (the README's adopt line names where it was sent).
        self.assertNotIn(str(Path.home()).encode(), everything(package / "identity"))
        self.assertNotIn(b"places.json", b"\n".join(p.name.encode() for p in package.rglob("*")))
        self.assertIn('identity = [ "yu" ]'.replace(" ", ""), (package / "package.toml").read_text(encoding="utf-8")
                      .replace(" ", ""))
        nodes = json.loads((package / "identity" / "yu" / "reactions.json").read_text(encoding="utf-8"))["nodes"]
        self.assertEqual(nodes[0]["when"]["match"]["group"], "<group>")
        self.assertIn("<group>", nodes[0]["about"])
        self.assertTrue((package / "identity" / "yu" / "skills" / "add_one" / "test.py").is_file())
        # Every text in the package was in the preview, as it is there.
        texts = {row["file"]: row["text"] for row in preview["texts"]}
        for path in (package / "identity" / "yu").rglob("*"):
            if path.is_file() and path.suffix != ".png":
                relative = path.relative_to(package).as_posix()
                self.assertEqual(texts.get(relative), path.read_bytes().decode("utf-8"), relative)
        self.assertEqual(preview["other_files"], ["identity/yu/avatar.png"])
        self.assertIn("memory", preview["left_out"])
        self.assertIn("private key", preview["left_out"])
        self.assertTrue(result["install"].startswith("harness agent adopt "))

    def test_nothing_goes_without_consent_and_a_credential_stops_it(self):
        from harness_agent import take

        identity, _ = self.identity()
        refused = take.share(identity, str(self.root / "out"), confirm=lambda preview: False, log=lambda text: None)
        self.assertTrue(refused["needs_consent"])
        self.assertFalse((self.root / "out").exists())
        (identity.directory / "SOUL.md").write_text(f"my key is {MODEL_KEY}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "credential"):
            take.share(identity, str(self.root / "out"), confirm=lambda preview: True, log=lambda text: None)

    def test_character_card_holds_only_name_and_persona(self):
        from harness_agent import cards, take

        identity, seed = self.identity()
        for name in ("yu.json", "yu.png"):
            result = take.share_card(identity, self.root / name, confirm=lambda preview: True)
            card = cards.read(result["sent"])
            self.assertEqual(card["name"], "小鱼")
            self.assertIn("Calm and brief", card["description"])
            raw = (self.root / name).read_bytes()
            for secret in (seed, MODEL_KEY, CHANNEL_TOKEN, GROUP, "add_one"):
                self.assertNotIn(secret.encode(), raw)

    def test_adopted_identity_is_new_with_skills_proposed_and_reactions_off(self):
        from harness_agent import take
        from harness_agent.reactions import Tree
        from harness_agent.state import Identity

        identity, _ = self.identity()
        result, _, _ = self.shared(identity)
        adopted = take.adopt(result["sent"], id="buddy", log=lambda text: None)
        new = Identity("buddy", create=False)
        self.assertNotEqual(new.fingerprint, identity.fingerprint)
        self.assertEqual(new.name, "小鱼")
        self.assertEqual(json.loads((new.directory / "adopted.json").read_text(encoding="utf-8"))["from"], result["sent"])
        skill = new.directory / "skills" / "add_one"
        self.assertEqual(json.loads((skill / "origin.json").read_text(encoding="utf-8"))["evidence"], "proposed")
        self.assertFalse((skill / "program.py").exists())  # waits for its own test here
        self.assertEqual(adopted["reactions"], ["study group quiet"])
        node = Tree(new).node("study group quiet")
        self.assertFalse(node["enabled"])
        self.assertEqual(node["evidence"], "proposed")
        self.assertFalse((new.directory / "memory").exists() and any((new.directory / "memory").glob("*.md")))
        tested = take.test_adopted(new)
        self.assertEqual(tested, [{"skill": "add_one", "ok": True, "evidence": "own_test"}])
        self.assertEqual((skill / "program.py").read_text(encoding="utf-8"), SKILL_CODE)

    def test_backup_restored_elsewhere_carries_on_and_wrong_passphrase_fails(self):
        from harness_agent import take
        from harness_agent.sdk import Agent
        from harness_agent import keys

        identity, seed = self.identity()
        made = take.backup(identity, self.root / "yu.harness-backup", "correct horse", with_keys=True)
        blob = (self.root / "yu.harness-backup").read_bytes()
        for secret in (seed, MODEL_KEY, CHANNEL_TOKEN, "Pull requests"):
            self.assertNotIn(secret.encode(), blob)
        self.assertEqual(made["channels"], ["QQ 10001"])
        there = self.root / "there"
        with mock.patch.dict(os.environ, {"HARNESS_HOME": str(there), "HARNESS_DATA": str(there)}):
            with self.assertRaisesRegex(ValueError, "passphrase is wrong"):
                take.restore(self.root / "yu.harness-backup", "wrong horse")
            self.assertFalse((there / "agents" / "yu").exists())
            restored = take.restore(self.root / "yu.harness-backup", "correct horse")
            self.assertEqual(restored["channels"], ["QQ 10001"])
            self.assertEqual(restored["model_keys"], ["OPENROUTER_API_KEY"])
            agent = Agent("yu")
            self.assertEqual(agent.name, "小鱼")
            self.assertEqual(agent.fingerprint, identity.fingerprint)
            self.assertEqual(agent._identity.memory()["entries"]["pr language"]["text"], "Pull requests are in English")
            signature = agent._identity.sign(b"hello")
            self.assertTrue(keys.verify(identity.public_key, b"hello", signature))
            self.assertEqual(json.loads((there / "agents" / ".keys" / "yu.json").read_text(encoding="utf-8"))["seed"], seed)
            self.assertIn(CHANNEL_TOKEN, (there / "agents" / "yu" / "channels" / "qq-10001.json").read_text(encoding="utf-8"))
            agent._identity.live()  # it lives there now

    def test_retired_identity_says_it_moved(self):
        from harness_agent import state, take
        from harness_agent.sdk import Agent
        from harness_agent.state import IdentityError

        identity, _ = self.identity()
        take.retire(identity)
        with self.assertRaisesRegex(IdentityError, "moved to another computer"):
            Agent("yu")
        with self.assertRaisesRegex(IdentityError, "moved"):
            identity.live()
        state.use("yu")
        with self.assertRaisesRegex(IdentityError, "moved"):
            state.resolve()
        from harness_agent import cli
        self.assertEqual(cli.main(["about", "--identity", "yu"]), 2)

    def test_openclaw_comes_over_without_tokens(self):
        from harness_agent import take
        from harness_agent.state import Identity

        workspace = self.root / ".openclaw" / "workspace"
        (workspace / "memory").mkdir(parents=True)
        (workspace / "skills" / "weather").mkdir(parents=True)
        (workspace / "SOUL.md").write_text("# SOUL\n\nDry humour, short answers.\n", encoding="utf-8")
        (workspace / "IDENTITY.md").write_text("# IDENTITY\n\n- **Name:** Claw\n- **Emoji:** 🦞\n", encoding="utf-8")
        (workspace / "USER.md").write_text("# USER\n\nLives in Toronto.\n", encoding="utf-8")
        (workspace / "MEMORY.md").write_text("# MEMORY\n\n- Prefers tea.\n- Uses Linux.\n", encoding="utf-8")
        (workspace / "memory" / "2026-11-20.md").write_text("Fixed the CI together.\n", encoding="utf-8")
        (workspace / "skills" / "weather" / "SKILL.md").write_text(
            "---\nname: weather\ndescription: the forecast\n---\n\nAsk wttr.in.\n", encoding="utf-8")
        (self.root / ".openclaw" / "credentials").mkdir()
        (self.root / ".openclaw" / "credentials" / "telegram.json").write_text(json.dumps({"token": CHANNEL_TOKEN}),
                                                                           encoding="utf-8")
        (self.root / ".openclaw" / "openclaw.json").write_text(json.dumps({"channels": {"token": CHANNEL_TOKEN}}),
                                                               encoding="utf-8")
        result = take.import_from("openclaw", workspace)
        identity = Identity(result["identity"], create=False)
        self.assertEqual(identity.name, "Claw")
        self.assertIn("Dry humour", (identity.directory / "SOUL.md").read_text(encoding="utf-8"))
        self.assertIn("Toronto", (identity.directory / "USER.md").read_text(encoding="utf-8"))
        texts = [entry["text"] for entry in identity.memory()["entries"].values()]
        self.assertEqual(sorted(texts), ["- Prefers tea.", "- Uses Linux.", "Fixed the CI together."])
        self.assertEqual(result["skills"], ["weather"])
        self.assertEqual(json.loads((identity.directory / "skills" / "weather" / "origin.json")
                                    .read_text(encoding="utf-8"))["evidence"], "proposed")
        self.assertNotIn(CHANNEL_TOKEN.encode(), everything(self.here))
        self.assertIn("openclaw gateway stop", result["suggest"])

    def test_hermes_comes_over_without_tokens(self):
        from harness_agent import take
        from harness_agent.state import Identity

        profile = self.root / ".hermes" / "profiles" / "coder"
        (profile / "memories").mkdir(parents=True)
        (profile / "skills" / "devops" / "deploy").mkdir(parents=True)
        (profile / "SOUL.md").write_text("You are a careful coding assistant.\n", encoding="utf-8")
        (profile / "profile.yaml").write_text("display_name: Hermes Coder\n", encoding="utf-8")
        (profile / "memories" / "MEMORY.md").write_text("Project uses uv.\n§\nTests run with pytest -q.\n",
                                                        encoding="utf-8")
        (profile / "memories" / "USER.md").write_text("Name is Sam.\n", encoding="utf-8")
        (profile / "skills" / "devops" / "deploy" / "SKILL.md").write_text(
            "---\nname: deploy\ndescription: ship it\n---\n\nRun the deploy script.\n", encoding="utf-8")
        (profile / ".env").write_text(f"TELEGRAM_BOT_TOKEN={CHANNEL_TOKEN}\nOPENROUTER_API_KEY={MODEL_KEY}\n",
                                      encoding="utf-8")
        (profile / "auth.json").write_text(json.dumps({"oauth": CHANNEL_TOKEN}), encoding="utf-8")
        (profile / "config.yaml").write_text(f"telegram:\n  token: {CHANNEL_TOKEN}\n", encoding="utf-8")
        result = take.import_from("hermes", profile)
        identity = Identity(result["identity"], create=False)
        self.assertEqual(identity.name, "Hermes Coder")
        self.assertIn("careful coding assistant", (identity.directory / "SOUL.md").read_text(encoding="utf-8"))
        self.assertIn("Sam", (identity.directory / "USER.md").read_text(encoding="utf-8"))
        self.assertEqual(sorted(e["text"] for e in identity.memory()["entries"].values()),
                         ["Project uses uv.", "Tests run with pytest -q."])
        self.assertEqual(result["skills"], ["deploy"])
        raw = everything(self.here)
        self.assertNotIn(CHANNEL_TOKEN.encode(), raw)
        self.assertNotIn(MODEL_KEY.encode(), raw)

    def test_earlier_core_chats_are_listed_under_default(self):
        from harness_agent.chats import Chats
        from harness_agent.state import Identity

        run = self.here / "runs" / "old"
        run.mkdir(parents=True)
        records = [{"seq": 0, "time": 1.0, "event": "user_message", "text": "hello from before"},
                   {"seq": 1, "time": 2.0, "event": "model_request"},
                   {"seq": 2, "time": 3.0, "event": "finish", "text": "hi, earlier me"}]
        (run / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        (run / "meta.json").write_text(json.dumps({"title": "hello"}), encoding="utf-8")
        before = (run / "events.jsonl").read_bytes()
        (self.here / "host").mkdir()
        (self.here / "host" / "sessions.jsonl").write_text(json.dumps(
            {"id": "a1b2c3", "agent": "main", "title": "hello", "frontend": "terminal", "created": 1.0,
             "directory": str(run), "run": "old"}) + "\n", encoding="utf-8")
        identity = Identity("default")
        chats = Chats(identity)
        row = next(row for row in chats.listing() if row["chat"] == "core-a1b2c3")
        self.assertEqual(row["kind"], "earlier")
        self.assertEqual([(r["event"], r["text"]) for r in chats.read("core-a1b2c3")],
                         [("user", "hello from before"), ("reply", "hi, earlier me")])
        self.assertEqual((run / "events.jsonl").read_bytes(), before)
