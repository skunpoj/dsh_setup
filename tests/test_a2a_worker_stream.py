"""Private stream contracts only. No credential, process or cluster is used."""
import ssl
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
from urllib.parse import urlsplit
from scripts.a2a_worker_stream import WorkerStream,static_kubeconfig,write_frame_once
from threading import Event


class WorkerStreamTests(TestCase):
    def test_cancel_during_reservation_or_memfd_seal_never_starts_attach_helper(self):
        from contextlib import ExitStack
        for phase in ('reservation','seal'):
            with self.subTest(phase=phase),ExitStack() as stack:
                stream=self.stream()
                stream.api.read_pod=Mock(return_value={})
                if phase=='reservation':self.before.side_effect=stream.abort_send.set
                control=SimpleNamespace(F_ADD_SEALS=1,F_SEAL_WRITE=2,F_SEAL_GROW=4,
                    F_SEAL_SHRINK=8,F_SEAL_SEAL=16,fcntl=Mock())
                if phase=='seal':control.fcntl.side_effect=lambda *_:stream.abort_send.set()
                stack.enter_context(patch('scripts.a2a_worker_stream.os.name','posix'))
                stack.enter_context(patch('scripts.a2a_worker_stream.os.memfd_create',return_value=123,create=True))
                stack.enter_context(patch('scripts.a2a_worker_stream.os.MFD_CLOEXEC',1,create=True))
                stack.enter_context(patch('scripts.a2a_worker_stream.os.MFD_ALLOW_SEALING',2,create=True))
                stack.enter_context(patch('scripts.a2a_worker_stream.fcntl',control))
                stack.enter_context(patch('scripts.a2a_worker_stream.verify_kubectl'))
                stack.enter_context(patch('scripts.a2a_worker_stream.verify_pod'))
                config=stack.enter_context(patch('scripts.a2a_worker_stream.static_kubeconfig',return_value={}))
                stack.enter_context(patch('scripts.a2a_worker_stream.os.fdopen'))
                stack.enter_context(patch('scripts.a2a_worker_stream.os.lseek'))
                close=stack.enter_context(patch('scripts.a2a_worker_stream.os.close'))
                popen=stack.enter_context(patch('scripts.a2a_worker_stream.subprocess.Popen'))
                with self.assertRaisesRegex(ValueError,'CANCELLED'):stream.start()
                popen.assert_not_called();self.before.assert_called_once()
                with self.assertRaisesRegex(ValueError,'ALREADY_CONSUMED'):stream.start()
                if phase=='reservation':config.assert_not_called()
                else:close.assert_called_once_with(123)

    def test_authorization_supplier_failure_never_echoes_its_error_content(self):
        api=self.api();api.authorization.side_effect=RuntimeError('synthetic-private-error-content')
        with self.assertRaisesRegex(RuntimeError,'AUTHORIZATION_UNAVAILABLE') as caught:
            static_kubeconfig(api)
        self.assertNotIn('synthetic-private-error-content',str(caught.exception))

    def test_observation_timeout_keeps_same_helper_and_does_not_restart_or_resend(self):
        stream=self.stream();stream.process=Mock();stream.selector=Mock()
        stream.selector.get_map.return_value={'synthetic-fd':object()}
        stream.selector.select.return_value=[]
        with self.assertRaises(TimeoutError):stream.receive_line(timeout=.001)
        self.assertFalse(stream.closed)
        stream.process.stdin.write.assert_not_called();stream.process.wait.assert_not_called()
        self.api_value.authorization.assert_not_called()
    def api(self):
        tls=Mock(check_hostname=True,verify_mode=ssl.CERT_REQUIRED)
        tls.get_ca_certs.return_value=[b'synthetic-public-ca-not-a-real-certificate']
        return SimpleNamespace(tls=tls,authorization=Mock(return_value='Bearer synthetic-not-a-real-token'),
            origin=urlsplit('https://kubernetes.invalid:6443'),namespace='dsh-a2a-qual')

    def stream(self):
        self.before=Mock();self.api_value=self.api()
        return WorkerStream(api=self.api_value,expected_pod={'metadata':{'name':'a2a-'+'a'*32}},
            pod_uid='22222222-2222-4222-8222-222222222222',before_attach=self.before)

    def test_constructor_has_no_authentication_or_execution_side_effect(self):
        stream=self.stream()
        self.api_value.authorization.assert_not_called();self.before.assert_not_called()
        self.assertIsNone(stream.process)

    def test_windows_is_refused_before_auth_reservation_or_child_start(self):
        stream=self.stream()
        with patch('scripts.a2a_worker_stream.os.name','nt'), \
             patch('scripts.a2a_worker_stream.subprocess.Popen') as popen:
            with self.assertRaisesRegex(ValueError,'LINUX_ONLY'):stream.start()
            popen.assert_not_called()
        self.api_value.authorization.assert_not_called();self.before.assert_not_called()
        with self.assertRaisesRegex(ValueError,'ALREADY_CONSUMED'):stream.start()

    def test_configuration_is_static_explicit_ca_and_no_exec_provider_or_password(self):
        api=self.api();config=static_kubeconfig(api)
        self.assertEqual(set(config['users'][0]['user']),{'token'})
        self.assertEqual(set(config['clusters'][0]['cluster']),{'server','certificate-authority-data'})
        self.assertEqual(config['contexts'][0]['context']['namespace'],'dsh-a2a-qual')
        api.authorization.assert_called_once()

    def test_missing_ca_or_disabled_verification_does_not_read_authentication(self):
        api=self.api();api.tls.get_ca_certs.return_value=[]
        with self.assertRaisesRegex(ValueError,'CA_BUNDLE'):static_kubeconfig(api)
        api.authorization.assert_not_called()
        api.tls.check_hostname=False
        with self.assertRaisesRegex(ValueError,'VERIFIED_STREAM_TLS'):static_kubeconfig(api)
        api.authorization.assert_not_called()

    def test_partial_delivery_fences_all_further_writes_instead_of_resending(self):
        stream=self.stream();stream.process=Mock();stream.process.poll.return_value=None
        with patch('scripts.a2a_worker_stream.write_frame_once',side_effect=OSError('synthetic partial delivery')) as write:
            with self.assertRaisesRegex(RuntimeError,'UNCERTAIN_NO_RESEND'):stream.send_line('synthetic')
            with self.assertRaisesRegex(ValueError,'NOT_OPEN'):stream.send_line('synthetic')
            write.assert_called_once()

    def test_byte_continuation_never_resends_a_frame_prefix(self):
        selector=Mock();selector.select.return_value=[('synthetic',None)]
        with patch('scripts.a2a_worker_stream.os.set_blocking') as blocking, \
             patch('scripts.a2a_worker_stream.os.write',side_effect=[2,2,3]) as write:
            write_frame_once(123,b'abcdef\n',Event(),selector_factory=lambda:selector)
            self.assertEqual([c.args[1] for c in write.call_args_list],[b'abcdef\n',b'cdef\n',b'ef\n'])
            blocking.assert_called_once_with(123,False)
        selector.close.assert_called_once()

    def test_backpressure_or_cancel_stops_without_writing_or_new_request(self):
        selector=Mock();selector.select.return_value=[]
        with patch('scripts.a2a_worker_stream.os.set_blocking'), \
             patch('scripts.a2a_worker_stream.os.write') as write:
            with self.assertRaises(TimeoutError):
                write_frame_once(123,b'one-frame\n',Event(),timeout=1,
                                 selector_factory=lambda:selector,clock=iter([0,.1,1.1]).__next__)
            abort=Event();abort.set()
            with self.assertRaisesRegex(RuntimeError,'CANCELLED'):
                write_frame_once(123,b'one-frame\n',abort,selector_factory=lambda:selector)
            write.assert_not_called()

    def test_oversized_complete_frame_is_not_accepted_just_because_newline_exists(self):
        stream=self.stream();stream.selector=Mock()
        stream.buffer=bytearray(b'x'*1048577+b'\n')
        with self.assertRaisesRegex(ValueError,'OUTPUT_LIMIT'):stream.receive_line(timeout=1)

    def test_local_close_does_not_produce_a_remote_stop_receipt(self):
        stream=self.stream();stream.process=Mock();stream.process.wait.return_value=0
        self.assertIsNone(stream.close());self.assertTrue(stream.closed)
        stream.process.stdin.close.assert_called_once()
        self.api_value.authorization.assert_not_called()
