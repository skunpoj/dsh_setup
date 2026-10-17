"""Upgrade only the filtered resolver source after an expected-hash review."""
import argparse,copy,hashlib,json,re
from pathlib import Path
import yaml
from rollout_shared_inference_boundary import kube,patch_spec,wait,validate_authoritative_cluster_zone

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--expected-current-sha256',required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args();a.checkpoint.mkdir(exist_ok=False)
 core=json.loads(kube('kube-system','get','cm','rke2-coredns-rke2-coredns','-o','json'))['data']['Corefile']
 validate_authoritative_cluster_zone(core)
 old=json.loads(kube('llm','get','deploy','dsh-internal-dns','-o','json'));volume=next(v for v in old['spec']['template']['spec']['volumes']if v['name']=='config');cm=json.loads(kube('llm','get','cm',volume['configMap']['name'],'-o','json'))
 assert hashlib.sha256(cm['data']['resolver.py'].encode()).hexdigest()==a.expected_current_sha256,'Resolver changed since expected source review'
 root=Path(__file__).resolve().parents[1];source=(root/'scripts/internal_dns_allowlist.py').read_text(encoding='utf-8');data=copy.deepcopy(cm['data']);data['resolver.py']=source;name='dsh-internal-dns-'+hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:12]
 candidate={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':name,'namespace':'llm'},'immutable':True,'data':data};(a.checkpoint/'before.private.json').write_text(json.dumps(old),encoding='utf-8')
 print(json.dumps({'resolverConfigMap':name,'authoritativePrivateZoneChecked':True,'apply':a.apply}),flush=True)
 if not a.apply:return
 kube('llm','create','-f','-',source=json.dumps(candidate));new=copy.deepcopy(old['spec']);next(v for v in new['template']['spec']['volumes']if v['name']=='config')['configMap']['name']=name
 try:
  patch_spec('llm','deploy','dsh-internal-dns',old['spec'],new);wait('dsh-internal-dns')
  actual=json.loads(kube('llm','get','deploy','dsh-internal-dns','-o','json'))['spec'];assert actual==new
 except Exception:patch_spec('llm','deploy','dsh-internal-dns',new,old['spec']);wait('dsh-internal-dns');raise
 docs=list(yaml.safe_load_all((root/'k8s/dsh-internal-dns.yaml').read_text(encoding='utf-8')))
 for i,d in enumerate(docs):
  if d['kind']=='ConfigMap':docs[i]=candidate
  elif d['kind']=='Deployment':d['spec']=new
 (root/'k8s/dsh-internal-dns.yaml').write_text(yaml.safe_dump_all(docs,sort_keys=False),encoding='utf-8')
 settings=root/'k8s/shared-inference-dns-settings.json';v=json.loads(settings.read_text(encoding='utf-8'));v['dnsConfigMap']=name;settings.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
 (a.checkpoint/'result.json').write_text(json.dumps({'applied':True,'configMap':name,'existingExactNamesRetained':True,'dynamicPrivateServiceFQDNOnly':True,'noClientOrModelRestart':True},indent=2),encoding='utf-8')
if __name__=='__main__':main()
