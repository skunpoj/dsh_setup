"""Metadata joins only; no provider, database, key or log retrieval."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
import uuid
from scripts.unattended_model_guard import AdmissionLedger
from scripts.a2a_model_reconciliation import reconcile_metadata


class ModelReconciliationTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.task=SimpleNamespace(id='a'*32,correlation_id='b'*32)
        self.ledger=AdmissionLedger(Path(self.temp.name)/'guard.jsonl',self.task.id,1,
                                   task_correlation_id=self.task.correlation_id)
    def record(self,*,finish=True):
        _,_,sequence,mark,operation=self.ledger.reserve('/v1/messages',b'{"messages":[]}')
        call_id=str(uuid.UUID(operation))
        if finish:self.ledger.complete(sequence,mark,operation,200,'response-complete',
                                       upstream_identity={'litellm_call_id':call_id})
        self.ledger.fence('c'*32)
        return dict(request_id='chatcmpl-synthetic-response',litellm_call_id=call_id,
            model='custom_openai/deepseek-v4.1-flash',status='success',prompt_tokens=10,completion_tokens=3)
    def join(self,rows):
        return reconcile_metadata(self.task,guard_bytes=self.ledger.path.read_bytes(),provider_rows=rows)
    def test_exact_call_id_join_does_not_conflate_response_id_or_claim_retirement(self):
        row=self.record();result=self.join([row])
        self.assertEqual(result['matchedOperationCount'],1)
        self.assertEqual(result['providerRecordIds'],['chatcmpl-synthetic-response'])
        self.assertNotIn('providerResponseIds',result)
        self.assertTrue(result['providerMetadataIdentityMatched'])
        self.assertFalse(result['providerExecutionStoppedVerified'])
        self.assertFalse(result['untrackedProviderCallsExcluded']);self.assertFalse(result['workerRetired'])
    def test_missing_duplicate_or_foreign_provider_row_remains_unresolved(self):
        row=self.record();foreign={**row,'litellm_call_id':'11111111-1111-4111-8111-111111111111'}
        for rows in ([],[row,row],[foreign]):
            with self.subTest(rows=len(rows)),self.assertRaisesRegex(ValueError,'MISSING_DUPLICATE_OR_FOREIGN'):
                self.join(rows)
    def test_extra_raw_log_fields_external_models_and_bad_counts_are_refused(self):
        row=self.record()
        for change in ({'metadata':{'user_api_key':'synthetic-must-not-be-consumed'}},
                       {'model':'external-model'},{'prompt_tokens':True},{'completion_tokens':-1}):
            changed=copy.deepcopy(row);changed.update(change)
            with self.assertRaisesRegex(ValueError,'INVALID_OR_UNFILTERED'):self.join([changed])
    def test_guard_reservation_without_durable_completion_cannot_reconcile(self):
        row=self.record(finish=False)
        with self.assertRaisesRegex(ValueError,'COMPLETION_PERSISTENCE_UNRESOLVED'):self.join([row])
    def test_zero_reserved_starts_never_claims_global_provider_absence(self):
        self.ledger.fence('c'*32);result=self.join([])
        self.assertEqual(result['matchedOperationCount'],0)
        self.assertFalse(result['untrackedProviderCallsExcluded'])

    def test_conflicting_returned_call_identity_cannot_be_hidden_by_matching_query_row(self):
        row=self.record()
        rows=[json.loads(line) for line in self.ledger.path.read_text().splitlines()]
        finished=next(item for item in rows if item['event']=='upstream-finished')
        finished['upstream_identity']={'litellm_call_id':'11111111-1111-4111-8111-111111111111'}
        finished['upstream_identity_confirmed']=False
        raw=('\n'.join(json.dumps(item) for item in rows)+'\n').encode()
        with self.assertRaisesRegex(ValueError,'CONFLICTING_GUARD_PROVIDER_IDENTITY'):
            reconcile_metadata(self.task,guard_bytes=raw,provider_rows=[row])
