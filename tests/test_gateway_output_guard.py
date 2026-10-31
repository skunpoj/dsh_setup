import asyncio
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Rejected(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


class OutputGuardTests(unittest.TestCase):
    def setUp(self):
        api = types.ModuleType('fastapi')
        api.HTTPException = Rejected
        logger = types.ModuleType('litellm.integrations.custom_logger')
        logger.CustomLogger = object
        stream_errors = types.ModuleType('stream_admission_errors')
        stream_errors.install = lambda: None
        scope = {}
        with patch.dict(sys.modules, {'fastapi': api, 'litellm': types.ModuleType('litellm'),
            'litellm.integrations': types.ModuleType('litellm.integrations'),
            'litellm.integrations.custom_logger': logger,
            'stream_admission_errors': stream_errors}):
            exec((Path(__file__).parents[1]/'scripts/gateway_output_guard.py').read_text(), scope)
        self.guard = scope['OutputGuard']()

    def call(self, **fields):
        data = {'model': 'deepseek-v4.1-flash', 'messages': [{'role': 'user', 'content': 'test'}], **fields}
        return asyncio.run(self.guard.async_pre_call_hook(None, None, data, 'acompletion'))

    def test_endpoint_override_cannot_bypass_the_final_wire_guard(self):
        for name in ['api_base', 'base_url', 'custom_llm_provider']:
            with self.assertRaises(Rejected) as caught:
                self.call(**{name: 'unapproved'})
            self.assertEqual(caught.exception.status_code, 400)

    def test_normal_request_aliases_have_one_bounded_output_limit(self):
        result = self.call(max_tokens=65536, max_completion_tokens=12000)
        self.assertEqual(result['max_tokens'], 8192)
        self.assertNotIn('max_completion_tokens', result)


if __name__ == '__main__':
    unittest.main()
