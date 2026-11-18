"""Banking-only physical template and protected per-task grant validation.

No object creation/admission occurs here. Native templates and CAP1 unchanged.
"""
import copy
import hashlib
import re
from scripts.banking_sdk_scope_factory import canonical,digest
from scripts.a2a_sdk_worker_pod import sdk_worker_pod
from scripts.banking_sdk_package_mounts import mount_package_inputs
from scripts.a2a_worker_identity import annotate,template_hash

GRANT_KEYS={'kind','mode','binding','grantSha256','scopeDigest','sourceCommit','imageDigest',
    'packageAdmissionSha256','cap','storage','workerPodUID','controllerPodUID','templateSha256',
    'expiresAt','providerPolicyReference','billingAuthorizationReference'}


def validate_grant(value,*,worker_uid,clock):
    if not isinstance(value,dict) or set(value)!=GRANT_KEYS or value.get('kind')!='DSH_BANKING_SDK_WORKER_GRANT_V1' or value.get('mode')!='banking':
        raise ValueError('EXACT_PROTECTED_BANKING_WORKER_GRANT_REQUIRED')
    if (value.get('cap') is None)!=(value.get('expiresAt') is None):raise ValueError('STANDING_WORKER_POLICY_MIXED')
    binding=value['binding']
    keys={'subject','generation','taskId','project','correlationId','runId','runtime','runner','writes','promptSha256'}
    if (not isinstance(binding,dict) or set(binding)!=keys or binding.get('runtime')!='sdk' or binding.get('runner')!='official-native-sdk'
            or type(binding['writes']) is not bool or not (value['cap'] is None and value.get('expiresAt','missing') is None or type(value['cap']) is int and 2<=value['cap']<=32)):
        raise ValueError('BANKING_WORKER_TASK_CAP_BINDING_REQUIRED')
    for key in ('taskId','correlationId'):
        if not re.fullmatch(r'[a-f0-9]{32}',str(binding[key])):raise ValueError('BANKING_WORKER_TASK_ID_REQUIRED')
    for key in ('subject','generation','runId'):
        if not isinstance(binding[key],str) or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',binding[key]):raise ValueError('BANKING_WORKER_OWNER_REQUIRED')
    if not isinstance(binding['project'],str) or not binding['project'] or not re.fullmatch(r'[a-f0-9]{64}',str(binding['promptSha256'])):
        raise ValueError('BANKING_WORKER_PROJECT_PROMPT_REQUIRED')
    for key in ('grantSha256','scopeDigest','imageDigest','packageAdmissionSha256','templateSha256'):
        if not re.fullmatch(r'[a-f0-9]{64}',str(value[key])):raise ValueError('BANKING_WORKER_DIGEST_REQUIRED')
    if not re.fullmatch(r'[a-f0-9]{40}',str(value['sourceCommit'])):raise ValueError('BANKING_WORKER_SOURCE_REQUIRED')
    for key in ('workerPodUID','controllerPodUID'):
        if not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',str(value[key])):raise ValueError('BANKING_WORKER_UID_REQUIRED')
    if value['workerPodUID']!=worker_uid or value['workerPodUID']==value['controllerPodUID']:
        raise ValueError('BANKING_WORKER_UID_MISMATCH')
    if value['expiresAt'] is not None and (type(value['expiresAt']) not in (int,float) or not 0<value['expiresAt']-clock()<=300):
        raise ValueError('BANKING_WORKER_GRANT_EXPIRED')
    if not isinstance(value['storage'],dict) or set(value['storage'])!={'claim','claimUID','namespace','subpath','globalLedgerIdentity','guardStateIdentity'} or value['storage'].get('namespace')!='llm' or value['storage'].get('claim')!='dsh-banking-protected-guard-state' or any(not isinstance(v,str) or not v for v in value['storage'].values()):
        raise ValueError('BANKING_WORKER_STORAGE_UNBOUND')
    for key in ('providerPolicyReference','billingAuthorizationReference'):
        if not isinstance(value[key],str) or not value[key]:raise ValueError('BANKING_WORKER_PROVIDER_POLICY_UNBOUND')
    return copy.deepcopy(value)


def worker_template(*,admission,binding,cap,policy,create_operation):
    required={'namespace','namespaceUID','nodeName','workspaceClaim','workspaceSubpath','credentialSecret','guardClaim','guardSubpath','serviceAccount','imageRepository'}
    if not isinstance(policy,dict) or set(policy)!=required or policy['workspaceClaim']==policy['guardClaim']:
        raise ValueError('DISTINCT_PROTECTED_BANKING_WORKER_POLICY_REQUIRED')
    for key in ('namespace','workspaceClaim','credentialSecret','guardClaim','serviceAccount'):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',str(policy[key])):raise ValueError('BANKING_WORKER_RESOURCE_NAME_REQUIRED')
    for key in ('workspaceSubpath','guardSubpath'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}(?:/[A-Za-z0-9_-]{1,128}){0,3}',str(policy[key])):raise ValueError('BANKING_WORKER_SUBPATH_REQUIRED')
    if not isinstance(policy['imageRepository'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{1,255}',policy['imageRepository']):raise ValueError('PINNED_BANKING_IMAGE_REPOSITORY_REQUIRED')
    pod=sdk_worker_pod(namespace=policy['namespace'],task_id=binding['taskId'],image=policy['imageRepository']+'@sha256:'+admission['imageDigest'],workspace_claim=policy['workspaceClaim'],project_subpath=policy['workspaceSubpath'],credential_secret=policy['credentialSecret'],correlation_id=binding['correlationId'],writes=binding['writes'],package_admission_sha256=admission['packageAdmissionSha256'])
    pod['metadata']['labels'].update({'app.kubernetes.io/part-of':'dsh-sdk-banking','dsh.example.com/runtime-purpose':'banking'})
    pod['metadata']['annotations'].update({'dsh.example.com/banking-scope':admission['scopeDigest'],'dsh.example.com/banking-cap':str(cap)})
    pod['spec']['securityContext'].pop('fsGroup',None)
    pod['spec']['nodeName']=policy['nodeName'];pod['spec']['serviceAccountName']=policy['serviceAccount']
    guard=pod['spec']['containers'][1]
    guard['securityContext'].update(runAsUser=0,runAsGroup=0,runAsNonRoot=False)
    pod['spec']['containers'][0]['securityContext']['runAsGroup']=10001
    pod['spec']['containers'][0]['workingDir']='/workspace/banking'
    next(m for m in pod['spec']['containers'][0]['volumeMounts'] if m['name']=='workspace')['mountPath']='/workspace/banking'
    pod['spec']['containers'][0]['command']=['/usr/local/bin/python3','-I','-S','/opt/dsh/scripts/banking_sdk_worker_entry.py']
    pod['spec']['containers'][0]['volumeMounts'].append(dict(name='banking-grant',mountPath='/etc/dsh-banking-grant',readOnly=True))
    guard['command']=['/usr/local/bin/python3','-I','-S','/opt/dsh/container/dsh-banking-sdk-guard.py']
    guard['volumeMounts'].append(dict(name='banking-grant',mountPath='/etc/dsh-banking-grant',readOnly=True))
    volumes=pod['spec']['volumes']
    state=next(v for v in volumes if v['name']=='guard-state');state.pop('emptyDir')
    state['persistentVolumeClaim']=dict(claimName=policy['guardClaim'],readOnly=False)
    state_mount=next(v for v in guard['volumeMounts'] if v['name']=='guard-state')
    task_subpath=digest({k:binding[k] for k in ('subject','runId','generation','taskId')})
    state_mount['mountPath']='/state/banking-guard-protected'
    state_mount['subPath']=policy['guardSubpath']+'/'+task_subpath
    volumes.append(dict(name='banking-grant',configMap=dict(name='sdk-bank-grant-'+binding['taskId'],defaultMode=0o400,items=[dict(key='grant.json',path='grant.json')])))
    # Worker never mounts grant or durable guard state; only guard can write it.
    pod=mount_package_inputs(pod,namespace_uid=policy['namespaceUID'],admission_sha256=admission['packageAdmissionSha256'])
    return annotate(pod,namespace_uid=policy['namespaceUID'],operation_id=create_operation)
