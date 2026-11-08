"""One exact worker retirement by the existing protected Task writer.

No background cleanup, retry, model call or credential/default endpoint exists.
An uncertain delete is only observed on recovery, never replayed. Resource
absence is not proof that provider computation stopped or that rollback passed.
"""
import copy
import hashlib
import os
import re
import time
import uuid
from scripts.a2a_factory_budget import sync_directory
from scripts.a2a_provider_capture import canonical,read_capture_bytes
from scripts.official_sdk_package_admission import unique_json
from scripts.a2a_model_reconciliation import reconcile_metadata
from scripts import a2a_worker_journal as journal

INTENT='a2a-worker-retirement-intent.json'
RESULT='a2a-worker-retirement-result.json'


def read_record(task,name):
    path=task.directory/name
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
    try:
        import stat
        info=os.fstat(fd)
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=32768:
            raise ValueError('BOUNDED_REGULAR_RETIREMENT_RECORD_REQUIRED')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(32769)
    finally:os.close(fd)
    value=unique_json(raw)
    if canonical(value)!=raw:raise ValueError('COMPLETE_CANONICAL_RETIREMENT_RECORD_REQUIRED')
    return raw,value


def write_once(task,name,value):
    raw=canonical(value)
    if len(raw)>32768:raise ValueError('BOUNDED_RETIREMENT_RECORD_REQUIRED')
    fd=os.open(task.directory/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0),0o600)
    try:
        offset=0
        while offset<len(raw):
            n=os.write(fd,raw[offset:])
            if type(n) is not int or not 0<n<=len(raw)-offset:raise OSError('RETIREMENT_WRITE_UNCERTAIN')
            offset+=n
        os.fsync(fd)
    finally:os.close(fd)
    sync_directory(task.directory)
    if read_record(task,name)[0]!=raw:raise ValueError('RETIREMENT_READBACK_CHANGED')
    return hashlib.sha256(raw).hexdigest()


class TaskWorkerRetirement:
    def __init__(self,*,registry,controller,capture,admission_reader,clock=time.time):
        if (not isinstance(getattr(registry,'tasks',None),dict) or not hasattr(registry,'lock')
                or not callable(admission_reader) or capture.controller is not controller):
            raise ValueError('SOLE_TASK_WRITER_RETIREMENT_DEPENDENCIES_REQUIRED')
        self.registry,self.controller,self.capture=registry,controller,capture
        self.read,self.clock=admission_reader,clock

    def _check(self,task,binding):
        worker=getattr(task,'a2a_cli_worker',None)
        if not isinstance(worker,dict):raise ValueError('EXACT_RETIREMENT_WORKER_REQUIRED')
        expected=dict(subject=self.controller.subject,generation=self.capture.generation,taskId=task.id,
            correlationId=task.correlation_id,project=task.request['project'],runtime=task.request['runtime'],
            writes=task.request['writes'],promptSha256=worker.get('promptSha256'))
        if (binding!=expected or task.authenticated_subject!=binding['subject']
                or worker.get('namespace')!=self.controller.api.namespace
                or worker.get('namespaceUID')!=self.controller.api.namespace_uid
                or worker.get('image')!=self.controller.image
                or not re.fullmatch(r'[a-f0-9]{64}',str(worker.get('providerCaptureSha256')))):
            raise ValueError('FOREIGN_OR_UNCAPTURED_RETIREMENT_WORKER')
        scope=dict(binding=copy.deepcopy(binding),namespace=worker['namespace'],namespaceUID=worker['namespaceUID'],
            podName=worker['podName'],podUID=worker['podUID'],source=copy.deepcopy(self.capture.source),
            captureSha256=worker['providerCaptureSha256'])
        lease=self.read()
        if (not isinstance(lease,dict) or set(lease)!={'scope','expiresAt','cleanupOnly'}
                or lease['scope']!=scope or lease['cleanupOnly'] is not True
                or type(lease['expiresAt']) not in (int,float) or not 0<lease['expiresAt']-self.clock()<=300
                or self.capture.observe()!=self.capture.source):
            raise ValueError('FINITE_EXACT_CLEANUP_ONLY_RETIREMENT_ADMISSION_REQUIRED')
        roots=list(self.registry.tasks.values())
        if (self.registry.tasks.get(task.id) is not task
                and sum(getattr(parent,'active_a2a_child',None) is task for parent in roots)!=1):
            raise ValueError('CANONICAL_RETIREMENT_TASK_REQUIRED')
        return scope

    def _locked(self,task,binding,action):
        with self.registry.lock:
            if not task.persistence_lock.acquire(blocking=False):raise ValueError('RETIREMENT_WRITER_BUSY')
            try:return action(self._check(task,binding))
            finally:task.persistence_lock.release()

    def retire(self,task,binding):
        # Validate terminal/guard/capture against the still-existing physical
        # worker BEFORE its exact UID can be reserved for deletion.
        self._locked(task,binding,lambda scope:None)
        retained=self.capture.recover(task,binding)
        actual=self.controller.observe(task)
        if actual['resourceAbsent']:raise ValueError('UNRESERVED_ABSENCE_IS_NOT_RETIREMENT')
        meta=actual['pod']['metadata']
        def reserve(scope):
            if (task.directory/INTENT).exists() or (task.directory/INTENT).is_symlink():
                raise ValueError('RETIREMENT_ALREADY_RESERVED_OBSERVE_ONLY')
            if meta['uid']!=scope['podUID'] or retained['captureSha256']!=scope['captureSha256']:
                raise ValueError('RETIREMENT_WORKER_OR_CAPTURE_CHANGED')
            value=dict(kind='DSH_WORKER_RETIREMENT_INTENT_V1',scope=scope,operationId=uuid.uuid4().hex,
                resourceVersion=meta['resourceVersion'],retainedResult=retained)
            digest=write_once(task,INTENT,value)
            task.a2a_cli_worker.update(retirementIntentSha256=digest,retirementStatus='reserved')
            task.save()  # A failure leaves the WAL consumed; no delete/retry.
            return value
        intent=self._locked(task,binding,reserve)
        self._locked(task,binding,lambda scope:None)
        # WorkerAPI supplies namespace verification and UID/resourceVersion
        # delete preconditions. Any timeout escapes; recovery is GET-only.
        self.controller.api.delete_pod_once(name=intent['scope']['podName'],pod_uid=intent['scope']['podUID'],
            resource_version=intent['resourceVersion'])
        return self.recover(task,binding)

    def recover(self,task,binding):
        def read(scope):
            raw,intent=read_record(task,INTENT)
            if (set(intent)!={'kind','scope','operationId','resourceVersion','retainedResult'}
                    or intent['kind']!='DSH_WORKER_RETIREMENT_INTENT_V1' or intent['scope']!=scope
                    or not re.fullmatch(r'[a-f0-9]{32}',str(intent['operationId']))
                    or task.a2a_cli_worker.get('retirementIntentSha256') not in (None,hashlib.sha256(raw).hexdigest())):
                raise ValueError('RETIREMENT_INTENT_BINDING_CHANGED')
            capture_raw,capture=read_capture_bytes(task)
            worker=task.a2a_cli_worker
            guard=journal.read_guard_ledger_bytes(task)
            operation=worker.get('providerCaptureOperationId')
            query=self.capture._query_context(task,worker,guard,operation)
            joined=reconcile_metadata(task,guard_bytes=guard,provider_rows=capture.get('rows'))
            retained={**joined,'captureSha256':scope['captureSha256'],
                'captureOperationId':operation,'queryExecuted':bool(query['operationIds'])}
            if (hashlib.sha256(capture_raw).hexdigest()!=scope['captureSha256']
                    or set(capture)!={'kind','query','source','rows','join','queryExecuted'}
                    or capture['kind']!='DSH_TASK_PROVIDER_CAPTURE_V1'
                    or capture['query']!=query or capture['source']!=scope['source']
                    or type(capture['queryExecuted']) is not bool
                    or capture['queryExecuted']!=bool(query['operationIds'])
                    or capture['join']!=joined or intent['retainedResult']!=retained):
                raise ValueError('RETIREMENT_RETAINED_RESULT_CHANGED')
            return raw,intent
        raw,intent=self._locked(task,binding,read)
        actual=self.controller.api.read_pod(intent['scope']['podName'])
        if actual is not None:
            if actual['metadata']['uid']!=intent['scope']['podUID']:
                raise ValueError('RETIREMENT_NAME_REPLACED_NO_DELETE')
            return dict(kind='DSH_WORKER_RETIREMENT_PENDING_V1',operationId=intent['operationId'],resourceAbsent=False)
        result=dict(kind='DSH_WORKER_RETIREMENT_RESULT_V1',intentSha256=hashlib.sha256(raw).hexdigest(),
            operationId=intent['operationId'],scope=intent['scope'],resourceAbsent=True,
            retainedResult=intent['retainedResult'],providerExecutionStoppedVerified=False,rollbackVerified=False)
        def finish(scope):
            if (task.directory/RESULT).exists() or (task.directory/RESULT).is_symlink():
                if read_record(task,RESULT)[1]!=result:raise ValueError('RETIREMENT_RESULT_CHANGED')
            else:write_once(task,RESULT,result)
            task.a2a_cli_worker.update(retirementStatus='resource-absent',retirementResultSha256=hashlib.sha256(canonical(result)).hexdigest())
            task.save()
            return copy.deepcopy(result)
        return self._locked(task,binding,finish)
