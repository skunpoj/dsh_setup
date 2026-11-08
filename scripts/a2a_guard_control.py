"""One task-bound private stdin drain command; never a network control API.

Only metadata from the existing guard ledger is returned. Provider execution
and Pod termination still require independent controller observation.
"""
import base64
import hashlib
import re
import uuid
from types import SimpleNamespace
from scripts.a2a_worker_journal import validate_guard_ledger


def drain_once(request,*,task_id,correlation_id,pod_uid,server,ledger):
    expected={'kind','taskId','correlationId','podUID','operationId'}
    if (not isinstance(request,dict) or set(request)!=expected
            or request.get('kind')!='fence-and-snapshot'
            or request.get('taskId')!=task_id or request.get('correlationId')!=correlation_id
            or request.get('podUID')!=pod_uid
            or str(uuid.UUID(pod_uid))!=pod_uid
            or not re.fullmatch(r'[a-f0-9]{32}',str(request.get('operationId','')))
            or ledger.task_id!=task_id or ledger.task_correlation_id!=correlation_id):
        raise ValueError('FOREIGN_GUARD_DRAIN_OPERATION')
    proof=server.fence_and_drain(request['operationId'])
    if proof!={'localInflightDrained':True,'providerExecutionStoppedVerified':False}:
        raise ValueError('GUARD_LOCAL_DRAIN_UNVERIFIED')
    # Existing guard's lock is the sole ledger writer/serialization boundary.
    with ledger._locked():
        with ledger.path.open('rb') as stream:raw=stream.read(65537)
    if not raw or len(raw)>65536:raise ValueError('BOUNDED_GUARD_LEDGER_REQUIRED')
    rows=validate_guard_ledger(SimpleNamespace(id=task_id,correlation_id=correlation_id),raw)
    if (not rows or len(rows)>8 or any(not isinstance(row,dict)
            or row.get('task_id')!=task_id or row.get('task_correlation_id')!=correlation_id for row in rows)
            or not any(row.get('event')=='task-fenced'
                and row.get('operation_id')==request['operationId'] for row in rows)):
        raise ValueError('GUARD_LEDGER_TASK_OR_FENCE_MISMATCH')
    return dict(kind='DSH_GUARD_LOCAL_DRAIN_V1',taskId=task_id,correlationId=correlation_id,
        podUID=pod_uid,operationId=request['operationId'],localInflightDrained=True,
        providerExecutionStoppedVerified=False,ledgerSha256=hashlib.sha256(raw).hexdigest(),
        ledgerBase64=base64.b64encode(raw).decode('ascii'))
