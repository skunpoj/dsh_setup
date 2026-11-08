"""Exact identity join for ONE task's guard and metadata-only provider rows.

No API/SQL/authentication, credential discovery or implicit projection of raw
spend logs. A protected owner must supply a task-scoped metadata-only query and
retain its authoritative receipt. This join alone grants no retirement or live
acceptance and does not prove provider computation stopped.
"""
import hashlib
import json
import re
import uuid
from scripts.a2a_worker_journal import validate_guard_ledger

FIELDS={'request_id','litellm_call_id','model','status','prompt_tokens','completion_tokens'}
MODELS={'deepseek-v4.1-flash','custom_openai/deepseek-v4.1-flash'}


def reconcile_metadata(task,*,guard_bytes,provider_rows):
    rows=validate_guard_ledger(task,guard_bytes)
    if not any(row['event']=='task-fenced' for row in rows):
        raise ValueError('FENCED_GUARD_LEDGER_REQUIRED_BEFORE_RECONCILIATION')
    starts=[row for row in rows if row['event']=='upstream-start-reserved']
    finishes=[row for row in rows if row['event']=='upstream-finished']
    if len(starts)!=len(finishes):raise ValueError('GUARD_COMPLETION_PERSISTENCE_UNRESOLVED')
    # Missing response identity may be resolved by the protected provider
    # projection. A contradictory identity already returned by that route
    # cannot be silently discarded in favour of the generated request ID.
    for row in finishes:
        returned=row['upstream_identity'].get('litellm_call_id')
        if returned is not None and returned!=str(uuid.UUID(row['operation_correlation_id'])):
            raise ValueError('CONFLICTING_GUARD_PROVIDER_IDENTITY')
    if not isinstance(provider_rows,list) or len(provider_rows)>2:
        raise ValueError('BOUNDED_TASK_ONLY_PROVIDER_PROJECTION_REQUIRED')
    for row in provider_rows:
        if (not isinstance(row,dict) or set(row)!=FIELDS
                or not isinstance(row['request_id'],str)
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',row['request_id'])
                or not isinstance(row['litellm_call_id'],str)
                or str(uuid.UUID(row['litellm_call_id']))!=row['litellm_call_id']
                or not isinstance(row['model'],str) or row['model'] not in MODELS
                or not isinstance(row['status'],str) or row['status'] not in {'success','failure'}
                or any(type(row[key]) is not int or not 0<=row[key]<=2**31-1
                    for key in ('prompt_tokens','completion_tokens'))):
            raise ValueError('INVALID_OR_UNFILTERED_PROVIDER_METADATA_PROJECTION')
    expected={str(uuid.UUID(row['operation_correlation_id'])) for row in starts}
    actual=[row['litellm_call_id'] for row in provider_rows]
    if len(actual)!=len(set(actual)) or len(actual)!=len(expected) or set(actual)!=expected:
        raise ValueError('PROVIDER_IDENTITY_MISSING_DUPLICATE_OR_FOREIGN')
    if len({row['request_id'] for row in provider_rows})!=len(provider_rows):
        raise ValueError('DUPLICATE_PROVIDER_RESPONSE_ID')
    canonical=json.dumps(provider_rows,sort_keys=True,separators=(',',':')).encode()
    return dict(kind='DSH_TASK_MODEL_METADATA_JOIN_V2',taskId=task.id,
        correlationId=task.correlation_id,matchedOperationCount=len(starts),
        guardSha256=hashlib.sha256(guard_bytes).hexdigest(),
        providerProjectionSha256=hashlib.sha256(canonical).hexdigest(),
        operations=[dict(operationId=row['operation_correlation_id'],
            litellmCallId=str(uuid.UUID(row['operation_correlation_id']))) for row in starts],
        providerRecordIds=[row['request_id'] for row in provider_rows],
        providerMetadataIdentityMatched=True,providerExecutionStoppedVerified=False,
        untrackedProviderCallsExcluded=False,workerRetired=False)
