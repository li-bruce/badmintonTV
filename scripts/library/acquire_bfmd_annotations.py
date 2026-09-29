"""Acquire only the public BFMD annotation/source package after the main ZIP writer."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

from packages.library.cli import read_json_bounded
from packages.library.download import DownloadError, download
from packages.library.manifest import sha256_file
from packages.library.storage import QuotaManager
from scripts.library.acquire_small_sample import MetadataBudget, write_json
from scripts.library.acquire_training_dataset import BASE as FINE_BASE, verified_acquisition


BASE = "training/bfmd"
TOTAL_BYTES = 1_825_439_459
TOTAL_FILES = 121
PEAK_BYTES = 2_500_000_000
REVIEWED_SELECTION_SHA256 = "4783822f916ca3b679cdba7d188103be18b6e9d35955a8da34a4f5afdc1d5877"
BLOCKING_CODES = {
    "drive_access_denied", "drive_rate_limited", "drive_access_blocked",
    "drive_confirmation_rejected", "drive_invalid_confirmation", "drive_html_limit", "drive_invalid_redirect",
}


def validate_config(config):
    if (not isinstance(config, dict) or config.get("schema_version") != "1.0"
            or config.get("dataset_id") != "bfmd" or config.get("usage_scope") != "training_only"
            or config.get("repository_commit") != "c7c7e8e4c815085dda42746f16e07f1172503312"):
        raise ValueError("BFMD acquisition requires the reviewed metadata snapshot")
    sources = config.get("files")
    if not isinstance(sources, list) or len(sources) != TOTAL_FILES:
        raise ValueError("Expected exactly 121 reviewed non-video source files")
    seen_paths, seen_ids = set(), set()
    total = 0
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("BFMD source entries must be objects")
        relative, file_id, size = item.get("relative_path"), item.get("google_drive_id"), item.get("expected_bytes")
        if (item.get("kind"), item.get("mime_type")) not in {
            ("annotation_backup_archive_only", "application/x-trash"),
            ("annotation_json", "application/json"), ("documentation", "text/markdown"),
            ("helper_source_archive_only", "text/x-python"), ("index_csv", "text/csv"),
        }:
            raise ValueError("Only reviewed non-media BFMD kinds/MIME types may be acquired")
        if (not isinstance(relative, str) or relative.startswith("/") or "\\" in relative
                or any(part in {"", ".", ".."} or ":" in part for part in relative.split("/"))
                or Path(relative).suffix.lower() not in {".json", ".bak", ".csv", ".md", ".py"}):
            raise ValueError("BFMD source path must be a reviewed annotation/document/script, never media")
        if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", file_id):
            raise ValueError("Invalid public Drive file id")
        if item.get("url") != f"https://drive.usercontent.google.com/uc?id={file_id}&export=download":
            raise ValueError("BFMD download URL must match its observed public file id")
        if type(size) is not int or not 0 < size <= 200_000_000:
            raise ValueError("Per-file BFMD size is outside the reviewed finite bound")
        if relative.casefold() in seen_paths or file_id in seen_ids:
            raise ValueError("Duplicate BFMD path or source id")
        seen_paths.add(relative.casefold())
        seen_ids.add(file_id)
        total += size
    if total != TOTAL_BYTES:
        raise ValueError("BFMD source bytes changed from the independently reviewed total")
    selected = sorted([{key: item[key] for key in
                        ("relative_path", "google_drive_id", "expected_bytes", "kind", "mime_type", "url")}
                       for item in sources], key=lambda item: item["relative_path"])
    digest = hashlib.sha256(json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if digest != REVIEWED_SELECTION_SHA256:
        raise ValueError("BFMD selected file identities changed from the reviewed snapshot")
    return sources


def main():
    from packages.library.drive import open_drive_response

    argparse.ArgumentParser(description=__doc__).parse_args()
    config = read_json_bounded("configs/library/bfmd_sources.json", max_bytes=500_000)
    sources = validate_config(config)
    quota, budget = QuotaManager(), MetadataBudget(limit=50_000_000)
    if quota.resolve_path(FINE_BASE + "/source/Fine-Badminton.zip.lock").exists():
        raise ValueError("Main complete-video ZIP writer is active; BFMD must wait")
    verified_acquisition(quota)
    print(json.dumps({"event": "bfmd_preflight", "files": len(sources), "expected_bytes": TOTAL_BYTES,
                      "peak_reserved_bytes": PEAK_BYTES, "capacity": quota.snapshot()}), flush=True)
    records = []
    blocked = None
    with quota.reserve(PEAK_BYTES, purpose="BFMD annotations and five archive-only source files; no videos"):
        write_json(quota.resolve_path(BASE + "/source-catalog.v1.json"), config, quota=quota, budget=budget)
        for index, item in enumerate(sorted(sources, key=lambda value: (value["relative_path"].startswith("annotations/"), value["expected_bytes"], value["relative_path"])), 1):
            relative = BASE + "/raw/" + item["relative_path"]
            path = quota.resolve_path(relative)
            entry = {**item, "relative_path": path.relative_to(quota.project_root).as_posix(),
                     "usage_scope": "training_only", "video_alignment": "unmatched",
                     "provenance": {"usage_scope": "training_only", "dataset_id": "bfmd",
                                    "repository_commit": config["repository_commit"]}}
            try:
                if path.exists():
                    receipt = read_json_bounded(path.with_name(path.name + ".download.json"), max_bytes=16_384)
                    if (receipt.get("state") != "succeeded" or receipt.get("url") != item["url"]
                            or path.stat().st_size != item["expected_bytes"] or sha256_file(path) != receipt.get("sha256")):
                        raise ValueError("Existing BFMD file does not match its original bounded receipt")
                    reused = True
                else:
                    reused = False
                    for attempt in range(1, 4):
                        try:
                            result = download(item["url"], relative, quota=quota, max_bytes=item["expected_bytes"],
                                              timeout=60, response_opener=open_drive_response)
                            receipt = read_json_bounded(result.metadata_path, max_bytes=16_384)
                            break
                        except DownloadError as error:
                            if attempt == 3 or error.code not in {"download_failed", "incomplete", "drive_network_error"}:
                                raise
                            time.sleep(attempt * 3)
                    if path.stat().st_size != item["expected_bytes"]:
                        raise ValueError("BFMD file size differs from publisher public metadata")
                entry.update({"download_status": "verified_existing" if reused else "downloaded",
                              "sha256": receipt["sha256"], "size_bytes": path.stat().st_size,
                              "acquired_at": receipt["completed_at"], "publisher_hash_available": False})
            except (DownloadError, ValueError, OSError) as error:
                entry.update({"download_status": "failed", "error": {"code": getattr(error, "code", type(error).__name__)}})
                if entry["error"]["code"] in BLOCKING_CODES:
                    blocked = entry["error"]["code"]
            records.append(entry)
            summary = {"schema_version": "1.0", "dataset_id": "bfmd", "usage_scope": "training_only",
                       "complete": index == len(sources) and all(record["download_status"] != "failed" for record in records),
                       "files": records, "source_catalog_sha256": sha256_file(quota.resolve_path(BASE + "/source-catalog.v1.json")),
                       "media_files_downloaded": 0, "assets_created": 0, "converted_events": 0,
                       "video_alignment": "unmatched", "rights": config["rights"],
                       "scripts_executed": False, "backup_is_active_annotation": False}
            summary["blocked_reason"] = blocked
            summary["not_attempted_file_count"] = len(sources) - index
            summary["acquisition_status"] = ("BLOCKED" if blocked else "PASS" if summary["complete"]
                                             else "FAIL" if index == len(sources) else "IN_PROGRESS")
            write_json(quota.resolve_path("training/handoff/bfmd.annotations.v1.json"), summary, quota=quota, budget=budget)
            print(json.dumps({"event": "bfmd_file_finished", "index": index, "total": len(sources),
                              "relative_path": entry["relative_path"], "status": entry["download_status"],
                              "error": entry.get("error")}, ensure_ascii=True), flush=True)
            if blocked:
                print(json.dumps({"event": "bfmd_blocked", "code": blocked,
                                  "remaining_not_attempted": len(sources) - index}), flush=True)
                break
    failures = sum(record["download_status"] == "failed" for record in records)
    print(json.dumps({"event": "bfmd_completed", "files": len(records), "failures": failures,
                      "blocked_reason": blocked, "not_attempted": len(sources) - len(records),
                      "verified_bytes": sum(record.get("size_bytes", 0) for record in records),
                      "capacity": quota.snapshot()}), flush=True)
    return 2 if blocked else (1 if failures else 0)


if __name__ == "__main__":
    raise SystemExit(main())
