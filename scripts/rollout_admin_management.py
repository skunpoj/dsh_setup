"""Replace only the authentication gateway; retain auth content and all runtime mounts.

Private deployment snapshot enables rollback. Does not restart inference or users'
execution pods. Existing gateway browser sessions must sign in again after reload.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--namespace', default='llm')
    ap.add_argument('--deployment', default='dsh-environment-gateway')
    ap.add_argument('--expected-source-sha256', required=True)
    ap.add_argument('--snapshot', type=Path, help='Optional reviewed status JSON; replace it in the same gateway-only handover')
    ap.add_argument('--manual-dir', help='Already published versioned manual directory on the gateway auth volume')
    ap.add_argument('--signup-config', type=Path, help='Reviewed read-only signup pool/token mounts; no runtime data mounts or management token')
    ap.add_argument('--signup-acceptance', type=Path, help='Matching real signup/isolation/persistence result required before enabling signup')
    args = ap.parse_args()
    if args.manual_dir:
        import re
        if not re.fullmatch(r'/auth/manuals/[a-f0-9]{16}', args.manual_dir):
            raise ValueError('Expected a versioned operator-published manual directory')
    signup = json.loads(args.signup_config.read_text(encoding='utf-8')) if args.signup_config else None
    if signup:
        import re
        if not isinstance(signup.get('registrationEnabled'), bool):
            raise ValueError('Explicit signup state required')
        if signup['registrationEnabled'] and signup.get('poolFile') != '/signup-pool/live.json':
            raise ValueError('Publish the reviewed live pool before enabling registration')
        for v in signup['volumes']:
            if not re.fullmatch(r'signup-[a-z0-9-]+', v['name']) or set(v)-{'name','persistentVolumeClaim','configMap'} or ('persistentVolumeClaim' in v)==('configMap' in v):
                raise ValueError('Only bounded signup configuration and token claims may be added')
        names={v['name'] for v in signup['volumes']}
        for m in signup['mounts']:
            if m['name'] not in names or m.get('readOnly') is not True or not (m['mountPath']=='/signup-pool' or re.fullmatch(r'/runtime-tokens/signup/[a-f0-9]{16}/(secure|internet)',m['mountPath'])):
                raise ValueError('Signup gateway mounts must be read-only configuration or launch tokens')

    def kube(*parts, data=None):
        p = subprocess.run(['kubectl', '-n', args.namespace, '--request-timeout=30s', *parts],
                           input=data, text=True, encoding='utf-8', capture_output=True, timeout=180)
        if p.returncode:
            raise RuntimeError(p.stderr[-500:])
        return p.stdout

    source = (ROOT/'scripts/auth_proxy.js').read_text(encoding='utf-8')
    helper = (ROOT/'scripts/password_store.js').read_text(encoding='utf-8')
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    if signup and signup['registrationEnabled']:
        if not args.signup_acceptance:
            raise ValueError('Matching real signup acceptance is required before activation')
        accepted=json.loads(args.signup_acceptance.read_text(encoding='utf-8'))
        if accepted.get('status')!='passed' or accepted.get('gatewaySourceSHA256')!=source_hash or not accepted.get('accountAssignmentSurvivedGatewayRestart') or any(accepted.get(k,0)<n for k,n in {'defaultInternetDenials':2,'actualDshReplies':2,'crossUserHistoryDenials':4,'terminalReadbacks':4}.items()):
            raise ValueError('Signup acceptance is incomplete or belongs to another gateway source')
    snapshot_text=args.snapshot.read_text(encoding='utf-8')if args.snapshot else None
    snapshot=json.loads(snapshot_text)if snapshot_text is not None else None
    if snapshot is not None:
        if not isinstance(snapshot,dict)or not isinstance(snapshot.get('environments'),list)or not isinstance(snapshot.get('model'),dict):
            raise ValueError('Expected a reviewed environment/model status object')
    print(json.dumps({'apply': args.apply, 'sourceSHA256': source_hash, 'gatewayOnly': True}), flush=True)
    if not args.apply:
        return
    args.output.mkdir(parents=True, exist_ok=False)
    before = json.loads(kube('get', 'deploy', args.deployment, '-o', 'json'))
    (args.output/'deployment-before.private.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    read_hash = "console.log(require('crypto').createHash('sha256').update(require('fs').readFileSync('/gateway-source/auth_proxy.js')).digest('hex'))"
    if kube('exec', 'deploy/'+args.deployment, '--', 'node', '-e', read_hash).strip() != args.expected_source_sha256:
        raise RuntimeError('Live gateway changed; review before replacing')
    store_probe = "const f=require('fs'),c=require('crypto'),u=JSON.parse(f.readFileSync(process.env.DSH_USER_STORE_PATH)),digest=x=>c.createHash('sha256').update(x).digest('hex');console.log(JSON.stringify({count:Object.keys(u).length,hash:digest(JSON.stringify(Object.keys(u).sort().map(k=>[k,u[k]]))),records:Object.fromEntries(Object.keys(u).map(k=>[k,digest(JSON.stringify(u[k]))]))}))"
    def store():
        return json.loads(kube('exec', 'deploy/'+args.deployment, '--', 'node', '-e', store_probe))
    original_store = store()
    def original_accounts_preserved():
        current=store()
        if signup and signup['registrationEnabled']:
            return all(current['records'].get(k)==v for k,v in original_store['records'].items())
        return current==original_store
    record = {'timeUTC': datetime.now(timezone.utc).isoformat(), 'gatewaySourceSHA256': source_hash,
              'modelOrRuntimeRestartRequested': False, 'beforeAccounts': original_store['count']}
    changed = False
    try:
        name = 'dsh-gateway-users-'+source_hash[:12]
        kube('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
             'metadata': {'name': name}, 'data': {'auth_proxy.js': source, 'password_store.js': helper}}))
        template = json.loads(json.dumps(before['spec']['template']))
        if signup:
            pod=template['spec'];container=pod['containers'][0]
            if pod.get('automountServiceAccountToken') is not False or before['spec']['replicas']!=1:
                raise RuntimeError('Signup allocation requires a single non-privileged gateway writer')
            names={v['name'] for v in signup['volumes']}
            pod['volumes']=[v for v in pod['volumes'] if not v['name'].startswith('signup-')]+signup['volumes']
            container['volumeMounts']=[m for m in container['volumeMounts'] if not m['name'].startswith('signup-')]+signup['mounts']
            container['env']=[e for e in container['env'] if e['name'] not in {'DSH_ALLOW_REGISTRATION','DSH_SIGNUP_POOL_FILE'}]
            container['env'].append({'name':'DSH_ALLOW_REGISTRATION','value':str(signup['registrationEnabled']).lower()})
            if signup.get('poolFile'):
                container['env'].append({'name':'DSH_SIGNUP_POOL_FILE','value':signup['poolFile']})
            record['selfServiceRegistrationEnabled']=signup['registrationEnabled']
        if args.manual_dir:
            env=template['spec']['containers'][0].setdefault('env',[])
            env[:]=[e for e in env if e['name']!='DSH_MANUAL_DIR']
            env.append({'name':'DSH_MANUAL_DIR','value':args.manual_dir})
            record['manualDirectory']=args.manual_dir
        for volume in template['spec']['volumes']:
            if volume['name'] == 'gateway-source':
                volume['configMap']['name'] = name
        if snapshot_text is not None:
            summary_name='dsh-admin-status-'+hashlib.sha256(snapshot_text.encode()).hexdigest()[:12]
            kube('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,
              'metadata':{'name':summary_name},'data':{'summary.json':snapshot_text}}))
            volume=next(v for v in template['spec']['volumes']if v['name']=='admin-status')
            volume['configMap']['name']=summary_name
            record['snapshotConfigMap']=summary_name
        template.setdefault('metadata', {}).setdefault('annotations', {})['dsh.bot.or.th/gateway-source-sha256'] = source_hash
        changed = True
        kube('patch', 'deploy', args.deployment, '--type=merge', '-p', json.dumps({'spec': {
             'strategy': {'type': 'Recreate', 'rollingUpdate': None}, 'template': template}}))
        kube('rollout', 'status', 'deploy/'+args.deployment, '--timeout=150s')
        if kube('exec', 'deploy/'+args.deployment, '--', 'node', '-e', read_hash).strip() != source_hash:
            raise RuntimeError('Mounted source differs')
        if snapshot is not None:
            read="console.log(require('fs').readFileSync(process.env.DSH_ADMIN_SUMMARY_FILE||'/admin-status/summary.json','utf8'))"
            if json.loads(kube('exec','deploy/'+args.deployment,'--','node','-e',read))!=snapshot:
                raise RuntimeError('Mounted model/environment status differs')
            record['snapshotContentVerified']=True
        if not original_accounts_preserved():
            raise RuntimeError('Account content changed unexpectedly; preserve current store and investigate')
        if signup and signup['registrationEnabled']:
            # Once public signup is active, never run another process that
            # rewrites the account file; the gateway remains its sole writer.
            probe="""const h=require('http');function r(path,method='GET',body=''){return new Promise((ok,no)=>{const q=h.request({host:'127.0.0.1',port:3080,path,method,headers:{host:process.env.DSH_TRUSTED_HOST,'Content-Type':'application/x-www-form-urlencoded'}},s=>{let text='';s.on('data',b=>text+=b);s.on('end',()=>ok({status:s.statusCode,text}));});q.setTimeout(10000,()=>q.destroy(Error('timeout')));q.on('error',no);q.end(body);});}(async()=>{const p=await r('/login');if(!p.text.includes('id="tab-register"'))throw Error('Signup tab missing');const x=await r('/login','POST','username=admin&password=invalid-synthetic-verification');if(x.status!==401)throw Error('Incorrect password accepted');console.log(JSON.stringify({liveCreateAccountTabVisible:true,wrongPasswordDenied:true,accountStoreWritesByProbe:0,authenticatedSignupQualifiedOnMatchingCandidate:true}));})().catch(e=>{console.error(e.message);process.exitCode=1;});"""
        else:
            probe = (ROOT/'scripts/verify_hashed_gateway_live.js').read_text(encoding='utf-8')
        record['liveAuthChecks'] = json.loads(kube('exec', '-i', 'deploy/'+args.deployment, '--', 'node', '-', data=probe))
        if not original_accounts_preserved():
            raise RuntimeError('Account probe did not preserve original accounts')
        record.update(status='passed', accountContentPreserved=True, configMap=name,
                      positiveAdminFlow='Disposable-account browser/HTTP suite; not a live administrator login')
    except Exception:
        record['status'] = 'failed'
        if changed:
            # Restore configuration only, never older account or history bytes.
            kube('patch', 'deploy', args.deployment, '--type=json', '-p', json.dumps([
                {'op': 'replace', 'path': '/spec', 'value': before['spec']}]))
            kube('rollout', 'status', 'deploy/'+args.deployment, '--timeout=150s')
            record['configurationRolledBack'] = True
        raise
    finally:
        (args.output/'result.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
