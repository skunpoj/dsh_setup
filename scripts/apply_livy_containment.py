"""Apply a reviewed fail-closed Livy patch and test all No Internet workers.

Temporarily disables new Livy connections; does not revoke AD rights, alter
storage, restart workloads or stop existing remote Spark applications.
Requires the operator's explicit routing decision before execution.
"""
import argparse
import concurrent.futures
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from run_isolation_canary import legacy_fingerprint


def kube(*args,data=None):
    p=subprocess.run(['kubectl','--request-timeout=30s','-n','llm',*args],input=data,
                     text=True,capture_output=True,check=True)
    return p.stdout


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prepared',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    patch=json.loads((args.prepared/'containment-patch.json').read_text())
    rollback=json.loads((args.prepared/'rollback-spec.json').read_text())
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'legacyBefore':legacy_fingerprint(),
            'workloadsRestarted':False,'adPermissionsChanged':False,'existingRemoteApplicationsStopped':False}
    changed=False
    try:
        kube('patch','networkpolicy','dsh-offline-egress','--type=json','-p',json.dumps(patch));changed=True
        actual=json.loads(kube('get','networkpolicy','dsh-offline-egress','-o','json'))['spec']
        assert actual==patch[1]['value']
        items=json.loads(kube('get','deploy','-o','json'))['items']
        workers=[d['metadata']['name'] for d in items if d['spec'].get('replicas')==1 and
                 d['spec']['template']['metadata'].get('labels',{}).get('dsh.bot.or.th/egress-mode')=='offline']
        code=r'''import json,socket,urllib.request,os
def connects(host,port):
 try:
  with socket.create_connection((host,port),timeout=3):return True
 except OSError:return False
assert not connects('botdlk-gw3-p1.bot.or.th',28998),'Livy still reachable'
assert connects('bot-dc-p1.bot.or.th',88),'KDC no longer reachable'
req=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',
data=json.dumps({'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':'Reply exactly CONTAINMENT_OK'}],
'max_tokens':32,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}).encode(),
headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
with urllib.request.urlopen(req,timeout=30) as response:
 assert json.load(response)['choices'][0]['message']['content'].strip()=='CONTAINMENT_OK'
assert os.path.isdir('/workspace') and os.path.isdir('/state/sessions')
print(json.dumps({'newLivyConnectionDenied':True,'kdcReachable':True,'internalInferenceExact':True,'workspaceAndStatePresent':True}))
'''
        def probe(name):
            return {'runtime':name,**json.loads(kube('exec','-i','deploy/'+name,'--','python3','-',data=code))}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:record['workers']=list(pool.map(probe,workers))
        assert len(record['workers'])==9
        record['legacyAfter']=legacy_fingerprint();assert record['legacyAfter']==record['legacyBefore']
        record['status']='passed';record['livePolicyChanged']=True
    except Exception as e:
        record['status']='failed';record['error']=str(e)
        if changed:
            kube('patch','networkpolicy','dsh-offline-egress','--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':rollback}]))
            record['originalPolicyRestored']=True
        raise
    finally:
        (args.output/'livy-containment-live.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__=='__main__':main()
