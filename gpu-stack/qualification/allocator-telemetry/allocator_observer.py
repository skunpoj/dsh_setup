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
    _start_from_foreground(cuda, emit, device, backend, fraction)

# Opt-in read-only telemetry. Foreground allocator/quota behavior above is intact.
import threading
_periodic = {}
_periodic_lock = threading.Lock()

def _periodic_error(emit, exc):
    try:
        emit('DSH_ALLOCATOR_OBSERVER_ERROR ' + json.dumps({'errorClass': type(exc).__name__}, sort_keys=True))
    except Exception:
        pass  # A failed logger must not crash inference or retry forever.

def _periodic_worker(cuda, emit, device, backend, fraction, identity, stop,
                     clock=time.monotonic, wall=time.time):
    # No CUDA API except memory_stats(device); no CUDA context initialization.
    try:
        while not stop.wait(5):
            sample_started_utc = wall()
            stats = cuda.memory_stats(device)
            if any(key not in stats for key in KEYS):
                raise RuntimeError('Missing allocator counters')
            counters = {key: int(stats[key]) for key in KEYS}
            if any(value < 0 for value in counters.values()):
                raise RuntimeError('Negative allocator counter')
            emit('DSH_ALLOCATOR_COUNTERS ' + json.dumps({
                'device': device, 'backend': backend,
                'processMemoryFraction': fraction,
                'monotonicSeconds': clock(), 'sampleStartedUTC': sample_started_utc,
                'sampleUTC': wall(),
                'sampleKind': 'periodic-readonly',
                'counters': counters, 'processIdentity': identity,
            }, sort_keys=True))
    except Exception as exc:
        stop.set()
        _periodic_error(emit, exc)

def _start_periodic(cuda, emit, device, backend, fraction, identity,
                    event_factory=threading.Event, thread_factory=threading.Thread):
    if os.environ.get('DSH_QUALIFICATION_PERIODIC_READONLY_COUNTERS') != '1':
        return
    # Called only after a successful foreground observe with initialized CUDA.
    # Keep a tombstone even on failure: no repeated thread-start attempts.
    with _periodic_lock:
        if device in _periodic:
            return
        _periodic[device] = {'state': 'starting'}
        try:
            stop = event_factory()
            worker = thread_factory(target=_periodic_worker,
                args=(cuda, emit, device, backend, fraction, dict(identity), stop),
                daemon=True, name='dsh-readonly-allocator-'+str(device))
            _periodic[device] = {'state': 'started', 'stop': stop, 'thread': worker}
            worker.start()
        except Exception as exc:
            entry = _periodic[device]
            if 'stop' in entry:
                entry['stop'].set()
            entry['state'] = 'failed'
            _periodic_error(emit, exc)

def _start_from_foreground(cuda, emit, device, backend, fraction):
    if os.environ.get('DSH_QUALIFICATION_PERIODIC_READONLY_COUNTERS') != '1':
        return
    if device in _periodic:
        return
    try:
        identity = process_identity(Path('/proc/self/stat').read_text(), os.getpid())
        _start_periodic(cuda, emit, device, backend, fraction, identity)
    except Exception as exc:
        with _periodic_lock:
            _periodic[device] = {'state': 'failed'}
        _periodic_error(emit, exc)
