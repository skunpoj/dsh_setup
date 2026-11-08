"""Synthetic receipt validation; no root file or process operation is run."""
import json
from unittest import TestCase
from unittest.mock import patch
from scripts.a2a_worker_receipt import terminal_projection,decode_projection,TerminationSink


class WorkerReceiptTests(TestCase):
    def receipt(self):
        return dict(subject='owner',stageId='a'*32,correlationId='b'*32,project='private',runtime='claude',
            scopeUid='22222222-2222-4222-8222-222222222222',stopped=True,processExitVerified=True,
            descendantAbsenceVerified=True,pidNamespaceInode=12345,exitCode=0,output='synthetic private answer')

    def test_projection_contains_metadata_and_hash_not_private_answer(self):
        value=terminal_projection(self.receipt());raw=json.dumps(value)
        self.assertNotIn('synthetic private answer',raw)
        self.assertNotIn('output',value)
        self.assertEqual(decode_projection(raw),value)

    def test_no_pid_only_or_forged_extra_message_can_be_accepted(self):
        receipt=self.receipt();receipt['descendantAbsenceVerified']=False
        with self.assertRaises(ValueError):terminal_projection(receipt)
        value=terminal_projection(self.receipt());value['unadmitted']='synthetic'
        with self.assertRaisesRegex(ValueError,'UNADMITTED'):decode_projection(json.dumps(value))

    def test_duplicate_fields_and_oversized_message_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):
            decode_projection('{"outputSha256":"a","outputSha256":"b"}')
        with self.assertRaisesRegex(ValueError,'BOUNDED'):decode_projection('x'*4097)

    def test_cancel_requires_exact_operation_and_never_claims_an_output(self):
        receipt=self.receipt();receipt.update(cancelled=True,neverStarted=True,exitCode=None,output='')
        with self.assertRaisesRegex(ValueError,'STOP_OPERATION'):terminal_projection(receipt)
        receipt['operationId']='c'*32
        value=terminal_projection(receipt)
        self.assertTrue(value['neverStarted']);self.assertTrue(value['cancelled'])

    def test_sink_refuses_ordinary_test_or_broker_process_before_opening_any_file(self):
        with patch('scripts.a2a_worker_receipt.os.getpid',return_value=123), \
             self.assertRaisesRegex(ValueError,'PRIVATE_WORKER_INIT'):TerminationSink()
