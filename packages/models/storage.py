"""Conservative quota reservations for models-owned derived data and downloads."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import time
from .protocol import ModelBlocked, resolve_relative

LIMITS = {'models': 180_000_000_000, 'runtime': 70_000_000_000,
          'data': 300_000_000_000, 'render': 40_000_000_000, 'platform': 60_000_000_000}


def tree_bytes(path):
    total = 0
    if path.exists():
        for directory, _, files in os.walk(path, followlinks=False):
            for name in files:
                p = Path(directory) / name
                if not p.is_symlink():
                    total += p.stat().st_size
    return total


@contextmanager
def reserve(root, peak_bytes):
    """One models writer at a time; stale locks require explicit inspection."""
    root = Path(root).resolve()
    resolve_relative(root,'models/.writer-reservation.json',owner='models')
    owner = root / 'models'
    owner.mkdir(parents=True, exist_ok=True)
    lock = owner / '.writer-reservation.json'
    if type(peak_bytes) is not int or peak_bytes <= 0:
        raise ValueError('positive peak_bytes required')
    try:
        stream = lock.open('x', encoding='utf-8')
    except FileExistsError:
        raise ModelBlocked('OWNER_BUSY','models写入容量正由另一任务预留；保留锁并在其完成后显式重试') from None
    with stream:
        json.dump({'pid': os.getpid(), 'peak_bytes': peak_bytes, 'created': time.time()}, stream)
    try:
        # Fixed, disjoint quotas bound concurrent writers without traversing
        # other owners' changing environment trees (or following their links).
        usage = dict(LIMITS)
        usage['models'] = tree_bytes(owner)
        if usage['models'] + peak_bytes > LIMITS['models']:
            raise OSError('models quota exceeded')
        # Other owners cannot exceed their fixed disjoint partitions; no borrowing.
        if any(usage[name] > limit for name, limit in LIMITS.items()):
            raise OSError('existing owner allocation exceeded')
        if sum(usage.values()) + peak_bytes > 700_000_000_000:
            raise OSError('global quota exceeded')
        if shutil.disk_usage(root).free < peak_bytes + 5_000_000_000:
            raise OSError('insufficient free disk reserve')
        yield usage
    finally:
        lock.unlink()
