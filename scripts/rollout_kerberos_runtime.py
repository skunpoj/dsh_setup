"""Replace DSH images after a matching isolated canary, preserving mounted state.

Does not authenticate to AD, create a keytab, change datalake permissions or
restart inference. Restores exact previous specifications if acceptance fails.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from run_isolation_canary import legacy_fingerprint

ROOT=Path(__file__).resolve().parents[1]


def kube(*args,data=None):
    p=subprocess.run(['kubectl','--request-timeout=30s','-n','llm',*args],input=data,text=True,capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr.strip())
    return p.stdout


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--image',required=True)
    ap.add_argument('--canary',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    checked=json.loads(args.canary.read_text(encoding='utf-8'))
    if checked.get('status')!='passed' or checked.get('image')!=args.image:raise RuntimeError('Matching passed image canary required')
    args.output.mkdir(parents=True,exist_ok=False)
    ds=json.loads(kube('get','deploy','-o','json'))['items']
    pools=[d for d in ds if d['spec']['replicas']==1 and (d['metadata']['name'] in ['dsh-secure','dsh-internet'] or d['metadata']['name'].startswith('dsh-u-'))]
    gateway=next(d for d in ds if d['metadata']['name']=='dsh-environment-gateway')
    originals=pools+[gateway]
    (args.output/'deployments-before.json').write_text(json.dumps(originals,indent=2),encoding='utf-8')
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'image':args.image,'modelRestarted':False,
            'actualRdtAuthenticationTested':False,'legacyBefore':legacy_fingerprint(),'runtimes':[]}
    modified=[];marker='.kerberos-image-'+datetime.now(timezone.utc).strftime('%H%M%S')
    def probe(name,phase):
        code="""from pathlib import Path
import os,json,subprocess,stat
paths=[Path('/workspace')/MARKER,Path('/state/attachments')/MARKER]
value=IDENTITY.encode()
for p in paths:
 if PHASE=='create':
  with p.open('xb') as f:f.write(value)
 else:assert p.read_bytes()==value
r={'persistenceMarkers':len(paths)}
if PHASE=='verify':
 p=Path('/state/kerberos');assert p.is_dir() and (stat.S_IMODE(p.stat().st_mode)&0o777)==0o700, 'Kerberos cache must deny group and other access'
 assert os.environ['KRB5CCNAME']=='FILE:/state/kerberos/ccache'
 result=subprocess.run(['klist','-V'],capture_output=True,text=True,check=True)
 assert 'Kerberos' in result.stdout+result.stderr
 r.update({'uid':os.getuid(),'kerberosVersion':(result.stdout+result.stderr).strip(),
   'privateTicketCacheConfigured':True,'ticketCacheDirectoryMode':oct(stat.S_IMODE(p.stat().st_mode)), 'groupAndOtherAccessDenied':True})
 for p in paths:p.unlink()
print(json.dumps(r))
""".replace('MARKER',repr(marker)).replace('IDENTITY',repr(name)).replace('PHASE',repr(phase))
        return json.loads(kube('exec','-i','deploy/'+name,'--','python3','-',data=code))
    try:
        for d in pools:
            name=d['metadata']['name'];probe(name,'create');modified.append(d)
            patch=[{'op':'replace','path':'/spec/template/spec/containers/0/image','value':args.image}]
            kube('patch','deploy',name,'--type=json','-p',json.dumps(patch))
            kube('rollout','status','deploy/'+name,'--timeout=180s')
            result=probe(name,'verify')
            pods=json.loads(kube('get','pods','-l','app='+name,'-o','json'))['items']
            actual=next(p for p in pods if p['status'].get('phase')=='Running' and not p['metadata'].get('deletionTimestamp'))
            image_id=actual['status']['containerStatuses'][0]['imageID']
            if args.image.split('@')[1] not in image_id:raise RuntimeError('Running image digest mismatch')
            record['runtimes'].append({'runtime':name,'imageID':image_id,**result})
            print(json.dumps({'runtimeAccepted':name,'imageDigestVerified':True,'privateKerberosCache':True}),flush=True)
        modified.append(gateway)
        kube('patch','deploy','dsh-environment-gateway','--type=json','-p',json.dumps([
          {'op':'replace','path':'/spec/template/spec/containers/0/image','value':args.image}]))
        kube('rollout','status','deploy/dsh-environment-gateway','--timeout=180s')
        verify=(ROOT/'scripts/verify_private_routing_live.js').read_text(encoding='utf-8')
        record['accessVerification']=json.loads(kube('exec','-i','deploy/dsh-environment-gateway','--','node','-',data=verify))
        record['legacyAfter']=legacy_fingerprint();assert record['legacyBefore']==record['legacyAfter'];record['status']='passed'
    except Exception as e:
        record['status']='failed';record['error']=str(e)
        for d in reversed(modified):
            name=d['metadata']['name']
            kube('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':d['spec']}]))
            kube('rollout','status','deploy/'+name,'--timeout=180s')
        record['originalSpecificationsRestored']=True;raise
    finally:
        (args.output/'kerberos-runtime-live.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record),flush=True)


if __name__=='__main__':main()
