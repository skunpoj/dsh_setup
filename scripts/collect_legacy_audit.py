"""Bounded central projection of legacy access events, never account files.

Mount only each protected audit subdirectory read-only. Full source archives
remain at source; this is a recent-event view, not an immutable command ledger.
"""
import json
import os
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone

EVENTS = {'login.success','login.denied','logout','runtime.http','admin.denied','terminal.open','application.websocket'}


def project(directory, label):
    rows=[]
    for file in sorted(Path(directory).glob('events*.jsonl')):
        if file.is_symlink() or not file.is_file(): continue
        with file.open('rb') as stream:
            size=file.stat().st_size;start=max(0,size-1048576);stream.seek(start)
            if start:stream.readline()
            text=stream.read(1048576).decode('utf-8',errors='replace')
        for line in text.splitlines():
            try:
                v=json.loads(line)
                if v.get('event') not in EVENTS or not re.fullmatch(r'[A-Za-z0-9_.-]{1,30}',v.get('user','')):continue
                stamp=datetime.fromisoformat(v['time'].replace('Z','+00:00'))
                if stamp.tzinfo is None:continue
                rows.append({'time':stamp.astimezone(timezone.utc).isoformat(),'event':v['event'],
                             'user':v['user'],'environment':label+'/internet'})
            except (ValueError,TypeError,KeyError,AttributeError):continue
    unique={json.dumps(v,sort_keys=True):v for v in rows}
    return sorted(unique.values(),key=lambda v:v['time'])[-1000:]


def atomic(file, text):
    temporary=file.with_name(file.name+'.tmp-'+uuid.uuid4().hex)
    with temporary.open('w',encoding='utf-8') as stream:
        os.chmod(temporary,0o600);stream.write(text);stream.flush();os.fsync(stream.fileno())
    temporary.replace(file)


def main():
    output=Path(os.environ.get('DSH_AUDIT_OUTPUT','/output'));output.mkdir(exist_ok=True)
    status={'observedAt':datetime.now(timezone.utc).isoformat(),'instances':[],'scope':'Recent protected access events; no command bodies or account credentials'}
    selected=os.environ.get('DSH_AUDIT_SOURCE_LABEL')
    labels=[selected] if selected in ['legacy-dsh2','legacy-dsh3'] else ['legacy-dsh2','legacy-dsh3']
    for label in labels:
        rows=project('/sources/'+label,label)
        atomic(output/('events.jsonl' if selected else label+'.jsonl'),''.join(json.dumps(v)+'\n' for v in rows))
        status['instances'].append({'name':label,'events':len(rows)})
    atomic(output/'status.json',json.dumps(status,indent=2)+'\n')
    print(json.dumps(status))


if __name__=='__main__':main()
