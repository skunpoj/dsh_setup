"""Prepare exclusive, empty signup runtimes from reviewed live private templates.

Writes site-bound manifests only to an operator-supplied private directory.
No existing workload, account, workspace or history is replaced. Runtime pairs
are never automatically recycled. The login service needs no Kubernetes token.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess


def generate(templates, claims, pool_id, count):
    if not re.fullmatch(r'[a-z0-9-]{3,24}', pool_id) or not 1 <= count <= 16:
        raise ValueError('Use a bounded pool identifier and 1-16 pairs')
    if set(templates) != {'secure', 'internet'}:
        raise ValueError('Both reviewed private environments are required')
    documents, slots, paths = [], {}, []
    for index in range(1, count + 1):
        slot = f'{pool_id}-{index:02d}'
        identity = hashlib.sha256(slot.encode()).hexdigest()[:16]
        slots[slot] = {}
        for environment in ('secure', 'internet'):
            source = templates[environment]
            workload = copy.deepcopy(source)
            name = f'dsh-u-{identity}-{environment}'
            workload['metadata'] = {'name': name, 'namespace': 'llm', 'labels': {'dsh.bot.or.th/signup-pool': pool_id}}
            workload.pop('status', None)
            workload['spec']['replicas'] = 1
            workload['spec']['selector']['matchLabels'] = {'app': name}
            runtime = workload['spec']['template']
            runtime['metadata'] = {'labels': {**runtime['metadata']['labels'], 'app': name,
                'dsh.bot.or.th/owner': identity, 'dsh.bot.or.th/signup-pool': pool_id}}
            pod = runtime['spec']
            # A one-time upgrade backup belongs to the old user's populated
            # state. Fresh runtimes must seed from their pinned image instead.
            if any(c['name'] != 'context-profile-backup' for c in pod.get('initContainers', [])):
                raise ValueError('Review unexpected initialization before cloning')
            pod.pop('initContainers', None)
            if pod.get('automountServiceAccountToken') is not False:
                raise ValueError('Template must not mount a management token')
            # Runtime service approvals belong to the old private runtime. Never
            # clone its supervisor, policy/status claims or running services.
            if len(pod['containers'])==2 and {c['name']for c in pod['containers']}=={'dsh','app-supervisor'}:
                pod['containers']=[c for c in pod['containers']if c['name']=='dsh']
                private_service_volumes={'app-supervisor-source','app-service-control','app-service-status','app-supervisor-tmp'}
                if any(m['name']in private_service_volumes for m in pod['containers'][0]['volumeMounts']):raise ValueError('Supervisor control unexpectedly mounted in agent')
                pod['volumes']=[v for v in pod['volumes']if v['name']not in private_service_volumes]
            if len(pod['containers']) != 1 or pod.get('hostNetwork') or pod.get('hostPID'):
                raise ValueError('Unexpected private template')
            container = pod['containers'][0]
            if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', container['image']):
                raise ValueError('Pin the qualified image')
            for process in [container] + pod.get('initContainers', []):
                context = process.get('securityContext', {})
                if context.get('privileged') or context.get('allowPrivilegeEscalation') is not False:
                    raise ValueError('Unsafe execution template')
            if container['securityContext'].get('runAsNonRoot') is not True:
                raise ValueError('Non-root execution required')
            for env in container['env']:
                if env['name'] == 'DEEPSEEK_API_KEY':
                    env['valueFrom']['secretKeyRef']['name'] = 'dsh-inference-signup-' + identity
            for volume in pod['volumes']:
                if 'hostPath' in volume:
                    raise ValueError('No host filesystem mounts')
                if volume['name'] == 'harness-credentials':
                    volume['secret']['secretName'] = f'dsh-harness-signup-{identity}-{environment}'
                if 'persistentVolumeClaim' not in volume:
                    continue
                old = volume['persistentVolumeClaim']['claimName']
                mounts = [m for m in container['volumeMounts'] if m['name'] == volume['name']]
                if old == 'dsh-package-approved':
                    if not mounts or not all(m.get('readOnly') for m in mounts):
                        raise ValueError('Approved artifacts must be read-only')
                    continue
                if old == 'dsh-da-workspace-secure':
                    if environment != 'secure' or len(mounts) != 6:
                        raise ValueError('Unexpected central-storage template')
                    for mount in mounts:
                        if mount['mountPath'] == '/workspace':
                            suffix = 'secure'
                        elif mount['mountPath'] in ['/state/' + n for n in ['sessions', 'attachments', 'storages', 'workspaces', 'logs']]:
                            suffix = 'state/' + mount['mountPath'].split('/')[-1]
                        else:
                            raise ValueError('Unexpected central mount')
                        mount['subPath'] = f'dsh/private/{identity}/{suffix}'
                        paths.append(mount['subPath'])
                    continue
                claim = name + '-' + volume['name']
                spec = claims[old]['spec']
                new_spec = {k: copy.deepcopy(spec[k]) for k in ['accessModes', 'resources', 'storageClassName', 'volumeMode'] if k in spec}
                volume['persistentVolumeClaim']['claimName'] = claim
                documents.append({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                    'metadata': {'name': claim, 'namespace': 'llm', 'labels': {'dsh.bot.or.th/signup-pool': pool_id}}, 'spec': new_spec})
            documents.extend([workload, {'apiVersion': 'v1', 'kind': 'Service',
                'metadata': {'name': name, 'namespace': 'llm', 'labels': {'dsh.bot.or.th/signup-pool': pool_id}},
                'spec': {'clusterIP': 'None', 'selector': {'app': name}, 'ports': [
                    {'name': 'web', 'port': 3081, 'targetPort': 'web'}, {'name': 'terminal', 'port': 7681, 'targetPort': 'terminal'}]}}])
            slots[slot][environment] = {'host': name + '.llm.svc.cluster.local', 'port': 3081,
                'tokenFile': f'/runtime-tokens/signup/{identity}/{environment}/{environment}'}
    return documents, {'slots': slots}, sorted(set(paths))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--template-user', required=True)
    ap.add_argument('--pool-id', required=True)
    ap.add_argument('--count', type=int, default=6)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--image', help='Optional immutable image for acceptance-only candidate runtimes')
    ap.add_argument('--kubectl', default='kubectl')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    def kube(*parts, data=None, timeout=90):
        p = subprocess.run([args.kubectl, '-n', 'llm', '--request-timeout=30s', *parts], input=data,
            text=True, encoding='utf-8', capture_output=True, timeout=timeout)
        if p.returncode:
            raise RuntimeError(p.stderr[-500:])
        return p.stdout
    routing = json.loads(json.loads(kube('get', 'cm', 'dsh-user-routing', '-o', 'json'))['data']['users.json'])
    if args.template_user in {'admin', 'thanatcc'}:
        raise ValueError('Use an ordinary isolated runtime template, never the legacy owner')
    templates = {e: json.loads(kube('get', 'deploy', t['host'].split('.')[0], '-o', 'json')) for e, t in routing[args.template_user].items()}
    if args.image:
        if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', args.image):
            raise ValueError('Candidate image must use an immutable digest')
        for template in templates.values():
            template['spec']['template']['spec']['containers'][0]['image'] = args.image
    claims = {p['metadata']['name']: p for p in json.loads(kube('get', 'pvc', '-o', 'json'))['items']}
    documents, pool, paths = generate(templates, claims, args.pool_id, args.count)
    if any(d['metadata']['name'] in claims for d in documents if d['kind'] == 'PersistentVolumeClaim'):
        raise ValueError('A signup claim already exists; never reuse private state')
    existing = {x['metadata']['name'] for x in json.loads(kube('get', 'deploy', '-o', 'json'))['items']}
    if any(d['metadata']['name'] in existing for d in documents if d['kind'] == 'Deployment'):
        raise ValueError('A signup workload already exists; never overwrite or recycle it')
    (args.output/'runtime-manifests.private.json').write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': documents}, indent=2))
    (args.output/'pool.private.json').write_text(json.dumps(pool, indent=2))
    if not args.apply:
        print(json.dumps({'prepared': True, 'pairs': args.count, 'applied': False}));return
    import provision_inference_client
    import provision_harness_credentials
    provision_inference_client.kube = lambda *parts, data=None: kube(*parts, data=data)
    provision_harness_credentials.kube = lambda *parts, source=None: kube(*parts, data=source)
    # These helpers keep generated credentials inside cluster Secrets and never print values.
    for slot in pool['slots']:
        identity = hashlib.sha256(slot.encode()).hexdigest()[:16]
        provision_inference_client.provision('dsh-inference-signup-' + identity, ['deepseek-v4.1-flash'])
        for env in ['secure', 'internet']:
            provision_harness_credentials.provision(f'dsh-harness-signup-{identity}-{env}')
        print(json.dumps({'credentialsPreparedForSlot': slot}), flush=True)
    # Prepare only absent, new identity paths through an operator-owned short-lived job.
    code = "from pathlib import Path\nimport json\npaths=" + repr(paths) + "\nfor p in paths:\n q=Path('/central')/p\n if q.exists() and any(q.iterdir()):raise RuntimeError('Refusing a non-empty signup path')\n q.mkdir(parents=True,exist_ok=True)\nprint(json.dumps({'emptyPrivateDirectories':len(paths)}))"
    image = templates['secure']['spec']['template']['spec']['containers'][0]['image']
    job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': args.pool_id + '-init', 'namespace': 'llm'},
        'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 180, 'template': {'metadata': {'labels': {'app': 'dsh-maintenance'}},
        'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
            'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001, 'fsGroup': 10001},
            'containers': [{'name': 'initialize', 'image': image, 'command': ['python3', '-c', code],
                'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
                'volumeMounts': [{'name': 'central', 'mountPath': '/central'}]}],
            'volumes': [{'name': 'central', 'persistentVolumeClaim': {'claimName': 'dsh-da-workspace-secure'}}]}}}}
    kube('apply', '-f', '-', data=json.dumps(job))
    kube('wait', '--for=condition=complete', 'job/' + args.pool_id + '-init', '--timeout=180s', timeout=210)
    kube('delete', 'job', args.pool_id + '-init', '--wait=true')
    kube('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': documents}))
    print(json.dumps({'applied': True, 'newRuntimePairs': args.count, 'existingWorkloadsChanged': False}), flush=True)


if __name__ == '__main__':
    main()
