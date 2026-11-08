"""One task-scoped metadata capture in the EXISTING broker Task directory.

Protected owner injects an already approved metadata-only query and exact
exporter identity observer. No HTTP/SQL/default auth, credential discovery,
unfiltered spend-log projection, model call or automatic query retry exists.
"""
import copy
import hashlib
import json
import os
import re
import stat
import uuid
from scripts import a2a_worker_journal as journal
from scripts.a2a_factory_budget import sync_directory
from scripts.a2a_model_reconciliation import reconcile_metadata
from scripts.official_sdk_package_admission import unique_json

NAME='a2a-provider-capture.json'
MAX_BYTES=32768


def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()


def read_capture_bytes(task):
    path=task.directory/NAME
    if path.is_symlink():raise ValueError('REGULAR_PROVIDER_CAPTURE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=MAX_BYTES:
            raise ValueError('BOUNDED_PROVIDER_CAPTURE_REQUIRED')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(MAX_BYTES+1)
    finally:os.close(fd)
    value=unique_json(raw)
    if canonical(value)!=raw:raise ValueError('CANONICAL_COMPLETE_PROVIDER_CAPTURE_REQUIRED')
    return raw,value


def write_capture_once(task,value):
    raw=canonical(value)
    if len(raw)>MAX_BYTES:raise ValueError('BOUNDED_PROVIDER_CAPTURE_REQUIRED')
    fd=os.open(task.directory/NAME,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0),0o600)
    try:
        offset=0
        while offset<len(raw):
            written=os.write(fd,raw[offset:])
            if type(written) is not int or not 0<written<=len(raw)-offset:
                raise OSError('PROVIDER_CAPTURE_WRITE_UNRESOLVED')
            offset+=written
        os.fsync(fd)
    finally:os.close(fd)
    sync_directory(task.directory)
    saved,_=read_capture_bytes(task)
    if saved!=raw:raise ValueError('PROVIDER_CAPTURE_READBACK_CHANGED')
    return hashlib.sha256(raw).hexdigest()


class TaskProviderCapture:
    def __init__(self,*,controller,generation,query_metadata,source_observer,source_binding):
        if (not callable(query_metadata) or not callable(source_observer)
                or not isinstance(generation,str) or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',generation)
                or not isinstance(source_binding,dict)
                or set(source_binding)!={'sourceCommit','imageDigest','exporterSha256'}
                or not re.fullmatch(r'[a-f0-9]{40}',str(source_binding.get('sourceCommit')))
                or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(source_binding.get('imageDigest')))
                or not re.fullmatch(r'[a-f0-9]{64}',str(source_binding.get('exporterSha256')))
                or source_binding['sourceCommit']=='0'*40 or source_binding['imageDigest']=='sha256:'+'0'*64
                or source_binding['exporterSha256']=='0'*64):
            raise ValueError('PINNED_PROTECTED_PROVIDER_CAPTURE_DEPENDENCIES_REQUIRED')
        self.controller,self.generation=controller,generation
        self.query,self.observe=query_metadata,source_observer
        self.source=copy.deepcopy(source_binding)

    def _context(self,task,binding):
        worker=getattr(task,'a2a_cli_worker',None)
        expected=dict(subject=self.controller.subject,generation=self.generation,taskId=task.id,
            correlationId=task.correlation_id,runtime=task.request['runtime'],project=task.request['project'],
            writes=task.request['writes'],promptSha256=worker.get('promptSha256') if isinstance(worker,dict) else None)
        if (binding!=expected or task.authenticated_subject!=self.controller.subject
                or not isinstance(worker,dict) or not re.fullmatch(r'[a-f0-9]{64}',str(expected['promptSha256']))):
            raise ValueError('EXACT_PROVIDER_CAPTURE_TASK_BINDING_REQUIRED')
        self.controller.recover_terminal(task)
        self.controller.observe_drained_guard(task)
        return copy.deepcopy(worker)

    def _query_context(self,task,worker,guard,operation):
        rows=journal.validate_guard_ledger(task,guard)
        return dict(kind='DSH_TASK_PROVIDER_METADATA_QUERY_V1',subject=self.controller.subject,
            taskId=task.id,correlationId=task.correlation_id,namespace=worker['namespace'],
            namespaceUID=worker['namespaceUID'],podUID=worker['podUID'],captureOperationId=operation,
            guardSha256=hashlib.sha256(guard).hexdigest(),
            operationIds=[str(uuid.UUID(row['operation_correlation_id'])) for row in rows if row['event']=='upstream-start-reserved'])

    def __call__(self,task,binding):
        worker=self._context(task,binding)
        guard=journal.read_guard_ledger_bytes(task)
        if self.observe()!=self.source:raise ValueError('PROVIDER_CAPTURE_SOURCE_CHANGED')
        with task.persistence_lock:
            current=task.a2a_cli_worker
            if (current.get('providerCaptureOperationId') is not None
                    or current.get('guardLedgerSha256')!=hashlib.sha256(guard).hexdigest()):
                raise ValueError('PROVIDER_CAPTURE_ALREADY_RESERVED_OR_CHANGED_NO_REQUERY')
            operation=uuid.uuid4().hex
            current.update(providerCaptureOperationId=operation,providerCaptureStatus='reserved')
            task.save()  # No external query until this exact reservation is saved.
        request=self._query_context(task,worker,guard,operation)
        try:
            if request['operationIds']:
                try:response=self.query(copy.deepcopy(request))  # Exactly one metadata-only call.
                except Exception:raise RuntimeError('TASK_PROVIDER_CAPTURE_QUERY_UNCERTAIN_NO_RETRY') from None
                if (not isinstance(response,dict) or set(response)!={'query','source','rows'}
                        or response['query']!=request or response['source']!=self.source):
                    raise ValueError('FOREIGN_OR_UNPROVEN_PROVIDER_CAPTURE_RESPONSE')
                provider_rows=response['rows']
            else:provider_rows=[]  # Empty selector must never become an unfiltered query.
            if self.observe()!=self.source:raise ValueError('PROVIDER_CAPTURE_SOURCE_CHANGED')
            joined=reconcile_metadata(task,guard_bytes=guard,provider_rows=provider_rows)
            value=dict(kind='DSH_TASK_PROVIDER_CAPTURE_V1',query=request,source=self.source,
                rows=provider_rows,join=joined,queryExecuted=bool(request['operationIds']))
            with task.persistence_lock:
                if (task.a2a_cli_worker.get('providerCaptureOperationId')!=operation
                        or task.a2a_cli_worker.get('guardLedgerSha256')!=request['guardSha256']):
                    raise ValueError('PROVIDER_CAPTURE_RESERVATION_CHANGED')
                digest=write_capture_once(task,value)
                task.a2a_cli_worker.update(providerCaptureSha256=digest,providerCaptureStatus='retained')
                task.save()
            return {**joined,'captureSha256':digest,'captureOperationId':operation,'queryExecuted':value['queryExecuted']}
        except BaseException:
            with task.persistence_lock:
                task.a2a_cli_worker['providerCaptureStatus']='uncertain';task.state='interrupted'
                try:task.save()
                except BaseException:pass
            raise  # A timeout or invalid projection is never automatically queried again.

    def recover(self,task,binding):
        if self.observe()!=self.source:raise ValueError('PROVIDER_CAPTURE_SOURCE_CHANGED')
        worker=self._context(task,binding)
        guard=journal.read_guard_ledger_bytes(task)
        operation=worker.get('providerCaptureOperationId')
        if not re.fullmatch(r'[a-f0-9]{32}',str(operation)):
            raise ValueError('EXISTING_PROVIDER_CAPTURE_RESERVATION_REQUIRED')
        raw,value=read_capture_bytes(task)
        request=self._query_context(task,worker,guard,operation)
        if (not isinstance(value,dict) or set(value)!={'kind','query','source','rows','join','queryExecuted'}
                or value['kind']!='DSH_TASK_PROVIDER_CAPTURE_V1' or value['query']!=request
                or value['source']!=self.source or type(value['queryExecuted']) is not bool
                or value['queryExecuted']!=bool(request['operationIds'])):
            raise ValueError('PROVIDER_CAPTURE_FILE_BINDING_CHANGED')
        joined=reconcile_metadata(task,guard_bytes=guard,provider_rows=value['rows'])
        if joined!=value['join']:raise ValueError('PROVIDER_CAPTURE_RECONCILIATION_CHANGED')
        digest=hashlib.sha256(raw).hexdigest()
        with task.persistence_lock:
            if self.observe()!=self.source:raise ValueError('PROVIDER_CAPTURE_SOURCE_CHANGED')
            if (task.a2a_cli_worker.get('providerCaptureOperationId')!=operation
                    or task.a2a_cli_worker.get('providerCaptureSha256') not in (None,digest)):
                raise ValueError('PROVIDER_CAPTURE_DURABLE_HASH_CHANGED')
            task.a2a_cli_worker.update(providerCaptureSha256=digest,providerCaptureStatus='retained')
            task.save()
        return {**joined,'captureSha256':digest,'captureOperationId':operation,'queryExecuted':value['queryExecuted']}
