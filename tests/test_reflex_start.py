"""A node of the tree is started or not (runtime/reactive/tree.py). One that is not started is
in the tree and answers nothing, and neither do the nodes under it. The model starts and
stops nodes; a node it sets is started; a node a library entry puts into the tree is not."""
import unittest

import helpers  # noqa: F401
from harness.runtime.events import Event, ExecutionTrace
from harness.runtime.reactive.rules import period
from harness.runtime.reactive.tree import NOT_STARTED, Reflexes, stage, told


def tree():
    layer = Reflexes(0.05)
    layer.set("wide", lambda view: True, lambda: None)
    layer.set("narrow", lambda view: True, lambda: None, under="wide")
    layer.set("other", lambda view: True, lambda: None)
    layer.set("ends", lambda view: True, "stop")
    layer.set("hears", "KNOCK", lambda: None)
    return layer


def holds(layer, name):
    with period(1.0):
        return layer._run(layer.nodes[name], {})


class StartAndStop(unittest.TestCase):
    def test_a_node_that_is_set_is_started_and_one_that_is_stopped_answers_nothing(self):
        layer = tree()
        self.assertTrue(all(not node.stopped for node in layer.nodes.values()))
        self.assertTrue(holds(layer, "wide"))
        self.assertEqual(layer.stop("wide"), ["wide", "narrow"])     # with the nodes under it
        self.assertFalse(holds(layer, "wide"))
        self.assertFalse(holds(layer, "narrow"))
        self.assertTrue(holds(layer, "other"))                       # the others go on
        self.assertEqual(sorted(layer.nodes), ["ends", "hears", "narrow", "other", "wide"])   # it stays in the tree
        self.assertEqual(layer.stop("wide"), [])                     # stopped already
        self.assertEqual(layer.start("wide"), ["wide", "narrow"])
        self.assertTrue(holds(layer, "narrow"))

    def test_every_way_the_tree_acts_leaves_out_what_is_not_started(self):
        layer = tree()
        self.assertTrue(layer.stops())
        with period(1.0):
            self.assertEqual(layer.evaluate({}).name, "ends")
        self.assertTrue(layer.listens({"KNOCK"}))
        self.assertTrue(layer.reads_changes())
        layer.set("timed", lambda view: True, lambda: None, every=1.0)
        self.assertIsNotNone(layer.next_due(0.0))
        started = []
        knock = ExecutionTrace("test", {}, 0, 0, Event("KNOCK", "test", {}, 0))
        self.assertEqual(layer.stop(), ["wide", "narrow", "other", "ends", "hears", "timed"])
        with period(1.0):
            self.assertIsNone(layer.evaluate({}))
        self.assertFalse(layer.listens({"KNOCK"}))
        self.assertFalse(layer.answer(knock, lambda node, program: started.append(node.name)))
        self.assertFalse(layer.reads_changes())
        self.assertIsNone(layer.next_due(0.0))
        self.assertEqual(layer.start(), ["wide", "narrow", "other", "ends", "hears", "timed"])
        self.assertTrue(layer.answer(knock, lambda node, program: started.append(node.name) or object()))
        self.assertEqual(started, ["hears"])

    def test_a_node_under_one_that_is_not_started_is_started_with_it_not_without_it(self):
        layer = tree()
        layer.stop("wide")
        with self.assertRaisesRegex(ValueError, "'narrow' is under 'wide', which is not started"):
            layer.start("narrow")
        self.assertTrue(layer.nodes["narrow"].stopped)
        with self.assertRaisesRegex(ValueError, "no reflex 'nowhere'"):
            layer.start("nowhere")
        with self.assertRaisesRegex(ValueError, "no reflex 'nowhere'"):
            layer.stop("nowhere")
        # A node set under one that is not started is started itself, and acts when that one is.
        layer.set("new", lambda view: True, lambda: None, under="wide")
        self.assertFalse(layer.nodes["new"].stopped)
        with period(1.0):
            self.assertFalse(layer._above_hold(layer.nodes["new"], {}))
        layer.start("wide")
        with period(1.0):
            self.assertTrue(layer._above_hold(layer.nodes["new"], {}))

    def test_the_model_is_told_which_nodes_are_not_started(self):
        layer = tree()
        layer.stop("wide")
        lines = layer.digest()
        self.assertEqual((lines["wide"], lines["wide/narrow"]), (NOT_STARTED, NOT_STARTED))
        self.assertIn("2 not started (start_reflex() starts them)", told(lines, {}))
        self.assertEqual([row.get("started") for row in layer.listing()], [False, None, None, None])
        # Told again while they wait, also when nothing else changed.
        self.assertIn("2 not started", told(lines, lines))
        layer.start()
        self.assertNotIn("not started", told(layer.digest(), {}))


class FromALibrary(unittest.TestCase):
    def test_a_node_a_library_puts_into_the_tree_is_not_started_until_the_model_starts_it(self):
        layer = Reflexes(0.05)
        with stage(layer, {"reactive/kept.py": "r1"}) as staged:
            layer.set("kept", lambda view: True, lambda: None)
            layer.set("below", lambda view: True, lambda: None, under="kept")
        layer.publish(staged)
        self.assertEqual([(node.name, node.stopped) for node in layer._ordered()], [("kept", True), ("below", True)])
        self.assertFalse(holds(layer, "kept"))
        self.assertEqual(layer.start(), ["kept", "below"])
        self.assertTrue(holds(layer, "below"))

    def test_a_library_node_that_takes_a_nodes_place_stands_as_that_one_stood(self):
        layer = Reflexes(0.05)
        layer.set("running", lambda view: True, lambda: None)
        layer.set("waiting", lambda view: True, lambda: None)
        layer.stop("waiting")
        with stage(layer, {"reactive/kept.py": "r2"}) as staged:
            layer.set("running", lambda view: False, lambda: None)
            layer.set("waiting", lambda view: False, lambda: None)
            layer.set("new", lambda view: True, lambda: None)
        layer.publish(staged)
        self.assertEqual({name: node.stopped for name, node in layer.nodes.items()},
                         {"running": False, "waiting": True, "new": True})

    def test_a_library_entry_neither_starts_nor_stops_a_node(self):
        layer = tree()
        with stage(layer, {}):
            with self.assertRaisesRegex(ValueError, "a library entry cannot start a reflex"):
                layer.start()
            with self.assertRaisesRegex(ValueError, "a library entry cannot stop a reflex"):
                layer.stop()


if __name__ == "__main__":
    unittest.main()
