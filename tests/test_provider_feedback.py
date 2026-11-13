"""Provider failures retain their evidence and explain a useful next action."""
import io
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from harness.runtime.decision.model import ChatModel, _provider_errors


class ProviderFeedbackTests(unittest.TestCase):
    def test_keyless_endpoint_receives_no_fabricated_authorization(self):
        received = []

        def transport(url, headers, body, timeout):
            received.append(headers)
            return {"choices": [{"message": {"content": "ok"}}]}

        with patch.dict(os.environ, {}, clear=True):
            model = ChatModel({"backend": "openai_chat", "model": "local",
                               "base_url": "http://localhost:1234/v1"}, transport)
            self.assertEqual(model.complete("", [{"role": "user", "content": "hello"}]).text, "ok")
        self.assertNotIn("authorization", received[0])

    def test_http_error_keeps_original_detail_and_adds_recovery_hint(self):
        for status, hint in ((401, "key"), (403, "access"), (429, "quota"), (503, "retry")):
            with self.subTest(status=status):
                with self.assertRaises(RuntimeError) as raised:
                    with _provider_errors():
                        raise HTTPError("https://example.invalid", status, "failed", {}, io.BytesIO(b"ORIGINAL_DETAIL"))
                message = str(raised.exception)
                self.assertIn(f"Provider HTTP {status}", message)
                self.assertIn("ORIGINAL_DETAIL", message)
                self.assertIn(hint, message.lower())

    def test_connection_failure_names_endpoint_and_network(self):
        with self.assertRaises(RuntimeError) as raised:
            with _provider_errors():
                raise URLError("connection refused")
        self.assertIn("connection refused", str(raised.exception))
        self.assertIn("endpoint", str(raised.exception).lower())


if __name__ == "__main__":
    unittest.main()
