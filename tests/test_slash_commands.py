"""End-to-end contract tests for the unified slash command architecture."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_agent import commands as slash_commands
from harness_agent.life import Life
from harness_agent.state import Identity
from harness_external_agents.model import AcpModel


ACP_COMMANDS_STUB = r"""
import json, sys

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    msg = json.loads(line)
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": mid, "result": {"sessionId": "s-cmd"}})
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s-cmd",
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [
                    {"name": "cursor-fix", "description": "Fix lint issues in workspace", "input": {"hint": "<path>"}},
                    {"name": "review", "description": "Duplicate of builtin review"},
                ],
            },
        }})
    elif method == "session/prompt":
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s-cmd",
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}},
        }})
        send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn"}})
"""


class FakeReply:
    def __init__(self, text: str):
        self.text = text
        self.reasoning = ""
        self.usage = {"input_tokens": 120, "output_tokens": 20, "cost_usd": 0.0}
        self.seconds = 0.05


class CapturingModel:
    model = "fake-model"
    images = True

    def __init__(self):
        self.calls: list[dict] = []

    def complete(self, system, messages, **_kw):
        self.calls.append({"system": system, "messages": list(messages) if isinstance(messages, list) else []})
        return FakeReply(json.dumps({"action": "reply", "text": "Done."}))


class SlashCommandsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.ident = Identity("cmdtest", root=self.root / "identities", create=True)
        self.project = self.root / "repo"
        self.project.mkdir()
        self.fake_home = self.root / "home"
        self.fake_home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovery_precedence_custom_markdown_skills_and_acp_commands(self):
        # 1. Identity skills: one invocable, one marked user-invocable: false
        s1 = self.ident.directory / "skills" / "deploy-check"
        s1.mkdir(parents=True)
        (s1 / "SKILL.md").write_text(
            "---\nname: deploy-check\ndescription: Verify deploy health\nargument-hint: <env>\n---\nCheck $ARGUMENTS now.\n",
            encoding="utf-8",
        )
        s2 = self.ident.directory / "skills" / "internal-only"
        s2.mkdir(parents=True)
        (s2 / "SKILL.md").write_text(
            "---\nname: internal-only\ndescription: Hidden skill\nuser-invocable: false\n---\nSecret.\n",
            encoding="utf-8",
        )
        skills_meta = [
            {"name": "deploy-check", "description": "Verify deploy health", "evidence": "effective"},
            {"name": "internal-only", "description": "Hidden skill", "evidence": "effective"},
        ]

        # 2. User global .claude/commands + Project .claude/commands & .cursor/commands
        u_cmd = self.fake_home / ".claude" / "commands"
        u_cmd.mkdir(parents=True)
        (u_cmd / "triage.md").write_text("---\ndescription: User triage\n---\nUser body $ARGUMENTS", encoding="utf-8")

        p_claude = self.project / ".claude" / "commands" / "deploy"
        p_claude.mkdir(parents=True)
        (p_claude / "canary.md").write_text(
            "---\ndescription: Roll out canary\nargument-hint: <env> <ver>\nmode: ask\n---\nDeploy $2 to $1 ($ARGUMENTS).",
            encoding="utf-8",
        )
        p_cursor = self.project / ".cursor" / "commands"
        p_cursor.mkdir(parents=True)
        # Project overrides user triage
        (p_cursor / "triage.md").write_text("---\ndescription: Project triage\n---\nProject body", encoding="utf-8")
        # Dotfile & empty file must be safely skipped
        (p_cursor / ".hidden.md").write_text("hidden", encoding="utf-8")
        (p_cursor / "empty.md").write_text("   \n", encoding="utf-8")

        # 3. Live ACP available_commands_update through real AcpModel stdio peer
        stub = self.root / "acp_cmd_stub.py"
        stub.write_text(ACP_COMMANDS_STUB, encoding="utf-8")
        acp_model = AcpModel({"agent": "acp:cursor"}, [sys.executable, str(stub)])
        try:
            acp_model("", {}, {"messages": [{"role": "user", "content": "hi"}]}, 15)
            acp_cmds = list(acp_model.available_commands)
        finally:
            acp_model.close()
        self.assertEqual([c["name"] for c in acp_cmds], ["cursor-fix", "review"])

        with patch.object(slash_commands, "harness_home", return_value=self.fake_home / ".harness"), \
             patch.object(slash_commands.Path, "home", return_value=self.fake_home):
            catalog = slash_commands.discover(
                self.ident,
                folder=self.project,
                skills=skills_meta,
                acp_commands=acp_cmds,
                agent_label="cursor",
            )
            by_name = {row["name"]: row for row in catalog}

            # Core built-in workflows & actions present
            for required in ("goal", "learn", "plan", "grill-me", "schedule", "review", "init", "boost", "teamwork",
                             "compact", "new", "rename", "rewind", "diff", "context", "usage", "status"):
                self.assertIn(required, by_name)

            # Skill filtering & metadata
            self.assertIn("deploy-check", by_name)
            self.assertNotIn("internal-only", by_name)
            self.assertTrue(by_name["deploy-check"]["needs_arg"])

            # Namespaced .claude/commands + project precedence over user
            self.assertIn("deploy:canary", by_name)
            self.assertEqual(by_name["deploy:canary"]["mode"], "ask")
            self.assertEqual(by_name["triage"]["description_en"], "Project triage")
            self.assertEqual(by_name["triage"]["source"], "project:cursor")
            self.assertNotIn(".hidden", by_name)
            self.assertNotIn("empty", by_name)

            # ACP command surfaced in its own group; duplicate `review` does not shadow builtin
            self.assertEqual(by_name["cursor-fix"]["group"], "acp")
            self.assertEqual(by_name["cursor-fix"]["arg_hint_en"], "<path>")
            self.assertEqual(by_name["review"]["group"], "workflow")

            # Expansion checks: positional args, fallback append, bare /plan stays None
            exp_canary = slash_commands.expand("/deploy:canary staging v2.1", identity=self.ident, folder=self.project, skills=skills_meta)
            self.assertIsNotNone(exp_canary)
            self.assertEqual(exp_canary.prompt, "Deploy v2.1 to staging (staging v2.1).")
            self.assertEqual(exp_canary.mode, "ask")

            exp_triage = slash_commands.expand("/triage login 500 error", identity=self.ident, folder=self.project, skills=skills_meta)
            self.assertEqual(exp_triage.prompt, "Project body\n\nUser request:\nlogin 500 error")

            self.assertIsNone(slash_commands.expand("/plan", identity=self.ident, folder=self.project, skills=skills_meta))
            exp_plan = slash_commands.expand("/plan migrate auth to OAuth2", identity=self.ident, folder=self.project, skills=skills_meta)
            self.assertEqual(exp_plan.mode, "plan")
            self.assertIn("migrate auth to OAuth2", exp_plan.prompt)

    def test_life_say_expands_workflow_without_polluting_user_record_and_switches_plan_mode(self):
        cap = CapturingModel()
        life = Life(self.ident, model=lambda *_a, **_kw: cap, tasks=lambda row=None: None)
        try:
            chat_id = life.chats.new("Slash test")
            # Bind project with a custom .claude/commands/ship.md
            p_dir = self.project / ".claude" / "commands"
            p_dir.mkdir(parents=True)
            (p_dir / "ship.md").write_text("---\ndescription: Ship release\n---\nRelease $ARGUMENTS safely.", encoding="utf-8")
            place = life.project(str(self.project))
            life.work_in(chat_id, place["id"])

            # 1. `/goal` keeps clean user record while sending expanded goal loop prompt to model
            res = life.say(chat_id, "/goal pass all integration tests", wait=True, timeout=15)
            self.assertEqual(res.get("answer"), "Done.")
            recs = [r for r in life.chats.read(chat_id) if r.get("event") == "user"]
            self.assertEqual(recs[-1]["text"], "/goal pass all integration tests")
            self.assertEqual(recs[-1].get("command"), "goal")
            sent_msgs = cap.calls[-1]["messages"]
            last_user = next(m for m in reversed(sent_msgs) if m.get("role") == "user")
            self.assertNotIn("expanded", last_user)
            self.assertIn("[Slash command: /goal]", last_user["content"])
            self.assertIn("pass all integration tests", last_user["content"])

            # 2. `/plan <task>` atomically switches chat mode to `plan` and expands planning prompt
            life.say(chat_id, "/plan design caching layer", wait=True, timeout=15)
            self.assertEqual(life.chats.meta(chat_id).get("mode"), "plan")
            last_user = next(m for m in reversed(cap.calls[-1]["messages"]) if m.get("role") == "user")
            self.assertIn("[Slash command: /plan]", last_user["content"])
            self.assertIn("design caching layer", last_user["content"])

            # 3. `Life.commands(chat_id)` discovers project `.claude/commands/ship.md`
            listed = {row["name"]: row for row in life.commands(chat_id)["commands"]}
            self.assertIn("ship", listed)
            life.say(chat_id, "/ship v1.2", wait=True, timeout=15)
            last_user = next(m for m in reversed(cap.calls[-1]["messages"]) if m.get("role") == "user")
            self.assertEqual(last_user["content"], "Release v1.2 safely.")
        finally:
            life.close()


if __name__ == "__main__":
    unittest.main()
