"""The agent's text in the terminal chat: what looks like HTML is shown as written, not left
out; a line break and a key keep their meaning; Markdown without tags reads as before."""
import io
import unittest

import helpers  # noqa: F401
from rich.console import Console
from rich.markdown import Markdown

from harness.tui.answer import Answer


def shown(renderable, width=100) -> str:
    out = io.StringIO()
    Console(file=out, force_terminal=False, width=width).print(renderable)
    return "\n".join(line.rstrip() for line in out.getvalue().strip().splitlines())


class AnswerTests(unittest.TestCase):
    def test_text_that_looks_like_html_is_shown_as_written(self):
        for text in ("Use Vec<String> for a list of strings.",
                     "Generic HashMap<K, V> and <T extends Foo> bounds.",
                     "<h1>Title</h1> and <title>x</title>",
                     "<div>a whole block</div>",
                     "**bold <i>x</i>**"):
            with self.subTest(text=text):
                self.assertEqual(shown(Answer(text)), text.replace("**", ""))

    def test_the_lines_after_a_block_tag_are_not_lost(self):
        # A <div> line starts an HTML block that runs to the next blank line: rich showed
        # only the first of these four lines.
        text = "Use Vec<String> for a list.\n<div>whole block</div>\nLine one\nPress Ctrl+C."
        self.assertEqual(shown(Answer(text)), text.replace("\n", " "))

    def test_code_and_links_read_as_before(self):
        for text in ("Compare `Vec<String>` in code.", "```html\n<div class=\"a\">x</div>\n```",
                     "See <https://example.com> for more.", "if a < b and c > d: ~~gone~~"):
            with self.subTest(text=text):
                self.assertEqual(shown(Answer(text)), shown(Markdown(text)))

    def test_a_line_break_breaks_the_line(self):
        self.assertEqual(shown(Answer("one<br>two<BR/>three<br />four")), "one\ntwo\nthree\nfour")
        self.assertIn("y", shown(Answer("| a | b |\n|---|---|\n| x<br>y | <T> |")).splitlines()[-1])

    def test_a_key_keeps_its_style(self):
        console = Console(file=io.StringIO(), force_terminal=True, width=80)
        segments = list(console.render(Answer("Press <kbd>Ctrl</kbd>+C.")))
        key = next(segment for segment in segments if segment.text == "Ctrl")
        self.assertTrue(key.style and key.style.bold)
        self.assertEqual(shown(Answer("Press <kbd>Ctrl</kbd>+C.")), "Press Ctrl+C.")

    def test_a_key_closed_that_was_not_opened_is_text(self):
        # rich itself fails on it (IndexError).
        self.assertEqual(shown(Answer("a stray </kbd> here")), "a stray </kbd> here")

    def test_markdown_without_tags_reads_as_before(self):
        text = ("# Plan\n\nSome **bold**, *em* and `code`.\n\n- one\n- two\n\n1. first\n2. second\n\n"
                "> quoted\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1 < 2)\n```\n\n"
                "[a link](https://example.com)\n")
        self.assertEqual(shown(Answer(text)), shown(Markdown(text)))


if __name__ == "__main__":
    unittest.main()
