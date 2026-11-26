"""Editing the terminal chat's input as Claude Code's is edited: the word keys take a word
to be letters and digits, Ctrl+W goes back to the whitespace, what a word or line key
deletes is pasted again, Up and Down move between the rows a draft shows, a long paste is a
chip that is sent whole; and its history: kept per directory, the same message twice in a
row once, a cleared draft walked in this session, every directory searched."""
import json
from pathlib import Path
import tempfile
import unittest

import helpers  # noqa: F401
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.clipboard import InMemoryClipboard
from prompt_toolkit.document import Document

from harness.tui import clipboard, editing
from harness.tui.history import History


class WordTests(unittest.TestCase):
    def test_alt_b_stops_where_claude_codes_documentation_says(self):
        text = "open src/utils/foo.ts"
        stops, at = [], len(text)
        while at:
            at = editing.word_start(text, at)
            stops.append(text[at:].split("/")[0].split(".")[0].split(" ")[0])
        self.assertEqual(stops, ["ts", "foo", "utils", "src", "open"])

    def test_alt_f_goes_to_the_end_of_this_word_or_of_the_next(self):
        text = "some_name = value"
        self.assertEqual(editing.word_end(text, 0), 4)     # "some": the underscore separates words
        self.assertEqual(editing.word_end(text, 4), 9)     # between words: the end of "name"
        self.assertEqual(editing.word_end(text, 9), 17)

    def test_text_without_spaces_moves_a_run_at_a_time(self):
        text = "これはテストです"
        self.assertEqual(editing.word_start(text, len(text)), 6)   # "です"
        self.assertEqual(editing.word_start(text, 6), 3)           # "テスト"
        self.assertEqual(editing.word_start("修复 bug 之后", 9), 7)

    def test_kills_go_to_the_ring_and_come_back(self):
        buffer, ring = Buffer(multiline=True), InMemoryClipboard()
        buffer.set_document(Document("run src/utils/foo.ts now", 20))
        editing.kill(buffer, ring, editing.word_start(buffer.text, 20), 20)   # Alt+Backspace
        self.assertEqual((buffer.text, ring.get_data().text), ("run src/utils/foo. now", "ts"))
        buffer.undo()
        self.assertEqual(buffer.text, "run src/utils/foo.ts now")


class RowTests(unittest.TestCase):
    def test_a_long_line_wraps_into_rows_by_cells(self):
        self.assertEqual(editing.rows("abcdefgh", 3), [(0, 3), (3, 6), (6, 8)])
        self.assertEqual(editing.rows("汉字汉字汉", 4), [(0, 2), (2, 4), (4, 5)])  # each two cells wide
        self.assertEqual(editing.rows("ab\n\ncd", 10), [(0, 2), (3, 3), (4, 6)])

    def test_up_and_down_keep_the_column_and_stop_at_the_edges(self):
        buffer = Buffer(multiline=True)
        buffer.set_document(Document("first line\nsecond\nthird line", 25))  # row 3, column 7
        self.assertTrue(editing.vertical(buffer, 40, -1))
        self.assertEqual(buffer.cursor_position, 17)  # the end of "second": it is shorter
        self.assertTrue(editing.vertical(buffer, 40, -1))
        self.assertEqual(buffer.cursor_position, 6)
        self.assertFalse(editing.vertical(buffer, 40, -1))  # the first row: the history's turn
        buffer.cursor_position = len(buffer.text)
        self.assertFalse(editing.vertical(buffer, 40, 1))

    def test_a_wrapped_line_is_rows_too(self):
        buffer = Buffer(multiline=True)
        buffer.set_document(Document("x" * 25, 22))
        self.assertTrue(editing.vertical(buffer, 10, -1))
        self.assertEqual(buffer.cursor_position, 12)


class ChipTests(unittest.TestCase):
    def test_a_short_paste_is_text_and_a_long_one_a_chip_sent_whole(self):
        kept = editing.Attachments()
        self.assertEqual(kept.paste("one\r\ntwo\rthree"), "one\ntwo\nthree")   # three lines: as it is
        long = "\n".join(f"line {number}" for number in range(121))
        chip = kept.paste(long)
        self.assertEqual(chip, "[Pasted text #1 +120 lines]")
        self.assertEqual(kept.paste("x" * 801), "[Pasted text #2]")
        text, files = kept.expand(f"look at {chip} please")
        self.assertEqual((text, files), (f"look at {long} please", []))

    def test_an_image_chip_stays_and_its_file_goes_with_the_message(self):
        kept = editing.Attachments()
        chip = kept.image("C:/pasted/image-1.png")
        self.assertEqual(chip, "[Image #1]")
        self.assertEqual(kept.expand(f"what is {chip}?"), ("what is [Image #1]?", ["C:/pasted/image-1.png"]))

    def test_what_chips_stand_for_is_kept_with_a_recalled_message(self):
        kept = editing.Attachments()
        chip = kept.paste("a\nb\nc\nd\ne")
        saved = json.loads(json.dumps(kept.kept(f"see {chip}")))  # as the history file keeps it
        later = editing.Attachments()
        later.restore(saved)
        self.assertEqual(later.expand(f"see {chip}")[0], "see a\nb\nc\nd\ne")

    def test_a_delete_that_cuts_into_a_chip_takes_all_of_it(self):
        buffer, ring = Buffer(multiline=True), InMemoryClipboard()
        text = "see [Pasted text #1 +4 lines] now"
        buffer.set_document(Document(text, 20))
        editing.kill(buffer, ring, 12, 20)
        self.assertEqual(buffer.text, "see  now")
        buffer.set_document(Document(text, 29))
        editing.backspace(buffer)
        self.assertEqual(buffer.text, "see  now")
        buffer.set_document(Document("abc", 3))
        editing.backspace(buffer)
        self.assertEqual(buffer.text, "ab")


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)

    def test_up_walks_this_directorys_messages_from_earlier_sessions_too(self):
        first = History(self.directory, "project-a")
        first.add("build it")
        first.add("test it")
        History(self.directory, "project-b").add("something else")
        again = History(self.directory, "project-a")  # a later session
        self.assertEqual(again.previous("draft")["text"], "test it")
        self.assertEqual(again.previous("")["text"], "build it")
        self.assertIsNone(again.previous(""))
        self.assertEqual(again.next()["text"], "test it")
        self.assertEqual(again.next()["text"], "draft")  # past the newest: what was being typed
        self.assertIsNone(again.next())

    def test_the_same_message_twice_in_a_row_is_kept_once(self):
        history = History(self.directory, "here")
        for text in ("run", "run", "check", "run", "   "):
            history.add(text)
        self.assertEqual([entry["text"] for entry in history.here()], ["run", "check", "run"])

    def test_a_cleared_draft_comes_back_with_up_in_this_session_only(self):
        history = History(self.directory, "here")
        history.add("sent before")
        history.draft("a long draft")
        self.assertEqual(history.previous("")["text"], "a long draft")
        self.assertEqual(history.previous("")["text"], "sent before")
        for number in range(12):
            history.draft(f"draft {number}")
        self.assertEqual(len(history.drafts), 10)
        self.assertEqual([entry["text"] for entry in History(self.directory, "here").here()], ["sent before"])

    def test_search_finds_the_messages_of_every_directory_newest_first(self):
        History(self.directory, "elsewhere").add("deploy the staging server")
        history = History(self.directory, "here")
        history.add("deploy to production")
        history.add("something else")
        self.assertEqual(history.search("deploy")["text"], "deploy to production")
        self.assertEqual(history.search("deploy", 1)["text"], "deploy the staging server")
        self.assertIsNone(history.search("deploy", 2))
        self.assertIsNone(history.search("nothing like it"))

    def test_a_word_of_a_long_paste_finds_its_message(self):
        history = History(self.directory, "here")
        history.add("why does [Pasted text #1 +9 lines] fail", {"pastes": {1: "Traceback: ZeroDivisionError"}})
        self.assertIn("Pasted text #1", history.search("zerodivision")["text"])

    def test_the_history_of_an_earlier_version_is_read_once(self):
        (self.directory / "tui-history").write_text("\n# 2026-11-01 10:00:00\n+first message\n\n# 2026-11-01 10:01:00\n"
                                                    "+two\n+lines\n", encoding="utf-8")
        history = History(self.directory, "here")
        self.assertEqual(history.search("first")["text"], "first message")
        self.assertEqual(history.search("lines")["text"], "two\nlines")
        self.assertEqual(history.here(), [])  # written before messages were kept per directory
        self.assertFalse((self.directory / "tui-history").exists())


class ClipboardTests(unittest.TestCase):
    def test_copy_uses_the_systems_program_and_else_asks_the_terminal(self):
        ran, written = [], []
        done = lambda command, text=None, timeout=15: (ran.append((command, text)), type("Done", (), {"returncode": 0}))[1]  # noqa: E731
        self.assertEqual(clipboard.copy("hello", written.append, run=done, command=["pbcopy"]), "clipboard")
        self.assertEqual(ran, [(["pbcopy"], "hello")])
        failed = lambda command, text=None, timeout=15: type("Done", (), {"returncode": 1})  # noqa: E731
        self.assertEqual(clipboard.copy("hello", written.append, run=failed, command=["pbcopy"]), "terminal")
        self.assertEqual(written, ["\x1b]52;c;aGVsbG8=\x07"])

    def test_a_remote_shell_copies_through_the_terminal(self):
        self.assertIsNone(clipboard.copier("linux", {"SSH_CONNECTION": "1 2 3 4"}))
        self.assertEqual(clipboard.copier("darwin", {}), ["pbcopy"])
        self.assertTrue(clipboard.osc52("x", {"TMUX": "1"}).startswith("\x1bPtmux;"))


if __name__ == "__main__":
    unittest.main()
