import json
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from scripts.openshell_native_rpc import NativeOpenShellRPC


def message(**values):
    return SimpleNamespace(**values,execution_timeout=SimpleNamespace(seconds=0,nanos=0))


class NativeRPCTests(unittest.TestCase):
    def setUp(self):
        self.stub=Mock()
        pb=SimpleNamespace(CreateSandboxRequest=message,GetSandboxRequest=message,ExecSandboxRequest=message)
        dm=SimpleNamespace(WorkspaceSelector=message)
        self.rpc=NativeOpenShellRPC(self.stub,pb,dm,workspace='isolated-test',clock=lambda:100)
        self.binding='a'*32;self.operation='b'*32
        self.metadata=SimpleNamespace(id='native1',name=self.rpc.name(self.binding),workspace='isolated-test',labels={'dsh.example.com/binding':self.binding,'dsh.example.com/allocation':self.operation})
        self.stub.CreateSandbox.return_value=SimpleNamespace(sandbox=SimpleNamespace(metadata=self.metadata))
        self.stub.GetSandbox.return_value=self.stub.CreateSandbox.return_value

    def test_create_transmits_durable_id_and_only_admitted_spec(self):
        spec=object()
        self.rpc.create(self.binding,self.operation,admitted_spec=spec,expires_at=220)
        req=self.stub.CreateSandbox.call_args.args[0]
        self.assertEqual(req.request_id,'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')
        self.assertIs(req.spec,spec)
        self.assertEqual(req.workspace_scope.workspace,'isolated-test')
        self.assertEqual(self.stub.CreateSandbox.call_count,1)

    def test_lookup_is_read_only_and_uses_binding_name(self):
        self.rpc.lookup(self.binding,self.operation)
        self.assertEqual(self.stub.GetSandbox.call_args.args[0].name,self.rpc.name(self.binding))
        self.stub.CreateSandbox.assert_not_called()

    def test_exec_sends_prompt_on_stdin_not_shell_or_environment(self):
        envelope={'bindingId':self.binding,'operationId':self.operation,'expiresAt':220,'prompt':'private prompt'}
        self.rpc.execute(self.binding,self.operation,envelope)
        req=self.stub.ExecSandbox.call_args.args[0]
        self.assertEqual(req.command,['/usr/local/bin/dsh-openshell-worker'])
        self.assertEqual(json.loads(req.stdin),envelope)
        self.assertTrue(req.no_login_shell)
        self.assertEqual(req.request_id,'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')
        self.assertEqual(req.execution_timeout.seconds,120)
        self.assertEqual(self.stub.ExecSandbox.call_count,1)

    def test_uncertain_create_never_retries(self):
        self.stub.CreateSandbox.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):
            self.rpc.create(self.binding,self.operation,admitted_spec=object(),expires_at=220)
        self.assertEqual(self.stub.CreateSandbox.call_count,1)

    def test_expired_foreign_and_zero_operations_refused_before_rpc(self):
        with self.assertRaises(ValueError):self.rpc.create(self.binding,self.operation,admitted_spec=object(),expires_at=100)
        with self.assertRaises(ValueError):self.rpc.create(self.binding,'0'*32,admitted_spec=object(),expires_at=220)
        with self.assertRaises(ValueError):self.rpc.execute(self.binding,self.operation,{'bindingId':'c'*32,'operationId':self.operation,'expiresAt':220})
        self.stub.CreateSandbox.assert_not_called();self.stub.ExecSandbox.assert_not_called()

    def test_unsafe_name_only_stop_is_never_sent(self):
        with self.assertRaisesRegex(ValueError,'EXACT_SUPERVISOR_STOP_REQUIRED'):self.rpc.stop(self.binding)
        self.stub.StopSandbox.assert_not_called()

    def test_pinned_gateway_name_limits_and_full_binding_label(self):
        self.assertEqual(len(self.rpc.name(self.binding)),19)
        self.rpc.create(self.binding,self.operation,admitted_spec=object(),expires_at=220)
        req=self.stub.CreateSandbox.call_args.args[0]
        self.assertEqual(req.labels['dsh.example.com/binding'],self.binding)
        self.assertEqual(req.name,self.rpc.name(self.binding))
        with self.assertRaisesRegex(ValueError,'INVALID_NATIVE_WORKSPACE'):
            NativeOpenShellRPC(self.stub,None,None,workspace='x'*20)

    def test_short_name_collision_with_foreign_full_binding_is_refused(self):
        self.metadata.labels['dsh.example.com/binding']='c'*32
        with self.assertRaisesRegex(ValueError,'NATIVE_ALLOCATION_IDENTITY_MISMATCH'):
            self.rpc.lookup(self.binding,self.operation)
        self.stub.CreateSandbox.assert_not_called()

    def test_wrong_create_workspace_cannot_be_accepted_or_retried(self):
        self.metadata.workspace='foreign'
        with self.assertRaisesRegex(ValueError,'NATIVE_ALLOCATION_IDENTITY_MISMATCH'):
            self.rpc.create(self.binding,self.operation,admitted_spec=object(),expires_at=220)
        self.assertEqual(self.stub.CreateSandbox.call_count,1)


if __name__=='__main__':unittest.main()
