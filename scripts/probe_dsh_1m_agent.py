"""Run inside the disposable DSH canary; no real histories or credentials output.

Uses the same authenticated HTTP RPCs as the web client and validates persisted
assistant events. Output contains synthetic results and usage, not large input.
"""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import time
import uuid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-target', type=int, default=0)
    ap.add_argument('--deadline', type=int, default=3000)
    args = ap.parse_args()
    host = 'dsh.aiportal.bot.or.th'
    token = Path('/runtime-tokens/secure').read_text()
    conn = http.client.HTTPConnection('127.0.0.1', 3080, timeout=40)
    conn.request('GET', '/?token='+token, headers={'Host': host})
    response = conn.getresponse()
    cookie = '; '.join(v.split(';')[0] for k, v in response.getheaders() if k.lower() == 'set-cookie')
    response.read()
    conn.close()
    if not cookie:
        raise RuntimeError('Canary launch-token exchange failed')

    def rpc(method, fields):
        body = {'type': 'client-request', 'rpcId': str(uuid.uuid4()),
                'method': method, 'payload': {'args': fields}}
        conn = http.client.HTTPConnection('127.0.0.1', 3080, timeout=60)
        conn.request('POST', '/api/'+method, json.dumps(body), headers={
            'Host': host, 'Origin': 'http://'+host,
            'Content-Type': 'application/json', 'Cookie': cookie})
        response = conn.getresponse()
        value = json.loads(response.read())
        conn.close()
        if not value.get('result', {}).get('ok'):
            raise RuntimeError('Canary RPC failed: '+json.dumps(value.get('result', {}).get('error'))[:500])
        return value['result']['value']

    created = rpc('session/create', {'request': {'cwd': '/workspace'}})
    session = created['sessionId']
    rpc('session/rename', {'request': {'sessionId': session, 'title': 'Synthetic 1M acceptance'}})
    expected = 'DSH_LONG_CONTEXT_OK'
    prompt = ('Synthetic acceptance nonce '+uuid.uuid4().hex+'\n'
        + ' red blue green yellow'*(args.input_target//4)
        + '\nReply exactly '+expected+'. Do not use tools.')
    result = {'sessionId': session, 'inputTarget': args.input_target,
              'inputSha256': hashlib.sha256(prompt.encode()).hexdigest(),
              'inputBytes': len(prompt.encode()), 'expected': expected}
    start = time.monotonic()
    rpc('session/prompt', {'request': {'sessionId': session, 'requestId': str(uuid.uuid4()),
        'content': [{'type': 'text', 'text': prompt}], 'mode': 'queue'}})
    last_seq = -1
    while time.monotonic()-start < args.deadline:
        projection = rpc('session/projections', {'request': {'sessionId': session}})
        if projection and projection['asOfSeq'] != last_seq:
            last_seq = projection['asOfSeq']
            page = rpc('session/page', {'request': {'address': {'kind': 'session', 'sessionId': session},
                'throughSeq': last_seq, 'maxMessages': 10}})
            events = [r['event'] for r in page['records']]
            selected = [e for e in events if e['type'].startswith(('assistant/', 'llm/', 'turn/end', 'step/end'))]
            # Preserve actual synthetic response/error events, never system/user input.
            result['events'] = selected
            result['projection'] = {k: projection['values'].get(k) for k in [
                'contextPressure', 'sessionStats', 'tokenUsage', 'modelSelection']}
            result['elapsedSeconds'] = round(time.monotonic()-start, 4)
            Path('/tmp/dsh-1m-agent-result.json').write_text(json.dumps(result))
            if any(e['type'] == 'turn/end' for e in events):
                result['finished'] = True
                result['expectedTextPresent'] = expected in json.dumps(selected)
                print(json.dumps(result))
                return
        time.sleep(2)
    result['finished'] = False
    result['elapsedSeconds'] = round(time.monotonic()-start, 4)
    print(json.dumps(result))
    raise SystemExit(1)


if __name__ == '__main__':
    main()
