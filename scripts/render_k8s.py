"""Render a fresh generic installation. Never discovers or copies cluster data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import ipaddress
import yaml

ROOT = Path(__file__).resolve().parents[1]
SC = {'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True,
      'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}

def validate(c):
    for key in ['namespace','storage_class','shared_storage_class','dsh_image','public_hostname']:
        if not isinstance(c.get(key),str) or not c[key] or 'CHANGE_ME' in c[key] or 'example.invalid' in c[key]:
            raise ValueError('Supply a local value for '+key)
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}',c['namespace']):raise ValueError('Invalid namespace')
    if not re.fullmatch(r'[A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64}',c['dsh_image']):raise ValueError('Pin the built runtime image digest')
    for user in c['users']:
        if not re.fullmatch(r'[a-z0-9_.-]{3,30}',user):raise ValueError('Invalid local identity')
    if len(set(c['users']))!=len(c['users']) or not set(c['admin_users']).issubset(c['users']):raise ValueError('Invalid account mapping')
    if not re.fullmatch(r'[a-f0-9]{40}',c['model_revision']):raise ValueError('Pin a model commit')
    for key in ['cluster_dns_ip','filtered_dns_ip']:ipaddress.IPv4Address(c[key])

def build(c):
    validate(c);ns=c['namespace'];docs=[]
    def obj(kind,name,spec=None,**extra):
        d={'apiVersion':'v1' if kind in ['Namespace','ConfigMap','Service','PersistentVolumeClaim'] else 'apps/v1',
           'kind':kind,'metadata':{'name':name,**({} if kind=='Namespace' else {'namespace':ns})},**extra}
        if spec is not None:d['spec']=spec
        docs.append(d);return d
    def claim(name,size,shared=False):
        return obj('PersistentVolumeClaim',name,{'accessModes':['ReadWriteMany' if shared else 'ReadWriteOnce'],
          'storageClassName':c['shared_storage_class' if shared else 'storage_class'],'resources':{'requests':{'storage':size}}})
    def service(name,port,app=None):return obj('Service',name,{'selector':{'app':app or name},'ports':[{'port':port,'targetPort':port}]})
    def deploy(name,containers,volumes,init=None):
        pod={'automountServiceAccountToken':False,'securityContext':{'seccompProfile':{'type':'RuntimeDefault'}},
             'containers':containers,'volumes':volumes}
        if name in ['gateway','litellm'] or name.startswith('user-') and name.endswith('-secure'):
            pod['dnsPolicy']='None';pod['dnsConfig']={'nameservers':[c['filtered_dns_ip']],
              'searches':[ns+'.svc.'+c['cluster_domain'],'svc.'+c['cluster_domain'],c['cluster_domain']],
              'options':[{'name':'ndots','value':'1'}]}
        if init:pod['initContainers']=init
        return obj('Deployment',name,{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app':name}},
             'template':{'metadata':{'labels':{'app':name}},'spec':pod}})
    def envref(name,key,secret='platform-secrets'):
        return {'name':name,'valueFrom':{'secretKeyRef':{'name':secret,'key':key}}}
    def policy(name,selector,ingress,egress):
        d=obj('NetworkPolicy',name,{'podSelector':selector,'policyTypes':['Ingress','Egress'],'ingress':ingress,'egress':egress});d['apiVersion']='networking.k8s.io/v1'
    def peer(app):return {'podSelector':{'matchLabels':{'app':app}}}
    def port(n):return {'protocol':'TCP','port':n}
    cluster_dns={'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}],
         'ports':[{'protocol':'UDP','port':53},port(53)]}
    dns={'to':[peer('filtered-dns')],'ports':[{'protocol':'UDP','port':53},port(53),{'protocol':'UDP','port':5353},port(5353)]}
    obj('Namespace',ns)
    claim('model-cache',c['model_storage']);claim('database','20Gi');claim('gateway-auth','1Gi');claim('routing-tokens','1Gi',True);claim('approved-packages','10Gi',True)
    allowed=[]
    for name in ['litellm','model','database','gateway','filtered-dns']:
      allowed.extend([name,name+'.'+ns+'.svc.'+c['cluster_domain']])
    obj('ConfigMap','dns-source',data={'resolver.py':(ROOT/'scripts/internal_dns_allowlist.py').read_text(encoding='utf-8'),'allowed.json':json.dumps(allowed)})
    dns_container={'name':'resolver','image':c['dsh_image'],'command':['python3','/config/resolver.py'],'securityContext':SC,
      'env':[{'name':'DNS_UPSTREAM','value':c['cluster_dns_ip']},{'name':'DNS_RUNTIME_NAMESPACE','value':ns},{'name':'DNS_CLUSTER_DOMAIN','value':c['cluster_domain']}],
      'volumeMounts':[{'name':'source','mountPath':'/config','readOnly':True}],
      'resources':{'requests':{'cpu':'50m','memory':'64Mi'},'limits':{'cpu':'500m','memory':'256Mi'}},
      'readinessProbe':{'httpGet':{'path':'/health','port':8080}}}
    deploy('filtered-dns',[dns_container],[{'name':'source','configMap':{'name':'dns-source'}}])
    obj('Service','filtered-dns',{'clusterIP':c['filtered_dns_ip'],'selector':{'app':'filtered-dns'},'ports':[{'name':'udp','protocol':'UDP','port':53,'targetPort':5353},{'name':'tcp','protocol':'TCP','port':53,'targetPort':5353}]})
    scheduler={n:(ROOT/'scripts'/n).read_text(encoding='utf-8') for n in ['scheduler_fairness_patch.py','scheduler_chunk_guard_patch.py']}
    obj('ConfigMap','scheduler-source',data=scheduler)
    # The download job is the only model component permitted external access.
    download=obj('Job','download-model',{'backoffLimit':1,'template':{'metadata':{'labels':{'app':'download-model'}},'spec':{
      'automountServiceAccountToken':False,'restartPolicy':'Never','containers':[{'name':'download','image':c['sglang_image'],
      'command':['python3','-c','from huggingface_hub import snapshot_download; import os; snapshot_download(repo_id=os.environ["MODEL_REPO"], revision=os.environ["MODEL_REVISION"], local_dir="/models/model")'],
      'env':[{'name':'MODEL_REPO','value':c['model_repository']},{'name':'MODEL_REVISION','value':c['model_revision']},
             {'name':'HF_TOKEN','valueFrom':{'secretKeyRef':{'name':'model-download','key':'token','optional':True}}}],
      'resources':{'requests':{'cpu':'1','memory':'2Gi'},'limits':{'cpu':'4','memory':'8Gi'}},
      'volumeMounts':[{'name':'models','mountPath':'/models'}]}],
      'volumes':[{'name':'models','persistentVolumeClaim':{'claimName':'model-cache'}}]}}});download['apiVersion']='batch/v1'
    args=['--model-path','/models/model','--served-model-name','deepseek-v4.1-flash,deepseek-flash','--host','0.0.0.0','--port','8000',
      '--tp-size','4','--moe-runner-backend','marlin','--trust-remote-code','--mem-fraction-static','0.90','--max-running-requests','16',
      '--chunked-prefill-size','1024','--max-prefill-tokens','2048','--swa-prefix-tails','0','--context-length','1048576',
      '--reasoning-parser','deepseek-v41','--tool-call-parser','deepseekv41','--enable-mixed-chunk','--enable-metrics','--prefill-decode-interval','4','--enable-session-radix-cache']
    model={'name':'model','image':c['sglang_image'],'command':['python3','-m','sglang.launch_server'],'args':args,
      'env':[{'name':k,'value':v} for k,v in {'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HOME':'/models/huggingface',
        'SGLANG_ENABLE_DSV41_ENGRAM_HOST_TABLE':'1','SGLANG_DSV41_ENGRAM_HOST_TABLE_LAYOUT':'private','SGLANG_DSV41_ENGRAM_HOST_TABLE_PIN':'1',
        'SGLANG_ENABLE_DSV41_ENGRAM_KV_PREFETCH':'1','SGLANG_ENABLE_DSV41_ENGRAM_DROP_PAGE_CACHE':'1','PYTORCH_CUDA_ALLOC_CONF':'expandable_segments:True'}.items()],
      'resources':{'requests':{'nvidia.com/gpu':4,'cpu':'16','memory':'256Gi'},'limits':{'nvidia.com/gpu':4,'cpu':'32','memory':'512Gi'}},
      'volumeMounts':[{'name':'models','mountPath':'/models'},{'name':'shm','mountPath':'/dev/shm'},
        {'name':'overlay','mountPath':'/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py','subPath':'scheduler.py','readOnly':True},
        {'name':'overlay','mountPath':'/sgl-workspace/sglang/python/sglang/srt/managers/schedule_policy.py','subPath':'schedule_policy.py','readOnly':True}],
      'startupProbe':{'httpGet':{'path':'/health','port':8000},'periodSeconds':15,'timeoutSeconds':15,'failureThreshold':120},
      'readinessProbe':{'httpGet':{'path':'/health','port':8000},'periodSeconds':10,'timeoutSeconds':15},
      'livenessProbe':{'httpGet':{'path':'/health','port':8000},'periodSeconds':30,'timeoutSeconds':15,'failureThreshold':5}}
    md=deploy('model',[model],[{'name':'models','persistentVolumeClaim':{'claimName':'model-cache'}},{'name':'shm','emptyDir':{'medium':'Memory','sizeLimit':'128Gi'}},
      {'name':'overlay','emptyDir':{}},{'name':'patch','configMap':{'name':'scheduler-source'}}],
      [{'name':'scheduler-overlay','image':c['sglang_image'],'command':['sh','-ec',
        'python3 /patch/scheduler_fairness_patch.py /sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py /overlay/scheduler.py\npython3 /patch/scheduler_chunk_guard_patch.py /sgl-workspace/sglang/python/sglang/srt/managers/schedule_policy.py /overlay/schedule_policy.py'],
        'volumeMounts':[{'name':'overlay','mountPath':'/overlay'},{'name':'patch','mountPath':'/patch','readOnly':True}]}]);service('model',8000)
    md['spec']['template']['spec']['nodeSelector']=c.get('gpu_node_selector',{})
    md['spec']['progressDeadlineSeconds']=2100
    download['spec']['template']['spec']['nodeSelector']=c.get('gpu_node_selector',{})
    pg={'name':'postgres','image':c['postgres_image'],'env':[envref('POSTGRES_PASSWORD','POSTGRES_PASSWORD'),{'name':'POSTGRES_USER','value':'gateway'},{'name':'POSTGRES_DB','value':'gateway'}],
       'volumeMounts':[{'name':'data','mountPath':'/var/lib/postgresql/data','subPath':'data'}],
       'readinessProbe':{'exec':{'command':['pg_isready','-U','gateway']},'periodSeconds':10},
       'resources':{'requests':{'cpu':'250m','memory':'512Mi'},'limits':{'cpu':'2','memory':'2Gi'}}}
    deploy('database',[pg],[{'name':'data','persistentVolumeClaim':{'claimName':'database'}}]);service('database',5432)
    config={'model_list':[{'model_name':name,'litellm_params':{'model':'openai/deepseek-v4.1-flash','api_base':'http://127.0.0.1:4001/v1','api_key':'not-required-internal',
         'max_tokens':8192,'timeout':3600,'num_retries':0},'model_info':{'max_input_tokens':1048576,'max_output_tokens':8192}} for name in ['deepseek-v4.1-flash','deepseek-flash']],
       'general_settings':{'master_key':'os.environ/LITELLM_MASTER_KEY','database_url':'os.environ/DATABASE_URL'},
       'litellm_settings':{'callbacks':['gateway_output_guard.proxy_handler_instance'],'drop_params':False,'set_verbose':False},'router_settings':{'num_retries':0}}
    sources={n:(ROOT/'scripts'/n).read_text(encoding='utf-8') for n in ['context_forwarder.py','context_envelope.py','long_context_callbacks.py','gateway_output_guard.py','stream_admission_errors.py']}
    sources['config.yaml']=yaml.safe_dump(config,sort_keys=False);obj('ConfigMap','gateway-source',data=sources)
    mount=[{'name':'source','mountPath':'/etc/litellm','readOnly':True}]
    proxy={'name':'litellm','image':c['litellm_image'],'command':['litellm'],'args':['--config','/etc/litellm/config.yaml','--port','4000'],
      'env':[envref('LITELLM_MASTER_KEY','LITELLM_MASTER_KEY'),envref('LITELLM_SALT_KEY','LITELLM_SALT_KEY'),envref('DATABASE_URL','DATABASE_URL'),{'name':'PYTHONPATH','value':'/etc/litellm'}],
      'volumeMounts':mount,'resources':{'requests':{'cpu':'500m','memory':'1Gi'},'limits':{'cpu':'4','memory':'4Gi'}},
      'startupProbe':{'tcpSocket':{'port':4000},'periodSeconds':5,'failureThreshold':120},'readinessProbe':{'tcpSocket':{'port':4000}}}
    forward={'name':'context-forwarder','image':c['litellm_image'],'command':['python','-m','uvicorn','context_forwarder:app','--app-dir','/etc/litellm','--host','127.0.0.1','--port','4001'],
      'env':[{'name':'PYTHONPATH','value':'/etc/litellm'},{'name':'HOME','value':'/tmp'},{'name':'DSH_TOKENIZER_URL','value':'http://model:8000/v1/tokenize'}],
      'volumeMounts':mount,'securityContext':SC,'resources':{'requests':{'cpu':'250m','memory':'256Mi'},'limits':{'cpu':'2','memory':'2Gi'}},
      'readinessProbe':{'exec':{'command':['python','-c',"import urllib.request; urllib.request.urlopen('http://127.0.0.1:4001/health',timeout=2).read()"]},'periodSeconds':10}}
    deploy('litellm',[proxy,forward],[{'name':'source','configMap':{'name':'gateway-source'}}]);service('litellm',4000)
    routes={};token_dirs=[]
    for user in c['users']:
      routes[user]={}
      ident=hashlib.sha256(user.encode()).hexdigest()[:16]
      for mode in ['secure','internet']:
        name='user-'+ident+'-'+mode;sub=ident+'/'+mode;token_dirs.append(sub)
        for suffix,size in [('state','5Gi'),('workspace','10Gi')]:claim(name+'-'+suffix,size)
        routes[user][mode]={'host':name,'port':3081,'tokenFile':'/runtime-tokens/'+sub+'/'+mode}
        mounts=[{'name':'state','mountPath':'/state'},{'name':'workspace','mountPath':'/workspace'},
                {'name':'tokens','mountPath':'/runtime-tokens','subPath':sub},
                {'name':'harness-credentials','mountPath':'/harness-credentials','readOnly':True}]
        volumes=[{'name':'state','persistentVolumeClaim':{'claimName':name+'-state'}},{'name':'workspace','persistentVolumeClaim':{'claimName':name+'-workspace'}},
                 {'name':'tokens','persistentVolumeClaim':{'claimName':'routing-tokens'}},
                 {'name':'harness-credentials','secret':{'secretName':name+'-inference','items':[{'key':'key','path':'api-key'}]}}]
        if mode=='secure':
          volumes.append({'name':'packages','persistentVolumeClaim':{'claimName':'approved-packages'}})
          mounts.append({'name':'packages','mountPath':'/packages/approved','readOnly':True})
        else:
          claim(name+'-incoming','10Gi');volumes.append({'name':'packages','persistentVolumeClaim':{'claimName':name+'-incoming'}})
          mounts.append({'name':'packages','mountPath':'/packages/incoming'})
        env=[{'name':'DSH_ENVIRONMENT','value':mode},{'name':'DSH_TRUSTED_HOST','value':c['public_hostname']},
             {'name':'DSH_CONTEXT_TOKENS','value':'1048576'},{'name':'DSH_LLM_TRANSPORT_ORIGIN','value':'http://litellm:4000'}]
        for key in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','LITELLM_API_KEY']:env.append(envref(key,'key',name+'-inference'))
        runtime={'name':'dsh','image':c['dsh_image'],'env':env,'securityContext':SC,'volumeMounts':mounts,
          'resources':{'requests':{'cpu':'250m','memory':'1Gi'},'limits':{'cpu':'4','memory':'8Gi'}},
          'startupProbe':{'tcpSocket':{'port':3081},'periodSeconds':5,'failureThreshold':60},'readinessProbe':{'tcpSocket':{'port':3081}}}
        init_mounts=[{'name':'state','mountPath':'/state'},{'name':'workspace','mountPath':'/workspace'}]
        initialize='chown -R 10001:10001 /state /workspace'
        if mode=='internet':
          init_mounts.append({'name':'packages','mountPath':'/incoming'});initialize+=' /incoming'
        d=deploy(name,[runtime],volumes,[{'name':'prepare-private-storage','image':c['dsh_image'],
          'command':['sh','-ec',initialize],'volumeMounts':init_mounts}]);d['spec']['template']['metadata']['labels'].update({'component':'runtime','environment':mode})
        sv=service(name,3081);sv['spec']['ports']=[{'name':label,'port':n,'targetPort':n} for label,n in [('dsh',3081),('terminal',7681),('application',3000)]]
    obj('ConfigMap','user-routing',data={'users.json':json.dumps(routes)})
    gateway={'name':'gateway','image':c['dsh_image'],'command':['node','/opt/dsh/scripts/auth_proxy.js'],'securityContext':SC,
      'env':[{'name':k,'value':v} for k,v in {'DSH_USER_TARGETS_FILE':'/routing/users.json','DSH_USER_STORE_PATH':'/auth/users.json',
        'DSH_USER_SETTINGS_PATH':'/auth/settings.json','DSH_AUDIT_DIR':'/auth/audit','DSH_ADMIN_USERS':','.join(c['admin_users']),
        'DSH_TRUSTED_HOST':c['public_hostname'],'DSH_ALLOW_REGISTRATION':'false','PORT':'3080'}.items()],
      'volumeMounts':[{'name':'auth','mountPath':'/auth'},{'name':'routing','mountPath':'/routing','readOnly':True},{'name':'tokens','mountPath':'/runtime-tokens','readOnly':True}],
      'resources':{'requests':{'cpu':'250m','memory':'256Mi'},'limits':{'cpu':'2','memory':'1Gi'}},'readinessProbe':{'tcpSocket':{'port':3080}}}
    seed='mkdir -p /auth; if [ ! -f /auth/users.json ]; then cp /seed/users.json /auth/users.json; fi; chmod 0600 /auth/users.json; chown -R 10001:10001 /auth; '
    seed+='; '.join('mkdir -p /tokens/'+s+'; chown 10001:10001 /tokens/'+s for s in token_dirs)
    deploy('gateway',[gateway],[{'name':'auth','persistentVolumeClaim':{'claimName':'gateway-auth'}},{'name':'routing','configMap':{'name':'user-routing'}},
      {'name':'tokens','persistentVolumeClaim':{'claimName':'routing-tokens'}},{'name':'seed','secret':{'secretName':'account-seed'}}],
      [{'name':'initialize-account-store','image':c['dsh_image'],'command':['sh','-ec',seed],
        'volumeMounts':[{'name':'auth','mountPath':'/auth'},{'name':'seed','mountPath':'/seed','readOnly':True},{'name':'tokens','mountPath':'/tokens'}]}]);service('gateway',3080)
    # Operators must restrict ingress to their controller. No public Ingress,
    # NodePort, hostPath, cluster-management identity or corporate data mount.
    policy('model',{'matchLabels':{'app':'model'}},[{'from':[peer('litellm')],'ports':[port(8000)]}],[])
    policy('database',{'matchLabels':{'app':'database'}},[{'from':[peer('litellm')],'ports':[port(5432)]}],[])
    policy('litellm',{'matchLabels':{'app':'litellm'}},[{'from':[{'podSelector':{'matchLabels':{'component':'runtime'}}}],'ports':[port(4000)]}],
      [dns,{'to':[peer('model')],'ports':[port(8000)]},{'to':[peer('database')],'ports':[port(5432)]}])
    for mode in ['secure','internet']:
      egress=[cluster_dns if mode=='internet' else dns,{'to':[peer('litellm')],'ports':[port(4000)]}]
      if mode=='internet':egress.append({'to':[{'ipBlock':{'cidr':'0.0.0.0/0','except':['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16']}}]})
      policy('runtime-'+mode,{'matchLabels':{'component':'runtime','environment':mode}},[{'from':[peer('gateway')],'ports':[port(3081),port(7681),port(3000)]}],egress)
    ingress=[]
    if c.get('ingress_enabled'):
      ingress=[{'from':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':c['ingress_namespace']}},'podSelector':{'matchLabels':c['ingress_pod_selector']}}],'ports':[port(3080)]}]
      d=obj('Ingress','gateway',{'ingressClassName':c['ingress_class'],'tls':[{'hosts':[c['public_hostname']],'secretName':c['tls_secret']}],
        'rules':[{'host':c['public_hostname'],'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':'gateway','port':{'number':3080}}}}]}}]})
      d['apiVersion']='networking.k8s.io/v1';d['metadata']['annotations']={'nginx.ingress.kubernetes.io/proxy-read-timeout':'3600','nginx.ingress.kubernetes.io/proxy-send-timeout':'3600','nginx.ingress.kubernetes.io/proxy-buffering':'off','nginx.ingress.kubernetes.io/proxy-body-size':'32m'}
    policy('gateway',{'matchLabels':{'app':'gateway'}},ingress,[dns,{'to':[{'podSelector':{'matchLabels':{'component':'runtime'}}}],'ports':[port(3081),port(7681),port(3000)]}])
    policy('filtered-dns',{'matchLabels':{'app':'filtered-dns'}},[{'from':[{'podSelector':{}}],'ports':[{'protocol':'UDP','port':5353},port(5353)]}],[cluster_dns])
    return docs

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    docs=build(yaml.safe_load(a.config.read_text()));a.output.mkdir(parents=True,exist_ok=True)
    # No Secret values are emitted. Operators provision them separately.
    (a.output/'namespace.yaml').write_text(yaml.safe_dump_all([x for x in docs if x['kind']=='Namespace'],sort_keys=False))
    (a.output/'storage.yaml').write_text(yaml.safe_dump_all([x for x in docs if x['kind']=='PersistentVolumeClaim'],sort_keys=False))
    (a.output/'download.yaml').write_text(yaml.safe_dump_all([x for x in docs if x['kind']=='Job'],sort_keys=False))
    (a.output/'platform.yaml').write_text(yaml.safe_dump_all([x for x in docs if x['kind'] not in ['Namespace','PersistentVolumeClaim','Job']],sort_keys=False))
    print(json.dumps({'objects':len(docs),'secretValuesRendered':False}))

if __name__=='__main__':main()
