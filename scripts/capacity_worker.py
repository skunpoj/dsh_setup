"""Provision and qualify fresh runtime pairs with a separate trusted operator identity.

No pod exec, account-store access, existing workload updates, or data migration.
Site templates and Secret references are supplied only by an infrastructure owner.
"""
import base64
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import time
import urllib.request

from capacity_kube import Kube
from capacity_controller import atomic_json, read_json, read_config
from prepare_signup_pool import generate
from deploy_app_supervision import sidecar, key


def initialize_services(controls):
    """Publish defaults only for a new identity; never reset an admin Stop.

    A completed temporary file is linked exclusively into place, so concurrent
    initialization cannot overwrite existing policy or expose partial JSON.
    The unassigned pair stays disallowed until gateway account reconciliation.
    """
    controls = Path(controls)
    controls.mkdir(exist_ok=True)
    target = controls / 'config.json'
    temp = controls / ('.jupyter-default-' + secrets.token_hex(12))
    value = {'allowed': False, 'services': {'jupyter': {
        'name': 'jupyter', 'kind': 'jupyter', 'cwd': '/workspace',
        'argv': ['jupyter', 'lab'], 'port': 8888,
        'enabled': True, 'generation': 1}}}
    try:
        with temp.open('x', encoding='utf8') as stream:
            os.chmod(temp, 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, target, follow_symlinks=False)
        except FileExistsError:
            return False
        if hasattr(os, 'O_DIRECTORY'):
            descriptor = os.open(controls, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return True
    finally:
        temp.unlink(missing_ok=True)


def quantity(value):
    text=str(value)
    for unit, scale in [('Ki',1024),('Mi',1024**2),('Gi',1024**3),('Ti',1024**4),
                        ('k',1000),('K',1000),('M',1000**2),('G',1000**3),('T',1000**4),('P',1000**5),('E',1000**6),('n',1e-9),('m',.001)]:
        if text.endswith(unit):return float(text[:-len(unit)])*scale
    return float(text)


def effective_request(pod, resource):
    regular=sum(quantity(c.get('resources',{}).get('requests',{}).get(resource,'0'))for c in pod['spec']['containers'])
    initialization=0;sidecars=0
    for c in pod['spec'].get('initContainers',[]):
        request=quantity(c.get('resources',{}).get('requests',{}).get(resource,'0'))
        if c.get('restartPolicy')=='Always':
            sidecars+=request;initialization=max(initialization,sidecars)
        else:initialization=max(initialization,sidecars+request)
    pod_request=quantity(pod['spec'].get('resources',{}).get('requests',{}).get(resource,'0'))
    return max(regular+sidecars,initialization,pod_request)+quantity(pod['spec'].get('overhead',{}).get(resource,'0'))


def validate_runtime(pod, expected):
    actual=pod['spec'];wanted=expected['spec']['template']['spec']
    if actual.get('automountServiceAccountToken')is not False or any(actual.get(k)for k in ['hostNetwork','hostPID','shareProcessNamespace']):return False
    if {c['name']for c in actual['containers']}!={c['name']for c in wanted['containers']}:return False
    for volume in actual.get('volumes',[]):
        if 'hostPath'in volume or any('serviceAccountToken'in x for x in volume.get('projected',{}).get('sources',[])):return False
    for container in wanted['containers']:
        current=next(c for c in actual['containers']if c['name']==container['name']);security=current.get('securityContext',{})
        if current['image']!=container['image']or security.get('runAsNonRoot')is not True or security.get('allowPrivilegeEscalation')is not False:return False
        if 'ALL'not in security.get('capabilities',{}).get('drop',[]):return False
        if any(security.get(k)!=container['securityContext'][k]for k in ['runAsUser','runAsGroup','readOnlyRootFilesystem']if k in container['securityContext']):return False
        if current.get('command')!=container.get('command')or current.get('args')!=container.get('args'):return False
        if {e['name']:e for e in current.get('env',[])}!={e['name']:e for e in container.get('env',[])}:return False
        if len(current.get('volumeMounts',[]))!=len(container['volumeMounts']):return False
        for mount in container['volumeMounts']:
            matches=[m for m in current.get('volumeMounts',[])if m['mountPath']==mount['mountPath']]
            if len(matches)!=1 or any(matches[0].get(k,False if k=='readOnly'else None)!=mount.get(k,False if k=='readOnly'else None)for k in ['name','subPath','readOnly']):return False
    for volume in wanted['volumes']:
        for field in ['configMap','secret']:
            if field in volume:
                matches=[v for v in actual['volumes']if v['name']==volume['name']]
                name='name'if field=='configMap'else'secretName'
                if len(matches)!=1 or matches[0].get(field,{}).get(name)!=volume[field][name]:return False
        if 'persistentVolumeClaim'in volume:
            matches=[v for v in actual['volumes']if v['name']==volume['name']]
            if len(matches)!=1 or matches[0].get('persistentVolumeClaim',{}).get('claimName')!=volume['persistentVolumeClaim']['claimName']:return False
    statuses=pod.get('status',{}).get('containerStatuses',[])
    return all(any(s['name']==c['name']and s.get('ready')and s.get('imageID','').endswith(c['image'].split('@')[-1])for s in statuses)for c in wanted['containers'])


class Worker:
    def __init__(self, config, root):
        self.config=config;self.root=Path(root);self.kube=Kube(config['namespace']);self.phase='resource-check'
        self.template=read_config(config['templateFile'],1048576)
        self.central=Path(config.get('centralMount','/central'))
        self.services=Path(config.get('serviceControlMount','/service-control'))
        if not re.fullmatch(r'dsh-cap-[a-z0-9-]+',config['sourceConfigMap']):raise ValueError('Pinned provisioner source required')

    def resources(self):
        self.phase='resource-check'
        nodes=self.kube.call('GET','Node')['items']
        # Single-node installation: prevent accidentally applying this arithmetic
        # to heterogeneous nodes or treating aggregate CPU as schedulable space.
        if len(nodes)!=1:return {}
        node=nodes[0];alloc=node['status']['allocatable']
        pods=[p for p in self.kube.call('GET','AllPod')['items']if p['spec'].get('nodeName')in [None,node['metadata']['name']] and p['status']['phase']not in ['Succeeded','Failed']]
        cpu=sum(effective_request(p,'cpu')for p in pods)
        memory=sum(effective_request(p,'memory')for p in pods)
        from datetime import datetime,timezone
        try:
            metric=next(m for m in self.kube.call('GET','NodeMetrics')['items']if m['metadata']['name']==node['metadata']['name'])
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(metric['timestamp'].replace('Z','+00:00'))).total_seconds()
            if age < -5 or age > 90:return {}
            observed_cpu=quantity(metric['usage']['cpu']);observed_memory=quantity(metric['usage']['memory'])
            import math
            if not all(math.isfinite(x)and x>=0 for x in [observed_cpu,observed_memory]):return {}
        except (RuntimeError,KeyError,StopIteration,ValueError):return {}
        capacities=self.kube.call('GET','StorageCapacity')['items']
        storage=[quantity(c['capacity'])/1024**3 for c in capacities if c.get('storageClassName')==self.config['storageClass'] and c.get('capacity')]
        # Storage and requests are separate from live usage. Missing CSI capacity
        # fails closed rather than guessing that an unbound PVC will fit.
        if not storage:return {}
        # Derive the future pair's real generated claims and container requests;
        # retain conservative minimum budgets and include both token exporters.
        docs,_,_=generate(self.template['templates'],self.template['claims'],'cap-0000000000000000',1)
        future=[sidecar(d,self.config['sourceConfigMap'],self.config['serviceControlPVC'],'0'*24)
                for d in docs if d['kind']=='Deployment']
        pair_cpu=max(.25,sum(effective_request(d['spec']['template'],'cpu')for d in future)+.01)
        pair_memory=max(2.25,sum(effective_request(d['spec']['template'],'memory')for d in future)/1024**3+32/1024)
        pair_storage=max(23,sum(quantity(d['spec']['resources']['requests']['storage'])for d in docs if d['kind']=='PersistentVolumeClaim')/1024**3+2)
        resources={'cpu':{'available':max(0,quantity(alloc['cpu'])-max(cpu,observed_cpu)),'reserve':self.config.get('reserveCPU',2),'pairBudget':pair_cpu},
                   'memoryGiB':{'available':max(0,(quantity(alloc['memory'])-max(memory,observed_memory))/1024**3),'reserve':self.config.get('reserveMemoryGiB',32),'pairBudget':pair_memory},
                   'pods':{'available':max(0,int(alloc['pods'])-len(pods)),'reserve':self.config.get('reservePods',10),'pairBudget':len(future)},
                   'storageGiB':{'available':min(storage),'reserve':self.config.get('reserveStorageGiB',32),'pairBudget':pair_storage}}
        additional=[];complete='additionalAccountDeployments'in self.config
        for item in self.config.get('additionalAccountDeployments',[]):
            name,label=item['name'],item['label']
            if not re.fullmatch(r'[a-z0-9.-]{1,63}',name)or not re.fullmatch(r'[A-Za-z0-9 -]{1,40}',label):raise ValueError('Invalid additional deployment')
            d=self.kube.call('GET','Deployment',name)
            if not d:complete=False;continue
            owners={e['value']for c in d['spec']['template']['spec']['containers']for e in c.get('env',[])if e.get('name')=='AUTH_USER'and e.get('value')}
            if len(owners)!=1:complete=False;continue
            ownpods=[p for p in pods if all(p.get('metadata',{}).get('labels',{}).get(k)==v for k,v in d['spec']['selector']['matchLabels'].items())]
            additional.append({'label':label,'accounts':1,'desiredWorkers':d['spec'].get('replicas',1),
                               'readyWorkers':d.get('status',{}).get('readyReplicas',0),
                               'reservedCPU':sum(effective_request(p,'cpu')for p in ownpods),
                               'reservedMemoryGiB':sum(effective_request(p,'memory')for p in ownpods)/1024**3})
        try:
            s=os.statvfs(self.central);central_free=s.f_bavail*s.f_frsize/1024**3
        except OSError:central_free=None
        result={k:v['available']-v['reserve']-v['pairBudget']for k,v in resources.items()}
        return {'cpuAfterPair':result['cpu'],'memoryGiBAfterPair':result['memoryGiB'],
                'podsAfterPair':result['pods'],'storageGiBAfterPair':result['storageGiB'],
                'capacityInputs':{'resources':resources,'additionalDeployments':additional,
                                  'additionalDeploymentsComplete':complete,'centralStorageFreeGiB':central_free,
                                  'observedUsage':{'timestamp':metric['timestamp'],'cpu':observed_cpu,'memoryGiB':observed_memory/1024**3,'reservedCPU':cpu,'reservedMemoryGiB':memory/1024**3,
                                                   # Totals for the sign-in utilisation bars. GPU has no live usage metric here,
                                                   # so it is shown as allocated (requested) versus installed.
                                                   'cpuAllocatable':quantity(alloc['cpu']),'memoryGiBAllocatable':quantity(alloc['memory'])/1024**3,
                                                   'gpuAllocatable':quantity(alloc.get('nvidia.com/gpu','0')),
                                                   'gpuRequested':sum(effective_request(p,'nvidia.com/gpu')for p in pods)}}}

    def runtimes(self):
        """Private user runtime Deployments and their replica state."""
        from capacity_session import RUNTIME
        items = self.kube.call('GET', 'Deployment')['items']
        return {d['metadata']['name']: {'replicas': int(d['spec'].get('replicas', 1)),
                                        'ready': int(d.get('status', {}).get('readyReplicas', 0) or 0)}
                for d in items if RUNTIME.fullmatch(d['metadata']['name'])}

    def credential(self, name, field, messages):
        existing=self.kube.call('GET','Secret',name)
        if existing:
            if existing['metadata'].get('labels',{}).get('dsh.example.com/capacity-managed')!='true':raise ValueError('Secret collision')
            token=base64.b64decode(existing['data'][field]).decode()
        else:
            # Persist a fresh planned token before issuance. A controller crash
            # cannot produce an untraceable generated credential or rotate one.
            token='sk-'+secrets.token_hex(32)
            self.kube.ensure_new({'apiVersion':'v1','kind':'Secret','metadata':{'name':name},'type':'Opaque',
                'data':{field:base64.b64encode(token.encode()).decode()}})
        master=Path(self.config['issuerKeyFile']).read_text().strip()
        base=self.config['litellmBase'].rstrip('/')
        def call(endpoint,key,body=None):
            request=urllib.request.Request(base+endpoint,data=json.dumps(body).encode()if body is not None else None,
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request,timeout=45)as response:return response.status,json.load(response)
            except urllib.error.HTTPError as error:
                return error.code,{}
        # The lookup API accepts its stored digest. Never put a reusable client
        # credential in an access-log URL or rotate an existing key on retry.
        digest=hashlib.sha256(token.encode()).hexdigest()
        status,info=call('/key/info?key='+digest,master)
        if status==200 and info.get('info',{}).get('models')!=['deepseek-v4.1-flash']:
            raise ValueError('Existing inference credential has unexpected model scope')
        if status!=200:
            if status not in [400,401,404]:raise RuntimeError('Credential issuer is unavailable')
            body={'key':token,'key_alias':name,'models':['deepseek-v4.1-flash'],
                'allowed_routes':['/v1/messages','/messages','/v1/chat/completions','/chat/completions','/v1/models','/models','/token/count','/utils/token_counter'],
                'metadata':{'purpose':'Private DSH automatic provisioning; inference only'}}
            status,result=call('/key/generate',master,body)
            if status!=200 or result.get('key')!=token:raise RuntimeError('Planned inference credential was not issued')
        for endpoint in ['/key/generate','/model/new']:
            status,_=call(endpoint,token,{})
            if status not in [401,403]:raise ValueError('Issued credential permits administration')
        denied,_=call('/v1/chat/completions',token,{'model':'claude-opus-4-6','max_tokens':1,'messages':[{'role':'user','content':'Restriction check'}]})
        if denied not in [401,403]:raise ValueError('Issued credential permits an unapproved model')
        if messages:
            status,result=call('/v1/messages',token,{'model':'deepseek-v4.1-flash','max_tokens':128,
                'thinking':{'type':'disabled'},'messages':[{'role':'user','content':'Reply exactly CAPACITY_KEY_OK'}]})
            text=''.join(v.get('text','')for v in result.get('content',[]))
        else:
            status,result=call('/v1/chat/completions',token,{'model':'deepseek-v4.1-flash','max_tokens':32,'temperature':0,
                'chat_template_kwargs':{'enable_thinking':False},'messages':[{'role':'user','content':'Reply exactly CAPACITY_KEY_OK'}]})
            text=result.get('choices',[{}])[0].get('message',{}).get('content','')
        if status!=200 or text.strip()!='CAPACITY_KEY_OK':raise RuntimeError('Fresh restricted credential inference failed')

    def prepare_and_qualify(self, slot):
        self.phase='private-storage'
        if not re.fullmatch(r'cap-[a-f0-9]{16}-01',slot):raise ValueError('Invalid slot')
        identity=hashlib.sha256(slot.encode()).hexdigest()[:16]
        documents,pool,paths=generate(self.template['templates'],self.template['claims'],slot[:-3],1)
        if list(pool['slots'])!=[slot]:raise ValueError('Slot generation mismatch')
        ledger=self.root/'inventory'/(slot+'.json')
        if not ledger.exists():atomic_json(ledger,{'slot':slot,'initialized':False})
        record=read_json(ledger)
        if not record['initialized']:
            # New random identities only; never reuse populated private paths.
            for value in paths:
                if not re.fullmatch('dsh/private/'+identity+r'/(secure|state/(sessions|attachments|storages|workspaces|logs))',value):raise ValueError('Unexpected central path')
                folder=self.central/value
                if folder.exists() and any(folder.iterdir()):raise ValueError('Non-empty new private path')
                folder.mkdir(parents=True,exist_ok=True)
            record['initialized']=True;atomic_json(ledger,record)
        self.phase='restricted-inference-credentials'
        self.credential('dsh-inference-signup-'+identity,'litellm-api-key',False)
        for env in ['secure','internet']:self.credential('dsh-harness-signup-'+identity+'-'+env,'api-key',True)
        self.phase='private-runtime-creation'
        routes=pool['slots'][slot];names=[];expected={}
        for env,target in routes.items():
            target['host']=target['host'].split('.')[0]+'.'+self.config['namespace']+'.svc.cluster.local'
        for document in documents:
            if document['kind']!='Deployment':
                self.kube.ensure_new(document);continue
            env='secure' if document['metadata']['name'].endswith('-secure')else 'internet'
            mode='off' if env=='secure'else 'on';name=document['metadata']['name'];names.append(name)
            service_id=key(name+'.'+self.config['namespace']+'.svc.cluster.local',mode)
            # Definitions and status remain outside the password/account store.
            controls=self.services/service_id
            initialize_services(controls)
            (controls/'ready').touch(exist_ok=True)
            status=self.root/'inventory'/'runtime-status'/service_id;status.mkdir(parents=True,exist_ok=True)
            status_link=controls/'status'
            if not status_link.exists() and not status_link.is_symlink():status_link.symlink_to('/capacity/inventory/runtime-status/'+service_id,target_is_directory=True)
            public=self.root/'inventory'/'runtime-tokens'/identity/env;public.mkdir(parents=True,exist_ok=True)
            updated=sidecar(document,self.config['sourceConfigMap'],self.config['serviceControlPVC'],service_id)
            updated['spec']['template']['metadata'].setdefault('labels',{})['dsh.example.com/capacity-managed']='true'
            pod=updated['spec']['template']['spec']
            # Untrusted app status stays on a dedicated bounded PVC. Only the
            # separate trusted exporter may publish a small validated projection
            # to gateway inventory; an app cannot fill that shared volume.
            self.kube.ensure_new({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':'dsh-app-status-'+service_id},
                'spec':{'storageClassName':self.config['storageClass'],'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'1Gi'}}}})
            pod['volumes'].append({'name':'capacity-publication','persistentVolumeClaim':{'claimName':self.config['inventoryPVC']}})
            image=next(c for c in pod['containers']if c['name']=='dsh')['image']
            pod['containers'].append({'name':'capacity-token-exporter','image':image,
                'command':['python3','/service-source/capacity-token-exporter.py'],
                'env':[{'name':'DSH_ENVIRONMENT','value':env}],
                'volumeMounts':[{'name':'app-supervisor-source','mountPath':'/service-source','readOnly':True},
                    {'name':'routing-tokens','mountPath':'/runtime-tokens','readOnly':True},
                    {'name':'app-service-status','mountPath':'/private-status','readOnly':True},
                    {'name':'capacity-publication','mountPath':'/published','subPath':'runtime-tokens/'+identity+'/'+env},
                    {'name':'capacity-publication','mountPath':'/published-status','subPath':'runtime-status/'+service_id}],
                'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']},'seccompProfile':{'type':'RuntimeDefault'}},
                'resources':{'requests':{'cpu':'5m','memory':'16Mi'},'limits':{'cpu':'100m','memory':'64Mi'}}})
            routes[env]['tokenFile']='/runtime-tokens/capacity/'+identity+'/'+env+'/token'
            expected[name]=updated
            self.kube.ensure_new(updated)
        # Resume after restart rather than generating another pair. A failed pair
        # remains unpublished, with all partial resources retained for review.
        self.phase='runtime-and-isolation-checks'
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            ready=True
            for env,target in routes.items():
                deployment=self.kube.call('GET','Deployment',target['host'].split('.')[0])
                if not deployment or deployment.get('status',{}).get('readyReplicas',0)!=1:ready=False;break
                name=target['host'].split('.')[0]
                pods=[p for p in self.kube.call('GET','Pod',selector='app='+name)['items']if not p['metadata'].get('deletionTimestamp')]
                if len(pods)!=1 or not validate_runtime(pods[0],expected[name]):ready=False;break
                public=self.root/'inventory'/'runtime-tokens'/identity/env
                try:
                    qualification=read_json(public/'qualification.json')
                    if not qualification.get('passed')or time.time()-qualification['observedAt']>600:ready=False;break
                    token=(public/'token').read_text().strip()
                    self.empty_history(target,token)
                except (OSError,ValueError,RuntimeError,socket.error):ready=False;break
            if ready:
                return routes,{'status':'passed','newEmptyHistories':2,'isolatedWorkspaceAndState':True,
                    'securePublicEgressDenied':True,'internetPublicHTTPSAvailable':True,'managementTokenAbsent':True}
            time.sleep(5)
        raise RuntimeError('New runtime pair did not qualify before deadline')

    def empty_history(self,target,token):
        connection=http.client.HTTPConnection(target['host'],target['port'],timeout=10)
        from urllib.parse import quote
        host=self.config['trustedHost']
        connection.request('GET','/?token='+quote(token),headers={'Host':host})
        response=connection.getresponse();response.read()
        cookies=[v.split(';')[0]for k,v in response.getheaders()if k.lower()=='set-cookie'and v.startswith('dsh-auth-')]
        if not cookies:raise RuntimeError('Private DSH authentication failed')
        body=json.dumps({'type':'client-request','rpcId':secrets.token_hex(12),'method':'session/list','payload':{'args':{'_request':{}}}})
        connection.request('POST','/api/session/list',body=body,headers={'Host':host,'Cookie':'; '.join(cookies),'Origin':'https://'+host,'Content-Type':'application/json'})
        response=connection.getresponse();value=json.loads(response.read(262145))
        if response.status!=200 or value.get('result',{}).get('ok')is not True or value['result']['value']['items']!=[]:
            raise RuntimeError('Fresh private runtime inherited sessions or cannot list history')
        connection.close()
