"""Restore thanatcc's preserved legacy runtimes without exposing peer subtrees.

Creates fresh private admin runtimes, masks the legacy /workspace/private tree,
then replaces the gateway's immutable routing revision. Never copies histories,
credentials or source data. Rollback restores specifications, not old data.
"""
import argparse
import copy
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from provision_inference_client import provision
from run_isolation_canary import legacy_fingerprint

ROOT = Path(__file__).resolve().parents[1]
OWNER = 'thanatcc'
ADMIN_ID = hashlib.sha256(b'admin').hexdigest()[:16]


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '--request-timeout=30s', '-n', 'llm', *args],
                       input=data, text=True, capture_output=True, timeout=210)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout


def apply(resource):
    kube('apply', '-f', '-', data=json.dumps(resource))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--prepared-from', type=Path,
                    help='Resume only the two admin candidates prepared by a reviewed earlier attempt')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    record = {'observedAt': datetime.now(timezone.utc).isoformat(), 'owner': OWNER,
              'historyCopies': 0, 'modelRestarted': False, 'checks': []}
    originals = {}
    changed = []
    gateway_changed = False
    try:
        gw = json.loads(kube('get', 'deploy', 'dsh-environment-gateway', '-o', 'json'))
        if args.prepared_from:
            saved = json.loads((args.prepared_from/'gateway-before.json').read_text(encoding='utf-8'))
            previous_routing = next(v['configMap']['name'] for v in saved['spec']['template']['spec']['volumes'] if v['name']=='routing')
            current_routing = next(v['configMap']['name'] for v in gw['spec']['template']['spec']['volumes'] if v['name']=='routing')
            if previous_routing != current_routing:
                raise RuntimeError('Prepared candidates cannot be resumed across a different gateway routing baseline')
        routes = json.loads(kube('exec', 'deploy/dsh-environment-gateway', '--', 'cat', '/routing/users.json'))
        if not routes['admin']['secure']['host'].startswith('dsh-secure'):
            raise RuntimeError('Initial legacy routing is not the reviewed baseline')
        # Rollback resources contain only references, never literal auth secrets.
        for env in gw['spec']['template']['spec']['containers'][0].get('env', []):
            if env.get('value') and any(x in env['name'] for x in ['PASS', 'API_KEY']):
                raise RuntimeError('Refusing to save a rollback manifest containing a literal credential')
        (args.output/'gateway-before.json').write_text(json.dumps(gw, indent=2), encoding='utf-8')
        record['legacyBefore'] = legacy_fingerprint()
        originals = {mode: json.loads(kube('get', 'deploy', 'dsh-'+mode, '-o', 'json'))
                     for mode in ['secure', 'internet']}
        # Review sensitive legacy aliases before any workload or route mutation.
        sensitive = json.loads(kube('exec','deploy/dsh-secure','--','python3','-c',
            "from pathlib import Path;import json;print(json.dumps({'recoveries':[p.name for p in Path('/workspace').glob('.state-recovery-*') if p.is_dir()]}))"))
        file_fences = ['/workspace/users/.user_auth.json', '/workspace/.git-credentials',
                       '/workspace/dsh_storage/.credentials.yaml']
        directory_fences = ['/workspace/private','/workspace/dsh-routing'] + [
            '/workspace/'+name for name in sensitive['recoveries']]
        for mode, d in originals.items():
            (args.output/('legacy-'+mode+'-before.json')).write_text(json.dumps(d, indent=2), encoding='utf-8')
        admin_routes = {}
        new_mounts, new_volumes, directory_paths = [], [], []
        for mode in ['secure', 'internet']:
            old_name = routes[OWNER][mode]['host'].split('.')[0]
            # A fresh private owner runtime must not contain unmerged user work.
            probe = """import json
from pathlib import Path
r={'workspaceFiles':sum(p.is_file() for p in Path('/workspace').rglob('*')),
   'sessionFiles':sum(p.is_file() for p in Path('/state/sessions').rglob('*'))}
print(json.dumps(r))
"""
            empty = json.loads(kube('exec', 'deploy/'+old_name, '--', 'python3', '-c', probe))
            if empty['workspaceFiles'] or empty['sessionFiles']:
                raise RuntimeError('Owner private runtime contains newer work; reconciliation required before routing changes')
            record['checks'].append({'environment': mode, 'formerPrivateWorkEmpty': True})
            original = json.loads(kube('get', 'deploy', old_name, '-o', 'json'))
            name = 'dsh-u-'+ADMIN_ID+'-'+mode
            if args.prepared_from:
                candidate=json.loads(kube('get','deploy',name,'-o','json'))
                labels=candidate['spec']['template']['metadata']['labels']
                assert labels['dsh.bot.or.th/owner']==ADMIN_ID
                assert candidate['spec']['template']['spec']['containers'][0]['image']==original['spec']['template']['spec']['containers'][0]['image']
                token_claim=name+'-routing-tokens';vname='token-'+ADMIN_ID+'-'+mode
                assert any(v.get('persistentVolumeClaim',{}).get('claimName')==token_claim for v in candidate['spec']['template']['spec']['volumes'])
                kube('rollout','status','deploy/'+name,'--timeout=180s')
                new_volumes.append({'name':vname,'persistentVolumeClaim':{'claimName':token_claim}})
                new_mounts.append({'name':vname,'mountPath':'/runtime-tokens/'+ADMIN_ID+'/'+mode,'readOnly':True})
                admin_routes[mode]={'host':name+'.llm.svc.cluster.local','port':3081,
                    'tokenFile':'/runtime-tokens/'+ADMIN_ID+'/'+mode+'/'+mode}
                continue
            if kube('get', 'deploy', name, '--ignore-not-found').strip():
                raise RuntimeError('Admin candidate already exists; refuse to overwrite')
            d = {'apiVersion': 'apps/v1', 'kind': 'Deployment',
                 'metadata': {'name': name, 'namespace': 'llm'}, 'spec': copy.deepcopy(original['spec'])}
            d['spec']['selector']['matchLabels'] = {'app': name}
            t = d['spec']['template'];t['metadata']['labels']['app'] = name
            t['metadata']['labels']['dsh.bot.or.th/owner'] = ADMIN_ID
            pod = t['spec'];container = pod['containers'][0]
            for volume in pod['volumes']:
                if 'persistentVolumeClaim' not in volume:
                    continue
                if volume['name'] == 'protected-workspace':
                    for mount in container['volumeMounts']:
                        if mount['name'] == volume['name']:
                            mount['subPath'] = mount['subPath'].replace(hashlib.sha256(OWNER.encode()).hexdigest()[:16], ADMIN_ID)
                            directory_paths.append(mount['subPath'])
                    continue
                if volume['name'] == 'package-cache':
                    continue
                claim = name+'-'+volume['name']
                if kube('get', 'pvc', claim, '--ignore-not-found').strip():
                    raise RuntimeError('Candidate PVC already exists; refuse to repurpose it')
                apply({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                       'metadata': {'name': claim, 'namespace': 'llm'},
                       'spec': {'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {
                           'storage': '100Mi' if volume['name']=='routing-tokens' else '5Gi'}}}})
                volume['persistentVolumeClaim']['claimName'] = claim
                if volume['name'] == 'routing-tokens':
                    vname = 'token-'+ADMIN_ID+'-'+mode
                    new_volumes.append({'name': vname, 'persistentVolumeClaim': {'claimName': claim}})
                    new_mounts.append({'name': vname, 'mountPath': '/runtime-tokens/'+ADMIN_ID+'/'+mode, 'readOnly': True})
            secret = 'dsh-inference-u-'+ADMIN_ID
            if mode == 'secure':
                if kube('get', 'secret', secret, '--ignore-not-found').strip():
                    raise RuntimeError('Candidate inference Secret already exists; refuse to overwrite')
                record['inferenceKey'] = provision(secret)
            for env in container['env']:
                if env['name']=='DEEPSEEK_API_KEY':
                    env['valueFrom']['secretKeyRef']['name'] = secret
            if directory_paths:
                code = 'from pathlib import Path\nfor p in '+repr(directory_paths)+":Path('/workspace',p.removeprefix('dsh/')).mkdir(parents=True,exist_ok=True)"
                kube('exec', 'deploy/dsh-secure', '--', 'python3', '-c', code)
            apply(d)
            apply({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name, 'namespace': 'llm'},
                   'spec': {'clusterIP': 'None', 'selector': {'app': name}, 'ports': [
                       {'name':'web','port':3081,'targetPort':'web'},
                       {'name':'terminal','port':7681,'targetPort':'terminal'}]}})
            kube('rollout', 'status', 'deploy/'+name, '--timeout=180s')
            admin_routes[mode] = {'host': name+'.llm.svc.cluster.local', 'port':3081,
                                 'tokenFile':'/runtime-tokens/'+ADMIN_ID+'/'+mode+'/'+mode}
        # Shadow the sole private-identity subtree before assigning the old tree
        # to a non-admin. Read-only emptyDir also denies creation of new entries.
        d = originals['secure'];template = copy.deepcopy(d['spec']['template'])
        fence_map='dsh-legacy-credential-fence-v1'
        apply({'apiVersion':'v1','kind':'ConfigMap','immutable':True,
            'metadata':{'name':fence_map,'namespace':'llm'},'data':{'empty':'','auth':'{}'}})
        template['spec']['volumes']=[v for v in template['spec']['volumes'] if v['name'] not in {'legacy-private-fence','legacy-credential-fence'}]
        container=template['spec']['containers'][0]
        container['volumeMounts']=[m for m in container['volumeMounts'] if m['name'] not in {'legacy-private-fence','legacy-credential-fence'}]
        template['spec']['volumes'].extend([{'name':'legacy-private-fence','emptyDir':{}},
            {'name':'legacy-credential-fence','configMap':{'name':fence_map}}])
        container['volumeMounts'].extend({'name':'legacy-private-fence','mountPath':p,'readOnly':True} for p in directory_fences)
        container['volumeMounts'].extend({'name':'legacy-credential-fence','mountPath':p,'readOnly':True,
            'subPath':'auth' if p.endswith('.user_auth.json') else 'empty'} for p in file_fences)
        changed.append('secure')
        kube('patch','deploy','dsh-secure','--type=merge','-p',json.dumps({'spec':{'template':template}}))
        kube('rollout','status','deploy/dsh-secure','--timeout=180s')
        fence = """from pathlib import Path
import json
for name in DIRECTORIES:
 p=Path(name);assert p.is_dir() and not list(p.iterdir())
 try:(p/'forbidden-marker').write_text('x');raise RuntimeError('Fence writable')
 except OSError:pass
for name in FILES:
 p=Path(name);assert p.read_text() in ['', '{}']
 try:p.open('a').close();raise RuntimeError('Credential fence writable')
 except OSError:pass
print(json.dumps({'privateSubtreeHidden':True,'privateSubtreeReadOnly':True,'credentialAliasesMasked':len(FILES),'recoveryAndRoutingDirectoriesMasked':len(DIRECTORIES)-1}))
""".replace('DIRECTORIES',repr(directory_fences)).replace('FILES',repr(file_fences))
        record['fence'] = json.loads(kube('exec','deploy/dsh-secure','--','python3','-c',fence))
        assert legacy_fingerprint() == record['legacyBefore']
        next_routes = copy.deepcopy(routes)
        next_routes[OWNER] = routes['admin'];next_routes['admin'] = admin_routes
        text = json.dumps(next_routes, indent=2)
        name = 'dsh-user-routing-'+hashlib.sha256(text.encode()).hexdigest()[:12]
        apply({'apiVersion':'v1','kind':'ConfigMap','immutable':True,
               'metadata':{'name':name,'namespace':'llm'},'data':{'users.json':text}})
        template = copy.deepcopy(gw['spec']['template']);pod=template['spec']
        next(v for v in pod['volumes'] if v['name']=='routing')['configMap']['name'] = name
        pod['volumes'].extend(new_volumes);pod['containers'][0]['volumeMounts'].extend(new_mounts)
        gateway_changed = True
        kube('patch','deploy','dsh-environment-gateway','--type=merge','-p',json.dumps({'spec':{'template':template}}))
        kube('rollout','status','deploy/dsh-environment-gateway','--timeout=180s')
        probe = (ROOT/'scripts/verify_private_routing_live.js').read_text(encoding='utf-8')
        record['access'] = json.loads(kube('exec','-i','deploy/dsh-environment-gateway','--','node','-',data=probe))
        record['legacyAfter'] = legacy_fingerprint()
        assert record['legacyAfter']==record['legacyBefore']
        record['status']='passed'
    except Exception as e:
        record['status']='failed';record['error']=str(e)
        if gateway_changed:
            kube('patch','deploy','dsh-environment-gateway','--type=json','-p',json.dumps([
                {'op':'replace','path':'/spec','value':gw['spec']}]))
            kube('rollout','status','deploy/dsh-environment-gateway','--timeout=180s')
        for mode in changed:
            kube('patch','deploy','dsh-'+mode,'--type=json','-p',json.dumps([
                {'op':'replace','path':'/spec','value':originals[mode]['spec']}]))
            kube('rollout','status','deploy/dsh-'+mode,'--timeout=180s')
        if gateway_changed or changed:
            record['priorRoutingAndSpecsRestored']=True
        else:
            record['priorRoutingAndSpecsUnchanged']=True
        raise
    finally:
        (args.output/'legacy-owner-restoration.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__=='__main__':
    main()
