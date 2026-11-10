"""Attribution at the HTTP receiver, plus provider/hostname boundaries."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from unittest.mock import patch

from harness.core.http import RequestCancellation
from harness.runtime.decision.model import ChatModel


class AttributionTests(unittest.TestCase):
    def test_received_headers_streaming_and_json(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(dict((k.lower(), v) for k, v in self.headers.items()))
                self.send_response(200)
                self.end_headers()
                if body.get('stream'):
                    reply = {'choices': [{'delta': {'content': 'OK'}, 'finish_reason': 'stop'}]}
                    self.wfile.write(('data: ' + json.dumps(reply) + '\n\ndata: [DONE]\n\n').encode())
                else:
                    self.wfile.write(json.dumps({'choices': [{'message': {'content': 'OK'}}]}).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, OPENROUTER_API_KEY='test-only'):
                for backend in ('openrouter', 'openai_chat'):
                    for stream in (False, True):
                        for cancellable in (False, True):
                            with self.subTest(backend=backend, stream=stream, cancellable=cancellable):
                                model = ChatModel({'backend': backend, 'model': 'fixture',
                                                   'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                                                   'stream': stream, 'retries': 0})
                                reply = model.complete('', [{'role': 'user', 'content': 'hello'}],
                                                       cancellation=RequestCancellation() if cancellable else None)
                                self.assertEqual(reply.text, 'OK')
                                self.assertEqual(received[-1]['user-agent'], 'the-harness')
                                if backend == 'openrouter':
                                    self.assertEqual(received[-1].get('http-referer'), 'https://harness.lmms-lab.com/')
                                    self.assertEqual(received[-1].get('x-openrouter-title'), 'the-harness')
                                else:
                                    self.assertNotIn('http-referer', received[-1])
                                    self.assertNotIn('x-openrouter-title', received[-1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_openai_compatible_hostname_boundary(self):
        for url, attributed in (
            ('https://openrouter.ai/api/v1', True),
            ('https://OPENROUTER.AI:443/api/v1', True),
            ('https://openrouter.ai.example.org/v1', False),
            ('https://example.org/openrouter.ai', False),
            ('https://openrouter.ai@example.org/v1', False),
        ):
            with self.subTest(url=url):
                captured = []

                def transport(url, headers, payload, timeout):
                    captured.append(headers)
                    return {'choices': [{'message': {'content': 'OK'}}]}

                model = ChatModel({'backend': 'openai_chat', 'model': 'fixture', 'base_url': url}, transport)
                model.complete('', [{'role': 'user', 'content': 'hello'}])
                self.assertEqual('http-referer' in captured[0], attributed)
                self.assertEqual('x-openrouter-title' in captured[0], attributed)


if __name__ == '__main__':
    unittest.main()
