"""Mercator's actual HTTP host composed with the shared copilot transport."""
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import mercator
from support import running_server


class CopilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        for field, value in [('DATA', self.data), ('DB', self.data / 'mercator.sqlite3')]:
            p = patch.object(mercator, field, value)
            p.start(); self.addCleanup(p.stop)
        records = self.records = []
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                body = b'{"contract_version":"1.0"}' if self.path.endswith('capabilities') else b'export const testPanel = true;'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json' if self.path.endswith('capabilities') else 'application/javascript')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                if self.command != 'HEAD': self.wfile.write(body)
            do_HEAD = do_GET
            def do_POST(self):
                records.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                failure = self.path.endswith('/failure')
                body = b'{"error":"fixture failure"}' if failure else b'data: {"delta":"fixture"}\n\ndata: [DONE]\n\n'
                self.send_response(409 if failure else 200)
                self.send_header('Content-Type', 'application/json' if failure else 'text/event-stream')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        p = patch.dict('os.environ', {'MERCATOR_FAUSTUS_URL': f'http://127.0.0.1:{self.upstream.server_port}'})
        p.start(); self.addCleanup(p.stop)

    def stop(self):
        self.upstream.shutdown(); self.upstream.server_close(); self.thread.join(5)
        mercator._copilots.pop(str(self.data.resolve()), None)
        mercator.close_databases()

    def request(self, port, method, path, body=None):
        conn = HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            headers = {'Content-Type': 'application/json'} if body is not None else {}
            conn.request(method, path, json.dumps(body) if body is not None else None, headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_html_launcher_and_both_entry_points_preserve_assets(self):
        with running_server() as port:
            for path in ['/', '/publicacion']:
                status, headers, body = self.request(port, 'GET', path)
                self.assertEqual(status, 200)
                self.assertEqual(body.count(b'src="/api/copilot/launcher.js"'), 1)
                self.assertEqual(int(headers['Content-Length']), len(body))
                self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
            status, _, body = self.request(port, 'GET', '/copilot-context.js')
            self.assertEqual(body, (mercator.ROOT / 'static' / 'copilot-context.js').read_bytes())
            self.assertEqual(status, 200)
            status, _, body = self.request(port, 'GET', '/api/health')
            self.assertEqual(json.loads(body)['service'], 'mercator-hoard')
            self.assertNotIn(b'/api/copilot/launcher.js', body)

    def test_info_identity_survives_relay_recreation_and_head_is_empty(self):
        with running_server() as port:
            _, _, body = self.request(port, 'GET', '/api/copilot/info')
            first = json.loads(body)
            mercator._copilots.pop(str(self.data.resolve()))
            _, _, body = self.request(port, 'GET', '/api/copilot/info')
            self.assertEqual(json.loads(body)['data_space_id'], first['data_space_id'])
            self.assertEqual(first['app_id'], 'mercator')
            status, headers, body = self.request(port, 'HEAD', '/api/copilot/panel.js')
            self.assertEqual((status, body), (200, b''))
            self.assertIn('application/javascript', headers['Content-Type'])

    def test_proxy_stream_rewrites_origin_and_retains_context_and_upstream_error(self):
        context = {'origin': {'app_id': 'forged', 'data_space_id': 'forged'},
            'view': {'editor': {'fields': {'title': 'User draft'}}}}
        with running_server() as port:
            status, headers, body = self.request(port, 'POST', '/api/copilot/proxy', {
                'path': '/api/chat_stream', 'method': 'POST', 'body': {'hoard_context': context}})
            self.assertEqual(status, 200)
            self.assertIn('text/event-stream', headers['Content-Type'])
            self.assertIn(b'data: [DONE]', body)
            received = self.records[-1]['hoard_context']
            self.assertEqual(received['view'], context['view'])
            self.assertEqual(received['origin']['app_id'], 'mercator')
            self.assertNotEqual(received['origin']['data_space_id'], 'forged')
            status, _, body = self.request(port, 'POST', '/api/copilot/proxy', {
                'path': '/api/chat/failure', 'method': 'POST', 'body': {}})
            self.assertEqual((status, json.loads(body)), (409, {'error': 'fixture failure'}))

    def test_manifest_declares_shared_routes(self):
        manifest = json.loads((mercator.ROOT / 'faustus-plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['x-family']['copilot']['contract_version'], '1.0')
        self.assertEqual(manifest['x-family']['copilot']['proxy'], '/api/copilot/proxy')
