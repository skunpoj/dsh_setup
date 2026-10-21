"""Issue model-only client keys through an operator-only local port forward."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import yaml
from bootstrap_secrets import create

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--port',type=int,default=14000);a=p.parse_args()
    c=yaml.safe_load(a.config.read_text());ns=c['namespace']
    raw=json.loads(subprocess.check_output(['kubectl','get','secret','platform-secrets','-n',ns,'-o','json']))
    key=base64.b64decode(raw['data']['LITELLM_MASTER_KEY']).decode();raw=None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for user in c['users']:
      identity=hashlib.sha256(user.encode()).hexdigest()[:16]
      for mode in ['secure','internet']:
        name='user-'+identity+'-'+mode+'-inference'
        existing=subprocess.check_output(['kubectl','get','secret',name,'-n',ns,'--ignore-not-found','-o','name'])
        if existing.strip():raise RuntimeError('Existing client Secret; refuse implicit rotation')
        request=urllib.request.Request('http://127.0.0.1:'+str(a.port)+'/key/generate',
          data=json.dumps({'models':['deepseek-v4.1-flash','deepseek-flash'],'key_alias':name}).encode(),
          headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with opener.open(request,timeout=60) as response:result=json.load(response)
        issued=result['key'];create(ns,name,{'key':issued});result=None;issued=None
    key=None;print('Per-user/environment model-only Secrets created; no values printed.')

if __name__=='__main__':main()
