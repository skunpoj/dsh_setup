"""Loopback-only final-wire 1M guard between LiteLLM and internal SGLang.

Bind to 127.0.0.1 in the authenticated LiteLLM pod. Never expose this listener
as a Service. Prompts and keys are not logged or captured.
"""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from long_context_callbacks import CONTEXT, OUTPUT, RESERVE, TOKENIZER, LongContextGuard, count_request
from context_envelope import normalize_conditioning

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_timing_clock = time.monotonic


class RequestTiming:
    """Content-free measurements at the final forwarding boundary.

    Upstream packet timing is not GPU kernel time or browser delivery time.
    The bounded parser observes only numeric usage and the presence of a delta;
    packet contents are never included in emitted records.
    """
    def __init__(self):
        self.started = _timing_clock()
        self.record = {}
        self.pending = b''
        self.last_packet = None
        self.finished = False

    def elapsed(self):
        return round((_timing_clock()-self.started)*1000, 3)

    def packet(self, chunk):
        now = _timing_clock()
        self.record.setdefault('firstUpstreamByteMs', self.elapsed())
        self.record['upstreamChunks'] = self.record.get('upstreamChunks', 0)+1
        self.record['upstreamBytes'] = self.record.get('upstreamBytes', 0)+len(chunk)
        if self.last_packet is not None:
            gap = (now-self.last_packet)*1000
            self.record['maxUpstreamGapMs'] = round(max(gap, self.record.get('maxUpstreamGapMs', 0)), 3)
            if gap > 500:
                self.record['upstreamGapsOver500ms'] = self.record.get('upstreamGapsOver500ms', 0)+1
        self.last_packet = now
        self.pending += chunk
        if len(self.pending) > 128*1024:
            self.pending = b''
            self.record['timingParserOversize'] = True
            return
        while b'\n' in self.pending:
            line, self.pending = self.pending.split(b'\n', 1)
            if not line.startswith(b'data: ') or line[6:].strip() == b'[DONE]':
                continue
            try:
                item = json.loads(line[6:])
                if not isinstance(item, dict):
                    continue
                choices = item.get('choices')
                if isinstance(choices, list) and any(isinstance(c, dict) and isinstance(c.get('delta'), dict) and any(
                    c['delta'].get(k) for k in ['content', 'reasoning_content', 'tool_calls'])
                    for c in choices):
                    self.record.setdefault('firstUpstreamDeltaMs', self.elapsed())
                usage = item.get('usage')
                if isinstance(usage, dict) and type(usage.get('completion_tokens')) is int:
                    self.record['outputTokens'] = usage['completion_tokens']
            except (ValueError, TypeError, AttributeError):
                pass

    def finish(self):
        if self.finished:
            return
        self.finished = True
        self.pending = b''
        try:
            print(json.dumps({'event': 'dsh_request_timing', **self.record,
                              'elapsedMs': self.elapsed()}), flush=True)
        except (OSError, ValueError):
            pass  # Diagnostic logging must never block stream/lease cleanup.

class InteractiveLane:
    """Let ordinary streams drain between bounded long-prefill steps.

    Long work gets a step after at most 8s of uninterrupted foreground load;
    this is cooperative scheduling, not GPU preemption or a latency SLA.
    """
    def __init__(self, maximum_pause=8):
        self.active = 0
        self.idle = asyncio.Event()
        self.idle.set()
        self.maximum_pause = maximum_pause

    def enter(self):
        self.active += 1
        self.idle.clear()

    def leave(self):
        if self.active < 1:
            raise RuntimeError('Interactive lane released without ownership')
        self.active -= 1
        if not self.active:
            self.idle.set()

    async def wait_turn(self):
        start = time.monotonic()
        deadline = start + self.maximum_pause
        while self.active:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self.idle.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            # An idle notification may be stale: another foreground request
            # can enter before this waiter resumes. Recheck the counter.
        return time.monotonic() - start


interactive = InteractiveLane()
guard = LongContextGuard()
guard.before_warm_step = interactive.wait_turn
BACKEND = TOKENIZER.removesuffix('/v1/tokenize')



async def open_owned_cache_reference(session_id):
    # Backend TTL reaps orphaned metadata even if the proxy process disappears.
    async with httpx.AsyncClient(timeout=5, trust_env=False) as open_client:
        response = await open_client.post(BACKEND+'/open_session', json={
            'session_id':session_id, 'capacity_of_str_len':CONTEXT,
            'streaming':False, 'timeout':3900})
        response.raise_for_status()
        if response.json() != session_id:
            raise RuntimeError('Backend did not confirm the owned cache-reference identity')

async def close_owned_cache_reference(session_id):
    # Engine cache references are metadata, not a security boundary or hard pin.
    # IDs are generated server-side and never copied from client input.
    last_error = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as close_client:
                response = await close_client.post(BACKEND+'/close_session', json={'session_id': session_id})
                response.raise_for_status()
            print(json.dumps({'event':'dsh_cache_reference_closed','sessionId':session_id}), flush=True)
            return
        except Exception as error:
            last_error = error
            if attempt == 0:
                await asyncio.sleep(.2)
    print(json.dumps({'event':'dsh_cache_reference_close_failed','sessionId':session_id,'errorType':type(last_error).__name__}), flush=True)
    raise RuntimeError('Owned cache reference close failed; keep long admission held') from last_error


def cache_reference_remaining(deadline):
    if deadline is None:
        return None
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Owned cache preparation/response exceeded its 3300-second budget')
    return remaining

async def within_cache_deadline(factory, deadline):
    remaining = cache_reference_remaining(deadline)
    if remaining is None:
        return await factory()
    return await asyncio.wait_for(factory(), timeout=remaining)

def assemble_response(chunks, messages):
    from litellm import ModelResponseStream, stream_chunk_builder
    result = stream_chunk_builder([ModelResponseStream(**c) for c in chunks], messages=messages)
    if result is None:
        raise HTTPException(503, 'No complete model response was received.')
    return result.model_dump(mode='json')


async def abort(rid):
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            await client.post(BACKEND+'/abort_request', json={'rid': rid})
    except Exception:
        pass


async def watch_client(request, coroutine):
    task = asyncio.create_task(coroutine)
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=.5)
            if await request.is_disconnected():
                raise HTTPException(499, 'Client disconnected.')
        return await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


@app.get('/health')
async def health():
    return {'context': CONTEXT, 'output': OUTPUT, 'finalWireGuard': True}


@app.get('/v1/models')
async def models():
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(BACKEND+'/v1/models')
        return JSONResponse(response.json(), status_code=response.status_code)


@app.post('/v1/chat/completions')
async def completion(request: Request):
    timing = RequestTiming()
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 64*1024*1024:
            raise HTTPException(413, 'Request body exceeds the supported envelope.')
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(400, 'Invalid JSON.')
    if not isinstance(data, dict) or not isinstance(data.get('messages'), list):
        raise HTTPException(400, 'Chat messages required.')
    if data.get('model') not in ['deepseek-v4.1-flash', 'deepseek-flash']:
        raise HTTPException(400, 'Model is outside this context policy.')
    for private_field in ('session_id', 'session_params', 'cache_salt'):
        data.pop(private_field, None)
    normalize_conditioning(data)
    tokenize_start = _timing_clock()
    interactive.enter()
    try:
        tokenized = await asyncio.to_thread(count_request, data, True)
    except Exception:
        raise HTTPException(503, 'Final-wire token budgeting unavailable; not dispatched.')
    finally:
        interactive.leave()
    timing.record['tokenizeMs'] = round((_timing_clock()-tokenize_start)*1000, 3)
    available = CONTEXT-RESERVE-tokenized['count']
    if available < 1:
        raise HTTPException(400, 'Input exceeds 1M total-token budget; compact or reduce it.')
    limits = [data[k] for k in ['max_tokens', 'max_completion_tokens'] if k in data]
    if any(type(n) is not int or n < 1 for n in limits):
        raise HTTPException(400, 'Invalid output budget.')
    data.pop('max_completion_tokens', None)
    data['max_tokens'] = min([OUTPUT, available]+limits)
    long = tokenized['count']+data['max_tokens'] > 32768
    non_text = any(isinstance(m.get('content'), list) and any(
        isinstance(part, dict) and part.get('type') != 'text' for part in m['content'])
        for m in data['messages'] if isinstance(m, dict))
    if tokenized['count']+data['max_tokens'] > 131072 and non_text:
        raise HTTPException(400, 'Above 128K, this warming route supports text and tools; reduce multimodal input.')
    # Preserve existing <=128K multimodal behavior; raw-token preparation is text-only.
    if non_text:
        long = False
    incoming_stream = bool(data.get('stream'))
    if long and not incoming_stream and any(data.get(k) for k in
        ['return_token_ids', 'return_prompt_token_ids', 'return_meta_info', 'return_hidden_states']):
        raise HTTPException(400, 'Large nonstreaming requests do not support raw backend debug metadata.')
    lease = {'metadata': {}}
    rid = 'dsh-final-'+uuid.uuid4().hex
    timing.record.update(requestId=rid, inputTokens=tokenized['count'], outputBudget=data['max_tokens'], long=long)
    data['rid'] = rid
    client = None
    upstream = None
    handed_off = False
    cleaned = False
    ordinary_owned = False
    cache_session_id = None
    cache_reference_deadline = None
    cleanup_task = None
    async def perform_cleanup():
        nonlocal cleaned, ordinary_owned
        if cleaned:
            return
        cleaned = True
        timing.finish()
        if ordinary_owned:
            interactive.leave()
            ordinary_owned = False
        try:
            if upstream is not None:
                await upstream.aclose()
            if client is not None:
                await client.aclose()
            await abort(rid)
        finally:
            if cache_session_id is not None:
                await close_owned_cache_reference(cache_session_id)
            guard.release(lease)
    async def cleanup():
        nonlocal cleanup_task
        if cleanup_task is None:
            cleanup_task = asyncio.create_task(perform_cleanup())
        interrupted = False
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                interrupted = True
            except Exception:
                break
        cleanup_task.result()
        if interrupted:
            raise asyncio.CancelledError()
    try:
        if not long:
            interactive.enter()
            ordinary_owned = True
        if long:
            key = uuid.uuid4().hex
            lease['metadata']['dsh_long_lease'] = key
            async def prepare():
                nonlocal cache_session_id, cache_reference_deadline
                admission_start = _timing_clock()
                timing.record['admissionState'] = 'waiting'
                print(json.dumps({'event': 'dsh_long_admission_started', 'requestId': rid,
                                  'inputTokens': tokenized['count'], 'waitBudgetSeconds': 1500}), flush=True)
                admission = await guard.acquire(key, wait_seconds=1500, max_waiters=1)
                timing.record['admissionState'] = 'acquired'
                timing.record['admissionQueue'] = admission
                timing.record['admissionMs'] = round((_timing_clock()-admission_start)*1000, 3)
                cache_session_id = 'dsh-cache-'+key
                await open_owned_cache_reference(cache_session_id)
                cache_reference_deadline = time.monotonic()+3300
                data['session_id'] = cache_session_id
                print(json.dumps({'event':'dsh_cache_reference_started','sessionId':cache_session_id}), flush=True)
                warm_start = _timing_clock()
                summary = await within_cache_deadline(lambda: guard.warm(tokenized['tokens'], cache_session_id=cache_session_id), cache_reference_deadline)
                timing.record['warmMs'] = round((_timing_clock()-warm_start)*1000, 3)
                print(json.dumps({'event': 'dsh_final_wire_warmed', **summary}), flush=True)
            if not incoming_stream:
                await watch_client(request, prepare())

        async def dispatch():
            nonlocal client, upstream
            client = httpx.AsyncClient(timeout=httpx.Timeout(3600, connect=10), trust_env=False)
            wire_data = dict(data)
            if long and not incoming_stream:
                wire_data['stream'] = True
                wire_data['stream_options'] = {**(data.get('stream_options') or {}), 'include_usage': True}
            dispatch_start = _timing_clock()
            upstream = await within_cache_deadline(lambda: client.send(client.build_request('POST', BACKEND+'/v1/chat/completions', json=wire_data), stream=True), cache_reference_deadline)
            timing.record['upstreamHeadersMs'] = round((_timing_clock()-dispatch_start)*1000, 3)
            timing.record['upstreamStatus'] = upstream.status_code

        if not (long and incoming_stream):
            await dispatch()
            if upstream.status_code != 200 or (not long and not incoming_stream):
                body = await upstream.aread()
                timing.record['bodyConsumed'] = True
                return JSONResponse(json.loads(body), status_code=upstream.status_code, headers={'X-DSH-Request-ID': rid})

        async def stream():
            iterator = upstream.aiter_raw().__aiter__()
            first = not long
            deadline = time.monotonic()+15
            buffer = b''
            try:
                while True:
                    remaining = deadline-time.monotonic() if not first else 3600
                    owned_remaining = cache_reference_remaining(cache_reference_deadline)
                    if owned_remaining is not None:
                        remaining = min(remaining, owned_remaining)
                    if remaining <= 0:
                        raise TimeoutError('Cache handoff did not produce output')
                    try:
                        chunk = await asyncio.wait_for(anext(iterator), timeout=remaining)
                    except StopAsyncIteration:
                        timing.record['bodyConsumed'] = True
                        break
                    timing.packet(chunk)
                    if not first:
                        buffer += chunk
                        while b'\n' in buffer:
                            line, buffer = buffer.split(b'\n', 1)
                            if line.startswith(b'data: ') and line[6:].strip() != b'[DONE]':
                                try:
                                    item = json.loads(line[6:])
                                    first = first or any(any(c.get('delta', {}).get(k) for k in
                                        ['content', 'reasoning_content', 'tool_calls']) for c in item.get('choices', []))
                                except Exception:
                                    pass
                    yield chunk
            except (TimeoutError, httpx.TimeoutException):
                yield b'data: '+json.dumps({'error': {'code': 'context_cache_handoff_failed',
                    'message': 'Long-context cache handoff failed; request stopped without full-prefill fallback.'}}).encode()+b'\n\n'
            finally:
                await asyncio.shield(cleanup())
        if long and incoming_stream:
            async def prepared_stream():
                # Start HTTP streaming before admission/preparation. Otherwise an
                # upstream proxy can remain blocked awaiting response headers
                # after the end user cancels, retaining the long-request lease.
                async def ready():
                    await prepare()
                    await dispatch()
                task = asyncio.create_task(ready())
                try:
                    yield b': dsh-long-request-pending\n\n'
                    while not task.done():
                        done, _ = await asyncio.wait({task}, timeout=5)
                        if not done:
                            yield b': dsh-long-request-pending\n\n'
                    await task
                    if upstream.status_code != 200:
                        yield b'data: '+json.dumps({'error': {'code': 'context_upstream_failed',
                            'message': 'Long-context upstream request failed.'}}).encode()+b'\n\n'
                        return
                    async for chunk in stream():
                        yield chunk
                except HTTPException as exc:
                    # LiteLLM's OpenAI-compatible stream parser reads numeric
                    # error.code; a diagnostic string here becomes HTTP 500.
                    yield b'data: '+json.dumps({'error': {'code': exc.status_code,
                        'type': 'rate_limit_error' if exc.status_code == 429 else 'api_error',
                        'dsh_code': 'context_admission_failed',
                        'status': exc.status_code, 'message': str(exc.detail)}}).encode()+b'\n\n'
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(json.dumps({'event': 'dsh_context_preparation_failed',
                        'requestId': rid, 'inputTokens': tokenized['count'],
                        'errorType': type(exc).__name__}), flush=True)
                    yield b'data: '+json.dumps({'error': {'code': 'context_preparation_failed',
                        'message': 'Long-context preparation stopped.'}}).encode()+b'\n\n'
                finally:
                    if not task.done():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                    await asyncio.shield(cleanup())
            handed_off = True
            return StreamingResponse(prepared_stream(), media_type='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'X-DSH-Request-ID': rid},
                background=BackgroundTask(cleanup))
        if not incoming_stream:
            async def collect():
                packets = []
                buffer = b''
                async for chunk in stream():
                    buffer += chunk
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if not line.startswith(b'data: ') or line[6:].strip() == b'[DONE]':
                            continue
                        packet = json.loads(line[6:])
                        if 'error' in packet:
                            raise HTTPException(503, 'Long-context response stopped before completion.')
                        packets.append(packet)
                return assemble_response(packets, data['messages'])
            return JSONResponse(await watch_client(request, collect()))
        handed_off = True
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-DSH-Request-ID': rid},
                                 background=BackgroundTask(cleanup))
    finally:
        if not handed_off:
            await asyncio.shield(cleanup())
