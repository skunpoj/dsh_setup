"""SDK private transport source contracts, no process/network/provider."""
import json
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_sdk_transport import SDKWorkerTransport
from scripts.official_sdk_control_peer import SDKFrameCodec


class SDKTransportTests(TestCase):
    def setUp(self):
        from test_a2a_sdk_worker import SDKWorkerTests
        self.request=SDKWorkerTests().request();self.stream=Mock()
        self.before_start=Mock();self.before_cancel=Mock()
        self.transport=SDKWorkerTransport(stream=self.stream,context=self.request['context'],
            timeout_seconds=120,before_start=self.before_start,before_cancel=self.before_cancel)
    def start(self):self.transport.start(self.request['bootstrap'])
    def codec(self):return SDKFrameCodec(b'x'*32,self.request['bootstrap']['binding'])
    def test_inert_constructor_then_one_bootstrap_after_existing_journal_callback(self):
        self.stream.start.assert_not_called();self.before_start.assert_not_called()
        self.start();self.before_start.assert_called_once();self.stream.start.assert_called_once()
        request=json.loads(self.stream.send_line.call_args.args[0])
        self.assertEqual(request['bootstrap']['options']['cwd'],'/workspace')
        with self.assertRaisesRegex(ValueError,'CONSUMED'):self.start()
        self.stream.send_line.assert_called_once()
    def test_both_directions_preserve_authenticated_frames_with_separate_sequences(self):
        self.start()
        outgoing=self.codec().encode(dict(kind='call',id='d'*32,method='start',params={}))
        self.transport.send(outgoing)
        sent=json.loads(self.stream.send_line.call_args.args[0])
        self.assertEqual(sent['kind'],'sdk-frame');self.assertEqual(sent['frame'],outgoing)
        response=self.codec().encode(dict(kind='response',id='d'*32,ok=True,result=None))
        self.stream.receive_line.return_value=json.dumps(dict(kind='sdk-frame',
            context=self.request['context'],frame=response))
        self.assertEqual(self.transport.receive(),response)
        with self.assertRaises(ValueError):self.transport.receive()  # Same response cannot replay.
    def test_bad_mac_fences_rpc_but_one_exact_stop_is_still_possible(self):
        self.start();frame=json.loads(self.codec().encode({'kind':'call'}));frame['mac']='0'*64
        with self.assertRaises(ValueError):self.transport.send(json.dumps(frame))
        self.stream.send_line.assert_called_once()
        with self.assertRaises(ValueError):self.transport.send(self.codec().encode({'kind':'call'}))
        result=self.transport.cancel_once('e'*32)
        self.assertFalse(result['processExitVerified']);self.before_cancel.assert_called_once_with('e'*32)
        request=json.loads(self.stream.send_line.call_args.args[0]);self.assertEqual(request['kind'],'cancel')
        with self.assertRaisesRegex(ValueError,'NO_RESEND'):self.transport.cancel_once('e'*32)
        self.assertEqual(self.stream.send_line.call_count,2)
    def test_terminal_frame_is_only_metadata_until_actual_pod_observation(self):
        self.start();receipt=dict(self.request['context'],stopped=True,processExitVerified=True,
            descendantAbsenceVerified=True,pidNamespaceInode=123,exitCode=0,output='')
        self.stream.receive_line.return_value=json.dumps(dict(kind='terminal',receipt=receipt))
        with self.assertRaisesRegex(EOFError,'ACTUAL_POD_OBSERVATION'):self.transport.receive()
        self.assertEqual(self.transport.terminal,receipt)
        self.transport.failed=False  # Terminal publication itself fences RPC, independently of fault flag timing.
        with self.assertRaisesRegex(ValueError,'NOT_OPEN'):
            self.transport.send(self.codec().encode(dict(kind='call',id='f'*32,method='run',params={})))
        with self.assertRaisesRegex(ValueError,'RECONCILE_ONLY'):self.transport.cancel_once('e'*32)
        self.before_cancel.assert_not_called();self.stream.send_line.assert_called_once()
        self.assertIsNone(self.transport.cancel_operation)
    def test_cancel_first_and_terminal_observation_have_one_delivery_boundary(self):
        from threading import Event,Thread,Lock,current_thread
        self.start();entered=Event();release=Event();attempted=Event();terminal_done=Event()
        results=[];errors=[];order=[]
        class ObservedLock:
            def __init__(self):self.lock=Lock()
            def __enter__(self):
                if current_thread().name=='sdk-terminal-observer':attempted.set()
                self.lock.acquire();return self
            def __exit__(self,*_):self.lock.release()
        self.transport.write_lock=ObservedLock()
        def write(raw):
            self.assertEqual(json.loads(raw)['kind'],'cancel');entered.set()
            if not release.wait(5):raise TimeoutError('synthetic cancel not released')
            order.append('cancel-delivered')
        self.stream.send_line.side_effect=write
        receipt=dict(self.request['context'],stopped=True,processExitVerified=True,
            descendantAbsenceVerified=True,pidNamespaceInode=123,exitCode=0,output='')
        self.stream.receive_line.return_value=json.dumps(dict(kind='terminal',receipt=receipt))
        def cancel():
            try:results.append(self.transport.cancel_once('e'*32))
            except BaseException as error:errors.append(error)
        def terminal():
            try:self.transport.receive()
            except EOFError:order.append('terminal-observed')
            except BaseException as error:errors.append(error)
            finally:terminal_done.set()
        sender=Thread(target=cancel,name='sdk-cancel-writer');observer=Thread(target=terminal,name='sdk-terminal-observer')
        sender.start()
        try:
            self.assertTrue(entered.wait(5));observer.start()
            self.assertTrue(attempted.wait(5))
            self.assertFalse(terminal_done.is_set());self.assertIsNone(self.transport.terminal)
        finally:
            release.set();sender.join(timeout=5)
            if observer.ident is not None:observer.join(timeout=5)
        self.assertFalse(sender.is_alive());self.assertFalse(observer.is_alive());self.assertEqual(errors,[])
        self.assertEqual(order,['cancel-delivered','terminal-observed'])
        self.assertTrue(results[0]['stopFrameDelivered'])
        self.assertEqual(self.transport.terminal,receipt);self.before_cancel.assert_called_once()
        with self.assertRaisesRegex(ValueError,'RECONCILE_ONLY'):self.transport.cancel_once('f'*32)
        self.assertEqual(self.stream.send_line.call_count,2)

    def test_failed_launch_reservation_never_attaches_or_sends_bootstrap(self):
        self.before_start.side_effect=OSError('synthetic launch reservation failure')
        with self.assertRaises(OSError):self.start()
        self.stream.start.assert_not_called();self.stream.send_line.assert_not_called()
        self.stream.close.assert_called_once()
        with self.assertRaisesRegex(ValueError,'CONSUMED'):self.start()
    def test_cancellation_during_launch_callback_prevents_attach(self):
        self.before_start.side_effect=lambda:setattr(self.transport,'cancel_operation','e'*32)
        with self.assertRaisesRegex(ValueError,'FENCED_BEFORE_ATTACH'):self.start()
        self.stream.start.assert_not_called();self.stream.send_line.assert_not_called()
    def test_failed_stop_reservation_never_sends_or_retries_stop(self):
        self.start();self.before_cancel.side_effect=OSError('synthetic stop reservation failure')
        with self.assertRaises(OSError):self.transport.cancel_once('e'*32)
        self.stream.send_line.assert_called_once()
        self.stream.close.assert_called_once()
        with self.assertRaisesRegex(ValueError,'NO_RESEND'):self.transport.cancel_once('e'*32)
        self.before_cancel.assert_called_once()
