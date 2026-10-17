"""Apply only the reviewed shared forwarder scheduling source; retain rollback.

No model restart, user profile, route, storage or network change. Run only after
owned long work has completed. Single replica/Recreate remains required.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ['context_forwarder.py', 'long_context_callbacks.py']


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '--request-timeout=30s', '-n', 'llm', *args],
                       input=data, text=True, encoding='utf-8', capture_output=True, timeout=200)
    if p.returncode:
        raise RuntimeError(p.stderr[-350:])
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--expected-forwarder-sha', required=True)
    ap.add_argument('--expected-callback-sha', required=True)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    deployment = json.loads(kube('get', 'deploy', 'litellm', '-o', 'json'))
    assert deployment['spec']['replicas'] == 1
    assert deployment['spec']['strategy']['type'] == 'Recreate'
    volumes = deployment['spec']['template']['spec']['volumes']
    index = next(i for i, v in enumerate(volumes) if v['name'] == 'config')
    old_name = volumes[index]['configMap']['name']
    old = json.loads(kube('get', 'cm', old_name, '-o', 'json'))
    expected = [args.expected_forwarder_sha, args.expected_callback_sha]
    for file, wanted in zip(FILES, expected):
        assert hashlib.sha256(old['data'][file].encode()).hexdigest() == wanted, 'Unreviewed source baseline'
    data = dict(old['data'])
    for file in FILES:
        data[file] = (ROOT/'scripts'/file).read_text(encoding='utf-8')
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    name = 'litellm-interactive-' + digest[:12]
    if not args.apply:
        print(json.dumps({'previousConfigMap': old_name, 'candidateConfigMap': name,
                          'changedFiles': FILES, 'modelRestartRequired': False}))
        return
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'deployment-before.json').write_text(json.dumps(deployment, indent=2), encoding='utf-8')
    lock = "import fcntl;f=open('/tmp/dsh-long-admission/active.lock','a+');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)"
    kube('exec', 'deploy/litellm', '-c', 'context-forwarder', '--', 'python', '-c', lock)
    cm = {'apiVersion':'v1', 'kind':'ConfigMap', 'immutable':True,
          'metadata':{'name':name,'namespace':'llm'},'data':data}
    kube('apply', '-f', '-', data=json.dumps(cm))
    path = f'/spec/template/spec/volumes/{index}/configMap/name'
    kube('patch', 'deploy', 'litellm', '--type=json', '-p', json.dumps([
        {'op':'test','path':path,'value':old_name},
        {'op':'replace','path':path,'value':name}]))
    try:
        kube('rollout', 'status', 'deploy/litellm', '--timeout=180s')
        for file in FILES:
            actual = kube('exec', 'deploy/litellm', '-c', 'context-forwarder', '--', 'cat', '/etc/litellm/'+file)
            assert actual.rstrip() == data[file].rstrip(), 'Mounted source mismatch'
        health = json.loads(kube('exec','deploy/litellm','-c','context-forwarder','--','python','-c',
            "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:4001/health').read().decode())"))
        assert health['context'] == 1048576 and health['finalWireGuard']
        result = {'passed':True,'previousConfigMap':old_name,'configMap':name,'context':health['context'],
                  'mountedSourceMatches':True,'modelRestarted':False}
    except BaseException:
        kube('patch','deploy','litellm','--type=json','-p',json.dumps([
            {'op':'test','path':path,'value':name},{'op':'replace','path':path,'value':old_name}]))
        kube('rollout','status','deploy/litellm','--timeout=180s')
        raise
    (args.output/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
