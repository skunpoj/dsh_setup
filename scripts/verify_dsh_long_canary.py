"""Observe the actual DSH RPC/agent route with disposable synthetic history."""
import argparse
import json
import hashlib
from pathlib import Path
import subprocess
import threading
from datetime import datetime, timezone

from stress_live_inference import snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-target', type=int, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--pod', choices=['dsh-1m-canary', 'dsh-1m-image-canary', 'dsh-1m-managed-canary'], default='dsh-1m-canary')
    args = ap.parse_args()
    if args.output.exists():
        raise ValueError('Refuse to overwrite prior evidence')
    record = {'startUTC': datetime.now(timezone.utc).isoformat(),
              'target': args.input_target, 'before': snapshot(), 'samples': [], 'status': 'running'}
    if record['before']['metrics']['sglang:num_running_reqs'] or record['before']['metrics']['sglang:num_queue_reqs']:
        raise RuntimeError('Service busy; defer test')
    def save():
        args.output.write_text(json.dumps(record, indent=2), encoding='utf8')
    stop = threading.Event()
    def monitor():
        while not stop.wait(10):
            try:
                record['samples'].append(snapshot())
            except Exception as e:
                record['samples'].append({'error': type(e).__name__})
            save()
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        source = "import sys;sys.argv=['probe','--input-target',"+repr(str(args.input_target))+",'--deadline','3000']\n"
        source += Path(__file__).with_name('probe_dsh_1m_agent.py').read_text(encoding='utf8')
        record['executedProbeSHA256'] = hashlib.sha256(source.encode()).hexdigest()
        save()
        response = subprocess.run(['kubectl', '-n', 'llm', 'exec', '-i', args.pod, '--', 'python3', '-'],
            input=source, text=True, encoding='utf8', capture_output=True, timeout=3060)
        record['result'] = json.loads(response.stdout)
        record['exitCode'] = response.returncode
        record['status'] = 'passed' if response.returncode == 0 and record['result']['expectedTextPresent'] else 'failed'
    except Exception as e:
        record['status'] = 'failed'
        record['error'] = str(e)[:300]
    finally:
        stop.set()
        thread.join(timeout=40)
        try:
            record['after'] = snapshot()
            record['modelUnchanged'] = record['before']['pods'] == record['after']['pods']
            if not record['modelUnchanged']:
                record['status'] = 'failed'
        except Exception as e:
            record['finalCheckError'] = type(e).__name__
            record['status'] = 'failed'
        record['finishUTC'] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({'status': record['status'], 'elapsed': record.get('result', {}).get('elapsedSeconds'),
                     'usage': record.get('result', {}).get('lastUsage'), 'error': record.get('error')}), flush=True)
    if record['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
