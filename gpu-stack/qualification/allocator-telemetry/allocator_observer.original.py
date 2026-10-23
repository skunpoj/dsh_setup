"""Qualification-only allocator counters. Does not change tensor operations.

Enable only in a scoped candidate. Native allocator configuration is supplied
before CUDA initialization. The existing process quota is re-applied unchanged
to enable PyTorch's native garbage-collection threshold, rather than increasing
the quota or calling empty_cache on every forward.
"""
import json
import os
import time
from pathlib import Path

def process_identity(stat_text, pid):
    # comm can contain spaces and ')'; split at the final closing parenthesis.
    if type(pid) is not int or pid<=0:raise ValueError('Invalid process PID')
    head,sep,tail=stat_text.rpartition(')')
    fields=tail.split()
    if not sep or not head.startswith(str(pid)+' (') or len(fields)<20:
        raise ValueError('Malformed self process stat')
    ticks=fields[19]
    if not ticks.isdecimal() or int(ticks)<=0:raise ValueError('Invalid process start ticks')
    if fields[0] in {'Z','X','x'}:raise ValueError('Non-live self process stat')
    return {'pid':pid,'startTicks':int(ticks)}


_state = {}
KEYS = (
    'allocated_bytes.all.current', 'reserved_bytes.all.current',
    'allocated_bytes.all.peak', 'reserved_bytes.all.peak',
    'inactive_split_bytes.all.current', 'num_alloc_retries', 'num_ooms',
    'num_device_alloc', 'num_device_free',
)

def observe(cuda, emit, clock=time.monotonic):
    if os.environ.get('DSH_QUALIFICATION_NATIVE_ALLOCATOR') != '1':
        return
    if not cuda.is_initialized() or cuda.is_current_stream_capturing():
        return
    device = int(cuda.current_device())
    now = clock()
    previous = _state.get(device)
    if previous and now - previous['at'] < 5:
        return
    backend = cuda.get_allocator_backend()
    if backend != 'native':
        raise RuntimeError('Qualification requires native allocator')
    fraction = float(cuda.get_per_process_memory_fraction(device))
    if not (0 < fraction <= 1):
        raise RuntimeError('Invalid existing CUDA process memory fraction')
    if previous is None:
        cuda.set_per_process_memory_fraction(fraction, device)
    stats = cuda.memory_stats(device)
    missing = [key for key in KEYS if key not in stats]
    if missing:
        raise RuntimeError('Required allocator counters unavailable: ' + ','.join(missing))
    counters = {key: int(stats[key]) for key in KEYS}
    if any(value < 0 for value in counters.values()):
        raise RuntimeError('Invalid negative allocator counter')
    emit('DSH_ALLOCATOR_COUNTERS ' + json.dumps({
        'device': device, 'backend': backend, 'processMemoryFraction': fraction,
        'monotonicSeconds': now, 'counters': counters,
        'processIdentity': process_identity(Path('/proc/self/stat').read_text(), os.getpid()),
    }, sort_keys=True))
    _state[device] = {'at': now}
