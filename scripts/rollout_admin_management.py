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
    args = ap.parse_args()

    def kube(*parts, data=None):
        p = subprocess.run(['kubectl', '-n', args.namespace, '--request-timeout=30s', *parts],
                           input=data, text=True, encoding='utf-8', capture_output=True, timeout=180)
        if p.returncode:
            raise RuntimeError(p.stderr[-500:])
        return p.stdout

    source = (ROOT/'scripts/auth_proxy.js').read_text(encoding='utf-8')
    helper = (ROOT/'scripts/password_store.js').read_text(encoding='utf-8')
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    print(json.dumps({'apply': args.apply, 'sourceSHA256': source_hash, 'gatewayOnly': True}), flush=True)
    if not args.apply:
        return
    args.output.mkdir(parents=True, exist_ok=False)
    before = json.loads(kube('get', 'deploy', args.deployment, '-o', 'json'))
    (args.output/'deployment-before.private.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    read_hash = "console.log(require('crypto').createHash('sha256').update(require('fs').readFileSync('/gateway-source/auth_proxy.js')).digest('hex'))"
    if kube('exec', 'deploy/'+args.deployment, '--', 'node', '-e', read_hash).strip() != args.expected_source_sha256:
        raise RuntimeError('Live gateway changed; review before replacing')
    store_probe = "const f=require('fs'),c=require('crypto'),u=JSON.parse(f.readFileSync(process.env.DSH_USER_STORE_PATH));console.log(JSON.stringify({count:Object.keys(u).length,hash:c.createHash('sha256').update(JSON.stringify(Object.keys(u).sort().map(k=>[k,u[k]]))).digest('hex')}))"
    def store():
        return json.loads(kube('exec', 'deploy/'+args.deployment, '--', 'node', '-e', store_probe))
    original_store = store()
    record = {'timeUTC': datetime.now(timezone.utc).isoformat(), 'gatewaySourceSHA256': source_hash,
              'modelOrRuntimeRestartRequested': False, 'beforeAccounts': original_store['count']}
    changed = False
    try:
        name = 'dsh-gateway-users-'+source_hash[:12]
        kube('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
             'metadata': {'name': name}, 'data': {'auth_proxy.js': source, 'password_store.js': helper}}))
        template = json.loads(json.dumps(before['spec']['template']))
        for volume in template['spec']['volumes']:
            if volume['name'] == 'gateway-source':
                volume['configMap']['name'] = name
        template.setdefault('metadata', {}).setdefault('annotations', {})['dsh.bot.or.th/gateway-source-sha256'] = source_hash
        changed = True
        kube('patch', 'deploy', args.deployment, '--type=merge', '-p', json.dumps({'spec': {
             'strategy': {'type': 'Recreate', 'rollingUpdate': None}, 'template': template}}))
        kube('rollout', 'status', 'deploy/'+args.deployment, '--timeout=150s')
        if kube('exec', 'deploy/'+args.deployment, '--', 'node', '-e', read_hash).strip() != source_hash:
            raise RuntimeError('Mounted source differs')
        if store() != original_store:
            raise RuntimeError('Account content changed unexpectedly; preserve current store and investigate')
        probe = (ROOT/'scripts/verify_hashed_gateway_live.js').read_text(encoding='utf-8')
        record['liveAuthChecks'] = json.loads(kube('exec', '-i', 'deploy/'+args.deployment, '--', 'node', '-', data=probe))
        if store() != original_store:
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
