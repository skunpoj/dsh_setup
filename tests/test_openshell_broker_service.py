import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from scripts.openshell_task_binding import BrokerOpenShellService


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.task=SimpleNamespace(id="a"*32,request={"project":"project"},state="queued",openshell=None,save=Mock())
        self.registry=Mock();self.registry.get.return_value=self.task
        self.transport=Mock()
        self.transport.allocate.side_effect=lambda c,o,e:{**c,"workerUID":"worker1","operationId":o}
        self.service=BrokerOpenShellService(self.registry,"alice","g1",self.transport,qualified=True)

    def call(self,op,body=None,subject="alice"):
        return self.service.operate(subject,self.task.id,op,{"approved":True} if body is None else body)

    def test_server_identity_and_binding_not_caller_selected(self):
        value=self.call("bind")
        self.assertEqual(value["subject"],"alice");self.assertEqual(value["generation"],"g1")
        with self.assertRaises(ValueError):self.call("bind",{"approved":True,"subject":"bob"})
        self.assertEqual(self.transport.allocate.call_count,1)

    def test_foreign_subject_never_reaches_transport(self):
        with self.assertRaises(ValueError):self.call("bind",subject="bob")
        self.transport.allocate.assert_not_called()

    def test_default_unqualified_refuses(self):
        service=BrokerOpenShellService(self.registry,"alice","g1",self.transport)
        with self.assertRaises(ValueError):service.operate("alice",self.task.id,"bind",{"approved":True})
        self.transport.allocate.assert_not_called()

    def test_expired_admission_blocks_new_work_but_allows_exact_cleanup(self):
        import time
        state=self.call('bind')
        self.service.admission_expires_at=time.time()-1
        self.assertFalse(self.service.qualified)
        with self.assertRaisesRegex(ValueError,'NATIVE_ADMISSION_EXPIRED'):self.call('dispatch')
        self.call('revoke')
        self.transport.stop_exact.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'stopped':True}
        self.transport.verify_absent.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'absent':True}
        self.call('stop');self.assertEqual(self.task.openshell['phase'],'stopped')
        self.transport.dispatch.assert_not_called()

    def test_full_typed_lifecycle_uses_existing_task_state(self):
        state=self.call("bind")
        ctx={k:state[k] for k in ("subject","generation","taskId","project","bindingId","workerUID")}
        self.transport.dispatch.side_effect=lambda c,o:{**c,"operationId":o,"nativeRequired":True,"unrestrictedFallback":False}
        self.call("dispatch");self.call("revoke")
        self.transport.stop_exact.side_effect=lambda c,o:{"workerUID":c["workerUID"],"operationId":o,"stopped":True}
        self.transport.verify_absent.side_effect=lambda c,o:{"workerUID":c["workerUID"],"operationId":o,"absent":True}
        self.call("stop");self.assertEqual(self.task.openshell["phase"],"stopped")
        self.assertEqual(self.transport.dispatch.call_count,1)
        with self.assertRaises(ValueError):self.call("dispatch")

    def test_recovered_binding_rejects_new_generation(self):
        self.call("bind")
        successor=BrokerOpenShellService(self.registry,"alice","g2",self.transport,qualified=True)
        with self.assertRaisesRegex(ValueError,"STALE_SERVER_IDENTITY"):
            successor.operate("alice",self.task.id,"dispatch",{"approved":True})
        self.transport.dispatch.assert_not_called()

    def test_uncertain_allocation_is_reserved_and_never_recreated(self):
        self.transport.allocate.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.call("bind")
        self.assertEqual(self.task.openshell["phase"],"allocation-reserved")
        with self.assertRaises(ValueError):self.call("bind")
        with self.assertRaises(ValueError):self.call("dispatch")
        self.assertEqual(self.transport.allocate.call_count,1)
        self.transport.dispatch.assert_not_called()

    def test_recovery_looks_up_exact_allocation_without_creation(self):
        self.transport.allocate.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.call("bind")
        self.transport.lookup_allocation.side_effect=lambda c,o:{**c,"operationId":o,"workerUID":"recovered-worker"}
        value=self.call("resolve")
        self.assertEqual(value["workerUID"],"recovered-worker")
        self.assertEqual(self.transport.allocate.call_count,1)

    def test_wrong_allocation_receipt_stays_fenced(self):
        self.transport.allocate.side_effect=lambda c,o,e:{**c,"subject":"bob","operationId":o,"workerUID":"worker1"}
        with self.assertRaises(ValueError):self.call("bind")
        self.assertTrue(self.task.openshell["fenced"])
        self.assertIsNone(self.task.openshell["workerUID"])

    def test_recovery_stops_old_generation_without_model_replay(self):
        self.call("bind");self.task.request['backend']='openshell';self.task.emit=Mock()
        self.registry.tasks={self.task.id:self.task}
        self.transport.stop_exact.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'stopped':True}
        self.transport.verify_absent.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'absent':True}
        successor=BrokerOpenShellService(self.registry,'alice','g2',self.transport,qualified=True)
        self.assertEqual(len(successor.recover_pending()),1)
        self.assertEqual(self.task.state,'interrupted');self.assertEqual(self.task.openshell['phase'],'stopped')
        self.transport.dispatch.assert_not_called();self.assertEqual(self.transport.allocate.call_count,1)

    def test_recovery_refuses_another_subject(self):
        self.call('bind');self.task.request['backend']='openshell';self.registry.tasks={self.task.id:self.task}
        successor=BrokerOpenShellService(self.registry,'bob','g2',self.transport,qualified=True)
        with self.assertRaisesRegex(ValueError,'FOREIGN_RECOVERY_SUBJECT'):successor.recover_pending()
        self.transport.stop_exact.assert_not_called()

    def prepare_native_handoff(self):
        self.task.request.update(runtime='sdk', backend='openshell', prompt='draft',
                                 handoffRuntime='claude', handoffPrompt='Check the draft.')
        self.task.finished=threading.Event()
        self.task.correlation_id='b'*32
        self.task.emit=Mock()
        self.trace=[]
        self.dispatched=[]
        def allocate(context,operation,expiry):
            worker='worker-'+str(len(self.dispatched))
            self.trace.append(('allocate',worker))
            return {**context,'workerUID':worker,'operationId':operation}
        def dispatch(context,operation):
            self.dispatched.append((dict(context),dict(self.task.execution_stage),self.task.execution_prompt))
            self.trace.append(('dispatch',context['workerUID']))
            return {**context,'operationId':operation,'nativeRequired':True,'unrestrictedFallback':False}
        def events(context,operation):
            yield {'type':'output','text':'checked native result'}
            yield {'type':'exit','exitCode':0,'workerUID':context['workerUID'],'operationId':operation}
        def absent(context,operation):
            self.trace.append(('absent',context['workerUID']))
            return {'workerUID':context['workerUID'],'operationId':operation,'absent':True}
        self.transport.allocate.side_effect=allocate
        self.transport.dispatch.side_effect=dispatch
        self.transport.events.side_effect=events
        self.transport.stop_exact.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'stopped':True}
        self.transport.verify_absent.side_effect=absent

    def test_native_handoff_cleans_first_worker_before_fresh_stage(self):
        self.prepare_native_handoff()
        self.service.run_task('alice',self.task)
        self.assertEqual(self.task.state,'completed')
        self.assertTrue(self.task.finished.is_set())
        self.assertEqual([s[1]['runtime'] for s in self.dispatched],['sdk','claude'])
        self.assertNotEqual(self.dispatched[0][0]['bindingId'],self.dispatched[1][0]['bindingId'])
        self.assertNotEqual(self.dispatched[0][1]['correlationId'],self.dispatched[1][1]['correlationId'])
        self.assertLess(self.trace.index(('absent','worker-0')),self.trace.index(('allocate','worker-1')))
        self.assertIn('Check the draft.',self.dispatched[1][2])
        self.assertIn('checked native result',self.dispatched[1][2])
        self.assertEqual(len(self.task.native_stages),2)
        self.assertTrue(all(s['binding']['phase']=='stopped' for s in self.task.native_stages))
        self.assertIsNone(self.task.execution_prompt)

    def test_native_handoff_never_advances_on_uncertain_absence(self):
        self.prepare_native_handoff()
        self.transport.verify_absent.side_effect=TimeoutError
        self.service.run_task('alice',self.task)
        self.assertEqual(self.task.state,'interrupted')
        self.assertEqual(self.transport.allocate.call_count,1)
        self.assertEqual(self.transport.dispatch.call_count,1)
        self.assertEqual(self.task.openshell['phase'],'stop-reserved')
        self.assertIsNone(self.task.execution_prompt)

    def test_native_failed_first_stage_never_dispatches_second(self):
        self.prepare_native_handoff()
        self.transport.events.side_effect=lambda c,o:iter([{'type':'exit','exitCode':1,'workerUID':c['workerUID'],'operationId':o}])
        self.service.run_task('alice',self.task)
        self.assertEqual(self.task.state,'failed')
        self.assertEqual(self.transport.allocate.call_count,1)
        self.assertEqual(self.task.openshell['phase'],'stopped')

    def test_cancellation_at_native_handoff_prevents_next_allocation(self):
        self.prepare_native_handoff()
        def emit(kind,data):
            if kind=='handoff':self.task.state='cancelled'
        self.task.emit.side_effect=emit
        self.service.run_task('alice',self.task)
        self.assertEqual(self.task.state,'cancelled')
        self.assertEqual(self.transport.allocate.call_count,1)
        self.assertEqual(self.task.openshell['phase'],'stopped')

    def test_cancelled_after_binding_cannot_be_overwritten_by_running(self):
        self.prepare_native_handoff()
        original=self.service.operate
        def cancel_after_bind(subject,task_id,operation,body):
            result=original(subject,task_id,operation,body)
            if operation=='bind':self.service.cancel_task(subject,self.task)
            return result
        self.service.operate=cancel_after_bind
        self.service.run_task('alice',self.task)
        self.assertEqual(self.task.state,'cancelled')
        self.assertTrue(self.task.finished.is_set())
        self.transport.dispatch.assert_not_called()
        self.assertEqual(self.task.openshell['phase'],'stopped')


if __name__=="__main__":unittest.main()
