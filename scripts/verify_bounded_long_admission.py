"""Real authenticated gateway admission with an explicitly simulated occupied lease.

No fake GPU benchmark: a separate process holds the same flock for at most 360s.
Ordinary DSH calls must bypass it; a long API call must return bounded HTTP 429.
"""
import argparse
import concurrent.futures
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from promote_1m_runtimes import kube
from stress_live_inference import snapshot


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pod',required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists():raise ValueError('Refuse to overwrite evidence')
    if not a.pod.startswith('dsh-current-1m-retest'):raise ValueError('Disposable pod required')
    flag='/tmp/admission-release-'+uuid.uuid4().hex
    holder_source="""import fcntl,os,time,json
from pathlib import Path
fd=os.open('/tmp/dsh-long-admission/active.lock',os.O_RDWR)
fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
print(json.dumps({'leaseHeld':True}),flush=True)
end=time.monotonic()+360
while time.monotonic()<end and not Path(FLAG).exists():time.sleep(.1)
fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
Path(FLAG).unlink(missing_ok=True)
print(json.dumps({'leaseReleased':True}),flush=True)
""".replace('FLAG',repr(flag))
    rec={'startUTC':datetime.now(timezone.utc).isoformat(),'scope':'Real LiteLLM HTTP response under a simulated occupied admission lease; not simultaneous GPU 1M requests','before':snapshot()}
    holder=None
    def remote(source,timeout=360):
        p=subprocess.run(['kubectl','-n','llm','exec','-i',a.pod,'--','python3','-'],input=source,text=True,encoding='utf8',capture_output=True,timeout=timeout)
        if p.returncode:raise RuntimeError('Admission probe failed: '+p.stderr[-350:])
        return json.loads(p.stdout)
    api_source=r'''
import json,os,time,urllib.request,urllib.error,uuid
body={'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':str(uuid.uuid4())+' a b c d'*REPEATS+'\nReply exactly LEASE_RELEASE_OK.'}],'max_tokens':16,'temperature':0}
r=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
t=time.monotonic()
try:
 with urllib.request.urlopen(r,timeout=330) as response:
  v=json.load(response);result={'httpStatus':response.status,'exact':v['choices'][0]['message']['content'].strip()=='LEASE_RELEASE_OK','usage':v.get('usage')}
except urllib.error.HTTPError as e:
 text=e.read().decode();result={'httpStatus':e.code,'capacityBusy':'Long-context capacity busy' in text,'retryAfter':e.headers.get('retry-after'),'overflow':'exceeds' in text.lower() or 'budget' in text.lower()}
result['seconds']=time.monotonic()-t;print(json.dumps(result))
'''
    try:
        holder=subprocess.Popen(['kubectl','-n','llm','exec','-i','deploy/litellm','-c','context-forwarder','--','python','-'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        holder.stdin.write(holder_source);holder.stdin.close()
        assert json.loads(holder.stdout.readline())['leaseHeld']
        probe=Path(__file__).with_name('probe_dsh_1m_agent.py').read_text()
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            long=pool.submit(remote,api_source.replace('REPEATS','35000'))
            time.sleep(5)
            code="import sys;sys.argv=['probe','--deadline','90']\n"+probe
            small=[pool.submit(remote,code,110) for _ in range(2)]
            rec['ordinaryDsh']=[f.result() for f in small]
            rec['ordinaryFinishedWhileLeaseHeld']=not long.done()
            assert all(v['expectedTextPresent'] and v['persistedPromptMatches'] for v in rec['ordinaryDsh'])
            rec['busyResponse']=long.result()
        assert rec['busyResponse']['httpStatus']==429 and rec['busyResponse']['capacityBusy']
        assert 295<=rec['busyResponse']['seconds']<330
        rec['status']='busy-response-passed'
    finally:
        if holder:
            kube('exec','deploy/litellm','-c','context-forwarder','--','python','-c',"from pathlib import Path;Path("+repr(flag)+").touch()")
            holder.wait(timeout=20)
            rec['leaseReleased']=any('leaseReleased' in line for line in holder.stdout)
        a.output.write_text(json.dumps(rec,indent=2))
    rec['afterRelease']=remote(api_source.replace('REPEATS','35000'),160)
    assert rec['leaseReleased'] and rec['afterRelease']['httpStatus']==200 and rec['afterRelease']['exact']
    rec['overflow']=remote(api_source.replace('REPEATS','262250'),90)
    assert rec['overflow']['httpStatus']==400
    rec['after']=snapshot();assert rec['after']['pods']==rec['before']['pods']
    rec['status']='passed';rec['finishUTC']=datetime.now(timezone.utc).isoformat()
    a.output.write_text(json.dumps(rec,indent=2))
    print(json.dumps({'status':'passed','busy':rec['busyResponse'],'afterRelease':rec['afterRelease'],'overflow':rec['overflow'],'shortDshSeconds':[v['elapsedSeconds'] for v in rec['ordinaryDsh']]}),flush=True)


if __name__=='__main__':main()
