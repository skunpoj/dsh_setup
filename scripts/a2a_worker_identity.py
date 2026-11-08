"""Verify actual worker Pod fields, not labels/readiness alone.

Known API defaults are normalized; unadmitted injected containers, credentials,
commands, namespaces, privileges and volumes are rejected. Running identity
checks are not execution, descendant-stop or model-ledger acceptance.
"""
import copy
import hashlib
import json
import re
from scripts.a2a_worker_journal import uid
from scripts.official_sdk_deployment_observer import exact_running_digest
from scripts.a2a_worker_receipt import terminal_projection,decode_projection,FIELDS

CREATE='dsh.example.com/create-operation'
TEMPLATE='dsh.example.com/worker-template-sha256'
NAMESPACE='dsh.example.com/worker-namespace-uid'


def template_hash(template):
    value=copy.deepcopy(template)
    annotations=value['metadata'].get('annotations',{})
    for key in (CREATE,TEMPLATE,NAMESPACE):annotations.pop(key,None)
    if not annotations:value['metadata'].pop('annotations',None)
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def annotate(template, *, namespace_uid, operation_id):
    uid(namespace_uid)
    if not isinstance(operation_id,str) or not re.fullmatch(r'[a-f0-9]{32}',operation_id):
        raise ValueError('EXACT_WORKER_CREATE_OPERATION_REQUIRED')
    result=copy.deepcopy(template)
    result['metadata'].setdefault('annotations',{}).update({
        CREATE:operation_id,TEMPLATE:template_hash(template),NAMESPACE:namespace_uid})
    return result


def strip_default(value, expected, key, default):
    if key not in expected and key in value:
        if type(value[key]) is not type(default) or value[key]!=default:
            raise ValueError('UNADMITTED_WORKER_DEFAULT_'+key)
        value.pop(key)


def normalized_spec(spec,expected):
    value=copy.deepcopy(spec)
    for key,default in [('dnsPolicy','ClusterFirst'),('schedulerName','default-scheduler'),
        ('serviceAccountName','default'),('serviceAccount','default'),('priority',0),
        ('preemptionPolicy','PreemptLowerPriority'),('initContainers',[]),('ephemeralContainers',[])]:
        strip_default(value,expected,key,default)
    if 'nodeName' in value and 'nodeName' not in expected:
        node=value.pop('nodeName')
        if not isinstance(node,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}',node):
            raise ValueError('INVALID_WORKER_NODE_NAME')
        # Node admission is a separate protected controller policy; this is
        # normalization of scheduler output, not approval of any chosen node.
    if 'tolerations' in value and 'tolerations' not in expected:
        standard=[dict(key='node.kubernetes.io/'+key,operator='Exists',effect='NoExecute',tolerationSeconds=300)
                  for key in ('not-ready','unreachable')]
        tolerations=value.pop('tolerations')
        if not isinstance(tolerations,list) or any(t not in standard for t in tolerations):
            raise ValueError('UNADMITTED_WORKER_TOLERATIONS')
    if len(value.get('containers',[]))!=len(expected['containers']):
        raise ValueError('UNADMITTED_WORKER_CONTAINER_SET')
    for container,want in zip(value['containers'],expected['containers']):
        for key,default in [('imagePullPolicy','IfNotPresent'),('terminationMessagePath','/dev/termination-log'),
            ('terminationMessagePolicy','File'),('tty',False),('stdin',False),('stdinOnce',False)]:
            strip_default(container,want,key,default)
        security=container.get('securityContext',{})
        for key,default in [('privileged',False),('procMount','Default')]:
            strip_default(security,want['securityContext'],key,default)
        if len(container.get('volumeMounts',[]))!=len(want['volumeMounts']):
            raise ValueError('UNADMITTED_WORKER_MOUNT_SET')
        for mount,desired in zip(container['volumeMounts'],want['volumeMounts']):
            for key,default in [('readOnly',False),('mountPropagation','None'),('recursiveReadOnly','Disabled')]:
                strip_default(mount,desired,key,default)
    if len(value.get('volumes',[]))!=len(expected['volumes']):
        raise ValueError('UNADMITTED_WORKER_VOLUME_SET')
    for volume,want in zip(value['volumes'],expected['volumes']):
        if 'secret' in volume and 'secret' in want:
            strip_default(volume['secret'],want['secret'],'optional',False)
        if 'emptyDir' in volume and 'emptyDir' in want:
            strip_default(volume['emptyDir'],want['emptyDir'],'medium','')
        if 'downwardAPI' in volume and 'downwardAPI' in want:
            items=volume['downwardAPI'].get('items',[]);wanted=want['downwardAPI']['items']
            if len(items)!=len(wanted):raise ValueError('UNADMITTED_WORKER_IDENTITY_MOUNT')
            for item,desired in zip(items,wanted):
                strip_default(item.get('fieldRef',{}),desired['fieldRef'],'apiVersion','v1')
    return value


def verify_pod(pod,expected,*,pod_uid=None,require_running=False):
    if not isinstance(pod,dict) or pod.get('kind')!='Pod' or pod.get('apiVersion')!='v1':
        raise ValueError('INVALID_WORKER_POD_RESPONSE')
    meta=pod.get('metadata',{});want=expected['metadata']
    actual_uid=uid(meta.get('uid'))
    if (meta.get('name')!=want['name'] or meta.get('namespace')!=want['namespace']
            or (pod_uid is not None and actual_uid!=pod_uid) or meta.get('deletionTimestamp')
            or not isinstance(meta.get('resourceVersion'),str) or not meta['resourceVersion']):
        raise ValueError('WORKER_POD_IDENTITY_CHANGED')
    if any(meta.get('labels',{}).get(k)!=v for k,v in want['labels'].items()):
        raise ValueError('WORKER_POD_LABEL_BINDING_CHANGED')
    if any(meta.get('annotations',{}).get(k)!=want.get('annotations',{}).get(k)
           or want.get('annotations',{}).get(k) is None for k in (CREATE,TEMPLATE,NAMESPACE)):
        raise ValueError('WORKER_POD_OPERATION_BINDING_CHANGED')
    if any(meta.get('annotations',{}).get(key)!=value for key,value in want.get('annotations',{}).items()):
        raise ValueError('WORKER_ADMITTED_ANNOTATION_CHANGED')
    if (json.dumps(normalized_spec(pod.get('spec',{}),expected['spec']),sort_keys=True,separators=(',',':'))
            !=json.dumps(expected['spec'],sort_keys=True,separators=(',',':'))):
        raise ValueError('WORKER_POD_TEMPLATE_CHANGED')
    if require_running:
        statuses=pod.get('status',{}).get('containerStatuses',[])
        if pod.get('status',{}).get('phase')!='Running' or len(statuses)!=2:
            raise ValueError('WORKER_RUNNING_CONTAINERS_UNVERIFIED')
        by_name={status.get('name'):status for status in statuses}
        if set(by_name)!={'worker','model-guard'}:raise ValueError('WORKER_STATUS_SET_UNVERIFIED')
        for container in expected['spec']['containers']:
            status=by_name[container['name']]
            if (status.get('ready') is not True or not status.get('state',{}).get('running')
                    or type(status.get('restartCount')) is not int or status.get('restartCount')!=0
                    or exact_running_digest(status.get('imageID'))!=container['image'].rsplit('@',1)[1]):
                raise ValueError('WORKER_RUNNING_IMAGE_OR_GENERATION_UNVERIFIED')
    return {'podUID':actual_uid,'resourceVersion':meta['resourceVersion'],
            'templateSha256':want['annotations'][TEMPLATE]}


def verify_terminal_worker(pod,expected,*,pod_uid,context,stream_receipt=None):
    identity=verify_pod(pod,expected,pod_uid=pod_uid)
    statuses=pod.get('status',{}).get('containerStatuses',[])
    by_name={value.get('name'):value for value in statuses}
    if len(statuses)!=2 or set(by_name)!={'worker','model-guard'}:
        raise ValueError('TERMINAL_WORKER_CONTAINER_SET_UNVERIFIED')
    for container in expected['spec']['containers']:
        status=by_name[container['name']]
        if (type(status.get('restartCount')) is not int or status['restartCount']!=0
                or exact_running_digest(status.get('imageID'))!=container['image'].rsplit('@',1)[1]):
            raise ValueError('TERMINAL_WORKER_IMAGE_OR_GENERATION_CHANGED')
    terminated=by_name['worker'].get('state',{}).get('terminated')
    if (not isinstance(terminated,dict) or type(terminated.get('exitCode')) is not int
            or not 0<=terminated['exitCode']<=255 or not terminated.get('finishedAt')):
        raise ValueError('WORKER_INIT_EXIT_UNVERIFIED')
    proof=decode_projection(terminated.get('message'))
    if (not isinstance(context,dict) or set(context)!=FIELDS-{'scopeUid'}
            or any(proof.get(k)!=v for k,v in context.items()) or proof['scopeUid']!=pod_uid):
        raise ValueError('FOREIGN_PHYSICAL_WORKER_TERMINAL_RECEIPT')
    if stream_receipt is not None and terminal_projection(stream_receipt)!=proof:
        raise ValueError('WORKER_STREAM_AND_TERMINATION_RECEIPT_MISMATCH')
    return {**identity,**proof,'workerRootExitCode':terminated['exitCode'],
        'outputAvailable':stream_receipt is not None,
        'guardStopped':isinstance(by_name['model-guard'].get('state',{}).get('terminated'),dict)}
