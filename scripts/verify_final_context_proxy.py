"""Actual candidate API checks; keys stay inside the disposable DSH runtime."""
import json
from pathlib import Path
import subprocess

SOURCE = r'''
import os,json,urllib.request,urllib.error,time
url='http://SERVICE_IP:4000/v1/chat/completions'
headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']}
def call(body):
 return json.load(urllib.request.urlopen(urllib.request.Request(url,data=json.dumps(body).encode(),headers=headers),timeout=500))
body={'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':'Reply exactly GUARD_OK.'}],'temperature':0,'max_tokens':32}
t=time.monotonic();v=call(body);result={'exact':v['choices'][0]['message']['content'].strip()=='GUARD_OK','seconds':time.monotonic()-t}
try:call({**body,'api_base':'http://127.0.0.1:9/v1'})
except urllib.error.HTTPError as e:
 text=e.read().decode();result['overrideRejected']=e.code in (400,401) and any(x in text for x in ['Managed context route','api_base is not allowed'])
assert result['exact'] and result.get('overrideRejected')
t=time.monotonic()
v=call({**body,'messages':[{'role':'user','content':'Synthetic nonstream acceptance. '+' a b c d'*35000+'\nReply exactly GUARD_OK.'}]})
result['nonStreaming']={'exact':v['choices'][0]['message']['content'].strip()=='GUARD_OK','usage':v.get('usage'),'seconds':time.monotonic()-t}
assert result['nonStreaming']['exact'] and v['usage']['prompt_tokens']>131072
print(json.dumps(result))
'''

if __name__ == '__main__':
    ip=json.loads(subprocess.check_output(['kubectl','-n','llm','get','svc','litellm-1m-canary','-o','json']))['spec']['clusterIP']
    p=subprocess.run(['kubectl','-n','llm','exec','-i','dsh-1m-image-canary','--','python3','-'],input=SOURCE.replace('SERVICE_IP',ip),text=True,capture_output=True,timeout=520)
    if p.returncode:
        raise RuntimeError(p.stderr[-1800:])
    result=json.loads(p.stdout)
    Path('docs/context-evidence/final-wire-api-acceptance-20261016.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
