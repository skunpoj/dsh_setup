"""Physical worker reservations in the EXISTING broker Task journal only.

No independent store/writer, API request, process spawn or model call. A failed
or ambiguous reservation is retained and can only be observed, never resent.
"""
import copy
import re
import uuid
import hashlib
import json
import os
import stat
from scripts.dsh_correlation import operation_correlation_id
from scripts.a2a_worker_receipt import decode_projection


def uid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('EXACT_WORKER_UID_REQUIRED')
    return value


def reserve(task, *, namespace, namespace_uid, template_sha256, image,sdk_binding=None,prompt_sha256=None):
    if not isinstance(namespace,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',namespace):
        raise ValueError('INVALID_WORKER_NAMESPACE')
    uid(namespace_uid)
    if not isinstance(template_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',template_sha256):
        raise ValueError('EXACT_WORKER_TEMPLATE_HASH_REQUIRED')
    if not isinstance(image,str) or not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}',image):
        raise ValueError('IMMUTABLE_WORKER_IMAGE_REQUIRED')
    with task.persistence_lock:
        if prompt_sha256 is not None:
            prompt=task.request.get('prompt')
            if (not isinstance(prompt_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',prompt_sha256)
                    or not isinstance(prompt,str) or hashlib.sha256(prompt.encode()).hexdigest()!=prompt_sha256):
                raise ValueError('EXACT_WORKER_PROMPT_HASH_REQUIRED')
        context=getattr(task,'a2a_cli_context',None)
        if (task.state != 'running' or not isinstance(context,dict)
                or context.get('stageId') != task.id or context.get('correlationId') != task.correlation_id
                or context.get('project') != task.request['project']
                or not getattr(task,'authenticated_subject',None)
                or context.get('subject') != task.authenticated_subject
                or context.get('runtime') != task.request['runtime']):
            raise ValueError('WORKER_TASK_NOT_ADMITTED')
        if getattr(task,'a2a_cli_worker',None) is not None:
            raise ValueError('WORKER_ALREADY_RESERVED_NO_RESEND')
        if task.request['runtime']=='sdk':
            native=getattr(task,'native_sdk',None)
            if (not isinstance(sdk_binding,dict) or set(sdk_binding)!={'generation','launchOperationId','packageAdmissionSha256'}
                    or not isinstance(native,dict) or native.get('phase')!='launch-reserved'
                    or native.get('guardLifecyclePending') is not True or native.get('stopOperationId')
                    or any(native.get(k)!=v for k,v in dict(subject=task.authenticated_subject,
                        taskId=task.id,sessionId=task.id,project=task.request['project'],
                        correlationId=task.correlation_id,generation=sdk_binding.get('generation'),
                        launchOperationId=sdk_binding.get('launchOperationId')).items())
                    or any(not isinstance(value,str) for value in sdk_binding.values())
                    or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',sdk_binding['generation'])
                    or not re.fullmatch(r'[a-f0-9]{32}',sdk_binding['launchOperationId'])
                    or not re.fullmatch(r'[a-f0-9]{64}',sdk_binding['packageAdmissionSha256'])
                    or sdk_binding['packageAdmissionSha256']=='0'*64):
                raise ValueError('EXACT_NATIVE_SDK_WORKER_BINDING_REQUIRED')
        elif sdk_binding is not None:raise ValueError('SDK_BINDING_ON_NONSDK_WORKER_REFUSED')
        value=dict(namespace=namespace,namespaceUID=namespace_uid,podName='a2a-'+task.id,
            createOperationId=uuid.uuid4().hex,templateSha256=template_sha256,
            image=image,phase='create-reserved',podUID=None,guardLedgerSha256=None)
        if sdk_binding is not None:value['sdkBinding']=copy.deepcopy(sdk_binding)
        if prompt_sha256 is not None:value['promptSha256']=prompt_sha256
        task.a2a_cli_worker=value
        try:
            task.save()  # Must finish before ANY Pod create/attach is attempted.
        except BaseException:
            value['phase']='persistence-uncertain'
            task.state='interrupted'
            raise
        return copy.deepcopy(value)


def bind_created(task, *, operation_id, pod_uid):
    uid(pod_uid)
    with task.persistence_lock:
        value=getattr(task,'a2a_cli_worker',None)
        if (not value or value['phase'] != 'create-reserved' or value['podUID'] is not None
                or operation_id != value['createOperationId']):
            raise ValueError('WORKER_CREATE_IDENTITY_UNCERTAIN')
        value['podUID']=pod_uid;value['phase']='bound'
        try:
            task.save()
        except BaseException:
            value['phase']='persistence-uncertain';task.state='interrupted'
            raise
        return copy.deepcopy(value)


def reserve_dispatch(task, *, pod_uid):
    uid(pod_uid)
    with task.persistence_lock:
        value=getattr(task,'a2a_cli_worker',None)
        if (not value or value['phase'] != 'bound' or value['podUID'] != pod_uid
                or task.state != 'running'):
            raise ValueError('WORKER_DISPATCH_FENCED_OR_ALREADY_RESERVED')
        value['phase']='dispatch-reserved'
        try:
            task.save()
        except BaseException:
            value['phase']='persistence-uncertain';task.state='interrupted'
            raise
        return copy.deepcopy(value)


def reserve_attach(task, *, pod_uid):
    uid(pod_uid)
    with task.persistence_lock:
        value=getattr(task,'a2a_cli_worker',None)
        if (not value or value['phase']!='dispatch-reserved' or value['podUID']!=pod_uid
                or task.state!='running' or value.get('attachOperationId') is not None):
            raise ValueError('WORKER_ATTACH_ALREADY_RESERVED_OR_FENCED')
        value['attachOperationId']=uuid.uuid4().hex
        try:task.save()
        except BaseException:
            value['phase']='persistence-uncertain';task.state='interrupted'
            raise
        return value['attachOperationId']


def reserve_sdk_stop_frame(task,*,pod_uid,operation_id):
    uid(pod_uid)
    with task.persistence_lock:
        worker=getattr(task,'a2a_cli_worker',None);native=getattr(task,'native_sdk',None)
        if (not worker or worker['phase']!='dispatch-reserved' or worker['podUID']!=pod_uid
                or not worker.get('attachOperationId') or worker.get('stopFrameOperationId') is not None
                or task.state not in {'finalizing','cancelling','interrupted'}
                or not isinstance(native,dict) or native.get('phase') not in {'stop-reserved','stop-uncertain'}
                or task.request.get('runtime')!='sdk' or native.get('sessionId')!=task.id
                or native.get('stopOperationId')!=operation_id or native.get('taskId')!=task.id
                or native.get('subject')!=task.authenticated_subject
                or native.get('project')!=task.request['project']
                or native.get('correlationId')!=task.correlation_id
                or not re.fullmatch(r'[a-f0-9]{32}',str(operation_id))):
            raise ValueError('EXACT_NATIVE_SDK_STOP_REQUIRED_NO_RESEND')
        worker['stopFrameOperationId']=operation_id
        try:task.save()
        except BaseException:
            worker['phase']='persistence-uncertain';task.state='interrupted'
            raise
        return operation_id


def reserve_stop_frame(task,*,pod_uid,operation_id):
    uid(pod_uid)
    with task.persistence_lock:
        value=getattr(task,'a2a_cli_worker',None)
        cancel=getattr(task,'a2a_cli_cancel',None)
        if (not value or value['phase']!='dispatch-reserved' or value['podUID']!=pod_uid
                or not value.get('attachOperationId') or task.state!='cancelling'
                or not isinstance(cancel,dict) or cancel.get('status')!='reserved'
                or cancel.get('operationId')!=operation_id
                or not re.fullmatch(r'[a-f0-9]{32}',str(operation_id))
                or value.get('stopFrameOperationId') is not None):
            raise ValueError('EXACT_RESERVED_STOP_REQUIRED_NO_RESEND')
        value['stopFrameOperationId']=operation_id
        try:task.save()
        except BaseException:
            value['phase']='persistence-uncertain';task.state='interrupted'
            raise
        return operation_id


def reserve_guard_attach(task,*,pod_uid):
    uid(pod_uid)
    with task.persistence_lock:
        value=getattr(task,'a2a_cli_worker',None)
        if (not value or value['phase']!='dispatch-reserved' or value['podUID']!=pod_uid
                or not value.get('terminalReceiptSha256') or value.get('guardAttachOperationId') is not None):
            raise ValueError('GUARD_ATTACH_NOT_ADMITTED_OR_ALREADY_CONSUMED')
        value['guardAttachOperationId']=uuid.uuid4().hex
        try:task.save()
        except BaseException:
            value['phase']='persistence-uncertain';task.state='interrupted'
            raise
        return value['guardAttachOperationId']


def retain_terminal_projection(task, *, pod_uid, projection):
    """Retain already Pod-verified stop metadata in the existing Task directory.

    This records evidence only; it neither retires a worker nor reconciles model
    accounting. Raw answers and prompts are never written to this receipt.
    """
    uid(pod_uid)
    raw=json.dumps(projection,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    value=decode_projection(raw.decode())
    if (value['scopeUid']!=pod_uid
            or any(value.get(key)!=item for key,item in task.a2a_cli_context.items())):
        raise ValueError('FOREIGN_TERMINAL_TASK_RECEIPT')
    digest=hashlib.sha256(raw).hexdigest()
    with task.persistence_lock:
        worker=getattr(task,'a2a_cli_worker',None)
        if (not worker or worker['phase']!='dispatch-reserved' or worker['podUID']!=pod_uid
                or not worker.get('attachOperationId')):
            raise ValueError('DISPATCHED_WORKER_RECEIPT_REQUIRED')
        path=task.directory/'a2a-worker-terminal.json'
        if path.exists() or path.is_symlink():
            raise ValueError('TERMINAL_RECEIPT_EXISTS_RECONCILE_NO_OVERWRITE')
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            if os.name=='posix':
                directory_fd=os.open(task.directory,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(directory_fd)
                finally:os.close(directory_fd)
            worker['terminalReceiptSha256']=digest
            task.save()
        except BaseException:
            worker['phase']='persistence-uncertain';task.state='interrupted'
            try:task.save()
            except BaseException:pass
            raise
        return copy.deepcopy(worker)


def read_terminal_projection(task):
    """Read exact saved metadata; disk presence alone cannot repair uncertainty."""
    with task.persistence_lock:
        worker=copy.deepcopy(getattr(task,'a2a_cli_worker',None))
        if (not worker or worker['phase']!='dispatch-reserved' or not worker.get('attachOperationId')
                or not re.fullmatch(r'[a-f0-9]{64}',str(worker.get('terminalReceiptSha256')))):
            raise ValueError('DURABLE_TERMINAL_JOURNAL_BINDING_REQUIRED')
        path=task.directory/'a2a-worker-terminal.json'
        if path.is_symlink():raise ValueError('REGULAR_TERMINAL_RECEIPT_REQUIRED')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=4096:
                raise ValueError('BOUNDED_REGULAR_TERMINAL_RECEIPT_REQUIRED')
            with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(4097)
        finally:os.close(fd)
        if hashlib.sha256(raw).hexdigest()!=worker['terminalReceiptSha256']:
            raise ValueError('TERMINAL_RECEIPT_BYTES_CHANGED')
        value=decode_projection(raw.decode('utf-8'))
        if (value['scopeUid']!=worker['podUID']
                or any(value.get(key)!=item for key,item in task.a2a_cli_context.items())):
            raise ValueError('FOREIGN_TERMINAL_TASK_RECEIPT')
        return value


def validate_guard_ledger(task, raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > 65536:
        raise ValueError('BOUNDED_GUARD_LEDGER_BYTES_REQUIRED')
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('DUPLICATE_GUARD_LEDGER_FIELD')
            value[key]=item
        return value
    rows=[json.loads(line,object_pairs_hook=unique) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if not rows or len(rows)>8:raise ValueError('INVALID_GUARD_LEDGER_ROW_COUNT')
    schemas={
        'task-fenced':{'event','task_id','task_correlation_id','operation_id','utc'},
        'upstream-start-reserved':{'event','task_id','task_correlation_id','operation_correlation_id',
            'litellm_call_id','sequence','path','fingerprint','utc'},
        'upstream-finished':{'event','task_id','task_correlation_id','operation_correlation_id',
            'sequence','fingerprint','status','outcome','upstream_identity','upstream_identity_confirmed','utc'}}
    starts={};finishes=set();fenced=False
    for row in rows:
        if (not isinstance(row,dict) or row.get('event') not in schemas
                or set(row)!=schemas[row['event']] or row.get('task_id')!=task.id
                or row.get('task_correlation_id')!=task.correlation_id
                or not isinstance(row.get('utc'),str) or len(row['utc'])>64):
            raise ValueError('FOREIGN_OR_UNBOUNDED_GUARD_LEDGER')
        event=row['event']
        if event=='task-fenced':
            if fenced or not re.fullmatch(r'[a-f0-9]{32}',str(row['operation_id'])):
                raise ValueError('INVALID_GUARD_FENCE')
            fenced=True;continue
        if (type(row['sequence']) is not int or row['sequence']!=1
                or not re.fullmatch(r'[a-f0-9]{64}',str(row['fingerprint']))
                or row['operation_correlation_id']!=operation_correlation_id(task.correlation_id,1,row['fingerprint'])):
            raise ValueError('INVALID_GUARD_OPERATION_BINDING')
        if event=='upstream-start-reserved':
            if (fenced or starts or row['path'] not in {'/v1/messages','/v1/chat/completions','/v1/responses'}
                    or row['litellm_call_id']!=str(uuid.UUID(row['operation_correlation_id']))):
                raise ValueError('INVALID_GUARD_START_SEQUENCE')
            starts[1]=row
        else:
            identity=row['upstream_identity']
            if (1 not in starts or 1 in finishes or row['fingerprint']!=starts[1]['fingerprint']
                    or type(row['status']) is not int or not 100<=row['status']<=599
                    or row['outcome'] not in {'response-complete','caller-cancelled-or-disconnected','transport-failed'}
                    or not isinstance(identity,dict) or set(identity)-{'litellm_call_id'}
                    or type(row['upstream_identity_confirmed']) is not bool):
                raise ValueError('INVALID_GUARD_FINISH_SEQUENCE')
            if identity:
                uid(identity['litellm_call_id'])
            confirmed=identity.get('litellm_call_id')==str(uuid.UUID(row['operation_correlation_id']))
            if row['upstream_identity_confirmed']!=confirmed:
                raise ValueError('GUARD_SERVER_IDENTITY_FLAG_MISMATCH')
            finishes.add(1)
    # A retained ledger may be uncertain/incomplete. Retention is NOT LiteLLM
    # reconciliation and cannot qualify success by itself.
    return rows


def _read_guard_ledger_record(task):
    with task.persistence_lock:
        worker=copy.deepcopy(getattr(task,'a2a_cli_worker',None))
        if (not worker or worker['phase']!='dispatch-reserved'
                or not re.fullmatch(r'[a-f0-9]{64}',str(worker.get('guardLedgerSha256')))
                or not re.fullmatch(r'[a-f0-9]{32}',str(worker.get('guardAttachOperationId')))):
            raise ValueError('DURABLE_GUARD_JOURNAL_BINDING_REQUIRED')
        path=task.directory/'a2a-guard-ledger.jsonl'
        if path.is_symlink():raise ValueError('REGULAR_GUARD_LEDGER_REQUIRED')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=65536:
                raise ValueError('BOUNDED_REGULAR_GUARD_LEDGER_REQUIRED')
            with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(65537)
        finally:os.close(fd)
        if hashlib.sha256(raw).hexdigest()!=worker['guardLedgerSha256']:
            raise ValueError('GUARD_LEDGER_BYTES_CHANGED')
        rows=validate_guard_ledger(task,raw)
        if not any(row['event']=='task-fenced' and row['operation_id']==worker['guardAttachOperationId'] for row in rows):
            raise ValueError('GUARD_CAPTURE_OPERATION_UNVERIFIED')
        return raw,rows


def read_guard_ledger(task):return _read_guard_ledger_record(task)[1]


def read_guard_ledger_bytes(task):return _read_guard_ledger_record(task)[0]


def retain_guard_ledger(task, *, pod_uid, ledger_bytes):
    uid(pod_uid)
    validate_guard_ledger(task,ledger_bytes)
    ledger_sha256=hashlib.sha256(ledger_bytes).hexdigest()
    with task.persistence_lock:
        value=getattr(task,'a2a_cli_worker',None)
        if (not value or value['phase'] != 'dispatch-reserved' or value['podUID'] != pod_uid
                or value['guardLedgerSha256'] is not None):
            raise ValueError('WORKER_LEDGER_IDENTITY_UNCERTAIN')
        # Keep actual exact metadata bytes in the same protected Task directory,
        # BEFORE its journal mark. A caller-supplied hash is insufficient.
        path=task.directory/'a2a-guard-ledger.jsonl'
        if path.exists() or path.is_symlink():
            raise ValueError('GUARD_LEDGER_ALREADY_PRESENT_RECONCILE_NO_OVERWRITE')
        temp=task.directory/('guard-ledger-'+uuid.uuid4().hex+'.tmp')
        try:
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(ledger_bytes);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
            if os.name=='posix':
                directory_fd=os.open(task.directory,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(directory_fd)
                finally:os.close(directory_fd)
        except BaseException:
            value['phase']='persistence-uncertain';task.state='interrupted'
            try:task.save()
            except BaseException:pass
            raise
        finally:
            if temp.exists():temp.unlink()
        value['guardLedgerSha256']=ledger_sha256
        try:
            task.save()
        except BaseException:
            value['phase']='persistence-uncertain';task.state='interrupted'
            raise
        return copy.deepcopy(value)
