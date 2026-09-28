"""Bounded metadata/PTS probing and complete CPU decoding with provided tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from fractions import Fraction

from .manifest import ManifestError, safe_asset_path, sha256_file


class ProbeError(RuntimeError):
    """Unavailable tool, malformed media, failed decode, or exceeded bound."""


def _run(args: list[str], timeout_seconds: float) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                timeout=timeout_seconds, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"tool failed: {type(exc).__name__}: {exc}") from exc
    if result.returncode:
        raise ProbeError(f"{Path(args[0]).name} exited {result.returncode}: {result.stderr[-4000:]}")
    return result


def _rational(value: object, name: str) -> Fraction:
    try:
        rate = Fraction(str(value))
        if rate <= 0:
            raise ValueError()
        return rate
    except (ValueError, ZeroDivisionError):
        raise ProbeError(f"missing or invalid {name}: {value!r}") from None


def _pts_index(
    media: Path, target: Path, storage_root: Path, *, ffprobe: str,
    timeout_seconds: float, max_pts_frames: int, max_pts_bytes: int, time_base: str,
    stream_index: int,
) -> dict:
    """Save integer PTS JSONL without buffering the full video frame inventory."""
    if max_pts_frames < 2 or max_pts_bytes < 1:
        raise ProbeError("PTS frame/byte limits must be positive (at least 2 frames)")
    target = target.resolve()
    if not target.is_relative_to(storage_root):
        raise ProbeError("PTS index must be inside storage_root")
    try:
        relative = target.relative_to(storage_root).as_posix()
        safe_asset_path(relative, storage_root)
    except ManifestError as exc:
        raise ProbeError(str(exc)) from exc
    if target.exists():
        raise ProbeError("PTS index already exists; choose a new output path")
    target.parent.mkdir(parents=True, exist_ok=True)
    args = [ffprobe, "-v", "error", "-select_streams", str(stream_index), "-show_frames",
            "-show_entries", "frame=best_effort_timestamp", "-of", "csv=p=0", str(media)]
    expired = threading.Event()
    count, written, previous, min_delta, max_delta = 0, 0, None, None, None
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=target.name + ".", suffix=".tmp", delete=False
        ) as output:
            name = output.name
            try:
                process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as exc:
                raise ProbeError(f"PTS probe unavailable: {exc}") from exc

            # Drain diagnostics without an unbounded temporary file or pipe deadlock.
            error_tail = bytearray()
            def drain_errors():
                assert process.stderr is not None
                for chunk in iter(lambda: process.stderr.read(4096), b""):
                    error_tail.extend(chunk)
                    del error_tail[:-4000]
            error_thread = threading.Thread(target=drain_errors, daemon=True)
            error_thread.start()

            def expire():
                expired.set()
                if process.poll() is None:
                    process.kill()

            timer = threading.Timer(timeout_seconds, expire)
            timer.daemon = True
            timer.start()
            try:
                assert process.stdout is not None
                # read at most one small ffprobe CSV record at a time
                while True:
                    raw = process.stdout.readline(4097)
                    if not raw:
                        break
                    if len(raw) > 4096:
                        raise ProbeError("unexpected oversized PTS record")
                    # ffprobe can append a side-data description after the PTS.
                    token = raw.decode("utf-8", errors="replace").strip().split(",", 1)[0]
                    if not token:  # an empty separator is not a frame
                        continue
                    try:
                        pts = int(token)
                    except ValueError:
                        raise ProbeError("frame has no usable integer presentation timestamp") from None
                    if count >= max_pts_frames:
                        raise ProbeError("PTS frame limit exceeded; index was not published")
                    row = (json.dumps({"frame_index": count, "pts": pts}, separators=(",", ":")) + "\n").encode("utf-8")
                    if written + len(row) > max_pts_bytes:
                        raise ProbeError("PTS byte limit exceeded; index was not published")
                    output.write(row)
                    written += len(row)
                    if previous is not None:
                        delta = pts - previous
                        if delta <= 0:
                            raise ProbeError("non-increasing frame PTS; cannot safely map frames")
                        min_delta = delta if min_delta is None else min(min_delta, delta)
                        max_delta = delta if max_delta is None else max(max_delta, delta)
                    previous = pts
                    count += 1
                returncode = process.wait()
                if expired.is_set():
                    raise ProbeError("PTS probe timed out")
                if returncode:
                    error_thread.join(timeout=1)
                    raise ProbeError(f"PTS probe exited {returncode}: {error_tail.decode('utf-8', errors='replace')}")
                if count == 0:
                    raise ProbeError("video has no timestamped frames")
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                process.wait()
                error_thread.join(timeout=1)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
            output.flush()
            os.fsync(output.fileno())
        # A hard link is atomic and refuses to replace any existing destination.
        os.link(name, target)
        Path(name).unlink()
        name = None
        # One tick of rounding variation cannot prove variable frame timing.
        if count < 3:
            status = "unknown"
        elif min_delta == max_delta:
            status = "cfr_observed"
        elif max_delta - min_delta > 1:
            status = "vfr_observed"
        else:
            status = "unknown"
        return {
            "relative_path": relative, "sha256": sha256_file(target),
            "size_bytes": written, "format": "jsonl", "frame_count": count,
            "time_base": time_base, "pts_field": "best_effort_timestamp",
            "complete": True, "vfr_status": status,
            "min_delta_ticks": min_delta, "max_delta_ticks": max_delta,
        }
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def probe_video(
    path: str | Path, *, ffprobe: str | Path = "ffprobe", ffmpeg: str | Path = "ffmpeg",
    timeout_seconds: float = 300, pts_index_path: str | Path | None = None,
    storage_root: str | Path = "D:/video", max_pts_frames: int = 1_000_000,
    max_pts_bytes: int = 64_000_000,
) -> dict:
    """Return Asset technical fields only after successful whole-video CPU decode.

    Metadata fps is a rational estimate, not proof of CFR. Optional complete PTS
    scanning writes a bounded index; callers reserve its maximum bytes first.
    Timeouts apply separately to metadata, decode and PTS scan. Files are read-only.
    """
    media = Path(path).resolve()
    if not media.is_file():
        raise ProbeError("video file does not exist")
    if timeout_seconds <= 0:
        raise ProbeError("timeout_seconds must be positive")
    before = media.stat()
    ffprobe, ffmpeg = str(ffprobe), str(ffmpeg)
    probe_version = _run([ffprobe, "-version"], min(timeout_seconds, 30)).stdout.splitlines()[0]
    decoder_version = _run([ffmpeg, "-version"], min(timeout_seconds, 30)).stdout.splitlines()[0]
    raw = _run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media)], timeout_seconds)
    try:
        metadata = json.loads(raw.stdout)
        video = next(stream for stream in metadata["streams"] if stream.get("codec_type") == "video"
                     and not stream.get("disposition", {}).get("attached_pic"))
    except (ValueError, KeyError, TypeError, StopIteration):
        raise ProbeError("no usable video stream in ffprobe output") from None
    fps_source = "avg_frame_rate"
    try:
        fps = _rational(video.get(fps_source), fps_source)
    except ProbeError:
        fps_source = "r_frame_rate"
        fps = _rational(video.get(fps_source), fps_source)
    time_base = _rational(video.get("time_base"), "time_base")
    try:
        width, height = int(video["width"]), int(video["height"])
        duration_source = "stream.duration"
        duration_text = video.get("duration")
        if duration_text in (None, "N/A"):
            duration_source = "format.duration"
            duration_text = metadata.get("format", {}).get("duration")
        duration = Decimal(str(duration_text))
        if not duration.is_finite() or duration <= 0 or min(width, height) <= 0:
            raise ValueError()
        duration_ms = int((duration * 1000).to_integral_value(rounding=ROUND_CEILING))
    except (ValueError, KeyError, TypeError, InvalidOperation):
        raise ProbeError("video requires finite positive duration and dimensions") from None
    video_index = str(video["index"])
    decode_args = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-xerror",
                   "-hwaccel", "none", "-threads", "1", "-i", str(media),
                   "-map", "0:" + video_index, "-an", "-sn", "-dn", "-threads", "1",
                   "-fps_mode", "passthrough",
                   "-progress", "pipe:1", "-nostats", "-f", "null", "-"]
    decoded = _run(decode_args, timeout_seconds)
    if decoded.stderr.strip():
        raise ProbeError("CPU decode reported errors: " + decoded.stderr[-4000:])
    frames = [int(line.partition("=")[2].strip()) for line in decoded.stdout.splitlines()
              if line.startswith("frame=")]
    if not frames or frames[-1] < 1 or "progress=end" not in decoded.stdout:
        raise ProbeError("CPU decode did not report a completed nonempty video")
    result = {
        "duration_ms": duration_ms, "width": width, "height": height,
        "fps_num": fps.numerator, "fps_den": fps.denominator,
        "time_base": f"{time_base.numerator}/{time_base.denominator}",
        "probe": {
            "ffprobe_version": probe_version, "ffmpeg_version": decoder_version,
            "probed_at": datetime.now(timezone.utc).isoformat(),
            "codec_name": video.get("codec_name", "unknown"), "stream_index": video["index"],
            "fps_source": fps_source, "duration_source": duration_source,
            "start_time": video.get("start_time"), "start_pts": video.get("start_pts"),
            "avg_frame_rate": video.get("avg_frame_rate"), "r_frame_rate": video.get("r_frame_rate"),
            "vfr_status": "unknown", "pts_index": None,
            "timing_note": "Container rates alone do not prove CFR; original timestamps retained when indexed.",
            "decode": {"status": "passed", "scope": "full_video_stream", "device": "cpu",
                       "frames": frames[-1], "exit_code": decoded.returncode},
        },
    }
    if pts_index_path is not None:
        index = _pts_index(media, Path(pts_index_path), Path(storage_root).resolve(),
                           ffprobe=ffprobe, timeout_seconds=timeout_seconds,
                           max_pts_frames=max_pts_frames, max_pts_bytes=max_pts_bytes,
                           time_base=result["time_base"], stream_index=video["index"])
        result["probe"]["pts_index"] = index
        result["probe"]["vfr_status"] = index["vfr_status"]
    result["probe"]["source_sha256"] = sha256_file(media)
    result["probe"]["source_size_bytes"] = before.st_size
    after = media.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ProbeError("video changed during probing; report is invalid")
    return result
