"""Waiting for a condition by polling it."""

import time


def wait_until(predicate, timeout: float, interval: float = 0.1):
    """Call `predicate()` every `interval` seconds until it returns something true or
    `timeout` seconds have passed; what it returned last."""
    deadline = time.monotonic() + timeout
    while not (value := predicate()) and time.monotonic() < deadline:
        time.sleep(interval)
    return value
