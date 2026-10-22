"""Preserve the trusted loopback guard's 429 through OpenAI streaming.

OpenAI SDK 2.33 discards SSE error status and raises generic APIError. Keep
this compatibility shim limited to the pinned reader and our loopback route.
"""
import hashlib
import inspect

import httpx
from openai import APIError, RateLimitError
from openai._streaming import AsyncStream

READER_SHA256 = '7f3b4c5cc4e3672403b9e5631ac6d297d1412512f28a7360004628f6dadd725c'


def install(port=4001):
    original = AsyncStream.__stream__
    if getattr(original, '_dsh_admission_port', None) == port:
        return
    if hashlib.sha256(inspect.getsource(original).encode()).hexdigest() != READER_SHA256:
        raise RuntimeError('OpenAI streaming reader changed; qualify admission mapping before startup')

    async def guarded(self):
        try:
            async for item in original(self):
                yield item
        except APIError as exc:
            url = exc.request.url
            body = exc.body
            if (url.scheme == 'http' and url.host == '127.0.0.1' and url.port == port
                    and url.path == '/v1/chat/completions'
                    and isinstance(body, dict) and type(body.get('code')) is int
                    and body['code'] == 429 and body.get('type') == 'rate_limit_error'
                    and body.get('dsh_code') == 'context_admission_failed'):
                response = httpx.Response(429, request=exc.request, headers={'Retry-After': '30'})
                raise RateLimitError('Long-context capacity busy; retry later.',
                                     response=response, body=body) from exc
            raise

    guarded._dsh_admission_port = port
    AsyncStream.__stream__ = guarded
