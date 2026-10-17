"""Guarded credential migration. Credentials stay in process memory, never artifacts.

Only the authentication gateway/process is replaced. Runtime/history mounts and
Livy/Spark permissions are unchanged. Rollback restores the original account
bytes only on failure, before restoring an incompatible old gateway process.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def kube(*args, source=None):
    p = subprocess.run(['kubectl', '-n', 'llm', '--request-timeout=30s', *args],
                       input=source, text=True, encoding='utf-8', capture_output=True, timeout=180)
    if p.returncode:
        # Do not emit stdout: credential reads use that channel privately.
        raise RuntimeError('Kubernetes operation failed: ' + p.stderr[-300:])
    return p.stdout


STORE_READ = "const fs=require('fs');console.log(fs.readFileSync(process.env.DSH_USER_STORE_PATH||'/workspace/users/.user_auth.json','utf8'));"
STORE_RESTORE = "const fs=require('fs');const p=process.env.DSH_USER_STORE_PATH||'/workspace/users/.user_auth.json';const v=fs.readFileSync(0);fs.writeFileSync(p+'.rollback',v,{mode:0o600});fs.renameSync(p+'.rollback',p);"
STORE_CHECK = "const fs=require('fs');const p=process.env.DSH_USER_STORE_PATH||'/workspace/users/.user_auth.json';const v=JSON.parse(fs.readFileSync(p));console.log(JSON.stringify({accounts:Object.keys(v).length,hashed:Object.values(v).every(x=>x.scheme==='scrypt-v1'),mode:fs.statSync(p).mode&511}));"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--rollback-dir', type=Path, required=True)
    ap.add_argument('--legacy', choices=['dsh-user2', 'dsh3'])
    ap.add_argument('--source-only', action='store_true', help='Update a hash-compatible source without reverting account records')
    args = ap.parse_args()
    name = args.legacy or 'dsh-environment-gateway'
    source = (ROOT/'scripts/auth_proxy.js').read_text(encoding='utf-8')
    helper = (ROOT/'scripts/password_store.js').read_text(encoding='utf-8')
    digest = hashlib.sha256((source+helper).encode()).hexdigest()
    if not args.apply:
        print(json.dumps({'deployment': name, 'source': digest, 'apply': False})); return
    args.rollback_dir.mkdir(parents=True, exist_ok=False)
    before = json.loads(kube('get', 'deploy', name, '-o', 'json'))
    # A legacy startup command may contain historic credentials. Its deployment
    # is not changed by this process-only operation, so do not export those bytes.
    saved = before if not args.legacy else {'deployment': name, 'deploymentChanged': False,
        'specSHA256': hashlib.sha256(json.dumps(before['spec'], sort_keys=True).encode()).hexdigest()}
    snapshot = args.rollback_dir/'deployment-before.json'
    snapshot.write_text(json.dumps(saved, indent=2)); snapshot.chmod(0o600)
    original = kube('exec', 'deploy/'+name, '--', 'node', '-e', STORE_READ)
    users = json.loads(original)
    if not users or (not args.source_only and any(not isinstance(v, str) for v in users.values())):
        raise RuntimeError('Expected an unmigrated account store; refuse replay')
    record = {'timeUTC': datetime.now(timezone.utc).isoformat(), 'deployment': name,
              'sourceSHA256': digest, 'credentialsExportedToArtifacts': False,
              'runtimeOrModelRestartRequested': False}
    changed = False
    try:
        if args.legacy:
            # Persistent startup source is maintained separately in dsh-scripts.
            payload = json.dumps({'auth_proxy.js': source, 'password_store.js': helper})
            install = r'''
import sys,json,pathlib,os,subprocess,signal,time
d=json.load(sys.stdin);root=pathlib.Path('/tmp/dsh-credential-hardening');root.mkdir(mode=0o700,exist_ok=True)
for n,v in d.items():(root/n).write_text(v)
pids=[]
for p in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
 try:
  a=p.read_bytes().split(b'\0')
  if len(a)>1 and a[0].endswith(b'node') and a[1] in [b'/scripts/auth_proxy.js',b'/tmp/dsh-credential-hardening/auth_proxy.js']:pids.append(int(p.parent.name))
 except OSError:pass
if len(pids)!=1:raise RuntimeError('Expected one legacy auth process')
os.kill(pids[0],signal.SIGTERM);time.sleep(1)
env=dict(os.environ);env.pop('AUTH_PASS',None)
with open('/tmp/dsh-auth-hardened.log','ab') as log:
 child=subprocess.Popen(['node',str(root/'auth_proxy.js')],env=env,stdout=log,stderr=log,start_new_session=True,stdin=subprocess.DEVNULL)
print(json.dumps({'authProcessReplaced':True,'pid':child.pid}))
'''
            changed = True
            record['process'] = json.loads(kube('exec', '-i', 'deploy/'+name, '--', 'python3', '-', source=install.replace('d=json.load(sys.stdin)', 'd='+repr(json.loads(payload)))))
        else:
            cm = 'dsh-gateway-password-'+digest[:12]
            kube('apply', '-f', '-', source=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,
                 'metadata':{'name':cm,'namespace':'llm'},'data':{'auth_proxy.js':source,'password_store.js':helper}}))
            template = json.loads(json.dumps(before['spec']['template']))
            for volume in template['spec']['volumes']:
                if volume['name'] == 'gateway-source': volume['configMap']['name'] = cm
            template['metadata'].setdefault('annotations', {})['dsh.bot.or.th/gateway-source-sha256'] = hashlib.sha256(source.encode()).hexdigest()
            changed = True
            kube('patch', 'deploy', name, '--type=merge', '-p', json.dumps({'spec':{'strategy':{'type':'Recreate','rollingUpdate':None},'template':template}}))
            kube('rollout','status','deploy/'+name,'--timeout=150s')
            record['configMap'] = cm
        for _ in range(30):
            try:
                state = json.loads(kube('exec','deploy/'+name,'--','node','-e',STORE_CHECK))
                if state['hashed']: break
            except RuntimeError: pass
            time.sleep(1)
        else: raise RuntimeError('Credential migration did not complete')
        if state['mode'] != 0o600 or state['accounts'] != len(users):
            raise RuntimeError('Account count or file permission mismatch')
        if args.source_only and not args.legacy:
            probe = (ROOT/'scripts/verify_hashed_gateway_live.js').read_text(encoding='utf-8')
        elif not args.legacy:
            probe = (ROOT/'scripts/verify_private_routing_live.js').read_text(encoding='utf-8')
            probe = probe.replace("const users=JSON.parse(fs.readFileSync(process.env.DSH_USER_STORE_PATH,'utf8'));", "const users=JSON.parse(fs.readFileSync(0,'utf8'));")
        else:
            probe = (ROOT/'scripts/review_legacy_auth.js').read_text(encoding='utf-8')
            probe = probe.replace("const users=JSON.parse(fs.readFileSync('/workspace/users/.user_auth.json'));", "const users=JSON.parse(fs.readFileSync(0,'utf8'));")
            if args.source_only:
                probe = probe.replace("const users=JSON.parse(fs.readFileSync(0,'utf8'));", "const users={[process.env.AUTH_USER]:process.env.AUTH_PASS};")
        record['behavior'] = json.loads(kube('exec','-i','deploy/'+name,'--','node','-e',probe,source=json.dumps(users)))
        if args.legacy and (not record['behavior']['authenticatedHistoryRpcSucceeded'] or record['behavior']['authenticatedAppIsLoginPage']):
            raise RuntimeError('Legacy application/history verification failed')
        record['store'] = state
        record['status'] = 'passed'
    except Exception:
        record['status'] = 'failed'
        if changed:
            # Restore the prior live store privately, not through a saved artifact.
            if not args.source_only:
                kube('exec','-i','deploy/'+name,'--','node','-e',STORE_RESTORE,source=original)
            if not args.legacy:
                kube('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':before['spec']}]))
                kube('rollout','status','deploy/'+name,'--timeout=150s')
            record['credentialStoreRestored'] = not args.source_only
        raise
    finally:
        users.clear(); original = None
        (args.rollback_dir/'result.json').write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps(record), flush=True)


if __name__ == '__main__': main()
