"""Trusted encoder selection and read-only verification of the shared GPU lease."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import time

from .timeline import RenderError, require


def verify_gpu_lease(db_path, lease_id, job_id, attempt_id):
    """Never create/claim a lease here: the platform worker owns its lifecycle."""
    if not db_path or not lease_id or not Path(db_path).is_file():
        raise RenderError("GPU_LEASE_REQUIRED", "NVENC requires the shared worker GPU lease", "blocked")
    try:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("""SELECT r.*, w.expires_at AS window_expires_at,
                j.status AS job_status, j.worker_id AS job_worker_id,
                j.attempt AS job_attempt, j.lease_expires_at AS job_lease_expires_at
                FROM resource_leases r JOIN gpu_windows w USING(window_id)
                JOIN jobs j USING(job_id) WHERE r.lease_id=?""", (lease_id,)).fetchone()
            now = time.time()
            valid = row is not None and all((
                row["status"] == "active", row["resource"] == "gpu0",
                row["model_id"] == "render-nvenc", row["job_id"] == job_id,
                attempt_id == f"attempt-{row['attempt']}", row["job_status"] == "running",
                row["worker_id"] == row["job_worker_id"], row["attempt"] == row["job_attempt"],
                row["expires_at"] > now, row["window_expires_at"] > now,
                (row["job_lease_expires_at"] or 0) > now,
            ))
            if not valid:
                raise RenderError("GPU_LEASE_REQUIRED", "GPU lease does not cover this running render attempt", "blocked")
            return {key: row[key] for key in ("lease_id", "window_id", "model_id", "worker_id")}
    except (sqlite3.Error, OSError) as exc:
        raise RenderError("GPU_LEASE_REQUIRED", f"Cannot verify shared GPU lease: {exc}", "blocked") from exc


def encoder_args(backend, preset):
    require(backend in ("cpu", "nvenc"), "invalid effective backend")
    common = ["-maxrate", preset["maxrate"], "-bufsize", preset["bufsize"], "-pix_fmt", "yuv420p"]
    if backend == "cpu":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", *common]
    # CQ and CRF numbers are NOT equivalent quality scales. Benchmark separately.
    return ["-c:v", "h264_nvenc", "-gpu", "0", "-preset", "p5", "-tune", "hq", "-rc", "vbr",
            "-cq", "21", "-b:v", preset["maxrate"], *common]


def mp4_faststart(path):
    """Inspect actual top-level box ordering, not merely the requested movflags."""
    boxes = []
    with Path(path).open("rb") as stream:
        end = Path(path).stat().st_size
        while stream.tell() + 8 <= end:
            offset = stream.tell()
            size, name = struct.unpack(">I4s", stream.read(8))
            header = 8
            if size == 1:
                if stream.tell() + 8 > end:
                    return False
                size = struct.unpack(">Q", stream.read(8))[0]
                header = 16
            elif size == 0:
                size = end - offset
            if size < header or offset + size > end:
                return False
            boxes.append(name)
            stream.seek(offset + size)
        if stream.tell() != end:
            return False
    return b"moov" in boxes and b"mdat" in boxes and boxes.index(b"moov") < boxes.index(b"mdat")
