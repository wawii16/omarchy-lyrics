import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer


class TruncatedLyricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', '100')
        self.end_headers()
        self.wfile.write(b'secret-token')

    def log_message(self, format, *args):
        pass


class OnceFetchFailure(unittest.TestCase):
    def test_incomplete_http_response_publishes_unavailable_without_leaking(self):
        server = HTTPServer(('127.0.0.1', 0), TruncatedLyricsHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            busctl = root / 'busctl'
            records = [
                {'data': {'mpris:trackid': {'data': '/track/123'}, 'xesam:title': {'data': 'Song'}}},
                {'data': 'Playing'},
                {'data': 0},
            ]
            busctl.write_text('#!/bin/sh\nprintf \'%s\\n\' ' + ' '.join("'" + json.dumps(record) + "'" for record in records) + '\n')
            busctl.chmod(0o755)
            state = root / 'state.json'
            env = os.environ.copy()
            env.update(PATH=str(root) + os.pathsep + env.get('PATH', ''), XDG_CONFIG_HOME=str(root))
            backend = Path(__file__).resolve().parents[1] / 'backend.py'
            result = subprocess.run([sys.executable, str(backend), '--once', '--state', str(state),
                                     '--engine', 'http://127.0.0.1:%d' % server.server_port],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(state.read_text())
            self.assertEqual((data['track_id'], data['track'], data['text'], data['unavailable']),
                             ('123', 'Song', '', True))
            self.assertNotIn('secret-token', result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
