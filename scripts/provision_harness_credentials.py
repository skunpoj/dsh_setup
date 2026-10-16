"""Issue a model-scoped harness credential directly into a runtime Secret."""
import base64
import json
import subprocess

def kube(*args, source=None):
    p = subprocess.run(['kubectl', '-n', 'llm', *args], input=source,
                       text=True, encoding='utf8', capture_output=True, timeout=100)
    if p.returncode: raise RuntimeError(p.stderr[-300:])
    return p.stdout

def provision(name, gateway='deploy/litellm'):
    existing = json.loads(kube('get', 'secret', '-o', 'json'))['items']
    if any(x['metadata']['name'] == name for x in existing):
        return {'secret': name, 'created': False}
    code = r'''
import os,json,urllib.request,urllib.error
base='http://127.0.0.1:4000';master=os.environ['LITELLM_MASTER_KEY']
def call(path,key,body):
 req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=45) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:
  try:return e.code,json.load(e)
  except Exception:return e.code,{}
status,data=call('/key/generate',master,{'key_alias':ALIAS,
 'models':['deepseek-v4.1-flash'],
 'allowed_routes':['/v1/messages','/messages','/v1/chat/completions','/chat/completions','/v1/models','/models','/token/count','/utils/token_counter'],
 'metadata':{'purpose':'Managed Claude Code and TrueForge; internal DeepSeek only'}})
if status!=200 or not data.get('key'):raise RuntimeError('Credential issuance failed')
key=data['key']
try:
 status,result=call('/v1/messages',key,{'model':'deepseek-v4.1-flash','max_tokens':128,'thinking':{'type':'disabled'},'messages':[{'role':'user','content':'Reply exactly HARNESS_KEY_OK'}]})
 text=''.join(x.get('text','') for x in result.get('content',[]))
 if status!=200 or text.strip()!='HARNESS_KEY_OK':raise RuntimeError('Messages acceptance failed; status='+str(status)+' detail='+str(result).replace(key,'[redacted]').replace(master,'[redacted]')[:300])
 for path,body in [('/key/generate',{}),('/model/new',{}),('/v1/messages',{'model':'claude-opus-4-6','max_tokens':8,'messages':[{'role':'user','content':'Hi'}]})]:
  status,_=call(path,key,body)
  if status not in [401,403]:raise RuntimeError('Credential restriction failed')
 print(json.dumps({'token':key,'messagesExact':True,'administrationDenied':True,'otherModelDenied':True}))
except Exception:
 call('/key/delete',master,{'keys':[key]});raise
'''.replace('ALIAS', repr(name))
    result = json.loads(kube('exec', '-i', gateway, '-c', 'litellm', '--', 'python', '-', source=code))
    token = result.pop('token')
    kube('apply', '-f', '-', source=json.dumps({'apiVersion':'v1','kind':'Secret',
        'metadata':{'name':name},'type':'Opaque','data':{'api-key':base64.b64encode(token.encode()).decode()}}))
    return {'secret':name,'created':True,**result}

if __name__ == '__main__':
    import argparse,re
    ap=argparse.ArgumentParser();ap.add_argument('--secret',required=True);ap.add_argument('--gateway',default='deploy/litellm');a=ap.parse_args()
    if not re.fullmatch(r'dsh-harness-[a-z0-9-]+',a.secret):raise ValueError('Dedicated Secret name required')
    print(json.dumps(provision(a.secret,a.gateway)))
