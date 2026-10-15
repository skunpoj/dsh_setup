"""Reconcile a stopped local workspace into its original central mount.

Local content wins only after a differing central file has been preserved and
verified in a separate recovery directory. Never delete destination-only files.
Run as an operator with the source writer stopped, not as an interactive tool.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import uuid


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def bounded(path, root):
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes the approved workspace')
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError('Symlinks require a separate reviewed migration')
        current = current.parent


def atomic_copy(source, destination):
    temporary = destination.with_name('.dsh-copy-' + uuid.uuid4().hex)
    try:
        with source.open('rb') as incoming, temporary.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if digest(source) != digest(temporary):
            raise RuntimeError('Copy verification failed')
        value = source.stat()
        os.utime(temporary, ns=(value.st_atime_ns, value.st_mtime_ns))
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def reconcile(source, target, recovery):
    source, target, recovery = map(lambda p: Path(p).absolute(), (source, target, recovery))
    if target.resolve() == source.resolve() or recovery.resolve().is_relative_to(target.resolve()):
        raise ValueError('Recovery must be outside the mounted workspace')
    if recovery.exists():
        raise FileExistsError('Never reuse an earlier recovery directory')
    entries = sorted(source.rglob('*'))
    # Reject unsafe types before changing the destination.
    for path in entries:
        bounded(path, source)
        destination = target / path.relative_to(source)
        bounded(destination, target)
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError('Special files require a separate reviewed migration')
        if destination.exists() and path.is_dir() != destination.is_dir():
            raise ValueError('File/directory collision requires manual reconciliation')
    recovery.mkdir(parents=True, mode=0o700)
    records = []
    result = dict(sourceFiles=0, unchanged=0, copiedNew=0, conflictsPreserved=0,
                  verifiedFiles=0, contentFailures=0, destinationOnlyPreserved=0)
    source_files = set()
    for path in entries:
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        source_files.add(relative.as_posix())
        result['sourceFiles'] += 1
        expected = digest(path)
        old = digest(destination) if destination.exists() else None
        if old == expected:
            result['unchanged'] += 1
        else:
            if old is not None:
                preserved = recovery / 'central-conflicts' / relative
                preserved.parent.mkdir(parents=True, exist_ok=True)
                atomic_copy(destination, preserved)
                if digest(preserved) != old or digest(destination) != old:
                    raise RuntimeError('Central file changed during preservation')
                result['conflictsPreserved'] += 1
            else:
                result['copiedNew'] += 1
            destination.parent.mkdir(parents=True, exist_ok=True)
            if (digest(destination) if destination.exists() else None) != old:
                raise RuntimeError('Concurrent destination change; do not overwrite it')
            atomic_copy(path, destination)
        if digest(destination) != expected:
            result['contentFailures'] += 1
            raise RuntimeError('Resulting central content differs')
        result['verifiedFiles'] += 1
        records.append({'path': relative.as_posix(), 'sha256': expected,
                        'previousCentralSha256': old})
        if result['verifiedFiles'] % 250 == 0:
            print(json.dumps({'phase': 'reconcile', **result}), flush=True)
    for path in target.rglob('*'):
        if path.is_file() and path.relative_to(target).as_posix() not in source_files:
            result['destinationOnlyPreserved'] += 1
    (recovery / 'workspace-manifest.json').write_text(json.dumps(records), encoding='utf-8')
    (recovery / 'workspace-result.json').write_text(json.dumps(result), encoding='utf-8')
    return result


def restore_history_archive(archive, target):
    """Portable safe extraction for the installed Python, without extractall.

    Restore only ordinary files/directories into a new quarantine directory;
    refuse links, special files and paths outside it, then read back every file.
    """
    archive, target = Path(archive), Path(target)
    target.mkdir(mode=0o700)  # Never overwrite a previous restore attempt.
    records = []
    with tarfile.open(archive, 'r:gz') as source:
        for member in source:
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe archive path')
            destination = target / relative
            bounded(destination, target)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                destination.parent.mkdir(parents=True, exist_ok=True)
                expected = hashlib.sha256()
                with source.extractfile(member) as incoming, destination.open('xb') as outgoing:
                    for block in iter(lambda: incoming.read(1024 * 1024), b''):
                        expected.update(block)
                        outgoing.write(block)
                if digest(destination) != expected.hexdigest():
                    raise RuntimeError('Extracted history differs from archive')
                records.append({'path': relative.as_posix(), 'sha256': expected.hexdigest()})
            else:
                raise ValueError('Archive links or special files require review')
    return {'restoredStateFilesChecked': len(records), 'stateArchiveSHA256': digest(archive),
            'restoredManifest': records}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--recovery', required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.source, args.target, args.recovery)), flush=True)
