"""Collect bounded file-size summaries; optionally publish to the admin audit volume.

Requires the operator's existing Kubernetes access. Grants no new cluster role,
reads no file contents, follows no filesystem symlinks and restarts no workload.
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

REMOTE = r'''
import json, os, stat, time
def file_sizes(roots, max_entries=100000, seconds=8):
    deadline=time.monotonic()+seconds; pending=list(roots); total=entries=0; complete=True
    while pending:
        if time.monotonic()>deadline or entries>=max_entries:complete=False;break
        directory=pending.pop()
        try:
            if os.path.islink(directory):continue
            with os.scandir(directory) as items:
                for item in items:
                    if time.monotonic()>deadline or entries>=max_entries:complete=False;break
                    entries+=1
                    try:
                        info=item.stat(follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):pending.append(item.path)
                        elif stat.S_ISREG(info.st_mode):total+=info.st_size
                    except OSError:complete=False
        except OSError:complete=False
    return {'bytes':total,'complete':complete,'entries':entries}
if __name__=='__main__':
    workspace=file_sizes(['/workspace'])
    durable=file_sizes(['/state/sessions','/state/attachments','/state/storages','/state/workspaces','/state/logs'])
    try:
        state=os.statvfs('/state');used=(state.f_blocks-state.f_bfree)*state.f_frsize;capacity=state.f_blocks*state.f_frsize
    except OSError:used=capacity=None
    print(json.dumps({'workspaceFileBytes':workspace['bytes'],'workspaceScanComplete':workspace['complete'],
      'durableStateFileBytes':durable['bytes'],'durableStateScanComplete':durable['complete'],
      'stateUsedBytes':used,'stateCapacityBytes':capacity}))
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kubectl',default='kubectl');ap.add_argument('--namespace',required=True)
    ap.add_argument('--gateway',default='dsh-environment-gateway');ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--publish',action='store_true')
    args=ap.parse_args()
    if args.output.exists():raise SystemExit('Choose a new output file to retain the prior observation')
    def kube(*items,source=None):
        return subprocess.check_output([args.kubectl,'--request-timeout=25s','-n',args.namespace,*items],
          input=source,timeout=35)
    read="const fs=require('fs');const p=process.env.DSH_USER_TARGETS_FILE;if(!p)throw Error('Private routing is not configured');const d=JSON.parse(fs.readFileSync(p,'utf8'));console.log(JSON.stringify(Object.entries(d).flatMap(([user,e])=>Object.entries(e).filter(([environment])=>['secure','internet'].includes(environment)).map(([environment,t])=>({user,environment,host:t.host})))));"
    routes=json.loads(kube('exec','deploy/'+args.gateway,'--','node','-e',read))
    if len(routes)>128:raise SystemExit('Too many configured runtimes')
    services={s['metadata']['name']:s for s in json.loads(kube('get','services','-o','json'))['items']}
    pods=json.loads(kube('get','pods','-o','json'))['items']
    def collect(route):
        row={'user':route['user'],'environment':route['environment']}
        if not re.fullmatch(r'[a-z0-9_.-]{3,30}',row['user']):raise ValueError('Invalid provisioned identity')
        service=services.get(route['host'].split('.')[0]);selector=(service or {}).get('spec',{}).get('selector')
        matches=[p for p in pods if selector and all(p['metadata'].get('labels',{}).get(k)==v for k,v in selector.items())
          and not p['metadata'].get('deletionTimestamp') and p.get('status',{}).get('phase')=='Running'
          and any(c['name']=='dsh'for c in p['spec']['containers'])]
        if len(matches)!=1:return {**row,'available':False}
        try:
            data=json.loads(kube('exec','-i',matches[0]['metadata']['name'],'-c','dsh','--','timeout','22','python3','-',source=REMOTE.encode()))
            allowed={'workspaceFileBytes','workspaceScanComplete','durableStateFileBytes','durableStateScanComplete','stateUsedBytes','stateCapacityBytes'}
            if set(data)!=allowed:raise ValueError('Unexpected capacity fields')
            return {**row,**data,'available':True}
        except (subprocess.SubprocessError,ValueError):return {**row,'available':False}
    with concurrent.futures.ThreadPoolExecutor(4)as pool:rows=list(pool.map(collect,routes))
    result={'observedAt':datetime.now(timezone.utc).isoformat(),'runtimes':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(result,sort_keys=True).encode();args.output.write_bytes(raw)
    if args.publish:
        write="const fs=require('fs'),crypto=require('crypto');let b='';process.stdin.on('data',x=>b+=x);process.stdin.on('end',()=>{JSON.parse(b);const base=process.env.DSH_AUDIT_DIR||((process.env.WORKSPACE_ROOT||'/workspace/users')+'/audit');fs.mkdirSync(base,{recursive:true,mode:0o700});const target=process.env.DSH_ADMIN_CAPACITY_FILE||base+'/capacity.json',temp=target+'.'+crypto.randomBytes(8).toString('hex');fs.writeFileSync(temp,b,{mode:0o600,flag:'wx'});fs.renameSync(temp,target);console.log(crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex'));});"
        digest=kube('exec','-i','deploy/'+args.gateway,'--','node','-e',write,source=raw).decode().strip()
        if digest!=hashlib.sha256(raw).hexdigest():raise RuntimeError('Published capacity readback differs')
    print(json.dumps({'observedAt':result['observedAt'],'runtimes':len(rows),'available':sum(r['available']for r in rows),
      'completeWorkspaceScans':sum(r.get('workspaceScanComplete')is True for r in rows),'published':args.publish,
      'noFileContentsCollected':True,'workloadsRestarted':False}))

if __name__=='__main__':main()
