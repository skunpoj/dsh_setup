"""Run real signup/DSH/terminal/persistence acceptance only on reserved runtimes."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pool', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--kubectl', default='kubectl')
    ap.add_argument('--gateway', default='dsh-environment-gateway', help='Isolated candidate gateway Deployment or the staged main gateway')
    a = ap.parse_args();a.output.mkdir(parents=True, exist_ok=False)
    def kube(*args):
        return subprocess.check_output([a.kubectl, '-n', 'llm', '--request-timeout=30s', *args], text=True, encoding='utf-8', timeout=190)
    expected = json.loads(a.pool.read_text())['slots']
    actual = json.loads(kube('exec', 'deploy/'+a.gateway, '--', 'cat', '/signup-pool/test.json'))['slots']
    if not actual or any(s not in expected or actual[s] != expected[s] for s in actual):
        raise RuntimeError('Acceptance targets differ from the prepared private pool')
    workloads = []
    for slot, pair in actual.items():
        for environment, target in pair.items():
            name = target['host'].split('.')[0]
            obj = json.loads(kube('get', 'deploy', name, '-o', 'json'))
            if not obj['metadata'].get('labels', {}).get('dsh.bot.or.th/signup-pool'):
                raise RuntimeError('Refusing to replace a non-signup workload')
            workloads.append(name)
    source = (Path(__file__).parent/'verify_self_signup_live.js').read_text()
    p = subprocess.Popen([a.kubectl, '-n', 'llm', '--request-timeout=30s', 'exec', '-i',
        'deploy/'+a.gateway, '--', 'node', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding='utf-8', bufsize=1)
    p.stdin.write(source);p.stdin.close();records = []
    try:
        with (a.output/'events.jsonl').open('w') as log:
            for line in p.stdout:
                log.write(line);log.flush()
                if not line.startswith('{'):continue
                event = json.loads(line);records.append(event);print(json.dumps(event), flush=True)
                if event.get('phase') == 'awaiting-runtime-replacement':
                    checkpoint = event['checkpoint']
                    if not re.fullmatch(r'/auth/signup-acceptance-[a-f0-9]{10}/continue', checkpoint):
                        raise RuntimeError('Unexpected acceptance checkpoint')
                    for name in workloads:
                        kube('rollout', 'restart', 'deploy/' + name)
                        kube('rollout', 'status', 'deploy/' + name, '--timeout=150s')
                    kube('exec', 'deploy/'+a.gateway, '--', 'node', '-e',
                        'require("fs").writeFileSync(' + json.dumps(checkpoint) + ',"continue")')
        if p.wait() != 0 or not records or records[-1].get('status') != 'passed':
            raise RuntimeError('Signup acceptance failed; leave registration disabled')
        (a.output/'result.json').write_text(json.dumps(records[-1], indent=2)+'\n')
        for name in workloads:
            kube('scale', 'deploy/' + name, '--replicas=0')
        print(json.dumps({'acceptancePassed': True, 'retiredTestRuntimes': len(workloads)}))
    finally:
        if p.poll() is None:p.terminate()


if __name__ == '__main__':main()
