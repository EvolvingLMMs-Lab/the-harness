"""A skill's own pages of instructions: declared in skill.toml, read with guide(name), and the
calls a page names refused until it was read."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness.runtime.execution import entries
from harness.runtime.execution import session as sessions
from harness.runtime.execution import skills
from harness.runtime.task import run as task_run


def skill_folder(root, guides: str, exports='["lift", "look_up"]') -> Path:
    folder = Path(root) / "crane"
    folder.mkdir()
    (folder / "page.md").write_text("How a crane lifts.\n", encoding="utf-8")
    (folder / "skill.toml").write_text(
        f'name = "crane"\nsummary = "a crane"\nmixin = "skills.crane:Crane"\nexports = {exports}\n'
        f'embodiments = ["*"]\n{guides}', encoding="utf-8")
    return folder / "skill.toml"


class Declared(unittest.TestCase):
    def test_a_skill_names_its_pages_and_the_calls_that_wait_for_one(self):
        with tempfile.TemporaryDirectory() as root:
            skill = skills._skill(skill_folder(root, '[guides.crane]\nfile = "page.md"\nbefore = ["lift"]\n'
                                                     '[guides.rigging]\nfile = "page.md"\n'))
        self.assertEqual(skill.guides, (("crane", "page.md", ("lift",)), ("rigging", "page.md", ())))

    def test_what_a_page_may_not_be(self):
        for guides, said in (
                ('[guides.tree]\nfile = "page.md"\n', "is a page of the core"),
                ('[guides.crane]\nfile = "missing.md"\n', "no file missing.md"),
                ('[guides.crane]\nfile = "page.md"\nbefore = ["drop"]\n', "does not export"),
                ('[guides.crane]\nfile = "page.md"\nsummary = "x"\n', "is {file, before}"),
                ('guides = ["page.md"]\n', "a table of pages by name")):
            with self.subTest(guides=guides), tempfile.TemporaryDirectory() as root:
                with self.assertRaises(ValueError) as refused:
                    skills._skill(skill_folder(root, guides))
                self.assertIn(said, str(refused.exception))


class Read(unittest.TestCase):
    def session(self, root):
        page = Path(root) / "page.md"
        page.write_text("How a crane lifts.\n", encoding="utf-8")
        session = sessions.EpisodeCore.__new__(sessions.EpisodeCore)
        session._guides, session._guides_read, session._method_read = dict(sessions.GUIDES), set(), False
        box = entries.Box()
        session._box = lambda: box
        with mock.patch.object(skills, "guides", return_value={"crane": (page, ("lift",))}):
            exports = session._with_guides(["crane"], {"lift": lambda load: f"lifted {load}", "look_up": lambda: "sky"})
        return session, exports, page

    def test_a_call_that_waits_for_a_page_is_refused_until_the_page_was_read(self):
        with tempfile.TemporaryDirectory() as root:
            session, exports, page = self.session(root)
            self.assertEqual(exports["look_up"](), "sky")   # names no page: never waits
            with self.assertRaises(ValueError) as refused:
                exports["lift"]("a beam")
            self.assertEqual(str(refused.exception),
                             'Nothing ran: read how lift is used first. The page guide("crane") is given to you '
                             "with your next message. Read it, then call lift in a later program.")
            # The refusal asked for the page: it is on its way, as after guide("crane").
            self.assertEqual([page["name"] for page in session._pages], ["crane"])
            self.assertEqual(session.guide("crane"),
                             'guide("crane"): the page is given to you with your next message (19 characters).')
            # Asked for is not read: the call still waits.
            with self.assertRaises(ValueError):
                exports["lift"]("a beam")
            # The unit's result carries the page to the model: from then on it is read.
            self.assertEqual(session._pages_given(session._pages),
                             [{"name": "crane", "file": str(page), "size": 19}])
            self.assertEqual(exports["lift"]("a beam"), "lifted a beam")

    def test_a_reflexs_program_does_not_wait_for_a_page(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as root:
            session, exports, _ = self.session(root)
            root_unit = SimpleNamespace(rule=None, parent=None)
            reflex = SimpleNamespace(rule="weak", parent=root_unit)
            inside = SimpleNamespace(rule=None, parent=reflex)
            program = SimpleNamespace(rule=None, parent=root_unit)
            for current, refused in ((program, True), (reflex, False), (inside, False)):
                session.__dict__["_entry_tree"] = SimpleNamespace(root=root_unit, current=lambda current=current: current)
                with self.subTest(rule=current.rule, under=getattr(current.parent, "rule", None)):
                    if refused:
                        with self.assertRaises(ValueError):
                            exports["lift"]("a beam")
                    else:
                        # (A conversation that goes on in another process starts with no page read; its
                        # reflexes act all the same.)
                        self.assertEqual(exports["lift"]("a beam"), "lifted a beam")

    def test_pages_beyond_what_one_message_carries_are_not_given_and_not_read(self):
        with tempfile.TemporaryDirectory() as root:
            session, exports, page = self.session(root)
            with mock.patch.object(sessions, "PAGES_CHARS", 20), mock.patch.object(sessions.spans, "note"):
                session.guide("crane")
                answer = session.guide("units")
            self.assertIn('guide("units") was not given', answer)
            self.assertIn("It is not read.", answer)
            self.assertEqual([item["name"] for item in session._pages], ["crane"])

    def test_the_pages_of_the_core_stay_and_an_unknown_page_is_named(self):
        with tempfile.TemporaryDirectory() as root:
            session, _, _ = self.session(root)
            with mock.patch.object(sessions.spans, "note"):
                self.assertIn('guide("units"): the page is given', session.guide("units"))
                session.guide("tree")
            self.assertFalse(session._method_read)   # asked for, not yet given
            session._pages_given(session._pages)
            self.assertTrue(session._method_read)
            with self.assertRaises(ValueError) as refused:
                session.guide("everything")
            self.assertIn("['crane', 'tree', 'units']", str(refused.exception))

    def test_two_skills_cannot_bring_the_same_page(self):
        with tempfile.TemporaryDirectory() as root:
            session, _, page = self.session(root)
            with mock.patch.object(skills, "guides", return_value={"crane": (page, ())}):
                with self.assertRaises(ValueError):
                    session._with_guides(["other"], {})

    def test_a_page_that_was_read_is_given_again_from_its_file(self):
        with tempfile.TemporaryDirectory() as root:
            page = Path(root) / "page.md"
            page.write_text("How a crane lifts.\n", encoding="utf-8")
            self.assertEqual(task_run._guide_page(str(page)), "How a crane lifts.\n")


class ListedForWhereTheAgentIs(unittest.TestCase):
    def test_a_list_made_before_the_agent_came_here_stops_a_program_that_acts(self):
        session = sessions.EpisodeCore.__new__(sessions.EpisodeCore)
        session._method_required, session._situations, session._covers, session._listed_in = True, None, {}, set()
        session.reactive = mock.Mock(nodes={})
        session.profile = {"situation": "place", "situations_hint": "The manual says what lives there."}
        session.state = {"place": "field"}
        # Nothing listed: no action, and the environment's own sentence comes with the refusal.
        refused = session._uncovered("dig")
        self.assertIn("you have not said what can happen to the agent", refused)
        self.assertTrue(refused.endswith("The manual says what lives there."))
        with mock.patch.object(sessions.spans, "note"):
            session.situations(("it rains", "nothing to do then"))
        self.assertIsNone(session._uncovered("dig"))
        # The agent is somewhere else: the list is from before, until it is given again here.
        session.state = {"place": "cave"}
        refused = session._uncovered("dig")
        self.assertIn("the state's place is now \"cave\", and situations() was listed before that", refused)
        self.assertIn("Think this through first", refused)
        self.assertTrue(refused.endswith("The manual says what lives there."))
        with mock.patch.object(sessions.spans, "note"):
            session.situations(("it rains", "nothing to do then"), ("it is dark", "nothing to do then"))
        self.assertIsNone(session._uncovered("dig"))
        # Back where the list was made for: it still counts.
        session.state = {"place": "field"}
        self.assertIsNone(session._uncovered("dig"))


class Interrupted(unittest.TestCase):
    def test_only_a_program_of_the_model_asks_to_be_told_not_a_reflexs_own_program(self):
        import time
        from types import SimpleNamespace

        from harness.runtime.reactive import tree

        class Unit:
            def __init__(self, name, rule=None):
                self.id = self.name = name
                self.rule, self.running, self.report, self.interrupted = rule, True, None, "tell"
                self.pauses, self.started = [{"by": "hot", "at": time.monotonic()}], time.time()
                self.interruptions_told = self.interruptions_untold = 0

        unit = Unit

        mine, eating = unit("program 3"), unit("hungry", rule="hungry")
        session = SimpleNamespace(_entries=SimpleNamespace(_completed=lambda entry: None, reports=lambda entry: {}))
        rows, asking, place = tree.interrupted_by(session, SimpleNamespace(name="hot"),
                                                  SimpleNamespace(took=[mine, eating]), {})
        self.assertEqual([row["name"] for row in rows], ["program 3", "hungry"])
        self.assertEqual(asking, [mine])
        self.assertEqual(([row.get("asked") for row in rows], place), ([True, None], "next"))
        # With only a reflex's program interrupted, nobody asks: the node's own tell decides.
        self.assertEqual(tree.interrupted_by(session, SimpleNamespace(name="hot"), SimpleNamespace(took=[eating]), {})[1:],
                         ([], None))


if __name__ == "__main__":
    unittest.main()
