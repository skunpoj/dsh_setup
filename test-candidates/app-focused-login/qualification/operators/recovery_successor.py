from pathlib import Path
import json,copy,sys,time
from guard_helpers import durable,api
from apply_successor import sha,verify_subset,ready,state
ROOT=Path(__file__).parent;NAME='dsh-app-signin-test'
if not __debug__:raise RuntimeError('Non-optimized Python required')
def main():
 assert len(sys.argv)==2 and sys.argv[1]in['off','on'];mode=sys.argv[1]
 plan=json.loads((ROOT/'PLAN_PRIVATE.json').read_bytes());review=json.loads((ROOT/'INDEPENDENT_REVIEW.json').read_bytes())
 assert review['result']=='PASS'and review['source_identity']==plan['source_identity']
 for n in ['PLAN_PRIVATE.json','guard_helpers.py','apply_successor.py','recovery_successor.py']:assert review['files'][n]==sha((ROOT/n).read_bytes())
 uid=plan['targets']['Deployment']['uid'];baseline=json.loads((ROOT/'DEPLOYMENT_READBACK_PRIVATE.json').read_bytes());assert baseline['metadata']['uid']==uid and baseline['metadata']['labels']==plan['labels']and baseline['spec']==plan['targets']['Deployment']['new_spec']
 sys.path.insert(0,'C:/Users/skunpojt/outputs/product-label-join-followup-20261015');import control as c
 expected=copy.deepcopy(baseline['spec']);gateway=next(ct for ct in expected['template']['spec']['containers']if ct['name']=='gateway');next(e for e in gateway['env']if e['name']=='DSH_APP_LOGIN_ENABLED')['value']='true'if mode=='off'else'false'
 path=api('Deployment',NAME);current=c.cluster(path);assert current['metadata']['uid']==uid and current['metadata']['labels']==plan['labels']and current['spec']==expected
 desired=copy.deepcopy(expected);gateway=next(ct for ct in desired['template']['spec']['containers']if ct['name']=='gateway');next(e for e in gateway['env']if e['name']=='DSH_APP_LOGIN_ENABLED')['value']='false'if mode=='off'else'true'
 before=state(c)
 durable(ROOT/('RECOVERY_'+mode+'_STARTED.json'),{'uid':uid,'spec_sha256':sha(json.dumps(expected,sort_keys=True).encode()),'state_before':before,'epoch':time.time()},exclusive=True)
 patch=[{'op':'test','path':'/metadata/uid','value':uid},{'op':'test','path':'/metadata/resourceVersion','value':current['metadata']['resourceVersion']},{'op':'test','path':'/spec','value':expected},{'op':'replace','path':'/spec','value':desired}]
 try:c.run(['-n','llm','patch','deployment',NAME,'--type=json','-p',json.dumps(patch)],timeout=45)
 except Exception:
  current=c.cluster(path);assert current['metadata']['uid']==uid and current['spec']==desired,'Unknown recovery outcome; no blind retry'
 pod=ready(c,plan,'false'if mode=='off'else'true');current=c.cluster(path);assert current['metadata']['uid']==uid and current['spec']==desired
 after=state(c);assert before==after,'Own Test store drift across recovery; preserve evidence'
 durable(ROOT/('RECOVERY_'+mode+'_READBACK.json'),{'uid':uid,'pod_uid':pod['metadata']['uid'],'source_hashes_verified':True,'new_mode':mode,'own_PVC_preserved':True,'state_hashes_unchanged':True,'state_after':after,'actual_application_acceptance_pending':True});print('Own Test feature '+mode+' ready; application acceptance remains required')
if __name__=='__main__':main()
