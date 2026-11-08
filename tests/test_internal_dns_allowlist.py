import importlib.util
import json
import os
from pathlib import Path
import socketserver
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch


class DNSContainment(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();allowed=Path(self.temp.name)/'allowed.json'
        allowed.write_text(json.dumps(['litellm.ai-workspace.svc.cluster.local','_kerberos._tcp.example.invalid']))
        self.forwarded=[]
        parent=self
        class Upstream(socketserver.BaseRequestHandler):
            def handle(self):
                packet, sock=self.request;parent.forwarded.append(packet)
                sock.sendto(packet[:2]+struct.pack('!5H',0x8180,1,0,0,0)+packet[12:],self.client_address)
        self.server=socketserver.UDPServer(('127.0.0.1',0),Upstream)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        with patch.dict(os.environ,{'DNS_ALLOWLIST':str(allowed),'DNS_UPSTREAM':'127.0.0.1','DNS_UPSTREAM_PORT':str(self.server.server_address[1])}):
            spec=importlib.util.spec_from_file_location('dns_relay',Path(__file__).resolve().parents[1]/'scripts/internal_dns_allowlist.py')
            self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.temp.cleanup()

    def packet(self,name,kind=1,additional=b''):
        wire=b''.join(bytes([len(x)])+x.encode() for x in name.split('.'))+b'\0'+struct.pack('!HH',kind,1)
        return b'RD'+struct.pack('!5H',0x0100,1,0,0,1 if additional else 0)+wire+additional

    def test_unknown_public_and_encoded_names_never_forward(self):
        for name in ['example.com','sensitive-data.example.com','directory.example.invalid','litellm.ai-workspace.svc.cluster.local.attacker.com']:
            result=self.module.answer(self.packet(name));self.assertEqual(struct.unpack('!H',result[2:4])[0]&15,3)
        self.assertEqual(self.forwarded,[])

    def test_new_private_runtime_fqdn_can_resolve_without_a_public_wildcard(self):
        name='user-0123456789abcdef-secure.ai-workspace.svc.cluster.local'
        self.module.answer(self.packet(name));self.assertEqual(len(self.forwarded),1)
        for bad in ['user-0123456789abcdef-secure',name+'.attacker.com','user-private-secret-secure.ai-workspace.svc.cluster.local','user-0123456789abcdef-secure.other.svc.cluster.local']:
            response=self.module.answer(self.packet(bad));self.assertEqual(struct.unpack('!H',response[2:4])[0]&15,3)
        self.assertEqual(len(self.forwarded),1)

    def test_allowed_query_is_rebuilt_without_client_payload_or_id(self):
        response=self.module.answer(self.packet('LiteLLM.ai-workspace.svc.cluster.local',additional=b'PRIVATE_EDNS_PAYLOAD'))
        self.assertEqual(response[:2],b'RD');self.assertEqual(len(self.forwarded),1)
        upstream=self.forwarded[0]
        self.assertNotIn(b'PRIVATE_EDNS_PAYLOAD',upstream)
        self.assertEqual(struct.unpack('!6H',upstream[:12])[2:],(1,0,0,0))
        self.assertIn(b'litellm',upstream)

    def test_only_supported_internal_query_types(self):
        self.module.answer(self.packet('_kerberos._tcp.example.invalid',33));self.assertEqual(len(self.forwarded),1)
        result=self.module.answer(self.packet('litellm.ai-workspace.svc.cluster.local',16))
        self.assertEqual(struct.unpack('!H',result[2:4])[0]&15,2);self.assertEqual(len(self.forwarded),1)
        self.module.answer(b'RD'+struct.pack('!5H',0x100,1,0,0,0)+b'\xc0\x0c\x00\x01\x00\x01')
        self.assertEqual(len(self.forwarded),1)


if __name__=='__main__':unittest.main()
