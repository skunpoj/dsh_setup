import asyncio
import contextlib
import io
import json
import os
import sys
import types
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch


class Rejected(Exception):
    def __init__(self, status_code, detail, **kwargs):
        self.status_code = status_code
        super().__init__(detail)


def load_guard(lease_directory):
    lease_directory = Path(lease_directory).as_posix()
    logger = types.ModuleType('litellm.integrations.custom_logger')
    logger.CustomLogger = object
    api = types.ModuleType('fastapi')
    api.HTTPException = Rejected
    modules = {'fastapi': api, 'litellm': types.ModuleType('litellm'),
               'litellm.integrations': types.ModuleType('litellm.integrations'),
               'litellm.integrations.custom_logger': logger}
    if os.name == 'nt':
        modules['fcntl'] = types.SimpleNamespace()
    os.environ.setdefault('DSH_TOKENIZER_URL', 'http://inference.invalid/v1/tokenize')
    scope = {}
    with patch.dict(sys.modules, modules):
        exec((Path(__file__).parents[1]/'runtime/long_context_callbacks.py').read_text(encoding='utf-8').replace('/tmp/dsh-long-admission', lease_directory), scope)
    return scope


class LongContextGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        lease = tempfile.TemporaryDirectory(prefix='dsh-test-admission-')
        self.addCleanup(lease.cleanup)
        self.scope = load_guard(lease.name)
        self.guard = self.scope['LongContextGuard']()
        self.count = 1000
        self.scope['count_request'] = lambda _: {'count': self.count, 'tokens': []}
        async def warmed(_):
            return {'steps': 0}
        self.guard.warm = warmed

    async def request(self, **fields):
        data = {'model': 'deepseek-v4.1-flash', 'messages': [{'role': 'user', 'content': 'test'}], **fields}
        return await self.guard.async_pre_call_hook(None, None, data, 'acompletion')

    async def test_alias_normalizes_and_honors_the_smaller_limit(self):
        data = await self.request(max_tokens=200, max_completion_tokens=30)
        self.assertEqual(data['max_tokens'], 30)
        self.assertNotIn('max_completion_tokens', data)

    async def test_overflow_and_counter_failure_refuse_dispatch(self):
        self.count = 1048320
        with self.assertRaises(Rejected):
            await self.request()
        def fail(_):
            raise ValueError('unavailable')
        self.scope['count_request'] = fail
        with self.assertRaises(Rejected) as caught:
            await self.request()
        self.assertEqual(caught.exception.status_code, 503)

    async def test_unrecognized_responses_shape_is_rejected(self):
        with self.assertRaises(Rejected):
            await self.request(input='unrecognized')

    async def test_unrelated_model_retains_the_existing_guard(self):
        calls = []
        class Legacy:
            async def async_pre_call_hook(self, user, cache, data, call_type):
                calls.append(data['model'])
                return {**data, 'max_tokens': 8192}
        legacy = types.ModuleType('custom_callbacks')
        legacy.proxy_handler_instance = Legacy()
        with patch.dict(sys.modules, {'custom_callbacks': legacy}):
            result = await self.request(model='unrelated-model', max_tokens=65536)
        self.assertEqual(calls, ['unrelated-model'])
        self.assertEqual(result['max_tokens'], 8192)

    async def test_warming_yields_between_bounded_prefix_extensions(self):
        guard = self.scope['LongContextGuard']()
        self.scope['WARM_STEP'] = 1024
        self.scope['CACHE_PROBE_SECONDS'] = 0
        lengths = []
        def warm(ids):
            previous = lengths[-1] if lengths else 0
            lengths.append(len(ids))
            return {'cached_tokens': previous}
        self.scope['warm_prefix'] = warm
        result = await guard.warm([0]*2500)
        self.assertEqual(lengths, [1024, 2048, 2500])
        self.assertEqual(result['steps'], 3)

    async def test_cache_loss_stops_warming_without_monolithic_fallback(self):
        guard = self.scope['LongContextGuard']()
        self.scope['WARM_STEP'] = 1024
        self.scope['CACHE_PROBE_SECONDS'] = 0
        lengths = []
        def warm(ids):
            lengths.append(len(ids))
            return {'cached_tokens': 0}
        self.scope['warm_prefix'] = warm
        with self.assertRaisesRegex(RuntimeError, 'evicted'):
            await guard.warm([0]*8000)
        self.assertEqual(lengths, [1024, 2048])

    async def test_step_deadline_and_failure_diagnostic_do_not_log_input(self):
        self.assertEqual(self.scope['warm_prefix'].__defaults__, (30,))
        self.assertEqual(self.scope['CACHE_PROBE_SECONDS'], 2)
        self.scope['CACHE_PROBE_SECONDS'] = 0
        guard = self.scope['LongContextGuard']()
        def fail(_): raise self.scope['CacheProbeMiss']('private-content-marker')
        self.scope['warm_prefix'] = fail
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), self.assertRaises(self.scope['CacheProbeMiss']):
            await guard.warm([1234567]*2048)
        event = json.loads(captured.getvalue())
        self.assertEqual(event, {'event':'dsh_warm_step_failed','previousTokens':0,
            'targetTokens':2048,'steps':0,'errorType':'CacheProbeMiss'})
        self.assertNotIn('private-content-marker', captured.getvalue())
        self.assertNotIn('1234567', captured.getvalue())

    async def test_cache_loss_diagnostic_contains_only_numeric_progress(self):
        self.scope['CACHE_PROBE_SECONDS'] = 0
        self.scope['warm_prefix'] = lambda _: {'cached_tokens':0}
        guard = self.scope['LongContextGuard']()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), self.assertRaisesRegex(RuntimeError, 'evicted'):
            await guard.warm([1234567]*4096)
        self.assertEqual(json.loads(captured.getvalue()), {'event':'dsh_prefix_cache_lost',
            'previousTokens':2048,'targetTokens':4096,'cachedTokens':0,'steps':1})
        self.assertNotIn('1234567', captured.getvalue())

    async def test_hot_prefix_uses_one_bounded_probe_instead_of_rewarming(self):
        guard = self.scope['LongContextGuard']()
        calls = []
        def warm(ids, timeout):
            calls.append((len(ids), timeout))
            return {'cached_tokens': len(ids), 'prompt_tokens': len(ids)}
        self.scope['warm_prefix'] = warm
        result = await guard.warm([0]*2500)
        self.assertEqual(calls, [(2500, 2)])
        self.assertEqual(result['mode'], 'bounded-cache-probe')

    @unittest.skipIf(os.name == 'nt', 'POSIX process-shared lease')
    async def test_warmup_failure_releases_admission(self):
        self.count = 200000
        async def fail(_):
            raise RuntimeError('cache loss')
        self.guard.warm = fail
        with self.assertRaises(RuntimeError):
            await self.request()
        self.assertEqual(self.guard.leases, {})

    @unittest.skipIf(os.name == 'nt', 'POSIX process-shared lease')
    async def test_stream_lifetime_and_failure_release_the_long_lease(self):
        self.count = 200000
        data = await self.request(stream=True)
        key = data['metadata']['dsh_long_lease']
        self.assertIn(key, self.guard.leases)
        async def response():
            yield 'first'
            raise RuntimeError('stream failed')
        stream = self.guard.async_post_call_streaming_iterator_hook(None, response(), data)
        self.assertEqual(await anext(stream), 'first')
        with self.assertRaises(RuntimeError):
            await anext(stream)
        self.assertNotIn(key, self.guard.leases)
        again = await self.request()
        await self.guard.async_post_call_failure_hook(again, RuntimeError(), None)
        self.assertEqual(self.guard.leases, {})

    @unittest.skipIf(os.name == 'nt', 'POSIX process-shared lease')
    async def test_short_requests_are_not_blocked_by_long_admission(self):
        self.count = 200000
        long = await self.request(stream=True)
        self.count = 10
        short = await asyncio.wait_for(self.request(), .5)
        self.assertNotIn('dsh_long_lease', short['metadata'])
        self.guard.release(long)


    async def test_warm_steps_honor_foreground_gate_and_record_wait(self):
        guard = self.scope['LongContextGuard']()
        self.scope['WARM_STEP'] = 1024
        self.scope['CACHE_PROBE_SECONDS'] = 0
        calls = []
        async def wait_turn():
            calls.append('foreground')
            return .25
        def warm(ids):
            calls.append(len(ids))
            return {'cached_tokens': max(0, len(ids) - 1024)}
        guard.before_warm_step = wait_turn
        self.scope['warm_prefix'] = warm
        result = await guard.warm([0]*2048)
        self.assertEqual(calls, ['foreground', 1024, 'foreground', 2048])
        self.assertEqual(result['foregroundYieldSeconds'], .5)

    @unittest.skipIf(os.name == 'nt', 'POSIX process-shared lease')
    async def test_bounded_queue_waits_once_and_excess_is_rejected_immediately(self):
        await self.guard.acquire('active')
        waiting = asyncio.create_task(self.guard.acquire('waiting', wait_seconds=1500))
        await asyncio.sleep(.02)
        self.assertEqual(self.guard.waiters, ['waiting'])
        with self.assertRaises(Rejected) as caught:
            await self.guard.acquire('excess', wait_seconds=1500)
        self.assertEqual(caught.exception.status_code, 429)
        self.guard.release({'metadata': {'dsh_long_lease': 'active'}})
        result = await asyncio.wait_for(waiting, 1)
        self.assertEqual(result, {'queued': True, 'waitBudgetSeconds': 1500})
        self.guard.release({'metadata': {'dsh_long_lease': 'waiting'}})
        self.assertEqual(self.guard.waiters, [])

    @unittest.skipIf(os.name == 'nt', 'POSIX process-shared lease')
    async def test_waiter_cancellation_preserves_active_owner_and_frees_queue(self):
        await self.guard.acquire('active')
        waiting = asyncio.create_task(self.guard.acquire('cancelled', wait_seconds=1500))
        await asyncio.sleep(.02)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(self.guard.waiters, [])
        self.assertEqual(list(self.guard.leases), ['active'])
        self.guard.release({'metadata': {'dsh_long_lease': 'active'}})
        await asyncio.wait_for(self.guard.acquire('next'), 1)
        self.guard.release({'metadata': {'dsh_long_lease': 'next'}})

    @unittest.skipIf(os.name == 'nt', 'POSIX process-shared lease')
    async def test_queue_timeout_removes_waiter_without_unlocking_active_request(self):
        await self.guard.acquire('active')
        with self.assertRaises(Rejected):
            await self.guard.acquire('expired', wait_seconds=.01)
        self.assertEqual(self.guard.waiters, [])
        self.assertEqual(list(self.guard.leases), ['active'])
        self.guard.release({'metadata': {'dsh_long_lease': 'active'}})

    @unittest.skipIf(os.name == 'nt', 'POSIX process-shared lease')
    async def test_fifo_waiters_cannot_be_overtaken(self):
        await self.guard.acquire('active')
        first = asyncio.create_task(self.guard.acquire('first', max_waiters=2))
        await asyncio.sleep(.02)
        second = asyncio.create_task(self.guard.acquire('second', max_waiters=2))
        await asyncio.sleep(.02)
        self.guard.release({'metadata': {'dsh_long_lease': 'active'}})
        await asyncio.wait_for(first, 1)
        self.assertFalse(second.done())
        self.guard.release({'metadata': {'dsh_long_lease': 'first'}})
        await asyncio.wait_for(second, 1)
        self.guard.release({'metadata': {'dsh_long_lease': 'second'}})


if __name__ == '__main__':
    unittest.main()
