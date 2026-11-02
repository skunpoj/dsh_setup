import time
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from scripts.openshell_broker_transport import NativeBrokerTransport


class Event:
    def __init__(self,kind,value):
        self.kind=kind
        setattr(self,kind,SimpleNamespace(**({'data':value} if kind in ('stdout','stderr') else {'exit_code':value})))
    def WhichOneof(self,_):return self.kind


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.context={'subject':'alice','generation':'g1','taskId':'a'*32,'project':'project','bindingId':'b'*32,'workerUID':'native1'}
        self.operation='c'*32;self.expiry=time.time()+120
        state={**self.context,'phase':'dispatch-reserved','operationId':self.operation,'expiresAt':self.expiry,'fenced':False,'revoked':False,'allocationOperationId':'d'*32,'podUID':'pod1'}
        self.task=SimpleNamespace(request={'backend':'openshell','writes':False},openshell=state,
            execution_stage={'runtime':'claude','correlationId':'e'*32},execution_prompt='checked prompt',save=Mock())
        self.registry=Mock();self.registry.get.return_value=self.task
        self.rpc=Mock();self.rpc.clock.side_effect=time.time
        self.rpc.create.return_value=SimpleNamespace(sandbox=SimpleNamespace(metadata=SimpleNamespace(id='native1')))
        self.rpc.lookup.return_value=self.rpc.create.return_value
        self.rpc.execute.return_value=iter([Event('stdout',b'checked result'),Event('exit',0)])
        self.supervisor=Mock()
        self.supervisor.observe_exact.side_effect=lambda a:{**a,'podUID':'pod1'}
        self.supervisor.assign_exact.side_effect=lambda a:{**a,'assigned':True}
        self.supervisor.stop_exact.side_effect=lambda a,o:{**a,'operationId':o,'stopped':True}
        self.supervisor.verify_absent.side_effect=lambda a,o:{**a,'operationId':o,'absent':True}
        self.spec=Mock(return_value=object())
        self.transport=NativeBrokerTransport(self.registry,self.rpc,self.supervisor,self.spec)

    def test_dispatch_uses_stage_identity_and_memory_prompt_then_streams_typed_exit(self):
        receipt=self.transport.dispatch(self.context,self.operation)
        envelope=self.rpc.execute.call_args.args[2]
        self.assertEqual(envelope['runtime'],'claude');self.assertEqual(envelope['prompt'],'checked prompt')
        self.assertEqual(envelope['correlationId'],'e'*32)
        self.assertEqual(envelope['podUID'],'pod1')
        self.assertEqual(self.task.openshell['podUID'],'pod1')
        events=list(self.transport.events(self.context,self.operation))
        self.assertEqual(events[0],{'type':'output','text':'checked result'})
        self.assertEqual(events[1],{'type':'exit','exitCode':0,'workerUID':'native1','operationId':self.operation})
        self.assertFalse(receipt['unrestrictedFallback'])

    def test_uncertain_dispatch_never_relaunches(self):
        self.rpc.execute.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.transport.dispatch(self.context,self.operation)
        with self.assertRaisesRegex(ValueError,'NATIVE_STREAM_REPLAY'):self.transport.dispatch(self.context,self.operation)
        self.assertEqual(self.rpc.execute.call_count,1);self.assertEqual(self.supervisor.assign_exact.call_count,1)

    def test_foreign_assignment_cannot_start_native_process(self):
        self.supervisor.assign_exact.side_effect=lambda a:{**a,'subject':'bob','podUID':'pod1','assigned':True}
        with self.assertRaisesRegex(ValueError,'NATIVE_ASSIGNMENT_UNVERIFIED'):self.transport.dispatch(self.context,self.operation)
        self.rpc.execute.assert_not_called()

    def test_allocation_reservation_and_lookup_use_same_operation(self):
        self.task.openshell.update(phase='allocation-reserved',workerUID=None)
        context={k:v for k,v in self.context.items() if k!='workerUID'}
        value=self.transport.allocate(context,'d'*32,self.expiry)
        self.assertEqual(value['workerUID'],'native1')
        self.transport.lookup_allocation(context,'d'*32)
        self.rpc.lookup.assert_called_once_with('b'*32,'d'*32)
        self.assertEqual(self.rpc.create.call_count,1)

    def test_allocated_worker_can_be_cleaned_before_dispatch(self):
        self.task.openshell.update(phase='allocation-reserved',workerUID=None,podUID=None)
        context={k:v for k,v in self.context.items() if k!='workerUID'}
        self.transport.allocate(context,'d'*32,self.expiry)
        self.task.openshell.update(phase='stop-reserved',stopOperationId=self.operation,fenced=True,revoked=True)
        self.assertTrue(self.transport.stop_exact(self.context,self.operation)['stopped'])
        self.rpc.execute.assert_not_called()

    def test_assignment_cannot_silently_follow_replaced_pod(self):
        self.supervisor.assign_exact.side_effect=lambda a:{**a,'podUID':'replacement','assigned':True}
        with self.assertRaisesRegex(ValueError,'NATIVE_ASSIGNMENT_UNVERIFIED'):self.transport.dispatch(self.context,self.operation)
        self.rpc.execute.assert_not_called()

    def test_stop_and_absence_require_both_native_and_pod_identity(self):
        self.task.openshell.update(phase='stop-reserved',fenced=True,revoked=True,stopOperationId=self.operation,podUID='pod1')
        result=self.transport.stop_exact(self.context,self.operation)
        self.assertTrue(result['stopped'])
        self.assertEqual(self.supervisor.stop_exact.call_args.args[0]['podUID'],'pod1')
        self.supervisor.verify_absent.side_effect=lambda a,o:{**a,'podUID':'replacement','operationId':o,'absent':True}
        with self.assertRaisesRegex(ValueError,'EXACT_NATIVE_ABSENCE_UNVERIFIED'):self.transport.verify_absent(self.context,self.operation)

    def test_unreserved_stop_and_foreign_binding_never_reach_supervisor(self):
        with self.assertRaisesRegex(ValueError,'UNRESERVED_EXACT_NATIVE_STOP'):self.transport.stop_exact(self.context,self.operation)
        with self.assertRaisesRegex(ValueError,'STALE_TRANSPORT_BINDING'):self.transport.dispatch({**self.context,'subject':'bob'},self.operation)
        self.supervisor.stop_exact.assert_not_called();self.rpc.execute.assert_not_called()

    def test_broker_two_stage_handoff_uses_transport_and_exact_cleanup(self):
        from scripts.openshell_task_binding import BrokerOpenShellService
        self.task.id=self.context['taskId'];self.task.state='queued';self.task.openshell=None
        self.task.finished=threading.Event();self.task.correlation_id='f'*32;self.task.emit=Mock()
        self.task.request.update(project='project',runtime='sdk',prompt='draft',handoffRuntime='claude')
        trace=[];created=[];envelopes=[]
        def create(binding,operation,**kwargs):
            worker='native'+str(len(created)+1);created.append(worker);trace.append(('create',worker))
            return SimpleNamespace(sandbox=SimpleNamespace(metadata=SimpleNamespace(id=worker)))
        self.rpc.create.side_effect=create
        self.supervisor.observe_exact.side_effect=lambda a:{**a,'podUID':'pod-'+a['workerUID']}
        def execute(binding,operation,envelope):
            envelopes.append(envelope);trace.append(('execute',envelope['workerUID']))
            return iter([Event('stdout',b'checked draft'),Event('exit',0)])
        self.rpc.execute.side_effect=execute
        def stop(a,o):
            trace.append(('stop',a['workerUID']));return {**a,'operationId':o,'stopped':True}
        def absence(a,o):
            trace.append(('absent',a['workerUID']));return {**a,'operationId':o,'absent':True}
        self.supervisor.stop_exact.side_effect=stop;self.supervisor.verify_absent.side_effect=absence
        service=BrokerOpenShellService(self.registry,'alice','g1',self.transport,qualified=True)
        service.run_task('alice',self.task)
        self.assertEqual(self.task.state,'completed')
        self.assertEqual([e['runtime'] for e in envelopes],['sdk','claude'])
        self.assertNotEqual(envelopes[0]['correlationId'],envelopes[1]['correlationId'])
        self.assertIn('checked draft',envelopes[1]['prompt'])
        self.assertLess(trace.index(('absent','native1')),trace.index(('create','native2')))
        self.assertEqual([s['binding']['podUID'] for s in self.task.native_stages],['pod-native1','pod-native2'])
        self.assertEqual([s['executionId'] for s in self.task.native_stages],[e['operationId'] for e in envelopes])
        self.assertTrue(self.task.finished.is_set());self.assertIsNone(self.task.execution_prompt)


if __name__=='__main__':unittest.main()
