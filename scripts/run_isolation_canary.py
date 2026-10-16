"""Run two synthetic users in a fresh namespace without writing the legacy tree.

Retains synthetic PVCs/evidence, scales all candidate deployments to zero and
removes test secrets at completion. Never patches Production deployments.
"""
import argparse
import hashlib
import json
import secrets
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from isolation_canary_resources import build, identity, USERS, DURABLE

ROOT = Path(__file__).resolve().parents[1]


def command(*args, data=None, check=True):
    p = subprocess.run(['kubectl', '--request-timeout=30s', *args], input=data,
                       text=True, capture_output=True)
    if check and p.returncode:
        # kubectl output for these operations contains no secret payload.
        raise RuntimeError(p.stderr.strip())
    return p.stdout


def legacy_fingerprint():
    codec = (ROOT / 'scripts/session_cwd_migration.py').read_text(encoding='utf-8')
    code = codec + '''
rows=[];ids=set();codec=Zstd()
for p in sorted(Path('/state/sessions').rglob('*.jsonl.zstd')):
 before=p.stat();h,n=codec.header(p);sha=file_digest(p);after=p.stat()
 if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('Legacy file changed during read-only fingerprint')
 rows.append([str(p.relative_to('/state/sessions')),sha]);ids.add(h['id'])
print(json.dumps({'uniqueHistories':len(ids),'sessionFiles':len(rows),'aggregateSHA256':hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()}))
'''
    return json.loads(command('exec', '-i', '-n', 'llm', 'deploy/dsh-secure', '--', 'python3', '-', data=code))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone(timedelta(hours=7)))
    ns = 'dsh-iso-' + now.strftime('%Y%m%d-%H%M%S')
    args.output.mkdir(parents=True, exist_ok=False)
    record = {'namespace': ns, 'timeICT': now.isoformat(), 'scope': 'Disposable users and synthetic data only',
              'productionRoutingChanged': False, 'legacyHistoriesMigrated': False}
    (args.output / 'namespace.txt').write_text(ns)
    record['legacyBefore'] = legacy_fingerprint()
    if record['legacyBefore']['uniqueHistories'] != 80:
        raise RuntimeError('Legacy baseline differs from the requested 80; review without modifying it')
    deployed = json.loads(command('get', 'deploy', 'dsh-secure', '-n', 'llm', '-o', 'json'))
    image = deployed['spec']['template']['spec']['containers'][0]['image']
    docs = build(ns, image)
    workload_names = [d['metadata']['name'] for d in docs if d['kind'] == 'Deployment']
    runtimes = [n for n in workload_names if n != 'dsh-environment-gateway']
    record['image'] = image
    record['syntheticUsers'] = list(USERS)
    record['legacyBaselineExpected'] = 80
    record['candidateManifestsSHA256'] = hashlib.sha256(json.dumps(docs, sort_keys=True).encode()).hexdigest()

    def k(*a, data=None):
        return command('-n', ns, *a, data=data)

    def apply(doc):
        if doc['kind'] == 'Namespace':
            assert doc['metadata']['name'] == ns
        elif doc['kind'] == 'PersistentVolume':
            assert doc['metadata']['name'] in {ns + '-pv', ns + '-source-pv'}
        else:
            assert doc['metadata']['namespace'] == ns
        return command('apply', '-f', '-', data=json.dumps(doc))

    def wait_deployments(names):
        for _ in range(160):
            ready = True
            for name in names:
                d = json.loads(k('get', 'deploy', name, '-o', 'json'))
                ready &= d.get('status', {}).get('observedGeneration', 0) >= d['metadata']['generation'] and d.get('status', {}).get('availableReplicas') == 1
            if ready:
                return
            time.sleep(3)
        raise RuntimeError('Candidate deployments did not become available; inspect the isolated namespace')

    def exec_python(name, code):
        return json.loads(k('exec', '-i', 'deploy/' + name, '--', 'python3', '-', data=code))

    probe = subprocess.run(['kubectl', 'get', 'namespace', ns, '-o', 'name'], text=True, capture_output=True)
    if probe.returncode == 0 or 'NotFound' not in probe.stderr:
        raise RuntimeError('Expected a nonexistent fresh test namespace')
    apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns, 'labels': {'dsh.bot.or.th/synthetic-test': 'true'}}})
    try:
        # The only copied Production secret field is the existing internal
        # inference key. It is never persisted in local or Git evidence.
        existing = json.loads(command('get', 'secret', 'dsh-runtime-secrets', '-n', 'llm', '-o', 'json'))
        apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'dsh-runtime-secrets', 'namespace': ns},
               'data': {'litellm-api-key': existing['data']['litellm-api-key']}})
        users = {u: secrets.token_hex(32) for u in USERS}
        apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'synthetic-identities', 'namespace': ns},
               'stringData': {'users.json': json.dumps(users)}})
        del users, existing
        apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'canary-scripts', 'namespace': ns},
               'data': {'report_server.py': (ROOT / 'scripts/isolation_canary_report_server.py').read_text(),
                        'gateway_probe.js': (ROOT / 'scripts/isolation_canary_gateway_probe.js').read_text(),
                        'auth_proxy.js': (ROOT / 'scripts/auth_proxy.js').read_text(encoding='utf-8')}})
        for d in docs:
            if d['kind'] not in {'Deployment', 'Service'}:
                apply(d)
        # This operator-only initializer sees the share root just long enough
        # to create new synthetic paths. No Harness runs with this mount.
        prefix = 'dsh-isolation-tests/' + ns
        seed = """from pathlib import Path
import json
root=Path('/central')/PREFIX
root.mkdir(parents=True,exist_ok=False)
(root/'source').mkdir();(root/'source/records.csv').write_text('case_id,amount\\nSYNTH_001,100\\nSYNTH_002,200\\n')
(root/'outside-source.txt').write_text('SYNTHETIC_OUTSIDE_APPROVED_SOURCE')
for owner in OWNERS:
 (root/'private'/owner/'secure').mkdir(parents=True)
 for directory in DIRECTORIES:(root/'private'/owner/'state'/directory).mkdir(parents=True)
print(json.dumps({'syntheticSourceSeeded':True,'productionTreeTouched':False}))
""".replace('PREFIX', repr(prefix)).replace('OWNERS', repr([identity(u) for u in USERS])).replace('DIRECTORIES', repr(DURABLE))
        job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': 'synthetic-initialize', 'namespace': ns},
            'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 300, 'template': {'metadata': {'labels': {'dsh.bot.or.th/egress-mode': 'offline'}},
            'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'runAsNonRoot': True, 'fsGroup': 10001},
                'containers': [{'name': 'seed', 'image': image, 'command': ['python3', '-c', seed],
                    'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
                    'volumeMounts': [{'name': 'central', 'mountPath': '/central'}]}],
                'volumes': [{'name': 'central', 'persistentVolumeClaim': {'claimName': 'synthetic-central'}}]}}}}
        apply(job)
        for _ in range(100):
            status = json.loads(k('get', 'job', 'synthetic-initialize', '-o', 'json')).get('status', {})
            if status.get('failed'):
                raise RuntimeError('Synthetic initialization failed')
            if status.get('succeeded'):
                break
            time.sleep(3)
        else:
            raise RuntimeError('Synthetic initialization did not finish')
        record['initialization'] = json.loads(k('logs', 'job/synthetic-initialize'))
        k('delete', 'job', 'synthetic-initialize', '--wait=true', '--timeout=60s')
        for d in docs:
            if d['kind'] in {'Deployment', 'Service'}:
                apply(d)
        print(json.dumps({'phase': 'candidate resources created', 'namespace': ns, 'runtimeCount': 4}), flush=True)
        wait_deployments(workload_names)
        for name in runtimes:
            data = exec_python(name, """from pathlib import Path
import os,json
owner=os.environ['CANARY_IDENTITY'];mode=os.environ['CANARY_ENVIRONMENT'];run=RUN
values={'/workspace/private-report.txt':'PRIVATE_REPORT_'+owner+'_'+mode+'_'+run,
 '/state/attachments/private-attachment.txt':'PRIVATE_ATTACHMENT_'+owner+'_'+mode+'_'+run}
for directory in ['storages','workspaces','logs']:values['/state/'+directory+'/persistence.txt']='PRIVATE_STATE_'+owner+'_'+mode+'_'+run
for file,value in values.items():
 p=Path(file);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
print(json.dumps({'identity':owner,'environment':mode,'privateFixtureFiles':len(values)}))
""".replace('RUN', repr(ns)))
            record.setdefault('fixtures', []).append(data)
        result = json.loads(k('exec', 'deploy/dsh-environment-gateway', '--', 'node', '/synthetic-tests/gateway_probe.js', 'create'))
        record['beforeRestart'] = result
        (args.output / 'progress.json').write_text(json.dumps(record, indent=2))
        print(json.dumps({'phase': 'authenticated isolation checks passed', 'result': result}), flush=True)
        # Test each execution worker in place; do not co-mount its live local PVC.
        record['workerTests'] = []
        for name in runtimes:
            own = json.loads(k('get', 'deploy', name, '-o', 'json'))
            owner = own['spec']['template']['metadata']['labels']['dsh.bot.or.th/owner']
            mode = 'secure' if name.endswith('-secure') else 'internet'
            other = next(n for n in runtimes if n.endswith('-' + mode) and owner not in n)
            peer = json.loads(k('get', 'pods', '-l', 'app=' + other, '-o', 'json'))['items'][0]['status']['podIP']
            code = """from pathlib import Path
import os,json,csv,hashlib,subprocess,urllib.request
mode=os.environ['CANARY_ENVIRONMENT'];r={'environment':mode,'identity':os.environ['CANARY_IDENTITY'],'uid':os.getuid()}
r['noServiceAccountToken']=not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()
r['legacyHistoryTreeAbsent']=not Path('/workspace/dsh_storage/sessions').exists()
r['neighborWorkspaceAbsent']=not Path('/workspace/../'+OTHER+'/secure/private-report.txt').exists()
r['noEffectiveCapabilities']=next(s.split()[1] for s in Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:'))=='0000000000000000'
assert r['uid']==10001 and r['noServiceAccountToken'] and r['legacyHistoryTreeAbsent'] and r['neighborWorkspaceAbsent'] and r['noEffectiveCapabilities']
if mode=='secure':
 source=Path('/data/rdt/records.csv');before=hashlib.sha256(source.read_bytes()).hexdigest();rows=list(csv.DictReader(source.open()));assert sum(int(x['amount']) for x in rows)==300
 denied=[]
 for operation in ['append','delete','create']:
  try:
   if operation=='append':
    with source.open('a') as f:f.write('UNEXPECTED_WRITE')
   elif operation=='delete':source.unlink()
   else:Path('/data/rdt/new.txt').write_text('UNEXPECTED_WRITE')
  except OSError as e:denied.append({'operation':operation,'errno':e.errno})
 assert len(denied)==3 and all(x['errno'] in [13,30] for x in denied)
 assert hashlib.sha256(source.read_bytes()).hexdigest()==before
 assert not Path('/data/rdt/../outside-source.txt').exists()
 r.update({'syntheticRows':len(rows),'syntheticAmountTotal':300,'sourceWritesDenied':denied,'sourceHashUnchanged':True,'outsideSourceAbsent':True})
else:
 r['noRdtMount']=not Path('/data/rdt').exists();assert r['noRdtMount']
probe=subprocess.run(['curl','--max-time','3','-s','-o','/dev/null','-w','%{http_code}','https://github.com'],capture_output=True,text=True)
r['publicHTTPS']={'exitCode':probe.returncode,'status':probe.stdout}
assert (probe.returncode!=0 and probe.stdout=='000') if mode=='secure' else probe.stdout=='200'
try:
 urllib.request.urlopen('http://'+PEER+':8081/report',timeout=3).read();r['peerNetworkDenied']=False
except Exception:r['peerNetworkDenied']=True
assert r['peerNetworkDenied']
print(json.dumps(r))
""".replace('OTHER', repr(identity(next(u for u in USERS if identity(u) != owner)))).replace('PEER', repr(peer))
            record['workerTests'].append(exec_python(name, code))
        record['podUIDsBefore'] = {n: json.loads(k('get', 'pods', '-l', 'app=' + n, '-o', 'json'))['items'][0]['metadata']['uid'] for n in runtimes}
        for name in runtimes:
            k('rollout', 'restart', 'deploy/' + name)
        wait_deployments(runtimes)
        record['podUIDsAfter'] = {n: json.loads(k('get', 'pods', '-l', 'app=' + n, '-o', 'json'))['items'][0]['metadata']['uid'] for n in runtimes}
        if any(record['podUIDsBefore'][n] == record['podUIDsAfter'][n] for n in runtimes):
            raise RuntimeError('Candidate process replacement was not established')
        record['afterRestart'] = json.loads(k('exec', 'deploy/dsh-environment-gateway', '--', 'node', '/synthetic-tests/gateway_probe.js', 'verify'))
        record['legacyAfter'] = legacy_fingerprint()
        record['legacyByteIdentical'] = record['legacyBefore'] == record['legacyAfter']
        if not record['legacyByteIdentical']:
            raise RuntimeError('Legacy fingerprint changed; do not restore or overwrite user work. Investigate concurrent activity.')
        record['status'] = 'passed'
        print(json.dumps({'phase': 'candidate restart and legacy preservation checks passed', 'namespace': ns}), flush=True)
    except BaseException as error:
        record['status'] = 'failed'
        record['failure'] = str(error)
        raise
    finally:
        cleanup = {'candidateDeploymentsStopped': False, 'temporarySecretsRemoved': False}
        try:
            command('-n', ns, 'delete', 'job', 'synthetic-initialize', '--ignore-not-found=true', '--wait=true', '--timeout=60s', check=False)
            for name in workload_names:
                command('-n', ns, 'scale', 'deploy/' + name, '--replicas=0', check=False)
            for _ in range(60):
                pods = json.loads(k('get', 'pods', '-o', 'json'))['items']
                if not pods:
                    break
                time.sleep(2)
            cleanup['candidateDeploymentsStopped'] = all(d['spec']['replicas'] == 0 for d in json.loads(k('get', 'deploy', '-o', 'json'))['items'])
            cleanup['candidatePodsTerminated'] = not json.loads(k('get', 'pods', '-o', 'json'))['items']
            for name in ['synthetic-identities', 'dsh-runtime-secrets']:
                k('delete', 'secret', name, '--ignore-not-found=true')
            remaining_secrets = {s['metadata']['name'] for s in json.loads(k('get', 'secret', '-o', 'json'))['items']}
            cleanup['temporarySecretsRemoved'] = not remaining_secrets.intersection({'synthetic-identities', 'dsh-runtime-secrets'})
        finally:
            if 'legacyAfter' not in record:
                try:
                    record['legacyAfter'] = legacy_fingerprint()
                    record['legacyByteIdentical'] = record['legacyBefore'] == record['legacyAfter']
                except Exception as error:
                    record['legacyVerificationError'] = str(error)
            record['cleanup'] = cleanup
            record['syntheticVolumesRetained'] = True
            record['credentialValuesExported'] = False
            (args.output / 'result.json').write_text(json.dumps(record, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
