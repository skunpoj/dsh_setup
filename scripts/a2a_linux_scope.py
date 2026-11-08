"""Physical cgroup-v2 scope primitives for an admitted Linux task worker.

No delegation, privilege elevation, model call or subprocess occurs on import.
The caller must supply a predelegated private cgroup root, never host/root.
These primitives alone do not qualify a supervisor or enable broker admission.
"""
import os
from pathlib import Path
import re
import time


class LinuxTaskScope:
    def __init__(self, root, scope_id, *, expected_root_inode):
        if os.name != "posix" or not Path('/proc/self/cgroup').exists():
            raise ValueError('LINUX_CGROUP_REQUIRED')
        if not re.fullmatch(r'[a-f0-9]{32}', scope_id):
            raise ValueError('INVALID_SCOPE_ID')
        root = Path(root)
        if root.is_symlink() or root.resolve(strict=True) != root:
            raise ValueError('UNSAFE_CGROUP_ROOT')
        if root == Path('/sys/fs/cgroup') or not root.is_relative_to('/sys/fs/cgroup'):
            raise ValueError('PRIVATE_DELEGATED_CGROUP_REQUIRED')
        stat = root.stat()
        if stat.st_ino != expected_root_inode:
            raise ValueError('CGROUP_ROOT_IDENTITY_CHANGED')
        if not (root / 'cgroup.controllers').is_file():
            raise ValueError('CGROUP_V2_REQUIRED')
        self.root, self.root_inode = root, expected_root_inode
        self.path, self.inode = root / scope_id, None

    def _root_identity(self):
        if (self.root.is_symlink() or self.root.resolve(strict=True) != self.root
                or self.root.stat().st_ino != self.root_inode):
            raise ValueError('CGROUP_ROOT_IDENTITY_CHANGED')

    def create_once(self):
        self._root_identity()
        self.path.mkdir()  # Existing scope is an error, never reused or overwritten.
        self.inode = self.path.stat().st_ino
        self._identity()
        return self.inode

    def bind_existing(self, inode):
        if type(inode) is not int or inode <= 0:
            raise ValueError('INVALID_CGROUP_INODE')
        self.inode = inode
        self._identity()

    def _identity(self):
        self._root_identity()
        if (self.inode is None or self.path.is_symlink()
                or self.path.resolve(strict=True) != self.path
                or self.path.stat().st_ino != self.inode):
            raise ValueError('TASK_CGROUP_IDENTITY_CHANGED')

    def populated(self):
        self._identity()
        raw = (self.path / 'cgroup.events').read_text(encoding='ascii')
        entries = {}
        for line in raw.splitlines():
            key, value = line.split()
            if key in entries:
                raise ValueError('AMBIGUOUS_CGROUP_EVENTS')
            entries[key] = value
        if entries.get('populated') not in {'0', '1'}:
            raise ValueError('CGROUP_POPULATION_UNAVAILABLE')
        # Kernel populated includes descendants, including nested cgroups.
        return entries['populated'] == '1'

    def join_current_process(self):
        """Called by a disposable worker BEFORE exec of any agent/tool.

        This is deliberately not a broker-side PID attach; the worker cannot
        execute its payload before kernel membership has been read back.
        """
        self._identity()
        (self.path / 'cgroup.procs').write_text(str(os.getpid()), encoding='ascii')
        members = (self.path / 'cgroup.procs').read_text(encoding='ascii').split()
        if str(os.getpid()) not in members:
            raise ValueError('CGROUP_JOIN_NOT_VERIFIED')

    def kill_and_verify(self, *, timeout=5.0):
        if type(timeout) not in (int, float) or not 0 < timeout <= 5:
            raise ValueError('INVALID_SCOPE_STOP_TIMEOUT')
        self._identity()
        # cgroup.kill recursively kills all members; setsid cannot escape it.
        # Missing delegation/control fails, with no process-group fallback.
        (self.path / 'cgroup.kill').write_text('1', encoding='ascii')
        deadline = time.monotonic() + timeout
        while self.populated():
            if time.monotonic() >= deadline:
                raise TimeoutError('TASK_CGROUP_STILL_POPULATED')
            time.sleep(0.02)
        self._identity()
        return {'scopeInode': self.inode, 'descendantAbsenceVerified': True}

    def remove_empty(self):
        self._identity()
        if self.populated():
            raise ValueError('REFUSE_REMOVE_POPULATED_SCOPE')
        self.path.rmdir()  # Nested scopes or any other failure remain visible.
        if self.path.exists():
            raise ValueError('TASK_CGROUP_REMOVAL_UNVERIFIED')
