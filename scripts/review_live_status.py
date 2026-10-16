"""Collect bounded configuration/behavior evidence without exporting secrets."""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def kube(*args, data=None):
    p = subprocess.run(['kubectl', '--request-timeout=30s', '-n', 'llm', *args],
                       input=data, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout


RUNTIME = r'''
import concurrent.futures,json,os,subprocess
targets={'/workspace','/state','/state/sessions','/state/attachments','/state/storages','/state/workspaces','/state/logs','/packages/approved'}
mounts=[]
for line in open('/proc/self/mountinfo'):
 fields=line.split();separator=fields.index('-')
 if fields[4] in targets:mounts.append({'target':fields[4],'filesystem':fields[separator+1],
 'source':fields[separator+2],'mountRoot':fields[3],'options':fields[5]})
def connect(url):
 p=subprocess.run(['curl','--silent','--output','/dev/null','--max-time','6','--write-out','%{http_code}',url],capture_output=True,text=True)
 return {'url':url,'exitCode':p.returncode,'HTTP':p.stdout}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 network=list(pool.map(connect,['https://github.com','https://pypi.org','https://registry.npmjs.org']))
print(json.dumps({'uid':os.getuid(),'serviceAccountTokenMounted':os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'),
 'mounts':mounts,'network':network,'rdtSourceMounted':os.path.exists('/data/rdt')}))
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    record = {'timeUTC': datetime.now(timezone.utc).isoformat(), 'deployments': {}, 'runtimes': {}}
    for name in ['dsh-environment-gateway', 'dsh-secure', 'dsh-internet', 'dsh-user2', 'dsh3',
                 'litellm', 'vllm-deepseek-v4-1-flash']:
        d = json.loads(kube('get', 'deploy', name, '-o', 'json'))
        pod = d['spec']['template']['spec']
        row = {'desired': d['spec']['replicas'], 'ready': d.get('status', {}).get('readyReplicas', 0),
               'image': pod['containers'][0]['image'], 'annotations': d['spec']['template']['metadata'].get('annotations', {}),
               'volumes': pod.get('volumes', []), 'mounts': pod['containers'][0].get('volumeMounts', []),
               'securityContext': pod['containers'][0].get('securityContext', {}),
               'automountServiceAccountToken': pod.get('automountServiceAccountToken', 'default'),
               'resources': pod['containers'][0].get('resources', {})}
        if name == 'vllm-deepseek-v4-1-flash':
            row['arguments'] = pod['containers'][0]['args']
        if name == 'dsh-environment-gateway':
            row['command'] = pod['containers'][0].get('command')
            row['userRoutingConfigured'] = any(e['name'] == 'DSH_USER_TARGETS_FILE' for e in pod['containers'][0].get('env', []))
        record['deployments'][name] = row
    for name in ['dsh-secure', 'dsh-internet', 'dsh-user2', 'dsh3']:
        record['runtimes'][name] = json.loads(kube('exec', '-i', 'deploy/' + name, '--', 'python3', '-', data=RUNTIME))
    policies = json.loads(kube('get', 'networkpolicy', '-o', 'json'))
    record['networkPolicies'] = [{'name': p['metadata']['name'], 'spec': p['spec']} for p in policies['items']]
    cm = json.loads(kube('get', 'configmap', 'litellm-config', '-o', 'json'))
    # Parse only public limits/routes. Never export the full ConfigMap.
    import yaml
    record['liteLLM'] = []
    for text in cm.get('data', {}).values():
        try:
            cfg = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if not isinstance(cfg, dict) or 'model_list' not in cfg:
            continue
        for m in cfg['model_list']:
            if 'deepseek' not in str(m.get('model_name', '')).lower():
                continue
            info = m.get('model_info', {})
            record['liteLLM'].append({'model': m.get('model_name'),
                 'maxTokens': info.get('max_tokens'), 'maxInputTokens': info.get('max_input_tokens'),
                 'maxOutputTokens': info.get('max_output_tokens'),
                 'endpoint': m.get('litellm_params', {}).get('api_base')})
        record['fallbackConfigured'] = bool(cfg.get('litellm_settings', {}).get('fallbacks') or cfg.get('router_settings', {}).get('fallbacks'))
    args.output.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps({'saved': str(args.output), 'runtimeCount': len(record['runtimes']),
                      'gatewayPrivateUserRouting': record['deployments']['dsh-environment-gateway']['userRoutingConfigured']}))


if __name__ == '__main__':
    main()
