"""Prepare/promote the qualified loopback context guard; retain rollback.

Existing auth/database Secret references and unrelated routes are preserved.
The original ConfigMap is never edited. No GPU/model deployment is changed.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '-n', 'llm', '--request-timeout=30s', *args],
        input=json.dumps(data) if data is not None else None,
        text=True, encoding='utf8', capture_output=True, timeout=100)
    if p.returncode:
        raise RuntimeError(p.stderr[:350])
    return p.stdout


def candidate(original, data, image):
    if original['spec'].get('replicas') != 1:
        raise ValueError('One gateway replica is required for admission ownership')
    spec = copy.deepcopy(original['spec'])
    pod = spec['template']['spec']
    if len(pod['containers']) == 2 and pod['containers'][1]['name'] == 'context-forwarder':
        pod['containers'] = pod['containers'][:1]
    elif len(pod['containers']) != 1:
        raise ValueError('Unexpected existing sidecars; review rather than overwrite')
    config = yaml.safe_load(data['config.yaml'])
    matched = []
    for route in config['model_list']:
        if route['model_name'] not in ['deepseek-v4.1-flash', 'deepseek-flash']:
            continue
        if route['litellm_params']['model'] != 'openai/deepseek-v4.1-flash':
            raise ValueError('Canonical route no longer uses the qualified backend')
        route['litellm_params']['api_base'] = 'http://127.0.0.1:4001/v1'
        route['litellm_params']['timeout'] = 3600
        route['litellm_params']['stream_timeout'] = 3600
        route.setdefault('model_info', {})['max_input_tokens'] = 1048576
        route['model_info']['max_output_tokens'] = 8192
        matched.append(route['model_name'])
    if sorted(matched) != ['deepseek-flash', 'deepseek-v4.1-flash']:
        raise ValueError('Expected both canonical routes')
    config['litellm_settings']['callbacks'] = ['gateway_output_guard.proxy_handler_instance']
    new_data = dict(data)
    new_data['config.yaml'] = yaml.safe_dump(config, sort_keys=False)
    for name in ['gateway_output_guard.py', 'context_forwarder.py',
                 'context_envelope.py', 'long_context_callbacks.py']:
        new_data[name] = (ROOT/'scripts'/name).read_text(encoding='utf8')
    new_data['custom_callbacks.py'] = (ROOT/'scripts/litellm_custom_callbacks.py').read_text(encoding='utf8')
    digest = hashlib.sha256(json.dumps(new_data, sort_keys=True).encode()).hexdigest()
    name = 'litellm-1m-'+digest[:12]
    cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
          'metadata': {'name': name}, 'data': new_data}
    next(v for v in pod['volumes'] if v['name'] == 'config')['configMap']['name'] = name
    main = pod['containers'][0]
    main['image'] = image
    env = [e for e in main.get('env', []) if e['name'] != 'PYTHONPATH']
    main['env'] = env+[{'name': 'PYTHONPATH', 'value': '/etc/litellm'}]
    main['readinessProbe'] = {'exec': {'command': ['python', '-c',
        "import urllib.request;urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness',timeout=2).read()"]},
        'periodSeconds': 3, 'timeoutSeconds': 3, 'failureThreshold': 3}
    sidecar = {'name': 'context-forwarder', 'image': image,
        'command': ['python', '-m', 'uvicorn', 'context_forwarder:app', '--app-dir', '/etc/litellm',
                    '--host', '127.0.0.1', '--port', '4001'],
        'env': [{'name': 'PYTHONPATH', 'value': '/etc/litellm'}, {'name': 'HOME', 'value': '/tmp'}],
        'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'runAsNonRoot': True,
            'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']},
            'seccompProfile': {'type': 'RuntimeDefault'}},
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/litellm', 'readOnly': True}],
        'resources': {'requests': {'cpu': '250m', 'memory': '256Mi'},
                      'limits': {'cpu': '2', 'memory': '2Gi'}},
        'readinessProbe': {'exec': {'command': ['python', '-c',
            "import json,urllib.request;s=json.load(urllib.request.urlopen('http://127.0.0.1:4001/health',timeout=2));assert s['context']==1048576 and s['finalWireGuard']"]},
            'periodSeconds': 3, 'timeoutSeconds': 3, 'failureThreshold': 3}}
    pod['containers'].append(sidecar)
    pod['automountServiceAccountToken'] = False
    spec['template']['metadata'].setdefault('annotations', {})['dsh.bot.or.th/context-policy'] = digest
    return spec, cm, digest


def wait_available(timeout=180):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        d = json.loads(kube('get', 'deploy', 'litellm', '-o', 'json'))
        if (d['status'].get('observedGeneration', 0) >= d['metadata']['generation']
                and d['status'].get('availableReplicas') == 1
                and d['status'].get('updatedReplicas') == 1
                and d['status'].get('readyReplicas') == 1
                and d['status'].get('replicas') == 1):
            return d
        time.sleep(3)
    raise RuntimeError('Gateway did not become available')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--acceptance', type=Path)
    ap.add_argument('--rollback-dir', type=Path, required=True)
    args = ap.parse_args()
    original = json.loads(kube('get', 'deploy', 'litellm', '-o', 'json'))
    cm_name = next(v for v in original['spec']['template']['spec']['volumes'] if v['name'] == 'config')['configMap']['name']
    data = json.loads(kube('get', 'cm', cm_name, '-o', 'json'))['data']
    pods = json.loads(kube('get', 'pods', '-l', 'app=litellm', '-o', 'json'))['items']
    if len(pods) != 1:
        raise RuntimeError('Gateway is already rolling; defer')
    image = pods[0]['status']['containerStatuses'][0]['imageID'].removeprefix('docker-pullable://')
    spec, cm, digest = candidate(original, data, image)
    plan = {'configMap': cm['metadata']['name'], 'image': image,
            'context': 1048576, 'output': 8192, 'sha256': digest,
            'loopbackOnly': True, 'productionCaptureEnabled': False}
    if not args.apply:
        print(json.dumps(plan))
        return
    if not args.acceptance:
        raise ValueError('Actual DSH near-1M acceptance record required')
    evidence = json.loads(args.acceptance.read_text(encoding='utf8'))
    result = evidence.get('result', {})
    if not (evidence.get('status') == 'passed' and evidence.get('modelUnchanged')
            and result.get('expectedTextPresent') and result.get('persistedPromptMatches')
            and result.get('lastUsage', {}).get('inputTokens', 0) >= 1000000):
        raise ValueError('Near-1M actual-content acceptance is not satisfied')
    args.rollback_dir.mkdir(parents=True, exist_ok=False)
    (args.rollback_dir/'deployment-before.json').write_text(json.dumps(original, indent=2), encoding='utf8')
    kube('apply', '-f', '-', data=cm)
    current = json.loads(kube('get', 'deploy', 'litellm', '-o', 'json'))
    if current['spec'] != original['spec']:
        raise RuntimeError('Gateway changed after plan; preserve concurrent edits')
    try:
        kube('patch', 'deploy', 'litellm', '--type=merge', '-p', json.dumps({'spec': spec}))
        live = wait_available()
        live_cm = json.loads(kube('get', 'cm', cm['metadata']['name'], '-o', 'json'))
        if live_cm['data'] != cm['data']:
            raise RuntimeError('Persisted configuration differs')
        if next(v for v in live['spec']['template']['spec']['volumes'] if v['name'] == 'config')['configMap']['name'] != cm['metadata']['name']:
            raise RuntimeError('Wrong mounted configuration')
        probe = r'''
import json,os,time,urllib.request,urllib.error
url='http://litellm.llm.svc.cluster.local:4000/v1/chat/completions'
body={'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':'Reply exactly LIVE_PROXY_1M_OK.'}],'max_tokens':32,'temperature':0}
def call(data):
 req=urllib.request.Request(url,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
 return json.load(urllib.request.urlopen(req,timeout=30))
start=time.monotonic();value=call(body);exact=value['choices'][0]['message']['content'].strip()=='LIVE_PROXY_1M_OK'
negative=None
try:call({**body,'api_base':'http://127.0.0.1:9/v1'})
except urllib.error.HTTPError as e:
 text=e.read().decode();negative=e.code in (400,401) and any(x in text for x in ['Managed context route','api_base is not allowed'])
print(json.dumps({'exact':exact,'seconds':round(time.monotonic()-start,3),'endpointOverrideRejected':negative}))
assert exact and negative
'''
        response = subprocess.run(['kubectl', '-n', 'llm', 'exec', '-i', 'deploy/dsh-secure', '--', 'python3', '-'],
            input=probe, text=True, encoding='utf8', capture_output=True, timeout=80)
        if response.returncode:
            raise RuntimeError('Actual inference/managed-route check failed: '+response.stdout[:200])
        checked = json.loads(response.stdout)
        if not checked.get('exact') or not checked.get('endpointOverrideRejected'):
            raise RuntimeError('Actual response differs from acceptance')
        plan['deployed'] = True
        plan['actualInference'] = checked
        plan['note'] = 'Actual inference and endpoint-override rejection passed; DSH profile rollout is separate.'
        (args.rollback_dir/'applied.json').write_text(json.dumps(plan, indent=2), encoding='utf8')
        print(json.dumps(plan))
    except Exception:
        kube('patch', 'deploy', 'litellm', '--type=merge', '-p', json.dumps({'spec': original['spec']}))
        wait_available()
        print(json.dumps({'rolledBack': True, 'originalConfigMapRetained': cm_name}))
        raise


if __name__ == '__main__':
    main()
