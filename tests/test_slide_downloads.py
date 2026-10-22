import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


class SlideDownloads(unittest.TestCase):
    def test_bounded_attachment_and_denials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b'fixture-presentation-bytes'
            name = 'Reviewed.pptx'
            (root/name).write_bytes(data)
            (root/'manifest.json').write_text(json.dumps({'hosts':['dsh.example.com'],'files':{name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}}}))
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0))
                port = sock.getsockname()[1]
            env = dict(os.environ,DSH_SLIDES_ROOT=tmp,DSH_SLIDES_BIND='127.0.0.1',PORT=str(port))
            script = Path(__file__).resolve().parents[1]/'scripts/slide_downloads.py'
            process = subprocess.Popen([sys.executable,str(script)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for _ in range(80):
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1):
                            break
                    except OSError:
                        time.sleep(.05)
                def request(path,method='GET',host='dsh.example.com'):
                    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
                    connection.request(method,path,headers={'Host':host})
                    response=connection.getresponse()
                    result=(response.status,dict(response.getheaders()),response.read())
                    connection.close()
                    return result
                status,headers,body=request('/manual/downloads/'+name)
                self.assertEqual((status,body),(200,data))
                self.assertEqual(headers['Content-Type'],'application/vnd.openxmlformats-officedocument.presentationml.presentation')
                self.assertEqual(headers['Content-Disposition'],'attachment; filename="Reviewed.pptx"')
                self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
                self.assertEqual(request('/manual/downloads/'+name,'HEAD')[2],b'')
                for path in ['/','/manual/downloads/','/manual/downloads/../manifest.json','/manual/downloads/%2e%2e/Reviewed.pptx','/manual/downloads/'+name+'?file=other','/manual/downloads/Other.pptx']:
                    self.assertEqual(request(path)[0],404,path)
                self.assertEqual(request('/manual/downloads/'+name,host='attacker.example.com')[0],404)
                self.assertEqual(request('/manual/downloads/'+name,'POST')[0],405)
                (root/name).write_bytes(b'corrupt')
                self.assertEqual(request('/manual/downloads/'+name)[0],503)
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__=='__main__':
    unittest.main()
