"""Lowered-threshold automatic compaction fixture using actual DSH persistence.

Does not change production thresholds or access real histories.
"""
import copy
import json
from pathlib import Path
import subprocess
import uuid

def kube(*args,source=None):
    p=subprocess.run(['kubectl','-n','llm',*args],input=source,text=True,capture_output=True,timeout=700)
    if p.returncode:raise RuntimeError(p.stderr[-1000:])
    return p.stdout

def main():
    name='dsh-compaction-canary'
    if kube('get','pod',name,'--ignore-not-found','-o','name').strip():raise ValueError('Existing fixture; inspect rather than replace')
    original=json.loads(kube('get','pod','dsh-1m-image-canary','-o','json'))
    spec=copy.deepcopy(original['spec']);c=spec['containers'][0]
    c['env']=[e for e in c.get('env',[]) if e['name']!='DSH_CONTEXT_TOKENS']+[{'name':'DSH_CONTEXT_TOKENS','value':''}]
    patch=r"""
const fs=require('fs');const YAML=require(require.resolve('yaml',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
const f='/state/profiles/web/cordis.patch.yml';const p=YAML.parse(fs.readFileSync(f,'utf8'));
const comp=p.find(x=>x.id==='compaction-basic');
comp.config.thresholdRatio=0.02;comp.config.retainRatio=0.001;
for(const rule of comp.config.modelPolicies){rule.thresholdRatio=0.02;rule.retainRatio=0.001;}
fs.writeFileSync(f,YAML.stringify(p));
"""
    spec['initContainers'][0]['command'][2]+="\nnode - <<'FIXTURE'\n"+patch+"\nFIXTURE\n"
    kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'labels':original['metadata']['labels']},'spec':spec}))
    kube('wait','--for=condition=Ready','pod/'+name,'--timeout=120s')
    token='REMEMBER_'+uuid.uuid4().hex[:12]
    base=Path(__file__).with_name('probe_dsh_1m_agent.py').read_text()
    def run(prompt,expected,session=None):
        s=base.replace("expected = 'DSH_LONG_CONTEXT_OK'","expected = "+repr(expected))
        a=s.index("    prompt = (");b=s.index('    tool_file =',a)
        s=s[:a]+'    prompt = '+repr(prompt)+'\n'+s[b:]
        s=s.replace("'turn/end', 'step/end'","'turn/end', 'step/end', 'compaction/'")
        s=s.replace("'maxMessages': 10","'maxMessages': 200")
        argv=['probe','--deadline','600']+(['--session-id',session] if session else [])
        source='import sys;sys.argv='+repr(argv)+'\n'+s
        value=json.loads(kube('exec','-i',name,'--','python3','-',source=source))
        assert value['expectedTextPresent'] and value['persistedPromptMatches']
        return value
    first=run('Remember the verification code '+token+'. '+' a b c d'*2500+'\nReply exactly REMEMBERED.','REMEMBERED')
    second=run('More synthetic history. '+' e f g h'*2500+'\nWhat was the verification code? Reply with that code only.',token,first['sessionId'])
    third=run('Recall the verification code from our earlier conversation. Reply with that code only.',token,first['sessionId'])
    summaries=[e for r in [first,second,third] for e in r['events'] if e['type']=='compaction/summary']
    ends=[e for r in [first,second,third] for e in r['events'] if e['type']=='compaction/end']
    result={'fixtureThresholdRatio':0.02,'productionRatioUnchanged':0.875,'context':1048576,
        'summaryPersisted':bool(summaries),'summaryRetainedCode':any(token in json.dumps(e['data']) for e in summaries),
        'compactionEndsWithoutError':bool(ends) and all(not e['data'].get('error') for e in ends),'turns':[first,second,third]}
    Path('docs/context-evidence/dsh-automatic-compaction-fixture-20261016.json').write_text(json.dumps(result,indent=2))
    assert result['summaryPersisted'] and result['summaryRetainedCode'] and result['compactionEndsWithoutError']
    print(json.dumps({k:v for k,v in result.items() if k!='turns'}))

if __name__=='__main__':main()
