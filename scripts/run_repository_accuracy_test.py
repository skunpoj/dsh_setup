"""Monitor one real DSH repository review with paired ordinary DSH requests.

No Production configuration writes. Only an explicitly named disposable runtime.
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from stress_live_inference import snapshot


def require_idle(state, admission_available):
    if (not admission_available or state['metrics'].get('sglang:num_running_reqs', 1)
            or state['metrics'].get('sglang:num_queue_reqs', 1)):
        raise RuntimeError('Model or long-admission slot busy; do not start review')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--directory', type=Path, required=True)
    ap.add_argument('--pod', required=True); a = ap.parse_args()
    if a.pod != 'dsh-realistic-1m-test-20261017': raise ValueError('Disposable runtime required')
    root = Path(__file__).resolve().parents[1]; out = a.directory

    def remote(code, timeout=60, stdin=None):
        p = subprocess.run(['kubectl', '--request-timeout=25s', '-n', 'llm', 'exec', '-i',
            a.pod, '--', 'python3', '-c', code], input=stdin, text=True,
            encoding='utf-8', capture_output=True, timeout=timeout)
        if p.returncode: raise RuntimeError(p.stderr[-500:])
        return p.stdout

    # Copy only prepared corpus and test helpers. No user volumes or credentials are read.
    for local, dest in [(out/'prompt.txt', '/tmp/realistic-review/prompt.txt'),
                       (root/'scripts/probe_dsh_document_review.py', '/tmp/realistic-review/probe.py'),
                       (root/'scripts/probe_dsh_1m_agent.py', '/tmp/realistic-review/short.py')]:
        remote("import sys;from pathlib import Path;p=Path("+repr(dest)+");p.parent.mkdir(exist_ok=True);p.write_text(sys.stdin.read(),encoding='utf-8')",
            timeout=120, stdin=local.read_text(encoding='utf-8'))
    before = snapshot()
    # Prefix warming deliberately yields between steps, so zero GPU running/queue
    # metrics alone do not establish that the long-admission slot is free.
    lease_code = """import os,fcntl,json
p='/tmp/dsh-long-admission/active.lock';available=True
if os.path.exists(p):
 f=open(p,'r+')
 try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
 except BlockingIOError:available=False
 finally:f.close()
print(json.dumps({'available':available}))
"""
    lease = subprocess.run(['kubectl', '-n', 'llm', 'exec', 'deploy/litellm', '-c',
        'context-forwarder', '--', 'python', '-c', lease_code], text=True, capture_output=True, timeout=35)
    if lease.returncode: raise RuntimeError('Admission availability check failed')
    require_idle(before, json.loads(lease.stdout)['available'])
    record = {'startUTC': datetime.now(timezone.utc).isoformat(), 'status': 'running',
        'pod': a.pod, 'before': before, 'samples': [], 'shortPairs': []}
    def save():
        p = out/'controller.tmp'; p.write_text(json.dumps(record, indent=2), encoding='utf-8')
        p.replace(out/'controller.json')
    save()
    pid = remote("import subprocess;f=open('/tmp/realistic-review/probe.log','w');p=subprocess.Popen(['python3','/tmp/realistic-review/probe.py','--prompt','/tmp/realistic-review/prompt.txt','--output','/tmp/realistic-review/long-result.json'],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True);print(p.pid)").strip()
    record['remoteProbePID'] = pid; save()
    def short():
        # Kubernetes exec encodes -c arguments in its request URI. Keep it short;
        # upload helper source on stdin instead of causing ingress HTTP 414.
        code = "import runpy,sys;sys.argv=['short','--deadline','90'];runpy.run_path('/tmp/realistic-review/short.py',run_name='__main__')"
        return json.loads(remote(code, timeout=110))
    start = time.monotonic(); next_short = 30; transient = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            while time.monotonic()-start < 3500:
                try:
                    value = json.loads(remote("from pathlib import Path;print(Path('/tmp/realistic-review/long-result.json').read_text())"))
                    (out/'long-result.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
                    state = snapshot(); transient = 0
                except Exception as error:
                    transient += 1
                    record.setdefault('monitorErrors', []).append({'seconds': time.monotonic()-start, 'message': str(error)[-350:]})
                    save()
                    if transient >= 3: raise
                    time.sleep(10); continue
                record['samples'].append(state); record['elapsedSeconds'] = time.monotonic()-start
                if state['pods'] != before['pods']: raise RuntimeError('Model identity/restart changed')
                if value.get('status') != 'running':
                    record['status'] = value.get('status'); record['longUsage'] = value.get('lastUsage')
                    record['finishUTC'] = datetime.now(timezone.utc).isoformat(); save()
                    print(json.dumps({'status': record['status'], 'usage': record['longUsage'], 'shortPairs': len(record['shortPairs'])}), flush=True)
                    return
                if time.monotonic()-start >= next_short:
                    pending = [pool.submit(short) for _ in range(2)]
                    results = [f.result() for f in pending]
                    after = json.loads(remote("from pathlib import Path;print(Path('/tmp/realistic-review/long-result.json').read_text())"))
                    record['shortPairs'].append({'longRunningAfter': after.get('status') == 'running', 'results': results})
                    save()
                    if not all(r.get('expectedTextPresent') and r.get('persistedPromptMatches') and r.get('elapsedSeconds', 999) < 60 for r in results):
                        raise RuntimeError('Short DSH responsiveness or correctness gate failed')
                    print(json.dumps({'seconds': round(time.monotonic()-start), 'shorts': [r['elapsedSeconds'] for r in results]}), flush=True)
                    next_short = time.monotonic()-start+120
                save(); time.sleep(10)
        raise RuntimeError('Controller deadline')
    except Exception as error:
        record['status'] = 'stopped'; record['reason'] = str(error)
        record['modelCancellationConfirmed'] = False
        record['cleanupScope'] = 'Disposable runtime deletion only; verify admission release independently.'
        save()
        # Stop only this disposable runtime, never restart the shared model.
        subprocess.run(['kubectl', '-n', 'llm', 'delete', 'pod', a.pod, '--wait=false'], capture_output=True, timeout=35)
        raise


if __name__ == '__main__': main()
