from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from scripts.a2a_executor import PrivateA2AExecutor


class ExecutorTests(unittest.TestCase):
    def test_exact_service_dispatch_and_no_fallback(self):
        sdk=SimpleNamespace(subject='owner',qualified=True,run_task=Mock(return_value='sdk output'))
        cli=SimpleNamespace(subject='owner',qualified=True,run_task=Mock(return_value='cli output'))
        executor=PrivateA2AExecutor(sdk_service=sdk,cli_service=cli)
        child=SimpleNamespace(request=dict(runtime='sdk',backend='private'))
        self.assertEqual(executor(child),'sdk output')
        sdk.run_task.assert_called_once_with('owner',child);cli.run_task.assert_not_called()
        sdk.run_task.side_effect=TimeoutError('synthetic')
        with self.assertRaises(TimeoutError):executor(child)
        self.assertEqual(sdk.run_task.call_count,2);cli.run_task.assert_not_called()

    def test_foreign_subject_and_revoked_scope_cannot_dispatch(self):
        sdk=SimpleNamespace(subject='owner',qualified=True,run_task=Mock())
        cli=SimpleNamespace(subject='foreign',qualified=True,run_task=Mock())
        executor=PrivateA2AExecutor(sdk_service=sdk,cli_service=cli)
        child=SimpleNamespace(request=dict(runtime='sdk',backend='private'))
        with self.assertRaises(ValueError):executor(child)
        cli.subject='owner';cli.qualified=False
        with self.assertRaises(ValueError):executor(child)
        sdk.run_task.assert_not_called();cli.run_task.assert_not_called()
