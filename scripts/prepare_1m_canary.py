"""Prepare isolated 1M LiteLLM/DSH candidates without changing live routing.

No real user histories or workspaces are mounted. Existing Secret references
are retained in Kubernetes, not exported. The four-GPU backend is unchanged.
"""
import copy
import json
import subprocess
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '-n', 'llm', '--request-timeout=30s', *args],
        input=json.dumps(data) if data is not None else None,
        text=True, capture_output=True, timeout=100)
    if p.returncode:
        raise RuntimeError(p.stderr[:400])
    return p.stdout


def apply(value):
    kube('apply', '-f', '-', data=value)


def prepare_dsh(ip):
    apply({'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': 'dsh-1m-context-source'},
        'data': {'configure_runtime_context.js': (ROOT/'scripts/configure_runtime_context.js').read_text()}})
    original = json.loads(kube('get', 'deploy', 'dsh-secure', '-o', 'json'))
    source = original['spec']['template']['spec']
    container = copy.deepcopy(source['containers'][0])
    mounts = [('state', '/state'), ('workspace', '/workspace'),
              ('tokens', '/runtime-tokens'), ('packages', '/packages/approved')]
    container['volumeMounts'] = [{'name': n, 'mountPath': p} for n, p in mounts]
    for field in ['startupProbe', 'readinessProbe', 'livenessProbe']:
        container.pop(field, None)
    seed = r"""cp -R --no-preserve=ownership,timestamps,mode /opt/dsh/seed/dsh-home/. /state/
python3 - <<'PY'
from pathlib import Path
import re
for p in Path('/state').rglob('*'):
 if not p.is_file() or p.suffix not in ['.yaml','.yml','.md']:continue
 t=p.read_text()
 t=t.replace('contextWindow: 131072','contextWindow: 1048576').replace('Verified 128K','1M candidate')
 t=t.replace('http://litellm.llm.svc.cluster.local:4000','http://CANDIDATE_IP:4000')
 t=re.sub(r'(?m)^(\s*)apiKeyEnv: DEEPSEEK_API_KEY$',r'\1apiKeyEnv: DEEPSEEK_API_KEY\n\1timeoutMs: 3600000\n\1streamIdleTimeoutMs: 3600000',t)
 t=t.replace('thresholdRatio: 0.75','thresholdRatio: 0.875\n    headroomTokens: 65536\n    maxTokens: 8192')
 p.write_text(t)
PY
node /context/configure_runtime_context.js /state 1048576
""".replace('CANDIDATE_IP', ip)
    apply({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
        'metadata': {'name': 'dsh-1m-canary'}, 'spec': {
        'podSelector': {'matchLabels': {'app': 'dsh-1m-canary'}},
        'policyTypes': ['Ingress', 'Egress'], 'ingress': [],
        'egress': [{'to': [{'podSelector': {'matchLabels': {'app': 'litellm-1m-canary'}}}],
                    'ports': [{'port': 4000, 'protocol': 'TCP'}]}]}})
    apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'dsh-1m-canary',
        'labels': {'app': 'dsh-1m-canary'}}, 'spec': {
        'automountServiceAccountToken': False, 'securityContext': source['securityContext'],
        'containers': [container], 'initContainers': [{'name': 'profile',
            'image': container['image'], 'command': ['sh', '-ec', seed],
            'securityContext': container['securityContext'],
            'volumeMounts': [{'name': 'state', 'mountPath': '/state'},
                {'name': 'context-source', 'mountPath': '/context', 'readOnly': True}]}],
        'volumes': [{'name': n, 'emptyDir': {}} for n, _ in mounts]+
            [{'name': 'context-source', 'configMap': {'name': 'dsh-1m-context-source'}}]}})


def main():
    name = 'litellm-1m-canary'
    # Refuse an unexpected existing candidate rather than overwrite it.
    exists = kube('get', 'pod', name, '--ignore-not-found', '-o', 'name').strip()
    if exists:
        raise RuntimeError('Candidate exists; inspect it before repeating preparation')
    cm = json.loads(kube('get', 'cm', 'litellm-config', '-o', 'json'))
    config = yaml.safe_load(cm['data']['config.yaml'])
    config['model_list'] = [x for x in config['model_list']
        if x['model_name'] in ['deepseek-v4.1-flash', 'deepseek-flash']]
    for model in config['model_list']:
        model.setdefault('model_info', {})['max_input_tokens'] = 1048576
        model['litellm_params']['api_base'] = 'http://127.0.0.1:4001/v1'
    config['litellm_settings']['callbacks'] = ['gateway_output_guard.proxy_handler_instance']
    apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name},
        'data': {'config.yaml': yaml.safe_dump(config),
                 'custom_callbacks.py': cm['data']['custom_callbacks.py'],
                 'gateway_output_guard.py': (ROOT/'scripts/gateway_output_guard.py').read_text(),
                 'context_forwarder.py': (ROOT/'scripts/context_forwarder.py').read_text(),
                 'context_envelope.py': (ROOT/'scripts/context_envelope.py').read_text(),
                 'long_context_callbacks.py': (ROOT/'scripts/long_context_callbacks.py').read_text()}})
    original = json.loads(kube('get', 'deploy', 'litellm', '-o', 'json'))
    spec = copy.deepcopy(original['spec']['template']['spec'])
    spec['automountServiceAccountToken'] = False
    spec['volumes'] = [{'name': 'config', 'configMap': {'name': name}}]
    container = spec['containers'][0]
    pods = json.loads(kube('get', 'pods', '-l', 'app=litellm', '-o', 'json'))['items']
    container['image'] = pods[0]['status']['containerStatuses'][0]['imageID'].removeprefix('docker-pullable://')
    for field in ['startupProbe', 'readinessProbe', 'livenessProbe']:
        container.pop(field, None)
    container['env'].append({'name': 'PYTHONPATH', 'value': '/etc/litellm'})
    spec['containers'].append({'name': 'context-forwarder', 'image': container['image'],
        'command': ['python', '-m', 'uvicorn', 'context_forwarder:app', '--app-dir', '/etc/litellm',
                    '--host', '127.0.0.1', '--port', '4001'],
        'env': [{'name': 'PYTHONPATH', 'value': '/etc/litellm'}, {'name': 'HOME', 'value': '/tmp'},
                {'name': 'DSH_CAPTURE_SYNTHETIC_ENVELOPE', 'value': '1'}],
        'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'runAsNonRoot': True,
            'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/litellm', 'readOnly': True}],
        'resources': {'requests': {'cpu': '250m', 'memory': '256Mi'},
                      'limits': {'cpu': '2', 'memory': '2Gi'}}})
    apply({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': name},
        'spec': {'podSelector': {'matchLabels': {'app': name}}, 'policyTypes': ['Ingress'],
        'ingress': [{'from': [{'podSelector': {'matchLabels': {'app': 'dsh-1m-canary'}}}],
                     'ports': [{'port': 4000, 'protocol': 'TCP'}]}]}})
    apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name,
        'labels': {'app': name}}, 'spec': spec})
    apply({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name},
        'spec': {'selector': {'app': name},
                 'ports': [{'port': 4000, 'targetPort': 4000}]}})
    for _ in range(30):
        pod = json.loads(kube('get', 'pod', name, '-o', 'json'))
        if pod.get('status', {}).get('podIP'):
            service = json.loads(kube('get', 'service', name, '-o', 'json'))
            prepare_dsh(service['spec']['clusterIP'])
            break
        time.sleep(2)
    else:
        raise RuntimeError('Candidate pod IP not assigned; inspect before retrying')
    print('Created isolated LiteLLM candidate. Production Service selectors unchanged.')


if __name__ == '__main__':
    main()
