"""Finite parallel HTTP ranges committed to one sequential resumable prefix.

The caller must verify immutable source identity and reserve disk capacity first,
then verify the final complete SHA256 before publication. This helper never
publishes weights, retries restrictions, or writes concurrent fragment files.
Its response-body buffers total at most 32 MiB (HTTP/runtime overhead excluded).
"""
from concurrent.futures import ThreadPoolExecutor
import math
import os
from pathlib import Path
import time
import urllib.request
from urllib.parse import urlsplit

MAX_CONCURRENCY = 4
MAX_RANGE_BYTES = 8_388_608
MAX_BUFFER_BYTES = MAX_CONCURRENCY * MAX_RANGE_BYTES
READ_BYTES = 65_536


def _positive_seconds(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + " must be finite and positive")


def _check_deadline(range_started, transfer_deadline, range_timeout):
    now = time.monotonic()
    if now >= transfer_deadline or now-range_started >= range_timeout:
        raise TimeoutError("bounded Range transfer deadline; prior committed prefix preserved")
    return now


def _read_range(url, start, end, total, *, transfer_deadline, range_timeout, request_timeout):
    began = time.monotonic()
    _check_deadline(began, transfer_deadline, range_timeout)
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    timeout = min(request_timeout, range_timeout, transfer_deadline-began)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        expected_length = end-start+1
        if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{total}":
            raise ValueError("server did not honor exact bounded Range")
        length = response.headers.get("Content-Length")
        if length is not None and (not str(length).isdecimal() or int(length) != expected_length):
            raise ValueError("unexpected Range Content-Length")
        body = bytearray(expected_length)
        view = memoryview(body)
        offset = 0
        while offset < expected_length:
            _check_deadline(began, transfer_deadline, range_timeout)
            amount = min(READ_BYTES, expected_length-offset)
            read = response.readinto(view[offset:offset+amount])
            _check_deadline(began, transfer_deadline, range_timeout)
            if type(read) is not int or read < 0 or read > amount:
                raise ValueError("invalid bounded HTTP read length")
            if read == 0:
                raise ValueError("truncated Range; current batch discarded and prior prefix preserved")
            offset += read
        # Reuse the first buffer byte for overflow detection: no second body
        # allocation or join/copy is needed. Any excess invalidates the batch.
        _check_deadline(began, transfer_deadline, range_timeout)
        extra = response.readinto(view[:1])
        _check_deadline(began, transfer_deadline, range_timeout)
        if type(extra) is not int or extra != 0:
            raise ValueError("Range body exceeds requested byte interval")
        view.release()
        return body


def append_ranges(url, partial_path, expected_total, *, concurrency=4, chunk_bytes=MAX_RANGE_BYTES,
                  pause_file=None, range_timeout_seconds=180, total_timeout_seconds=7200,
                  request_timeout_seconds=30):
    """Append ordered validated batches and return complete/paused byte stats.

    A pause marker is observed before each batch, after a fully validated batch
    has been committed and fsynced. Exceptions leave preceding committed bytes
    intact. A disk-write failure can leave a shorter prefix of a validated batch;
    the caller may resume from that actual byte offset and must verify full SHA.
    No authentication headers or source URL are returned in statistics.
    """
    if type(expected_total) is not int or expected_total <= 0:
        raise ValueError("expected_total must be a positive exact byte count")
    if type(concurrency) is not int or not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError("concurrency must be 1..4")
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= MAX_RANGE_BYTES:
        raise ValueError("chunk_bytes must be 1..8 MiB")
    for name, value in (("range_timeout_seconds", range_timeout_seconds), ("total_timeout_seconds", total_timeout_seconds),
                        ("request_timeout_seconds", request_timeout_seconds)):
        _positive_seconds(value, name)
    source = urlsplit(url)
    if source.scheme != "https" or not source.hostname or source.username is not None or source.password is not None or source.fragment:
        raise ValueError("A normal public HTTPS source without embedded credentials is required")
    path = Path(partial_path)
    if path.is_symlink() or not path.parent.is_dir():
        raise ValueError("Partial must have an existing local parent and must not be a symlink")
    pause = Path(pause_file) if pause_file is not None else None
    count = path.stat().st_size if path.exists() else 0
    if count > expected_total:
        raise ValueError("oversize partial preserved")
    started = time.monotonic()
    deadline = started+total_timeout_seconds
    stats = {"status": "complete", "start_offset": count, "final_offset": count, "bytes_appended": 0,
             "ranges_completed": 0, "batches_completed": 0, "concurrency": concurrency,
             "maximum_range_bytes": chunk_bytes, "peak_body_buffer_bytes": 0,
             "verification": "range transport only; final whole-file SHA256 is caller responsibility"}
    if count == expected_total:
        stats["elapsed_seconds"] = time.monotonic()-started
        return stats
    if pause is not None and pause.exists():
        stats.update(status="paused", elapsed_seconds=time.monotonic()-started)
        return stats
    with path.open("ab" if path.exists() else "xb") as out, ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="btv-range") as pool:
        while count < expected_total:
            if pause is not None and pause.exists():
                stats["status"] = "paused"
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("bounded total transfer deadline; prior committed prefix preserved")
            ranges = [(position, min(expected_total-1, position+chunk_bytes-1))
                      for position in range(count, min(expected_total, count+concurrency*chunk_bytes), chunk_bytes)]
            stats["peak_body_buffer_bytes"] = max(stats["peak_body_buffer_bytes"], sum(end-start+1 for start, end in ranges))
            futures = [pool.submit(_read_range, url, start, end, expected_total, transfer_deadline=deadline,
                                   range_timeout=range_timeout_seconds, request_timeout=request_timeout_seconds)
                       for start, end in ranges]
            blocks = []
            try:
                # Completion can be out of order; no bytes are committed until
                # every response in this batch passes exact length validation.
                for future in futures:
                    blocks.append(future.result())
                if time.monotonic() >= deadline:
                    raise TimeoutError("bounded total transfer deadline; validated batch not committed")
                if os.fstat(out.fileno()).st_size != count:
                    raise ValueError("partial changed concurrently; no batch appended")
                for (start, end), block in zip(ranges, blocks):
                    if start != count or len(block) != end-start+1:
                        raise ValueError("validated Range ordering or length mismatch")
                    view = memoryview(block)
                    offset = 0
                    while offset < len(view):
                        written = out.write(view[offset:])
                        if type(written) is not int or written <= 0:
                            raise OSError("incomplete append; actual prefix retained")
                        offset += written
                        count += written
                    view.release()
                out.flush()
                os.fsync(out.fileno())
                stats.update(final_offset=count, bytes_appended=count-stats["start_offset"])
                stats["ranges_completed"] += len(ranges)
                stats["batches_completed"] += 1
            finally:
                for pending in futures:
                    pending.cancel()
                # Release all result references before allocating another batch.
                blocks.clear()
                futures.clear()
                if "future" in locals():
                    del future
                if "pending" in locals():
                    del pending
                if "block" in locals():
                    del block
    stats["elapsed_seconds"] = time.monotonic()-started
    return stats
