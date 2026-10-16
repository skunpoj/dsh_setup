"""Bounded real DSH and API requests during the owned production 1M test."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
from stress_live_inference import snapshot, REQUEST

out={'before':snapshot(),'intent':'Ordinary replies during production near-1M DSH continuation','dsh':[],'apiBursts':[]}
s="import sys;sys.argv=['probe','--deadline','90']\n"+Path(__file__).with_name('probe_dsh_1m_agent.py').read_text()
def run(i):
    p=subprocess.run(['kubectl','-n','llm','exec','-i','dsh-1m-canary','--','python3','-'],input=s,text=True,capture_output=True,timeout=100)
    if p.returncode:raise RuntimeError(p.stderr[-400:])
    return json.loads(p.stdout)
with concurrent.futures.ThreadPoolExecutor(2) as pool:out['dsh']=list(pool.map(run,range(2)))
ip=json.loads(subprocess.check_output(['kubectl','-n','llm','get','svc','litellm-1m-canary','-o','json']))['spec']['clusterIP']
for n in [2,4]:
    source=REQUEST.replace('PLAN',repr(json.dumps({'kind':'burst','concurrency':n}))).replace('http://litellm.llm.svc.cluster.local:4000',f'http://{ip}:4000')
    p=subprocess.run(['kubectl','-n','llm','exec','-i','dsh-1m-canary','--','python3','-'],input=source,text=True,capture_output=True,timeout=90)
    assert not p.returncode,p.stderr[-300:]
    value=json.loads(p.stdout);assert value['allExact'];out['apiBursts'].append(value)
out['after']=snapshot();out['modelUnchanged']=out['before']['pods']==out['after']['pods']
assert out['modelUnchanged'] and all(r['expectedTextPresent'] and r['persistedPromptMatches'] for r in out['dsh'])
Path('docs/context-evidence/production-1m-mixed-concurrency-20261016.json').write_text(json.dumps(out,indent=2))
print(json.dumps({'dshSeconds':[r['elapsedSeconds'] for r in out['dsh']],
    'bursts':[{'concurrency':v['plan']['concurrency'],'seconds':v['wallSeconds'],'aggregateTokensPerSecond':v['aggregateOutputTokensPerSecond']} for v in out['apiBursts']],
    'modelUnchanged':out['modelUnchanged']}))
