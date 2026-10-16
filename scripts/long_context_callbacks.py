"""Exact backend budgeting and one-at-a-time long-prefill admission.

Run in one LiteLLM replica. The process-shared flock remains held until the
stream closes, including cancellation/failure. Ordinary requests do not wait
on this lock. No prompt content or credentials are logged.
"""
import asyncio
import fcntl
import json
import os
import time
import urllib.request
import urllib.error
import uuid

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

CONTEXT = 1048576
OUTPUT = 8192
RESERVE = 256
LONG_THRESHOLD = 131072
MODELS = {'deepseek-v4.1-flash', 'deepseek-flash'}
TOKENIZER = os.environ.get('DSH_TOKENIZER_URL',
    'http://vllm-deepseek-v4-flash.llm.svc.cluster.local:8000/v1/tokenize')
WARM_STEP = 2048
CACHE_PROBE_SECONDS = 2


class CacheProbeMiss(TimeoutError):
    """The bounded cache probe was cold and its own request was aborted."""


def count_request(data, final_envelope=False):
    allowed = ('messages', 'tools', 'tool_choice', 'reasoning_effort',
               'continue_final_message', 'chat_template_kwargs')
    payload = dict(data) if final_envelope else {k: data[k] for k in allowed if k in data}
    if final_envelope:
        # Tokenization has no streaming transport. Preserve every conditioning
        # field from the final wire payload, excluding only SSE output controls.
        payload['stream'] = False
        payload.pop('stream_options', None)
    payload['model'] = 'deepseek-v4.1-flash'
    req = urllib.request.Request(TOKENIZER, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        # Debug only validation locations/types, never the rejected input.
        details = []
        try:
            body = json.load(error)
            if isinstance(body.get('detail'), list):
                details = [{'location': d.get('loc'), 'type': d.get('type')}
                           for d in body['detail'] if isinstance(d, dict)]
        except Exception:
            pass
        print(json.dumps({'event': 'dsh_tokenizer_rejected',
                          'status': error.code, 'validation': details}), flush=True)
        raise
    count = result.get('count')
    if type(count) is not int or count < 0 or result.get('max_model_len') != CONTEXT:
        raise ValueError('Unexpected backend tokenizer result')
    ids = result.get('tokens')
    if not isinstance(ids, list) or len(ids) != count or any(type(x) is not int for x in ids):
        raise ValueError('Exact tokenizer IDs unavailable')
    return result


def warm_prefix(ids, timeout=15):
    rid = 'dsh-warm-'+uuid.uuid4().hex
    base = TOKENIZER.removesuffix('/v1/tokenize')
    request = urllib.request.Request(TOKENIZER.removesuffix('/v1/tokenize')+'/generate',
        data=json.dumps({'input_ids': ids, 'rid': rid,
            'sampling_params': {'max_new_tokens': 1, 'temperature': 0}}).encode(),
        headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            result = json.load(response)
    except BaseException as error:
        aborted = False
        try:
            abort = urllib.request.Request(base+'/abort_request',
                data=json.dumps({'rid': rid}).encode(), headers={'Content-Type': 'application/json'})
            with opener.open(abort, timeout=5) as reply:
                aborted = reply.status == 200
        except Exception:
            pass
        if isinstance(error, TimeoutError):
            if aborted:
                raise CacheProbeMiss('Cold prefix probe cancelled') from error
            raise RuntimeError('Warm request cancellation not acknowledged; stop escalation') from error
        raise
    return result['meta_info']


class LongContextGuard(CustomLogger):
    def __init__(self):
        super().__init__()
        self.leases = {}

    async def warm(self, ids):
        """Finish small cached-prefill requests so cold DSH requests get turns.

        Discard the one-token warmup outputs; they never enter the conversation
        or execute tools. Cancellation stops the loop after at most one small
        outstanding step. Cache loss fails closed rather than silently retrying
        the whole prompt. Measured latency is not an absolute SLA.
        """
        previous = 0
        steps = 0
        start = time.monotonic()
        if CACHE_PROBE_SECONDS:
            try:
                meta = await asyncio.to_thread(warm_prefix, ids, CACHE_PROBE_SECONDS)
            except CacheProbeMiss:
                pass
            else:
                if meta.get('prompt_tokens') != len(ids):
                    raise RuntimeError('Unexpected cache-probe token usage')
                return {'steps': 1, 'tokens': len(ids), 'mode': 'bounded-cache-probe',
                    'cachedTokens': meta.get('cached_tokens'),
                    'seconds': round(time.monotonic()-start, 3),
                    'probeSeconds': CACHE_PROBE_SECONDS}
        for end in range(WARM_STEP, len(ids)+WARM_STEP, WARM_STEP):
            end = min(end, len(ids))
            meta = await asyncio.to_thread(warm_prefix, ids[:end])
            cached = meta.get('cached_tokens', 0)
            if previous and cached < previous-512:
                raise RuntimeError('Long prefix was evicted; defer and retry the request')
            previous = end
            steps += 1
            await asyncio.sleep(.05)
        return {'steps': steps, 'tokens': len(ids),
                'seconds': round(time.monotonic()-start, 3), 'stepTokens': WARM_STEP,
                'mode': 'chunked-prefix-warming', 'probeSeconds': CACHE_PROBE_SECONDS}

    async def acquire(self, key):
        os.makedirs('/tmp/dsh-long-admission', mode=0o700, exist_ok=True)
        fd = os.open('/tmp/dsh-long-admission/active.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            deadline = time.monotonic() + 300
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.leases[key] = fd
                    return
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise HTTPException(429, 'Long-context capacity busy; retry later.',
                            headers={'Retry-After': '30'})
                    await asyncio.sleep(.1)
        except BaseException:
            os.close(fd)
            raise

    def release(self, data):
        if not isinstance(data, dict):
            return
        key = (data.get('metadata') or {}).get('dsh_long_lease')
        fd = self.leases.pop(key, None)
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if not isinstance(data, dict):
            return data
        model = str(data.get('model', '')).removeprefix('openai/')
        if model not in MODELS:
            # Preserve the existing limits on unrelated production routes.
            from custom_callbacks import proxy_handler_instance as legacy
            return await legacy.async_pre_call_hook(user_api_key_dict, cache, data, call_type)
        if not isinstance(data.get('messages'), list) or not data['messages']:
            raise HTTPException(400, 'This route requires Chat Completions messages.')
        if 'input' in data or 'max_output_tokens' in data:
            raise HTTPException(400, 'Responses format is not supported on this route.')
        try:
            tokenized = await asyncio.to_thread(count_request, data)
            count = tokenized['count']
        except Exception:
            raise HTTPException(503, 'Backend token budgeting unavailable; request not dispatched.')
        available = CONTEXT - RESERVE - count
        if available < 1:
            raise HTTPException(400, 'Input exceeds 1M total budget; compact or reduce the input.')
        limits = [data[k] for k in ('max_tokens', 'max_completion_tokens') if k in data]
        if any(type(x) is not int or x < 1 for x in limits):
            raise HTTPException(400, 'Output token limits must be positive integers.')
        maximum = min(limits or [OUTPUT])
        data.pop('max_completion_tokens', None)
        data['max_tokens'] = min(maximum, OUTPUT, available)
        # Lease identity is generated server-side, never accepted from a client.
        metadata = dict(data.get('metadata') or {})
        metadata.pop('dsh_long_lease', None)
        data['metadata'] = metadata
        if count + data['max_tokens'] > LONG_THRESHOLD:
            key = uuid.uuid4().hex
            metadata['dsh_long_lease'] = key
            await self.acquire(key)
            try:
                metadata['dsh_prefix_warmup'] = await self.warm(tokenized['tokens'])
                print(json.dumps({'event': 'dsh_prefix_warmup_complete',
                                  **metadata['dsh_prefix_warmup']}), flush=True)
            except BaseException:
                self.release(data)
                raise
        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        if not data.get('stream'):
            self.release(data)
        return response

    async def async_post_call_failure_hook(self, request_data, original_exception,
                                          user_api_key_dict, traceback_str=None):
        self.release(request_data)

    async def async_post_call_streaming_iterator_hook(self, user_api_key_dict,
                                                     response, request_data):
        try:
            async for item in response:
                yield item
        finally:
            self.release(request_data)


proxy_handler_instance = LongContextGuard()
