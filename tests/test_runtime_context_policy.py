import json
from pathlib import Path
import subprocess
import unittest


class RuntimeContextPolicyTests(unittest.TestCase):
    def test_policy_preserves_unrelated_models_and_credential_references(self):
        source = Path(__file__).parents[1]/'scripts/configure_runtime_context.js'
        script = r'''
const {configure}=require(SOURCE);
const p=[{id:'llm-pi-ai',config:{providers:{'litellm-cluster':{
 baseURL:'http://internal/v1',apiKeyEnv:'DEEPSEEK_API_KEY',models:[
 {id:'deepseek-v4.1-flash',contextWindow:131072},{id:'deepseek-flash',contextWindow:131072},
 {id:'another-model',contextWindow:4096}]
}}}},{id:'compaction-basic',config:{auto:true,modelPolicies:[{provider:'other',model:'other',thresholdRatio:.5}]}}];
configure(p,1048576);
const a=p[0].config.providers['litellm-cluster'];
if(a.models[2].contextWindow!==4096||a.apiKeyEnv!=='DEEPSEEK_API_KEY'||a.baseURL!=='http://internal/v1')throw Error('Unrelated policy changed');
if(a.models.slice(0,2).some(m=>m.contextWindow!==1048576||m.maxTokens!==8192))throw Error('1M budget missing');
if(a.streamIdleTimeoutMs!==3600000)throw Error('Long prefill idle watchdog unchanged');
if(p[1].config.modelPolicies.length!==3)throw Error('Unrelated compaction policy lost');
configure(p,1048576);if(p[1].config.modelPolicies.length!==3)throw Error('Repeated policy duplicated');
let rejected=false;try{configure(p,10000000)}catch{rejected=true}if(!rejected)throw Error('Unsupported budget accepted');
console.log(JSON.stringify({passed:true}));
'''.replace('SOURCE', json.dumps(str(source)))
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])


if __name__ == '__main__':
    unittest.main()
