"""Change only guarded model-group 429 retries, retaining exact gateway rollback."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import yaml
from promote_1m_runtimes import kube
from promote_1m_proxy import configure_admission_retries, wait_available
from stress_live_inference import snapshot


PROBE = r'''
import json,os,urllib.request
body={'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':'Reply exactly ADMISSION_POLICY_OK'}],'max_tokens':32,'temperature':0}
r=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
with urllib.request.urlopen(r,timeout=45) as response:
 v=json.load(response);assert v['choices'][0]['message']['content'].strip()=='ADMISSION_POLICY_OK'
print(json.dumps({'exactInference':True}))
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--rollback-dir', type=Path, required=True)
    ap.add_argument('--probe-pod', required=True)
    a = ap.parse_args()
    old = json.loads(kube('get', 'deploy', 'litellm', '-o', 'json'))
    if old['spec']['replicas'] != 1:
        raise RuntimeError('Single gateway required')
    volume = next(v for v in old['spec']['template']['spec']['volumes'] if v['name'] == 'config')
    cm = json.loads(kube('get', 'cm', volume['configMap']['name'], '-o', 'json'))
    data = copy.deepcopy(cm['data'])
    config = yaml.safe_load(data['config.yaml'])
    groups = configure_admission_retries(config)
    data['config.yaml'] = yaml.safe_dump(config, sort_keys=False)
    name = 'litellm-admission-'+hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
    print(json.dumps({'guardedGroups': groups, 'rateLimitRetries': 0, 'configMap': name}), flush=True)
    if not a.apply:
        return
    state = snapshot()
    if state['metrics'].get('sglang:num_running_reqs', 1) or state['metrics'].get('sglang:num_queue_reqs', 1):
        raise RuntimeError('Shared model busy; defer handover')
    lease_probe = "import fcntl,os;p='/tmp/dsh-long-admission/active.lock';fd=os.open(p,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd);print('idle')"
    assert kube('exec', 'deploy/litellm', '-c', 'context-forwarder', '--', 'python', '-c', lease_probe).strip() == 'idle'
    a.rollback_dir.mkdir(parents=True, exist_ok=False)
    (a.rollback_dir/'deployment.private.json').write_text(json.dumps(old))
    (a.rollback_dir/'configmap.private.json').write_text(json.dumps(cm))
    new = copy.deepcopy(old['spec'])
    new['strategy'] = {'type': 'Recreate', 'rollingUpdate': None}
    next(v for v in new['template']['spec']['volumes'] if v['name'] == 'config')['configMap']['name'] = name
    obj = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True, 'metadata': {'name': name}, 'data': data}
    kube('apply', '-f', '-', source=json.dumps(obj))
    current = json.loads(kube('get', 'deploy', 'litellm', '-o', 'json'))
    if current['spec'] != old['spec']:
        raise RuntimeError('Gateway changed during preparation; preserve concurrent edits')
    try:
        kube('patch', 'deploy', 'litellm', '--type=merge', '-p', json.dumps({'spec': new}))
        wait_available(240)
        code = "import yaml,json;from pathlib import Path;x=yaml.safe_load(Path('/etc/litellm/config.yaml').read_text());print(json.dumps(x['router_settings']['model_group_retry_policy']))"
        actual = json.loads(kube('exec', 'deploy/litellm', '-c', 'litellm', '--', 'python', '-c', code))
        assert all(actual[n]['RateLimitErrorRetries'] == 0 for n in groups)
        live = json.loads(kube('get', 'deploy', 'litellm', '-o', 'json'))
        assert live['spec']['strategy'] == {'type': 'Recreate'}
        result = json.loads(kube('exec', '-i', a.probe_pod, '--', 'python3', '-', source=PROBE))
        assert snapshot()['pods'] == state['pods']
        result.update({'configMap': name, 'guardedGroups': groups, 'policy': actual,
                       'modelUnchanged': True, 'rollbackApplied': False})
        (a.rollback_dir/'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    except Exception:
        kube('patch', 'deploy', 'litellm', '--type=merge', '-p', json.dumps({'spec': old['spec']}))
        wait_available(240)
        raise


if __name__ == '__main__':
    main()
