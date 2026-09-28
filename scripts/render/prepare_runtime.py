"""Install a pinned, hash-verified FFmpeg build in the render runtime owner.

Only Python's standard library is required. No PATH, Conda, or system changes.
Existing files are never overwritten or removed; a failed partial download is
retained under its unique attempt directory for a human to inspect.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import uuid
import zipfile

VERSION = "9.0.2"
PACKAGE = f"ffmpeg-{VERSION}-essentials_build"
URL = f"https://www.gyan.dev/ffmpeg/builds/packages/{PACKAGE}.zip"
SHA_URL = URL + ".sha256"
EXPECTED_SHA = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
SHARED_ROOT = Path("D:/video")
OWNER_ROOT = SHARED_ROOT / "runtime" / "render"
DOWNLOAD_LIMIT = 200_000_000
EXTRACT_LIMIT = 650_000_000
QA_LIMIT = 20_000_000
PEAK_LIMIT = DOWNLOAD_LIMIT + EXTRACT_LIMIT + QA_LIMIT
OWNER_LIMIT = 5_000_000_000
SHARED_LIMIT = 700_000_000_000
OTHER_OWNER_CEILING = 645_000_000_000  # 650GB allocation less render runtime 5GB
DISK_MARGIN = 1_000_000_000


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(stage: str, **data) -> None:
    print(json.dumps({"stage": stage, **data}, ensure_ascii=False), flush=True)


def safe_size(path: Path) -> int:
    """Count real files without following any junctions or symlinks."""
    total = 0
    if not path.exists():
        return total
    for base, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not Path(base, d).is_symlink()
                   and not Path(base, d).is_junction()]
        for name in files:
            item = Path(base, name)
            try:
                # Windows cannot follow WSL LX symlinks, and their targets may
                # live outside this shared tree. Count the entry without following
                # it; real target files inside the tree are counted separately.
                total += item.lstat().st_size
            except FileNotFoundError:  # other owner's atomic temporary rename
                pass
    return total


def capacity(additional: int) -> dict:
    owner_used = safe_size(OWNER_ROOT)
    shared_used = safe_size(SHARED_ROOT)
    free = shutil.disk_usage(SHARED_ROOT).free
    # Reserve the full allocation of all other owners. This upper-bounds all
    # their active reservations, including WSL-native environments unseen here.
    # Existing bytes outside this owner are deliberately double-counted, so a
    # crowded machine fails conservatively instead of borrowing the 50GB reserve.
    shared_with_reserves = shared_used + OTHER_OWNER_CEILING + additional
    value = {"owner_used_bytes": owner_used, "shared_used_bytes": shared_used,
             "additional_reserved_bytes": additional,
             "other_owner_reservations_ceiling_bytes": OTHER_OWNER_CEILING,
             "conservative_shared_peak_bytes": shared_with_reserves,
             "physical_free_bytes": free, "owner_quota_bytes": OWNER_LIMIT,
             "shared_hard_limit_bytes": SHARED_LIMIT}
    if owner_used + additional > OWNER_LIMIT:
        raise RuntimeError(f"runtime/render quota exceeded: {value}")
    if shared_with_reserves > SHARED_LIMIT:
        raise RuntimeError(f"Conservative shared capacity check failed: {value}")
    if free < additional + OTHER_OWNER_CEILING + DISK_MARGIN:
        raise RuntimeError(f"Insufficient physical disk capacity: {value}")
    return value


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def remote(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "badmintonTV-render-runtime/1.0"})
    response = urllib.request.urlopen(request, timeout=60)
    from urllib.parse import urlparse
    final = urlparse(response.url)
    if final.scheme != "https" or final.hostname not in {"www.gyan.dev", "gyan.dev"}:
        response.close()
        raise RuntimeError("Unexpected download redirect; inspect official source before retrying")
    return response


def download(path: Path) -> dict:
    with remote(SHA_URL) as response:
        website_checksum = response.read(4097).decode("ascii").strip()
    if not re.fullmatch(r"[a-fA-F0-9]{64}", website_checksum):
        raise RuntimeError("Invalid official SHA256 response")
    if website_checksum.lower() != EXPECTED_SHA:
        raise RuntimeError("Official checksum changed; refuse an unreviewed binary")
    digest = hashlib.sha256()
    received = 0
    next_progress = 10_000_000
    with remote(URL) as response, path.open("xb") as output:
        declared = int(response.headers.get("Content-Length", "0"))
        if declared > DOWNLOAD_LIMIT:
            raise RuntimeError(f"Archive declares {declared} bytes, above hard limit")
        while True:
            block = response.read(min(1024 * 1024, DOWNLOAD_LIMIT - received + 1))
            if not block:
                break
            received += len(block)
            if received > DOWNLOAD_LIMIT:
                raise RuntimeError("Actual streamed bytes exceed archive hard limit")
            output.write(block)
            digest.update(block)
            if received >= next_progress:
                emit("download", bytes=received, declared_bytes=declared)
                next_progress += 10_000_000
    if declared and received != declared:
        raise RuntimeError("Archive response was truncated")
    if digest.hexdigest() != EXPECTED_SHA:
        raise RuntimeError("Archive SHA256 does not match the official pinned value")
    return {"url": URL, "sha256_url": SHA_URL, "sha256": digest.hexdigest(),
            "size_bytes": received, "path": str(path), "verified_at": now()}


def extract(archive: Path, attempt: Path) -> tuple[Path, int]:
    with zipfile.ZipFile(archive) as bundle:
        total = sum(item.file_size for item in bundle.infolist())
        if total > EXTRACT_LIMIT or len(bundle.infolist()) > 10000:
            raise RuntimeError("Archive exceeds pre-reserved extraction bound")
        names = set()
        for item in bundle.infolist():
            parts = PurePosixPath(item.filename).parts
            if not parts or parts[0] != PACKAGE or ".." in parts or "\\" in item.filename:
                raise RuntimeError(f"Unsafe ZIP member: {item.filename!r}")
            if any(":" in part or part.endswith((".", " ")) for part in parts):
                raise RuntimeError(f"Unsafe Windows ZIP path: {item.filename!r}")
            if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                raise RuntimeError("ZIP links and encrypted entries are not permitted")
            target = attempt.joinpath(*parts)
            if not target.resolve().is_relative_to(attempt.resolve()):
                raise RuntimeError("ZIP member escaped the runtime attempt directory")
            key = str(target).lower()
            if key in names:
                raise RuntimeError("Duplicate case-insensitive ZIP member")
            names.add(key)
        emit("extraction_preflight", unpacked_bytes=total,
             archive_plus_unpacked_bytes=archive.stat().st_size + total,
             capacity=capacity(total + QA_LIMIT))
        for item in bundle.infolist():
            target = attempt.joinpath(*PurePosixPath(item.filename).parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            copied = 0
            with bundle.open(item) as src, target.open("xb") as dst:
                while block := src.read(1024 * 1024):
                    copied += len(block)
                    if copied > item.file_size:
                        raise RuntimeError("ZIP member exceeded declared size")
                    dst.write(block)
            if copied != item.file_size:
                raise RuntimeError("ZIP member was truncated")
    return attempt / PACKAGE, total


def run_checked(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, encoding="utf-8",
                            errors="replace", timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}\n{result.stderr[-6000:]}")
    return result.stdout + result.stderr


def validate(build: Path, attempt: Path) -> dict:
    ffmpeg = build / "bin" / "ffmpeg.exe"
    ffprobe = build / "bin" / "ffprobe.exe"
    version = run_checked([str(ffmpeg), "-version"])
    encoders = run_checked([str(ffmpeg), "-hide_banner", "-encoders"])
    filters = run_checked([str(ffmpeg), "-hide_banner", "-filters"])
    for encoder in ("libx264", "aac"):
        if not re.search(rf"\s{encoder}\s", encoders):
            raise RuntimeError(f"Required encoder unavailable: {encoder}")
    if not re.search(r"\ssubtitles\s", filters):
        raise RuntimeError("Required subtitles filter unavailable")
    fonts = [p for p in [Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/simhei.ttf")]
             if p.is_file()]
    if not fonts:
        raise RuntimeError("No expected Chinese font is available")
    srt = attempt / "chinese-test.srt"
    with srt.open("x", encoding="utf-8") as output:
        output.write("1\n00:00:00,000 --> 00:00:00,800\n网前击球 · 中文字幕测试\n")
    mp4 = attempt / "runtime-smoke.mp4"
    log = run_checked([str(ffmpeg), "-hide_banner", "-nostdin", "-n", "-f", "lavfi", "-i",
                       "color=c=0x101827:s=360x640:r=30:d=1", "-f", "lavfi", "-i",
                       "sine=frequency=440:sample_rate=48000:duration=1", "-vf",
                       "subtitles=chinese-test.srt:force_style='Fontname=Microsoft YaHei,Fontsize=22'",
                       "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-pix_fmt",
                       "yuv420p", "-c:a", "aac", "-ac", "2", "-t", "1", "-movflags",
                       "+faststart", "runtime-smoke.mp4"], cwd=attempt)
    if "Glyph" in log and "not found" in log:
        raise RuntimeError("Subtitle smoke test reports missing glyphs")
    with (attempt / "runtime-smoke.log").open("x", encoding="utf-8") as stream:
        stream.write(log)
    probe = json.loads(run_checked([str(ffprobe), "-v", "error", "-show_format", "-show_streams",
                                   "-of", "json", str(mp4)]))
    streams = {s["codec_type"]: s for s in probe["streams"]}
    assert streams["video"]["codec_name"] == "h264" and streams["audio"]["codec_name"] == "aac"
    decode = run_checked([str(ffmpeg), "-v", "error", "-nostdin", "-i", str(mp4), "-f", "null", "-"])
    frame = attempt / "chinese-test.png"
    run_checked([str(ffmpeg), "-v", "error", "-nostdin", "-n", "-i", str(mp4),
                 "-frames:v", "1", str(frame)])
    return {"ffmpeg": str(ffmpeg), "ffprobe": str(ffprobe),
            "ffmpeg_sha256": hash_file(ffmpeg), "ffprobe_sha256": hash_file(ffprobe),
            "version": version.splitlines()[0], "build_configuration": version.splitlines()[2],
            "required_encoders": {"libx264": "verified", "aac": "verified"},
            "subtitles_filter": "verified", "chinese_font_files": [str(p) for p in fonts],
            "font_selection_log": [line for line in log.splitlines() if "fontselect" in line],
            "smoke_mp4": str(mp4), "smoke_frame": str(frame),
            "smoke_type": "synthetic_runtime_check_only", "smoke_duration": probe["format"]["duration"],
            "full_decode": "passed" if not decode else decode,
            "manual_chinese_frame_review": "pending"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="download, extract and validate the pinned build")
    parser.add_argument("--report", type=Path, help="new workspace environment JSON path; must not already exist")
    args = parser.parse_args()
    if os.name != "nt" or not hasattr(Path(), "is_junction"):
        parser.error("This installer requires Windows and Python 3.12+")
    if OWNER_ROOT.resolve() != Path("D:/video/runtime/render").absolute():
        raise RuntimeError("Runtime owner path cannot be a symlink or junction")
    baseline = capacity(PEAK_LIMIT)
    emit("preflight", version=VERSION, archive_url=URL, expected_sha256=EXPECTED_SHA,
         archive_limit_bytes=DOWNLOAD_LIMIT, extraction_limit_bytes=EXTRACT_LIMIT,
         planned_peak_bytes=PEAK_LIMIT, capacity=baseline)
    if not args.install:
        return 0
    if args.report and args.report.exists():
        raise FileExistsError(f"Refuse to overwrite existing report: {args.report}")
    OWNER_ROOT.mkdir(parents=True, exist_ok=True)
    lock = OWNER_ROOT / ".prepare-runtime.lock"
    lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    attempt = OWNER_ROOT / ("install-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as stream:
            json.dump({"owner": "runtime/render", "pid": os.getpid(), "reserved_bytes": PEAK_LIMIT,
                       "attempt": str(attempt), "created_at": now()}, stream)
        # Preflight again after acquiring the owner-exclusive reservation.
        baseline = capacity(PEAK_LIMIT)
        attempt.mkdir()
        write_json_new(attempt / "reservation.json", {"status": "active", "reserved_bytes": PEAK_LIMIT,
                                                      "preflight": baseline, "created_at": now()})
        archive = attempt / (PACKAGE + ".zip")
        acquisition = download(archive)
        build, unpacked = extract(archive, attempt)
        verification = validate(build, attempt)
        report = {"schema_version": "1.0", "owner": "render", "status": "ready",
                  "prepared_at": now(), "runtime_root": str(OWNER_ROOT),
                  "python": {"executable": sys.executable, "version": sys.version,
                             "use": "standard-library installer only; no base modifications"},
                  "sources": {"official_download_index": "https://ffmpeg.org/download.html",
                              "build_provider": "https://www.gyan.dev/ffmpeg/builds/",
                              "ffmpeg_source_commit": "https://github.com/FFmpeg/FFmpeg/commit/946fcce07b",
                              "license": "GPLv3", "license_reference": "https://ffmpeg.org/legal.html"},
                  "acquisition": acquisition, "unpacked_bytes": unpacked,
                  "checks": verification, "capacity_before": baseline, "capacity_after": capacity(0),
                  "planned_peak_bytes": PEAK_LIMIT, "gpu_used": False,
                  "network_services_started": False, "existing_files_deleted_or_overwritten": False}
        write_json_new(attempt / "environment.json", report)
        write_json_new(attempt / "reservation-completed.json", {"status": "completed", "reserved_bytes": 0,
                                                               "actual_bytes": safe_size(attempt), "ended_at": now()})
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            write_json_new(args.report, report)
        emit("ready", environment_report=str(attempt / "environment.json"), **verification)
        return 0
    except Exception as exc:
        if attempt.exists():
            write_json_new(attempt / "failure.json", {"status": "failed", "error": str(exc),
                                                      "retained_partial_directory": str(attempt), "ended_at": now()})
        emit("failed", message=str(exc), retained_partial_directory=str(attempt))
        return 1
    finally:
        # This lock was exclusively created by this process; release is recorded
        # by completed/failure JSON. No pre-existing locks/files are deleted.
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
