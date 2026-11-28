"""End-to-end contract tests for ACP v1 parameterized model configOptions (Effort, Context, Fast, Thinking)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness import model_list, onboarding, providers
from harness.config import dumps
from harness_agent.chats import Chats
from harness_agent.life import Life
from harness_agent.state import Identity
from harness_external_agents import host as ext_host
from harness_external_agents.acp import AcpSession
from harness_external_agents.model import AcpModel


# Real stdio ACP v1 stub mirroring Cursor's parameterizedModelPicker + Claude's speed/model_config options.
STUB_ACP = r"""
import json, sys

state = {
    "parameterized": False,
    "model": "grok-4.7",
    "mode": "agent",
    "opts": {
        "grok-4.7": {"context": "256k", "reasoning_effort": "high", "fast": "true"},
        "claude-opus-5": {"thinking": "true", "context": "300k", "effort": "high", "fast": "false"},
        "gpt-5-mini": {},
    },
    "calls": [],
}

def build_config_options():
    if not state["parameterized"]:
        return [
            {"id": "mode", "name": "Mode", "category": "mode", "type": "select", "currentValue": state["mode"],
             "options": [{"value": "agent", "name": "Agent"}, {"value": "ask", "name": "Ask"}]},
            {"id": "model", "name": "Model", "category": "model", "type": "select",
             "currentValue": "grok-4.7[context=256k,reasoning_effort=high,fast=true]",
             "options": [
                 {"value": "grok-4.7[context=256k,reasoning_effort=high,fast=true]", "name": "grok-4.7"},
             ]},
        ]
    cur = state["model"]
    vals = state["opts"][cur]
    out = [
        {"id": "mode", "name": "Mode", "category": "mode", "type": "select", "currentValue": state["mode"],
         "options": [{"value": "agent", "name": "Agent"}, {"value": "ask", "name": "Ask"}]},
        {"id": "model", "name": "Model", "category": "model", "type": "select", "currentValue": cur,
         "options": [
             {"group": "xAI", "options": [{"value": "grok-4.7", "name": "Grok 4.7"}]},
             {"group": "Anthropic", "options": [{"value": "claude-opus-5", "name": "Claude Opus 5"}]},
             {"value": "gpt-5-mini", "name": "GPT-5 Mini"},
         ]},
    ]
    if cur == "grok-4.7":
        out.extend([
            {"id": "context", "name": "Context", "category": "model_config", "type": "select",
             "currentValue": vals["context"],
             "options": [{"value": "256k", "name": "256K"}, {"value": "500k", "name": "500K"}]},
            {"id": "reasoning_effort", "name": "Effort", "category": "thought_level", "type": "select",
             "currentValue": vals["reasoning_effort"],
             "options": [
                 {"value": "low", "name": "Low"}, {"value": "medium", "name": "Medium"},
                 {"value": "high", "name": "High"}, {"value": "xhigh", "name": "Extra High"},
             ]},
            {"id": "fast", "name": "Fast", "category": "model_config", "type": "select",
             "currentValue": vals["fast"],
             "options": [{"value": "false", "name": "Off"}, {"value": "true", "name": "Fast"}]},
        ])
    elif cur == "claude-opus-5":
        out.extend([
            {"id": "thinking", "name": "Thinking", "category": "thought_level", "type": "select",
             "currentValue": vals["thinking"],
             "options": [{"value": "false", "name": "Off"}, {"value": "true", "name": "On"}]},
            {"id": "context", "name": "Context", "category": "model_config", "type": "select",
             "currentValue": vals["context"],
             "options": [{"value": "300k", "name": "300K"}, {"value": "1m", "name": "1M"}]},
            {"id": "effort", "name": "Effort", "category": "thought_level", "type": "select",
             "currentValue": vals["effort"],
             "options": [{"value": "medium", "name": "Medium"}, {"value": "high", "name": "High"}]},
            {"id": "fast", "name": "Fast", "category": "speed", "type": "select",
             "currentValue": vals["fast"],
             "options": [{"value": "false", "name": "Off"}, {"value": "true", "name": "Fast"}]},
        ])
    return out

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    msg = json.loads(line)
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        meta = (params.get("clientCapabilities") or {}).get("_meta") or {}
        state["parameterized"] = bool(meta.get("parameterizedModelPicker"))
        send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "sessionId": "s1",
            "configOptions": build_config_options(),
        }})
    elif method == "session/set_config_option":
        cid, val = params["configId"], params["value"]
        state["calls"].append([cid, val])
        if cid == "model":
            state["model"] = val
        elif cid == "mode":
            state["mode"] = val
        else:
            state["opts"][state["model"]][cid] = val
        send({"jsonrpc": "2.0", "id": mid, "result": {"configOptions": build_config_options()}})
    elif method == "session/prompt":
        reply = json.dumps({"model": state["model"], "opts": state["opts"][state["model"]], "calls": state["calls"]})
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1",
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": reply}},
        }})
        send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn"}})
"""


class AcpModelConfigOptionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.stub = self.root / "stub_acp.py"
        self.stub.write_text(STUB_ACP, encoding="utf-8")
        self.argv = [sys.executable, str(self.stub)]

    def tearDown(self):
        self.tmp.cleanup()

    def test_acp_model_negotiates_parameterized_options_switches_models_and_migrates_legacy_brackets(self):
        # 1. Switch from default grok-4.7 -> claude-opus-5, then apply its model-specific options
        #    (thinking=false, context=1m, fast=true, effort=medium) via refreshed configOptions.
        model = AcpModel(
            {
                "agent": "acp:cursor",
                "model": "claude-opus-5",
                "reasoning_effort": "medium",
                "model_options": {"thinking": "false", "context": "1m", "fast": "true"},
            },
            self.argv,
        )
        try:
            reply = model("", {}, {"messages": [{"role": "user", "content": "ping"}]}, 30)
            info = json.loads(reply["choices"][0]["message"]["content"])
            self.assertEqual(info["model"], "claude-opus-5")
            self.assertEqual(
                info["opts"],
                {"thinking": "false", "context": "1m", "effort": "medium", "fast": "true"},
            )
            # Context window is seeded from `context=1m` -> 1_000_000
            conv = next(iter(model.sessions.values()))
            self.assertEqual(conv.window, 1_000_000)
        finally:
            model.close()

        # 2. Legacy bracket-encoded Cursor ID ("grok-4.7[context=500k,reasoning_effort=xhigh,fast=false]")
        #    works seamlessly with parameterizedModelPicker enabled, and explicit overrides win.
        legacy = AcpModel(
            {
                "agent": "acp:cursor",
                "model": "grok-4.7[context=500k,reasoning_effort=xhigh,fast=false]",
                "model_options": {"fast": "true"},
            },
            self.argv,
        )
        try:
            reply = legacy("", {}, {"messages": [{"role": "user", "content": "ping"}]}, 30)
            info = json.loads(reply["choices"][0]["message"]["content"])
            self.assertEqual(info["model"], "grok-4.7")
            self.assertEqual(
                info["opts"],
                {"context": "500k", "reasoning_effort": "xhigh", "fast": "true"},
            )
            conv = next(iter(legacy.sessions.values()))
            self.assertEqual(conv.window, 500_000)
        finally:
            legacy.close()

        # 3. Unknown or unsupported option for a minimal model (gpt-5-mini) fails loudly.
        bad = AcpModel(
            {"agent": "acp:cursor", "model": "gpt-5-mini", "model_options": {"fast": "true"}},
            self.argv,
        )
        try:
            with self.assertRaises(ValueError):
                bad("", {}, {"messages": [{"role": "user", "content": "ping"}]}, 30)
        finally:
            bad.close()

    def test_onboarding_discovers_all_non_mode_config_options_and_normalizes_legacy_entries(self):
        class FakeModule:
            @staticmethod
            def agents():
                return [{"id": "acp:cursor", "kind": "acp", "installed": True}]

            @staticmethod
            def session_adapter(provider, directory, *, cwd, isolation, model, effort):
                return AcpSession(directory, provider, cwd, self_argv, model=model, effort=effort)

        self_argv = self.argv
        with patch("harness.extensions.modules", return_value=[FakeModule()]):
            # Grok 4.7 discovery (grouped model options + effort_labels + context + fast)
            grok = onboarding._declared("acp:cursor", "grok-4.7")
            self.assertEqual([m["id"] for m in grok["models"]], ["grok-4.7", "claude-opus-5", "gpt-5-mini"])
            self.assertEqual(grok["efforts"], ["low", "medium", "high", "xhigh"])
            self.assertEqual(grok["effort_labels"]["xhigh"], "Extra High")
            self.assertEqual(grok["effort_default"], "high")
            opt_ids = [o["id"] for o in grok["options"]]
            self.assertEqual(opt_ids, ["context", "fast"])
            self.assertEqual([c["value"] for c in grok["options"][0]["options"]], ["256k", "500k"])

            # Claude Opus 5 discovery includes category="speed" (fast) AND category="model_config" (thinking, context)
            opus = onboarding._declared("acp:cursor", "claude-opus-5")
            self.assertEqual([o["id"] for o in opus["options"]], ["thinking", "context", "fast"])
            self.assertEqual(opus["efforts"], ["medium", "high"])

            # Legacy bracket-encoded entry gets normalized cleanly by described()
            with patch.object(onboarding, "prepare_agent", lambda *_a, **_kw: None):
                onboarding._OFFERED.clear()
                desc = onboarding.described(
                    self.root,
                    {"provider": "acp:cursor", "model": "grok-4.7[context=256k,reasoning_effort=high,fast=true]", "base_url": None},
                )
            self.assertEqual(desc["model"], "grok-4.7")
            self.assertEqual(desc["name"], "Grok 4.7")
            self.assertEqual(desc["efforts"], ["low", "medium", "high", "xhigh"])
            self.assertEqual([o["id"] for o in desc["options"]], ["context", "fast"])

    def test_model_list_providers_and_chat_persistence_roundtrip_model_options(self):
        # Parse legacy helper does NOT mangle non-kv suffixes like claude-fable-5-2[1m]
        self.assertIsNone(model_list.parse_legacy_cursor_model("claude-fable-5-2[1m]"))
        self.assertEqual(
            model_list.parse_legacy_cursor_model("grok-4.7[context=256k,reasoning_effort=high,fast=true]"),
            ("grok-4.7", "high", {"context": "256k", "fast": "true"}),
        )

        # Save model with ACP options to models.json and verify reload + validation + TOML role generation
        rows = model_list.models(
            self.root,
            {
                "action": "save",
                "provider": "acp:cursor",
                "model": "grok-4.7",
                "name": "Grok 4.7",
                "efforts": ["low", "medium", "high", "xhigh"],
                "effort_default": "high",
                "effort_labels": {"xhigh": "Extra High"},
                "options": [
                    {"id": "context", "name": "Context", "category": "model_config", "default": "256k",
                     "options": [{"value": "256k", "name": "256K"}, {"value": "500k", "name": "500K"}]},
                    {"id": "fast", "name": "Fast", "category": "model_config", "default": "true",
                     "options": [{"value": "false", "name": "Off"}, {"value": "true", "name": "Fast"}]},
                ],
            },
        )
        entry = rows[0]
        self.assertEqual([o["id"] for o in entry["options"]], ["context", "fast"])
        self.assertEqual(
            model_list.validate_model_options(entry, {"context": "500k", "fast": "false"}),
            {"context": "500k", "fast": "false"},
        )
        with self.assertRaises(ValueError):
            model_list.validate_model_options(entry, {"context": "999k"})

        role = providers.model_role(entry, {"reasoning_effort": "xhigh", "model_options": {"context": "500k", "fast": "false"}})
        self.assertEqual(role["model_options"], {"context": "500k", "fast": "false"})
        # TOML roundtrip
        import tomllib
        self.assertEqual(tomllib.loads(dumps({"main": role}))["main"]["model_options"], {"context": "500k", "fast": "false"})

        # Life.chat_change persists model_options in meta.json and passes them to model_factory
        seen_calls = []

        def fake_model(name=None, effort=None, model_options=None):
            seen_calls.append((name, effort, model_options))
            return object()

        ident = Identity("default", root=self.root / "identities", create=True)
        life = Life(ident, model=fake_model)
        chat_id = life.chats.new("Cursor options test")
        with patch("harness.sdk.data", return_value=self.root):
            life.chat_change(
                chat_id,
                "model",
                model=entry["id"],
                effort="xhigh",
                model_options={"context": "500k", "fast": "false"},
            )
            listing = {r["chat"]: r for r in life.chats.listing()}
            self.assertEqual(listing[chat_id]["effort"], "xhigh")
            self.assertEqual(listing[chat_id]["model_options"], {"context": "500k", "fast": "false"})
            life._model(chat_id)
            self.assertEqual(seen_calls[-1], (entry["id"], "xhigh", {"context": "500k", "fast": "false"}))

    def test_windows_node_cmd_unwrapping_and_environment_allowlist(self):
        # 1. Sibling node.exe + index.js (Cursor dist-package layout) unwraps directly
        pkg = self.root / "dist-package"
        pkg.mkdir()
        cmd = pkg / "cursor-agent.cmd"
        node = pkg / "node.exe"
        js = pkg / "index.js"
        for p in (cmd, node, js):
            p.write_text("", encoding="utf-8")

        with patch.object(ext_host.os, "name", "nt"):
            self.assertEqual(ext_host._unwrap_windows_node_cmd(cmd), [str(node), str(js)])
            with patch.object(ext_host.shutil, "which", return_value=str(cmd)):
                self.assertEqual(
                    ext_host.command({"argv": [str(cmd), "acp"]}),
                    [str(node.resolve()), str(js.resolve()), "acp"],
                )
        with patch.object(ext_host.os, "name", "posix"):
            self.assertIsNone(ext_host._unwrap_windows_node_cmd(cmd))

        # 2. Versioned layout (versions/<latest>/node.exe + index.js) picks newest version
        vroot = self.root / "versioned"
        for ver in ("2026.01.01", "2026.02.15"):
            d = vroot / "versions" / ver
            d.mkdir(parents=True)
            (d / "node.exe").write_text("", encoding="utf-8")
            (d / "index.js").write_text("", encoding="utf-8")
        vcmd = vroot / "agent.cmd"
        vcmd.write_text("", encoding="utf-8")
        with patch.object(ext_host.os, "name", "nt"):
            self.assertEqual(
                ext_host._unwrap_windows_node_cmd(vcmd),
                [str(vroot / "versions" / "2026.02.15" / "node.exe"),
                 str(vroot / "versions" / "2026.02.15" / "index.js")],
            )

        # 3. Non-node .cmd launcher returns None
        plain = self.root / "plain"
        plain.mkdir()
        plain_cmd = plain / "tool.cmd"
        plain_cmd.write_text("", encoding="utf-8")
        with patch.object(ext_host.os, "name", "nt"):
            self.assertIsNone(ext_host._unwrap_windows_node_cmd(plain_cmd))

        # 4. Proxy and NODE_COMPILE_CACHE vars are preserved in external agent env
        with patch.dict(
            ext_host.os.environ,
            {"HTTPS_PROXY": "http://127.0.0.1:7890", "NODE_COMPILE_CACHE": "/tmp/cache"},
            clear=False,
        ):
            env = ext_host.environment({})
            self.assertEqual(env.get("HTTPS_PROXY"), "http://127.0.0.1:7890")
            self.assertEqual(env.get("NODE_COMPILE_CACHE"), "/tmp/cache")


if __name__ == "__main__":
    unittest.main()
