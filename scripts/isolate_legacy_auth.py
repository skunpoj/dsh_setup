"""Move legacy account verifiers and access audit out of execution mounts.

The existing owner is unchanged. Disabled peer records are retained in an
operator-only Kubernetes Secret, not in the generated-code workspace. A
readback-verified backup precedes removal of the old active store.
"""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

from migrate_legacy_private_runtime import kube, IMAGE, ROOT


def credential_from_dpapi(path):
    # Captured stdout stays in this process; never print the decrypted document.
    literal=str(path.resolve()).replace("'", "''")
    script="Add-Type -AssemblyName System.Security;$b=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes('"+literal+"'),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser);[Console]::Write([Text.Encoding]::UTF8.GetString($b))"
    p=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,encoding='utf-8',check=True)
    old=json.loads(p.stdout);env=old['spec']['template']['spec']['containers'][0]['env']
    return next(e['value'] for e in env if e['name']=='AUTH_PASS')


SEED = r'''
import pathlib,json,os,shutil
dest=pathlib.Path('/auth/users');dest.mkdir(parents=True,exist_ok=True)
target=dest/'users.json'
if not target.exists():
 data=json.loads(pathlib.Path('/seed/users.json').read_text());assert len(data)==1 and all(v.get('scheme')=='scrypt-v1' for v in data.values())
 temp=dest/'users.initializing';temp.write_text(json.dumps(data));os.chmod(temp,0o600);temp.replace(target)
 audit=pathlib.Path('/auth/audit');audit.mkdir(exist_ok=True)
 source=pathlib.Path('/workspace/users/audit')
 for p in source.glob('events*.jsonl'):
  if p.is_file() and not p.is_symlink():shutil.copy2(p,audit/p.name)
for base,dirs,files in os.walk('/auth',followlinks=False):
 for p in [pathlib.Path(base),*[pathlib.Path(base)/n for n in dirs+files]]:os.chown(p,10001,10001,follow_symlinks=False)
os.chmod('/auth/users',0o700);os.chmod(target,0o600)
os.chown('/tokens',10001,10001);os.chmod('/tokens',0o700)
'''


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name',choices=['dsh-user2','dsh3'],required=True)
    ap.add_argument('--credential-snapshot',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--reuse-provisioning',action='store_true')
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    before=json.loads(kube('get','deploy',a.name,'-o','json'));spec=before['spec'];worker=spec['template']['spec']['containers'][0]
    if worker['securityContext'].get('runAsUser')!=10001:raise RuntimeError('Non-root runtime acceptance required first')
    owner=next(e['value'] for e in worker['env'] if e['name']=='AUTH_USER')
    password=credential_from_dpapi(a.credential_snapshot)
    if a.reuse_provisioning:
        stored=json.loads(kube('get','secret','dsh-legacy-disabled-accounts-'+owner,'-o','json'))
        raw=base64.b64decode(stored['data']['users.json']).decode('utf-8')
    else:
        raw=kube('exec','deploy/'+a.name,'--','node','-e',"process.stdout.write(require('fs').readFileSync('/workspace/users/.user_auth.json','utf8'))")
    users=json.loads(raw);assert owner in users and all(v.get('scheme')=='scrypt-v1' for v in users.values())
    backup='dsh-legacy-disabled-accounts-'+owner
    # Back up verifiers privately, independently read back and compare decoded bytes.
    if not a.reuse_provisioning:
        kube('create','-f','-',source=json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':backup,'namespace':'llm'},'type':'Opaque','data':{'users.json':base64.b64encode(raw.encode()).decode()}}))
    saved=json.loads(kube('get','secret',backup,'-o','json'));assert base64.b64decode(saved['data']['users.json'])==raw.encode()
    claim='dsh-legacy-auth-'+owner;seed=claim+'-seed'
    if not a.reuse_provisioning:
        kube('create','-f','-',source=json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':seed,'namespace':'llm'},'type':'Opaque','stringData':{'users.json':json.dumps({owner:users[owner]})}}))
        kube('create','-f','-',source=json.dumps({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':claim,'namespace':'llm'},'spec':{'accessModes':['ReadWriteOnce'],'storageClassName':'topolvm','resources':{'requests':{'storage':'1Gi'}}}}))
    else:
        stored=json.loads(kube('get','secret',seed,'-o','json'))
        assert json.loads(base64.b64decode(stored['data']['users.json']))=={owner:users[owner]}
        kube('get','pvc',claim,'-o','name')
    script=(ROOT/'container/start-legacy-private.sh').read_text(encoding='utf-8')
    script=script.replace('node /scripts/auth_proxy.js &\nauth_pid=$!\n','').replace(' "$auth_pid"','').replace('"$dsh_pid" "$auth_pid"','"$dsh_pid"')
    script=script.replace('printf \'%s\' "${BASH_REMATCH[1]}" >/tmp/dsh_token.txt','printf \'%s\' "${BASH_REMATCH[1]}" >/tmp/dsh_token.txt\n    printf \'%s\' "${BASH_REMATCH[1]}" >/runtime-tokens/legacy')
    # The worker no longer needs to read an account file.
    script=script.replace('test -s /workspace/users/.user_auth.json\n','')
    digest=hashlib.sha256(script.encode()).hexdigest();cm='dsh-legacy-separated-start-'+digest[:12]
    kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':cm,'namespace':'llm'},'data':{'start.sh':script}}))
    new=copy.deepcopy(spec);pod=new['template']['spec'];worker=pod['containers'][0]
    base_env={e['name']:copy.deepcopy(e) for e in worker['env']}
    for key in ['AUTH_USER','DSH_COOKIE_NAME']:worker['env']=[e for e in worker['env'] if e['name']!=key]
    # fsGroup recursively widens credential modes to 0660; seed ownership
    # explicitly instead, preserving credentials-local's strict 0600 contract.
    pod['securityContext'].pop('fsGroup',None)
    pod['initContainers'][0]['command'][-1]+='\nfor p in [home/".dsh/.credentials.yaml",home/".git-credentials"]:\n if p.is_file():os.chmod(p,0o600)\n'
    for v in pod['volumes']:
        if v['name']=='legacy-start':v['configMap']['name']=cm
    pod['volumes'] += [{'name':'legacy-auth','persistentVolumeClaim':{'claimName':claim}},{'name':'auth-seed','secret':{'secretName':seed}},{'name':'launch-token','emptyDir':{}}]
    worker['volumeMounts'].append({'name':'launch-token','mountPath':'/runtime-tokens'})
    proxy_env=[base_env[k] for k in ['AUTH_USER','DSH_TRUSTED_HOST','DSH_COOKIE_NAME'] if k in base_env]
    proxy_env += [{'name':k,'value':v} for k,v in {'WORKSPACE_ROOT':'/auth/users','DSH_USER_STORE_PATH':'/auth/users/users.json','DSH_USER_SETTINGS_PATH':'/auth/users/settings.json','DSH_AUDIT_DIR':'/auth/audit','DSH_OFFLINE_TOKEN_FILE':'/runtime-tokens/legacy','DSH_ONLINE_TOKEN_FILE':'/runtime-tokens/legacy'}.items()]
    proxy={'name':'auth-proxy','image':IMAGE,'command':['node','/scripts/auth_proxy.js'],'env':proxy_env,
           'securityContext':copy.deepcopy(worker['securityContext']),'resources':{'requests':{'cpu':'50m','memory':'128Mi'},'limits':{'cpu':'1','memory':'512Mi'}},
           'ports':[{'name':'auth-proxy','containerPort':3080}],
           'volumeMounts':[{'name':'legacy-auth','mountPath':'/auth'},{'name':'dsh-scripts','mountPath':'/scripts','readOnly':True},{'name':'launch-token','mountPath':'/runtime-tokens','readOnly':True},{'name':'isolated-local-storage','mountPath':'/workspace','readOnly':True}],
           'readinessProbe':{'httpGet':{'path':'/login','port':3080},'periodSeconds':5,'timeoutSeconds':3}}
    worker['ports']=[p for p in worker.get('ports',[]) if p.get('containerPort')!=3080]
    pod['containers'].append(proxy)
    pod['initContainers'].append({'name':'private-auth-seed','image':IMAGE,'command':['python3','-c',SEED],
        'securityContext':copy.deepcopy(pod['initContainers'][0]['securityContext']),
        'volumeMounts':[{'name':'legacy-auth','mountPath':'/auth'},{'name':'auth-seed','mountPath':'/seed','readOnly':True},{'name':'isolated-local-storage','mountPath':'/workspace','readOnly':True},{'name':'launch-token','mountPath':'/tokens'}]})
    (a.output/'deployment-before.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'name':a.name,'owner':owner,'backupReadbackVerified':True,'backupSecret':backup,'authClaim':claim}
    changed=False;removed=False
    try:
        changed=True;kube('patch','deploy',a.name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':new}]))
        kube('rollout','status','deploy/'+a.name,'--timeout=180s')
        probe=(ROOT/'scripts/review_legacy_auth.js').read_text(encoding='utf-8').replace("const users=JSON.parse(fs.readFileSync('/workspace/users/.user_auth.json'));","const users=JSON.parse(fs.readFileSync(0,'utf8'));")
        record['behavior']=json.loads(kube('exec','-i','deploy/'+a.name,'-c','auth-proxy','--','node','-e',probe,source=json.dumps({owner:password,'guest':'denied','thanatcc':'denied'})))
        if not record['behavior']['authenticatedHistoryRpcSucceeded']:raise RuntimeError('History acceptance failed')
        check="const fs=require('fs');const p='/auth/users/users.json';let v=JSON.parse(fs.readFileSync(p));console.log(JSON.stringify({accounts:Object.keys(v).length,ownerOnly:Object.keys(v).join(',')===process.env.AUTH_USER,hashed:Object.values(v).every(x=>x.scheme==='scrypt-v1')}));"
        record['authStore']=json.loads(kube('exec','deploy/'+a.name,'-c','auth-proxy','--','node','-e',check));assert record['authStore']['ownerOnly'] and record['authStore']['hashed']
        # Remove only the original verifier file, after backup and replacement acceptance.
        remove="import pathlib,hashlib,json; p=pathlib.Path('/workspace/users/.user_auth.json');expected="+repr(hashlib.sha256(raw.encode()).hexdigest())+";assert hashlib.sha256(p.read_bytes()).hexdigest()==expected;p.unlink();print(json.dumps({'oldWorkspaceAccountFileRemoved':True,'authMountVisibleToWorker':pathlib.Path('/auth/users/users.json').exists()}))"
        record['workerBoundary']=json.loads(kube('exec','deploy/'+a.name,'-c','dsh','--','python3','-c',remove));removed=True;assert not record['workerBoundary']['authMountVisibleToWorker']
        current=json.loads(kube('get','deploy',a.name,'-o','json'))
        if password in current['metadata'].get('annotations',{}).get('kubectl.kubernetes.io/last-applied-configuration',''):
            kube('annotate','deploy',a.name,'kubectl.kubernetes.io/last-applied-configuration-')
        record['status']='passed'
        manifest={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':a.name,'namespace':'llm'},'spec':new}
        (a.output/'candidate-public.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    except Exception as error:
        record['status']='failed';record['error']=str(error)
        if changed:
            if removed:
                restore="const fs=require('fs');const p='/workspace/users/.user_auth.json';fs.writeFileSync(p,fs.readFileSync(0),{mode:0o600});"
                kube('exec','-i','deploy/'+a.name,'-c','dsh','--','node','-e',restore,source=raw)
            kube('patch','deploy',a.name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':spec}]))
            kube('rollout','status','deploy/'+a.name,'--timeout=180s');record['deploymentRestored']=True
        raise
    finally:
        password=None;users.clear();raw=None
        (a.output/'result.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8');print(json.dumps(record),flush=True)


if __name__=='__main__':main()
