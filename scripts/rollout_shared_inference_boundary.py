"""Restrict shared local inference without changing model weights or user data.

Public provider destinations are refused. Existing resolver entries are retained;
only explicit internal service names are added. Model pods are never restarted.
"""
import argparse,copy,hashlib,ipaddress,json,subprocess,time,re
from pathlib import Path
import yaml

def kube(ns,*args,source=None):
 p=subprocess.run(['kubectl','-n',ns,'--request-timeout=25s',*args],input=source,text=True,capture_output=True,encoding='utf-8',timeout=100)
 if p.returncode:raise RuntimeError(p.stderr[-500:])
 return p.stdout

def patch_spec(ns,kind,name,old,new):
 return kube(ns,'patch',kind,name,'--type=json','-p',json.dumps([{'op':'test','path':'/spec','value':old},{'op':'replace','path':'/spec','value':new}]))

def wait(name,ns='llm'):
 kube(ns,'rollout','status','deploy/'+name,'--timeout=80s')

def policy(name,selector,egress,ns='llm'):
 return {'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':name,'namespace':ns},'spec':{'podSelector':selector,'policyTypes':['Egress'],'egress':egress}}

def validate_authoritative_cluster_zone(core):
 if not re.search(r'kubernetes\s+cluster\.local',core)or re.search(r'^\s*rewrite\b',core,re.M):raise ValueError('Unreviewed cluster DNS zone configuration')
 for line in core.splitlines():
  words=line.strip().split()
  if words and words[0]=='fallthrough'and(len(words)==1 or any(x not in ['in-addr.arpa','ip6.arpa']for x in words[1:])):raise ValueError('Private-zone DNS must not fall through publicly')

def validate_shared_singleton(spec):
 if spec.get('replicas')!=1 or spec.get('strategy',{}).get('type')!='Recreate':raise ValueError('Shared forwarder requires one replica and Recreate for its admission lock')

def normalized_policy_spec(spec):
 result=copy.deepcopy(spec)
 if 'Egress' in result.get('policyTypes',[]):result.setdefault('egress',[])
 return result

def policies(dns_ip):
 address=ipaddress.IPv4Address(dns_ip)
 if not address.is_private or address.is_loopback:raise ValueError('A private filtered-DNS Service address is required')
 dns={'to':[{'podSelector':{'matchLabels':{'app':'dsh-internal-dns'}}},{'ipBlock':{'cidr':dns_ip+'/32'}}],'ports':[{'protocol':p,'port':n}for p in ['TCP','UDP']for n in [53,5353]]}
 gateway=policy('dsh-shared-gateway-egress',{'matchLabels':{'app':'dsh-environment-gateway'}},[dns,{'to':[{'podSelector':{'matchExpressions':[{'key':'dsh.bot.or.th/egress-mode','operator':'In','values':['offline','online']}]}},{'podSelector':{'matchExpressions':[{'key':'app','operator':'In','values':['dsh-user2','dsh3']} ]}}],'ports':[{'protocol':'TCP','port':1,'endPort':65535}]}])
 model_apps=['vllm-deepseek-v4-1-flash','vllm-deepseek-v4-flash','vllm-glm-5-3-flash-tp4','sglang-glm-5-3-flash-tp4','vllm-qwen3-8-27b','vllm-qwen3-8-flash-next','typhoon-audio-8b']
 inference=policy('dsh-local-inference-egress',{'matchLabels':{'app':'litellm'}},[dns,{'to':[{'podSelector':{'matchExpressions':[{'key':'app','operator':'In','values':model_apps}]}}],'ports':[{'protocol':'TCP','port':8000}]},{'to':[{'podSelector':{'matchLabels':{'app':'litellm-postgres'}}}],'ports':[{'protocol':'TCP','port':5432}]},{'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'ollama'}},'podSelector':{'matchLabels':{'app.kubernetes.io/name':'ollama'}}}],'ports':[{'protocol':'TCP','port':11434}]}])
 model=policy('dsh-local-model-egress',{'matchExpressions':[{'key':'app','operator':'In','values':model_apps}]},[])
 ollama=policy('dsh-local-embedding-egress',{'matchLabels':{'app.kubernetes.io/name':'ollama'}},[],'ollama')
 database=policy('dsh-local-database-egress',{'matchLabels':{'app':'litellm-postgres'}},[])
 return [gateway,inference,model,ollama,database]

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output-dir',required=True,type=Path);ap.add_argument('--apply',action='store_true');a=ap.parse_args();a.output_dir.mkdir(exist_ok=False)
 def save(n,x): (a.output_dir/n).write_text(json.dumps(x,indent=2),encoding='utf-8')
 core=json.loads(kube('kube-system','get','cm','rke2-coredns-rke2-coredns','-o','json'))['data']['Corefile'];validate_authoritative_cluster_zone(core)
 orig={n:json.loads(kube('llm','get','deploy',n,'-o','json'))for n in ['dsh-internal-dns','litellm','dsh-environment-gateway']}
 for n,v in orig.items():save(n+'-before.private.json',v)
 for n in ['litellm','dsh-environment-gateway']:validate_shared_singleton(orig[n]['spec'])
 dns_vol=next(v for v in orig['dsh-internal-dns']['spec']['template']['spec']['volumes']if v['name']=='config');old_cm=json.loads(kube('llm','get','cm',dns_vol['configMap']['name'],'-o','json'));save('dns-config-before.private.json',old_cm)
 resolver=Path(__file__).with_name('internal_dns_allowlist.py').read_text(encoding='utf-8');assert old_cm['data']['resolver.py'].replace('\r\n','\n')==resolver.replace('\r\n','\n'),'Unexpected resolver source'
 svcs=json.loads(kube('llm','get','svc','-o','json'))['items'];allowed=set(json.loads(old_cm['data']['allowed.json']))
 # Only explicit internal namespace service names, never suffix or public wildcards.
 for svc in svcs:
  n=svc['metadata']['name']
  if n.startswith(('dsh','litellm','vllm-','sglang-','typhoon-')):
   allowed.update([n,n+'.llm',n+'.llm.svc',n+'.llm.svc.cluster.local'])
 allowed.update(['ollama.ollama','ollama.ollama.svc','ollama.ollama.svc.cluster.local'])
 data=copy.deepcopy(old_cm['data']);data['allowed.json']=json.dumps(sorted(allowed));cm_name='dsh-internal-dns-'+hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:12]
 cm={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':cm_name,'namespace':'llm'},'immutable':True,'data':data};save('dns-config-candidate.json',cm)
 dns_ip=json.loads(kube('llm','get','svc','dsh-internal-dns','-o','json'))['spec']['clusterIP'];rules=policies(dns_ip);save('network-policies.json',{'apiVersion':'v1','kind':'List','items':rules})
 dns_np=json.loads(kube('llm','get','networkpolicy','dsh-internal-dns-boundary','-o','json'));save('dns-boundary-before.private.json',dns_np)
 new_np=copy.deepcopy(dns_np['spec']);extra_dns_rule=({'from':[{'podSelector':{'matchExpressions':[{'key':'app','operator':'In','values':['litellm','dsh-environment-gateway']}]}}],'ports':[{'protocol':'UDP','port':5353},{'protocol':'TCP','port':5353}]})
 if extra_dns_rule not in new_np['ingress']:new_np['ingress'].append(extra_dns_rule)
 # Ensure policies are new resources rather than silently replacing another owner.
 for rule in rules:
  existing=json.loads(kube(rule['metadata']['namespace'],'get','networkpolicy','-o','json'))['items'];assert not any(x['metadata']['name']==rule['metadata']['name']for x in existing),'Boundary already exists; inspect rather than overwrite'
 print(json.dumps({'plan':[x['metadata']['name']for x in rules],'dnsConfigMap':cm_name,'apply':a.apply}),flush=True)
 if not a.apply:return
 made=[];changed=[];dns_changed=False
 try:
  kube('llm','create','-f','-',source=json.dumps(cm));dns_spec=copy.deepcopy(orig['dsh-internal-dns']['spec']);next(v for v in dns_spec['template']['spec']['volumes']if v['name']=='config')['configMap']['name']=cm_name
  patch_spec('llm','deploy','dsh-internal-dns',orig['dsh-internal-dns']['spec'],dns_spec);dns_changed=True;wait('dsh-internal-dns')
  patch_spec('llm','networkpolicy','dsh-internal-dns-boundary',dns_np['spec'],new_np)
  for n in ['dsh-environment-gateway','litellm']:
   new=copy.deepcopy(orig[n]['spec']);p=new['template']['spec'];p['dnsPolicy']='None';p['dnsConfig']={'nameservers':[dns_ip],'searches':['llm.svc.cluster.local','svc.cluster.local','cluster.local'],'options':[{'name':'ndots','value':'2'}]}
   patch_spec('llm','deploy',n,orig[n]['spec'],new);changed.append((n,new));wait(n);print(json.dumps({'filteredDNSReady':n}),flush=True)
  for rule in rules:kube(rule['metadata']['namespace'],'create','-f','-',source=json.dumps(rule));made.append(rule)
  save('desired-pod-dns.json',{'deployments':['litellm','dsh-environment-gateway'],'dnsPolicy':'None','dnsConfig':changed[-1][1]['template']['spec']['dnsConfig']})
  save('applied.json',{'status':'applied-awaiting-behavior-tests','dnsConfigMap':cm_name,'policies':[x['metadata']['name']for x in rules],'modelRestarted':False})
  # Write canonical tracked manifests; existing mounted old ConfigMaps remain for rollback/Kerberos references.
  root=Path(__file__).resolve().parents[1];(root/'k8s/shared-inference-egress.yaml').write_text(yaml.safe_dump_all(rules,sort_keys=False),encoding='utf-8')
  docs=list(yaml.safe_load_all((root/'k8s/dsh-internal-dns.yaml').read_text(encoding='utf-8')))
  for i,d in enumerate(docs):
   if d['kind']=='ConfigMap':docs[i]=cm
   elif d['kind']=='Deployment':d['spec']=dns_spec
   elif d['kind']=='NetworkPolicy':d['spec']=new_np
  (root/'k8s/dsh-internal-dns.yaml').write_text(yaml.safe_dump_all(docs,sort_keys=False),encoding='utf-8')
 except Exception:
  for rule in reversed(made):kube(rule['metadata']['namespace'],'delete','networkpolicy',rule['metadata']['name'])
  for n,new in reversed(changed):patch_spec('llm','deploy',n,new,orig[n]['spec']);wait(n)
  if dns_changed:
   current=json.loads(kube('llm','get','networkpolicy','dsh-internal-dns-boundary','-o','json'))['spec']
   if current==new_np:patch_spec('llm','networkpolicy','dsh-internal-dns-boundary',new_np,dns_np['spec'])
   patch_spec('llm','deploy','dsh-internal-dns',dns_spec,orig['dsh-internal-dns']['spec']);wait('dsh-internal-dns')
  save('failed-rolled-back.json',{'rolledBack':True});raise
if __name__=='__main__':main()
