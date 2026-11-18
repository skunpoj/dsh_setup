"""Banking-only bounded multi-request ledger validation; native cap1 validator unchanged."""
import json,re,uuid
from scripts.dsh_correlation import operation_correlation_id
def uid(value):
    if str(uuid.UUID(value))!=value:raise ValueError("EXACT_GUARD_UID_REQUIRED")

def validate_banking_guard_ledger(task, raw, *, cap, fence_operation):
    if cap is not None and (type(cap) is not int or not 2<=cap<=32):raise ValueError("BANKING_GUARD_CAP_REQUIRED")
    if not isinstance(raw, bytes) or not raw or len(raw) > 262144:
        raise ValueError('BOUNDED_GUARD_LEDGER_BYTES_REQUIRED')
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('DUPLICATE_GUARD_LEDGER_FIELD')
            value[key]=item
        return value
    rows=[json.loads(line,object_pairs_hook=unique) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if not rows or cap is not None and len(rows)>2*cap+1:raise ValueError('INVALID_GUARD_LEDGER_ROW_COUNT')
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
        if (type(row['sequence']) is not int or not (1<=row['sequence'] and (cap is None or row['sequence']<=cap))
                or not re.fullmatch(r'[a-f0-9]{64}',str(row['fingerprint']))
                or row['operation_correlation_id']!=operation_correlation_id(task.correlation_id,row['sequence'],row['fingerprint'])):
            raise ValueError('INVALID_GUARD_OPERATION_BINDING')
        if event=='upstream-start-reserved':
            if (fenced or row['sequence']!=len(starts)+1 or row['path'] not in {'/v1/messages','/v1/chat/completions','/v1/responses'}
                    or row['litellm_call_id']!=str(uuid.UUID(row['operation_correlation_id']))):
                raise ValueError('INVALID_GUARD_START_SEQUENCE')
            starts[row['sequence']]=row
        else:
            identity=row['upstream_identity']
            if (row['sequence'] not in starts or row['sequence'] in finishes or row['fingerprint']!=starts[row['sequence']]['fingerprint']
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
            finishes.add(row['sequence'])
    # A retained ledger may be uncertain/incomplete. Retention is NOT LiteLLM
    # reconciliation and cannot qualify success by itself.
    if not any(v.get('event')=='task-fenced' and v.get('operation_id')==fence_operation for v in rows):raise ValueError('BANKING_GUARD_EXACT_FENCE_MISSING')
    return rows

