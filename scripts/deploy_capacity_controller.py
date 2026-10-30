"""Prepare/apply isolated or accepted automatic signup capacity. Private artifacts only.

The gateway never receives a Kubernetes token or the credential-issuer key.
No existing execution workload or data/history directory is replaced.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from gateway_sources import gateway_sources, gateway_sources_sha256, gateway_configmap_items
import re
import subprocess
import uuid

ROOT=Path(__file__).parents[1]


def reviewed_template(document):
    if document.get('kind')!='Deployment' or document.get('apiVersion')!='apps/v1':raise ValueError('Expected an apps/v1 Deployment')
    return {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':document['metadata']['name']},'spec':copy.deepcopy(document['spec'])}


def gateway_capacity(spec, source, policy_claim, inventory_claim, namespace):
    value=copy.deepcopy(spec);pod=value['template']['spec'];container=pod['containers'][0]
    if pod.get('automountServiceAccountToken')is not False or value.get('replicas')!=1:raise ValueError('Capacity requires one gateway writer with no management token')
    names={'capacity-policy','capacity-inventory'}
    if any(v['name']in names for v in pod['volumes']):raise ValueError('Capacity already installed; explicit upgrade required')
    pod['volumes'] += [{'name':'capacity-policy','persistentVolumeClaim':{'claimName':policy_claim}},
        {'name':'capacity-inventory','persistentVolumeClaim':{'claimName':inventory_claim}}]
    container['volumeMounts'] += [{'name':'capacity-policy','mountPath':'/capacity/policy'},
        {'name':'capacity-inventory','mountPath':'/capacity/inventory','readOnly':True},
        {'name':'capacity-inventory','mountPath':'/runtime-tokens/capacity','subPath':'runtime-tokens','readOnly':True}]
    container['env']=[e for e in container['env']if e['name']not in ['DSH_CAPACITY_ROOT','DSH_NAMESPACE']]+[
        {'name':'DSH_CAPACITY_ROOT','value':'/capacity'},{'name':'DSH_NAMESPACE','value':namespace}]
    next(v for v in pod['volumes']if v['name']=='gateway-source')['configMap']['name']=source
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubectl',default='kubectl');parser.add_argument('--namespace',default='llm')
    parser.add_argument('--gateway',default='dsh-environment-gateway');parser.add_argument('--template-user',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--canary',action='store_true')
    parser.add_argument('--expected-source-sha256',help='Required live gateway source digest for an accepted Production handover')
    parser.add_argument('--max-accounts',type=int,help='Initial account ceiling; dashboard changes persist after installation')
    parser.add_argument('--additional-account-deployment',action='append',default=[],metavar='NAME=LABEL',help='Additional fixed-owner deployment sharing this cluster; repeat for each instance')
    parser.add_argument('--warm-spares',type=int,default=2)
    parser.add_argument('--manual-dir',help='Previously published immutable manual directory for this handover')
    parser.add_argument('--instance',default='qa',help='Unique disposable canary installation identifier')
    parser.add_argument('--apply',action='store_true');parser.add_argument('--acceptance',type=Path)
    args=parser.parse_args()
    if args.manual_dir and not re.fullmatch(r'/auth/manuals/[a-f0-9]{16}',args.manual_dir):raise ValueError('Invalid immutable manual directory')
    for value in [args.namespace,args.gateway,args.template_user]:
        if not re.fullmatch(r'[a-z0-9_.-]{3,63}',value):raise ValueError('Invalid site identifier')
    if args.template_user in ['admin','thanatcc']:raise ValueError('Use an ordinary private user template')
    args.output.mkdir(parents=True,exist_ok=False)
    def kube(*parts,source=None,timeout=45):
        result=subprocess.run([args.kubectl,'-n',args.namespace,'--request-timeout=30s',*parts],input=source,
            capture_output=True,text=True,encoding='utf8',timeout=timeout)
        if result.returncode:raise RuntimeError(result.stderr[-300:])
        return result.stdout
    get=lambda kind,name=None:json.loads(kube('get',kind,*([name]if name else[]),'-o','json'))
    original=get('deploy',args.gateway)
    read="const f=require('fs'),e=process.env;console.log(JSON.stringify({pool:JSON.parse(f.readFileSync(e.DSH_SIGNUP_POOL_FILE)),routes:JSON.parse(f.readFileSync(e.DSH_USER_TARGETS_FILE)),count:Object.keys(JSON.parse(f.readFileSync(e.DSH_USER_STORE_PATH))).length,source:require('crypto').createHash('sha256').update(f.readFileSync('/gateway-source/auth_proxy.js')).digest('hex')}));"
    current=json.loads(kube('exec','deploy/'+args.gateway,'--','node','-e',read))
    templates={env:get('deploy',target['host'].split('.')[0])for env,target in current['routes'][args.template_user].items()}
    if set(templates)!={'secure','internet'}:raise ValueError('Private pair required')
    referenced={v['persistentVolumeClaim']['claimName']for d in templates.values()for v in d['spec']['template']['spec']['volumes']if 'persistentVolumeClaim'in v}
    claims={c['metadata']['name']:{'spec':{key:c['spec'][key]for key in ['accessModes','resources','storageClassName','volumeMode']if key in c['spec']}}for c in get('pvc')['items']if c['metadata']['name']in referenced}
    templates={env:reviewed_template(d)for env,d in templates.items()}
    from prepare_signup_pool import generate
    probe,_,_=generate(templates,claims,'cap-preflight',1)
    if any(d.get('kind')not in ['Deployment','Service','PersistentVolumeClaim']or not d.get('apiVersion')for d in probe):raise ValueError('Generated Kubernetes resource envelope is incomplete')
    issuer=next(c for c in get('deploy','litellm')['spec']['template']['spec']['containers']if c['name']=='litellm')
    issuer_ref=copy.deepcopy(next(e for e in issuer['env']if e['name']=='LITELLM_MASTER_KEY')['valueFrom']['secretKeyRef'])
    if not re.fullmatch(r'qa[a-z0-9-]{0,12}',args.instance):raise ValueError('Invalid canary identifier')
    prefix='dsh-cap-'+args.instance if args.canary else'dsh-cap-live'
    image=next(c for c in templates['secure']['spec']['template']['spec']['containers']if c['name']=='dsh')['image']
    if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}',image):raise ValueError('Pinned qualified image required')
    source_files={p.name:p.read_text(encoding='utf8')for p in [
        *[ROOT/'scripts'/n for n in ['auth_proxy.js','password_store.js','session_store.js','capacity_policy.js','signup_admission.js','course_files.js','package_portal.js','capacity_controller.py','capacity_planner.py','capacity_report.py','capacity_worker.py','capacity_kube.py','prepare_signup_pool.py','deploy_app_supervision.py']],
        ROOT/'container/app-supervisor.py',ROOT/'container/capacity-token-exporter.py']}
    source_files.update(gateway_sources(ROOT))
    digest=hashlib.sha256(json.dumps(source_files,sort_keys=True).encode()).hexdigest()
    source_name='dsh-cap-source-'+digest[:12]
    source_document={'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':source_name},'data':source_files}
    auth_digest=hashlib.sha256(source_files['auth_proxy.js'].encode()).hexdigest()
    if args.apply and not args.canary:
        if not args.acceptance:raise ValueError('Real isolated signup/replenishment acceptance required')
        accepted=json.loads(args.acceptance.read_text(encoding='utf8'))
        if accepted.get('status')!='passed'or accepted.get('sourceBundleSHA256')!=digest or not accepted.get('automaticReplenishmentVerified')or not accepted.get('restartPersistenceVerified'):
            raise ValueError('Matching acceptance is required')
    initial_pool={'slots':{}}if args.canary else current['pool']
    count=1 if args.canary else current['count']
    maximum=args.max_accounts if args.max_accounts is not None else(4 if args.canary else 16)
    if type(maximum)is not int or not max(1,count)<=maximum<=32 or not 0<=args.warm_spares<=min(8,maximum):raise ValueError('Invalid initial capacity; preserve all existing accounts')
    if args.apply and not args.canary and current['source']!=args.expected_source_sha256:raise ValueError('Live gateway source changed; inspect before handover')
    policy={'version':1,'enabled':True,'warmSpareSlots':args.warm_spares,'maxAccounts':maximum}
    policy_claim=prefix+'-policy';inventory_claim=prefix+'-inventory'
    control_claim=prefix+'-services'if args.canary else next(v['persistentVolumeClaim']['claimName']for v in original['spec']['template']['spec']['volumes']if v['name']=='app-service-control')
    central_claim='dsh-da-workspace-secure'
    trusted=next(e['value']for e in original['spec']['template']['spec']['containers'][0]['env']if e['name']=='DSH_TRUSTED_HOST')
    additional=[]
    for item in args.additional_account_deployment:
        name,separator,label=item.partition('=')
        if not separator or not re.fullmatch(r'[a-z0-9.-]{1,63}',name)or not re.fullmatch(r'[A-Za-z0-9 -]{1,40}',label):raise ValueError('Use NAME=LABEL for additional fixed-owner deployments')
        additional.append({'name':name,'label':label})
    config={'namespace':args.namespace,'templateFile':'/capacity-source/templates.json','sourceConfigMap':source_name,
        'additionalAccountDeployments':additional,
        'issuerKeyFile':'/issuer/key','litellmBase':'http://litellm.'+args.namespace+'.svc.cluster.local:4000',
        'inventoryPVC':inventory_claim,'serviceControlPVC':control_claim,'storageClass':'topolvm','trustedHost':trusted,
        'reserveCPU':2,'reserveMemoryGiB':32,'reserveStorageGiB':32,'reservePods':10}
    site={'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':prefix+'-site-'+digest[:12]},
        'data':{'site.json':json.dumps(config),'templates.json':json.dumps({'templates':templates,'claims':claims}),
                'initial-pool.json':json.dumps(initial_pool),'initial-policy.json':json.dumps(policy)}}
    # Site ConfigMap is private to the installation; never commit generated data.
    context={'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']},'seccompProfile':{'type':'RuntimeDefault'}}
    documents=[source_document,site]
    for name in [policy_claim,inventory_claim]+([control_claim,prefix+'-auth']if args.canary else[]):
        documents.append({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':name},'spec':{
            'accessModes':['ReadWriteOnce'],'storageClassName':'topolvm','resources':{'requests':{'storage':'100Mi'}}}})
    sa=prefix+'-controller'
    documents += [{'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':sa}},
        {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role','metadata':{'name':sa},'rules':[
            {'apiGroups':[''],'resources':['services','secrets','persistentvolumeclaims'],'verbs':['get','create']},
            {'apiGroups':['apps'],'resources':['deployments'],'verbs':['get','list','create']},
            # First-come sessions: start a private runtime on demand, stop it when idle.
            {'apiGroups':['apps'],'resources':['deployments/scale'],'verbs':['get','patch']}]},
        {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':{'name':sa},
            'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':sa},'subjects':[{'kind':'ServiceAccount','name':sa,'namespace':args.namespace}]},
        {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRole','metadata':{'name':sa+'-'+args.namespace},'rules':[
            {'apiGroups':[''],'resources':['nodes','pods'],'verbs':['get','list']},
            {'apiGroups':['storage.k8s.io'],'resources':['csistoragecapacities'],'verbs':['get','list']},
            {'apiGroups':['metrics.k8s.io'],'resources':['nodes'],'verbs':['get','list']}]},
        {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRoleBinding','metadata':{'name':sa+'-'+args.namespace},
            'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':sa+'-'+args.namespace},'subjects':[{'kind':'ServiceAccount','name':sa,'namespace':args.namespace}]}]
    volumes=[{'name':'source','configMap':{'name':source_name}},{'name':'site','configMap':{'name':site['metadata']['name']}},
        {'name':'policy','persistentVolumeClaim':{'claimName':policy_claim}},{'name':'inventory','persistentVolumeClaim':{'claimName':inventory_claim}},
        {'name':'central','persistentVolumeClaim':{'claimName':central_claim}},{'name':'services','persistentVolumeClaim':{'claimName':control_claim}},
        {'name':'issuer','secret':{'secretName':issuer_ref['name'],'items':[{'key':issuer_ref['key'],'path':'key'}]}}]
    mounts=[{'name':'source','mountPath':'/controller','readOnly':True},{'name':'site','mountPath':'/capacity-source','readOnly':True},
        {'name':'policy','mountPath':'/capacity/policy','readOnly':True},{'name':'inventory','mountPath':'/capacity/inventory'},
        {'name':'central','mountPath':'/central'},{'name':'services','mountPath':'/service-control'},{'name':'issuer','mountPath':'/issuer','readOnly':True}]
    controller={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':sa},'spec':{'replicas':1,'strategy':{'type':'Recreate'},
        'selector':{'matchLabels':{'app':sa}},'template':{'metadata':{'labels':{'app':sa,'dsh.example.com/capacity-controller':prefix}},
        'spec':{'serviceAccountName':sa,'securityContext':{'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},
        'volumes':volumes,'containers':[{'name':'controller','image':image,'command':['python3','/controller/capacity_controller.py'],
            'env':[{'name':'PYTHONDONTWRITEBYTECODE','value':'1'},{'name':'PYTHONUNBUFFERED','value':'1'}],
            'securityContext':context,'volumeMounts':mounts,'resources':{'requests':{'cpu':'25m','memory':'64Mi'},'limits':{'cpu':'500m','memory':'256Mi'}}}]}}}}
    controller['spec']['template']['spec']['imagePullSecrets']=copy.deepcopy(original['spec']['template']['spec'].get('imagePullSecrets',[]))
    controller['spec']['template']['spec']['dnsPolicy']=original['spec']['template']['spec'].get('dnsPolicy','ClusterFirst')
    if 'dnsConfig'in original['spec']['template']['spec']:controller['spec']['template']['spec']['dnsConfig']=copy.deepcopy(original['spec']['template']['spec']['dnsConfig'])
    documents.append(controller)
    gateway=copy.deepcopy(original)
    if args.canary:
        gateway['metadata']={'name':prefix+'-gateway'};gateway.pop('status',None)
        gateway['spec']['selector']['matchLabels']={'app':prefix+'-gateway'}
        pod=gateway['spec']['template']['spec'];c=pod['containers'][0]
        gateway['spec']['template']['metadata']={'labels':{'app':prefix+'-gateway','dsh.example.com/capacity-gateway':prefix}}
        # Only the isolated auth/control and explicit test routes survive. Do not
        # mount Production accounts, legacy launch tokens or audit histories.
        retained={'gateway-source'}
        pod['volumes']=[v for v in pod['volumes']if v['name']in retained]
        c['volumeMounts']=[m for m in c['volumeMounts']if m['name']in retained]
        pod['volumes'] += [{'name':'auth','persistentVolumeClaim':{'claimName':prefix+'-auth'}},
            {'name':'app-service-control','persistentVolumeClaim':{'claimName':control_claim}},{'name':'qa-config','configMap':{'name':site['metadata']['name']}}]
        c['volumeMounts'] += [{'name':'auth','mountPath':'/auth'},{'name':'app-service-control','mountPath':'/app-services'},
            {'name':'qa-config','mountPath':'/qa-config','readOnly':True}]
        remove={'WORKSPACE_ROOT','DSH_USER_STORE_PATH','DSH_USER_SETTINGS_PATH','DSH_AUDIT_DIR','DSH_USER_TARGETS_FILE','DSH_SIGNUP_POOL_FILE','DSH_SERVICE_TARGETS_FILE','DSH_MANUAL_DIR','DSH_APP_INVENTORY_FILE','DSH_ADMIN_SUMMARY_FILE','DSH_APP_LINKS_PATH','DSH_APP_POLICY_PATH','DSH_ADMIN_PASS','DSH_AUTH_PASS','DSH_ALLOW_REGISTRATION','DSH_APP_SERVICES_ROOT'}
        c['env']=[e for e in c['env']if e['name']not in remove]
        c['env'] += [{'name':name,'value':value}for name,value in {'WORKSPACE_ROOT':'/auth/workspaces','DSH_USER_STORE_PATH':'/auth/users.json','DSH_USER_SETTINGS_PATH':'/auth/settings.json',
            'DSH_AUDIT_DIR':'/auth/audit','DSH_USER_TARGETS_FILE':'/qa-config/routes.json','DSH_SIGNUP_POOL_FILE':'/qa-config/initial-pool.json',
            'DSH_ALLOW_REGISTRATION':'true','DSH_APP_SERVICES_ROOT':'/app-services','DSH_COOKIE_NAME':'dsh_capacity_qa'}.items()]
        site['data']['routes.json']=json.dumps({'admin':{'secure':{'host':'unprovisioned.invalid','port':3081,'tokenFile':'/runtime-tokens/absent'}}})
    old_site=site['metadata']['name'];site['metadata']['name']=prefix+'-site-'+hashlib.sha256(json.dumps(site['data'],sort_keys=True).encode()).hexdigest()[:12]
    for object in documents+[gateway]:
        if object['kind']=='Deployment':
            for volume in object['spec']['template']['spec'].get('volumes',[]):
                if volume.get('configMap',{}).get('name')==old_site:volume['configMap']['name']=site['metadata']['name']
    gateway['spec']=gateway_capacity(gateway['spec'],source_name,policy_claim,inventory_claim,args.namespace)
    next(v for v in gateway['spec']['template']['spec']['volumes'] if v['name']=='gateway-source')['configMap']['items']=gateway_configmap_items(source_files)
    if args.manual_dir:
        if args.canary:raise ValueError('A candidate must not mount Production manuals')
        c=gateway['spec']['template']['spec']['containers'][0]
        c['env']=[e for e in c['env']if e['name']!='DSH_MANUAL_DIR']+[{'name':'DSH_MANUAL_DIR','value':args.manual_dir}]
    documents.append(gateway)
    api=json.loads(kube('get','service','kubernetes','-n','default','-o','json'))
    endpoints=json.loads(kube('get','endpoints','kubernetes','-n','default','-o','json'))
    addresses=[api['spec']['clusterIP']]+[v['ip']for subset in endpoints.get('subsets',[])for v in subset.get('addresses',[])]
    api_rules=[{'to':[{'ipBlock':{'cidr':ip+('/128'if ':'in ip else'/32')}}],
        'ports':[{'protocol':'TCP','port':443},{'protocol':'TCP','port':6443}]}for ip in addresses]
    dns=original['spec']['template']['spec'].get('dnsConfig',{}).get('nameservers',[])
    dns_rules=[{'to':[{'ipBlock':{'cidr':ip+('/128'if ':'in ip else'/32')}}],
        'ports':[{'protocol':protocol,'port':53}for protocol in ['UDP','TCP']]}for ip in dns]
    services=json.loads(kube('get','services','-A','-o','json'))['items']
    for resolver in services:
        if resolver['spec'].get('clusterIP')in dns and resolver['spec'].get('selector'):
            ports=[{'protocol':p.get('protocol','TCP'),'port':p.get('targetPort',p['port'])}for p in resolver['spec']['ports']]
            dns_rules.append({'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':resolver['metadata']['namespace']}},
                'podSelector':{'matchLabels':resolver['spec']['selector']}}],'ports':ports})
            if resolver['metadata']['namespace']!=args.namespace:raise ValueError('Review cross-namespace resolver ingress before installation')
            documents.append({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':prefix+'-resolver-ingress'},'spec':{
                'podSelector':{'matchLabels':resolver['spec']['selector']},'policyTypes':['Ingress'],
                'ingress':[{'from':[{'podSelector':{'matchLabels':{'app':sa}}},{'podSelector':{'matchLabels':{'dsh.example.com/capacity-gateway':prefix}}}],'ports':ports}]}})
    if not dns_rules:raise ValueError('Explicit reviewed internal DNS required for provisioner')
    model_selector=get('service','litellm')['spec']['selector']
    private_selector={'dsh.example.com/capacity-managed':'true'}
    # Preserve the shared model service's ingress boundary. A new Ingress
    # policy would isolate every pre-existing caller when none existed before.
    # Sites with pre-existing ingress isolation must explicitly allow this
    # controller through that site's reviewed policy before qualification.
    documents += [
        {'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':prefix+'-controller'},'spec':{
            'podSelector':{'matchLabels':{'app':sa}},'policyTypes':['Ingress','Egress'],'ingress':[],
            'egress':dns_rules+api_rules+[{'to':[{'podSelector':{'matchLabels':model_selector}}],'ports':[{'protocol':'TCP','port':4000}]},
                {'to':[{'podSelector':{'matchLabels':private_selector}}],'ports':[{'protocol':'TCP','port':3081}]}]}},
        {'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':prefix+'-private-ingress'},'spec':{
            'podSelector':{'matchLabels':private_selector},'policyTypes':['Ingress'],'ingress':[
                {'from':[{'podSelector':{'matchLabels':{'app':args.gateway}}},{'podSelector':{'matchLabels':{'dsh.example.com/capacity-gateway':prefix}}}]},
                {'from':[{'podSelector':{'matchLabels':{'app':sa}}}],'ports':[{'protocol':'TCP','port':3081}]}]}}
    ]
    if args.canary:
        documents.append({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':prefix+'-gateway-egress'},'spec':{
            'podSelector':{'matchLabels':{'dsh.example.com/capacity-gateway':prefix}},'policyTypes':['Ingress','Egress'],'ingress':[],
            'egress':dns_rules+[{'to':[{'podSelector':{'matchLabels':private_selector}}]}]}})
    seed_code="""const f=require('fs'),c=require('crypto'),p=require('/source/password_store.js');
for(const d of ['/policy','/inventory','/inventory/runtime-tokens','/inventory/runtime-status'])f.mkdirSync(d,{recursive:true,mode:448});
const pool=JSON.parse(f.readFileSync('/site/initial-pool.json'));
for(const [file,value]of [['/policy/policy.json',JSON.parse(f.readFileSync('/site/initial-policy.json'))],['/inventory/pool.json',pool],['/inventory/inventory.json',{slots:Object.fromEntries(Object.entries(pool.slots).map(([k,routes])=>[k,{state:'ready',routes}]))}]])if(!f.existsSync(file))f.writeFileSync(file,JSON.stringify(value),{mode:384});
if(process.env.CANARY==='true'&&!f.existsSync('/auth/users.json')){const password=c.randomBytes(24).toString('hex');p.writeAtomicUsers('/auth/users.json',{admin:p.hashPassword(password)});f.writeFileSync('/auth/acceptance-admin.private.json',JSON.stringify({password}),{mode:384});}
"""
    seed_volumes=[{'name':n,'persistentVolumeClaim':{'claimName':v}}for n,v in [('policy',policy_claim),('inventory',inventory_claim)]]+[
        {'name':'source','configMap':{'name':source_name}},{'name':'site','configMap':{'name':site['metadata']['name']}}]
    seed_mounts=[{'name':n,'mountPath':'/'+n,'readOnly':n in ['source','site']}for n in ['policy','inventory','source','site']]
    if args.canary:seed_volumes.append({'name':'auth','persistentVolumeClaim':{'claimName':prefix+'-auth'}});seed_mounts.append({'name':'auth','mountPath':'/auth'})
    seed={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':prefix+'-initialize-'+uuid.uuid4().hex[:6]},'spec':{'backoffLimit':0,'activeDeadlineSeconds':120,
        'template':{'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,'securityContext':{'fsGroup':10001},'volumes':seed_volumes,
        'containers':[{'name':'initialize','image':image,'command':['node','-e',seed_code],'securityContext':context,'volumeMounts':seed_mounts,
            'env':[{'name':'CANARY','value':str(args.canary).lower()}]}]}}}}
    seed['spec']['template']['spec']['imagePullSecrets']=copy.deepcopy(original['spec']['template']['spec'].get('imagePullSecrets',[]))
    from capacity_network_guard import guard
    baseline=get('networkpolicy')['items']
    existing=get('deploy')['items']+get('pods')['items']
    boundary=guard([d for d in documents if d['kind']=='NetworkPolicy'],baseline,existing,{sa,prefix+'-gateway'}if args.canary else{sa})
    (args.output/'resources.private.json').write_text(json.dumps(documents),encoding='utf8')
    (args.output/'gateway-before.private.json').write_text(json.dumps(original),encoding='utf8')
    (args.output/'seed.private.json').write_text(json.dumps(seed),encoding='utf8')
    (args.output/'plan.json').write_text(json.dumps({'canary':args.canary,'sourceBundleSHA256':digest,'gatewaySourceSHA256':auth_digest,
        'gateway':gateway['metadata']['name'],'controller':sa,'warmSpareSlots':policy['warmSpareSlots'],'maxAccounts':policy['maxAccounts'],'existingDataModified':False,'sharedIngressGuard':boundary}),encoding='utf8')
    if not args.apply:print(json.dumps({'prepared':True,'applied':False,'canary':args.canary}));return
    # Do not activate the controller until the isolated gateway produces fresh
    # account projections. Its initial stale-state decision creates nothing.
    preliminary=[d for d in documents if d['kind']!='Deployment']
    for document in preliminary:kube('apply','-f','-',source=json.dumps(document))
    kube('apply','-f','-',source=json.dumps(seed));kube('wait','--for=condition=complete','job/'+seed['metadata']['name'],'--timeout=120s',timeout=140)
    if args.canary:kube('apply','-f','-',source=json.dumps(gateway))
    else:
        patch_file=args.output/'gateway-patch.private.json'
        patch_file.write_text(json.dumps([{'op':'test','path':'/spec/template','value':original['spec']['template']},{'op':'replace','path':'/spec','value':gateway['spec']}]),encoding='utf8')
        kube('patch','deploy',args.gateway,'--type=json','--patch-file',str(patch_file))
    for attempt in range(60):
        state=get('deploy',gateway['metadata']['name'])
        if state.get('status',{}).get('observedGeneration',0)>=state['metadata']['generation'] and state.get('status',{}).get('updatedReplicas')==1 and state.get('status',{}).get('availableReplicas')==1:break
        __import__('time').sleep(3)
    else:raise RuntimeError('Gateway handover readiness deadline; retain rollback artifacts')
    kube('apply','-f','-',source=json.dumps(controller))
    print(json.dumps({'applied':True,'canary':args.canary,'sourceBundleSHA256':digest,'gatewaySourceSHA256':auth_digest,'existingExecutionWorkloadsChanged':False}))


if __name__=='__main__':main()
