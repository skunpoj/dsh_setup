"""Exercise installed LiteLLM Router against an isolated local 429 server."""
import argparse
import json
from pathlib import Path
from promote_1m_runtimes import kube

SOURCE = r'''
import asyncio,json,threading,time
from http.server import BaseHTTPRequestHandler,HTTPServer
from litellm import Router
class Handler(BaseHTTPRequestHandler):
 count=0
 def log_message(self,*args):pass
 def do_POST(self):
  Handler.count+=1;self.rfile.read(int(self.headers['Content-Length']))
  b=json.dumps({'error':{'message':'Long-context capacity busy; retry later.','type':'rate_limit_error','code':'429'}}).encode()
  self.send_response(429);self.send_header('Content-Type','application/json');self.send_header('Retry-After','0');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
server=HTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
async def run(name,policy):
 Handler.count=0
 kw={'model_list':[{'model_name':name,'litellm_params':{'model':'openai/fixture','api_base':'http://127.0.0.1:'+str(server.server_port)+'/v1','api_key':'fixture-only'}}], 'retry_after':0}
 if policy:kw['model_group_retry_policy']={n:{'RateLimitErrorRetries':0} for n in ['deepseek-flash','deepseek-v4.1-flash']}
 r=Router(**kw);t=time.monotonic()
 try:await r.acompletion(model=name,messages=[{'role':'user','content':'fixture'}],max_tokens=8)
 except Exception as e:result={'modelGroup':name,'policy':policy,'errorType':type(e).__name__,'calls':Handler.count,'seconds':time.monotonic()-t,'defaultRetries':r.num_retries}
 return result
rows=[asyncio.run(run(n,p)) for n,p in [('deepseek-v4.1-flash',False),('deepseek-v4.1-flash',True),('deepseek-flash',True),('unrelated-fixture',True)]]
assert [r['calls'] for r in rows]==[3,1,1,3]
print(json.dumps({'scope':'Isolated loopback fixture, no real key or GPU inference','passed':True,'results':rows}));server.shutdown()
'''

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists():raise ValueError('Refuse to overwrite evidence')
    result=json.loads(kube('exec','-i','deploy/litellm','-c','litellm','--','python','-',source=SOURCE))
    a.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
