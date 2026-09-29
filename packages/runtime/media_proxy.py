"""Bounded CPU preview derivatives; source PTS remain the annotation authority.

The private index subprocess streams ffprobe records into SQLite. It is launched
through WorkerContext.execute, so it and ffprobe share the worker's process tree.
No video-sized JSON object or frame array is constructed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from .storage import CapacityLedger, resolve_owner_path, resolve_relative_path

MAX_WINDOW_MS = 120_000
MAX_SOURCE_MS = 14_400_000
MAX_SOURCE_BYTES = 20_000_000_000
MAX_SOURCE_PIXELS = 3840 * 2160
MAX_SOURCE_FRAMES = 1_728_000
MAX_WINDOW_FRAMES = 14_400
MAX_INDEX_BYTES = 256_000_000
MAX_PROXY_BYTES = 160_000_000
MAX_IMAGE_BYTES = 32_000_000
MAX_THUMBNAILS = 12
MAX_PAGE = 1000


def _integer(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _options(payload):
    asset = payload.get("asset")
    if not isinstance(asset, dict):
        raise ValueError("media job requires an asset snapshot")
    duration = _integer(asset.get("duration_ms"), "source duration_ms", 1, MAX_SOURCE_MS)
    _integer(asset.get("size_bytes"), "source size_bytes", 1, MAX_SOURCE_BYTES)
    width = _integer(asset.get("width"), "source width", 1, 8192)
    height = _integer(asset.get("height"), "source height", 1, 8192)
    if width * height > MAX_SOURCE_PIXELS:
        raise ValueError("source pixel limit exceeded")
    start = _integer(payload.get("start_ms", 0), "start_ms", 0, duration - 1)
    end = _integer(payload.get("end_ms", min(duration, start + MAX_WINDOW_MS)), "end_ms", start + 1, duration)
    if end - start > MAX_WINDOW_MS:
        raise ValueError("preview window exceeds 120 seconds")
    max_height = payload.get("max_height", 720)
    if type(max_height) is not int or max_height not in (720, 1080):
        raise ValueError("max_height must be 720 or 1080")
    max_fps = payload.get("max_fps")
    if max_fps is not None and (type(max_fps) is not int or max_fps != 30):
        raise ValueError("max_fps must be null or 30")
    return asset, start, end, max_height, max_fps


def estimate_peak_bytes(payload, operation="media_proxy"):
    """Extra media reservation; the worker's 128 MB protocol reserve is separate."""
    _options(payload)
    if operation == "exact_frame":
        return 2 * MAX_IMAGE_BYTES + 8_000_000
    if operation != "media_proxy":
        raise ValueError("unknown media operation")
    # Source index + rollback journal; MP4 + muxer headroom; bounded JPEG strip.
    return 2 * MAX_INDEX_BYTES + 2 * MAX_PROXY_BYTES + MAX_IMAGE_BYTES + 16_000_000


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _connect(index_path, readonly=False):
    if readonly:
        db = sqlite3.connect(Path(index_path).resolve().as_uri() + "?mode=ro", uri=True, factory=_ClosingConnection)
    else:
        db = sqlite3.connect(index_path, factory=_ClosingConnection)
    db.row_factory = sqlite3.Row
    return db


def _metadata(db):
    return {row["key"]: json.loads(row["value"]) for row in db.execute("SELECT key,value FROM metadata")}


def _set_metadata(db, values):
    db.executemany("INSERT OR REPLACE INTO metadata VALUES (?,?)", [(key, json.dumps(value, ensure_ascii=False)) for key, value in values.items()])


def _page_arguments(offset_frame, limit, at_ms):
    _integer(offset_frame, "offset_frame", 0)
    _integer(limit, "limit", 1, MAX_PAGE)
    if at_ms is not None and (isinstance(at_ms, bool) or not isinstance(at_ms, (int, float)) or not math.isfinite(at_ms) or at_ms < 0):
        raise ValueError("at_ms must be a finite nonnegative number")


def read_frame_map(index_path, offset_frame=0, limit=1000, at_ms=None):
    """Page displayed proxy frames; at_ms refers to proxy playback time."""
    _page_arguments(offset_frame, limit, at_ms)
    with _connect(index_path, True) as db:
        if at_ms is not None:
            row = db.execute("SELECT proxy_frame_index FROM proxy_frames WHERE proxy_pts_ms<=? ORDER BY proxy_pts_ms DESC LIMIT 1", (at_ms,)).fetchone()
            offset_frame = row[0] if row else 0
        rows = db.execute("SELECT * FROM proxy_frames WHERE proxy_frame_index>=? ORDER BY proxy_frame_index LIMIT ?", (offset_frame, limit)).fetchall()
        total = db.execute("SELECT COUNT(*) FROM proxy_frames").fetchone()[0]
    return {"frames": [dict(row) for row in rows], "total": total, "offset_frame": offset_frame, "limit": limit}


def read_source_frames(index_path, offset_frame=0, limit=1000, at_ms=None):
    """Page *every* source frame. Indices are absolute in the full source."""
    _page_arguments(offset_frame, limit, at_ms)
    with _connect(index_path, True) as db:
        if at_ms is not None:
            row = db.execute("SELECT source_frame_index FROM source_frames WHERE source_pts_ms<=? ORDER BY source_pts_ms DESC LIMIT 1", (at_ms,)).fetchone()
            offset_frame = row[0] if row else 0
        rows = db.execute("SELECT * FROM source_frames WHERE source_frame_index>=? ORDER BY source_frame_index LIMIT ?", (offset_frame, limit)).fetchall()
        total = db.execute("SELECT COUNT(*) FROM source_frames").fetchone()[0]
    return {"source_frames": [dict(row) for row in rows], "total": total, "offset_frame": offset_frame, "limit": limit, "source_index_scope": "full_source"}


def _binary(name):
    from .worker import JobBlocked
    binary = os.environ.get("BTV_" + name.upper()) or shutil.which(name)
    if not binary:
        raise JobBlocked("not_installed", f"{name} is not installed")
    return binary


def _run(context, argv, stage, **kwargs):
    context.check()
    code, output, error = context.execute(argv, stage, **kwargs)
    if code:
        raise ValueError(f"{stage} failed with exit {code}: {error[-3000:]}")
    return output


def _hash(path, context):
    digest = hashlib.sha256()
    before = path.stat()
    def identity(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    read = 0
    last_log = 0
    with path.open("rb") as handle:
        if identity(os.fstat(handle.fileno())) != identity(before):
            raise ValueError("source changed before hashing")
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            context.check()
            read += len(chunk)
            if read > MAX_SOURCE_BYTES:
                raise ValueError("source exceeds hard byte limit")
            digest.update(chunk)
            if time.monotonic() - last_log > 0.5:
                context.log("progress", stage="media_hash", current=read, total=before.st_size, unit="bytes")
                last_log = time.monotonic()
        if identity(os.fstat(handle.fileno())) != identity(before):
            raise ValueError("source changed during hashing")
    if identity(path.stat()) != identity(before):
        raise ValueError("source changed during hashing")
    return digest.hexdigest(), read, identity(before)


def _source(context, asset):
    from packages.contracts import assert_production_allowed
    assert_production_allowed(asset, storage_root=context.storage_root)
    source = resolve_relative_path(context.storage_root, asset["relative_path"], must_exist=True)
    if not source.is_file() or source.stat().st_size != asset["size_bytes"]:
        raise ValueError("source bytes differ from asset size_bytes")
    digest, size, identity = _hash(source, context)
    if digest != asset["sha256"] or size != asset["size_bytes"]:
        raise ValueError("source SHA-256 differs from asset snapshot")
    # Re-read the current registry against bytes just verified, including files
    # copied/renamed from training locations while this job was queued.
    assert_production_allowed({**asset, "sha256": digest}, storage_root=context.storage_root)
    return source, identity


def _output(context, exchange_dir, name):
    relative = (Path(exchange_dir) / name).relative_to(context.storage_root).as_posix()
    path = resolve_owner_path(context.storage_root, relative, "platform")
    if path.exists():
        raise ValueError("attempt output already exists; retry must use a fresh attempt directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _artifact(path, context, kind):
    digest, size, _ = _hash(path, context)
    return {"artifact_id": "media-" + digest[:24], "kind": kind,
            "relative_path": path.relative_to(context.storage_root).as_posix(), "sha256": digest,
            "size_bytes": size, "created_at": datetime.now(timezone.utc).isoformat(), "producer": "platform.media_proxy"}


def _result(context, name, value, artifacts):
    return {"schema_version": "1.0", "job_id": context.job["job_id"], "attempt_id": f"attempt-{context.job['attempt']}",
            "status": "succeeded", name: value, "artifacts": artifacts, "events": [], "error": None}


def _check_unchanged(source, identity):
    stat = source.stat()
    if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != identity:
        raise ValueError("source changed during media job")


def _probe(context, source):
    raw = _run(context, [_binary("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format", "-of", "json", str(source)], "media_probe", timeout=120, capture_limit=1_000_000)
    media = json.loads(raw)
    stream = next(iter(media.get("streams", [])), None)
    if stream is None:
        raise ValueError("source has no video stream")
    width, height = int(stream["width"]), int(stream["height"])
    if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
        raise ValueError("probed source pixel limit exceeded")
    duration = float(stream.get("duration") or media.get("format", {}).get("duration") or 0) * 1000
    if not math.isfinite(duration) or not 0 < duration <= MAX_SOURCE_MS:
        raise ValueError("probed source duration exceeds hard limit or is unknown")
    time_base = Fraction(stream["time_base"])
    if not 0 < time_base <= 1:
        raise ValueError("unsupported source time base")
    return stream, duration


def _index_command(context, source, index_path, stream, duration):
    config = {"storage_root": str(context.storage_root), "source_relative_path": source.relative_to(context.storage_root).as_posix(),
              "index_relative_path": index_path.relative_to(context.storage_root).as_posix(), "time_base": stream["time_base"],
              "duration_ms": duration, "job_id": context.job["job_id"]}
    request = _output(context, index_path.parent, index_path.stem + ".index-request.json")
    request.write_text(json.dumps(config), encoding="utf-8")
    _run(context, [sys.executable, "-m", "packages.runtime.media_proxy", "_index", "--request", str(request)],
         "source_pts_index", parse_progress=True, timeout=7200)


def _stream_index(config):
    root = Path(config["storage_root"])
    source = resolve_relative_path(root, config["source_relative_path"], must_exist=True)
    output = resolve_owner_path(root, config["index_relative_path"], "platform")
    if output.exists():
        raise ValueError("index output already exists")
    tb = Fraction(config["time_base"])
    db = _connect(output)
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA page_size=4096")
    db.execute(f"PRAGMA max_page_count={MAX_INDEX_BYTES // 4096}")
    db.executescript("""
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE source_frames(source_frame_index INTEGER PRIMARY KEY,source_pts INTEGER NOT NULL,
            source_pts_ms REAL NOT NULL,source_end_ms REAL NOT NULL,key_frame INTEGER NOT NULL);
        CREATE UNIQUE INDEX source_pts_lookup ON source_frames(source_pts_ms);
        CREATE TABLE proxy_frames(proxy_frame_index INTEGER PRIMARY KEY,proxy_pts_ms REAL NOT NULL,
            source_frame_index INTEGER NOT NULL,source_pts INTEGER NOT NULL,source_pts_ms REAL NOT NULL,
            coverage_start_ms REAL NOT NULL,coverage_end_ms REAL NOT NULL);
        CREATE UNIQUE INDEX proxy_pts_lookup ON proxy_frames(proxy_pts_ms);
    """)
    argv = [_binary("ffprobe"), "-v", "error", "-threads", "1", "-select_streams", "v:0", "-show_frames",
            "-show_entries", "frame=pts,best_effort_timestamp,duration,key_frame,width,height", "-of", "compact=p=0:nk=0", str(source)]
    # Inherits the worker's JobObject/process group. Do not detach this child.
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    count, origin, last_pts, last_ms, duration_ticks, seq = 0, None, None, None, None, 0
    try:
        for raw in iter(lambda: process.stdout.readline(65537), b""):
            if len(raw) > 65536:
                raise ValueError("ffprobe frame line exceeds bound")
            values = dict(part.split("=", 1) for part in raw.decode("utf-8").strip().split("|") if "=" in part)
            if "pts" not in values:
                continue
            if count >= MAX_SOURCE_FRAMES:
                raise ValueError("source frame count exceeds hard bound")
            if int(values.get("width", 0)) * int(values.get("height", 0)) > MAX_SOURCE_PIXELS:
                raise ValueError("decoded frame pixel bound exceeded")
            pts = int(values["pts"])
            origin = pts if origin is None else origin
            ms = float((pts - origin) * tb * 1000)
            if last_pts is not None and pts <= last_pts:
                raise ValueError("source PTS must be strictly increasing; refusing ambiguous frame map")
            if not 0 <= ms <= MAX_SOURCE_MS:
                raise ValueError("source PTS duration exceeds hard bound")
            if count:
                db.execute("UPDATE source_frames SET source_end_ms=? WHERE source_frame_index=?", (ms, count - 1))
            duration_ticks = int(values.get("duration", "0")) if values.get("duration", "0") != "N/A" else 0
            db.execute("INSERT INTO source_frames VALUES(?,?,?,?,?)", (count, pts, ms, ms, int(values.get("key_frame", 0))))
            count += 1
            last_pts, last_ms = pts, ms
            if count % 256 == 0:
                db.commit()
                seq += 1
                print(json.dumps({"schema_version": "1.0", "job_id": config["job_id"], "seq": seq, "event": "progress", "stage": "source_pts_index", "current": count, "unit": "frames", "message": "Decoded source PTS indexed"}), flush=True)
        if process.wait() != 0 or not count:
            raise ValueError("ffprobe failed or decoded no timestamped frames")
        tail = float(duration_ticks * tb * 1000) if duration_ticks and duration_ticks > 0 else max(0, float(config["duration_ms"]) - last_ms)
        if tail <= 0:
            raise ValueError("last source frame duration unavailable")
        source_end = last_ms + tail
        if source_end > MAX_SOURCE_MS + 1:
            raise ValueError("source end exceeds hard duration bound")
        db.execute("UPDATE source_frames SET source_end_ms=? WHERE source_frame_index=?", (source_end, count - 1))
        _set_metadata(db, {"source_time_base": str(tb), "source_origin_pts": origin, "source_frame_count": count, "source_end_ms": source_end})
        db.commit()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        db.close()


def _select_frames(index_path, start, end, max_fps):
    with _connect(index_path) as db:
        meta = _metadata(db)
        if end > meta["source_end_ms"] + 1:
            raise ValueError("requested window extends beyond decoded source frames")
        end = min(float(end), meta["source_end_ms"])
        first = db.execute("SELECT * FROM source_frames WHERE source_pts_ms<=? ORDER BY source_pts_ms DESC LIMIT 1", (start,)).fetchone()
        if not first:
            raise ValueError("requested window has no source frame")
        actual_start = first["source_pts_ms"]
        previous = None
        count = 0
        # A cursor keeps the full-source index off the Python heap.
        for row in db.execute("SELECT * FROM source_frames WHERE source_frame_index>=? AND source_pts_ms<? ORDER BY source_frame_index", (first["source_frame_index"], end)):
            ms = row["source_pts_ms"]
            if previous is not None and max_fps and ms - previous < 1000 / max_fps - 0.000001:
                continue
            if count:
                db.execute("UPDATE proxy_frames SET coverage_end_ms=? WHERE proxy_frame_index=?", (ms, count - 1))
            db.execute("INSERT INTO proxy_frames VALUES(?,?,?,?,?,?,?)", (count, ms - actual_start, row["source_frame_index"], row["source_pts"], ms, ms, end))
            count += 1
            if count > MAX_WINDOW_FRAMES:
                raise ValueError("preview window frame count exceeds hard bound")
            previous = ms
        last_source = db.execute("SELECT MAX(source_frame_index) FROM source_frames WHERE source_pts_ms<?", (end,)).fetchone()[0]
        _set_metadata(db, {"window_start_ms": actual_start, "window_end_ms": end, "requested_start_ms": start, "proxy_frame_count": count})
        db.commit()
    return first["source_frame_index"], last_source + 1, actual_start, end, count


def create_proxy(context, exchange_dir):
    payload = context.job["payload"]
    asset, start, end, max_height, max_fps = _options(payload)
    source, identity = _source(context, asset)
    ledger = CapacityLedger(context.queue.db_path, context.storage_root)
    reservation = ledger.reserve("platform", estimate_peak_bytes(payload), job_id=context.job["job_id"])
    try:
        stream, duration = _probe(context, source)
        index_path = _output(context, exchange_dir, "frame-index.sqlite3")
        _index_command(context, source, index_path, stream, duration)
        first, stop, actual_start, actual_end, count = _select_frames(index_path, start, end, max_fps)
        proxy = _output(context, exchange_dir, "preview.mp4")
        thumbnail = _output(context, exchange_dir, "thumbnails.jpg")
        ratio = min(1, max_height / int(stream["height"]), (1920 if max_height == 1080 else 1280) / int(stream["width"]))
        width, height = max(2, math.floor(int(stream["width"]) * ratio / 2) * 2), max(2, math.floor(int(stream["height"]) * ratio / 2) * 2)
        vf = f"trim=start_frame={first}:end_frame={stop},setpts=PTS-STARTPTS"
        if max_fps:
            vf += ",select='isnan(prev_selected_t)+gte(t-prev_selected_t,0.0333333323333333)'"
        vf += f",scale={width}:{height}:flags=lanczos,format=yuv420p"
        context.log("progress", stage="proxy_encode", current=0, total=count, unit="frames", message="CPU H.264 proxy encoding")
        _run(context, [_binary("ffmpeg"), "-nostdin", "-v", "error", "-noautorotate", "-threads", "2", "-i", str(source),
              "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf, "-fps_mode", "vfr", "-enc_time_base", "1:1000000",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "8M", "-bufsize", "16M", "-g", "30", "-keyint_min", "1",
              "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*1)", "-bf", "0", "-threads", "2", "-movflags", "+faststart", "-video_track_timescale", "1000000",
              "-t", f"{(actual_end-actual_start)/1000:.9f}", "-fs", str(MAX_PROXY_BYTES - 16_000_000), "-n", str(proxy)], "proxy_encode", timeout=7200)
        if not proxy.exists() or not 0 < proxy.stat().st_size <= MAX_PROXY_BYTES:
            raise ValueError("proxy byte limit exceeded or output missing")
        # Verify actual encoded PTS with another streaming index, then replace the
        # expected proxy clock with measured muxed timestamps (never FPS arithmetic).
        proxy_stream, proxy_duration = _probe(context, proxy)
        measured_index = _output(context, exchange_dir, "encoded-index.sqlite3")
        _index_command(context, proxy, measured_index, proxy_stream, proxy_duration)
        with _connect(index_path) as db, _connect(measured_index, True) as measured:
            if measured.execute("SELECT COUNT(*) FROM source_frames").fetchone()[0] != count:
                raise ValueError("encoded frame count differs from source selection; proxy is incomplete")
            for observed in measured.execute("SELECT * FROM source_frames ORDER BY source_frame_index"):
                context.check()
                expected = db.execute("SELECT * FROM proxy_frames WHERE proxy_frame_index=?", (observed["source_frame_index"],)).fetchone()
                if abs(observed["source_pts_ms"] - expected["proxy_pts_ms"]) > 0.01:
                    raise ValueError("encoded proxy PTS differs from selected source PTS")
                db.execute("UPDATE proxy_frames SET proxy_pts_ms=? WHERE proxy_frame_index=?", (observed["source_pts_ms"], observed["source_frame_index"]))
            _set_metadata(db, {"source_asset_id": asset["asset_id"], "source_sha256": asset["sha256"], "usage_scope": asset.get("usage_scope", "general"), "source_width": int(stream["width"]), "source_height": int(stream["height"])})
            db.commit()
            metadata = _metadata(db)
            indices = sorted({round(index * (count - 1) / max(1, min(MAX_THUMBNAILS, count) - 1)) for index in range(min(MAX_THUMBNAILS, count))})
            thumbs = []
            thumb_height = max(2, int(height * 160 / width) // 2 * 2)
            for tile, number in enumerate(indices):
                frame = dict(db.execute("SELECT * FROM proxy_frames WHERE proxy_frame_index=?", (number,)).fetchone())
                thumbs.append({"source_frame_index": frame["source_frame_index"], "source_pts_ms": frame["source_pts_ms"], "proxy_pts_ms": frame["proxy_pts_ms"], "x": tile * 160, "y": 0, "width": 160, "height": thumb_height})
        selection = "+".join(f"eq(n,{number})" for number in indices)
        _run(context, [_binary("ffmpeg"), "-nostdin", "-v", "error", "-i", str(proxy), "-an", "-vf", f"select='{selection}',scale=160:{thumb_height},tile={len(indices)}x1:nb_frames={len(indices)}",
              "-frames:v", "1", "-threads", "1", "-q:v", "3", "-fs", str(MAX_IMAGE_BYTES - 1_000_000), "-n", str(thumbnail)], "thumbnail_strip", timeout=300)
        if not thumbnail.exists() or not 0 < thumbnail.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError("thumbnail output exceeds byte bound or is missing")
        _check_unchanged(source, identity)
        context.check()
        preview = {"schema_version": "1.0", **{key: metadata[key] for key in ("source_asset_id", "source_sha256", "usage_scope", "source_time_base", "source_origin_pts", "source_frame_count", "proxy_frame_count", "window_start_ms", "window_end_ms", "requested_start_ms")},
                   "source_index_scope": "full_source", "relative_path": proxy.relative_to(context.storage_root).as_posix(),
                   "index_relative_path": index_path.relative_to(context.storage_root).as_posix(), "thumbnail_relative_path": thumbnail.relative_to(context.storage_root).as_posix(),
                   "thumbnail_count": len(thumbs), "thumbs": thumbs, "width": width, "height": height, "max_height": max_height, "max_fps": max_fps,
                   "has_audio": False, "codec": "h264", "pixel_format": "yuv420p", "peak_reserved_bytes": estimate_peak_bytes(payload)}
        context.log("progress", stage="proxy_encode", current=count, total=count, unit="frames", message="Encoded PTS verified")
        return _result(context, "preview", preview, [_artifact(path, context, kind) for path, kind in ((proxy, "preview"), (index_path, "frame_index"), (thumbnail, "thumbnail"))])
    finally:
        ledger.release(reservation)


def exact_frame(context, exchange_dir):
    payload = context.job["payload"]
    asset, *_ = _options(payload)
    source, identity = _source(context, asset)
    number = _integer(payload.get("source_frame_index"), "source_frame_index", 0, MAX_SOURCE_FRAMES - 1)
    index_path = resolve_owner_path(context.storage_root, payload["index_relative_path"], "platform", must_exist=True)
    with _connect(index_path, True) as db:
        metadata = _metadata(db)
        if metadata.get("source_sha256") != asset["sha256"] or metadata.get("source_asset_id") != asset["asset_id"]:
            raise ValueError("frame index does not match source asset and hash")
        row = db.execute("SELECT * FROM source_frames WHERE source_frame_index=?", (number,)).fetchone()
        if not row:
            raise ValueError("source frame is outside the indexed video")
        row = dict(row)
    ledger = CapacityLedger(context.queue.db_path, context.storage_root)
    reservation = ledger.reserve("platform", estimate_peak_bytes(payload, "exact_frame"), job_id=context.job["job_id"])
    try:
        output = _output(context, exchange_dir, f"source-frame-{number}.jpg")
        _run(context, [_binary("ffmpeg"), "-nostdin", "-v", "error", "-noautorotate", "-threads", "2", "-i", str(source),
              "-map", "0:v:0", "-an", "-vf", f"select='eq(n,{number})'", "-frames:v", "1", "-fps_mode", "vfr", "-q:v", "2", "-threads", "1",
              "-fs", str(MAX_IMAGE_BYTES - 1_000_000), "-n", str(output)], "exact_source_frame", timeout=7200)
        if not output.exists() or not 0 < output.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError("exact frame missing or exceeds byte bound")
        _check_unchanged(source, identity)
        return _result(context, "frame", {"source_asset_id": asset["asset_id"], "source_sha256": asset["sha256"], "usage_scope": asset.get("usage_scope", "general"),
                       "source_frame_index": number, "source_pts": row["source_pts"], "source_pts_ms": row["source_pts_ms"], "source_time_base": metadata["source_time_base"],
                       "width": metadata["source_width"], "height": metadata["source_height"], "relative_path": output.relative_to(context.storage_root).as_posix()}, [_artifact(output, context, "source_frame")])
    finally:
        ledger.release(reservation)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["_index"])
    parser.add_argument("--request", required=True)
    args = parser.parse_args(argv)
    path = Path(args.request)
    if path.stat().st_size > 65536:
        raise ValueError("index request exceeds 64 KiB")
    _stream_index(json.loads(path.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
