"""Render a portable candidate. Does not contact Kubernetes or create Secrets."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parent
ALIASES = ['deepseek-v4.1-flash', 'deepseek-flash']

def render(settings):
    required = {'namespace', 'modelClaim', 'gatewayImage', 'credentialSecret', 'databaseSecret'}
    if set(settings) != required:
        raise ValueError('Exactly the documented settings are required')
    for key in required - {'gatewayImage'}:
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', settings[key]):
            raise ValueError('Invalid Kubernetes name: '+key)
    if not re.fullmatch(r'[a-z0-9./_-]+@sha256:[a-f0-9]{64}', settings['gatewayImage']):
        raise ValueError('Gateway image must use an immutable digest')
    ns = settings['namespace']
    def obj(kind, name, spec=None, **extra):
        d = {'apiVersion': 'apps/v1' if kind=='Deployment' else 'networking.k8s.io/v1' if kind=='NetworkPolicy' else 'v1',
             'kind':kind, 'metadata':{'name':name,'namespace':ns}, **extra}
        if spec is not None: d['spec']=spec
        return d
    sources={p.name:p.read_text(encoding='utf-8') for p in (ROOT/'runtime').glob('*.py')}
    for source in sources.values():ast.parse(source)
    patches={k:v for k,v in sources.items() if k.startswith('scheduler_')}
    guard={k:v for k,v in sources.items() if k not in patches}
    config={
      'model_list':[{'model_name':alias,'litellm_params':{
        'model':'openai/deepseek-v4.1-flash','api_base':'http://127.0.0.1:4001/v1',
        'api_key':'os.environ/INTERNAL_ROUTE_KEY','timeout':3600,'stream_timeout':3600},
        'model_info':{'max_tokens':1048576,'max_input_tokens':1048320,'max_output_tokens':8192}}
        for alias in ALIASES],
      'litellm_settings':{'drop_params':True,'modify_params':True,
        'callbacks':['gateway_output_guard.proxy_handler_instance'],
        'use_chat_completions_url_for_anthropic_messages':True},
      'general_settings':{'master_key':'os.environ/LITELLM_MASTER_KEY','set_verbose':False},
      'router_settings':{'model_group_retry_policy':{a:{'RateLimitErrorRetries':0} for a in ALIASES}}}
    guard['config.yaml']=yaml.safe_dump(config,sort_keys=False)
    # Source-addressed immutable objects allow an exact rollback without editing old content.
    digest=lambda data:hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:12]
    pname='local-scheduler-'+digest(patches);gname='local-gateway-'+digest(guard)
    docs=list(yaml.safe_load_all((ROOT/'templates/model.yaml').read_text(encoding='utf-8')))
    for d in docs:d['metadata']['namespace']=ns
    m=docs[0]['spec']['template']['spec']
    for v in m['volumes']:
        if v['name']=='model-cache':v['persistentVolumeClaim']['claimName']=settings['modelClaim']
        if v['name']=='scheduler-patch-source':v['configMap']['name']=pname
    secret=lambda name,key:{'name':key,'valueFrom':{'secretKeyRef':{'name':name,'key':key}}}
    mounts=[{'name':'config','mountPath':'/etc/litellm','readOnly':True}]
    security={'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}
    containers=[{'name':'gateway','image':settings['gatewayImage'],
       'command':['litellm'],'args':['--config','/etc/litellm/config.yaml','--port','4000'],
       'ports':[{'containerPort':4000}],
       'env':[secret(settings['credentialSecret'],'LITELLM_MASTER_KEY'),
              secret(settings['credentialSecret'],'INTERNAL_ROUTE_KEY'),secret(settings['databaseSecret'],'DATABASE_URL'),
              {'name':'PYTHONPATH','value':'/etc/litellm'}],
       'volumeMounts':mounts,'securityContext':security,
       'readinessProbe':{'httpGet':{'path':'/health/readiness','port':4000},'periodSeconds':10},
       'resources':{'requests':{'cpu':'500m','memory':'512Mi'},'limits':{'cpu':'2','memory':'2Gi'}}},
      {'name':'context-forwarder','image':settings['gatewayImage'],
       'command':['python','-m','uvicorn','context_forwarder:app','--app-dir','/etc/litellm','--host','127.0.0.1','--port','4001'],
       'env':[{'name':'PYTHONPATH','value':'/etc/litellm'},
              {'name':'DSH_TOKENIZER_URL','value':f'http://local-model.{ns}.svc.cluster.local:8000/v1/tokenize'}],
       'volumeMounts':mounts,'securityContext':security,
       'readinessProbe':{'exec':{'command':['python','-c',"import urllib.request; urllib.request.urlopen('http://127.0.0.1:4001/health', timeout=3).read()"]},'periodSeconds':10},
       'resources':{'requests':{'cpu':'500m','memory':'512Mi'},'limits':{'cpu':'4','memory':'4Gi'}}}]
    deployment=obj('Deployment','local-inference',{'replicas':1,'strategy':{'type':'Recreate'},
       'selector':{'matchLabels':{'app':'local-inference'}},'template':{
         'metadata':{'labels':{'app':'local-inference'}},
         'spec':{'automountServiceAccountToken':False,'containers':containers,
                 'volumes':[{'name':'config','configMap':{'name':gname}}]}}})
    service=obj('Service','local-inference',{'selector':{'app':'local-inference'},'ports':[{'port':4000,'targetPort':4000}]})
    peer=lambda label:{'podSelector':{'matchLabels':{'app':label}}}
    port=lambda n:{'protocol':'TCP','port':n}
    policies=[obj('NetworkPolicy','local-inference-boundaries',{
      'podSelector':{'matchLabels':{'app':'local-inference'}},'policyTypes':['Ingress','Egress'],
      'ingress':[{'from':[{'podSelector':{'matchLabels':{'inference-client':'allowed'}}}], 'ports':[port(4000)]}],
      'egress':[{'to':[peer('local-model')],'ports':[port(8000)]},
                {'to':[peer('llm-database')],'ports':[port(5432)]},
                {'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},
                        'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}],
                 'ports':[{'protocol':p,'port':53} for p in ['UDP','TCP']]}]}),
      obj('NetworkPolicy','local-model-boundaries',{
        'podSelector':{'matchLabels':{'app':'local-model'}},'policyTypes':['Ingress','Egress'],
        'ingress':[{'from':[peer('local-inference')],'ports':[port(8000)]}],'egress':[]})]
    # Namespace must exist, with a CNI that actually enforces these policies.
    return [obj('ConfigMap',pname,immutable=True,data=patches),obj('ConfigMap',gname,immutable=True,data=guard),*docs,deployment,service,*policies]

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--settings',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise SystemExit('Refusing to overwrite an existing candidate')
    result=render(json.loads(args.settings.read_text(encoding='utf-8')))
    args.output.write_text(yaml.safe_dump_all(result,sort_keys=False),encoding='utf-8')
    print(json.dumps({'objects':len(result),'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()}))
