"""Actual private Jupyter HTTP and kernel checks; synthetic state only."""
from pathlib import Path
import http.client
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

SCRIPT = Path(__file__).resolve().parents[1]/'container/jupyter-managed.py'


class JupyterTests(unittest.TestCase):
    def test_notebook_kernel_auth_xsrf_and_prefix(self):
        if not hasattr(os, 'getuid'):
            self.skipTest('Managed Jupyter requires the Linux image user boundary')
        if os.getuid() == 0:
            self.skipTest('Run the integration test as the non-root image user')
        with tempfile.TemporaryDirectory(prefix='jupyter-acceptance-') as folder:
            root = Path(folder)/'workspace';root.mkdir()
            state = Path(folder)/'state'
            code = "import importlib.util; s=importlib.util.spec_from_file_location('managed',SCRIPT);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.serve(ROOT,STATE,'dsh.test')".replace('SCRIPT',repr(str(SCRIPT))).replace('ROOT',repr(str(root))).replace('STATE',repr(str(state)))
            with (Path(folder)/'server.log').open('w') as log:
                process = subprocess.Popen([sys.executable,'-c',code],stdout=log,stderr=log)
                try:
                    cookie = ''
                    def request(method, path, body=None, authenticated=True, xsrf=True, origin='https://dsh.test'):
                        nonlocal cookie
                        headers={'Content-Type':'application/json','Origin':origin}
                        if authenticated:headers.update({'X-DSH-User':'alice','X-Forwarded-Host':'dsh.test'})
                        if cookie:headers['Cookie']=cookie
                        if cookie and xsrf:headers['X-XSRFToken']=cookie.split('=',1)[1]
                        connection=http.client.HTTPConnection('127.0.0.1',8888,timeout=12)
                        connection.request(method,path,json.dumps(body)if body is not None else None,headers=headers)
                        response=connection.getresponse();data=response.read()
                        for k,v in response.getheaders():
                            if k.lower()=='set-cookie'and v.startswith('_xsrf='):cookie=v.split(';',1)[0]
                        status=response.status;connection.close();return status,data
                    for _ in range(160):
                        try:
                            status,body=request('GET','/lab')
                            if status==200:break
                        except OSError:pass
                        if process.poll()is not None:break
                        time.sleep(.25)
                    self.assertIsNone(process.poll(),'Jupyter startup failed')
                    self.assertEqual(status,200)
                    self.assertIn(b'/proxy/8888/',body)
                    self.assertTrue(cookie,'XSRF cookie missing')
                    self.assertIn(request('GET','/api/contents',authenticated=False)[0],(401,403))
                    self.assertEqual(request('POST','/api/kernels',{},xsrf=False)[0],403)
                    self.assertEqual(request('POST','/api/kernels',{},origin='https://evil.invalid')[0],403)
                    notebook={'type':'notebook','format':'json','content':{'nbformat':4,'nbformat_minor':5,'metadata':{},'cells':[{'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':'print(6 * 7)'}]}}
                    status,_=request('PUT','/api/contents/synthetic.ipynb',notebook);self.assertEqual(status,201)
                    status,body=request('GET','/api/contents/synthetic.ipynb');self.assertEqual(status,200);self.assertEqual(json.loads(body)['content']['cells'][0]['source'],'print(6 * 7)')
                    status,body=request('POST','/api/kernels',{'name':'python3'});self.assertEqual(status,201);kernel=json.loads(body)['id']
                    from websocket import create_connection
                    ws=create_connection('ws://127.0.0.1:8888/api/kernels/'+kernel+'/channels',header=['X-DSH-User: alice','Cookie: '+cookie],origin='https://dsh.test',timeout=15)
                    identity=uuid.uuid4().hex
                    ws.send(json.dumps({'header':{'msg_id':identity,'username':'alice','session':uuid.uuid4().hex,'msg_type':'execute_request','version':'5.3'},'parent_header':{},'metadata':{},'channel':'shell','content':{'code':'print(6 * 7)','silent':False,'store_history':False,'user_expressions':{},'allow_stdin':False,'stop_on_error':True}}))
                    output=''
                    for _ in range(50):
                        message=json.loads(ws.recv())
                        if message.get('parent_header',{}).get('msg_id')!=identity:continue
                        if message['msg_type']=='stream':output+=message['content']['text']
                        if message['msg_type']=='execute_reply':break
                    ws.close();self.assertIn('42',output)
                    self.assertEqual(request('DELETE','/api/kernels/'+kernel)[0],204)
                    self.assertTrue((root/'synthetic.ipynb').is_file())
                finally:
                    process.terminate()
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':unittest.main()
