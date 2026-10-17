"""Run a frozen repository review through a disposable actual DSH agent."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import time
import uuid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompt', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--deadline', type=int, default=3300)
    ap.add_argument('--session-id', help='Continue only the retained disposable review session')
    a = ap.parse_args()
    if not str(a.prompt).startswith('/tmp/realistic-review/'):
        raise ValueError('Disposable test input required')
    text = a.prompt.read_text()
    host = 'dsh.aiportal.bot.or.th'
    conn = http.client.HTTPConnection('127.0.0.1', 3080, timeout=40)
    conn.request('GET', '/?token='+Path('/runtime-tokens/secure').read_text(), headers={'Host': host})
    reply = conn.getresponse()
    cookie = '; '.join(v.split(';')[0] for k, v in reply.getheaders() if k.lower() == 'set-cookie')
    reply.read(); conn.close()
    if not cookie:
        raise RuntimeError('Disposable login failed')

    def rpc(method, fields):
        c = http.client.HTTPConnection('127.0.0.1', 3080, timeout=90)
        c.request('POST', '/api/'+method, json.dumps({'type': 'client-request',
            'rpcId': str(uuid.uuid4()), 'method': method, 'payload': {'args': fields}}),
            headers={'Host': host, 'Origin': 'http://'+host, 'Content-Type': 'application/json', 'Cookie': cookie})
        r = c.getresponse(); value = json.loads(r.read()); c.close()
        if not value.get('result', {}).get('ok'):
            raise RuntimeError('DSH review RPC failed: '+method)
        return value['result']['value']

    session = a.session_id or rpc('session/create', {'request': {'cwd': '/workspace'}})['sessionId']
    if not a.session_id:
        rpc('session/rename', {'request': {'sessionId': session, 'title': 'Repository accuracy acceptance - disposable'}})
    baseline_projection = rpc('session/projections', {'request': {'sessionId': session}})
    baseline = baseline_projection['asOfSeq']
    record = {'startUTC': datetime.now(timezone.utc).isoformat(), 'sessionId': session,
        'promptSHA256': hashlib.sha256(text.encode()).hexdigest(), 'promptBytes': len(text.encode()),
        'status': 'running', 'scope': 'Actual DSH agent, frozen repository sources, isolated ephemeral state'}
    record['continuedSession'] = bool(a.session_id)
    record['baselineSessionStats'] = baseline_projection['values'].get('sessionStats', {})
    start = time.monotonic()

    def save():
        temporary = a.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2))
        temporary.replace(a.output)

    save()
    rpc('session/prompt', {'request': {'sessionId': session, 'requestId': str(uuid.uuid4()),
        'content': [{'type': 'text', 'text': text}], 'mode': 'queue'}})
    last = -1
    while time.monotonic()-start < a.deadline:
        projection = rpc('session/projections', {'request': {'sessionId': session}})
        if projection['asOfSeq'] != last:
            last = projection['asOfSeq']
            page = rpc('session/page', {'request': {'address': {'kind': 'session', 'sessionId': session},
                'throughSeq': last, 'maxMessages': 30}})
            events = [r['event'] for r in page['records'] if r['event']['seq'] > baseline]
            selected = [e for e in events if e['type'].startswith(('assistant/', 'llm/', 'tool/', 'turn/end'))]
            record.update(events=selected, elapsedSeconds=round(time.monotonic()-start, 4),
                projection={k: projection['values'].get(k) for k in ['contextPressure', 'sessionStats', 'tokenUsage']})
            messages = [e['data'] for e in selected if e['type'] == 'assistant/message'
                and e['data'].get('message', {}).get('role') == 'assistant']
            if messages:
                record['assistantText'] = ''.join(b.get('text', '') for b in messages[-1]['message']['content'] if b.get('type') == 'text')
                record['lastUsage'] = messages[-1].get('usage')
            if any(e['type'] == 'turn/end' for e in events):
                user_texts = [''.join(b.get('text', '') for b in e['data'].get('message', e['data']).get('content', []) if b.get('type') == 'text')
                    for e in events if e['type'] == 'user/message']
                record['persistedPromptMatches'] = text in user_texts
                record['status'] = 'completed' if messages else 'failed'
                record['retryEvents'] = sum(e['type'] == 'llm/retry' for e in selected)
                save(); print(json.dumps({'status': record['status'], 'usage': record.get('lastUsage'), 'seconds': record['elapsedSeconds']}))
                return
            save()
        time.sleep(3)
    record['status'] = 'deadline'; record['elapsedSeconds'] = time.monotonic()-start; save()
    raise SystemExit('Review deadline reached')


if __name__ == '__main__':
    main()
