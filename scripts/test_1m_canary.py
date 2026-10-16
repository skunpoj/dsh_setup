"""Progressive synthetic current-scheduler test of the isolated 1M route."""
import argparse
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from stress_live_inference import REQUEST, kube, snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--targets', nargs='+', type=int, default=[256000, 512000, 1000000])
    args = ap.parse_args()
    if args.output.exists():
        raise ValueError('Refuse to overwrite prior evidence')
    ip = json.loads(kube('get', 'pod', 'litellm-1m-canary', '-o', 'json'))['status']['podIP']
    request = REQUEST.replace('http://litellm.llm.svc.cluster.local:4000', 'http://'+ip+':4000')
    request = request.replace('timeout=45', 'timeout=3000').replace('>60:', '>3000:')
    # Allow tokenization/prefill to begin before timing interactive probes.
    request = request.replace('time.sleep(.5)', 'time.sleep(10)')
    request = request.replace("'startMonotonic':start,", "'wallStartUnix':time.time()-elapsed,'startMonotonic':start,")
    result = {'startUTC': datetime.now(timezone.utc).isoformat(),
              'scope': 'Isolated LiteLLM candidate, current shared scheduler; not DSH agent acceptance',
              'stages': [], 'samples': [], 'status': 'running', 'before': snapshot()}
    def save():
        args.output.write_text(json.dumps(result, indent=2), encoding='utf8')
    stop = threading.Event()
    def monitor():
        while not stop.wait(5):
            try:
                result['samples'].append(snapshot())
            except Exception as e:
                result['samples'].append({'error': type(e).__name__})
            save()
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        for target in args.targets:
            state = snapshot()
            if state['pods'] != result['before']['pods']:
                raise RuntimeError('Model identity/restart changed')
            if state['metrics'].get('sglang:num_running_reqs', 1) or state['metrics'].get('sglang:num_queue_reqs', 1):
                raise RuntimeError('Shared service busy; defer escalation')
            plan = {'kind': 'mixed', 'inputTarget': target}
            source = 'PLAN = '+repr(json.dumps(plan))+'\n'+request
            stage = json.loads(kube('exec', '-i', 'dsh-1m-canary', '--', 'python3', '-', source=source, timeout=3060))
            result['stages'].append(stage)
            save()
            print(json.dumps({'target': target, 'allExact': stage['allExact'],
                'rows': [{'label': r['label'], 'inputTokens': r.get('usage', {}).get('prompt_tokens'),
                          'seconds': r['elapsedSeconds'], 'overlap': r.get('longStillRunningAfterReply'),
                          'error': r.get('errorType')} for r in stage['rows']]}), flush=True)
            if not stage['allExact']:
                raise RuntimeError('Incorrect output or failed inference; stop escalation')
            if any(r['elapsedSeconds'] > 5 or not r['longStillRunningAfterReply'] for r in stage['rows'][1:]):
                raise RuntimeError('Short-request responsiveness gate failed')
        result['status'] = 'passed'
    except Exception as e:
        result['status'] = 'stopped'
        result['reason'] = str(e)
    finally:
        stop.set()
        thread.join(timeout=40)
        try:
            result['after'] = snapshot()
        except Exception as e:
            result['finalCheckError'] = type(e).__name__
            result['status'] = 'stopped'
        result['finishUTC'] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({'status': result['status'], 'reason': result.get('reason')}), flush=True)
    if result['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
