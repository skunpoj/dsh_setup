"""Add launchers for future shell/client invocations; never signal processes.

Input is an operator-prepared, hash-qualified bundle on stdin. Recovery copies
remain private under this user's existing persistent state. No session database,
workspace document, global image file or Kubernetes template is modified.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

BASE = Path('/state/.dsh-managed-clients')
MAX_PRIVATE_FILE = 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('Expected a private, regular owner file')
        if info.st_size > MAX_PRIVATE_FILE:
            raise ValueError('Private profile or metadata is too large')
        chunks = []
        size = 0
        while True:
            chunk = os.read(fd, min(65536, MAX_PRIVATE_FILE + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_PRIVATE_FILE:
                raise ValueError('Private profile or metadata grew beyond its limit')
        after = os.fstat(fd)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Private file changed during read')
        return b''.join(chunks), info
    finally:
        os.close(fd)


def private_directory(path):
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    # Persistent state may inherit setgid; access still must be owner-only.
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o777 != 0o700:
        raise ValueError('Unexpected private launch-layer directory')


def exclusive(path, raw, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(os.dup(fd), 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def atomic_link(target):
    current = BASE / 'current'
    if current.exists() and not current.is_symlink():
        raise ValueError('Managed pointer is not a link')
    staging = BASE / ('.next-' + str(os.getpid()))
    staging.symlink_to(target, target_is_directory=True)
    staging.replace(current)


def install(request):
    payload = request['bundle']
    identity = payload['identity']
    if not re.fullmatch('[a-f0-9]{16}', identity) or payload['path'] != str(BASE / 'releases' / identity):
        raise ValueError('Unexpected release path')
    home = Path.home()
    if home.is_symlink() or home.stat().st_uid != os.getuid():
        raise ValueError('Unexpected user home')
    profile = home / '.bashrc'
    before, info = regular(profile)
    if sha(before) != request['expected_bashrc_sha256']:
        raise ValueError('User profile changed since preflight; no mutation')
    block = payload['bashrc_block'].encode()
    if b'DSH MANAGED CLIENT LAUNCHERS' in before and block not in before:
        raise ValueError('An unrecognized managed shell block already exists')
    if re.search(r'(?m)^\s*(?:alias\s+(?:kilo|kilocode|trueforge)=|(?:function\s+)?(?:kilo|kilocode|trueforge)\s*\()', before.decode('utf-8')):
        raise ValueError('Owner-defined client launcher requires explicit reconciliation')
    for path, expected in request['expected_system_hashes'].items():
        if sha(Path(path).read_bytes()) != expected:
            raise ValueError('A qualified source changed before installation')
    private_directory(BASE)
    private_directory(BASE / 'releases')
    private_directory(BASE / 'recovery')
    release = BASE / 'releases' / identity
    if not release.exists():
        staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=BASE / 'releases'))
        (staging / 'bin').mkdir(mode=0o700)
        for name, content in payload['files'].items():
            if name.startswith('/') or '..' in Path(name).parts or len(Path(name).parts) > 2:
                raise ValueError('Unexpected bundle member')
            exclusive(staging / name, content.encode(), 0o700 if name.startswith('bin/') else 0o600)
        staging.rename(release)
    for name, content in payload['files'].items():
        actual, _ = regular(release / name)
        if actual != content.encode():
            raise ValueError('Existing release differs; refuse overwrite')
    previous = BASE / 'current'
    previous_target = os.readlink(previous) if previous.is_symlink() else None
    if previous.exists() and not previous.is_symlink():
        raise ValueError('Unexpected activation pointer')
    if previous_target and not re.fullmatch(re.escape(str(BASE / 'releases')) + r'/[a-f0-9]{16}', previous_target):
        raise ValueError('Unrecognized previous managed release')
    recovery = BASE / 'recovery' / (str(time.time_ns()) + '-' + identity)
    private_directory(recovery)
    exclusive(recovery / 'bashrc.before', before, stat.S_IMODE(info.st_mode))
    record = {'version': 1, 'release': identity, 'path': str(release),
              'profile': str(profile), 'before_sha256': sha(before),
              'before_mode': stat.S_IMODE(info.st_mode), 'previous_target': previous_target,
              'block_already_present': block in before, 'recovery': str(recovery)}
    exclusive(recovery / 'transaction.json', json.dumps(record, indent=2).encode())
    # Compare once more immediately before an append-only update. O_APPEND keeps
    # existing bytes rather than replacing a user's concurrent appended content.
    current, current_info = regular(profile)
    if current != before or current_info.st_ino != info.st_ino:
        raise ValueError('Concurrent profile edit; activation refused')
    if block not in before:
        fd = os.open(profile, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            if os.fstat(fd).st_ino != info.st_ino:
                raise ValueError('Profile replaced during activation')
            if os.write(fd, block) != len(block):
                raise OSError('Incomplete managed block write')
            os.fsync(fd)
        finally:
            os.close(fd)
    after, _ = regular(profile)
    if not after.startswith(before) or block not in after:
        raise ValueError('Profile readback mismatch; preserve recovery files')
    # A failed profile update must not switch the launch pointer. A shell opened
    # during this small pre-activation interval simply keeps the old behavior.
    atomic_link(str(release))
    record['after_sha256'] = sha(after)
    record['profile_prefix_preserved'] = True
    exclusive(recovery / 'completed.json', json.dumps(record, indent=2).encode())
    return record


def rollback(request):
    recovery = Path(request['recovery'])
    if recovery.is_symlink() or recovery.parent != BASE / 'recovery':
        raise ValueError('Unrecognized recovery location')
    raw, _ = regular(recovery / 'completed.json')
    record = json.loads(raw)
    profile = Path(record['profile'])
    if profile != Path.home() / '.bashrc':
        raise ValueError('Unexpected recovery profile')
    current, _ = regular(profile)
    if sha(current) != record['after_sha256']:
        raise ValueError('User edited profile after install; rollback refuses overwrite')
    old, _ = regular(recovery / 'bashrc.before')
    if sha(old) != record['before_sha256']:
        raise ValueError('Recovery bytes changed')
    pointer = BASE / 'current'
    if not pointer.is_symlink() or os.readlink(pointer) != record['path']:
        raise ValueError('Activation pointer changed; rollback refused')
    temp = profile.with_name('.bashrc.dsh-restore-' + str(os.getpid()))
    exclusive(temp, old, record['before_mode'])
    if regular(profile)[0] != current:
        raise ValueError('Concurrent edit during recovery; no overwrite')
    temp.replace(profile)
    if record['previous_target']:
        atomic_link(record['previous_target'])
    else:
        pointer.unlink()
    assert regular(profile)[0] == old
    return {'profile_restored_exactly': True, 'release_files_retained': True,
            'processes_signalled': 0, 'recovery': str(recovery)}


if __name__ == '__main__':
    os.umask(0o077)
    request = json.load(sys.stdin)
    action = request.get('action', 'install')
    if action not in ['install', 'rollback']:
        raise ValueError('Unknown operation')
    print(json.dumps(install(request) if action == 'install' else rollback(request)))
