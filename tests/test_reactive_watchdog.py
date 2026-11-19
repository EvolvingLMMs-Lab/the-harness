"""The watchdog that ends reactive calls at their deadline off the main thread
(runtime/reactive/rules.py): an overrun landing anywhere in the caller's thread must not
leave anything held, so later calls are never blocked."""

import random
import threading
import time
import unittest

from harness.runtime.reactive import rules


def _call(budget, frac):
    # a reactive call that ends right around its deadline: the overrun lands in it, in the
    # watchdog's bookkeeping around it, or not at all
    try:
        with rules._deadline(budget):
            started = time.perf_counter()
            while time.perf_counter() - started < budget * frac:
                pass
    except rules._Overrun:
        pass


class WatchdogTest(unittest.TestCase):
    def test_calls_ending_at_their_deadline_never_block_later_calls(self):
        done = [0] * 4

        def loop(index):
            for _ in range(1500):
                _call(0.001, random.uniform(0.9, 1.1))
                done[index] += 1

        threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(4)]
        for thread in threads:
            thread.start()
        deadline = time.time() + 60
        for thread in threads:
            thread.join(max(0.1, deadline - time.time()))
        self.assertEqual([thread.is_alive() for thread in threads], [False] * 4, f"calls done: {done}")
        self.assertEqual(done, [1500] * 4)
        time.sleep(0.05)
        self.assertEqual(rules._watchdog._calls, {})

    def test_an_overrun_still_ends_a_call_past_its_deadline(self):
        def call():
            with rules._deadline(0.02):
                while True:
                    pass

        result = []

        def run():
            try:
                call()
                result.append("returned")
            except rules._Overrun:
                result.append("overrun")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(5)
        self.assertEqual(result, ["overrun"])


if __name__ == "__main__":
    unittest.main()
