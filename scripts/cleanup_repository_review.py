"""Archive, verify and remove only a completed disposable review runtime."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

from stress_live_inference import snapshot


def kube(*args, stdin=None):
    p = subprocess.run(['kubectl', '--request-timeout=25s', '-n', 'llm', *args],
                       input=stdin, text=True, encoding='utf-8', capture_output=True, timeout=90)
    if p.returncode: raise RuntimeError(p.stderr[-500:])
    return p.stdout


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--directory', type=Path, required=True)
    a = ap.parse_args(); out = a.directory
    controller = json.loads((out/'controller.json').read_text(encoding='utf-8'))
    pod = controller['pod']
    if pod != 'dsh-realistic-1m-revision-20261017' or controller['status'] != 'completed':
        raise ValueError('Only the completed, explicitly allowlisted review can be removed')
    for child in out.glob('correction-*/controller.json'):
        if json.loads(child.read_text(encoding='utf-8'))['status'] != 'completed':
            raise ValueError('A recorded correction is not complete; do not remove its runtime')
    code = '''import base64,hashlib,json,tarfile
from pathlib import Path
root=Path('/state/sessions');files=list(root.rglob('*'))
if any(p.is_symlink() for p in files):raise RuntimeError('Unexpected session symlink')
archive=Path('/tmp/review-sessions.tar.gz')
with tarfile.open(archive,'w:gz') as tar:tar.add(root,arcname='sessions')
data=archive.read_bytes()
print(json.dumps({'sha256':hashlib.sha256(data).hexdigest(),'sessionFiles':sum(p.is_file() for p in files),'bytes':len(data),'base64':base64.b64encode(data).decode()}))
'''
    remote = json.loads(kube('exec', '-i', pod, '--', 'python3', '-', stdin=code))
    data = base64.b64decode(remote.pop('base64'), validate=True)
    if hashlib.sha256(data).hexdigest() != remote['sha256']: raise ValueError('Archive hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        members = tar.getmembers()
        if any(PurePosixPath(m.name).is_absolute() or '..' in PurePosixPath(m.name).parts or
               PurePosixPath(m.name).parts[0] != 'sessions' or not (m.isdir() or m.isfile()) for m in members):
            raise ValueError('Archive path/type outside permitted session files')
        count = sum(m.isfile() for m in members)
    if count != remote['sessionFiles']: raise ValueError('Session archive count mismatch')
    (out/'disposable-session-archive.tar.gz').write_bytes(data)
    remote.update(downloadHashVerified=True, downloadedArchiveRegularFiles=count,
                  archivePathsRestrictedToSessions=True)
    (out/'session-archive-verification.json').write_text(json.dumps(remote, indent=2), encoding='utf-8')
    lease_code = '''import fcntl,json
f=open('/tmp/dsh-long-admission/active.lock','a+');available=True
try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
except BlockingIOError:available=False
f.close();print(json.dumps({'available':available}))
'''
    available = json.loads(kube('exec', '-i', 'deploy/litellm', '-c', 'context-forwarder',
                                '--', 'python', '-', stdin=lease_code))['available']
    if not available: raise RuntimeError('Long lease still occupied; do not treat deletion as cancellation')
    kube('delete', 'pod', pod, '--wait=true', '--timeout=60s')
    absent = not json.loads(kube('get', 'pods', '--field-selector=metadata.name='+pod, '-o', 'json'))['items']
    post = '''import json,os,time,urllib.request
start=time.monotonic();expected='REVIEW_REVISION_POST_OK'
r=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',data=json.dumps({'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':'Reply exactly '+expected}],'temperature':0,'max_tokens':32}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
with urllib.request.urlopen(r,timeout=40) as f:v=json.load(f)
print(json.dumps({'exact':v['choices'][0]['message']['content'].strip()==expected,'seconds':time.monotonic()-start,'usage':v.get('usage')}))
'''
    inference = json.loads(kube('exec', '-i', 'deploy/dsh-secure', '--', 'python3', '-', stdin=post))
    state = snapshot()
    available_after = json.loads(kube('exec', '-i', 'deploy/litellm', '-c', 'context-forwarder',
                                      '--', 'python', '-', stdin=lease_code))['available']
    result = {'testPodAbsent': absent, 'sessionArchive': remote, 'postCleanupInference': inference,
              'admissionAvailable': available_after,
              'admissionAvailableBeforeDeletion': available,
              'modelUnchanged': state['pods'] == controller['before']['pods'],
              'model': state['pods'], 'scope': 'Only completed disposable runtime removed; no user volumes or shared inference configuration changed.'}
    (out/'cleanup-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if not absent or not inference['exact'] or not result['modelUnchanged']:
        raise RuntimeError('Cleanup/post-inference verification failed; inspect saved result')
    print(json.dumps(result))


if __name__ == '__main__': main()
