import asyncio
from contextlib import asynccontextmanager
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
model_module = ModuleType('dsh_agent_model')
model_module.DSHManagedChat = lambda: 'fake-model'
with patch.dict(sys.modules, {'dsh_agent_model': model_module}):
    spec = importlib.util.spec_from_file_location('sdk', ROOT/'container/dsh_deepagents_sdk.py')
    sdk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sdk)

class ManagedSdk(unittest.IsolatedAsyncioTestCase):
    async def test_create_in_running_loop_and_lazy_dispatch(self):
        calls = []
        deepagents = ModuleType('deepagents')
        deepagents.create_deep_agent = lambda **args: args
        backends = ModuleType('deepagents.backends')
        backends.FilesystemBackend = lambda **args: args
        langchain = ModuleType('langchain_core.tools')
        langchain.StructuredTool = SimpleNamespace(from_function=lambda **args: args)
        langchain.ToolException = type('ToolException', (Exception,), {})
        class Session:
            async def call_tool(self, name, *, arguments):
                calls.append((name, arguments))
                return SimpleNamespace(isError=False, content=[SimpleNamespace(model_dump=lambda **kw: {'type':'text','text':'42'})])
        @asynccontextmanager
        async def connect(root, server):
            calls.append((root, server))
            yield Session()
        modules = {'deepagents':deepagents,'deepagents.backends':backends,'langchain_core.tools':langchain}
        with patch.dict(sys.modules, modules), patch.object(sdk, '_checked_project', return_value=Path('/workspace/fixture')), patch.object(sdk, '_managed_server', return_value={'fixture':True}), patch.object(sdk, '_managed_session', connect):
            agent = sdk.create_dsh_agent('fixture', checkpointer='private')
            self.assertEqual(calls, [])
            self.assertEqual(agent['interrupt_on'], {'write_file':True,'edit_file':True,'execute':True})
            self.assertEqual({t['name'] for t in agent['tools']}, {'pc140032646_run_python','pc140032646_download_file','pc140032646_verify_base64'})
            result = await agent['tools'][0]['coroutine']('print(6*7)')
            self.assertEqual(result[0]['text'], '42')
            self.assertEqual(calls[1:], [('run_python', {'code':'print(6*7)'})])

    async def test_inventory_is_list_only_and_rejects_extra_tool(self):
        names = list(sdk._NAMES)
        class Session:
            async def list_tools(self):
                return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in names])
        @asynccontextmanager
        async def connect(root, server):
            yield Session()
        with patch.object(sdk, '_checked_project', return_value=Path('/workspace/fixture')), patch.object(sdk, '_managed_server', return_value={}), patch.object(sdk, '_managed_session', connect):
            self.assertEqual(await sdk.list_dsh_mcp_tools('fixture'), sorted(names))
            names.append('unapproved')
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                await sdk.list_dsh_mcp_tools('fixture')

if __name__ == '__main__':
    unittest.main(verbosity=2)
