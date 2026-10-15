"""Stopped-writer header-only cwd migration. Conversation event frames stay byte-identical."""
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import shutil

class Zstd:
    def __init__(self):
        self.lib = ctypes.CDLL(ctypes.util.find_library('zstd'))
        for name, args in [('ZSTD_findFrameCompressedSize',[ctypes.c_void_p,ctypes.c_size_t]),('ZSTD_decompress',[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]),('ZSTD_compress',[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]),('ZSTD_isError',[ctypes.c_size_t])]:
            f=getattr(self.lib,name);f.argtypes=args;f.restype=ctypes.c_size_t
    def check(self,n):
        if self.lib.ZSTD_isError(n):raise ValueError('Invalid or oversized Zstandard header frame')
        return n
    def header(self,path):
        with path.open('rb') as f:b=f.read(65536)
        n=self.check(self.lib.ZSTD_findFrameCompressedSize(b,len(b)))
        out=ctypes.create_string_buffer(1048576)
        size=self.check(self.lib.ZSTD_decompress(out,len(out),b,n))
        raw=out.raw[:size]
        if raw.count(b'\n')!=1 or not raw.endswith(b'\n'):raise ValueError('First frame must contain only one header')
        return json.loads(raw),n
    def encode(self,h):
        b=(json.dumps(h,ensure_ascii=False,separators=(',',':'))+'\n').encode()
        out=ctypes.create_string_buffer(len(b)*2+1024)
        n=self.check(self.lib.ZSTD_compress(out,len(out),b,len(b),3))
        return out.raw[:n]

def project_key(cwd):
    readable='';separator=False
    for ch in cwd:
        if ch in '/\\:':
            if not separator:readable+='-'
            separator=True
        elif ch!='~' and ch.isascii() and (ch.isalnum() or ch in '._-'):
            readable+=ch;separator=False
        else:
            readable+='~'+format(ord(ch),'04X');separator=False
    return '--'+(readable.lstrip('-') or 'root')[:251]+'--'

def file_digest(path):
    return event_digest(path,0)

def event_digest(path,offset):
    h=hashlib.sha256()
    with path.open('rb') as f:
        f.seek(offset)
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def migrate(root,mapping,recovery,zstd=None):
    root,recovery=Path(root),Path(recovery)
    if recovery.exists():raise FileExistsError('Fresh recovery required')
    zstd=zstd or Zstd();plans=[];seen=set()
    for p in root.rglob('*.jsonl.zstd'):
        h,offset=zstd.header(p);old=h.get('cwd')
        if old not in mapping:
            if old=='/root' or isinstance(old,str) and old.startswith('/root/'):
                raise ValueError('Unmapped legacy root cwd; refusing partial migration')
            continue
        new=mapping[old]
        if not Path(new).is_dir() or not os.access(new,os.R_OK|os.X_OK):raise ValueError('Mapped workspace is unavailable')
        dest=root/project_key(new)/p.parent.name/p.name
        if dest.exists() and dest!=p:raise ValueError('Session generation collision')
        key=str(dest)
        if key in seen:raise ValueError('Duplicate destination')
        seen.add(key);plans.append((p,dest,h,offset,new))
    recovery.mkdir(parents=True,mode=0o700)
    changed=0;events_verified=0;ids=set()
    for p,dest,h,offset,new in plans:
        original=recovery/p.relative_to(root);original.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,original)
        if file_digest(p)!=file_digest(original):raise RuntimeError('Recovery copy differs')
        before=event_digest(p,offset);updated=dict(h,cwd=new)
        dest.parent.mkdir(parents=True,exist_ok=True);temporary=dest.with_name(dest.name+'.cwd-migration')
        with temporary.open('xb') as out,p.open('rb') as source:
            out.write(zstd.encode(updated));source.seek(offset);shutil.copyfileobj(source,out,1048576);out.flush();os.fsync(out.fileno())
        actual,new_offset=zstd.header(temporary)
        if actual!=updated or event_digest(temporary,new_offset)!=before:raise RuntimeError('Header or conversation event verification failed')
        os.replace(temporary,dest)
        if p!=dest:p.unlink()
        ids.add(h['id']);changed+=1;events_verified+=1
    return {'sessionRecordsCorrected':len(ids),'generationHeadersCorrected':changed,'eventStreamsByteIdentical':events_verified,'blanketHistoryReplacement':False}
