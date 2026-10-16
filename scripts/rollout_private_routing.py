"""Preserve admin's legacy trees and provision empty private runtimes for others.

No history ownership inference, history copies or new RDT grants. Shared guest,
demo and test identities remain in the auth store but are not routed.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from generate_user_runtimes import generate
from provision_inference_client import provision
from run_isolation_canary import legacy_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '--request-timeout=30s', '-n', 'llm', *args], input=data,
                       text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--verification-file', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = (ROOT / 'scripts/auth_proxy.js').read_text(encoding='utf-8')
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    tested = json.loads(args.verification_file.read_text(encoding='utf-8'))
    if tested.get('gatewayOverlaySHA256') != source_hash or tested.get('passed') is not True:
        raise RuntimeError('Matching passed gateway test evidence required')
    original = json.loads(kube('get', 'deploy', 'dsh-environment-gateway', '-o', 'json'))
    if any(e['name'] == 'DSH_USER_TARGETS_FILE' for e in original['spec']['template']['spec']['containers'][0]['env']):
        raise RuntimeError('Private routing is already installed; initial provisioning must not overwrite live user routing')
    (args.output / 'gateway-before.json').write_text(json.dumps(original, indent=2), encoding='utf-8')
    accounts = json.loads(kube('exec', 'deploy/dsh-environment-gateway', '--', 'node', '-e',
        "console.log(JSON.stringify(Object.keys(JSON.parse(require('fs').readFileSync(process.env.DSH_USER_STORE_PATH)))))"))
    if 'admin' not in accounts:
        raise RuntimeError('Confirmed legacy owner admin is absent')
    private = [u for u in accounts if u != 'admin' and re.fullmatch(r'[a-z0-9_.-]{3,30}', u)
               and u not in {'guest', 'demo', 'test', 'anonymous'} and not u.startswith(('rtcheck_', 'iso_'))]
    if not private:
        raise RuntimeError('No named local accounts to isolate')
    pool = json.loads(kube('get', 'deploy', 'dsh-secure', '-o', 'json'))
    image = pool['spec']['template']['spec']['containers'][0]['image']
    docs = generate(private, image)
    routes_map = next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'dsh-user-routing')
    routes = json.loads(routes_map['data']['users.json'])
    template = json.loads(json.dumps(original['spec']['template']))
    pod = template['spec'];gateway = pod['containers'][0]
    # Preserve original admin-only runtimes and their state paths/tokens.
    env = {e['name']: e.get('value') for e in gateway['env']}
    routes['admin'] = {
        'secure': {'host': env['DSH_OFFLINE_HOST'], 'port': int(env['DSH_OFFLINE_PORT']), 'tokenFile': env['DSH_OFFLINE_TOKEN_FILE']},
        'internet': {'host': env['DSH_ONLINE_HOST'], 'port': int(env['DSH_ONLINE_PORT']), 'tokenFile': env['DSH_ONLINE_TOKEN_FILE']}}
    routes_map['data']['users.json'] = json.dumps(routes, indent=2)
    record = {'timeUTC': datetime.now(timezone.utc).isoformat(), 'legacyOwner': 'admin',
              'privateAccountCount': len(private), 'excludedSharedAccountCount': len(accounts)-len(private)-1,
              'historyCopies': 0, 'realRdtGranted': False, 'legacyBefore': legacy_fingerprint(),
              'gatewaySourceSHA256': source_hash, 'runtimes': [], 'keyChecks': []}
    workloads = [d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] != 'dsh-environment-gateway']
    generated_gateway = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'dsh-environment-gateway')
    changed = False
    def apply(d):
        kube('apply', '-f', '-', data=json.dumps(d))
    try:
        for user in private:
            identity = hashlib.sha256(user.encode()).hexdigest()[:16]
            secret = 'dsh-inference-u-' + identity
            record['keyChecks'].append(provision(secret))
            for d in workloads:
                if d['spec']['template']['metadata']['labels']['dsh.bot.or.th/owner'] != identity:
                    continue
                for e in d['spec']['template']['spec']['containers'][0]['env']:
                    if e['name'] == 'DEEPSEEK_API_KEY':
                        e['valueFrom']['secretKeyRef']['name'] = secret
        for d in docs:
            if d['kind'] not in {'Deployment', 'ConfigMap'}:
                apply(d)
        # Operator-only initialization creates private subpaths; no legacy
        # session file is opened for writing or assigned to another account.
        paths = [m['subPath'] for d in workloads for m in d['spec']['template']['spec']['containers'][0]['volumeMounts']
                 if m['name'] == 'protected-workspace']
        paths.append('dsh-admin-audit')
        initialize = "from pathlib import Path\nimport json\npaths=" + repr(paths) + "\nfor p in paths: Path('/central',p).mkdir(parents=True,exist_ok=True)\nprint(json.dumps({'privateDirectoriesPrepared':len(paths)}))"
        job_name = 'dsh-private-init-' + datetime.now(timezone.utc).strftime('%H%M%S')
        job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': job_name, 'namespace': 'llm'},
          'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 180, 'template': {'metadata': {'labels': {'app': 'dsh-maintenance'}},
          'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
          'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'runAsNonRoot': True, 'fsGroup': 10001},
          'containers': [{'name': 'initialize', 'image': image, 'command': ['python3', '-c', initialize],
            'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
            'volumeMounts': [{'name': 'central', 'mountPath': '/central'}]}],
          'volumes': [{'name': 'central', 'persistentVolumeClaim': {'claimName': 'dsh-da-workspace-secure'}}]}}}}
        apply(job);kube('wait', '--for=condition=complete', 'job/'+job_name, '--timeout=180s')
        record['initialization'] = json.loads(kube('logs', 'job/'+job_name))
        kube('delete', 'job', job_name, '--wait=true')
        for d in workloads:
            apply(d)
            record['runtimes'].append(d['metadata']['name'])
        print(json.dumps({'phase': 'private runtimes starting', 'count': len(workloads)}), flush=True)
        for _ in range(160):
            ready = True
            for name in record['runtimes']:
                d = json.loads(kube('get', 'deploy', name, '-o', 'json'))
                ready &= d.get('status', {}).get('availableReplicas') == 1
            if ready: break
            time.sleep(3)
        else: raise RuntimeError('Private runtimes not ready; gateway not cut over')
        # Actual marker readback before/after replacing each private process.
        # These are new synthetic files, never edits to user histories.
        marker = '.private-acceptance-' + datetime.now(timezone.utc).strftime('%H%M%S')
        def marker_probe(name, phase):
            code = """from pathlib import Path
import os,json,hashlib
paths=[Path('/workspace')/MARKER,Path('/state/attachments')/MARKER]
value=IDENTITY.encode()
for p in paths:
 if PHASE=='create':
  with p.open('xb') as f:f.write(value)
 else:
  assert p.read_bytes()==value
  if PHASE=='cleanup':p.unlink()
assert os.getuid()==10001
assert not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()
assert not Path('/workspace/dsh_storage/sessions').exists()
print(json.dumps({'uid':os.getuid(),'markerFiles':len(paths),'phase':PHASE,'noLegacyTree':True}))
""".replace('MARKER',repr(marker)).replace('IDENTITY',repr(name)).replace('PHASE',repr(phase))
            return json.loads(kube('exec','-i','deploy/'+name,'--','python3','-',data=code))
        record['persistence'] = []
        for name in record['runtimes']:
            marker_probe(name,'create')
            old = json.loads(kube('get','pods','-l','app='+name,'-o','json'))['items'][0]['metadata']['uid']
            kube('rollout','restart','deploy/'+name)
            kube('rollout','status','deploy/'+name,'--timeout=180s')
            new = json.loads(kube('get','pods','-l','app='+name,'-o','json'))['items'][0]['metadata']['uid']
            if old==new:raise RuntimeError('Private runtime process was not replaced')
            result=marker_probe(name,'cleanup')
            record['persistence'].append({'runtime':name,'processReplaced':True,**result})
        for d in docs:
            if d['kind'] == 'ConfigMap': apply(d)
        gp = generated_gateway['spec']['template']['spec']
        names = {v['name'] for v in pod['volumes']}
        for v in gp['volumes']:
            if v['name'] not in names: pod['volumes'].append(v);names.add(v['name'])
            elif v['name'] == 'gateway-source':
                next(x for x in pod['volumes'] if x['name'] == 'gateway-source')['configMap'] = v['configMap']
        names = {m['name'] for m in gateway['volumeMounts']}
        for m in gp['containers'][0]['volumeMounts']:
            if m['name'] not in names: gateway['volumeMounts'].append(m);names.add(m['name'])
        gateway['env'] = [e for e in gateway['env'] if e['name'] not in {'DSH_USER_TARGETS_FILE','DSH_AUDIT_DIR'}]
        gateway['env'].extend([{'name':'DSH_USER_TARGETS_FILE','value':'/routing/users.json'},
                               {'name':'DSH_AUDIT_DIR','value':'/central-audit'}])
        pod['volumes'].append({'name':'central-audit','persistentVolumeClaim':{'claimName':'dsh-da-workspace-secure'}})
        gateway['volumeMounts'].append({'name':'central-audit','mountPath':'/central-audit','subPath':'dsh-admin-audit'})
        template['metadata'].setdefault('annotations', {})['dsh.bot.or.th/gateway-source-sha256'] = source_hash
        gateway['command'] = ['node','/gateway-source/auth_proxy.js']
        changed = True
        kube('patch','deploy','dsh-environment-gateway','--type=merge','-p',json.dumps({'spec':{'template':template}}))
        kube('rollout','status','deploy/dsh-environment-gateway','--timeout=180s')
        probe=(ROOT/'scripts/verify_private_routing_live.js').read_text(encoding='utf-8')
        record['accessVerification']=json.loads(kube('exec','-i','deploy/dsh-environment-gateway','--','node','-',data=probe))
        record['legacyAfter']=legacy_fingerprint()
        if record['legacyBefore']!=record['legacyAfter']:raise RuntimeError('Legacy histories changed; investigate without data rollback')
        record['status']='passed'
    except Exception as error:
        record['status']='failed';record['error']=str(error)
        if changed:
            kube('patch','deploy','dsh-environment-gateway','--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':original['spec']}]))
            kube('rollout','status','deploy/dsh-environment-gateway','--timeout=180s');record['gatewayRolledBack']=True
        for name in record['runtimes']:kube('scale','deploy',name,'--replicas=0')
        raise
    finally:
        (args.output/'private-routing-live.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__=='__main__':main()
