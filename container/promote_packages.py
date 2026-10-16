"""Promote reviewed artifacts without following symlinks or reopening sources.

Linux operator job only. The incoming mount is untrusted and read-only here;
the approved mount is writable only in this job. Never overwrite an approved
artifact: identical content is idempotent, conflicting content is refused.
"""
import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

DIR_FLAGS = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)


def relative_parts(value):
    parts = value.split('/')
    if not value or value.startswith('/') or any(p in ('', '.', '..') for p in parts):
        raise ValueError('Unsafe artifact path')
    if not re.fullmatch(r'[A-Za-z0-9_./+@=-]+', value):
        raise ValueError('Unsupported artifact path')
    return parts


def directory_at(root, parts, create=False):
    fd = os.dup(root)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def promote(manifest, incoming, approved):
    if not hasattr(os, 'O_NOFOLLOW') or os.open not in os.supports_dir_fd:
        raise RuntimeError('Linux no-follow and directory-FD operations required')
    rows=[]
    for line in Path(manifest).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        fields=line.split()
        if len(fields)!=2 or not re.fullmatch('[a-fA-F0-9]{64}',fields[0]):
            raise ValueError('Invalid approval row')
        parts=relative_parts(fields[1]);rows.append((fields[0].lower(),parts))
    if not rows or len({tuple(p) for _,p in rows})!=len(rows):
        raise ValueError('Approval must contain unique artifacts')
    source_root=os.open(incoming,DIR_FLAGS)
    target_root=os.open(approved,DIR_FLAGS)
    staged=[]
    try:
        # Verify and stage every row before making any artifact visible.
        for digest,parts in rows:
            parent=directory_at(source_root,parts[:-1])
            try:
                fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            finally:
                os.close(parent)
            h=hashlib.sha256()
            # Anonymous temporary staging is outside the untrusted Incoming mount.
            temporary=tempfile.TemporaryFile()
            try:
                with os.fdopen(fd,'rb') as f:
                    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                        raise ValueError('Artifact must be a regular file')
                    size=0
                    while block:=f.read(1024*1024):
                        size+=len(block)
                        if size>256*1024*1024:
                            raise ValueError('Artifact exceeds operator size limit')
                        h.update(block);temporary.write(block)
                if h.hexdigest()!=digest:
                    raise ValueError('Artifact hash mismatch')
                temporary.seek(0);staged.append((digest,parts,temporary))
            except BaseException:
                temporary.close();raise
        for digest,parts,temporary in staged:
            parent=directory_at(target_root,parts[:-1],create=True)
            name='.promotion-'+os.urandom(12).hex()
            try:
                fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444,dir_fd=parent)
                with os.fdopen(fd,'wb') as f:
                    while block:=temporary.read(1024*1024):f.write(block)
                    f.flush();os.fsync(f.fileno())
                try:
                    os.link(name,parts[-1],src_dir_fd=parent,dst_dir_fd=parent,follow_symlinks=False)
                except FileExistsError:
                    existing=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
                    with os.fdopen(existing,'rb') as f:
                        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode) or hashlib.file_digest(f,'sha256').hexdigest()!=digest:
                            raise ValueError('Approved artifact conflicts with manifest')
            finally:
                try:os.unlink(name,dir_fd=parent)
                except FileNotFoundError:pass
                os.close(parent)
        return len(staged)
    finally:
        for _,_,f in staged:f.close()
        os.close(source_root);os.close(target_root)


if __name__=='__main__':
    count=promote(os.environ.get('APPROVAL_MANIFEST','/approval/manifest.sha256'),
                  os.environ.get('INCOMING_ROOT','/packages/incoming'),
                  os.environ.get('APPROVED_ROOT','/packages/approved'))
    print(f'promoted {count} verified dependency artifacts')
