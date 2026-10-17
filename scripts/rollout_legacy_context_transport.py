"""Attach the qualified exact-budget transport to owner-only legacy workers.

This prepares the persistent workload specification. Run the normal private
owner login/history/terminal and durable-file checks before qualifying rollout.
No credential, profile, auth-container, mount migration or GPU change is made.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from rollout_managed_budget import SNAPSHOT

ROOT = Path(__file__).resolve().parents[1]


def candidate(original, config_map):
    spec = copy.deepcopy(original['spec'])
    if spec['replicas'] != 1 or spec['strategy']['type'] != 'Recreate':
        raise ValueError('Single-writer Recreate deployment required')
    pod = spec['template']['spec']
    worker = next(c for c in pod['containers'] if c['name'] == 'dsh')
    if '@sha256:' not in worker['image']:
        raise ValueError('Pinned application image required')
    name, target = 'context-transport', '/context-runtime'
    if any(m['mountPath'] == target for m in worker['volumeMounts']):
        raise ValueError('Existing transport must be reviewed, not replaced')
    if any(v['name'] == name for v in pod['volumes']):
        raise ValueError('Existing transport volume requires explicit review')
    options = next((e for e in worker.get('env', []) if e['name'] == 'NODE_OPTIONS'), None)
    if options and (options.get('value') or 'valueFrom' in options):
        raise ValueError('Existing Node loader requires explicit composition')
    pod['volumes'].append({'name': name, 'configMap': {'name': config_map}})
    worker['volumeMounts'].append({'name': name, 'mountPath': target, 'readOnly': True})
    worker['env'] = [e for e in worker.get('env', [])
                     if e['name'] not in ['NODE_OPTIONS', 'DSH_MANAGED_TRANSPORT']]
    worker['env'] += [
        {'name': 'NODE_OPTIONS', 'value': '--require /context-runtime/managed_inference_transport.cjs'},
        {'name': 'DSH_MANAGED_TRANSPORT', 'value': '1'},
    ]
    return spec


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '-n', 'llm', '--request-timeout=30s', *args],
                       input=data, text=True, encoding='utf-8', capture_output=True, timeout=200)
    if p.returncode:
        raise RuntimeError(p.stderr[-400:])
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', choices=['dsh-user2', 'dsh3'], required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    source = (ROOT/'scripts/managed_inference_transport.cjs').read_text(encoding='utf-8')
    digest = hashlib.sha256(source.encode()).hexdigest()
    cm = 'dsh-managed-transport-' + digest[:12]
    saved = json.loads(kube('get', 'cm', cm, '-o', 'json'))
    if saved['data']['managed_inference_transport.cjs'] != source or not saved.get('immutable'):
        raise ValueError('Qualified immutable transport source differs')
    original = json.loads(kube('get', 'deploy', args.name, '-o', 'json'))
    spec = candidate(original, cm)
    print(json.dumps({'name': args.name, 'transport': cm, 'gpuRestartRequired': False,
                      'credentialsOrProfilesChanged': False}), flush=True)
    if not args.apply:
        return
    legacy_snapshot = SNAPSHOT.replace('import http.client,json,uuid', 'import http.client,json,uuid,os')
    legacy_snapshot = legacy_snapshot.replace("h='dsh.aiportal.bot.or.th'", "h=os.environ['DSH_TRUSTED_HOST']")
    legacy_snapshot = legacy_snapshot.replace("HTTPConnection('127.0.0.1',3080", "HTTPConnection('127.0.0.1',3081")
    before = json.loads(kube('exec', '-i', 'deploy/'+args.name, '-c', 'dsh', '--',
                             'python3', '-', data=legacy_snapshot))
    if before['running']:
        raise ValueError('Active legacy agent turn; defer maintenance')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'deployment-before.private.json').write_text(json.dumps(original), encoding='utf-8')
    try:
        kube('patch', 'deploy', args.name, '--type=json', '-p', json.dumps([
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': original['metadata']['resourceVersion']},
            {'op': 'replace', 'path': '/spec', 'value': spec},
        ]))
        kube('rollout', 'status', 'deploy/'+args.name, '--timeout=180s')
        actual = kube('exec', 'deploy/'+args.name, '-c', 'dsh', '--', 'cat',
                      '/context-runtime/managed_inference_transport.cjs')
        if actual.rstrip() != source.rstrip():
            raise RuntimeError('Mounted transport source differs')
        budget = r"""import {clampMaxTokensToContext as clamp} from '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@earendil-works/pi-ai/dist/api/simple-options.js';const m={provider:'litellm-cluster',api:'openai-completions',id:'deepseek-v4.1-flash',baseUrl:'http://litellm.llm.svc.cluster.local:4000/v1',contextWindow:1048576,maxTokens:8192};const c={messages:[{role:'user',content:'x'.repeat(5600000)}]};if(clamp(m,c,8192)!==8192||clamp(m,c,1)!==1)throw Error('Installed budget hook failed');console.log(JSON.stringify({fullBudget:8192,explicitOne:1}));"""
        result = json.loads(kube('exec', 'deploy/'+args.name, '-c', 'dsh', '--',
                                'node', '--input-type=module', '-e', budget))
        after = json.loads(kube('exec', '-i', 'deploy/'+args.name, '-c', 'dsh', '--',
                               'python3', '-', data=legacy_snapshot))
        if not set(before['ids']).issubset(after['ids']):
            raise RuntimeError('Original history IDs missing after replacement')
        (args.output/'transport-result.json').write_text(json.dumps({
            'mountedSourceMatched': True, 'sourceSHA256': digest, 'budget': result,
            'originalHistoryIDsPreserved': True, 'historyCount': len(after['ids']),
            'loginAndPersistenceAcceptanceRequired': True,
        }, indent=2), encoding='utf-8')
    except BaseException:
        kube('patch', 'deploy', args.name, '--type=json', '-p',
             json.dumps([{'op': 'replace', 'path': '/spec', 'value': original['spec']}]))
        kube('rollout', 'status', 'deploy/'+args.name, '--timeout=180s')
        raise


if __name__ == '__main__':
    main()
