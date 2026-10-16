"""Run inside the model pod to test prefix reuse using synthetic input only.

Intermediate one-token generations are discarded; no tools are executed.
This is a cache feasibility test, not a 1M or application acceptance test.
"""
import json
import time
import urllib.request
import uuid


def post(path, body):
    request = urllib.request.Request('http://127.0.0.1:8000'+path,
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=120) as response:
        value = json.load(response)
    return value, round(time.monotonic()-start, 4)


def main():
    prompt = 'Synthetic nonce '+uuid.uuid4().hex+'\n'+' red blue green yellow'*6144
    prompt += '\nReply exactly CACHE_WARM_OK.'
    request = {'model': 'deepseek-v4.1-flash', 'messages': [{'role': 'user', 'content': prompt}],
               'chat_template_kwargs': {'enable_thinking': False}}
    tokenized, _ = post('/v1/tokenize', request)
    ids = tokenized['tokens']
    rows = []
    for length in [8192, 16384, len(ids)]:
        response, elapsed = post('/generate', {'input_ids': ids[:length],
            'sampling_params': {'max_new_tokens': 1, 'temperature': 0}})
        meta = response['meta_info']
        rows.append({'inputTokens': length, 'seconds': elapsed,
            'cachedTokens': meta.get('cached_tokens'),
            'promptTokens': meta.get('prompt_tokens'), 'outputTokens': meta.get('completion_tokens')})
    response, elapsed = post('/v1/chat/completions', {**request, 'max_tokens': 32, 'temperature': 0})
    exact = response['choices'][0]['message']['content'] == 'CACHE_WARM_OK'
    reuse = all(r.get('cachedTokens', 0) >= rows[i-1]['inputTokens']-512 for i, r in enumerate(rows) if i)
    print(json.dumps({'prefixStages': rows, 'chatSeconds': elapsed,
        'chatUsage': response.get('usage'), 'chatExact': exact,
        'reusedPriorPrefixes': reuse, 'status': 'passed' if exact and reuse else 'failed'}))
    if not (exact and reuse):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
