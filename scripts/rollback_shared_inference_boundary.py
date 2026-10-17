"""Restore only the saved shared-service network/DNS boundary; never restore data."""
import argparse,copy,json
from pathlib import Path
from rollout_shared_inference_boundary import kube,patch_spec,wait,normalized_policy_spec

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--rollback-dir',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
 load=lambda n:json.loads((a.rollback_dir/n).read_text(encoding='utf-8'))
 rules=load('network-policies.json')['items'];approved={'dsh-shared-gateway-egress','dsh-local-inference-egress','dsh-local-model-egress','dsh-local-embedding-egress','dsh-local-database-egress'};assert {r['metadata']['name']for r in rules}==approved
 for r in rules:
  ns=r['metadata']['namespace'];assert ns in ['llm','ollama'];current=json.loads(kube(ns,'get','networkpolicy',r['metadata']['name'],'-o','json'));assert normalized_policy_spec(current['spec'])==normalized_policy_spec(r['spec']),'Policy changed after rollout; stop'
 applied=load('applied.json');dns_current=json.loads(kube('llm','get','deploy','dsh-internal-dns','-o','json'))['spec'];active_cm=next(v for v in dns_current['template']['spec']['volumes']if v['name']=='config')['configMap']['name']
 assert active_cm in applied.get('allowedPostMigrationDNSConfigMaps',[applied['dnsConfigMap']]),'Resolver changed outside this rollout; stop'
 print(json.dumps({'restoreDNS':['litellm','dsh-environment-gateway','dsh-internal-dns'],'removeOnlyPolicies':sorted(approved),'apply':a.apply,'dataRestored':False}),flush=True)
 if not a.apply:return
 for r in rules:kube(r['metadata']['namespace'],'delete','networkpolicy',r['metadata']['name'])
 for n in ['litellm','dsh-environment-gateway']:
  old=load(n+'-before.private.json')['spec']['template']['spec'];current=json.loads(kube('llm','get','deploy',n,'-o','json'))['spec'];new=copy.deepcopy(current);pod=new['template']['spec']
  for k in ['dnsPolicy','dnsConfig']:
   if k in old:pod[k]=old[k]
   else:pod.pop(k,None)
  patch_spec('llm','deploy',n,current,new);wait(n)
 old=load('dsh-internal-dns-before.private.json');current=json.loads(kube('llm','get','deploy','dsh-internal-dns','-o','json'))['spec'];new=copy.deepcopy(current)
 original=next(v for v in old['spec']['template']['spec']['volumes']if v['name']=='config')['configMap']['name'];next(v for v in new['template']['spec']['volumes']if v['name']=='config')['configMap']['name']=original
 patch_spec('llm','deploy','dsh-internal-dns',current,new);wait('dsh-internal-dns')
 # Restore the DNS-policy snapshot only if no unrelated rule appeared.
 old_np=load('dns-boundary-before.private.json')['spec'];cur=json.loads(kube('llm','get','networkpolicy','dsh-internal-dns-boundary','-o','json'))['spec'];new_np=copy.deepcopy(cur)
 additional=[r for r in new_np['ingress']if r not in old_np['ingress']]
 assert not additional or (len(additional)==1 and additional[0]['from'][0]['podSelector']['matchExpressions'][0]['values']==['litellm','dsh-environment-gateway']),'Unexpected resolver rule; stop'
 new_np['ingress']=[r for r in new_np['ingress']if r not in additional];patch_spec('llm','networkpolicy','dsh-internal-dns-boundary',cur,new_np)
 print(json.dumps({'networkRestored':True,'userDataUntouched':True,'modelNotRestarted':True}))
if __name__=='__main__':main()
