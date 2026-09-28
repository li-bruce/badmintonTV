"""Exclusive owner reservation; never deletes user media or stale locks."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from .timeline import RenderError, require


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def directory_bytes(root):
    total = 0
    if not root.exists():
        return 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
        for name in files:
            p = Path(parent) / name
            if not p.is_symlink():
                try:
                    # lstat also handles WSL-created symlink/reparse entries on NTFS.
                    # Targets belong to their recorded owner; do not follow outside this tree.
                    total += p.lstat().st_size
                except FileNotFoundError:
                    pass  # another owner may have atomically renamed its own temporary
    return total


def sha256(path, check=None):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            if check:
                check()
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".partial")
    with temp.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


@contextmanager
def reservation(root, job_id, peak_bytes, owner_limit=40_000_000_000):
    owner = root / "render"
    require(owner.resolve() == root.resolve() / "render", "render owner root must not redirect", "unsafe_path")
    owner.mkdir(parents=True, exist_ok=True)
    lock = owner / ".render.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RenderError("render_busy", "render owner lock exists; active job or interrupted job requires inspection", "blocked")
    try:
        used = directory_bytes(owner)
        global_used = directory_bytes(root)
        free = shutil.disk_usage(root).free
        require(used + peak_bytes <= owner_limit, "render owner quota exceeded", "quota_exceeded")
        require(global_used + peak_bytes <= 700_000_000_000, "global storage limit exceeded", "quota_exceeded")
        # The independent allocation envelope includes WSL-native environments
        # that cannot be measured here. It is a logical upper bound, not an
        # active disk reservation, and must not be added to global_used again.
        other_owner_ceiling = 610_000_000_000
        require(used + peak_bytes + other_owner_ceiling <= 700_000_000_000, "allocated owner ceilings exceed hard limit", "quota_exceeded")
        # No shared active-reservation ledger exists yet. Fixed owner quotas do
        # not consume free space; only this job's additional peak and margin do.
        require(free >= peak_bytes + 256_000_000, "insufficient physical free space for render peak and safety margin", "disk_full")
        ledger = dict(schema_version="1.0", pid=os.getpid(), job_id=job_id, created_at=utcnow(),
                      reserved_bytes=peak_bytes, owner_used_bytes=used, global_used_bytes=global_used,
                      physical_free_bytes=free, other_owner_allocation_ceiling_bytes=other_owner_ceiling,
                      other_active_reserved_bytes=None, physical_safety_margin_bytes=256_000_000)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            json.dump(ledger, stream)
            stream.flush()
            os.fsync(stream.fileno())
        yield ledger
    finally:
        if fd is not None:
            os.close(fd)
        lock.unlink(missing_ok=True)
