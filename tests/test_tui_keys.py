"""The keys of the terminal chat: a keystroke written as in Claude Code's keybindings file is
the key prompt_toolkit binds; what a terminal reports for a modified key (the kitty protocol,
xterm's modifyOtherKeys) is read as that key; a burst of console records with a line break
is a paste; the user's keybindings.json rebinds and unbinds over the defaults, and a mistake
in it is said, not fatal; /terminal-setup writes a terminal's Shift+Enter binding with a
backup and leaves alone what it cannot read."""
import json
from pathlib import Path
import tempfile
import unittest

import helpers  # noqa: F401
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPress
from prompt_toolkit.keys import Keys

from harness.tui import keymap, keys, terminal_setup


class KeystrokeTests(unittest.TestCase):
    def test_a_keystroke_is_the_keys_prompt_toolkit_binds(self):
        self.assertEqual(keys.keys("ctrl+k"), ("c-k",))
        self.assertEqual(keys.keys("Ctrl+K"), ("c-k",))  # names are read without their case
        self.assertEqual(keys.keys("shift+tab"), ("s-tab",))
        self.assertEqual(keys.keys("meta+p"), ("escape", "p"))
        self.assertEqual(keys.keys("option+enter"), ("escape", "enter"))
        self.assertEqual(keys.keys("shift+k"), ("K",))
        self.assertEqual(keys.keys("ctrl+_"), ("c-_",))
        self.assertEqual(keys.keys("ctrl+shift+-"), ("c-_",))
        self.assertEqual(keys.keys("esc"), ("escape",))
        self.assertEqual(keys.keys("ctrl+left"), ("c-left",))

    def test_a_key_without_a_name_is_carried_by_one_character(self):
        shift_enter, ctrl_enter = keys.keys("shift+enter"), keys.keys("ctrl+enter")
        self.assertEqual(len(shift_enter), 1)
        self.assertEqual(len(shift_enter[0]), 1)
        self.assertNotEqual(shift_enter, ctrl_enter)
        self.assertEqual(keys.keys("shift+return"), shift_enter)
        KeyBindings().add(*shift_enter)(lambda event: None)  # a key prompt_toolkit takes

    def test_a_chord_and_its_spelling(self):
        self.assertEqual(keys.chord("Control+X  ctrl+e"), ("ctrl+x", "ctrl+e"))
        self.assertEqual(keys.normal("shift+ctrl+c"), "ctrl+shift+c")

    def test_what_is_wrong_with_a_keystroke_is_said(self):
        for bad in ("ctl+k", "ctrl+", "ctrl+nokey", ""):
            with self.assertRaises(keys.KeystrokeError, msg=bad):
                keys.keys(bad) if bad else keys.chord(bad)
        with self.assertRaises(keys.KeystrokeError):
            keys.chord("ctrl+ k")  # a space next to +: a chord whose first keystroke names no key


class ReportedKeysTests(unittest.TestCase):
    """What a terminal that reports modified keys sends, as the documents of the kitty
    keyboard protocol and of xterm's modifyOtherKeys give it."""

    def setUp(self):
        self.before = set(keys.bound)
        keys.bound.clear()
        keys.bound.update({"shift+enter", "ctrl+enter", "ctrl+backspace"})
        self.addCleanup(lambda: (keys.bound.clear(), keys.bound.update(self.before)))
        self.read = keys.Translator()

    def test_shift_enter_in_both_forms(self):
        carrier = keys.carrier("shift+enter")
        self.assertEqual(self.read.feed("\x1b[13;2u"), carrier)        # kitty: CSI code ; modifiers u
        self.assertEqual(self.read.feed("\x1b[27;2;13~"), carrier)     # modifyOtherKeys: CSI 27 ; modifiers ; code ~
        self.assertEqual(self.read.feed("\x1b[13;5u"), keys.carrier("ctrl+enter"))
        self.assertEqual(self.read.feed("\x1b[13;3u"), "\x1b\r")       # Alt+Enter: Escape, Enter
        self.assertEqual(self.read.feed("\x1b[13;4u"), "\x1b" + carrier)  # Alt+Shift+Enter
        self.assertEqual(self.read.feed("\x1b[127;5u"), keys.carrier("ctrl+backspace"))

    def test_keys_that_have_bytes_of_their_own_become_those_bytes(self):
        self.assertEqual(self.read.feed("\x1b[27u"), "\x1b")                 # Escape
        self.assertEqual(self.read.feed("\x1b[99;5u"), "\x03")               # Ctrl+C
        self.assertEqual(self.read.feed("\x1b[27;5;99~"), "\x03")
        self.assertEqual(self.read.feed("\x1b[98;3u"), "\x1bb")              # Alt+B
        self.assertEqual(self.read.feed("\x1b[9;2u"), "\x1b[Z")              # Shift+Tab
        self.assertEqual(self.read.feed("\x1b[95;5u"), "\x1f")               # Ctrl+_
        self.assertEqual(self.read.feed("\x1b[27;129u"), "\x1b")             # Escape with Num Lock on
        self.assertEqual(self.read.feed("a\x1b[13;2ub"), "a" + keys.carrier("shift+enter") + "b")
        self.assertEqual(self.read.feed("\x1b[A\x1b[1;5D"), "\x1b[A\x1b[1;5D")  # other sequences as they are

    def test_an_unbound_key_falls_back_to_the_plain_one(self):
        keys.bound.discard("shift+enter")
        self.assertEqual(self.read.feed("\x1b[13;2u"), "\r")

    def test_a_report_cut_in_two_by_the_read(self):
        self.assertEqual(self.read.feed("ab\x1b[13"), "ab")
        self.assertEqual(self.read.feed(";2u"), keys.carrier("shift+enter"))
        self.assertEqual(self.read.feed("\x1b["), "")
        self.assertEqual(self.read.flush(), "\x1b[")  # nothing followed: given on as it came

    def test_the_terminal_answers_that_it_has_the_kitty_protocol(self):
        said = []
        self.read.on_kitty = lambda: said.append("on")
        self.assertEqual(self.read.feed("\x1b[?0u\x1b[?62;22c"), "")  # the flags, then the device attributes
        self.assertTrue(self.read.kitty)
        self.assertEqual(said, ["on"])
        other = keys.Translator()
        self.assertEqual(other.feed("\x1b[?62;22c"), "")  # only the device attributes: no protocol
        self.assertFalse(other.kitty)


@unittest.skipUnless(__import__("sys").platform == "win32", "the Windows console's key records")
class ConsoleRecordTests(unittest.TestCase):
    def setUp(self):
        self.before = set(keys.bound)
        keys.bound.clear()
        keys.bound.update({"shift+enter", "ctrl+enter", "ctrl+backspace"})
        self.addCleanup(lambda: (keys.bound.clear(), keys.bound.update(self.before)))
        self.reader = keys._reader()

    def test_the_records_prompt_toolkit_does_not_tell_apart(self):
        self.assertEqual(keys.record_key(13, False, True), "shift+enter")
        self.assertEqual(keys.record_key(13, True, False), "ctrl+enter")
        self.assertEqual(keys.record_key(8, True, False), "ctrl+backspace")
        self.assertEqual(keys.record_key(0x43, True, True), "ctrl+shift+c")
        self.assertIsNone(keys.record_key(13, False, False))
        self.assertIsNone(keys.record_key(0x43, True, False))

    def text(self, value):
        return [KeyPress(Keys.ControlM, "\r") if character == "\r" else KeyPress(character, character)
                for character in value]

    def test_a_burst_with_a_line_break_is_one_paste(self):
        found = self.reader.pasted_keys(self.text("line one\rline two\r"), now=100.0)
        self.assertEqual([(key.key, key.data) for key in found], [(Keys.BracketedPaste, "line one\nline two\n")])

    def test_typing_and_enter_alone_are_keys(self):
        typed = self.text("hello")
        self.assertEqual(self.reader.pasted_keys(typed, now=100.0), typed)
        enter = self.text("\r")
        self.assertEqual(self.reader.pasted_keys(enter, now=200.0), enter)

    def test_the_next_burst_of_a_long_paste_is_still_the_paste(self):
        self.reader.pasted_keys(self.text("a\rb"), now=100.0)
        found = self.reader.pasted_keys(self.text("\r"), now=100.01)   # the paste's line break, read alone
        self.assertEqual([key.key for key in found], [Keys.BracketedPaste])
        later = self.reader.pasted_keys(self.text("\r"), now=101.0)    # Enter pressed after it
        self.assertEqual([key.key for key in later], [Keys.ControlM])

    def test_a_tab_in_a_paste_is_text(self):
        found = self.reader.pasted_keys([*self.text("a"), KeyPress(Keys.ControlI, "\t"), *self.text("b\rc")], now=5.0)
        self.assertEqual([(key.key, key.data) for key in found], [(Keys.BracketedPaste, "a\tb\nc")])


class KeymapTests(unittest.TestCase):
    def test_the_defaults_and_the_file_made_from_them_read_without_a_problem(self):
        found = keymap.read(keymap.template())
        self.assertEqual(found.problems, [])
        self.assertEqual(found.bindings, keymap.defaults())
        self.assertEqual(found.key("chat:newline"), "ctrl+j")
        self.assertIn("shift+enter", found.of("chat:newline"))
        self.assertEqual(found.key("app:toggleTranscript"), "ctrl+o")

    def test_a_block_rebinds_and_unbinds(self):
        found = keymap.read(json.dumps({"bindings": [{"context": "Chat", "bindings": {
            "ctrl+k": "chat:newline", "ctrl+s": None, "ctrl+x ctrl+k": "command:clear"}}]}))
        self.assertEqual(found.problems, [])
        self.assertIn("ctrl+k", found.of("chat:newline"))
        self.assertEqual(found.of("chat:stash"), [])
        self.assertEqual(found.bindings["Chat"][("ctrl+x", "ctrl+k")], "command:clear")

    def test_mistakes_are_said_and_the_rest_applies(self):
        found = keymap.read(json.dumps({"bindings": [
            {"context": "Chat", "bindings": {"ctl+k": "chat:newline", "ctrl+ e": "chat:undo", "ctrl+c": "chat:newline",
                                             "ctrl+d": "chat:stash", "ctrl+b": "chat:nothing",
                                             "ctrl+y": "select:next", "f5": "chat:newline"}},
            {"context": "Nowhere", "bindings": {"a": "chat:newline"}},
            {"context": "ThemePicker", "bindings": {"ctrl+t": "theme:toggleSyntaxHighlighting"}}]}))
        text = "\n".join(found.problems)
        for expected in ("'ctl'", "names no key", "ctrl+c cannot be rebound", "ctrl+d cannot be rebound",
                         "'chat:nothing' is not an action", "action of the Select context", "'Nowhere' is not a context"):
            self.assertIn(expected, text)
        self.assertEqual(len(found.problems), 7)  # a context of Claude Code that is not here is no mistake
        self.assertIn("f5", found.of("chat:newline"))
        self.assertEqual(found.bindings["Global"][("ctrl+c",)], "app:interrupt")

    def test_a_key_bound_twice_is_said(self):
        found = keymap.read('{"bindings": [{"context": "Chat", "bindings": {"f5": "chat:undo", "f5": "chat:newline"}}]}')
        self.assertIn("f5 is bound twice", found.problems[0])
        self.assertIn("f5", found.of("chat:newline"))

    def test_a_file_that_is_not_json_keeps_the_defaults(self):
        found = keymap.read("{ not json")
        self.assertIn("not valid JSON", found.problems[0])
        self.assertEqual(found.bindings, keymap.defaults())

    def test_the_keys_that_arrive_as_carriers(self):
        self.assertEqual(keymap.Keymap(keymap.defaults()).carried(), {"shift+enter", "ctrl+enter"})


class TerminalSetupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)

    def run_in(self, environ, platform="linux"):
        return terminal_setup.run(environ, self.home, platform)

    def test_the_terminal_is_told_from_its_environment(self):
        self.assertEqual(terminal_setup.terminal({"TERM_PROGRAM": "vscode"}, "linux"), "vscode")
        self.assertEqual(terminal_setup.terminal({"TERM_PROGRAM": "vscode", "CURSOR_TRACE_ID": "x"}, "linux"), "cursor")
        self.assertEqual(terminal_setup.terminal({"TERM_PROGRAM": "vscode", "TMUX": "/tmp/x"}, "linux"), "tmux")
        self.assertEqual(terminal_setup.terminal({"WT_SESSION": "1"}, "win32"), "windows-terminal")
        self.assertEqual(terminal_setup.terminal({"TERM": "alacritty"}, "linux"), "alacritty")
        self.assertEqual(terminal_setup.shift_enter({"WT_SESSION": "1"}, "win32"), "native")
        self.assertEqual(terminal_setup.shift_enter({"TERM_PROGRAM": "vscode"}, "linux"), "setup")
        self.assertEqual(terminal_setup.shift_enter({"VTE_VERSION": "7600"}, "linux"), "no")

    def test_vscode_gets_the_binding_and_a_second_run_changes_nothing(self):
        path = self.home / ".config" / "Code" / "User" / "keybindings.json"
        said = self.run_in({"TERM_PROGRAM": "vscode"})
        self.assertIn("Installed VSCode terminal Shift+Enter key binding", said[0][0])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [terminal_setup.VSCODE_BINDING])
        again = self.run_in({"TERM_PROGRAM": "vscode"})
        self.assertIn("already configured", again[0][0])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [terminal_setup.VSCODE_BINDING])

    def test_existing_bindings_and_comments_are_kept_with_a_backup(self):
        path = self.home / ".config" / "Cursor" / "User" / "keybindings.json"
        path.parent.mkdir(parents=True)
        before = '// my keys\n[\n  { "key": "ctrl+shift+u", "command": "x", }, // trailing comma\n]\n'
        path.write_text(before, encoding="utf-8")
        said = self.run_in({"TERM_PROGRAM": "vscode", "CURSOR_TRACE_ID": "1"})
        self.assertIn("Installed Cursor", said[0][0])
        after = path.read_text(encoding="utf-8")
        self.assertIn("// my keys", after)
        items = json.loads(terminal_setup.strip_comments(after))
        self.assertEqual([item["key"] for item in items], ["ctrl+shift+u", "shift+enter"])
        backups = list(path.parent.glob("keybindings.json.*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), before)

    def test_a_binding_with_other_arguments_is_left_as_it_is(self):
        path = self.home / ".config" / "Code" / "User" / "keybindings.json"
        path.parent.mkdir(parents=True)
        mine = [{"key": "shift+enter", "command": "workbench.action.terminal.sendSequence", "args": {"text": "\\\r\n"},
                 "when": "terminalFocus"}]
        path.write_text(json.dumps(mine), encoding="utf-8")
        said = self.run_in({"TERM_PROGRAM": "vscode"})
        self.assertIn("different args", said[0][0])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), mine)

    def test_a_file_that_does_not_read_is_left_unchanged(self):
        path = self.home / ".config" / "Code" / "User" / "keybindings.json"
        path.parent.mkdir(parents=True)
        path.write_text("[ {broken", encoding="utf-8")
        said = self.run_in({"TERM_PROGRAM": "vscode"})
        self.assertIn("left unchanged", said[0][0])
        self.assertTrue(any("shift+enter" in text for text, _ in said))  # the block to add by hand
        self.assertEqual(path.read_text(encoding="utf-8"), "[ {broken")

    def test_a_remote_editor_session_says_where_to_install(self):
        said = self.run_in({"TERM_PROGRAM": "vscode", "SSH_CONNECTION": "1 2 3 4"})
        self.assertIn("remote", said[0][0])
        self.assertFalse((self.home / ".config" / "Code").exists())

    def test_alacritty_and_zed(self):
        said = self.run_in({"TERM": "alacritty"})
        path = self.home / ".config" / "alacritty" / "alacritty.toml"
        self.assertIn("Installed Alacritty", said[0][0])
        self.assertIn('key = "Return"\nmods = "Shift"\nchars = "\\u001B\\r"', path.read_text(encoding="utf-8"))
        self.assertIn("already configured", self.run_in({"TERM": "alacritty"})[0][0])
        said = self.run_in({"ZED_TERM": "true"})
        zed = self.home / ".config" / "zed" / "keymap.json"
        self.assertIn("Installed Zed", said[0][0])
        self.assertEqual(json.loads(zed.read_text(encoding="utf-8")), [terminal_setup.ZED_BINDING])

    def test_windows_keeps_the_editors_files_under_appdata(self):
        roaming = self.home / "Roaming"
        self.run_in({"TERM_PROGRAM": "vscode", "APPDATA": str(roaming)}, platform="win32")
        self.assertTrue((roaming / "Code" / "User" / "keybindings.json").is_file())

    def test_a_terminal_that_needs_nothing_and_one_that_cannot(self):
        self.assertIn("nothing to set up", self.run_in({"WT_SESSION": "1"}, platform="win32")[0][0])
        said = "\n".join(text for text, _ in self.run_in({"VTE_VERSION": "7600"}))
        self.assertIn("Terminal setup cannot be run from", said)
        self.assertIn("Ctrl+J", said)
        inside = "\n".join(text for text, _ in self.run_in({"TMUX": "/tmp/tmux-1/default,1,0"}))
        self.assertIn("extended-keys on", inside)


if __name__ == "__main__":
    unittest.main()
