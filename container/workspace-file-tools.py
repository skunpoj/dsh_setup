#!/usr/bin/env python3
"""Bounded local text-file operations; no shell, network or credential access.

Linux dirfd traversal with O_NOFOLLOW keeps symlink swaps from escaping the
private workspace. New content is published atomically in the opened parent.
"""
import json
import os
import secrets
import stat
import sys

LIMIT = 1024 * 1024
ROOT = '/workspace'


def operate(request, root=ROOT):
    operation = request.get('name')
    args = request.get('arguments', {})
    path = args.get('path')
    if operation not in {'read_file', 'write_file', 'list_directory'}:
        raise ValueError('Unknown workspace operation')
    if not isinstance(path, str) or '\x00' in path or len(path) > 4096:
        raise ValueError('A workspace path is required')
    if path.startswith('/'):
        if path != root and not path.startswith(root + '/'):
            raise ValueError('Path is outside the private workspace')
        path = path[len(root):].lstrip('/')
    parts = path.split('/') if path else []
    if any(p in {'', '.', '..'} for p in parts):
        raise ValueError('Use a normalized workspace path without traversal')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = [os.open(root, flags)]
    try:
        parents = parts if operation == 'list_directory' else parts[:-1]
        for part in parents:
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        parent = descriptors[-1]
        if operation == 'list_directory':
            names = os.listdir(parent)
            if len(names) > 2000:
                raise ValueError('Directory exceeds the 2000-entry limit')
            return {'entries': sorted(names)}
        if not parts:
            raise ValueError('A file path is required')
        name = parts[-1]
        if operation == 'read_file':
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT:
                    raise ValueError('Only single-link regular text files up to 1 MiB are supported')
                data = file.read(LIMIT + 1)
                if len(data) > LIMIT:
                    raise ValueError('File exceeds the 1 MiB limit')
                return {'content': data.decode('utf-8')}
        content = args.get('content')
        if not isinstance(content, str) or len(content.encode('utf-8')) > LIMIT:
            raise ValueError('UTF-8 text up to 1 MiB is required')
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Refusing a symlink, hardlink or special file')
            mode = stat.S_IMODE(info.st_mode) & 0o666
        except FileNotFoundError:
            mode = 0o600
        temporary = '.dsh-file-' + secrets.token_hex(16)
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         mode, dir_fd=parent)
            with os.fdopen(fd, 'wb') as file:
                file.write(content.encode('utf-8'))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        return {'written': True, 'bytes': len(content.encode('utf-8'))}
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(2 * LIMIT + 1)
        if len(raw) > 2 * LIMIT:
            raise ValueError('Request too large')
        print(json.dumps(operate(json.loads(raw))))
    except (ValueError, OSError, UnicodeError, TypeError) as error:
        print(json.dumps({'error': str(error)}))
        raise SystemExit(1)
