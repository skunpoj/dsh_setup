"""Replace only the read-only admin snapshot; preserve private routing and audit.

Requires a reviewed JSON snapshot. Verifies mounted content and the deployed
hashed-auth boundary with a temporary unmapped identity; it does not recover
passwords from salted verifiers or claim a fresh positive admin-browser login.
Restores the prior spec on regression.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '--request-timeout=30s', '-n', 'llm', *args],
                       input=data, text=True, capture_output=True, check=True)
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--snapshot', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    text = args.snapshot.read_text(encoding='utf-8')
    snapshot = json.loads(text)
    assert snapshot['observedAt'] and snapshot['environments'] and snapshot['gaps']
    args.output.mkdir(parents=True, exist_ok=False)
    original = json.loads(kube('get', 'deploy', 'dsh-environment-gateway', '-o', 'json'))
    (args.output/'gateway-before.json').write_text(json.dumps(original, indent=2), encoding='utf-8')
    name = 'dsh-admin-status-' + hashlib.sha256(text.encode()).hexdigest()[:12]
    record = {'timeUTC': datetime.now(timezone.utc).isoformat(), 'snapshotConfigMap': name,
              'runtimePoolsRestarted': False, 'modelRestarted': False}
    try:
        kube('apply', '-f', '-', data=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,
             'metadata':{'name':name,'namespace':'llm'},'data':{'summary.json':text}}))
        volumes = original['spec']['template']['spec']['volumes']
        index = next(i for i,v in enumerate(volumes) if v['name']=='admin-status')
        kube('patch','deploy','dsh-environment-gateway','--type=json','-p',json.dumps([
             {'op':'replace','path':f'/spec/template/spec/volumes/{index}/configMap/name','value':name}]))
        kube('rollout','status','deploy/dsh-environment-gateway','--timeout=180s')
        actual=json.loads(kube('exec','deploy/dsh-environment-gateway','--','cat','/admin-status/summary.json'))
        assert actual==snapshot
        verify=(ROOT/'scripts/verify_hashed_gateway_live.js').read_text(encoding='utf-8')
        record['accessVerification']=json.loads(kube('exec','-i','deploy/dsh-environment-gateway','--','node','-',data=verify))
        record['mountedContentMatches']=True
        record['positiveLiveAdminBrowserLoginVerified']=False
        record['adminRoleAndRenderingCoverage']='Separate source regression suite; not a password-derived live login'
        record['status']='passed'
    except Exception as e:
        record['status']='failed';record['error']=str(e)
        kube('patch','deploy','dsh-environment-gateway','--type=json','-p',json.dumps([
             {'op':'replace','path':'/spec','value':original['spec']}]))
        kube('rollout','status','deploy/dsh-environment-gateway','--timeout=180s')
        record['originalSpecificationRestored']=True
        raise
    finally:
        (args.output/'admin-snapshot-live.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__=='__main__':main()
