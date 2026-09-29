"""Bounded acquisition of the complete 2026 Fine-Badminton training dataset."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from packages.library.cli import read_json_bounded
from packages.library.archive import extract_member, inspect_zip
from packages.library.download import DownloadError, download
from packages.library.manifest import build_asset, sha256_file, stable_asset_id, validate_asset
from packages.library.probe import probe_video
from packages.library.storage import QuotaManager
from scripts.library.acquire_small_sample import MetadataBudget, write_json


ROOT = Path("D:/video")
DATASET = "fine-badminton-2026-zenodo-20292976-v1.0"
BASE = "training/" + DATASET
API_URL = "https://zenodo.org/api/records/20292976"
CONTENT_URL = API_URL + "/files/Fine-Badminton.zip/content"
ZIP_BYTES = 6_455_837_331
PUBLISHER_MD5 = "cb3fcaca0ae9b08c564ac2a19ae4e7a0"


def dataset_source_metadata(member_name, sha256):
    stem = Path(member_name).stem
    # Publisher filenames establish conservative source groups, not facial
    # identity, current ranking, or independently verified match completeness.
    matches = {
        "2011 OSIM BWF World Superseries Finals-MS-MS - Group A-Chong Wei Lee vs. Peter Hoeg Gade": ("2011-finals-ms-group-a-lee-gade", ["Lee Chong Wei", "Peter Gade"]),
        "2011 OSIM BWF World Superseries Finals-MS-MS - Group B-Dan Lin vs. Kenichi Tago": ("2011-finals-ms-group-b-lin-tago", ["Lin Dan", "Kenichi Tago"]),
        "2014 THE STAR AUSTRALIAN BADMINTON OPEN-F-MS-Lin Dan (CHN) VS Simon Santoso (INA)": ("2014-australian-open-ms-final-lin-santoso", ["Lin Dan", "Simon Santoso"]),
        "SF - 2014 China Open -  Lin Dan vs Chou Tien Chen": ("2014-china-open-ms-semifinal-lin-chou", ["Lin Dan", "Chou Tien Chen"]),
        "TOTAL BWF World Championships 2017 _ Badminton F M3-MS _ Lin Dan vs Viktor Axelsen": ("2017-world-championships-ms-final-lin-axelsen", ["Lin Dan", "Viktor Axelsen"]),
        "[1080P] Lee Chong Wei vs Kento Momota - 2018 Badminton Asian Championship Semi Final": ("2018-asian-championships-ms-semifinal-lee-momota", ["Lee Chong Wei", "Kento Momota"]),
        "[4K50FPS] BEST MS MATCH！Lin Dan vs Lee Chong Wei _ 2011 World Championships": ("2011-world-championships-ms-lin-lee-round-unverified", ["Lin Dan", "Lee Chong Wei"]),
        "[Full] Badminton Lin Dan vs Lee Chong Wei 2010 Asian Games MS Final": ("2010-asian-games-ms-final-lin-lee", ["Lin Dan", "Lee Chong Wei"]),
        "[HD] SF - 2014 Asian Games - MS - LIN Dan vs LEE Chong Wei (1)": ("2014-asian-games-ms-semifinal-lin-lee", ["Lin Dan", "Lee Chong Wei"]),
    }
    slug, names = matches.get(stem, ("unverified-source-" + sha256[:16], []))
    return {"title": stem, "match_id": "fine-badminton-2026:" + slug,
            "players": [{"player_id": "publisher-" + name.lower().replace(" ", "-"),
                         "display_name": name, "identity_status": "unconfirmed"} for name in names],
            "identity_basis": "Publisher archive filename; no independent visual identity confirmation.",
            "source_match_offset_ms": None}


def announce(event, **values):
    print(json.dumps({"event": event, **values}, ensure_ascii=True), flush=True)


def extracted_relative_path(member_name):
    # Windows long paths are disabled on this host. Preserve publisher names
    # in the immutable archive and explicit inventory, with compact disk names.
    suffix = Path(member_name).suffix.lower() or ".bin"
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        raise ValueError("Archive member extension cannot form a portable short path")
    token = hashlib.sha256(member_name.encode("utf-8")).hexdigest()[:24]
    return BASE + "/extracted/" + token + suffix


def verified_download(quota, url, relative, limit, *, peak=None):
    path = quota.resolve_path(relative)
    if path.exists():
        receipt = read_json_bounded(path.with_name(path.name + ".download.json"), max_bytes=16384)
        if (receipt.get("state") != "succeeded" or receipt.get("url") != url
                or path.stat().st_size > limit or sha256_file(path) != receipt.get("sha256")):
            raise ValueError("Existing source does not match its origin/hash receipt")
        announce("verified_existing", relative_path=relative, size_bytes=path.stat().st_size)
        return path, receipt
    for attempt in range(1, 4):
        try:
            announce("download_started", relative_path=relative, attempt=attempt, max_bytes=limit)
            result = download(url, relative, quota=quota, max_bytes=limit, peak_bytes=peak, timeout=60)
            receipt = read_json_bounded(result.metadata_path, max_bytes=16384)
            announce("download_completed", size_bytes=result.size_bytes, sha256=result.sha256, resumed_bytes=result.resumed_bytes)
            return result.path, receipt
        except DownloadError as error:
            announce("download_failed", attempt=attempt, code=error.code, metadata_path=str(error.metadata_path))
            if attempt == 3 or error.code not in {"download_failed", "incomplete"}:
                raise
            time.sleep(attempt * 3)


def acquire(config, quota, budget):
    before = quota.snapshot()
    announce("capacity_preflight", capacity=before, download_peak_bytes=config["download_peak_bytes"])
    api, _ = verified_download(quota, API_URL, BASE + "/source/zenodo-record.json", 2_000_000)
    record = read_json_bounded(api, max_bytes=2_000_000)
    files = record.get("files", [])
    if not isinstance(files, list) or len(files) != 1:
        raise ValueError("Expected exactly one reviewed file in the official record")
    item = files[0]
    if (str(record.get("id")) != "20292976" or record.get("metadata", {}).get("version") != "v1.0"
            or item.get("key") != "Fine-Badminton.zip" or item.get("size") != ZIP_BYTES
            or item.get("checksum") != "md5:" + PUBLISHER_MD5
            or item.get("links", {}).get("self") != CONTENT_URL):
        raise ValueError("Official metadata changed from the reviewed size/hash/version/URL")
    archive, receipt = verified_download(quota, CONTENT_URL, BASE + "/source/Fine-Badminton.zip", ZIP_BYTES,
                                          peak=config["download_peak_bytes"])
    announce("publisher_md5_check_started", size_bytes=archive.stat().st_size)
    with archive.open("rb") as stream:
        actual_md5 = hashlib.file_digest(stream, "md5").hexdigest()
    status = "passed" if actual_md5 == PUBLISHER_MD5 and archive.stat().st_size == ZIP_BYTES else "failed"
    report = {"schema_version": "1.0", "dataset_id": DATASET, "usage_scope": "training_only",
              "status": status, "archive_relative_path": archive.relative_to(ROOT).as_posix(),
              "source_url": CONTENT_URL, "record_api_sha256": sha256_file(api),
              "size_bytes": archive.stat().st_size, "sha256": receipt["sha256"],
              "publisher_md5": PUBLISHER_MD5, "actual_md5": actual_md5,
              "capacity_before_download": before, "capacity_after_download": quota.snapshot(),
              "peak_reservation_bytes": config["download_peak_bytes"],
              "extraction_total_limit_bytes": config["extraction_total_limit_bytes"],
              "license_api": record.get("metadata", {}).get("license"),
              "license_description": record.get("metadata", {}).get("description"),
              "note": "Record API CC-BY and description noncommercial restriction are retained separately. Training only; video rights remain with original owners."}
    with quota.reserve(1_000_000, purpose="training dataset bounded acquisition report"):
        write_json(quota.resolve_path(BASE + "/acquisition.v1.json"), report, quota=quota, budget=budget)
    announce("publisher_md5_check_completed", status=status, md5=actual_md5, sha256=receipt["sha256"])
    if status != "passed":
        raise ValueError("Publisher size/MD5 mismatch; original retained and extraction prohibited")
    return archive, report


def verified_acquisition(quota):
    report = read_json_bounded(quota.resolve_path(BASE + "/acquisition.v1.json"))
    archive = quota.resolve_path(BASE + "/source/Fine-Badminton.zip")
    if (not isinstance(report, dict) or report.get("schema_version") != "1.0"
            or report.get("dataset_id") != DATASET or report.get("usage_scope") != "training_only"
            or report.get("source_url") != CONTENT_URL
            or report.get("archive_relative_path") != "data/" + BASE + "/source/Fine-Badminton.zip"
            or not isinstance(report.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", report["sha256"])):
        raise ValueError("Acquisition report must bind this training dataset, source path/URL, and a lowercase SHA256")
    if (report.get("status") != "passed" or report.get("actual_md5") != PUBLISHER_MD5
            or report.get("publisher_md5") != PUBLISHER_MD5 or report.get("size_bytes") != ZIP_BYTES
            or archive.stat().st_size != ZIP_BYTES):
        raise ValueError("Complete publisher-verified acquisition is required")
    # Every extract_member verifies this full archive SHA before and after
    # extracting; never treat a matching path/mtime as checksum verification.
    return archive, report


def extract_dataset(config, quota, budget):
    from packages.library.training import register_training_sources

    archive, acquisition = verified_acquisition(quota)
    inventory = inspect_zip(archive)
    files = [item for item in inventory if not item["is_directory"]]
    total = sum(item["size_bytes"] for item in files)
    if total > config["extraction_total_limit_bytes"]:
        raise ValueError("Archive uncompressed total exceeds reviewed 20GB limit")
    if any(item["encrypted"] or item["is_symlink"] for item in files):
        raise ValueError("Archive has an encrypted or symlink member")
    if any(item["compression"] not in (0, 8) for item in files):
        raise ValueError("Archive has unsupported compression")
    kinds = {suffix: sum(item["name"].lower().endswith(suffix) for item in files) for suffix in (".mp4", ".csv")}
    if kinds != {".mp4": 10, ".csv": 10}:
        raise ValueError("Publisher package file counts differ from the reviewed ten pairs")
    destinations = {item["name"]: extracted_relative_path(item["name"]) for item in files}
    if len(set(destinations.values())) != len(files):
        raise ValueError("Archive member storage paths must be unique")
    peak = total + 1_000_000_000
    announce("extraction_preflight", members=len(files), extracted_total_bytes=total,
             archive_bytes=ZIP_BYTES, archive_plus_extracted_bytes=ZIP_BYTES + total,
             batch_peak_reserved_bytes=peak, capacity=quota.snapshot())
    with quota.reserve(peak, purpose="complete training archive extraction plus receipts and inventory"):
        write_json(quota.resolve_path(BASE + "/archive-inventory.v1.json"),
                   {"schema_version": "1.0", "archive_sha256": acquisition["sha256"], "members": inventory,
                    "extracted_path_by_member": destinations,
                    "total_uncompressed_bytes": total, "usage_scope": "training_only"}, quota=quota, budget=budget)
        extracted = []
        # Read author README/LICENSE/CSV first, then expose fully verified media
        # in ascending size order. Never publish a partial archive member.
        ordered = sorted(files, key=lambda item: (item["name"].lower().endswith(".mp4"), item["size_bytes"], item["name"]))
        for item in ordered:
            relative = destinations[item["name"]]
            path = quota.resolve_path(relative)
            if path.exists():
                receipt = read_json_bounded(path.with_name(path.name + ".extract.json"), max_bytes=16_384)
                if (receipt.get("state") != "succeeded" or receipt.get("archive_sha256") != acquisition["sha256"]
                        or receipt.get("member_name") != item["name"] or receipt.get("size_bytes") != item["size_bytes"]
                        or sha256_file(path) != receipt.get("sha256")):
                    raise ValueError("Existing extracted source differs from its complete extraction receipt")
            else:
                announce("extract_started", member=item["name"], size_bytes=item["size_bytes"])
                result = extract_member(archive, item["name"], relative, quota=quota,
                                        max_bytes=max(1, item["size_bytes"]), expected_archive_sha256=acquisition["sha256"])
                receipt = read_json_bounded(result.metadata_path, max_bytes=16_384)
            entry = {"member_name": item["name"], "relative_path": path.relative_to(ROOT).as_posix(),
                     "size_bytes": receipt["size_bytes"], "sha256": receipt["sha256"], "usage_scope": "training_only"}
            if item["name"].lower().endswith(".mp4"):
                entry.update(dataset_source_metadata(item["name"], receipt["sha256"]))
                entry["asset_id"] = stable_asset_id(receipt["sha256"])
                entry["provenance"] = {"usage_scope": "training_only", "dataset_id": DATASET,
                                       "source_archive_sha256": acquisition["sha256"], "archive_member": item["name"]}
                registered = register_training_sources([entry], dataset_version=DATASET, quota=quota)
                announce("training_source_ready", **entry, registry_path=str(registered["registry_path"]))
            extracted.append(entry)
            write_json(quota.resolve_path(BASE + "/extracted-sources.v1.json"),
                       {"schema_version": "1.0", "complete": len(extracted) == len(files), "sources": extracted},
                       quota=quota, budget=budget)
    announce("extraction_completed", members=len(extracted), media_files=10, csv_files=10,
             extracted_bytes=total, capacity=quota.snapshot())
    return extracted


def probe_dataset(config, quota, budget, *, ffprobe, ffmpeg, workers, contracts_root=None):
    if contracts_root:
        import packages
        canonical_packages = str(Path(contracts_root).resolve() / "packages")
        sys.dont_write_bytecode = True
        previous_package_paths = list(packages.__path__)
        # Read-only reuse of coordinator-owned contracts; library modules that
        # are already imported remain this worktree's implementations.
        packages.__path__ = [canonical_packages, *packages.__path__]
        try:
            import packages.contracts as contracts
            if Path(contracts.__file__).resolve().parent != Path(canonical_packages) / "contracts":
                raise ValueError("Loaded contract implementation is not the requested read-only checkout")
            Asset = contracts.Asset
        finally:
            packages.__path__ = previous_package_paths
    else:
        from packages.contracts import Asset
    from packages.library.training import publish_training_manifest

    if "usage_scope" not in Asset.model_fields:
        raise ValueError("Training publication requires the new typed usage_scope contract")

    _, acquisition = verified_acquisition(quota)
    inventory = read_json_bounded(quota.resolve_path(BASE + "/extracted-sources.v1.json"))
    if inventory.get("complete") is not True:
        raise ValueError("Complete extraction inventory is required before probing")
    media = [item for item in inventory["sources"] if item["member_name"].lower().endswith(".mp4")]
    if len(media) != 10 or workers not in (1, 2):
        raise ValueError("Probe requires ten media and at most two CPU workers")
    source_receipt = read_json_bounded(quota.resolve_path(BASE + "/source/Fine-Badminton.zip.download.json"))

    def one(item):
        media_path = quota.resolve_path(item["relative_path"][len("data/"):])
        report_path = quota.resolve_path(BASE + "/probes/" + item["sha256"] + ".probe.json")
        if report_path.exists():
            report = read_json_bounded(report_path)
        else:
            announce("probe_started", relative_path=item["relative_path"])
            pts = quota.resolve_path(BASE + "/probes/" + item["sha256"] + "." + uuid.uuid4().hex + ".pts.jsonl")
            report = probe_video(media_path, ffprobe=ffprobe, ffmpeg=ffmpeg, timeout_seconds=7200,
                                 pts_index_path=pts, storage_root=ROOT,
                                 max_pts_frames=2_000_000, max_pts_bytes=128_000_000)
        metadata = {
            "title": item["title"], "match_id": item["match_id"], "source_type": "dataset",
            "usage_scope": "training_only", "source_url": CONTENT_URL, "source_page": config["source_page"],
            "acquired_at": source_receipt["completed_at"], "camera_type": "unknown", "discipline": "singles",
            "players": item["players"], "split": "unassigned",
            "rights": {"status": "research_only", "license_url": config["source_page"],
                       "evidence": "Author description restricts to non-commercial academic research; video copyright remains with original owners. API CC-BY metadata conflict retained in acquisition report.",
                       "allowed_uses": ["noncommercial_academic_research"]},
            "provenance": {**item["provenance"], "identity_basis": item["identity_basis"],
                           "source_match_offset_ms": None, "source_record_id": 20292976, "source_version": "v1.0",
                           "annotation_alignment": "unverified", "annotation_policy": "Original CSV preserved; frame-base and endpoint semantics require independent verification before Event conversion.",
                           "fine_labels": {"hand_technique": "unknown", "footwork": "unknown"},
                           "source_archive_publisher_md5": PUBLISHER_MD5}
        }
        asset = build_asset(media_path, metadata, report, storage_root=ROOT)
        return item, report_path, report, asset

    assets_by_sha = {}
    prior_manifest_path = quota.resolve_path("training/handoff/" + DATASET + ".assets.v1.json")
    if prior_manifest_path.exists():
        prior = read_json_bounded(prior_manifest_path)
        if (not isinstance(prior, dict) or prior.get("schema_version") != "1.0"
                or not isinstance(prior.get("assets"), list) or len(prior["assets"]) > len(media)):
            raise ValueError("Existing training manifest is invalid; preserving it unchanged")
        expected_sources = {item["sha256"]: item["relative_path"] for item in media}
        for prior_asset in prior["assets"]:
            verified = Asset.model_validate(prior_asset).model_dump(mode="json")
            if (verified.get("usage_scope") != "training_only"
                    or verified.get("provenance", {}).get("usage_scope") != "training_only"
                    or expected_sources.get(verified["sha256"]) != verified["relative_path"]
                    or verified["sha256"] in assets_by_sha):
                raise ValueError("Existing training manifest has conflicting scope/source/duplicates")
            validate_asset(verified, storage_root=ROOT)
            assets_by_sha[verified["sha256"]] = verified
        announce("prior_training_manifest_preserved", assets=len(assets_by_sha))
    completed_this_run = 0
    with quota.reserve(len(media) * 128_000_000 + 50_000_000, purpose="ten complete CPU decode/PTS indexes and bounded training handoff"):
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(one, item) for item in media]
            worker_errors = []
            try:
                for future in as_completed(futures):
                    if future.cancelled():
                        continue
                    try:
                        item, report_path, report, asset = future.result()
                    except Exception as error:
                        worker_errors.append(error)
                        # Stop queued work, but retain independently verified
                        # results from jobs which were already running. Their
                        # complete PTS indexes must not become orphaned merely
                        # because a different source failed.
                        for pending in futures:
                            pending.cancel()
                        announce("probe_worker_failed", error_type=type(error).__name__,
                                 error=str(error), completed_this_run=completed_this_run)
                        continue
                    if not report_path.exists():
                        write_json(report_path, report, quota=quota, budget=budget)
                    assets_by_sha[asset["sha256"]] = asset
                    completed_this_run += 1
                    published = publish_training_manifest(sorted(assets_by_sha.values(), key=lambda value: value["asset_id"]),
                                                          dataset_version=DATASET, quota=quota, asset_validator=Asset.model_validate)
                    announce("training_asset_ready", asset_id=asset["asset_id"], duration_ms=asset["duration_ms"],
                             decoded_frames=asset["probe"]["decode"]["frames"],
                             manifest_path=str(published["manifest_path"]), completed_this_run=completed_this_run,
                             published_assets=len(assets_by_sha), total_assets=len(media))
                if worker_errors:
                    raise worker_errors[0]
            except BaseException:
                # Do not start the rest of a long-video queue after a failure.
                # Already-running probes still finish within their own bounds
                # before the enclosing reservation can safely be released.
                for pending in futures:
                    pending.cancel()
                raise
        assets = list(assets_by_sha.values())
        summary = {"schema_version": "1.0", "usage_scope": "training_only", "dataset_id": DATASET,
                   "assets": len(assets), "total_duration_ms": sum(asset["duration_ms"] for asset in assets),
                   "total_decoded_frames": sum(asset["probe"]["decode"]["frames"] for asset in assets),
                   "source_claims": config["source_claims"], "annotation_alignment": "unverified",
                   "converted_events": 0, "publisher_md5_verified": True, "archive_sha256": acquisition["sha256"]}
        write_json(quota.resolve_path(BASE + "/probe-summary.v1.json"), summary, quota=quota, budget=budget)
    announce("all_media_probed", **summary, capacity=quota.snapshot())
    return assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["download", "extract", "probe"], default="download")
    parser.add_argument("--ffprobe")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    parser.add_argument("--contracts-root", help="Read-only checkout containing the new typed usage_scope contract")
    args = parser.parse_args()
    config = read_json_bounded("configs/library/fine_badminton_2026.json", max_bytes=100_000)
    if (config.get("dataset_id") != DATASET or config.get("download_url") != CONTENT_URL
            or config.get("size_bytes") != ZIP_BYTES or config.get("publisher_md5") != PUBLISHER_MD5
            or config.get("usage_scope") != "training_only" or config.get("split") != "unassigned"
            or config.get("download_peak_bytes") != 40_000_000_000
            or config.get("extraction_total_limit_bytes") != 20_000_000_000):
        raise ValueError("Only the reviewed bounded training source is supported")
    quota, budget = QuotaManager(), MetadataBudget()
    if args.phase == "download":
        acquire(config, quota, budget)
    elif args.phase == "extract":
        extract_dataset(config, quota, budget)
    elif args.phase == "probe":
        if not args.ffprobe or not args.ffmpeg:
            parser.error("probe phase requires --ffprobe and --ffmpeg")
        probe_dataset(config, quota, budget, ffprobe=args.ffprobe, ffmpeg=args.ffmpeg,
                      workers=args.workers, contracts_root=args.contracts_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
