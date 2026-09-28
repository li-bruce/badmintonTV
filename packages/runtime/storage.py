"""Shared-root path validation and conservative atomic capacity reservations."""

from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from pathlib import Path, PurePosixPath

from .queue import Queue


DEFAULT_QUOTAS = {
    "data": 300_000_000_000, "platform": 60_000_000_000,
    "models": 180_000_000_000, "render": 40_000_000_000,
    "runtime/common": 15_000_000_000, "runtime/models": 35_000_000_000,
    "runtime/platform": 10_000_000_000, "runtime/library": 5_000_000_000,
    "runtime/render": 5_000_000_000,
}
GLOBAL_QUOTA = 700_000_000_000


def resolve_relative_path(storage_root, relative_path, must_exist=False):
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path or ":" in relative_path or "\x00" in relative_path:
        raise ValueError("relative_path must be a nonempty POSIX relative path")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.split("/")):
        raise ValueError("absolute paths and dot segments are forbidden")
    # Reject Windows device names, trailing dot/space normalization and ADS on all hosts.
    for part in path.parts:
        if part.endswith((".", " ")) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
            raise ValueError("unsafe path component")
    root = Path(storage_root).resolve()
    result = (root / Path(*path.parts)).resolve(strict=must_exist)
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes storage root") from exc
    return result


def directory_bytes(root, exclude_roots=()):
    root = Path(root)
    try:
        root.stat()
    except FileNotFoundError:
        return 0
    excluded = {os.path.normcase(os.path.abspath(path)) for path in exclude_roots}
    def fail_walk(error):
        raise error
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail_walk):
        dirs[:] = [name for name in dirs if os.path.normcase(os.path.abspath(Path(directory) / name)) not in excluded
                   and not (Path(directory) / name).is_symlink()
                   and not (hasattr(Path(directory) / name, "is_junction") and (Path(directory) / name).is_junction())]
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                try:
                    # WSL symlink reparse points can be unreadable when followed by Windows.
                    # Count their on-disk metadata instead of traversing into another owner.
                    total += path.stat(follow_symlinks=False).st_size
                except FileNotFoundError:
                    continue
    return total


class CapacityLedger:
    def __init__(self, db_path, storage_root, quotas=None):
        self.queue = Queue(db_path)
        self.storage_root = Path(storage_root).resolve()
        self.quotas = dict(DEFAULT_QUOTAS if quotas is None else quotas)
        if any(not isinstance(value, int) or value < 0 for value in self.quotas.values()):
            raise ValueError("quotas must contain nonnegative integer byte limits")
        for owner in self.quotas:
            resolve_relative_path(self.storage_root, owner)

    def _measure_owners(self, strict_owner=None):
        measured = {}
        for owner, quota in self.quotas.items():
            try:
                used = directory_bytes(resolve_relative_path(self.storage_root, owner))
                measured[owner] = {"used_bytes": used, "measured": True, "quota_bytes": quota}
            except OSError as exc:
                if owner == strict_owner:
                    raise
                # Unknown usage consumes this owner's entire fixed allocation, once.
                measured[owner] = {"used_bytes": quota, "measured": False, "quota_bytes": quota,
                                   "measurement_error": type(exc).__name__}
        return measured

    def usage(self):
        with self.queue.connection() as db:
            reserved = dict(db.execute("SELECT owner,SUM(peak_bytes) FROM reservations WHERE released_at IS NULL GROUP BY owner"))
        return {owner: {**data, "reserved_bytes": reserved.get(owner, 0)} for owner, data in self._measure_owners().items()}

    def reserve(self, owner, peak_bytes, job_id=None):
        if owner not in self.quotas:
            raise ValueError("owner has no allocated quota")
        if not isinstance(peak_bytes, int) or isinstance(peak_bytes, bool) or peak_bytes < 0:
            raise ValueError("peak_bytes must be a nonnegative integer")
        if not self.storage_root.exists():
            raise ValueError("storage root must exist before capacity checks")
        with self.queue.connection(write=True) as db:
            reserved = db.execute("SELECT COALESCE(SUM(peak_bytes),0) FROM reservations WHERE released_at IS NULL AND owner=?", (owner,)).fetchone()[0]
            measured = self._measure_owners(strict_owner=owner)
            used = measured[owner]["used_bytes"]
            if used + reserved + peak_bytes > self.quotas[owner]:
                raise ValueError(f"owner quota exceeded: {owner}, used={used}, reserved={reserved}, requested={peak_bytes}")
            all_reserved = db.execute("SELECT COALESCE(SUM(peak_bytes),0) FROM reservations WHERE released_at IS NULL").fetchone()[0]
            owner_reservations = dict(db.execute("SELECT owner,SUM(peak_bytes) FROM reservations WHERE released_at IS NULL GROUP BY owner"))
            controlled_roots = [resolve_relative_path(self.storage_root, item) for item in self.quotas]
            outside_owners = directory_bytes(self.storage_root, exclude_roots=controlled_roots)
            logical_usage = outside_owners + sum(data["used_bytes"] + (owner_reservations.get(item, 0) if data["measured"] else 0)
                                                for item, data in measured.items())
            if logical_usage + peak_bytes > GLOBAL_QUOTA:
                raise ValueError("700 GB global hard limit would be exceeded")
            # Fallback full quotas are a logical bound, not new disk writes.
            if shutil.disk_usage(self.storage_root).free < all_reserved + peak_bytes:
                raise ValueError("insufficient physical free space for peak reservation")
            reservation_id = "reservation-" + uuid.uuid4().hex
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,NULL)", (reservation_id, owner, peak_bytes, job_id, time.time()))
            return reservation_id

    def release(self, reservation_id):
        with self.queue.connection(write=True) as db:
            db.execute("UPDATE reservations SET released_at=? WHERE reservation_id=? AND released_at IS NULL", (time.time(), reservation_id))
