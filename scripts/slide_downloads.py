"""Read-only HTTP delivery for explicitly published slide companions."""
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
ROOT = Path(os.environ.get('DSH_SLIDES_ROOT', '/slides'))
CONFIG = json.loads((ROOT / 'manifest.json').read_text())
HOSTS = frozenset(CONFIG['hosts'])
FILES = CONFIG['files']
assert HOSTS and 1 <= len(FILES) <= 8
for name, entry in FILES.items():
    assert name == Path(name).name and name.endswith('.pptx')
    assert all(c.isalnum() or c in '_.-' for c in name)
    assert 0 < entry['bytes'] <= 8 * 1024 * 1024
    assert len(entry['sha256']) == 64


class Handler(BaseHTTPRequestHandler):
    server_version = 'SlideDelivery/1'

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def reject(self, code):
        self.send_response(code)
        self.send_header('Content-Length', '0')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def do_POST(self):
        self.reject(405)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST
    do_OPTIONS = do_POST

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        host = self.headers.get('Host', '').lower().split(':')[0]
        target = urlsplit(self.path)
        prefix = '/manual/downloads/'
        name = target.path[len(prefix):] if target.path.startswith(prefix) else ''
        if host not in HOSTS or target.query or name not in FILES:
            return self.reject(404)
        try:
            data = (ROOT / name).read_bytes()
            entry = FILES[name]
            if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                return self.reject(503)
        except OSError:
            return self.reject(503)
        self.send_response(200)
        self.send_header('Content-Type', MIME)
        self.send_header('Content-Disposition', 'attachment; filename="' + name + '"')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('ETag', '"' + entry['sha256'] + '"')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        if self.command != 'HEAD':
            self.wfile.write(data)


if __name__ == '__main__':
    ThreadingHTTPServer((os.environ.get('DSH_SLIDES_BIND', '0.0.0.0'), int(os.environ.get('PORT', '8080'))), Handler).serve_forever()
