"""Actual worker/journal/capture composition with synthetic provider rows."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock
import uuid
from scripts.a2a_provider_capture import TaskProviderCapture,NAME,read_capture_bytes
from scripts.a2a_worker_receipt import terminal_projection
from scripts.unattended_model_guard import AdmissionLedger
from scripts import a2a_worker_journal as journal


class ProviderCaptureTests(TestCase):
    def setUp(self):
        from test_a2a_worker_controller import WorkerControllerTests
        self.f=WorkerControllerTests();self.f.setUp();self.task=self.f.task
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.task.directory=Path(self.temp.name)
        self.f.prepare();self.f.api.read_pod.return_value=self.f.pod;self.f.allow_models=1
        stream=Mock()
        def factory(**kwargs):stream.start.side_effect=kwargs['before_attach'];return stream
        self.f.controller.open_cli_stream(self.task,stream_factory=factory)
        result=dict(self.task.a2a_cli_context,scopeUid=self.f.pod['metadata']['uid'],stopped=True,
            processExitVerified=True,descendantAbsenceVerified=True,pidNamespaceInode=123,exitCode=0,output='synthetic')
        self.f.pod['status']['containerStatuses'][0]['state']={'terminated':dict(exitCode=0,
            finishedAt='synthetic',message=json.dumps(terminal_projection(result)))}
        self.f.controller.retain_terminal(self.task)
        self.ledger=AdmissionLedger(self.task.directory/'input-ledger.jsonl',self.task.id,1,
            task_correlation_id=self.task.correlation_id)
        self.f.pod['status']['containerStatuses'][1]['state']={'terminated':dict(exitCode=0,finishedAt='synthetic')}
        self.source=dict(sourceCommit='a'*40,imageDigest='sha256:'+'e'*64,exporterSha256='b'*64)
        self.query=Mock(side_effect=lambda query:dict(query=copy.deepcopy(query),source=copy.deepcopy(self.source),rows=[dict(self.row)]))
        self.capture=TaskProviderCapture(controller=self.f.controller,generation='g1',query_metadata=self.query,
            source_observer=lambda:copy.deepcopy(self.source),source_binding=self.source)
        self.binding=dict(subject='owner',generation='g1',taskId=self.task.id,correlationId=self.task.correlation_id,
            runtime='claude',project='project',writes=False,promptSha256=self.task.a2a_cli_worker['promptSha256'])
        self.task.save.reset_mock()

    def guard(self,*,start=True):
        if start:
            _,_,sequence,mark,operation=self.ledger.reserve('/v1/messages',b'{"messages":[]}')
            call_id=str(uuid.UUID(operation))
            self.ledger.complete(sequence,mark,operation,200,'response-complete',upstream_identity={'litellm_call_id':call_id})
            self.row=dict(request_id='chatcmpl-synthetic',litellm_call_id=call_id,
                model='deepseek-v4.1-flash',status='success',prompt_tokens=5,completion_tokens=2)
        self.ledger.fence('d'*32)
        self.task.a2a_cli_worker['guardAttachOperationId']='d'*32
        journal.retain_guard_ledger(self.task,pod_uid=self.f.pod['metadata']['uid'],ledger_bytes=self.ledger.path.read_bytes())
        self.task.save.reset_mock()

    def test_construction_is_inert_and_capture_retains_only_exact_metadata_once(self):
        self.query.assert_not_called();self.guard()
        result=self.capture(self.task,self.binding)
        self.assertEqual(self.query.call_count,1);self.assertFalse(result['providerExecutionStoppedVerified'])
        self.assertFalse(result['workerRetired']);self.assertTrue(result['providerMetadataIdentityMatched'])
        raw,value=read_capture_bytes(self.task)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),result['captureSha256'])
        self.assertEqual(set(value['rows'][0]),set(self.row))
        self.assertNotIn(self.task.request['prompt'],raw.decode())
        with self.assertRaisesRegex(ValueError,'NO_REQUERY'):self.capture(self.task,self.binding)
        self.query.assert_called_once()

    def test_zero_operation_selector_never_queries_all_provider_rows(self):
        self.guard(start=False)
        result=self.capture(self.task,self.binding)
        self.query.assert_not_called();self.assertFalse(result['queryExecuted'])
        self.assertEqual(result['matchedOperationCount'],0)
        self.assertFalse(result['untrackedProviderCallsExcluded'])

    def test_unfiltered_or_foreign_projection_is_not_saved_or_retried(self):
        self.guard()
        self.query.side_effect=lambda query:dict(query=query,source=self.source,
            rows=[{**self.row,'api_key':'synthetic-rejected'}])
        with self.assertRaisesRegex(ValueError,'INVALID_OR_UNFILTERED'):self.capture(self.task,self.binding)
        self.assertFalse((self.task.directory/NAME).exists())
        with self.assertRaisesRegex(ValueError,'NO_REQUERY'):self.capture(self.task,self.binding)
        self.query.assert_called_once()

    def test_query_timeout_remains_consumed_and_has_fixed_error(self):
        self.guard();self.query.side_effect=TimeoutError('synthetic provider detail must not escape')
        with self.assertRaisesRegex(RuntimeError,'QUERY_UNCERTAIN_NO_RETRY'):self.capture(self.task,self.binding)
        self.assertEqual(self.task.state,'interrupted')
        with self.assertRaisesRegex(ValueError,'NO_REQUERY'):self.capture(self.task,self.binding)
        self.query.assert_called_once()

    def test_recovery_of_complete_file_does_not_repeat_provider_query(self):
        self.guard();self.capture(self.task,self.binding)
        self.task.a2a_cli_worker.pop('providerCaptureSha256')
        self.task.a2a_cli_worker['providerCaptureStatus']='uncertain'
        result=self.capture.recover(self.task,self.binding)
        self.assertEqual(result['captureSha256'],hashlib.sha256((self.task.directory/NAME).read_bytes()).hexdigest())
        self.query.assert_called_once()
        (self.task.directory/NAME).write_bytes((self.task.directory/NAME).read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'CANONICAL_COMPLETE'):self.capture.recover(self.task,self.binding)

    def test_source_or_task_identity_changed_before_query_refuses(self):
        self.guard()
        with self.assertRaisesRegex(ValueError,'TASK_BINDING'):
            self.capture(self.task,{**self.binding,'generation':'foreign'})
        self.source['sourceCommit']='c'*40
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):self.capture(self.task,self.binding)
        self.query.assert_not_called()

    def test_recovery_refuses_current_source_drift_without_requery(self):
        self.guard();self.capture(self.task,self.binding)
        self.source['imageDigest']='sha256:'+'f'*64
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
            self.capture.recover(self.task,self.binding)
        self.query.assert_called_once()

    def test_foreign_query_response_is_not_retained(self):
        self.guard()
        self.query.side_effect=lambda query:dict(query={**query,'taskId':'f'*32},source=self.source,rows=[self.row])
        with self.assertRaisesRegex(ValueError,'FOREIGN_OR_UNPROVEN'):self.capture(self.task,self.binding)
        self.assertFalse((self.task.directory/NAME).exists());self.query.assert_called_once()

    def test_exporter_identity_change_during_query_is_not_retained(self):
        self.guard()
        def changed(query):
            response=dict(query=query,source=copy.deepcopy(self.source),rows=[self.row])
            self.source['imageDigest']='sha256:'+'f'*64
            return response
        self.query.side_effect=changed
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):self.capture(self.task,self.binding)
        self.assertFalse((self.task.directory/NAME).exists());self.query.assert_called_once()
