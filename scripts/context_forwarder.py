"""Loopback-only final-wire 1M guard between LiteLLM and internal SGLang.

Bind to 127.0.0.1 in the authenticated LiteLLM pod. Never expose this listener
as a Service. Prompts/keys are not logged. Only canaries may enable capture.
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
guard = LongContextGuard()
BACKEND = TOKENIZER.removesuffix('/v1/tokenize')


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
    normalize_conditioning(data)
    if os.environ.get('DSH_CAPTURE_SYNTHETIC_ENVELOPE') == '1':
        Path('/tmp/dsh-synthetic-envelope.json').write_text(json.dumps(data))
    try:
        tokenized = await asyncio.to_thread(count_request, data, True)
    except Exception:
        raise HTTPException(503, 'Final-wire token budgeting unavailable; not dispatched.')
    available = CONTEXT-RESERVE-tokenized['count']
    if available < 1:
        raise HTTPException(400, 'Input exceeds 1M total-token budget; compact or reduce it.')
    limits = [data[k] for k in ['max_tokens', 'max_completion_tokens'] if k in data]
    if any(type(n) is not int or n < 1 for n in limits):
        raise HTTPException(400, 'Invalid output budget.')
    data.pop('max_completion_tokens', None)
    data['max_tokens'] = min([OUTPUT, available]+limits)
    long = tokenized['count']+data['max_tokens'] > 131072
    non_text = any(isinstance(m.get('content'), list) and any(
        isinstance(part, dict) and part.get('type') != 'text' for part in m['content'])
        for m in data['messages'] if isinstance(m, dict))
    if long and non_text:
        raise HTTPException(400, 'Above 128K, this warming route supports text and tools; reduce multimodal input.')
    incoming_stream = bool(data.get('stream'))
    if long and not incoming_stream and any(data.get(k) for k in
        ['return_token_ids', 'return_prompt_token_ids', 'return_meta_info', 'return_hidden_states']):
        raise HTTPException(400, 'Large nonstreaming requests do not support raw backend debug metadata.')
    lease = {'metadata': {}}
    rid = 'dsh-final-'+uuid.uuid4().hex
    data['rid'] = rid
    client = None
    upstream = None
    handed_off = False
    async def cleanup():
        try:
            if upstream is not None:
                await upstream.aclose()
            if client is not None:
                await client.aclose()
            await abort(rid)
        finally:
            guard.release(lease)
    try:
        if long:
            key = uuid.uuid4().hex
            lease['metadata']['dsh_long_lease'] = key
            async def prepare():
                await guard.acquire(key)
                summary = await guard.warm(tokenized['tokens'])
                print(json.dumps({'event': 'dsh_final_wire_warmed', **summary}), flush=True)
            try:
                await watch_client(request, prepare())
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(503, 'Long-context cache preparation stopped; retry later.')
        client = httpx.AsyncClient(timeout=httpx.Timeout(3600, connect=10), trust_env=False)
        wire_data = dict(data)
        if long and not incoming_stream:
            wire_data['stream'] = True
            wire_data['stream_options'] = {**(data.get('stream_options') or {}), 'include_usage': True}
        upstream = await client.send(client.build_request('POST', BACKEND+'/v1/chat/completions', json=wire_data), stream=True)
        if upstream.status_code != 200 or (not long and not incoming_stream):
            body = await upstream.aread()
            return JSONResponse(json.loads(body), status_code=upstream.status_code)

        async def stream():
            iterator = upstream.aiter_raw().__aiter__()
            first = not long
            deadline = time.monotonic()+15
            buffer = b''
            try:
                while True:
                    remaining = deadline-time.monotonic() if not first else 3600
                    if remaining <= 0:
                        raise TimeoutError('Cache handoff did not produce output')
                    try:
                        chunk = await asyncio.wait_for(anext(iterator), timeout=remaining)
                    except StopAsyncIteration:
                        break
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
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'},
                                 background=BackgroundTask(cleanup))
    finally:
        if not handed_off:
            await asyncio.shield(cleanup())
