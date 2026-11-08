"""Pinned LiteLLM1.93.0 metadata SELECT; explicit approved identity only.

No driver import, environment/DATABASE_URL/master-key access or auth fallback.
The owner must supply the approved read-only identity/connection and actual
schema observation. Neither exists by default; source tests grant no access.
"""
import copy
import re
import time
import uuid
from scripts.a2a_model_reconciliation import FIELDS

SCHEMA=dict(version='1.93.0',imageDigest='sha256:4870893763aca143f590bd5685a25219037af027d1d27e97abcb17ac9ec5d09f',
            schemaSha256='f2d45d3252af3b35d4b223cba74a56c4e1b1f8de9023f07770eb5f8f43dc4222')
# litellm_call_id is a bounded JSON-property projection, NOT a physical column
# and NOT an alias for request_id. Retained exact Test receipts have a chatcmpl
# request_id and a distinct UUID guard/provider correlation in metadata.
DB_FIELDS=set(FIELDS)
SQL=('SELECT "request_id", "model", "status", "prompt_tokens", "completion_tokens", '
     '"metadata"::jsonb->>\'litellm_call_id\' AS litellm_call_id '
     'FROM "LiteLLM_SpendLogs" WHERE "metadata"::jsonb->>\'litellm_call_id\' = ANY(%s) LIMIT 2')


class LiteLLM193MetadataStore:
    def __init__(self,*,select_rows,schema_observer,identity_observer,identity_contract,clock=time.time):
        if (not callable(select_rows) or not callable(schema_observer) or not callable(identity_observer)
                or not isinstance(identity_contract,dict)
                or set(identity_contract)!={'kind','identity','receiptSha256','expiresAt'}
                or identity_contract['kind']!='DSH_READONLY_SPEND_ROUTE_V1'
                or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',str(identity_contract['identity']))
                or not re.fullmatch(r'[a-f0-9]{64}',str(identity_contract['receiptSha256']))
                or identity_contract['receiptSha256']=='0'*64):
            raise ValueError('APPROVED_EXPLICIT_READONLY_SPEND_ROUTE_REQUIRED')
        self.select,self.schema,self.identity=select_rows,schema_observer,identity_observer
        self.contract,self.clock=copy.deepcopy(identity_contract),clock

    def _admitted(self):
        if (type(self.contract['expiresAt']) not in (int,float)
                or not 0<self.contract['expiresAt']-self.clock()<=300
                or self.identity()!=self.contract or self.schema()!=SCHEMA):
            raise ValueError('SPEND_ROUTE_IDENTITY_SCHEMA_OR_EXPIRY_CHANGED')

    def select_task_metadata(self,*,columns,task_id,task_correlation_id,operation_ids):
        self._admitted()
        if (columns!=tuple(sorted(FIELDS)) or not isinstance(operation_ids,tuple) or len(operation_ids)!=1
                or any(not re.fullmatch(r'[a-f0-9]{32}',str(v)) for v in (task_id,task_correlation_id))
                or not isinstance(operation_ids[0],str) or str(uuid.UUID(operation_ids[0]))!=operation_ids[0]):
            raise ValueError('EXACT_BOUNDED_SPEND_OPERATION_ID_SELECTOR_REQUIRED')
        # Authorizer has bound these exact IDs to the Task guard before entry.
        # Select five direct columns and ONE named metadata property on the
        # server. Never fetch the complete metadata/prompt/response/API-key row.
        try:rows=self.select(SQL,(list(operation_ids),))
        except Exception:raise RuntimeError('READONLY_SPEND_QUERY_UNCERTAIN_NO_RETRY') from None
        self._admitted()
        if (not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict)
                or set(rows[0])!=DB_FIELDS or rows[0]['litellm_call_id']!=operation_ids[0]
                or not isinstance(rows[0]['request_id'],str)
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',rows[0]['request_id'])):
            raise ValueError('FOREIGN_OR_UNFILTERED_SPEND_ROW_REFUSED')
        return copy.deepcopy(rows)
