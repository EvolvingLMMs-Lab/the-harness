"""The core speaks the Agent Space Protocol (harness.space): the participant against the SDK's
test space."""

import sys
import unittest

from agent_space import End

from harness.space.environment import ActionFailed, SpaceEnvironment


class AnySpace(unittest.TestCase):
    def test_the_participant_enters_the_sdks_test_space(self):
        env = SpaceEnvironment.connect(f'"{sys.executable}" -m agent_space.testing test-space --listen stdio', timeout=30)
        try:
            self.assertIn("test.toggle", env.verbs())
            self.assertEqual(env.act("test.toggle", object="lamp:1"), {"on": True})
            with self.assertRaises(ActionFailed) as refused:
                env.act("test.add", {"n": "two"}, object="counter:1")
            self.assertIs(refused.exception.outcome.end, End.REFUSED)
            self.assertEqual(refused.exception.outcome.reason.code, "malformed")
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
