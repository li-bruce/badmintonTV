"""Read-only white-flash/tone onset measurement for synthetic sync fixtures.

Example (stdout is the report; no media or report files are written here)::

    python scripts/render/measure_sync.py --environment environments/render-runtime.json \
        --input D:/video/render/smoke-inputs/JOB/source-0.mp4 \
        --input D:/video/render/jobs/JOB/attempt-01/export.mp4

This measures a known synthetic cue; it is not a general real-video sync detector.
"""
from __future__ import annotations

import argparse
import array
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys


def capture(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=False, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-3000:])
    return result


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            sha.update(block)
    return sha.hexdigest()


def measure(path, ffmpeg, ffprobe, seconds, white_threshold):
    path = path.resolve(strict=True)
    probe = json.loads(capture([ffprobe, "-v", "error", "-show_streams", "-show_format",
                                "-of", "json", str(path)]).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    # Input demuxing is bounded one second beyond the analysis window. The trim
    # filter supplies the actual boundary, avoiding an output -t discarding a
    # frame after showinfo has already logged it. -copyts preserves presentation
    # offsets, including the old export's 21.333ms video start offset.
    read_limit = f"{seconds + 1:.6f}"
    vf = (f"trim=start=0:end={seconds:.6f},crop=iw:ih/4:0:3*ih/8,"
          "scale=32:18,format=gray,showinfo")
    frames = capture([
        ffmpeg, "-hide_banner", "-nostdin", "-copyts", "-t", read_limit,
        "-i", str(path), "-map", "0:v:0", "-an", "-vf", vf,
        "-fps_mode", "passthrough", "-f", "rawvideo", "pipe:1",
    ])
    times = [float(value) for value in re.findall(
        r"\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:([-0-9.e+]+)",
        frames.stderr.decode("utf-8", "replace"),
    )]
    pixels = 32 * 18
    if len(frames.stdout) % pixels:
        raise RuntimeError("Decoded grayscale frame is incomplete")
    means = [sum(frames.stdout[i:i + pixels]) / pixels
             for i in range(0, len(frames.stdout), pixels)]
    if len(times) != len(means):
        raise RuntimeError(f"Frame timestamp count {len(times)} differs from pixels {len(means)}")
    flashes = [{"pts_seconds": round(t, 6), "gray_mean": round(mean, 6)}
               for t, mean in zip(times, means) if mean >= white_threshold]

    # first_pts=0 pads or trims the leading samples onto presentation time zero;
    # no atempo or audio retiming is applied by this measurement command.
    af = f"aresample=48000:first_pts=0,atrim=start=0:end={seconds:.6f}"
    pcm = capture([
        ffmpeg, "-v", "error", "-nostdin", "-copyts", "-t", read_limit,
        "-i", str(path), "-map", "0:a:0", "-vn", "-af", af,
        "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
    ]).stdout
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    rms = [math.sqrt(sum(value * value for value in samples[i:i + 48]) /
                     len(samples[i:i + 48])) / 32768
           for i in range(0, len(samples), 48)]
    peak = max(rms, default=0)
    onsets = {}
    flash_start = flashes[0]["pts_seconds"] if flashes else None
    for fraction in (0.05, 0.1, 0.2, 0.5):
        active = [i for i, value in enumerate(rms) if peak > 0.0001 and value >= peak * fraction]
        start = active[0] / 1000 if active else None
        onsets[str(fraction)] = {
            "start_seconds": start,
            "end_seconds": (active[-1] + 1) / 1000 if active else None,
            "threshold_rms": round(peak * fraction, 9),
            "audio_minus_video_ms": round((start - flash_start) * 1000, 6)
            if start is not None and flash_start is not None else None,
        }
    return {
        "path": path.as_posix(), "sha256": digest(path), "size_bytes": path.stat().st_size,
        "video_start_time": video.get("start_time"), "audio_start_time": audio.get("start_time"),
        "format_start_time": probe["format"].get("start_time"),
        "video_fps": video.get("avg_frame_rate"), "decoded_frames": len(means),
        "decoded_audio_samples": len(samples), "flash_frames": flashes,
        "flash_start_seconds": flash_start, "audio_rms_peak": round(peak, 9),
        "audio_onsets": onsets,
        "audio_minus_video_ms_at_10_percent_peak": onsets["0.1"]["audio_minus_video_ms"],
        "cue_detected": bool(flashes and onsets["0.1"]["start_seconds"] is not None),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--white-threshold", type=float, default=240)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 60:
        parser.error("--seconds must be finite and within (0, 60]")
    if not math.isfinite(args.white_threshold) or not 0 < args.white_threshold <= 255:
        parser.error("--white-threshold must be within (0, 255]")
    ffmpeg, ffprobe = args.ffmpeg, args.ffprobe
    if args.environment:
        environment = json.loads(args.environment.read_text(encoding="utf-8-sig"))
        ffmpeg, ffprobe = environment["checks"]["ffmpeg"], environment["checks"]["ffprobe"]
    try:
        report = {
            "schema_version": "1.0", "measured_at": datetime.now(timezone.utc).isoformat(),
            "purpose": "synthetic_onset_sync_check_only",
            "invocation": ["python", *sys.argv],
            "ffmpeg_version": capture([ffmpeg, "-version"]).stdout.decode("utf-8", "replace").splitlines()[0],
            "method": {
                "window_seconds": [0, args.seconds],
                "video": "PTS-preserved central quarter-height crop; 32x18 grayscale mean",
                "white_threshold": args.white_threshold,
                "audio": "48kHz mono PCM; first_pts=0; non-overlapping 1ms RMS windows",
                "rms_peak_fractions": [0.05, 0.1, 0.2, 0.5],
                "offset_sign": "negative means audio leads video",
                "audio_onset_resolution_ms": 1,
                "limitations": [
                    "Measures this synthetic white-flash/tone cue only; no real-video synchronization claim",
                    "Visual timing is limited to decoded frame PTS; audio onset depends on the stated RMS thresholds",
                    "No pass/fail threshold or perceived human viewing acceptance is inferred",
                ],
            },
            "measurements": [measure(path, ffmpeg, ffprobe, args.seconds, args.white_threshold)
                             for path in args.input],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, RuntimeError, StopIteration, subprocess.TimeoutExpired, ValueError) as exc:
        print(json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
