"""Create/test a non-admin LiteLLM client key; persist only in a Kubernetes Secret.

No credential values are printed, written to local files or included in evidence.
Existing master keys and other clients are not rotated by this operation.
"""
import argparse
import base64
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '--request-timeout=30s', '-n', 'llm', *args],
                       input=data, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout


def provision(secret_name, allowed_models=None):
    # The admin credential is read only inside the existing LiteLLM pod. The
    # generated client token travels through captured stdin/stdout directly to
    # Kubernetes, never through a tool-visible print or local credential file.
    code = r'''
import os,json,urllib.request,urllib.error
master=os.environ['LITELLM_MASTER_KEY'];base='http://127.0.0.1:4000'
def call(route,key,body=None):
 req=urllib.request.Request(base+route,data=json.dumps(body).encode() if body is not None else None,
 headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=30) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,{}
status,models=call('/v1/models',master)
if status!=200:raise RuntimeError('Could not enumerate configured models')
names=[r['id'] for r in models['data']]
requested=REQUESTED_MODELS
if requested is not None:
 if not set(requested).issubset(names):raise RuntimeError('Requested managed models are not available')
 names=requested
status,key=call('/key/generate',master,{'key_alias':ALIAS,'models':names,
 'allowed_routes':['/chat/completions','/v1/chat/completions','/responses','/v1/responses',
 '/models','/v1/models','/embeddings','/v1/embeddings','/audio/transcriptions',
 '/v1/audio/transcriptions','/audio/translations','/v1/audio/translations','/token/count','/utils/token_counter'],
 'metadata':{'purpose':'DSH restricted inference; no administration'}})
if status!=200 or not key.get('key'):raise RuntimeError('Client key provisioning failed')
token=key['key'];denials={}
for route,body in [('/key/list',None),('/key/generate',{}),('/model/new',{})]:
 status,_=call(route,token,body);denials[route]=status
if any(v not in (401,403) for v in denials.values()):
 call('/key/delete',master,{'keys':[token]});raise RuntimeError('Client key did not deny administration')
status,result=call('/v1/chat/completions',token,{'model':'deepseek-v4.1-flash',
 'messages':[{'role':'user','content':'Reply exactly CLIENT_KEY_OK'}],'temperature':0,'max_tokens':32,
 'chat_template_kwargs':{'enable_thinking':False}})
if status!=200 or result['choices'][0]['message']['content'].strip()!='CLIENT_KEY_OK':
 call('/key/delete',master,{'keys':[token]});raise RuntimeError('Restricted-key inference failed')
print(json.dumps({'token':token,'denials':denials,'inferenceExact':True,'allowedModelCount':len(names)}))
'''.replace('ALIAS', repr(secret_name)).replace('REQUESTED_MODELS', repr(allowed_models))
    output = json.loads(kube('exec', '-i', 'deploy/litellm', '--', 'python', '-', data=code))
    token = output.pop('token')
    kube('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'Secret',
         'metadata': {'name': secret_name, 'namespace': 'llm'}, 'type': 'Opaque',
         'data': {'litellm-api-key': base64.b64encode(token.encode()).decode()}}))
    del token
    return {'timeUTC': datetime.now(timezone.utc).isoformat(), 'secret': secret_name,
            'credentialValuesExported': False, **output}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--secret', required=True)
    ap.add_argument('--evidence', type=Path, required=True)
    args = ap.parse_args()
    import re
    if not re.fullmatch(r'dsh-inference-[a-z0-9-]+', args.secret):
        raise ValueError('A dedicated DSH inference Secret name is required')
    result = provision(args.secret)
    args.evidence.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
