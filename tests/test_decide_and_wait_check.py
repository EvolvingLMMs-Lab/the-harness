"""decide(): a program asks the model and gets its <answer>; a <wait> carries a check that
only reads, run when the wait ends."""
import unittest

import helpers  # noqa: F401
from test_units import Episode, program, texts


def told(episode) -> str:
    return "\n".join(texts(request[-1]) for request in episode.chat.requests)


class DecideAndWaitCheckTest(unittest.TestCase):
    def test_a_program_gets_the_models_answer_to_its_question(self):
        asked = program("until(None)\nprint('GOT', decide('Which stacks go?', show='dirt 23, dirt 64'))")
        with Episode([asked, "<wait>10<check>pass</check></wait>", "<answer>the dirt 23</answer>",
                      "<wait>5<check>pass</check></wait>", "<finish>done</finish>"]) as episode:
            summary = episode.end()
            cells = {row["number"]: row["result"] for row in episode.records("cell")}
            said = told(episode)
        self.assertEqual(summary["status"], "finished")
        self.assertIn("asks you, and waits for your answer: Which stacks go?", said)
        self.assertIn("dirt 23, dirt 64", said)
        self.assertIn("GOT the dirt 23", cells[1]["stdout"])

    def test_a_wait_without_a_check_is_refused(self):
        with Episode(["<wait>1</wait>", "<finish>done</finish>"]) as episode:
            episode.end()
            refused = episode.records("wait_refused")
            said = told(episode)
        self.assertEqual(len(refused), 1)
        self.assertEqual(episode.records("wait"), [])
        self.assertIn("a <wait> carries the check", said)

    def test_the_check_runs_when_the_wait_ends_and_acts_on_nothing(self):
        check = "print('LOOKED', get_state()['step'])\ntype_text(1)"
        with Episode([program("type_text(30, seconds=0.2)"), f"<wait>1<check>{check}</check></wait>",
                      "<finish>done</finish>"]) as episode:
            episode.end()
            said = told(episode)
        self.assertIn("Your check, run when the wait ended:", said)
        self.assertIn("LOOKED", said)
        self.assertIn("Nothing acts in a wait's check", said)


if __name__ == "__main__":
    unittest.main()
