"""Deploy the canary-verified identity fix without touching runtime/history mounts.

Save an exact rollback specification privately. Verify actual login/logout,
history listing and terminal pages before and after; restore on failure.
"""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from run_isolation_canary import legacy_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '--request-timeout=30s', '-n', 'llm', *args],
                       input=data, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--verification-file', type=Path, default=ROOT / 'docs/context-evidence/user-isolation-canary-20261016.json')
    ap.add_argument('--admin-summary', type=Path, help='Sanitized operator snapshot for the read-only admin dashboard')
    args = ap.parse_args()
    args.output.mkdir(exist_ok=False, parents=True)
    source = (ROOT / 'scripts/auth_proxy.js').read_text(encoding='utf-8')
    password_helper = (ROOT / 'scripts/password_store.js').read_text(encoding='utf-8')
    helper_digest = hashlib.sha256(password_helper.encode()).hexdigest()
    digest = hashlib.sha256(source.encode()).hexdigest()
    evidence = json.loads(args.verification_file.read_text(encoding='utf-8'))
    if digest != evidence['gatewayOverlaySHA256'] or helper_digest != evidence.get('passwordHelperSHA256'):
        raise RuntimeError('Source differs from the live-tested canary correction')
    before = json.loads(kube('get', 'deployment', 'dsh-environment-gateway', '-o', 'json'))
    (args.output / 'gateway-before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    record = {'timeUTC': datetime.now(timezone.utc).isoformat(), 'sourceSHA256': digest,
              'runtimePoolsRestarted': False, 'modelRestarted': False,
              'legacyBefore': legacy_fingerprint()}
    probe = (ROOT / 'scripts/runtime_rollout_probe.js').read_text(encoding='utf-8')

    def run_probe(operation):
        # Temporary account values remain inside the private auth volume.
        return json.loads(kube('exec', '-i', 'deploy/dsh-environment-gateway', '--',
                              'node', '-', operation, data=probe))

    prepared = False
    changed = False
    try:
        record['prepare'] = run_probe('prepare')
        prepared = True
        record['before'] = run_probe('verify')
        name = 'dsh-gateway-source-' + hashlib.sha256((source+password_helper).encode()).hexdigest()[:12]
        cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
              'metadata': {'name': name, 'namespace': 'llm'}, 'data': {'auth_proxy.js': source, 'password_store.js': password_helper}}
        kube('apply', '-f', '-', data=json.dumps(cm))
        template = json.loads(json.dumps(before['spec']['template']))
        template['metadata'].setdefault('annotations', {})['dsh.bot.or.th/gateway-source-sha256'] = digest
        pod = template['spec']
        pod['volumes'] = [v for v in pod['volumes'] if v['name'] != 'gateway-source']
        pod['volumes'].append({'name': 'gateway-source', 'configMap': {'name': name}})
        c = pod['containers'][0]
        c['volumeMounts'] = [v for v in c['volumeMounts'] if v['name'] != 'gateway-source']
        c['volumeMounts'].append({'name': 'gateway-source', 'mountPath': '/gateway-source', 'readOnly': True})
        c['command'] = ['node', '/gateway-source/auth_proxy.js']
        if args.admin_summary:
            summary = args.admin_summary.read_text(encoding='utf-8')
            json.loads(summary)
            summary_name = 'dsh-admin-status-' + hashlib.sha256(summary.encode()).hexdigest()[:12]
            kube('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
                 'metadata': {'name': summary_name, 'namespace': 'llm'}, 'data': {'summary.json': summary}}))
            pod['volumes'] = [v for v in pod['volumes'] if v['name'] != 'admin-status']
            pod['volumes'].append({'name': 'admin-status', 'configMap': {'name': summary_name}})
            c['volumeMounts'] = [v for v in c['volumeMounts'] if v['name'] != 'admin-status']
            c['volumeMounts'].append({'name': 'admin-status', 'mountPath': '/admin-status', 'readOnly': True})
            record['adminSummaryConfigMap'] = summary_name
        changed = True
        kube('patch', 'deployment', 'dsh-environment-gateway', '--type=merge', '-p',
             json.dumps({'spec': {'template': template}}))
        kube('rollout', 'status', 'deployment/dsh-environment-gateway', '--timeout=180s')
        actual = kube('exec', 'deploy/dsh-environment-gateway', '--', 'node', '-e',
                      "console.log(require('crypto').createHash('sha256').update(require('fs').readFileSync('/gateway-source/auth_proxy.js')).digest('hex'))").strip()
        if actual != digest:
            raise RuntimeError('Running source hash mismatch')
        record['after'] = run_probe('verify')
        if args.admin_summary:
            admin_probe = (ROOT / 'scripts/verify_admin_dashboard_live.js').read_text(encoding='utf-8')
            record['adminDashboardVerification'] = json.loads(kube('exec', '-i', 'deploy/dsh-environment-gateway',
                                                                  '--', 'node', '-', data=admin_probe))
        record['legacyAfter'] = legacy_fingerprint()
        if record['legacyBefore'] != record['legacyAfter']:
            raise RuntimeError('Legacy history fingerprint changed; investigate without restoring data')
        record['runningSourceSHA256'] = actual
        record['status'] = 'passed'
        record['configMap'] = name
    except Exception as error:
        record['status'] = 'failed'
        record['error'] = str(error)
        if changed:
            # Replace rather than merge: remove overlay-only annotations and
            # volumes as well as restoring the old process command.
            kube('patch', 'deployment', 'dsh-environment-gateway', '--type=json', '-p',
                 json.dumps([{'op': 'replace', 'path': '/spec', 'value': before['spec']}]))
            kube('rollout', 'status', 'deployment/dsh-environment-gateway', '--timeout=180s')
            record['gatewaySpecificationRestored'] = True
        raise
    finally:
        if prepared:
            record['cleanup'] = run_probe('cleanup')
        (args.output / 'gateway-identity-live.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
