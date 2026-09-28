"""Pinned, bounded real-data sample. Run as python -m scripts.library.acquire_small_sample."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from packages.library.cli import MAX_JSON_BYTES, publication_audit, read_json_bounded
from packages.library.download import download
from packages.library.manifest import SplitRegistry, build_asset, write_manifest
from packages.library.probe import probe_video
from packages.library.storage import QuotaManager


ROOT = Path("D:/video")
DATA = ROOT / "data"
PTS_MAX_BYTES = 5_000_000
METADATA_BUDGET_BYTES = 10_000_000
REGISTRY_MAX_BYTES = 1_000_000
PINNED_HF_REVISION = "ff86093a51efdf9a243a0635704952d404e99e52"
PINNED_COACHAI_REVISION = "45517f7d4cb936b03f3eabf939cc7959d39226fe"
PINNED_VIDEOS = {
    "video_000001": (642017, "057d2d6dd52eb892719b36aa1f017ac6272e19502dd93efbc0ca9f97f35b6fe0"),
    "video_000002": (591764, "9051c7ba4daba25f1206555d73c5ee2f5c5dfff8f5749a2cc883571379536956"),
    "video_000003": (499766, "58aecdab108bd1e1332fb5b45811cc5c4f6e0f2f5987b7da3e98c7345ddc1a13"),
    "video_001951": (669106, "5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90"),
}
QA_FILES = {"benchmark_action_classification.json", "benchmark_round_comment_updated.json"}
SHUTTLESET_FILES = {
    "ShuttleSet/set/Anders_Antonsen_Viktor_Axelsen_HSBC_BWF_WORLD_TOUR_FINALS_2020_Finals/set1.csv",
    "ShuttleSet/README.md", "LICENSE",
}


class MetadataBudget:
    """Bound cumulative generated JSON bytes beneath the batch reservation."""
    def __init__(self, limit=METADATA_BUDGET_BYTES):
        self.limit, self.used = limit, 0

    def consume(self, size):
        if self.used + size > self.limit:
            raise ValueError("Generated metadata exceeds the reserved metadata budget")
        self.used += size


def validate_config(config):
    if (not isinstance(config, dict) or config.get("schema_version") != "1.0"
            or config.get("hf_revision") != PINNED_HF_REVISION
            or config.get("coachai_revision") != PINNED_COACHAI_REVISION):
        raise ValueError("Small-sample acquisition requires the reviewed pinned revisions")
    videos = config.get("videos")
    if not isinstance(videos, list) or not 1 <= len(videos) <= len(PINNED_VIDEOS):
        raise ValueError("Choose a nonempty subset of the four reviewed sample videos")
    seen = set()
    for item in videos:
        uid = item.get("video_uid")
        if not isinstance(uid, str) or not re.fullmatch(r"video_[0-9]{6}", uid) or uid in seen:
            raise ValueError("Invalid or duplicate video_uid")
        seen.add(uid)
        if (uid not in PINNED_VIDEOS or type(item.get("size_bytes")) is not int
                or (item["size_bytes"], item.get("sha256")) != PINNED_VIDEOS[uid]):
            raise ValueError("Video size/hash must match the reviewed pinned sample")
        visual = item.get("visual_observation", {})
        if not isinstance(visual, dict):
            raise ValueError("visual_observation must be an object")
        if visual.get("camera_type", "unknown") not in {"rear", "side", "overhead", "handheld", "mixed", "unknown"}:
            raise ValueError("Invalid observed camera_type")
        if visual.get("discipline", "unknown") not in {"singles", "doubles", "unknown"}:
            raise ValueError("Invalid observed discipline")
        names = visual.get("scoreboard_names", [])
        if not isinstance(names, list) or len(names) > 4 or any(not isinstance(name, str) or len(name) > 100 for name in names):
            raise ValueError("scoreboard_names must contain at most four short text observations")
        still = visual.get("still_relative_path")
        if still is not None and (not isinstance(still, str) or not re.fullmatch(r"data/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.(?:png|jpg|jpeg)", still)
                                  or any(part in {".", ".."} for part in still.split("/"))):
            raise ValueError("Observed still must have a safe data-relative image path")
    for field, allowed in (("qa_files", QA_FILES), ("shuttleset_files", SHUTTLESET_FILES)):
        files = config.get(field)
        if not isinstance(files, list) or not files or any(not isinstance(name, str) or name not in allowed for name in files) or len(set(files)) != len(files):
            raise ValueError(f"{field} must be a nonempty subset of reviewed source paths")
    if "LICENSE" not in config["shuttleset_files"]:
        raise ValueError("ShuttleSet acquisition must retain its source LICENSE")
    if config.get("grouping", {}).get("match_id") != "unknown" or config["grouping"].get("split") != "unassigned":
        raise ValueError("Unresolved sample matches must remain unknown/unassigned")
    minimum = len(videos) * PTS_MAX_BYTES + METADATA_BUDGET_BYTES
    if type(config.get("batch_peak_bytes")) is not int or config["batch_peak_bytes"] < minimum:
        raise ValueError(f"batch_peak_bytes must reserve at least {minimum} bytes")
    return config


def write_json(path, value, *, quota, budget, replace_existing=True):
    path = quota.resolve_path(Path(path).relative_to(quota.data_root))
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("Serialized JSON exceeds 10 MB")
    if not replace_existing and path.exists():
        raise FileExistsError("Immutable probe report already exists")
    budget.consume(len(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with publication_audit([path], quota, reason="Small-sample handoff regeneration", charge=budget.consume):
            with temp.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if replace_existing:
                os.replace(temp, path)
            else:
                os.link(temp, path)
                temp.unlink()
    finally:
        if temp.exists():
            temp.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/library/small_sample.json")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    config = validate_config(read_json_bounded(args.config, max_bytes=100_000))
    quota = QuotaManager()
    budget = MetadataBudget()
    results = []
    errors = []
    acquired_at = {}
    revision = config["hf_revision"]
    base = f"https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark/resolve/{revision}/"
    coach_base = f'https://raw.githubusercontent.com/wywyWang/CoachAI-Projects/{config["coachai_revision"]}/'

    def fetch(url, relative, max_bytes, sha=None):
        dest = quota.resolve_path(relative)
        receipt_path = quota.resolve_path(relative + ".download.json")
        # Re-running never overwrites existing raw files. Verify recorded origin and hash.
        if dest.exists():
            with dest.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            receipt = read_json_bounded(receipt_path, max_bytes=16_384) if receipt_path.exists() else {}
            recorded = receipt.get("sha256")
            if (actual != (sha or recorded) or dest.stat().st_size > max_bytes
                    or receipt.get("url") != url or receipt.get("state") != "succeeded"):
                raise ValueError(f"Existing source fails trusted hash/size verification: {relative}")
            result = {"relative_path": "data/" + relative, "size_bytes": dest.stat().st_size,
                      "sha256": actual, "source_url": url, "download_status": "verified_existing"}
        else:
            item = download(url, relative, quota=quota, max_bytes=max_bytes,
                            expected_sha256=sha, timeout=45)
            result = {"relative_path": "data/" + relative, "size_bytes": item.size_bytes,
                      "sha256": item.sha256, "source_url": url, "download_status": "downloaded"}
            receipt = read_json_bounded(receipt_path, max_bytes=16_384)
        acquired_at[relative] = receipt.get("completed_at") or receipt.get("created_at")
        if not acquired_at[relative]:
            raise ValueError("Verified download receipt lacks its original acquisition time")
        results.append(result)
        print(json.dumps(result), flush=True)
        return dest

    # An extra conservative batch reservation covers probes, metadata and handoff,
    # while every download holds its own independently enforced byte reservation.
    with quota.reserve(config["batch_peak_bytes"], purpose="pinned small sample and metadata"):
        fetch(base + "README.md", "sources/finebadmintonbenchmark/README.md", 100_000)
        for name in config["qa_files"]:
            fetch(base + "finebadmintonbenchmark/" + name,
                  "annotations/finebadmintonbenchmark/" + name, 2_000_000)
        for name in config["shuttleset_files"]:
            fetch(coach_base + name, "annotations/shuttleset/" + name, 500_000)
        assets = []
        for item in config["videos"]:
            uid = item["video_uid"]
            url = base + "hf_video_clips_qa/" + uid + ".mp4"
            path = fetch(url, "raw/finebadmintonbenchmark/" + uid + ".mp4",
                         item["size_bytes"], item["sha256"])
            if args.download_only:
                continue
            try:
                report_path = quota.resolve_path("probes/" + uid + ".probe.json")
                if report_path.exists():
                    probe = read_json_bounded(report_path)
                    if probe.get("probe", {}).get("source_sha256") != item["sha256"]:
                        raise ValueError("Retained probe does not match the pinned original")
                else:
                    index_path = quota.resolve_path("probes/" + uid + ".pts.jsonl")
                    recovery = None
                    if index_path.exists():
                        original_index = index_path
                        index_path = quota.resolve_path("probes/" + uid + ".attempt-" + uuid.uuid4().hex + ".pts.jsonl")
                        recovery = {"reason": "PTS exists without a probe report; preserved and generated a new attempt",
                                    "retained_index_relative_path": original_index.relative_to(ROOT).as_posix()}
                    probe = probe_video(path, ffprobe=args.ffprobe, ffmpeg=args.ffmpeg,
                                        pts_index_path=index_path,
                                        max_pts_frames=100_000, max_pts_bytes=PTS_MAX_BYTES)
                    if recovery:
                        probe["probe"]["recovery"] = recovery
                    write_json(report_path, probe, quota=quota, budget=budget, replace_existing=False)
                visual = item.get("visual_observation", {})
                if visual.get("still_relative_path"):
                    quota.resolve_path(visual["still_relative_path"][len("data/"):])
                metadata = {
                    "title": "FineBadmintonBenchmark " + uid,
                    "match_id": config["grouping"]["match_id"],
                    "source_type": "dataset", "source_url": url,
                    "source_page": "https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark",
                    "acquired_at": acquired_at["raw/finebadmintonbenchmark/" + uid + ".mp4"],
                    "camera_type": visual.get("camera_type", "unknown"),
                    "discipline": visual.get("discipline", "unknown"), "players": [],
                    "rights": config["video_rights"], "split": "unassigned",
                    "provenance": {
                        "dataset": "FineBadmintonBenchmark", "dataset_revision": revision,
                        "video_uid": uid, "publisher_sha256": item["sha256"],
                        "annotation_rights": config["annotation_rights"]["finebadminton"],
                        "source_match_offset_ms": None, "grouping": config["grouping"],
                        "identity_status": "unconfirmed",
                        "visual_observation": {**visual, "identity_status": "unconfirmed",
                                               "identity_note": "Scoreboard text observation only; player identity and canonical match are unconfirmed."},
                        "label_constraints": {"hand_technique": "unknown", "footwork": "unknown"},
                        "intended_use": "local research smoke test; public footage rights unresolved"
                    }
                }
                assets.append(build_asset(path, metadata, probe, storage_root=ROOT))
            except Exception as exc:
                errors.append({"video_uid": uid, "stage": "probe", "error": type(exc).__name__, "message": str(exc)})
        inventory = []
        for name in config["qa_files"]:
            source = quota.resolve_path("annotations/finebadmintonbenchmark/" + name)
            rows = read_json_bounded(source, max_bytes=2_000_000)
            selected = [{"source_row_index_zero_based": i, "original": row} for i, row in enumerate(rows)
                        if row["video_uid"] in {v["video_uid"] for v in config["videos"]}]
            inventory.append({"relative_path": source.relative_to(ROOT).as_posix(), "records": len(rows),
                              "matched_sample_records": selected, "license": config["annotation_rights"]["finebadminton"],
                              "conversion": "Original QA retained. No timestamps/player identity/fine-technique Events invented."})
        for name in config["shuttleset_files"]:
            if name.endswith(".csv"):
                source = quota.resolve_path("annotations/shuttleset/" + name)
                with source.open(encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    rows = list(reader)
                inventory.append({"relative_path": source.relative_to(ROOT).as_posix(), "records": len(rows),
                                  "columns": reader.fieldnames, "license": config["annotation_rights"]["shuttleset"],
                                  "paired_video_asset_id": None,
                                  "conversion": "Original CSV retained; referenced match video absent, so no Event conversion."})
        write_json(DATA / "handoff" / "annotations.v1.json", {"schema_version": "1.0", "annotations": inventory}, quota=quota, budget=budget)
        write_json(DATA / "handoff" / "downloads.v1.json", {"schema_version": "1.0", "downloads": results, "errors": errors}, quota=quota, budget=budget)
        if assets:
            manifest_path = quota.resolve_path("handoff/assets.v1.json")
            registry_path = quota.resolve_path("handoff/splits.v1.json")
            manifest_bytes = len((json.dumps({"schema_version": "1.0", "assets": assets}, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
            budget.consume(manifest_bytes + REGISTRY_MAX_BYTES)
            with publication_audit([manifest_path, registry_path], quota, reason="Small-sample Asset and split snapshot regeneration", charge=budget.consume):
                write_manifest(manifest_path, assets, storage_root=ROOT,
                               registry=SplitRegistry(registry_path, max_bytes=REGISTRY_MAX_BYTES),
                               max_bytes=min(manifest_bytes, MAX_JSON_BYTES))
        write_json(DATA / "handoff" / "sample_config.v1.json", config, quota=quota, budget=budget)
    capacity = quota.snapshot()
    capacity["snapshot_phase"] = "after_batch_before_capacity_publication"
    capacity["captured_at"] = datetime.now(timezone.utc).isoformat()
    with quota.reserve(2 * METADATA_BUDGET_BYTES, purpose="bounded capacity snapshot and audit"):
        write_json(DATA / "handoff" / "capacity.v1.json", capacity, quota=quota, budget=MetadataBudget())
    final_capacity = quota.snapshot()
    print(json.dumps({"assets_published": len(assets), "download_count": len(results), "errors": errors,
                      "final_active_reserved_bytes": final_capacity["active_reserved_bytes"],
                      "final_owner_used_bytes": final_capacity["owner_used_bytes"]}), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
