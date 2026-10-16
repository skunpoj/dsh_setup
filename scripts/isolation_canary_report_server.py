"""Synthetic report/attachment server behind the actual authenticated gateway."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import os
import base64
import hashlib


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        route = self.path.split('?', 1)[0]
        if route == '/ws-identity' and self.headers.get('Upgrade', '').lower() == 'websocket':
            key = self.headers.get('Sec-WebSocket-Key', '')
            accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', accept)
            self.end_headers()
            payload = json.dumps({'user': self.headers.get('x-dsh-user'),
                                  'mode': self.headers.get('x-dsh-internet-access'),
                                  'count': len(self.headers.get_all('x-dsh-user', []))}).encode()
            assert len(payload) < 126
            self.wfile.write(bytes([0x81, len(payload)]) + payload)
            self.wfile.flush()
            self.close_connection = True
            return
        files = {'/report': Path('/workspace/private-report.txt'),
                 '/attachment': Path('/state/attachments/private-attachment.txt')}
        if route == '/identity':
            value = {'identity': os.environ['CANARY_IDENTITY'],
                     'environment': os.environ['CANARY_ENVIRONMENT'],
                     'gatewayUser': self.headers.get('x-dsh-user')}
            body = json.dumps(value).encode()
        elif route in files and files[route].is_file():
            body = files[route].read_bytes()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 8081), Handler).serve_forever()
