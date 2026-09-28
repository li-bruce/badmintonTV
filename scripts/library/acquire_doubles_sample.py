"""Acquire one reviewed public doubles clip; preserve the original four-asset manifest."""

import argparse
import csv
import json
from pathlib import Path
from collections import Counter
import subprocess

from packages.library.cli import publication_audit, read_json_bounded
from packages.library.download import download
from packages.library.manifest import SplitRegistry, build_asset, sha256_file, write_manifest
from packages.library.probe import probe_video
from packages.library.storage import QuotaManager
from scripts.library.acquire_small_sample import MetadataBudget, write_json


ROOT = Path("D:/video")
CONFIG = Path("configs/library/doubles_sample.json")
SOURCE_REVISION = "14a6a74969f54adb57e013faa4fb24298794e985"
SOURCE_URL = "https://drive.usercontent.google.com/uc?id=1tncTXoI4IWBBL6qg8D9QtaE1f-EPZii5&export=download"
VIDEO_BYTES = 5_857_600
ANNOTATION_URL = "https://drive.usercontent.google.com/uc?id=1EdLWb-2xeCD3N0ZcnxLJbEesVnKl_wF4&export=download"
ANNOTATION_BYTES = 28_707


def verified_source(quota, url, relative, limit):
    path = quota.resolve_path(relative)
    receipt_path = quota.resolve_path(relative + ".download.json")
    if not path.exists():
        download(url, relative, quota=quota, max_bytes=limit, timeout=60)
    receipt = read_json_bounded(receipt_path, max_bytes=16_384)
    if (receipt.get("state") != "succeeded" or receipt.get("url") != url
            or path.stat().st_size > limit or sha256_file(path) != receipt.get("sha256")):
        raise ValueError("Existing source fails its bounded origin/hash receipt")
    return path, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    args = parser.parse_args()
    config = read_json_bounded(CONFIG, max_bytes=100_000)
    if (config.get("source_revision") != SOURCE_REVISION or config.get("source_url") != SOURCE_URL
            or config.get("max_download_bytes") != VIDEO_BYTES or config.get("batch_peak_bytes") != 50_000_000
            or config.get("relative_path") != "data/raw/dronebd/study-bd12-rally1-camera1.mp4"
            or config.get("camera_type") not in {"unknown", "overhead", "rear", "side"}
            or config.get("split") != "unassigned"):
        raise ValueError("This script accepts only the reviewed bounded doubles source")
    quota = QuotaManager()
    budget = MetadataBudget()
    original_manifest = quota.resolve_path("handoff/assets.v1.json")
    original_manifest_sha = sha256_file(original_manifest)
    original_assets = read_json_bounded(original_manifest)["assets"]
    original_hashes = {a["relative_path"]: sha256_file(ROOT / a["relative_path"]) for a in original_assets}
    with quota.reserve(config["batch_peak_bytes"], purpose="one public doubles video, source evidence, probe, QA and handoff"):
        readme_url = f"https://raw.githubusercontent.com/Ning-D/Drone_BD_ControlArea/{SOURCE_REVISION}/README.md"
        readme, readme_receipt = verified_source(quota, readme_url, "sources/dronebd/README.md", 100_000)
        video, receipt = verified_source(quota, SOURCE_URL, config["relative_path"][len("data/"):], VIDEO_BYTES)
        annotation, annotation_receipt = verified_source(
            quota, ANNOTATION_URL, "annotations/dronebd/BD12-Rally-1-1.csv", ANNOTATION_BYTES)
        if annotation.stat().st_size != ANNOTATION_BYTES:
            raise ValueError("Downloaded annotation size does not match publisher file metadata")
        with annotation.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            rows = list(reader)
        frames = [int(row["frame"]) for row in rows]
        annotation_inventory = {
            "schema_version": "1.0", "relative_path": annotation.relative_to(ROOT).as_posix(),
            "source_url": ANNOTATION_URL, "sha256": annotation_receipt["sha256"],
            "size_bytes": annotation_receipt["size_bytes"], "rows": len(rows), "fields": fields,
            "frame_min": min(frames), "frame_max": max(frames), "unique_frames": len(set(frames)),
            "contiguous_frames": frames == list(range(min(frames), max(frames) + 1)),
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "shuttle_nonnegative_rows": sum(float(row["shuttle_x"]) >= 0 and float(row["shuttle_y"]) >= 0 for row in rows),
            "association": "Publisher datacsv/BD12/Rally-1 folder",
            "alignment_status": "unverified", "converted_events": 0,
            "alignment_note": "Publisher README table assigns bounding-box/shuttle annotations to top-view only. This downloaded clip is rear-view; no frame or coordinate mapping is established. CSV frame numbers are not project milliseconds.",
            "status_semantics": "Not independently verified; counts are raw values, not confirmed event labels.",
            "rights": config["annotation_rights"]
        }
        write_json(quota.resolve_path("handoff/annotations.doubles.v1.json"), annotation_inventory, quota=quota, budget=budget)
        if video.stat().st_size != config["published_size_bytes"]:
            raise ValueError("Downloaded media size does not match publisher file metadata")
        report_path = quota.resolve_path("probes/dronebd-study-bd12-rally1-camera1.probe.json")
        if report_path.exists():
            report = read_json_bounded(report_path)
        else:
            pts_path = quota.resolve_path("probes/dronebd-study-bd12-rally1-camera1.pts.jsonl")
            if pts_path.exists():
                raise ValueError("Orphan doubles PTS retained; inspect before retry with a new attempt path")
            report = probe_video(video, ffprobe=args.ffprobe, ffmpeg=args.ffmpeg,
                                 pts_index_path=pts_path, max_pts_frames=100_000, max_pts_bytes=10_000_000)
            write_json(report_path, report, quota=quota, budget=budget)
        still = quota.resolve_path("qa/stills/dronebd-study-bd12-rally1-camera1.jpg")
        if not still.exists():
            still.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([args.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-ss", "1", "-i", str(video),
                            "-frames:v", "1", "-q:v", "3", "-fs", "2000000", "-n", str(still)],
                           check=True, capture_output=True, timeout=60)
        asset = build_asset(video, {
            "title": "Drone badminton doubles: Study_Videos / BD12 / Rally-1 / (1).mp4",
            "match_id": config["match_id"], "source_type": "dataset", "source_url": SOURCE_URL,
            "source_page": config["source_page"], "acquired_at": receipt["completed_at"],
            "camera_type": config["camera_type"], "discipline": "doubles", "players": [],
            "rights": config["rights"], "split": "unassigned",
            "provenance": {"dataset": "Drone_BD_ControlArea", "source_revision": SOURCE_REVISION,
                           "original_file_name": config["original_file_name"],
                           "official_folder_chain": config["official_folder_chain"],
                           "grouping_basis": config["grouping_basis"], "source_match_offset_ms": None,
                           "identity_status": "unconfirmed", "annotation_rights": config["annotation_rights"],
                           "visual_review": config.get("visual_review"),
                           "associated_csv": {"relative_path": annotation.relative_to(ROOT).as_posix(),
                                              "source_url": ANNOTATION_URL,
                                              "sha256": annotation_receipt["sha256"],
                                              "alignment_status": "unverified",
                                              "basis": annotation_inventory["alignment_note"]},
                           "publisher_sha256": None, "hash_verification": "Local SHA256 receipt plus publisher byte size; no publisher SHA256 supplied.",
                           "fine_labels": {"hand_technique": "unknown", "footwork": "unknown"},
                           "still_relative_path": still.relative_to(ROOT).as_posix(),
                           "source_readme_sha256": readme_receipt["sha256"]}
        }, report, storage_root=ROOT)
        target = quota.resolve_path("handoff/assets.doubles.v1.json")
        registry = quota.resolve_path("handoff/splits.doubles.v1.json")
        with publication_audit([target, registry], quota, reason="Additive doubles sample metadata", charge=budget.consume):
            write_manifest(target, [asset], storage_root=ROOT,
                           registry=SplitRegistry(registry, max_bytes=1_000_000), max_bytes=1_000_000)
        if original_manifest_sha != sha256_file(original_manifest):
            raise ValueError("Original four-asset manifest unexpectedly changed")
        for relative, expected in original_hashes.items():
            if sha256_file(ROOT / relative) != expected:
                raise ValueError("Original video unexpectedly changed")
        summary = {
            "schema_version": "1.0", "status": "verified", "asset_id": asset["asset_id"],
            "source_download_bytes": receipt["size_bytes"] + readme_receipt["size_bytes"] + annotation_receipt["size_bytes"],
            "round_download_limit_bytes": 1_000_000_000,
            "original_manifest_sha256_preserved": original_manifest_sha,
            "original_video_hashes_preserved": original_hashes, "doubles_manifest": target.relative_to(ROOT).as_posix(),
            "decode": asset["probe"]["decode"], "source_size_matches_public_metadata": True,
            "publisher_sha256_available": False, "camera_type": config["camera_type"],
            "readme_relative_path": readme.relative_to(ROOT).as_posix(),
            "annotation_relative_path": annotation.relative_to(ROOT).as_posix(),
            "annotation_alignment": "unverified"
        }
        write_json(quota.resolve_path("handoff/doubles-acquisition.v1.json"), summary, quota=quota, budget=budget)
    print(json.dumps({**summary, "capacity": quota.snapshot()}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
