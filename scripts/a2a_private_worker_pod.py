"""Exact disposable CLI-worker Pod template; construction grants no admission.

The authenticated controller must verify namespace UID/classification, private
workspace ownership, credential scope, running image and physical receipts.
No API client, credential lookup or automatic create/retry exists here.
"""
import re


def worker_pod_name(task_id):
    """The one name a worker Pod for this task can have (also used to prove that none exists)."""
    return 'a2a-'+task_id


def worker_pod(*, namespace, task_id, image, workspace_claim, project_subpath,
               credential_secret, correlation_id, writes=False):
    for value in (namespace, workspace_claim, credential_secret):
        if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', value):
            raise ValueError('INVALID_PRIVATE_WORKER_RESOURCE_NAME')
    if not re.fullmatch(r'[a-f0-9]{32}', str(task_id)) or not re.fullmatch(r'[a-f0-9]{32}', str(correlation_id)):
        raise ValueError('INVALID_PRIVATE_WORKER_TASK_ID')
    if not isinstance(image, str) or not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}', image):
        raise ValueError('IMMUTABLE_PRIVATE_WORKER_IMAGE_REQUIRED')
    if (not isinstance(project_subpath, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}(?:/[A-Za-z0-9_-]{1,128}){0,3}', project_subpath)):
        raise ValueError('EXACT_PRIVATE_PROJECT_SUBPATH_REQUIRED')
    if type(writes) is not bool:
        raise ValueError('EXPLICIT_WORKER_WRITE_POLICY_REQUIRED')
    security = dict(allowPrivilegeEscalation=False, readOnlyRootFilesystem=True,
                    capabilities={'drop':['ALL']})
    worker_security = {**security, 'runAsUser':0, 'runAsGroup':0,
                       'capabilities':{'drop':['ALL'],'add':['KILL','SETGID','SETUID']}}
    guard_security = {**security,'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True}
    return {'apiVersion':'v1','kind':'Pod','metadata':{
        'name':worker_pod_name(task_id),'namespace':namespace,
        'labels':{'app.kubernetes.io/part-of':'dsh-a2a-qualification',
                  'dsh.example.com/runtime-environment':'test',
                  'dsh.example.com/runtime-purpose':'qualification',
                  'dsh-task-id':task_id}},'spec':{
        'automountServiceAccountToken':False,'enableServiceLinks':False,
        'hostPID':False,'hostIPC':False,'hostNetwork':False,'shareProcessNamespace':False,
        'restartPolicy':'Never','activeDeadlineSeconds':300,'terminationGracePeriodSeconds':10,
        'securityContext':{'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},
        'containers':[
            {'name':'worker','image':image,'stdin':True,'stdinOnce':True,
             'terminationMessagePath':'/dev/termination-log','terminationMessagePolicy':'File',
             'command':['/usr/local/bin/python3','-I','-S','/opt/dsh/scripts/a2a_pid_namespace_worker.py'],
             'securityContext':worker_security,
             'resources':{'requests':{'cpu':'100m','memory':'256Mi'},'limits':{'cpu':'1','memory':'1Gi'}},
             'volumeMounts':[
                 {'name':'workspace','mountPath':'/workspace','subPath':project_subpath,'readOnly':not writes},
                 {'name':'tmp','mountPath':'/tmp'},
                 {'name':'payload-state','mountPath':'/state'},
                 {'name':'payload-home','mountPath':'/home/dsh'},
                 {'name':'worker-identity','mountPath':'/etc/dsh-worker-identity','readOnly':True}]},
            {'name':'model-guard','image':image,'stdin':True,'stdinOnce':True,
             'command':['/usr/local/bin/python3','-I','-S','/opt/dsh/container/dsh-task-guard-sidecar.py',
                        '--task-id',task_id,'--correlation-id',correlation_id,'--drain-on-stdin'],
             'securityContext':guard_security,
             'readinessProbe':{'exec':{'command':['/usr/local/bin/python3','-I','-S','-c',
                'import http.client,json; c=http.client.HTTPConnection("127.0.0.1",4001,timeout=1); '
                'c.request("GET","/_dsh/task-identity"); r=c.getresponse(); '
                'v=json.loads(r.read(4096)); assert r.status==200 and '
                + 'v["taskId"]=='+repr(task_id)+' and v["correlationId"]=='+repr(correlation_id)]},
                'periodSeconds':2,'timeoutSeconds':2,'failureThreshold':3},
             'resources':{'requests':{'cpu':'50m','memory':'64Mi'},'limits':{'cpu':'250m','memory':'256Mi'}},
             'volumeMounts':[
                 {'name':'guard-state','mountPath':'/state/unattended'},
                 {'name':'worker-identity','mountPath':'/etc/dsh-worker-identity','readOnly':True},
                 {'name':'task-model-credential','mountPath':'/harness-credentials','readOnly':True}]}],
        'volumes':[
            {'name':'workspace','persistentVolumeClaim':{'claimName':workspace_claim,'readOnly':not writes}},
            {'name':'tmp','emptyDir':{'sizeLimit':'32Mi'}},
            {'name':'payload-state','emptyDir':{'sizeLimit':'32Mi'}},
            {'name':'payload-home','emptyDir':{'sizeLimit':'32Mi'}},
            {'name':'guard-state','emptyDir':{'sizeLimit':'4Mi'}},
            {'name':'worker-identity','downwardAPI':{'defaultMode':0o444,'items':[
                {'path':'pod-uid','fieldRef':{'fieldPath':'metadata.uid'}}]}},
            {'name':'task-model-credential','secret':{'secretName':credential_secret,
                'defaultMode':0o440,'items':[{'key':'api-key','path':'api-key'}]}}]}}
