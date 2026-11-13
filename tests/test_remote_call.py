"""A worker method's own arguments reach it whatever they are called; a conversation's records
stream stops trying, and says so, when its session host is gone."""

import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError

from harness.host import client

from harness.core.remote import RemoteEnvironment
from harness.runtime.execution import control
from harness.runtime.execution.attached import RelayedEnvironment
from harness.runtime.execution.noenv import NoEnvironment


class RemoteCallTests(unittest.TestCase):
    def test_a_worker_method_may_have_an_argument_called_name(self):
        environment = RemoteEnvironment("http://127.0.0.1:1")
        with patch.object(RemoteEnvironment, "_request", return_value={"saved": True}) as request:
            environment.call("save", episode_id="e1", name="first", text="x")
            environment.managed_call("save", approval_key="key", name="first")
        self.assertEqual(request.call_args_list[0].args,
                         ("call", {"name": "save", "arguments": {"episode_id": "e1", "name": "first", "text": "x"}}))
        self.assertEqual(request.call_args_list[1].args,
                         ("call", {"name": "save", "arguments": {"name": "first"}}))

    def test_an_attached_environment_relays_an_argument_called_name(self):
        environment = RelayedEnvironment("project", timeout=7)
        with patch.object(control, "host_call", return_value={"saved": True}) as host_call:
            self.assertEqual(environment.call("save", name="first"), {"saved": True})
        self.assertEqual(host_call.call_args.args,
                         ({"environment": "project", "name": "save", "arguments": {"name": "first"}}, 7.0))

    def test_no_environment_refuses_the_method_not_its_argument(self):
        with self.assertRaisesRegex(RuntimeError, "save needs one"):
            NoEnvironment().call("save", name="first")


class RecordsStreamTests(unittest.TestCase):
    def refused(self):
        calls = []

        def open_url(*args, **kwargs):
            calls.append(1)
            if len(calls) > 50:
                raise AssertionError("the stream kept reconnecting")
            raise URLError(ConnectionRefusedError(61, "Connection refused"))

        return calls, open_url

    def test_a_host_that_stays_gone_ends_the_stream_after_a_few_tries(self):
        calls, open_url = self.refused()
        conversation = client.RemoteConversation("http://127.0.0.1:1", "key", "run")
        with patch.object(client, "open_url", open_url), patch.object(client, "GONE_SECONDS", 0.5):
            with self.assertRaisesRegex(client.HostGone, "does not answer"):
                list(conversation.records())
        self.assertLessEqual(len(calls), 6)

    def test_stopping_ends_the_wait_between_tries(self):
        calls, open_url = self.refused()
        conversation = client.RemoteConversation("http://127.0.0.1:1", "key", "run")
        stop = threading.Event()
        threading.Timer(0.2, stop.set).start()
        with patch.object(client, "open_url", open_url):
            self.assertEqual(list(conversation.records(stop=stop)), [])
        self.assertLessEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
