import asyncio
import contextlib
import io
import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Rejected(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class App:
    def __init__(self, **kwargs):
        pass
    def get(self, path):
        return lambda f: f
    post = get


class Response:
    def __init__(self, content, status_code=200, **kwargs):
        self.content, self.status_code = content, status_code


class Stream:
    def __init__(self, iterator, **kwargs):
        self.body_iterator = iterator
        self.background = kwargs.get('background')


class Background:
    def __init__(self, fn):
        self.fn = fn
    async def __call__(self):
        await self.fn()


class FakeGuard:
    def __init__(self):
        self.active = False
    async def acquire(self, key, **kwargs):
        self.active = True
        return {'queued': False, **kwargs}
    async def warm(self, ids, cache_session_id=None):
        return {'steps': 2}
    def release(self, data):
        self.active = False


class FakeRequest:
    def __init__(self, data):
        self.data = data
    async def stream(self):
        yield json.dumps(self.data).encode()
    async def is_disconnected(self):
        return False


def load():
    root = Path(__file__).parents[1]/'scripts'
    spec = importlib.util.spec_from_file_location('context_envelope', root/'context_envelope.py')
    envelope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(envelope)
    api = types.ModuleType('fastapi')
    api.FastAPI, api.HTTPException, api.Request = App, Rejected, FakeRequest
    responses = types.ModuleType('fastapi.responses')
    responses.JSONResponse, responses.StreamingResponse = Response, Stream
    background = types.ModuleType('starlette.background')
    background.BackgroundTask = Background
    tools = types.ModuleType('long_context_callbacks')
    tools.CONTEXT, tools.OUTPUT, tools.RESERVE = 1048576, 8192, 256
    tools.TOKENIZER = 'http://internal:8000/v1/tokenize'
    tools.LongContextGuard = FakeGuard
    tools.count_request = lambda d, final: {'count': 200000, 'tokens': [1, 2]}
    http = types.ModuleType('httpx')
    http.Timeout = lambda *a, **kw: None
    http.TimeoutException = TimeoutError
    scope = {}
    with patch.dict(sys.modules, {'fastapi': api, 'fastapi.responses': responses,
        'starlette': types.ModuleType('starlette'), 'starlette.background': background,
        'httpx': http, 'long_context_callbacks': tools, 'context_envelope': envelope}):
        exec((root/'context_forwarder.py').read_text(encoding='utf8'), scope)
    return scope, http


class ForwarderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scope, self.http = load()
        self.sent, self.aborted = [], []
        sent = self.sent
        class Upstream:
            status_code = 200
            async def aiter_raw(self):
                yield b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n'
                yield b'data: [DONE]\n\n'
            async def aclose(self):
                pass
        class Client:
            def __init__(self, **kwargs):
                assert kwargs['trust_env'] is False
            def build_request(self, method, url, json):
                sent.append(json)
                return json
            async def send(self, request, stream):
                return Upstream()
            async def aclose(self):
                pass
        self.http.AsyncClient = Client
        async def abort(rid):
            self.aborted.append(rid)
        self.scope['abort'] = abort
        self.cache_opened, self.cache_closed = [], []
        async def open_reference(sid): self.cache_opened.append(sid)
        async def close_reference(sid): self.cache_closed.append(sid)
        self.scope['open_owned_cache_reference'] = open_reference
        self.scope['close_owned_cache_reference'] = close_reference

    def request(self, **kwargs):
        return FakeRequest({'model': 'deepseek-v4.1-flash', 'messages': [{'role': 'user', 'content': 'test'}],
            'stream': True, 'max_tokens': 65536, 'rid': 'do-not-abort-another-request',
            'tools': [{'type': 'function', 'function': {'name': 'example'}}], **kwargs})

    async def test_final_wire_normalization_stream_and_lease_lifetime(self):
        response = await self.scope['completion'](self.request())
        self.assertFalse(self.scope['guard'].active)
        content = b''.join([b async for b in response.body_iterator])
        self.assertEqual(self.sent[0]['max_tokens'], 8192)
        self.assertIs(self.sent[0]['tools'][0]['function']['strict'], False)
        self.assertNotEqual(self.sent[0]['rid'], 'do-not-abort-another-request')
        self.assertIn(b'OK', content)
        self.assertFalse(self.scope['guard'].active)
        self.assertEqual(self.aborted, [self.sent[0]['rid']])
        self.assertEqual(self.cache_opened,self.cache_closed)

    async def test_never_consumed_stream_background_still_releases(self):
        response = await self.scope['completion'](self.request())
        self.assertFalse(self.scope['guard'].active)
        await response.background()
        self.assertFalse(self.scope['guard'].active)

    async def test_counted_conditioning_is_forwarded_and_exact_ids_are_warmed(self):
        counted = []
        warmed = []
        exact_ids = [91, 42, 17, 63]
        def count(data, final):
            self.assertTrue(final)
            counted.append(copy.deepcopy(data))
            return {'count': 200000, 'tokens': exact_ids}
        async def warm(ids, cache_session_id=None):
            warmed.append(list(ids))
            return {'steps': 1}
        self.scope['count_request'] = count
        self.scope['guard'].warm = warm
        response = await self.scope['completion'](self.request(
            tool_choice='auto', reasoning_effort='low',
            chat_template_kwargs={'enable_thinking': False},
            tools=[{'type': 'function', 'function': {'name': 'example',
                'strict': None, 'parameters': {'type': 'object',
                    'properties': {'label': {'type': 'string'}}}}}]))
        content = b''.join([b async for b in response.body_iterator])
        self.assertIn(b'OK', content)
        for field in ('model', 'messages', 'tools', 'tool_choice',
                      'reasoning_effort', 'chat_template_kwargs', 'continue_final_message'):
            self.assertEqual(counted[0][field], self.sent[0][field], field)
        self.assertIs(counted[0]['tools'][0]['function']['strict'], False)
        self.assertIs(counted[0]['continue_final_message'], False)
        self.assertEqual(warmed, [exact_ids])
        await response.background()

    async def test_explicit_conditioning_is_not_replaced_by_defaults(self):
        response = await self.scope['completion'](self.request(
            continue_final_message=True,
            tools=[{'type': 'function', 'function': {'name': 'example', 'strict': True}}]))
        content = b''.join([b async for b in response.body_iterator])
        self.assertIn(b'OK', content)
        self.assertTrue(self.sent[0]['continue_final_message'])
        self.assertTrue(self.sent[0]['tools'][0]['function']['strict'])
        await response.background()

    async def test_cache_handoff_deadline_aborts_only_its_own_request(self):
        clock = types.SimpleNamespace(now=0.)
        self.scope['time'] = types.SimpleNamespace(monotonic=lambda: clock.now)
        original_client = self.http.AsyncClient
        class NoTextUpstream:
            status_code=200
            async def aiter_raw(self):
                clock.now=16.
                yield b': heartbeat\n\n'
            async def aclose(self): pass
        class DelayedClient(original_client):
            async def send(self, request, stream): return NoTextUpstream()
        self.http.AsyncClient = DelayedClient
        response = await self.scope['completion'](self.request())
        content = b''.join([b async for b in response.body_iterator])
        self.assertIn(b'context_cache_handoff_failed', content)
        self.assertEqual(self.aborted, [self.sent[0]['rid']])
        self.assertNotEqual(self.aborted[0], 'do-not-abort-another-request')
        self.assertFalse(self.scope['guard'].active)

    async def test_large_nonstreaming_client_uses_guarded_internal_stream(self):
        captured = []
        def assemble(packets, messages):
            captured.extend(packets)
            return {'choices': [{'message': {'content': 'OK'}}]}
        self.scope['assemble_response'] = assemble
        response = await self.scope['completion'](self.request(stream=False))
        self.assertEqual(response.content['choices'][0]['message']['content'], 'OK')
        self.assertTrue(self.sent[0]['stream'])
        self.assertTrue(self.sent[0]['stream_options']['include_usage'])
        self.assertTrue(captured)
        self.assertFalse(self.scope['guard'].active)

    async def test_raw_token_warming_does_not_substitute_for_image_embeddings(self):
        request = self.request(messages=[{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,synthetic'}}]}])
        with self.assertRaises(Rejected) as caught:
            await self.scope['completion'](request)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.sent, [])

    async def test_unavailable_budget_never_dispatches(self):
        def fail(*args):
            raise ValueError('unavailable')
        self.scope['count_request'] = fail
        with self.assertRaises(Rejected) as caught:
            await self.scope['completion'](self.request())
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.sent, [])

    async def test_cancelled_client_stops_warmup_and_releases(self):
        cancelled = []
        async def warm(ids, cache_session_id=None):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
        self.scope['guard'].warm = warm
        response = await self.scope['completion'](self.request())
        iterator = response.body_iterator
        pending = await anext(iterator)
        self.assertTrue(pending.startswith(b':'))
        await asyncio.sleep(.01)
        self.assertTrue(self.scope['guard'].active)
        await iterator.aclose()
        self.assertTrue(cancelled)
        self.assertFalse(self.scope['guard'].active)
        self.assertEqual(self.sent, [])

    async def test_cancelled_waiting_stream_cancels_admission_without_dispatch(self):
        cancelled = []
        async def waiting(key, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
        self.scope['guard'].acquire = waiting
        response = await self.scope['completion'](self.request())
        iterator = response.body_iterator
        self.assertTrue((await anext(iterator)).startswith(b':'))
        await asyncio.sleep(.01)
        await iterator.aclose()
        self.assertTrue(cancelled)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.scope['guard'].active)

    async def test_streaming_queue_full_reports_error_without_model_dispatch(self):
        async def full(key, **kwargs):
            raise Rejected(429, 'Long-context waiting queue full; retry later.')
        self.scope['guard'].acquire = full
        response = await self.scope['completion'](self.request())
        content = b''.join([b async for b in response.body_iterator])
        self.assertIn(b'context_admission_failed', content)
        self.assertIn(b'429', content)
        packet = json.loads(next(line[6:] for line in content.splitlines() if line.startswith(b'data: ')))
        self.assertEqual(packet['error']['code'], 429)
        self.assertEqual(packet['error']['type'], 'rate_limit_error')
        self.assertEqual(packet['error']['dsh_code'], 'context_admission_failed')
        self.assertEqual(self.sent, [])


    async def test_preparation_error_diagnostic_does_not_publish_exception_content(self):
        async def fail(_, cache_session_id=None): raise RuntimeError('private-content-marker')
        self.scope['guard'].warm = fail
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            response = await self.scope['completion'](self.request())
            content = b''.join([b async for b in response.body_iterator])
        self.assertIn(b'context_preparation_failed', content)
        self.assertNotIn(b'private-content-marker', content)
        self.assertNotIn('private-content-marker', captured.getvalue())
        events = [json.loads(l)for l in captured.getvalue().splitlines()]
        event = next(e for e in events if e.get('event')=='dsh_context_preparation_failed')
        self.assertEqual(event['errorType'], 'RuntimeError')
        self.assertFalse(self.scope['guard'].active)
        self.assertEqual(self.sent, [])

    async def test_ordinary_stream_holds_foreground_lane_until_closed(self):
        self.scope['count_request'] = lambda *args: {'count': 9000, 'tokens': [1]}
        response = await self.scope['completion'](self.request())
        lane = self.scope['interactive']
        self.assertEqual(lane.active, 1)
        waiting = asyncio.create_task(lane.wait_turn())
        await asyncio.sleep(.01)
        self.assertFalse(waiting.done())
        content = b''.join([b async for b in response.body_iterator])
        self.assertIn(b'OK', content)
        await waiting
        self.assertEqual(lane.active, 0)
        # Starlette background cleanup follows iterator cleanup; release once.
        await response.background()
        self.assertEqual(lane.active, 0)

    async def test_foreground_parallelism_and_bounded_background_progress(self):
        lane = self.scope['InteractiveLane'](maximum_pause=.02)
        lane.enter()
        lane.enter()
        lane.leave()
        self.assertEqual(lane.active, 1)
        await asyncio.wait_for(lane.wait_turn(), timeout=.2)
        self.assertEqual(lane.active, 1)
        lane.leave()
        self.assertTrue(lane.idle.is_set())

    async def test_dispatch_failure_releases_ordinary_lane(self):
        self.scope['count_request'] = lambda *args: {'count': 9000, 'tokens': [1]}
        class Failed:
            def __init__(self, **kwargs): pass
            def build_request(self, *args, **kwargs): return {}
            async def send(self, *args, **kwargs): raise RuntimeError('dispatch')
            async def aclose(self): pass
        self.http.AsyncClient = Failed
        with self.assertRaises(RuntimeError):
            await self.scope['completion'](self.request())
        self.assertEqual(self.scope['interactive'].active, 0)




class ForegroundRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_foreground_entry_invalidates_previous_idle_wakeup(self):
        scope, _ = load()
        lane = scope['InteractiveLane'](maximum_pause=.5)
        lane.enter()
        waiting = asyncio.create_task(lane.wait_turn())
        await asyncio.sleep(.01)
        lane.leave()
        lane.enter()
        await asyncio.sleep(.02)
        self.assertFalse(waiting.done())
        lane.leave()
        await asyncio.wait_for(waiting, .1)

    async def test_token_counting_is_protected_and_failure_releases_lane(self):
        scope, _ = load()
        called = []
        def count(*args):
            called.append(scope['interactive'].active)
            raise RuntimeError('tokenizer unavailable')
        scope['count_request'] = count
        request = FakeRequest({'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':'test'}]})
        with self.assertRaises(Rejected):
            await scope['completion'](request)
        self.assertEqual(called, [1])
        self.assertEqual(scope['interactive'].active, 0)


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.scope, _ = load()
        self.now = 10.0
        self.scope['_timing_clock'] = lambda: self.now
        self.trace = self.scope['RequestTiming']()

    def test_split_sse_and_gaps_record_numbers_without_content(self):
        wire = b'data: {"choices":[{"delta":{"content":"DO_NOT_LOG"}}]}\n\n'
        self.trace.packet(wire[:17])
        self.now += 1.25
        self.trace.packet(wire[17:])
        self.trace.packet(b'data: {"usage":{"completion_tokens":119}}\n\n')
        with patch('builtins.print') as emit:
            self.trace.finish()
            self.trace.finish()
        self.assertEqual(emit.call_count, 1)
        serialized = emit.call_args.args[0]
        self.assertNotIn('DO_NOT_LOG', serialized)
        result = json.loads(serialized)
        self.assertEqual(result['outputTokens'], 119)
        self.assertEqual(result['maxUpstreamGapMs'], 1250)
        self.assertEqual(result['upstreamGapsOver500ms'], 1)
        self.assertEqual(result['firstUpstreamDeltaMs'], 1250)

    def test_oversized_or_malformed_packets_do_not_break_delivery_observer(self):
        self.trace.packet(b'x'*(128*1024+1))
        self.assertEqual(self.trace.pending, b'')
        self.assertTrue(self.trace.record['timingParserOversize'])
        self.trace.packet(b'data: {invalid}\n')
        self.trace.packet(b'data: {"choices":null}\n')
        self.assertNotIn('firstUpstreamDeltaMs', self.trace.record)

    def test_failed_diagnostic_sink_does_not_raise_during_cleanup(self):
        with patch('builtins.print', side_effect=BrokenPipeError):
            self.trace.finish()
        self.assertTrue(self.trace.finished)

if __name__ == '__main__':
    unittest.main()
