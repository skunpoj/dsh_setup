import unittest
from scripts.a2a_stage_journal import reserve, complete, complete_native, fence


class StageJournalTests(unittest.TestCase):
    def test_cli_main_exit_or_missing_scope_cannot_advance_handoff(self):
        stages=reserve([],runtime='claude',stage_id='a'*32,correlation_id='b'*32)
        proof=dict(stageId='a'*32,correlationId='b'*32,stopped=True,processExitVerified=True,
                   scopeUid='synthetic-scope')
        with self.assertRaisesRegex(ValueError,'TERMINAL_PROOF'):
            complete(stages,stage_id='a'*32,output='synthetic',terminal_receipt=proof)
        proof['descendantAbsenceVerified']=True;del proof['scopeUid']
        with self.assertRaisesRegex(ValueError,'TERMINAL_PROOF'):
            complete(stages,stage_id='a'*32,output='synthetic',terminal_receipt=proof)

    def native_record(self):
        context=dict(taskId='a'*32,sessionId='a'*32,subject='owner',generation='g1',operationId='c'*32)
        return dict(id='a'*32,project='project',correlationId='b'*32,state='completed',
            nativeSdk=dict(phase='stopped',taskId='a'*32,project='project',correlationId='b'*32,
                sessionId='a'*32,subject='owner',generation='g1',stopOperationId='c'*32,
                stopReceipt=dict(context,stopped=True,processExitVerified=True,descendantAbsenceVerified=True)))

    def test_native_completion_requires_exact_bound_stop_receipt(self):
        record=self.native_record()
        result=complete_native(self.first(),record=record,output='verified native answer')
        self.assertEqual(result[-1]['status'],'completed')
        record['nativeSdk']['stopReceipt']['operationId']='d'*32
        with self.assertRaisesRegex(ValueError,'NATIVE_TERMINAL'):
            complete_native(self.first(),record=record,output='answer')

    def test_native_completion_rejects_label_only_or_wrong_correlation(self):
        for key,value in [('nativeSdk',{'phase':'stopped'}),('correlationId','e'*32),('state','failed')]:
            record=self.native_record();record[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'NATIVE_TERMINAL'):
                complete_native(self.first(),record=record,output='answer')

    def first(self):
        return reserve([], runtime="sdk", stage_id="a"*32, correlation_id="b"*32)

    def done(self):
        return complete(self.first(), stage_id="a"*32, output="checked result",
                        terminal_receipt=dict(stageId="a"*32, correlationId="b"*32,
                                              stopped=True, processExitVerified=True,descendantAbsenceVerified=True))

    def test_verified_result_permits_unique_next_stage_without_storing_content(self):
        stages=self.done()
        self.assertNotIn("checked result", str(stages))
        result=reserve(stages,runtime="claude",stage_id="c"*32,correlation_id="d"*32)
        self.assertEqual(len(result),2)
        self.assertEqual(len(stages),1)

    def test_active_stage_cannot_start_second(self):
        with self.assertRaisesRegex(ValueError,"NOT_RETIRED"):
            reserve(self.first(),runtime="claude",stage_id="c"*32,correlation_id="d"*32)

    def test_recovery_fences_reservation_and_rejects_late_result(self):
        stages=fence(self.first())
        with self.assertRaisesRegex(ValueError,"FENCED"):
            complete(stages,stage_id="a"*32,output="late",terminal_receipt={})
        self.assertEqual(fence(stages),stages)

    def test_terminal_receipt_is_bound_to_stage_and_correlation(self):
        for receipt in ({},dict(stageId="a"*32,correlationId="e"*32,stopped=True,processExitVerified=True,descendantAbsenceVerified=True),
                        dict(stageId="a"*32,correlationId="b"*32,stopped=True,processExitVerified=False)):
            with self.subTest(receipt=receipt),self.assertRaisesRegex(ValueError,"PROOF"):
                complete(self.first(),stage_id="a"*32,output="answer",terminal_receipt=receipt)

    def test_duplicate_identity_and_third_stage_refuse(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            reserve(self.done(),runtime="claude",stage_id="c"*32,correlation_id="b"*32)
        second=reserve(self.done(),runtime="claude",stage_id="c"*32,correlation_id="d"*32)
        with self.assertRaisesRegex(ValueError,"LIMIT"):
            reserve(second,runtime="deepagents",stage_id="e"*32,correlation_id="f"*32)
