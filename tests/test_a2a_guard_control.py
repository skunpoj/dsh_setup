"""Private control contracts with a local guard; no provider requests."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_guard_control import drain_once
from scripts.unattended_model_guard import AdmissionLedger,GuardedServer


class GuardControlTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.task='a'*32;self.correlation='b'*32;self.pod='22222222-2222-4222-8222-222222222222'
        self.ledger=AdmissionLedger(Path(self.temp.name)/'ledger.jsonl',self.task,1,
                                    task_correlation_id=self.correlation)
        self.request=dict(kind='fence-and-snapshot',taskId=self.task,correlationId=self.correlation,
                          podUID=self.pod,operationId='c'*32)
    def call(self,server,request=None):
        return drain_once(self.request if request is None else request,task_id=self.task,
            correlation_id=self.correlation,pod_uid=self.pod,server=server,ledger=self.ledger)
    def test_actual_local_guard_fences_before_snapshot_without_reading_provider_token(self):
        server=GuardedServer(('127.0.0.1',0),'http://127.0.0.1:9',
            Path(self.temp.name)/'missing-provider-token',self.ledger,allow_test_upstream=True)
        try:
            result=self.call(server)
            raw=base64.b64decode(result['ledgerBase64'],validate=True)
            self.assertEqual(raw,self.ledger.path.read_bytes())
            self.assertEqual(result['ledgerSha256'],hashlib.sha256(raw).hexdigest())
            self.assertTrue(result['localInflightDrained'])
            self.assertFalse(result['providerExecutionStoppedVerified'])
            self.assertEqual(json.loads(raw)['event'],'task-fenced')
            accepted,*_=self.ledger.reserve('/v1/messages',b'{"messages":[]}')
            self.assertFalse(accepted)
        finally:server.server_close()
    def test_foreign_task_pod_or_operation_is_refused_before_fencing(self):
        for field,value in [('taskId','foreign'),('podUID','foreign'),('operationId','bad'),
                            ('correlationId','foreign'),('kind','restart')]:
            server=Mock();request={**self.request,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):self.call(server,request)
            server.fence_and_drain.assert_not_called()
        self.assertFalse(self.ledger.path.exists())
    def test_uncertain_drain_never_exports_a_ledger(self):
        server=Mock();server.fence_and_drain.return_value={'localInflightDrained':False}
        with self.assertRaisesRegex(ValueError,'DRAIN_UNVERIFIED'):self.call(server)
        self.assertFalse(self.ledger.path.exists())
    def test_unexpected_ledger_content_cannot_leave_guard(self):
        self.ledger.path.write_text(json.dumps(dict(event='task-fenced',task_id=self.task,
            task_correlation_id=self.correlation,operation_id='c'*32,utc='synthetic',
            unexpected='must not be exported'))+'\n')
        server=Mock();server.fence_and_drain.return_value=dict(localInflightDrained=True,
                                                           providerExecutionStoppedVerified=False)
        with self.assertRaises(ValueError):self.call(server)
