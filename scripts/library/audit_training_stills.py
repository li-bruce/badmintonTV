"""Bounded CPU middle-frame stills from published Fine-Badminton PTS evidence."""

import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading

from packages.library.manifest import sha256_file, validate_asset
from packages.library.storage import QuotaManager, directory_bytes
from scripts.library.acquire_training_dataset import BASE, DATASET


MANIFEST = "training/handoff/" + DATASET + ".assets.v1.json"
OUTPUT = BASE + "/quality-control"
TOTAL_LIMIT = 10_000_000
JPEG_LIMIT = 500_000
RECEIPT_LIMIT = 16_384


def read_json(path, limit=10_000_000):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("JSON exceeds its fixed byte bound")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def source_path(relative, quota):
    prefix = "data/" + BASE + "/"
    if not isinstance(relative, str) or not relative.startswith(prefix):
        raise ValueError("Source must remain in this training dataset")
    return quota.resolve_path(relative[len("data/"):])


def middle_pts(asset, quota):
    index = asset["probe"]["pts_index"]
    if (index.get("complete") is not True or index.get("format") != "jsonl"
            or index.get("pts_field") != "best_effort_timestamp"
            or type(index.get("frame_count")) is not int or not 1 <= index["frame_count"] <= 2_000_000
            or not 0 < index.get("size_bytes", 0) <= 128_000_000):
        raise ValueError("Still selection requires the published complete bounded source PTS index")
    path = source_path(index["relative_path"], quota)
    target, selected, previous, count, size = index["frame_count"] // 2, None, None, 0, 0
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while raw := stream.readline(4097):
            size += len(raw)
            if len(raw) > 4096 or size > index["size_bytes"] or count >= index["frame_count"]:
                raise ValueError("PTS bytes/rows exceed the published bounds")
            digest.update(raw)
            row = json.loads(raw)
            if (row.get("frame_index") != count or type(row.get("pts")) is not int
                    or (previous is not None and row["pts"] <= previous)):
                raise ValueError("PTS rows must be contiguous and strictly increasing")
            if count == target:
                selected = row
            previous, count = row["pts"], count + 1
    if count != index["frame_count"] or size != index["size_bytes"] or digest.hexdigest() != index["sha256"]:
        raise ValueError("PTS index no longer matches its published complete receipt")
    time_base = Fraction(index["time_base"])
    if time_base <= 0 or selected["pts"] < 0:
        raise ValueError("Unsupported PTS time base or negative middle-frame timestamp")
    timestamp = selected["pts"] * time_base
    return {"selection": "middle_frame_index_from_complete_source_pts", "frame_index": target,
            "pts_line_1based": target + 1, "pts": selected["pts"], "time_base": str(time_base),
            "time_seconds_fraction": str(timestamp), "time_seconds": float(timestamp),
            "pts_index_relative_path": index["relative_path"], "pts_index_sha256": index["sha256"]}


def capture(argv, *, timeout=180):
    """Keep both pipes bounded; never let FFmpeg write a disk output file."""
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    errors, timed_out = bytearray(), threading.Event()
    def drain():
        for block in iter(lambda: process.stderr.read(4096), b""):
            errors.extend(block)
            del errors[:-8192]
    worker = threading.Thread(target=drain, daemon=True)
    worker.start()
    def expire():
        timed_out.set()
        if process.poll() is None:
            process.kill()
    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    try:
        jpeg = process.stdout.read(JPEG_LIMIT + 1)
        if len(jpeg) > JPEG_LIMIT:
            raise ValueError("JPEG exceeds 500000 bytes; no image file was written")
        code = process.wait(timeout=10)
        worker.join(timeout=2)
        log = errors.decode("utf-8", errors="replace")
        if timed_out.is_set() or code or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise ValueError(f"Bounded JPEG extraction failed (exit={code}, timeout={timed_out.is_set()}): {log[-1000:]}")
        return jpeg, log
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        worker.join(timeout=2)
        process.stdout.close()
        process.stderr.close()


def publish_new(path, payload, quota):
    quota.resolve_path(path.relative_to(quota.data_root))
    partial = quota.resolve_path(str(path.relative_to(quota.data_root)) + ".part")
    if path.exists() or partial.exists():
        raise FileExistsError("Existing QA output/partial is preserved")
    with partial.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, path, follow_symlinks=False)
    partial.unlink()


def audit(ffmpeg, *, max_new):
    if not 0 <= max_new <= 10:
        raise ValueError("max_new must be between 0 and 10 (zero verifies existing outputs only)")
    quota = QuotaManager()
    manifest_path = quota.resolve_path(MANIFEST)
    manifest, manifest_sha = read_json(manifest_path)
    assets = manifest.get("assets")
    if manifest.get("schema_version") != "1.0" or not isinstance(assets, list) or not 1 <= len(assets) <= 10:
        raise ValueError("Expected the published Fine training manifest, at most ten assets")
    if len({asset["sha256"] for asset in assets}) != len(assets):
        raise ValueError("Published source SHAs must be unique")
    version = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=15, check=True).stdout.splitlines()[0]
    if not version.startswith("ffmpeg version 9.0.2"):
        raise ValueError("Use the existing reviewed CPU FFmpeg 9.0.2 executable")
    directory = quota.resolve_path(OUTPUT)
    with quota.reserve(TOTAL_LIMIT, purpose="training only middle-frame visual QA; 10 MB total and 500 KB per JPEG"):
        directory.mkdir(parents=True, exist_ok=True)
        lock = quota.resolve_path(OUTPUT + "/.audit-stills.lock")
        with lock.open("xb") as stream:
            stream.write(str(os.getpid()).encode("ascii"))
        try:
            created = 0
            for asset in sorted(assets, key=lambda row: (row["probe"]["probed_at"], row["asset_id"])):
                if asset.get("usage_scope") != "training_only" or asset.get("provenance", {}).get("usage_scope") != "training_only":
                    raise ValueError("Both typed and provenance usage_scope must remain training_only")
                if asset["probe"].get("source_sha256") != asset["sha256"]:
                    raise ValueError("Source probe must bind the published SHA")
                media = source_path(asset["relative_path"], quota)
                image = quota.resolve_path(OUTPUT + "/" + asset["sha256"][:24] + ".middle.jpg")
                receipt_path = quota.resolve_path(OUTPUT + "/" + asset["sha256"][:24] + ".middle.json")
                if image.exists() or receipt_path.exists():
                    saved, _ = read_json(receipt_path, RECEIPT_LIMIT)
                    if (saved.get("source_sha256") != asset["sha256"] or saved.get("source_asset_id") != asset["asset_id"]
                            or saved.get("usage_scope") != "training_only" or saved.get("provenance", {}).get("usage_scope") != "training_only"
                            or saved.get("output_relative_path") != image.relative_to(quota.project_root).as_posix()
                            or not image.is_file() or not 0 < image.stat().st_size <= JPEG_LIMIT
                            or saved.get("output_sha256") != sha256_file(image)):
                        raise ValueError("Existing QA outputs do not match their immutable receipt; preserved unchanged")
                    print(json.dumps({"event": "still_reused", "asset_id": asset["asset_id"], "path": str(image)}), flush=True)
                    continue
                if created >= max_new:
                    break
                if directory_bytes(directory) + 2 * (JPEG_LIMIT + RECEIPT_LIMIT) > TOTAL_LIMIT:
                    raise ValueError("QA directory including atomic publication headroom would exceed 10 MB")
                validate_asset(asset, storage_root=quota.project_root)
                selected = middle_pts(asset, quota)
                timestamp = Fraction(selected["time_seconds_fraction"])
                seek = max(Fraction(0), timestamp - 1)
                seek_decimal = (Decimal(seek.numerator) / Decimal(seek.denominator)).quantize(Decimal("0.000001"), rounding=ROUND_FLOOR)
                argv = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "info", "-copyts",
                        "-hwaccel", "none", "-threads", "1", "-protocol_whitelist", "file,pipe",
                        "-seek_timestamp", "1", "-ss", str(seek_decimal), "-i", str(media),
                        "-map", "0:" + str(asset["probe"]["stream_index"]), "-an", "-sn", "-dn",
                        "-filter_threads", "1", "-vf", f"select=eq(pts\\,{selected['pts']}),showinfo,scale=640:-2",
                        "-frames:v", "1", "-fps_mode", "passthrough", "-c:v", "mjpeg", "-q:v", "3",
                        "-threads", "1", "-f", "image2pipe", "pipe:1"]
                print(json.dumps({"event": "still_started", "asset_id": asset["asset_id"], **selected}), flush=True)
                jpeg, log = capture(argv)
                shown = re.findall(r"\bn:\s*\d+\s+pts:\s*(-?\d+)\s+pts_time:([\d.eE+-]+)", log)
                time_bases = re.findall(r"config in time_base:\s*(\d+/\d+)", log)
                if (not shown or any(int(pts) != selected["pts"] for pts, _ in shown)
                        or not time_bases or any(Fraction(value) != Fraction(selected["time_base"]) for value in time_bases)):
                    raise ValueError("FFmpeg did not confirm the selected original integer PTS/time base")
                if sha256_file(media) != asset["sha256"]:
                    raise ValueError("Source changed during still extraction; nothing published")
                record = {"schema_version": "1.0", "usage_scope": "training_only",
                          "provenance": {"usage_scope": "training_only", "dataset_id": DATASET},
                          "created_at": datetime.now(timezone.utc).isoformat(), "source_asset_id": asset["asset_id"],
                          "source_sha256": asset["sha256"], "source_relative_path": asset["relative_path"],
                          "manifest_relative_path": "data/" + MANIFEST, "manifest_sha256_at_selection": manifest_sha,
                          "selection": selected, "ffmpeg_version": version, "argv": argv, "device": "cpu",
                          "ffmpeg_observed_pts": [int(pts) for pts, _ in shown], "output_width": 640,
                          "output_relative_path": image.relative_to(quota.project_root).as_posix(),
                          "output_sha256": hashlib.sha256(jpeg).hexdigest(), "output_size_bytes": len(jpeg),
                          "limits": {"jpeg_bytes": JPEG_LIMIT, "directory_bytes": TOTAL_LIMIT},
                          "review_scope": "Court/match-image visibility only; no CSV alignment, stroke, face identity, or boundary judgement"}
                payload = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                if len(payload) > RECEIPT_LIMIT:
                    raise ValueError("QA receipt exceeds 16 KiB")
                publish_new(image, jpeg, quota)
                publish_new(receipt_path, payload, quota)
                created += 1
                print(json.dumps({"event": "still_created", "asset_id": asset["asset_id"], "path": str(image),
                                  "bytes": len(jpeg), "receipt_path": str(receipt_path),
                                  "qa_directory_bytes": directory_bytes(directory)}), flush=True)
        finally:
            lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--max-new", type=int, default=5)
    args = parser.parse_args()
    audit(args.ffmpeg, max_new=args.max_new)


if __name__ == "__main__":
    main()
