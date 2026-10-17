"""Non-forwarding-by-default DNS relay for explicitly named internal services.

Rebuilds upstream questions: client EDNS data, IDs and extra sections are never
forwarded. Unknown names are answered locally; query names are not logged.
"""
import json
import re
import os
import secrets
import socket
import socketserver
import struct
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ALLOWED = {x.lower().rstrip('.') for x in json.loads(Path(os.environ.get('DNS_ALLOWLIST', '/config/allowed.json')).read_text(encoding='utf-8'))}
# Only fully qualified private runtime Services; never short names or public suffixes.
# CoreDNS must remain authoritative for cluster.local (no public fallthrough).
PRIVATE_RUNTIME = re.compile(r'dsh-u-[a-f0-9]{16}-(?:secure|internet)\.llm\.svc\.cluster\.local\Z')
UPSTREAM = os.environ['DNS_UPSTREAM']
UPSTREAM_PORT = int(os.environ.get('DNS_UPSTREAM_PORT', '53'))
LIMIT = threading.BoundedSemaphore(16)
COUNTS = {'allowed': 0, 'denied': 0, 'errors': 0}


def question(packet):
    if len(packet) < 12 or len(packet) > 512:
        raise ValueError('Invalid query length')
    _, flags, count, _, _, _ = struct.unpack('!6H', packet[:12])
    if flags & 0xF800 or count != 1:
        raise ValueError('Unsupported query')
    position = 12
    labels = []
    while True:
        length = packet[position];position += 1
        if not length:break
        if length > 63 or position + length > len(packet):raise ValueError('Invalid name')
        labels.append(packet[position:position+length].decode('ascii').lower());position += length
    if position + 4 > len(packet):raise ValueError('Missing query type')
    kind, klass = struct.unpack('!HH', packet[position:position+4])
    if kind not in (1, 28, 33) or klass != 1:raise ValueError('Unsupported query type')
    wire = b''.join(bytes([len(x)])+x.encode() for x in labels)+b'\0'+struct.pack('!HH',kind,1)
    return '.'.join(labels), wire


def exact(stream, length):
    result=b''
    while len(result)<length:
        part=stream.recv(length-len(result))
        if not part:raise OSError('Incomplete DNS frame')
        result+=part
    return result


def answer(packet):
    identifier=packet[:2] if len(packet)>=2 else b'\0\0'
    try:
        name, wire=question(packet)
        if name not in ALLOWED and not PRIVATE_RUNTIME.fullmatch(name):
            COUNTS['denied']+=1
            return identifier+struct.pack('!5H',0x8183,1,0,0,0)+wire
        if not LIMIT.acquire(blocking=False):raise OSError('DNS request capacity')
        try:
            nonce=secrets.token_bytes(2)
            query=nonce+struct.pack('!5H',0x0100,1,0,0,0)+wire
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as upstream:
                upstream.settimeout(2);upstream.connect((UPSTREAM,UPSTREAM_PORT));upstream.send(query);response=upstream.recv(4096)
            if len(response)<12 or response[:2]!=nonce:raise OSError('Invalid upstream response')
            if struct.unpack('!H',response[2:4])[0]&0x0200:
                with socket.create_connection((UPSTREAM,UPSTREAM_PORT),timeout=2) as upstream:
                    upstream.sendall(struct.pack('!H',len(query))+query)
                    length=struct.unpack('!H',exact(upstream,2))[0]
                    if length>4096:raise OSError('Oversized upstream response')
                    response=exact(upstream,length)
                if response[:2]!=nonce:raise OSError('Invalid upstream response')
            COUNTS['allowed']+=1
            return identifier+response[2:]
        finally:LIMIT.release()
    except Exception:
        COUNTS['errors']+=1
        return identifier+struct.pack('!5H',0x8182,0,0,0,0)


class UDP(socketserver.BaseRequestHandler):
    def handle(self):
        packet, transport=self.request
        transport.sendto(answer(packet),self.client_address)


class TCP(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        try:
            length=struct.unpack('!H',exact(self.request,2))[0]
            if length>512:return
            response=answer(exact(self.request,length));self.request.sendall(struct.pack('!H',len(response))+response)
        except OSError:pass


class Health(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        if self.path not in ('/health','/metrics'):self.send_error(404);return
        body=json.dumps({'ready':True,'allowedNameCount':len(ALLOWED),'counts':COUNTS}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)


class BoundedThreads(socketserver.ThreadingMixIn):
    daemon_threads=True
    slots=threading.BoundedSemaphore(16)
    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
        try:super().process_request(request,client_address)
        except Exception:self.slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()


class UDPServer(BoundedThreads,socketserver.UDPServer):pass
class TCPServer(BoundedThreads,socketserver.TCPServer):pass


if __name__=='__main__':
    for cls,handler in [(UDPServer,UDP),(TCPServer,TCP)]:
        server=cls(('0.0.0.0',5353),handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    HTTPServer(('0.0.0.0',8080),Health).serve_forever()
