"""What a program does on the machine goes by the user's approvals (runtime/safety/permissions.py)."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

import helpers  # noqa: F401
from harness.runtime.safety import permissions
from test_units import Episode, program


class Conversation:
    """What Programs needs of a conversation: its runtime, whether a user can be asked, and their answers."""

    def __init__(self, approvals=None, answers=(), interactive=True, physical=None):
        self.config = SimpleNamespace(runtime={**({"approvals": approvals} if approvals is not None else {}),
                                               **({"physical": {"level": physical}} if physical else {})})
        self.interactive, self.answers, self.asked, self.records = interactive, list(answers), [], []
        self.trace = SimpleNamespace(emit=lambda event, **detail: self.records.append((event, detail)))

    def _ask_user(self, kind, target, **detail):
        self.asked.append((kind, target))
        return self.answers.pop(0)


def step(conversation, action="command", key="git", what="git status", **more):
    programs = getattr(conversation, "programs", None) or permissions.Programs(conversation)
    conversation.programs = programs
    return programs.handle({"action": action, "key": key, "what": what, **more})


class Decisions(unittest.TestCase):
    def test_the_default_asks_once_for_each_kind_in_a_conversation(self):
        conversation = Conversation(answers=[(True, ""), (False, "not that one")])
        self.assertEqual(step(conversation), {"value": "session"})
        self.assertEqual(step(conversation), {"value": "session"})          # the same program again: not asked
        refused = step(conversation, key="curl", what="curl example.com")   # another program: asked, and refused
        self.assertEqual(conversation.asked, [("program", "run the command git status"),
                                              ("program", "run the command curl example.com")])
        self.assertIn("the user did not allow the program to run the command curl example.com: not that one",
                      refused["error"])
        self.assertEqual([(row["allowed"], row["asked"]) for _, row in conversation.records],
                         [(True, True), (True, False), (False, True)])

    def test_where_nobody_can_be_asked_a_level_that_asks_refuses_and_says_why(self):
        conversation = Conversation(interactive=False)
        answer = step(conversation, action="network", key="example.com", what="example.com:443")
        self.assertIn("nobody can be asked in this run", answer["error"])
        self.assertIn("connect to example.com:443", answer["error"])
        self.assertEqual(conversation.asked, [])

    def test_levels_and_rules(self):
        rules = [{"level": "allow", "action": "network", "match": "*.example.com"},
                 {"level": "never", "action": "command", "match": "rm"}]
        conversation = Conversation({"programs": "ask_each", "rules": rules}, answers=[(True, ""), (True, "")],
                                    interactive=True)
        # A rule wins over the level: allowed without asking, refused without asking.
        self.assertEqual(step(conversation, action="network", key="docs.example.com", what="docs.example.com:443"),
                         {"value": "session"})
        self.assertIn("never allow", step(conversation, key="rm", what="rm -rf x")["error"])
        # ask_each asks every time and is not remembered.
        self.assertEqual([step(conversation), step(conversation)], [{"value": "once"}, {"value": "once"}])
        self.assertEqual(len(conversation.asked), 2)
        # allow asks nobody, in a run without a user as well.
        self.assertEqual(step(Conversation({"programs": "allow"}, interactive=False)), {"value": "session"})
        with self.assertRaises(ValueError):
            permissions.rules([{"level": "allow", "action": "anything", "match": "*"}])

    def test_sensitive_steps_always_wait_and_skipping_confirmations_skips_the_rest(self):
        skipping = Conversation({"programs": "ask_each"}, answers=[(True, "")], physical="allow")
        self.assertEqual(step(skipping), {"value": "once"})
        self.assertEqual(skipping.asked, [])
        opened = step(skipping, action="read", key="k", what="open k, which holds credentials", sensitive="credentials")
        self.assertEqual((opened, skipping.asked), ({"value": "once"}, [("credentials", "open k, which holds credentials")]))
        # Allowed for everything else, a run without a user still refuses a sensitive step.
        alone = Conversation({"programs": "allow"}, interactive=False)
        self.assertIn("nobody can be asked", step(alone, action="write", key="f", what="delete f", sensitive="deleting")["error"])
        self.assertTrue(permissions.credentials(os.path.join("home", ".ssh", "known_hosts")))
        self.assertTrue(permissions.credentials(os.path.join("project", ".env.local")))
        self.assertFalse(permissions.credentials(os.path.join("site-packages", "certifi", "cacert.pem")))


class OnTheMachine(unittest.TestCase):
    """A real kernel: the step is asked about before it happens."""

    def run_program(self, body, approvals=None):
        with Episode([program(body), "<finish>done</finish>"],
                     runtime={**({"approvals": approvals} if approvals else {})}) as episode:
            summary = episode.end()
            result = episode.records("cell")[0]["result"]
            decisions = [(row["action"], row["allowed"]) for row in episode.records("program_permission")]
        self.assertEqual(summary["status"], "finished")
        return (result.get("stdout") or "").strip(), decisions

    def test_a_run_without_a_user_reads_freely_and_is_refused_what_its_settings_ask_about(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        port = server.getsockname()[1]
        with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) as elsewhere:
            Path(elsewhere, "notes.txt").write_text("readable", encoding="utf-8")
            Path(elsewhere, ".env").write_text("KEY=secret", encoding="utf-8")
            body = "\n".join([
                "import os, socket, subprocess, sys, tempfile",
                f"there = {elsewhere!r}",
                "def attempt(name, fn):",
                "    try:",
                "        print(name, fn())",
                "    except PermissionError as error:",
                "        print(name, 'refused:', 'nobody can be asked' in str(error))",
                "attempt('read', lambda: open(os.path.join(there, 'notes.txt')).read())",
                "mine = os.path.join(tempfile.gettempdir(), 'harness-test-own.txt')",
                "attempt('own', lambda: (open(mine, 'w').write('x'), os.remove(mine))[0])",
                "attempt('command', lambda: subprocess.run([sys.executable, '-c', 'print(1)'], capture_output=True).returncode)",
                f"attempt('network', lambda: socket.create_connection(('127.0.0.1', {port}), timeout=5).close())",
                "attempt('write', lambda: open(os.path.join(there, 'new.txt'), 'w').write('x'))",
                "attempt('credentials', lambda: open(os.path.join(there, '.env')).read())",
                "attempt('delete', lambda: os.remove(os.path.join(there, 'notes.txt')))"])
            printed, decisions = self.run_program(body)
            self.assertEqual(printed.splitlines(), [
                "read readable", "own 1", "command refused: True", "network refused: True", "write refused: True",
                "credentials refused: True", "delete refused: True"])
            self.assertEqual(decisions, [("command", False), ("network", False), ("write", False), ("read", False),
                                         ("write", False)])
            self.assertEqual(sorted(os.listdir(elsewhere)), [".env", "notes.txt"])

    def test_what_the_settings_allow_happens(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        threading.Thread(target=lambda: server.accept(), daemon=True).start()
        port = server.getsockname()[1]
        with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) as elsewhere:
            body = "\n".join([
                "import os, socket",
                f"socket.create_connection(('127.0.0.1', {port}), timeout=5).close(); print('connected')",
                "try:",
                f"    open(os.path.join({elsewhere!r}, 'new.txt'), 'w').write('x')",
                "except PermissionError:",
                "    print('write refused')"])
            printed, decisions = self.run_program(body, {"programs": "never", "rules": [
                {"level": "allow", "action": "network", "match": "127.0.0.1"}]})
        # The rule lets the connection through; everything else stays at the level.
        self.assertEqual(printed.splitlines(), ["connected", "write refused"])
        self.assertEqual(decisions, [("network", True), ("write", False)])


class TheWeb(unittest.TestCase):
    def test_a_page_is_given_as_its_text_within_a_limit_that_says_how_to_read_on(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from skills.web import Web, page_text

        page = ("<html><head><title>t</title><script>var x = 1</script></head><body><h1>Movements</h1>"
                "<p>placeCost defaults to <b>1</b>. See <a href='https://example.com/api'>the API</a>.</p>"
                + "<p>" + "word " * 30_000 + "</p></body></html>")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = page.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *arguments):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        text = Web().fetch(url)
        # The page's text, without its scripts, a link with its address.
        self.assertTrue(text.startswith("Movements\n\nplaceCost defaults to 1. See the API (https://example.com/api)."))
        self.assertNotIn("var x", text)
        whole = page_text(page, "text/html")
        self.assertEqual(len(text.split("\n... [")[0]), 100_000)
        self.assertTrue(text.endswith(f"\n... [{len(whole) - 100_000} more characters: fetch(url, start=100000)]"))
        self.assertEqual(Web().fetch(url, start=100_000), whole[100_000:])
        with self.assertRaises(ValueError):
            Web().fetch("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
