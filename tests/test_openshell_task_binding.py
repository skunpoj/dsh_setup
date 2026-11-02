import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from scripts.openshell_task_binding import OpenShellBinding


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.task=SimpleNamespace(id="a"*32,request={"project":"project"},openshell=None,save=Mock())
        self.transport=Mock()
        self.binding=OpenShellBinding(self.task,self.transport)
        self.context=dict(subject="alice",generation="g1",taskId=self.task.id,project="project",bindingId="b1",workerUID="uid1")
        self.binding.bind(self.context,time.time()+120)

    def test_foreign_identity_refused(self):
        for key in self.context:
            with self.assertRaises(ValueError):self.binding.resolve({**self.context,key:"wrong"})

    def test_dispatch_reservation_prevents_replay_after_transport_failure(self):
        self.transport.dispatch.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.binding.dispatch(self.context,"b"*32)
        with self.assertRaises(ValueError):self.binding.dispatch(self.context,"b"*32)
        self.assertEqual(self.transport.dispatch.call_count,1)
        self.assertEqual(self.task.openshell["phase"],"dispatch-reserved")

    def test_native_receipt_and_durable_task_journal(self):
        self.transport.dispatch.return_value={**self.context,"operationId":"b"*32,"nativeRequired":True,"unrestrictedFallback":False}
        self.binding.dispatch(self.context,"b"*32)
        self.assertEqual(self.task.openshell["phase"],"running")
        self.assertGreaterEqual(self.task.save.call_count,3)

    def test_revoke_fences_dispatch(self):
        self.binding.revoke(self.context)
        with self.assertRaises(ValueError):self.binding.dispatch(self.context,"b"*32)
        self.transport.dispatch.assert_not_called()

    def test_stop_requires_exact_absence_and_preserves_operation(self):
        op="c"*32
        self.transport.stop_exact.return_value=dict(workerUID="uid1",stopped=True,operationId=op)
        self.transport.verify_absent.return_value=dict(workerUID="wrong",absent=True,operationId=op)
        with self.assertRaises(ValueError):self.binding.stop(self.context,op)
        self.assertEqual(self.task.openshell["phase"],"stop-reserved")
        self.transport.verify_absent.return_value=dict(workerUID="uid1",absent=True,operationId=op)
        self.binding.stop(self.context,op)
        calls=self.transport.stop_exact.call_count
        self.binding.stop(self.context,op)
        self.assertEqual(self.transport.stop_exact.call_count,calls)

    def test_expired_binding_refused(self):
        self.task.openshell["expiresAt"]=time.time()-1
        with self.assertRaises(ValueError):self.binding.resolve(self.context)


if __name__=="__main__":unittest.main()
