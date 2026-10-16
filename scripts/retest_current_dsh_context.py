"""Progressive real DSH context acceptance on an isolated current-image runtime.

Uses an existing disposable pod, never edits production configuration or histories.
Stops escalation on failed exact output, slow short replies or model replacement.
"""
import argparse
import concurrent.futures
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from stress_live_inference import REQUEST, snapshot


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pod', required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--targets', type=int, nargs='+', default=[256000, 512000, 1000000])
    a = ap.parse_args()
    if a.output.exists():
        raise ValueError('Refuse to overwrite evidence')
    if not a.pod.startswith('dsh-current-1m-retest'):
        raise ValueError('Disposable runtime required')
    record = {'startUTC': datetime.now(timezone.utc).isoformat(), 'pod': a.pod,
              'status': 'running', 'configurationChanged': False, 'stages': [], 'samples': []}

    def save():
        temporary = a.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2), encoding='utf8')
        temporary.replace(a.output)

    def remote(source, timeout):
        p = subprocess.run(['kubectl', '-n', 'llm', 'exec', '-i', a.pod,
                            '--', 'python3', '-'], input=source, text=True,
                           encoding='utf8', capture_output=True, timeout=timeout)
        if p.returncode:
            raise RuntimeError('Disposable DSH probe failed: '+p.stderr[-500:])
        return json.loads(p.stdout)

    probe = Path(__file__).with_name('probe_dsh_1m_agent.py').read_text()

    def agent(target=0, tool=False, session=None):
        args = ['probe', '--input-target', str(target), '--deadline', '2700']
        if tool:
            args += ['--tool-test']
        if session:
            args += ['--session-id', session]
        return remote('import sys;sys.argv='+repr(args)+'\n'+probe, 2800)

    try:
        before = snapshot()
        record['before'] = before
        save()
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            for target in a.targets:
                state = snapshot()
                if state['pods'] != before['pods']:
                    raise RuntimeError('Model identity/restart changed')
                if state['metrics'].get('sglang:num_running_reqs', 1) or state['metrics'].get('sglang:num_queue_reqs', 1):
                    raise RuntimeError('Shared service busy; stop escalation')
                stage = {'target': target, 'startUTC': datetime.now(timezone.utc).isoformat(),
                         'status': 'running', 'shortPairs': [], 'bursts': []}
                record['stages'].append(stage)
                save()
                future = pool.submit(agent, target)
                admission_future = None
                started = time.monotonic()
                next_probe = 20
                while not future.done():
                    time.sleep(10)
                    if time.monotonic()-started >= next_probe and not future.done():
                        pair = [pool.submit(agent), pool.submit(agent)]
                        values = [f.result() for f in pair]
                        overlap = not future.done()
                        stage['shortPairs'].append({'overlap': overlap, 'results': values})
                        if not all(v['expectedTextPresent'] and v['persistedPromptMatches'] and v['elapsedSeconds'] < 60 for v in values):
                            raise RuntimeError('Short DSH exact-output or responsiveness gate failed')
                        if not stage['bursts']:
                            for n in [2, 4]:
                                plan = {'kind': 'burst', 'concurrency': n}
                                source = 'PLAN='+repr(json.dumps(plan))+'\n'+REQUEST
                                burst = remote(source, 100)
                                burst['longStillRunningAfter'] = not future.done()
                                stage['bursts'].append(burst)
                                if not burst['allExact']:
                                    raise RuntimeError('Concurrent output mismatch')
                            if target >= 1000000 and not future.done():
                                admission_source = r'''
import json,os,time,uuid,urllib.request,urllib.error
body={'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':str(uuid.uuid4())+' red blue green yellow'*35000+' Reply exactly QUEUED_OK.'}],'max_tokens':16,'temperature':0}
request=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
start=time.monotonic()
try:
 with urllib.request.urlopen(request,timeout=340) as r:
  value=json.load(r);result={'httpStatus':r.status,'usage':value.get('usage')}
except urllib.error.HTTPError as e:
 text=e.read().decode();result={'httpStatus':e.code,'longCapacityBusy':'Long-context capacity busy' in text,'retryAfter':e.headers.get('retry-after')}
result['seconds']=time.monotonic()-start
print(json.dumps(result))
'''
                                admission_future = pool.submit(remote, admission_source, 355)
                        next_probe = time.monotonic()-started+120
                    state = snapshot()
                    record['samples'].append(state)
                    save()
                    if state['pods'] != before['pods']:
                        raise RuntimeError('Model replacement/restart during acceptance')
                value = future.result()
                stage['result'] = value
                if admission_future:
                    stage['secondLongAdmission'] = admission_future.result()
                    if stage['secondLongAdmission'].get('httpStatus') != 429:
                        raise RuntimeError('Second long request was not rejected by bounded admission')
                if not value['expectedTextPresent'] or not value['persistedPromptMatches']:
                    raise RuntimeError('Long DSH output/persistence mismatch')
                if value['lastUsage']['inputTokens'] < target:
                    raise RuntimeError('Actual input below target')
                stage['status'] = 'passed'
                save()
                print(json.dumps({'acceptedTarget': target, 'usage': value['lastUsage'],
                                  'seconds': value['elapsedSeconds'],
                                  'shortPairs': len(stage['shortPairs'])}), flush=True)
            last = record['stages'][-1]['result']
            tool = agent(tool=True, session=last['sessionId'])
            record['toolContinuation'] = tool
            assert tool['expectedTextPresent'] and tool['actualToolFileMatches'] and tool['testFileRemoved']
        record['after'] = snapshot()
        assert record['before']['pods'] == record['after']['pods']
        record['status'] = 'passed'
    except Exception as e:
        record['status'] = 'stopped'
        record['reason'] = str(e)
    finally:
        record['finishUTC'] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({'status': record['status'], 'reason': record.get('reason')}), flush=True)
    if record['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
