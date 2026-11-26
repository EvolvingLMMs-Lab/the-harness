"""The connectors a user manages, each listed, added, removed and tested the same way: MCP
servers and external agents (harness mcp, harness agents, harness.sdk.connectors), and an
identity's skill sources (harness skills)."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, mock

import helpers  # noqa: F401  (source paths)

from harness import cli
from harness.host import connectors
from harness.problems import Problem


def run(*words):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = cli.main(list(words))
    return status, out.getvalue(), err.getvalue()


class Base(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.folder.name, "HARNESS_DATA": self.folder.name})
        self.env.start()

    def tearDown(self):
        mock.patch.stopall()
        self.env.stop()
        self.folder.cleanup()


class McpTests(Base):
    def test_a_server_is_added_listed_switched_and_removed_and_its_secrets_are_never_listed(self):
        status, out, _ = run("mcp", "list")
        self.assertIn("no MCP servers yet", out)
        status, out, err = run("mcp", "add", "--env", "API_KEY=s3cret", "files", "--", "files-server", "--root", "/data")
        self.assertEqual(status, 0, err)
        self.assertIn("Added stdio MCP server files: files-server --root /data", out)
        status, out, err = run("mcp", "add", "--transport", "http", "--header", "Authorization: Bearer t0ken", "notes",
                               "https://mcp.example.com/mcp")
        self.assertEqual(status, 0, err)
        rows = {row["name"]: row for row in connectors.mcp_servers()}
        self.assertEqual((rows["files"]["transport"], rows["files"]["env"], rows["files"]["tools"]),
                         ("stdio", ["API_KEY"], ["*"]))
        self.assertEqual((rows["notes"]["transport"], rows["notes"]["target"], rows["notes"]["headers"]),
                         ("http", "https://mcp.example.com/mcp", ["Authorization"]))
        self.assertNotIn("s3cret", json.dumps(rows))
        self.assertNotIn("t0ken", json.dumps(rows))
        # What a conversation is given resolves the secrets from the credentials.
        from harness.paths import data
        from harness.services.connectors import configured_servers
        from harness.settings import Credentials, Settings

        servers = configured_servers(Settings(data()).get(), Credentials(data()))
        self.assertEqual(servers["files"]["env"], {"API_KEY": "s3cret"})
        self.assertEqual(servers["notes"]["headers"], {"Authorization": "Bearer t0ken"})
        status, out, _ = run("mcp", "disable", "notes")
        self.assertEqual(out.strip(), "notes is off")
        self.assertNotIn("notes", configured_servers(Settings(data()).get(), Credentials(data())))
        status, out, _ = run("mcp", "list")
        self.assertRegex(out, r"notes +http +https://mcp.example.com/mcp +\(off\)")
        status, out, _ = run("mcp", "remove", "files")
        self.assertEqual((status, out.strip()), (0, "Removed MCP server files"))
        self.assertEqual([row["name"] for row in connectors.mcp_servers()], ["notes"])
        self.assertIsNone(Credentials(data()).secret("HARNESS_MCP_FILES_API_KEY"))

    def test_what_cannot_be_added_says_why(self):
        for arguments, code in ((dict(name="Bad Name", url="https://x.example"), "mcp_name"),
                                (dict(name="both", url="https://x.example", command="y"), "mcp_target"),
                                (dict(name="none"), "mcp_target"),
                                (dict(name="ftp", url="ftp://x.example"), "mcp_target")):
            with self.assertRaises(Problem) as refused:
                connectors.mcp_add(**arguments)
            self.assertEqual(refused.exception.code, code)
        connectors.mcp_add("twice", url="https://x.example/mcp")
        with self.assertRaises(Problem) as refused:
            connectors.mcp_add("twice", url="https://y.example/mcp")
        self.assertEqual(refused.exception.code, "mcp_exists")
        status, _, err = run("mcp", "remove", "nothing")
        self.assertEqual(status, 1)
        self.assertIn("no MCP server called 'nothing'", err)

    def test_testing_connects_once_and_lists_the_tools_or_says_why_not(self):
        server = Path(self.folder.name) / "server.py"
        server.write_text('''import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}}
    if message["method"] == "tools/list":
        result = {"tools": [{"name": "convert", "description": "Convert a value\\nbetween units", "inputSchema": {}}]}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
''', encoding="utf-8")
        connectors.mcp_add("units", command=sys.executable, args=[str(server)])
        found = connectors.mcp_test("units")
        self.assertEqual(found["tools"], [{"name": "convert", "description": "Convert a value between units"}])
        status, out, _ = run("mcp", "test", "units")
        self.assertIn("answered", out)
        self.assertIn("convert", out)
        connectors.mcp_add("gone", command="no-such-command-anywhere")
        with self.assertRaises(Problem) as failed:
            connectors.mcp_test("gone")
        self.assertEqual(failed.exception.code, "mcp_command")
        connectors.mcp_add("closed", url="http://127.0.0.1:9/mcp")
        with self.assertRaises(Problem) as failed:
            connectors.mcp_test("closed")
        self.assertEqual((failed.exception.code, failed.exception.fix),
                         ("mcp_failed", "check the address and that the server is running"))


class AgentTests(Base):
    def test_agents_found_here_and_ones_of_your_own_are_listed_together(self):
        sys.path.insert(0, str(helpers.ROOT / "packages" / "external-agents"))
        self.addCleanup(sys.path.remove, str(helpers.ROOT / "packages" / "external-agents"))
        found = [{"kind": "agent", "provider": "acp:claude-acp", "name": "Claude Code", "plan": "your Claude plan",
                  "installed": True, "signed_in": True, "sign_in": "run claude and sign in (/login)", "model": "default"},
                 # One that is not on this computer is not "found" here.
                 {"kind": "agent", "provider": "acp:codex-acp", "name": "Codex", "plan": "your ChatGPT plan",
                  "installed": False, "signed_in": None, "sign_in": "run codex login", "model": "default"}]
        with mock.patch("harness.onboarding.agent_sources", lambda wait=True: found):
            self.assertEqual([(row["id"], row["state"], row["source"], row["signed_in"]) for row in connectors.agents()],
                             [("acp:claude-acp", "found", "found", True)])
            added = connectors.agent_add("mine", [sys.executable, "-c", "pass"])
            self.assertEqual(added, {"id": "acp:custom/mine"})
            rows = {row["id"]: row for row in connectors.agents()}
            self.assertEqual((rows["acp:custom/mine"]["state"], rows["acp:custom/mine"]["source"],
                              rows["acp:custom/mine"]["name"]), ("connected", "custom", "mine"))
            # A short name means your own command when there is one.
            self.assertEqual(connectors._agent_id("mine"), "acp:custom/mine")
            self.assertEqual(connectors.agent_remove("mine"), {"removed": "acp:custom/mine"})
            self.assertNotIn("acp:custom/mine", {row["id"] for row in connectors.agents()})
            with self.assertRaises(Problem) as refused:
                connectors.agent_remove("mine")
            self.assertEqual(refused.exception.code, "no_agent")


class SkillSourceTests(Base):
    def source(self):
        folder = Path(self.folder.name) / "their-skills"
        (folder / "tidy").mkdir(parents=True)
        (folder / "tidy" / "SKILL.md").write_text("---\nname: tidy-notes\ndescription: >\n  Put loose notes\n  into dated "
                                                  "files.\n---\n\nMove each note.\n", encoding="utf-8")
        (folder / "deep" / "rename").mkdir(parents=True)
        (folder / "deep" / "rename" / "SKILL.md").write_text("---\nname: rename photos\ndescription: By date.\n---\nRead "
                                                             "the date.\n", encoding="utf-8")
        (folder / "deep" / "rename" / "program.py").write_text("def main(event):\n    return 1\n", encoding="utf-8")
        return folder

    def life(self):
        from harness_agent.life import Life
        from harness_agent.state import Identity
        from test_agent_life import NoTasks, Recorder

        life = Life(Identity("default"), model=lambda: Recorder([]), tasks=lambda row: NoTasks())
        life.start()
        self.addCleanup(life.close)
        return life

    def test_a_source_brings_its_skills_as_proposed_and_takes_them_with_it_when_removed(self):
        sys.path.insert(0, str(helpers.ROOT / "packages" / "agent"))
        from harness_agent import sources

        life, folder = self.life(), self.source()
        held = sources.test(life, str(folder))
        self.assertEqual([(row["name"], row["description"], row["program"]) for row in held["skills"]],
                         [("rename photos", "By date.", True), ("tidy-notes", "Put loose notes into dated files.", False)])
        self.assertEqual(sources.listing(life)["sources"], [])   # testing takes nothing in
        added = sources.add(life, str(folder))
        self.assertEqual((added["kind"], added["added"], added["skipped"]), ("path", ["rename_photos", "tidy_notes"], []))
        skills = {row["name"]: row for row in life.learning.skills()}
        self.assertEqual({name: row["evidence"] for name, row in skills.items()},
                         {"rename_photos": "proposed", "tidy_notes": "proposed"})
        # Someone else's program waits; it is not a program the tree could run.
        taken = life.learning.skills_root / "rename_photos"
        self.assertTrue((taken / "program.proposed.py").is_file())
        self.assertFalse((taken / "program.py").exists())
        listed = sources.listing(life)["sources"][0]
        self.assertEqual((listed["id"], [skill["name"] for skill in listed["skills"]]),
                         (added["id"], ["rename_photos", "tidy_notes"]))
        with self.assertRaises(Problem) as again:
            sources.add(life, str(folder))
        self.assertEqual(again.exception.code, "source_exists")
        # A skill that appears in the source later is taken in by an update; the others stay.
        (folder / "new").mkdir()
        (folder / "new" / "SKILL.md").write_text("---\nname: new-one\ndescription: New.\n---\nx\n", encoding="utf-8")
        self.assertEqual(sources.update(life)["updated"], {added["id"]: ["new_one"]})
        removed = sources.remove(life, added["id"])
        self.assertEqual(sorted(removed["skills_removed"]), ["new_one", "rename_photos", "tidy_notes"])
        self.assertEqual((life.learning.skills(), sources.listing(life)["sources"]), ([], []))
        with self.assertRaises(Problem) as nothing:
            sources.add(life, str(folder / "tidy" / "missing"))
        self.assertEqual(nothing.exception.code, "source_unreadable")
