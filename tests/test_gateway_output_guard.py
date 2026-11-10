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

    def test_safeguards_field_is_refused_for_the_custom_openai_backed_model(self):
        with self.assertRaises(Rejected) as caught:
            self.call(safeguards=[{'type': 'synthetic-classifier'}])
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(str(caught.exception), 'unsupported-provider-safeguards')

    def test_safeguards_field_is_refused_for_the_sibling_deepseek_flash_alias(self):
        with self.assertRaises(Rejected) as caught:
            self.call(model='deepseek-flash', safeguards=[{'type': 'synthetic-classifier'}])
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(str(caught.exception), 'unsupported-provider-safeguards')

    def test_safeguards_refusal_does_not_apply_to_a_real_anthropic_backed_alias(self):
        # claude-sonnet-5 is a genuine Anthropic-backed alias and is delegated to
        # custom_callbacks.proxy_handler_instance (a different handler, line 16-18)
        # before this hook's own safeguards check; it must keep seeing 'safeguards'
        # untouched, since the real Anthropic backend supports it.
        delegated = types.ModuleType('custom_callbacks')
        seen = {}
        async def record(user_api_key_dict, cache, data, call_type):
            seen.update(data)
            return data
        delegated.proxy_handler_instance = types.SimpleNamespace(async_pre_call_hook=record)
        with patch.dict(sys.modules, {'custom_callbacks': delegated}):
            result = self.call(model='claude-sonnet-5', safeguards=[{'type': 'synthetic-classifier'}])
        self.assertIn('safeguards', seen)
        self.assertIn('safeguards', result)

    def test_request_without_safeguards_is_unaffected(self):
        result = self.call()
        self.assertNotIn('safeguards', result)
        self.assertEqual(result['messages'], [{'role': 'user', 'content': 'test'}])


if __name__ == '__main__':
    unittest.main()
