import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch
from scripts.openshell_worker_execution import run,validate


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"state"
        self.assigned=dict(subject="alice",generation="g1",taskId="a"*32,project=".",bindingId="b1",workerUID="w1",expiresAt=120)
        self.value={**self.assigned,"operationId":"b"*32,"correlationId":"c"*32,"runtime":"sdk","prompt":"synthetic","writes":False}
        self.child=Mock(pid=98765);self.child.wait.return_value=0
        self.popen=Mock(return_value=self.child);self.builder=Mock(return_value=["fixed-client"])
        self.now=100
    def tearDown(self):self.temp.cleanup()
    def run_worker(self):
        with patch("scripts.openshell_worker_execution.os.killpg",create=True) as kill, patch("scripts.openshell_worker_execution.signal.SIGKILL",9,create=True):
            value=run(self.value,self.assigned,self.root,self.builder,clock=lambda:self.now,popen=self.popen)
            self.signals=list(kill.call_args_list)
            return value
    def test_one_execution_per_binding_even_different_operation(self):
        self.run_worker();self.value["operationId"]="d"*32
        with self.assertRaises(FileExistsError):self.run_worker()
        self.assertEqual(self.popen.call_count,1)
        record=json.loads(next(self.root.glob("*.json")).read_text())
        self.assertNotIn("prompt",record)
    def test_timeout_fences_process_group(self):
        def deadline(**kwargs):
            if self.now==100:
                self.now=121
                raise subprocess.TimeoutExpired('client',20)
            return 0
        self.child.wait.side_effect=deadline
        result=self.run_worker();self.assertTrue(result["expired"])
        self.assertEqual(result["exitCode"],124);self.assertEqual(len(self.signals),2)
    def test_exit_also_cleans_descendants(self):
        self.assertEqual(self.run_worker()["exitCode"],0)
        self.assertEqual(len(self.signals),2)
    def test_foreign_identity_rejected_before_reservation(self):
        for key in ("subject","generation","taskId","project","bindingId","workerUID"):
            with self.assertRaises(ValueError):validate({**self.value,key:"wrong"},self.assigned,100)
        self.assertFalse(self.root.exists())
    def test_expired_or_extended_lifetime_rejected(self):
        with self.assertRaises(ValueError):validate(self.value,self.assigned,121)
        with self.assertRaises(ValueError):validate({**self.value,"expiresAt":130},self.assigned,100)
    def test_crash_before_launch_still_leaves_fence(self):
        self.popen.side_effect=OSError
        with self.assertRaises(OSError):self.run_worker()
        with self.assertRaises(FileExistsError):self.run_worker()
        self.assertEqual(self.popen.call_count,1)

    def test_handoff_uses_distinct_guard_execution_ids_with_same_parent(self):
        self.run_worker()
        self.assertEqual(self.builder.call_args.args[4],'b'*32)
        first_env=self.popen.call_args.kwargs['env']
        self.assigned.update(bindingId='b2',workerUID='w2')
        self.value.update(self.assigned,operationId='d'*32,correlationId='e'*32,runtime='claude')
        self.run_worker()
        second_env=self.popen.call_args.kwargs['env']
        self.assertEqual(self.builder.call_args.args[4],'d'*32)
        self.assertNotEqual(first_env['DSH_UNATTENDED_TASK'],second_env['DSH_UNATTENDED_TASK'])
        self.assertEqual(first_env['DSH_PARENT_TASK_ID'],second_env['DSH_PARENT_TASK_ID'])
        self.assertEqual(first_env['DSH_PARENT_TASK_ID'],'a'*32)
        self.assertEqual(self.popen.call_count,2)

    def test_cancel_before_launch_reserves_without_starting_client(self):
        result=run(self.value,self.assigned,self.root,self.builder,clock=lambda:100,popen=self.popen,cancelled=lambda:True)
        self.assertEqual(result['exitCode'],143);self.popen.assert_not_called()
        self.assertEqual(len(list(self.root.glob('*.json'))),1)

    def test_cancel_after_spawn_still_kills_whole_process_group(self):
        checks=iter([False,True])
        with patch('scripts.openshell_worker_execution.os.killpg',create=True) as kill,patch('scripts.openshell_worker_execution.signal.SIGKILL',9,create=True):
            result=run(self.value,self.assigned,self.root,self.builder,clock=lambda:100,popen=self.popen,cancelled=lambda:next(checks))
        self.assertTrue(result['cancelled']);self.assertEqual(result['exitCode'],143)
        self.assertEqual(kill.call_count,2)


if __name__=="__main__":unittest.main()
