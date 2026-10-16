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
from datetime import datetime, timezone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-target', type=int, default=0)
    ap.add_argument('--deadline', type=int, default=3000)
    ap.add_argument('--tool-test', action='store_true')
    ap.add_argument('--session-id')
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

    if args.session_id:
        session = args.session_id
        previous = rpc('session/projections', {'request': {'sessionId': session}})
        if previous['values'].get('title') != 'Synthetic 1M acceptance':
            raise RuntimeError('Refuse continuation of a non-test history')
    else:
        created = rpc('session/create', {'request': {'cwd': '/workspace'}})
        session = created['sessionId']
        rpc('session/rename', {'request': {'sessionId': session, 'title': 'Synthetic 1M acceptance'}})
    expected = 'DSH_LONG_CONTEXT_OK'
    nonce = uuid.uuid4().hex
    prompt = ('Synthetic acceptance nonce '+nonce+'\n'
        + ' a b c d'*(args.input_target//4)
        + '\nReply exactly '+expected+'. Do not use tools.')
    tool_file = Path('/workspace')/('dsh-context-proof-'+nonce+'.txt')
    marker = 'DSH_CONTEXT_TOOL_'+nonce
    if args.tool_test:
        expected = 'DSH_TOOL_CONTEXT_OK'
        prompt = ('Use the write tool to create '+str(tool_file)+' containing exactly '+marker+
            '. Use the read tool to read it back. Then reply exactly '+expected+'.')
    result = {'sessionId': session, 'inputTarget': args.input_target,
              'inputSha256': hashlib.sha256(prompt.encode()).hexdigest(),
              'inputBytes': len(prompt.encode()), 'expected': expected,
              'inputSpecification': {'nonce': nonce, 'filler': ' a b c d',
                  'repeats': args.input_target//4,
                  'suffix': '\nReply exactly '+expected+'. Do not use tools.'},
              'startUTC': datetime.now(timezone.utc).isoformat()}
    catalog = rpc('session/modelCatalog', {})
    result['catalogModels'] = [m for g in catalog['groups'] for m in g['models']
        if m['id'] in ['deepseek-v4.1-flash', 'deepseek-flash']]
    start = time.monotonic()
    baseline = rpc('session/projections', {'request': {'sessionId': session}})['asOfSeq']
    result['afterSeq'] = baseline
    rpc('session/prompt', {'request': {'sessionId': session, 'requestId': str(uuid.uuid4()),
        'content': [{'type': 'text', 'text': prompt}], 'mode': 'queue'}})
    last_seq = -1
    while time.monotonic()-start < args.deadline:
        projection = rpc('session/projections', {'request': {'sessionId': session}})
        if projection and projection['asOfSeq'] != last_seq:
            last_seq = projection['asOfSeq']
            page = rpc('session/page', {'request': {'address': {'kind': 'session', 'sessionId': session},
                'throughSeq': last_seq, 'maxMessages': 10}})
            events = [r['event'] for r in page['records'] if r['event']['seq'] > baseline]
            selected = [e for e in events if e['type'].startswith(('assistant/', 'llm/', 'tool/', 'turn/end', 'step/end'))]
            # Preserve actual synthetic response/error events, never system/user input.
            result['events'] = selected
            result['projection'] = {k: projection['values'].get(k) for k in [
                'contextPressure', 'sessionStats', 'tokenUsage', 'modelSelection']}
            result['elapsedSeconds'] = round(time.monotonic()-start, 4)
            Path('/tmp/dsh-1m-agent-probe-'+nonce+'.json').write_text(json.dumps(result))
            if any(e['type'] == 'turn/end' for e in events):
                result['finished'] = True
                messages = [e['data'] for e in selected if e['type'] == 'assistant/message'
                    and e['data'].get('message', {}).get('role') == 'assistant']
                text = ''.join(b.get('text', '') for b in messages[-1]['message']['content']
                    if b.get('type') == 'text') if messages else ''
                result['assistantText'] = text
                result['expectedTextPresent'] = text.strip() == expected
                user_texts = [''.join(b.get('text', '') for b in e['data'].get('message', e['data']).get('content', [])
                    if b.get('type') == 'text') for e in events if e['type'] == 'user/message']
                result['persistedPromptMatches'] = prompt in user_texts
                result['lastUsage'] = messages[-1].get('usage') if messages else None
                if args.tool_test:
                    content = tool_file.read_text() if tool_file.exists() else ''
                    result['actualToolFileMatches'] = content.rstrip('\n') == marker
                    result['toolFileSha256'] = hashlib.sha256(content.encode()).hexdigest()
                    if result['actualToolFileMatches']:
                        tool_file.unlink()
                        result['testFileRemoved'] = not tool_file.exists()
                    else:
                        result['expectedTextPresent'] = False
                print(json.dumps(result))
                if not result['expectedTextPresent']:
                    raise SystemExit(1)
                return
        time.sleep(2)
    result['finished'] = False
    result['elapsedSeconds'] = round(time.monotonic()-start, 4)
    print(json.dumps(result))
    raise SystemExit(1)


if __name__ == '__main__':
    main()
