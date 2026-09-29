"""Install pinned Gyan FFmpeg 8.0.1 beside 9.x; CPU checks only, no GPU use.

Reuses prepare_runtime's quota accounting, ZIP extraction and CPU subtitle QA.
The official GitHub release digest is checked before downloading. Existing
installations, reports, global environments and drivers are never overwritten.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from scripts.render import prepare_runtime as shared

VERSION = "8.0.1"
PACKAGE = f"ffmpeg-{VERSION}-essentials_build"
ASSET_NAME = PACKAGE + ".zip"
RELEASE_PAGE = "https://github.com/GyanD/codexffmpeg/releases/tag/8.0.1"
API_URL = "https://api.github.com/repos/GyanD/codexffmpeg/releases/tags/8.0.1"
URL = "https://github.com/GyanD/codexffmpeg/releases/download/8.0.1/" + ASSET_NAME
EXPECTED_SHA = "e2aaeaa0fdbc397d4794828086424d4aaa2102cef1fb6874f6ffd29c0b88b673"
SOURCE_COMMIT = "894da5ca7d"
HEADERS_README = "https://raw.githubusercontent.com/FFmpeg/nv-codec-headers/n13.0.19.0/README"


def allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    if parsed.hostname == "github.com":
        return parsed.path == urllib.parse.urlsplit(URL).path
    if parsed.hostname == "api.github.com":
        return parsed.path == urllib.parse.urlsplit(API_URL).path
    # GitHub's official binary delivery endpoint, never an arbitrary mirror.
    if parsed.hostname == "release-assets.githubusercontent.com":
        return parsed.path.startswith("/github-production-release-asset/306803927/")
    return False


class ReleaseRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise RuntimeError("Release redirected outside the pinned GitHub/asset URL allowlist")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def remote(url, extra_headers=None):
    if not allowed_url(url):
        raise RuntimeError("URL is outside the pinned release allowlist")
    opener = urllib.request.build_opener(ReleaseRedirectHandler())
    headers = {
        "User-Agent": "badmintonTV-render-compat-runtime/1.0",
        "Cache-Control": "no-cache", "Accept": "application/vnd.github+json" if "api.github.com" in url else "application/octet-stream",
    }
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, headers=headers)
    response = opener.open(request, timeout=60)
    if not allowed_url(response.url):
        response.close()
        raise RuntimeError("Unexpected final release URL")
    return response


def release_asset():
    with remote(API_URL) as response:
        content = response.read(200_001)
    if len(content) > 200_000:
        raise RuntimeError("Release metadata exceeds the bounded read")
    release = json.loads(content)
    if release.get("tag_name") != VERSION or release.get("html_url") != RELEASE_PAGE:
        raise RuntimeError("Unexpected official release identity")
    assets = [item for item in release.get("assets", []) if item.get("name") == ASSET_NAME]
    if len(assets) != 1:
        raise RuntimeError("Pinned essentials ZIP is absent or ambiguous")
    asset = assets[0]
    if asset.get("browser_download_url") != URL or asset.get("digest") != "sha256:" + EXPECTED_SHA:
        raise RuntimeError("Official release asset digest/URL differs from reviewed fixed values")
    if not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= shared.DOWNLOAD_LIMIT:
        raise RuntimeError("Official release size exceeds the download bound")
    return {"asset_id": asset["id"], "name": asset["name"], "size_bytes": asset["size"],
            "sha256": EXPECTED_SHA, "url": URL, "release_page": RELEASE_PAGE,
            "metadata_url": API_URL, "release_published_at": release.get("published_at"),
            "asset_updated_at": asset.get("updated_at")}


def download(path, asset, retained_partial_bytes, workers=8):
    """Disjoint bounded ranges write one preallocated file; no chunk duplication."""
    total = asset["size_bytes"]
    if retained_partial_bytes + total + workers > shared.DOWNLOAD_LIMIT:
        raise RuntimeError("Prior partial plus all new range bytes would exceed the 200MB actual download bound")
    with path.open("xb") as output:
        output.truncate(total)
    received, next_progress = 0, 10_000_000
    lock, stopped = threading.Lock(), threading.Event()
    started = time.monotonic()
    width = (total + workers - 1) // workers
    spans = [(start, min(start + width, total) - 1) for start in range(0, total, width)]

    def part(start, end):
        nonlocal received, next_progress
        expected, copied = end - start + 1, 0
        # A nonce only refreshes GitHub's public signed redirect; the pinned
        # asset path, host allowlist and full-file digest stay unchanged.
        request_url = URL + "?btv_range=" + uuid.uuid4().hex
        with remote(request_url, {"Range": f"bytes={start}-{end}"}) as response, path.open("r+b", buffering=0) as output:
            content_range = response.headers.get("Content-Range")
            if response.status != 206 or content_range != f"bytes {start}-{end}/{total}":
                raise RuntimeError(f"Official range response is not exact HTTP206 for {start}-{end}")
            declared = int(response.headers.get("Content-Length", "0"))
            if declared and declared != expected:
                raise RuntimeError("Range Content-Length differs from exact requested bytes")
            output.seek(start)
            while True:
                if stopped.is_set() or time.monotonic() - started > 900:
                    raise RuntimeError("Range download stopped or exceeded its 15-minute bound")
                block = response.read(min(65536, expected - copied + 1))
                if not block:
                    break
                copied += len(block)
                with lock:
                    received += len(block)
                    if retained_partial_bytes + received > shared.DOWNLOAD_LIMIT:
                        raise RuntimeError("Actual archive bytes including retained partial exceeded 200MB")
                    if received >= next_progress:
                        shared.emit("download_compat_ranges", bytes=received, total_bytes=total,
                                    retained_partial_bytes=retained_partial_bytes, workers=workers)
                        next_progress += 10_000_000
                if copied > expected:
                    raise RuntimeError("Range payload exceeded its exact hard byte bound")
                output.write(block)
            if copied != expected:
                raise RuntimeError("Range payload was truncated")
        return {"start": start, "end": end, "actual_bytes": copied, "http_status": 206, "content_range": content_range}

    ranges = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(part, start, end) for start, end in spans]
            try:
                for future in as_completed(futures):
                    ranges.append(future.result())
            except BaseException:
                stopped.set()
                raise
    except BaseException:
        shared.write_json_new(path.parent / "download-state-failed.json", {
            "actual_new_archive_bytes_received": received, "retained_prior_partial_bytes": retained_partial_bytes,
            "preallocated_file_bytes": total, "completed_ranges": ranges, "ended_at": shared.now()})
        raise
    if received != total or shared.hash_file(path) != EXPECTED_SHA:
        raise RuntimeError("Combined archive size or SHA256 differs from the official pinned release")
    return {**asset, "path": str(path), "verified_at": shared.now(), "delivery_host": "release-assets.githubusercontent.com",
            "range_workers": workers, "ranges": sorted(ranges, key=lambda item: item["start"]),
            "actual_new_archive_bytes_received": received, "retained_prior_partial_bytes": retained_partial_bytes,
            "actual_archive_bytes_including_retained_partial": retained_partial_bytes + received}


def inspect_nvcodec(build):
    readme = build / "README.txt"
    if not readme.is_file() or readme.stat().st_size > 1_000_000:
        raise RuntimeError("Build dependency README missing or too large")
    value = readme.read_text(encoding="utf-8", errors="strict")
    lines = [line.strip() for line in value.splitlines() if re.match(r"^ffnvcodec\s+n?\d", line.strip())]
    if len(lines) != 1:
        raise RuntimeError("Cannot determine compiled ffnvcodec version from the included README")
    match = re.match(r"ffnvcodec\s+n?(\d+)\.(\d+)\.(\d+)", lines[0])
    if not match:
        raise RuntimeError("Unrecognized ffnvcodec dependency format")
    major, minor, patch = map(int, match.groups())
    evidence = {"included_readme": str(readme), "readme_sha256": shared.hash_file(readme),
                "compiled_dependency_line": lines[0], "sdk_api_major": major, "sdk_api_minor": minor,
                "gpu_probe": "not_run", "compatibility": "compiled_dependency_only_not_runtime_verified",
                "headers_reference": HEADERS_README,
                "headers_reference_windows_min_driver": "570.0 for SDK 13.0.19"}
    if (major, minor) > (13, 0):
        raise RuntimeError(f"Build still requires NVENC API {major}.{minor}; stop without any GPU invocation")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--download-workers", type=int, choices=(4, 8), default=8)
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "environments/render-runtime-compat.json")
    args = parser.parse_args()
    if os.name != "nt" or not hasattr(Path(), "is_junction"):
        parser.error("Windows with Python 3.12+ required")
    if shared.OWNER_ROOT.resolve() != Path("D:/video/runtime/render").absolute():
        raise RuntimeError("Runtime owner cannot redirect outside D:/video/runtime/render")
    # Reuse the reviewed extractor with this single fixed package root. This is
    # process-local module configuration; prepare_runtime.py remains unchanged.
    shared.PACKAGE = PACKAGE
    baseline = shared.capacity(shared.PEAK_LIMIT)
    shared.emit("compat_preflight", version=VERSION, archive_url=URL, expected_sha256=EXPECTED_SHA,
                planned_peak_bytes=shared.PEAK_LIMIT, capacity=baseline, gpu_use=False)
    if not args.install:
        return 0
    if args.report.exists():
        raise FileExistsError(f"Refuse to overwrite compatibility report: {args.report}")
    asset = release_asset()
    shared.emit("official_asset_verified", **asset)
    shared.OWNER_ROOT.mkdir(parents=True, exist_ok=True)
    lock = shared.OWNER_ROOT / ".prepare-runtime.lock"
    lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    attempt = shared.OWNER_ROOT / ("compat-8.0.1-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as stream:
            json.dump({"owner": "runtime/render", "pid": os.getpid(), "reserved_bytes": shared.PEAK_LIMIT,
                       "attempt": str(attempt), "created_at": shared.now()}, stream)
        baseline = shared.capacity(shared.PEAK_LIMIT)
        attempt.mkdir()
        shared.write_json_new(attempt / "reservation.json", {"status": "active", "reserved_bytes": shared.PEAK_LIMIT,
                              "preflight": baseline, "created_at": shared.now()})
        retained_partial_bytes = sum(p.stat().st_size for p in shared.OWNER_ROOT.glob("compat-8.0.1-*/*.zip")
                                     if p.parent != attempt)
        acquisition = download(attempt / ASSET_NAME, asset, retained_partial_bytes, args.download_workers)
        build, unpacked = shared.extract(attempt / ASSET_NAME, attempt)
        dependency = inspect_nvcodec(build)
        shared.emit("compiled_dependency_verified", **dependency)
        verification = shared.validate(build, attempt)
        report = {"schema_version": "1.0", "owner": "render", "status": "ready",
                  "prepared_at": shared.now(), "runtime_root": str(shared.OWNER_ROOT),
                  "purpose": "compatibility candidate for unchanged API13.0 host; CPU validation only",
                  "python": {"executable": sys.executable, "version": sys.version, "no_environment_changes": True},
                  "sources": {"official_download_index": "https://ffmpeg.org/download.html",
                              "build_provider": "https://www.gyan.dev/ffmpeg/builds/", "release_page": RELEASE_PAGE,
                              "ffmpeg_source_commit": "https://github.com/FFmpeg/FFmpeg/commit/" + SOURCE_COMMIT,
                              "license": "GPLv3", "license_reference": "https://ffmpeg.org/legal.html"},
                  "acquisition": acquisition, "unpacked_bytes": unpacked, "checks": verification,
                  "nvcodec_dependency": dependency, "capacity_before": baseline, "capacity_after": shared.capacity(0),
                  "planned_peak_bytes": shared.PEAK_LIMIT, "gpu_used": False, "driver_changed": False,
                  "previous_9_0_2_installation": "retained unchanged", "existing_files_deleted_or_overwritten": False}
        shared.write_json_new(attempt / "environment.json", report)
        shared.write_json_new(attempt / "reservation-completed.json", {"status": "completed", "reserved_bytes": 0,
                              "actual_bytes": shared.safe_size(attempt), "ended_at": shared.now()})
        args.report.parent.mkdir(parents=True, exist_ok=True)
        shared.write_json_new(args.report, report)
        shared.emit("compat_ready", report=str(args.report), external_report=str(attempt / "environment.json"),
                    ffmpeg=verification["ffmpeg"], ffprobe=verification["ffprobe"], nvcodec=dependency["compiled_dependency_line"])
        return 0
    except Exception as exc:
        if attempt.exists():
            shared.write_json_new(attempt / "failure.json", {"status": "failed", "error": str(exc),
                                  "retained_partial_directory": str(attempt), "ended_at": shared.now()})
        shared.emit("compat_failed", message=str(exc), retained_partial_directory=str(attempt))
        return 1
    finally:
        lock.unlink()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
