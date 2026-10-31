"""Append bounded-question guidance without replacing user instructions or histories.
Run inside one idle runtime. Input policy is a reviewed UTF-8 file.
Backups and manifest are private operator artifacts, never commit their contents.
"""
import argparse, hashlib, json, os, time
from pathlib import Path

def digest(b): return hashlib.sha256(b).hexdigest()
def histories(root):
    return {str(p.relative_to(root)):digest(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--agents',type=Path,required=True);ap.add_argument('--policy',type=Path,required=True);ap.add_argument('--sessions',type=Path,required=True);ap.add_argument('--backup',type=Path,required=True);a=ap.parse_args()
    marker=b'<!-- DSH:BOUNDED-QUICK-REQUESTS:v1 -->'
    policy=a.policy.read_bytes();before=a.agents.read_bytes()
    if marker not in policy: raise SystemExit('Policy marker missing')
    if marker in before: raise SystemExit('Policy already present; refusing duplicate')
    if a.backup.exists(): raise SystemExit('Backup exists; refusing overwrite')
    lock=a.agents.with_name(a.agents.name+'.quick-policy.lock')
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        baseline=histories(a.sessions)
        with a.backup.open('xb') as f: f.write(before);f.flush();os.fsync(f.fileno())
        intended=before+b'\n\n'+policy
        if a.agents.read_bytes()!=before: raise RuntimeError('Concurrent instructions change; refusing')
        tmp=a.agents.with_name(a.agents.name+'.quick-policy.tmp')
        with tmp.open('xb') as f: f.write(intended);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,a.agents.stat().st_mode & 0o777);os.replace(tmp,a.agents)
        assert a.agents.read_bytes()==intended,'Instruction readback mismatch'
        after=histories(a.sessions)
        result={'historyFiles':len(baseline),'historiesUnchanged':baseline==after,'beforeSHA256':digest(before),'afterSHA256':digest(intended),'policySHA256':digest(policy),'backupSHA256':digest(a.backup.read_bytes())}
        print(json.dumps(result))
        if baseline!=after: raise RuntimeError('History changed concurrently; investigate; no histories were written by this tool')
    finally: os.close(fd);lock.unlink()
if __name__=='__main__':main()
