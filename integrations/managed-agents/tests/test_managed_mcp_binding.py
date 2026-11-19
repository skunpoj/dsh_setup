import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parent.parent
loader = SourceFileLoader('managed_launcher', str(ROOT/'container/deepagents-managed.py'))
spec = importlib.util.spec_from_loader(loader.name, loader)
launcher = importlib.util.module_from_spec(spec)
loader.exec_module(launcher)

class ManagedMCP(unittest.TestCase):
    def test_exact_pins_and_internal_injection(self):
        expected_paths = [ROOT/'config/managed-mcp.json', ROOT/'container/dsh-mcp-broker-stdio.py']
        for (_, digest), path in zip(launcher._MANAGED_MCP_PINS, expected_paths, strict=True):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o644, st_uid=0, st_size=1)), patch.object(Path, 'read_bytes', side_effect=[p.read_bytes() for p in expected_paths]):
            self.assertEqual(launcher.managed_mcp_arguments(['-n','fixture']), ['--mcp-config','/opt/dsh/config/managed-mcp.json','-n','fixture'])
        with self.assertRaises(ValueError):
            launcher.arguments(['--mcp-config','/workspace/mcp.json'])

    def test_reject_untrusted_or_mismatched_bytes(self):
        for mode, owner in [(stat.S_IFLNK|0o777,0),(stat.S_IFREG|0o666,0),(stat.S_IFREG|0o644,10001),(stat.S_IFREG|0o644,0)]:
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=mode, st_uid=owner, st_size=1)), patch.object(Path, 'read_bytes', return_value=b'wrong'):
                with self.assertRaises(ValueError):
                    launcher.managed_mcp_arguments([])
        self.assertEqual(launcher.managed_mcp_arguments(['--version']), ['--version'])

    def test_stdio_inventory_no_model(self):
        expected = json.loads((ROOT/'config/managed-mcp.json').read_text())['mcpServers']['pc140032646']['allowedTools']
        request = json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'})+'\n'
        execution = subprocess.run([sys.executable,'-I','-B',str(ROOT/'container/dsh-mcp-broker-stdio.py')], input=request, text=True, capture_output=True, check=True, timeout=10)
        response = json.loads(execution.stdout)
        self.assertEqual(sorted(t['name'] for t in response['result']['tools']), sorted(expected))

if __name__ == '__main__':
    unittest.main(verbosity=2)
