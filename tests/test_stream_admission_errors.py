"""Exercise the pinned-reader shim without network or model calls."""
import asyncio
import hashlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit


class APIError(Exception):
    def __init__(self, message='busy', *, request=None, body=None):
        super().__init__(message)
        self.request, self.body = request, body


class RateLimitError(APIError):
    def __init__(self, message, *, response, body):
        super().__init__(message, request=response.request, body=body)
        self.response = response


class AdmissionErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        async def original(stream):
            if stream.error:
                raise stream.error
            yield 'ordinary'
        class Stream:
            __stream__ = original
            def __init__(self, error=None):
                self.error = error
        self.Stream = Stream
        fake_openai = types.SimpleNamespace(APIError=APIError, RateLimitError=RateLimitError)
        fake_httpx = types.SimpleNamespace(Response=lambda status, **kw:
                                          types.SimpleNamespace(status_code=status, **kw))
        filename = Path(__file__).parents[1] / 'scripts/stream_admission_errors.py'
        spec = importlib.util.spec_from_file_location('admission_errors_test', filename)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'openai': fake_openai, 'httpx': fake_httpx,
                                     'openai._streaming': types.SimpleNamespace(AsyncStream=Stream)}):
            spec.loader.exec_module(self.module)
        self.module.READER_SHA256 = hashlib.sha256(b'pinned-reader').hexdigest()

    def install(self):
        with patch.object(self.module.inspect, 'getsource', return_value='pinned-reader'):
            self.module.install()

    def error(self, url='http://127.0.0.1:4001/v1/chat/completions', **changes):
        parsed = urlsplit(url)
        request = types.SimpleNamespace(url=types.SimpleNamespace(
            scheme=parsed.scheme, host=parsed.hostname, port=parsed.port, path=parsed.path))
        body = {'code': 429, 'type': 'rate_limit_error', 'dsh_code': 'context_admission_failed'}
        body.update(changes)
        return APIError(request=request, body=body)

    async def consume(self, error=None):
        return [x async for x in self.Stream(error).__stream__()]

    async def test_trusted_loopback_busy_preserves_429_and_retry_after(self):
        self.install()
        with self.assertRaises(RateLimitError) as caught:
            await self.consume(self.error())
        self.assertEqual(caught.exception.response.status_code, 429)
        self.assertEqual(caught.exception.response.headers, {'Retry-After': '30'})

    async def test_foreign_endpoints_and_paths_are_not_reclassified(self):
        self.install()
        for url in ['https://127.0.0.1:4001/v1/chat/completions',
                    'http://example.com:4001/v1/chat/completions',
                    'http://127.0.0.1:4002/v1/chat/completions',
                    'http://127.0.0.1:4001/other']:
            original = self.error(url)
            with self.subTest(url=url), self.assertRaises(APIError) as caught:
                await self.consume(original)
            self.assertIs(caught.exception, original)

    async def test_unrelated_errors_and_string_status_are_unchanged(self):
        self.install()
        for fields in [{'code': '429'}, {'code': 500}, {'type': 'other'}, {'dsh_code': 'other'}]:
            original = self.error(**fields)
            with self.subTest(fields=fields), self.assertRaises(APIError) as caught:
                await self.consume(original)
            self.assertIs(caught.exception, original)

    async def test_ordinary_stream_and_repeated_install_are_unchanged(self):
        self.install()
        installed = self.Stream.__stream__
        self.module.install()
        self.assertIs(self.Stream.__stream__, installed)
        self.assertEqual(await self.consume(), ['ordinary'])

    def test_changed_sdk_reader_fails_before_patching(self):
        original = self.Stream.__stream__
        with patch.object(self.module.inspect, 'getsource', return_value='changed-reader'):
            with self.assertRaises(RuntimeError):
                self.module.install()
        self.assertIs(self.Stream.__stream__, original)


if __name__ == '__main__':
    unittest.main()
