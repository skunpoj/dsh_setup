"""Install read-only service control and a non-root supervisor; preserve original mounts.

The default renders a plan. --apply installs only explicitly selected workers.
Control is a dedicated PVC, never the gateway password/account volume.
"""
import argparse,copy,hashlib,json,re,subprocess,time,uuid
from pathlib import Path


def key(host,mode):return hashlib.sha256((host+'|'+mode).encode()).hexdigest()[:24]


def sidecar(deployment,configmap,control_pvc,identity):
    d=copy.deepcopy(deployment);pod=d['spec']['template']['spec']
    if pod.get('shareProcessNamespace'):raise ValueError('Shared process namespace is not supported')
    main=next(c for c in pod['containers'] if c['name']=='dsh')
    if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}',main['image']):raise ValueError('Pinned image required')
    if any(c['name']=='app-supervisor' for c in pod['containers']):raise ValueError('Supervisor already installed; use an explicit upgrade')
    state=next(m for m in main['volumeMounts'] if m['mountPath']=='/state')
    notebook={'name':state['name'],'mountPath':'/state/jupyter','subPath':('/'.join([state.get('subPath','').strip('/'),'jupyter'])).lstrip('/')}
    mounts=[copy.deepcopy(m) for m in main['volumeMounts'] if m['mountPath']=='/workspace' or m['mountPath'].startswith('/workspace/') or m['mountPath'].startswith('/packages/approved')]
    mounts += [notebook,{'name':'app-supervisor-source','mountPath':'/service-source','readOnly':True},
               {'name':'app-service-control','mountPath':'/service-control','subPath':identity,'readOnly':True},
               {'name':'app-service-status','mountPath':'/service-status'},
               {'name':'app-supervisor-tmp','mountPath':'/tmp'}]
    env=[copy.deepcopy(e) for e in main.get('env',[]) if e['name'] in ['DSH_TRUSTED_HOST','DSH_ENVIRONMENT']]
    env += [{'name':'HOME','value':'/tmp/service-home'},{'name':'PYTHONDONTWRITEBYTECODE','value':'1'}]
    if next((e.get('value') for e in env if e['name']=='DSH_ENVIRONMENT'),None)=='secure':
        env += [{'name':'PIP_NO_INDEX','value':'1'},{'name':'PIP_FIND_LINKS','value':'/packages/approved/python'},{'name':'npm_config_offline','value':'true'}]
    pod['containers'].append({'name':'app-supervisor','image':main['image'],'command':['python3','/service-source/app-supervisor.py'],
       'env':env,'volumeMounts':mounts,'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']},'seccompProfile':{'type':'RuntimeDefault'}},
       'resources':{'requests':{'cpu':'25m','memory':'64Mi'},'limits':{'cpu':'1','memory':'1Gi'}}})
    pod.setdefault('volumes',[]).extend([{'name':'app-supervisor-source','configMap':{'name':configmap}},
        {'name':'app-service-control','persistentVolumeClaim':{'claimName':control_pvc}}, {'name':'app-service-status','persistentVolumeClaim':{'claimName':'dsh-app-status-'+identity}}, {'name':'app-supervisor-tmp','emptyDir':{'sizeLimit':'64Mi'}}])
    pod['automountServiceAccountToken']=False
    return d


def gateway_control_spec(original,control_pvc,identities):
    spec=copy.deepcopy(original);pod=spec['template']['spec'];c=pod['containers'][0]
    if not any(v['name']=='app-service-control' for v in pod.get('volumes',[])):
        pod['volumes'].append({'name':'app-service-control','persistentVolumeClaim':{'claimName':control_pvc}});c['volumeMounts'].append({'name':'app-service-control','mountPath':'/app-services'})
    c['env']=[e for e in c['env']if e['name']!='DSH_APP_SERVICES_ROOT']+[{'name':'DSH_APP_SERVICES_ROOT','value':'/app-services'}]
    for identity in identities:
        volume='app-status-'+identity
        if not any(v['name']==volume for v in pod['volumes']):
            pod['volumes'].append({'name':volume,'persistentVolumeClaim':{'claimName':'dsh-app-status-'+identity}})
            c['volumeMounts'].append({'name':volume,'mountPath':'/app-services/'+identity+'/status','readOnly':True})
    return spec


def initialize_control(k,gateway,claim,identities):
    job='dsh-service-control-init-'+uuid.uuid4().hex[:10]
    code="const f=require('fs');for(const n of "+json.dumps(identities)+"){const p='/control/'+n;f.mkdirSync(p+'/status',{recursive:true,mode:448});if(!f.existsSync(p+'/config.json'))f.writeFileSync(p+'/config.json',JSON.stringify({allowed:false,services:{}}),{mode:384});}"
    pod={'restartPolicy':'Never','automountServiceAccountToken':False,'securityContext':{'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'initialize','image':gateway['spec']['template']['spec']['containers'][0]['image'],'command':['node','-e',code],'securityContext':{'runAsNonRoot':True,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},'volumeMounts':[{'name':'control','mountPath':'/control'}]}],'volumes':[{'name':'control','persistentVolumeClaim':{'claimName':claim}}]}
    if 'imagePullSecrets' in gateway['spec']['template']['spec']:pod['imagePullSecrets']=copy.deepcopy(gateway['spec']['template']['spec']['imagePullSecrets'])
    k('apply','-f','-',data=json.dumps({'apiVersion':'batch/v1','kind':'Job','metadata':{'name':job},'spec':{'backoffLimit':0,'activeDeadlineSeconds':120,'template':{'spec':pod}}}))
    k('wait','--for=condition=complete','job/'+job,'--timeout=120s');k('delete','job',job,'--wait=true')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gateway',default='dsh-environment-gateway');p.add_argument('--targets',type=Path,required=True,help='Private array of {user,mode,host}; no credentials')
    p.add_argument('--platform-guide-configmap');p.add_argument('--guide-acceptance',type=Path);p.add_argument('--namespace',default='llm');p.add_argument('--storage-class',default='topolvm');p.add_argument('--control-pvc',default='dsh-app-service-control');p.add_argument('--output',type=Path,required=True);p.add_argument('--kubectl',default='kubectl');p.add_argument('--apply',action='store_true');p.add_argument('--acceptance',type=Path);p.add_argument('--test-only',action='store_true');a=p.parse_args()
    for value in [a.namespace,a.storage_class,a.control_pvc]:assert re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,251}[a-z0-9]',value)
    targets=json.loads(a.targets.read_text(encoding='utf-8'));assert targets and len(targets)<=64
    for t in targets:assert re.fullmatch(r'[a-z0-9_.-]{3,30}',t['user']) and t['mode'] in ['off','on'] and re.fullmatch(r'[a-z0-9.-]{3,253}',t['host'])
    assert len({key(t['host'],t['mode']) for t in targets})==len(targets)
    def k(*v,data=None):return subprocess.check_output([a.kubectl,'-n',a.namespace,'--request-timeout=30s',*v],input=data,text=True,encoding='utf-8',timeout=190)
    source=(Path(__file__).parents[1]/'container/app-supervisor.py').read_text(encoding='utf-8');sha=hashlib.sha256(source.encode()).hexdigest();cm='dsh-app-supervisor-'+sha[:12]
    if a.platform_guide_configmap:
        if not a.guide_acceptance:raise ValueError('Four-client guide qualification required')
        guide=json.loads(a.guide_acceptance.read_text(encoding='utf-8'));assert guide.get('fourClientGuideLoadVerified') and guide.get('markerWasNotInUserPrompt')
        assert {r['client']for r in guide['results']}=={'dsh','claude','kilo','trueforge'} and all(r['exact'] for r in guide['results'])
        from platform_guide_overlay import transform as guide_transform
    workers=[]
    for t in targets:
        d=json.loads(k('get','deploy',t['host'].split('.')[0],'-o','json'))
        test_label=d['metadata'].get('labels',{}).get('dsh.example.com/signup-pool','')
        if a.test_only:
            if not re.fullmatch(r'(?:qa|test|appstart)-[a-z0-9-]+',test_label):raise ValueError('Explicit disposable test label required')
        else:
            if not a.acceptance:raise ValueError('Non-test rollout requires lifecycle acceptance')
            qualified=json.loads(a.acceptance.read_text());assert qualified['status']=='passed' and qualified['supervisorSHA256']==sha and qualified['automaticJupyterAndAppAfterPodReplacement']
        updated=sidecar(d,cm,a.control_pvc,key(t['host'],t['mode']))
        if a.platform_guide_configmap:updated['spec']=guide_transform(updated['spec'],a.platform_guide_configmap)
        workers.append((t,d,updated))
    a.output.mkdir(parents=True,exist_ok=False)
    for _,d,new in workers:(a.output/(d['metadata']['name']+'-before.private.json')).write_text(json.dumps(d))
    print(json.dumps({'apply':a.apply,'workers':len(workers),'supervisorSHA256':sha,'controlPVC':a.control_pvc}),flush=True)
    if not a.apply:return
    k('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':a.control_pvc},'spec':{'storageClassName':a.storage_class,'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'1Gi'}}}}))
    k('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':cm},'immutable':True,'data':{'app-supervisor.py':source}}))
    claims=[{'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':'dsh-app-status-'+key(t['host'],t['mode'])},'spec':{'storageClassName':a.storage_class,'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'1Gi'}}}}for t,_,_ in workers]
    k('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'List','items':claims}))
    gateway=json.loads(k('get','deploy',a.gateway,'-o','json'));(a.output/'gateway-before.private.json').write_text(json.dumps(gateway))
    initialize_control(k,gateway,a.control_pvc,[key(t['host'],t['mode'])for t,_,_ in workers])
    spec=gateway_control_spec(gateway['spec'],a.control_pvc,[key(t['host'],t['mode'])for t,_,_ in workers])
    k('patch','deploy',a.gateway,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':spec}]))
    k('rollout','status','deploy/'+a.gateway,'--timeout=150s')
    keys=[key(t['host'],t['mode']) for t,_,_ in workers]
    bootstrap="const f=require('fs');for(const n of "+json.dumps(keys)+"){const p='/app-services/'+n;f.mkdirSync(p+'/status',{recursive:true,mode:448});if(!f.existsSync(p+'/config.json'))f.writeFileSync(p+'/config.json',JSON.stringify({allowed:false,services:{}}),{mode:384});f.writeFileSync(p+'/ready','provisioned');}"
    k('exec','deploy/'+a.gateway,'--','node','-e',bootstrap)
    results=[]
    import importlib.util
    check_spec=importlib.util.spec_from_file_location('runtime_persistence',Path(__file__).with_name('rollout_jupyter_runtime.py'));check=importlib.util.module_from_spec(check_spec);check_spec.loader.exec_module(check)
    for t,old,new in workers:
        name=old['metadata']['name']
        baseline=json.loads(k('exec','-i','deploy/'+name,'-c','dsh','--','python3','-',data=check.SNAPSHOT))
        notebook_active=k('exec','deploy/'+name,'-c','dsh','--','python3','-c',"from pathlib import Path;import os;print(sum(1 for p in Path('/proc').glob('[0-9]*/cmdline') if p.parts[2]!=str(os.getpid()) and b'jupyter' in p.read_bytes()))").strip()!='0'
        if baseline['running'] or notebook_active:
            results.append({'worker':name,'status':'deferred-active-agent-or-notebook'});(a.output/'results.json').write_text(json.dumps(results,indent=2));continue
        (a.output/(name+'-persistence-before.private.json')).write_text(json.dumps(baseline))
        k('exec','deploy/'+name,'-c','dsh','--','mkdir','-p','/state/jupyter')
        marker='.app-service-rollout-'+uuid.uuid4().hex
        create="from pathlib import Path\nfor root in ['/workspace','/state/jupyter']:\n p=Path(root)/"+repr(marker)+"\n with p.open('xb')as f:f.write(b'durable-service-marker')"
        k('exec','deploy/'+name,'-c','dsh','--','python3','-c',create)
        current=json.loads(k('get','deploy',name,'-o','json'));assert current['spec']==old['spec'],'Concurrent worker change'
        try:
            k('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':new['spec']}]))
            k('rollout','status','deploy/'+name,'--timeout=180s')
            for attempt in range(10):
                try:
                    status=json.loads(k('exec','deploy/'+name,'-c','app-supervisor','--','cat','/service-status/status.json'));assert not status['error'];break
                except (subprocess.CalledProcessError,AssertionError):
                    if attempt==9:raise
                    time.sleep(2)
            after=json.loads(k('exec','-i','deploy/'+name,'-c','dsh','--','python3','-',data=check.SNAPSHOT))
            assert set(baseline['ids']).issubset(after['ids']) and baseline['sessionFiles']==after['sessionFiles'],'History persistence regression'
            assert after['uid']==baseline['uid'] and after['uid']!=0
            verify="from pathlib import Path\nfor root in ['/workspace','/state/jupyter']:\n p=Path(root)/"+repr(marker)+"\n assert p.read_bytes()==b'durable-service-marker'\n p.unlink()"
            k('exec','deploy/'+name,'-c','dsh','--','python3','-c',verify)

            results.append({'worker':name,'status':'passed','mountsPreserved':True,'durableMarkers':2,'historyIDs':len(baseline['ids']),'unchangedSessionFiles':len(baseline['sessionFiles'])})
        except BaseException:
            current=json.loads(k('get','deploy',name,'-o','json'))
            if current['spec']==new['spec']:
                k('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':old['spec']}]))
                k('rollout','status','deploy/'+name,'--timeout=180s')
            raise
        (a.output/'results.json').write_text(json.dumps(results,indent=2))


if __name__=='__main__':main()
