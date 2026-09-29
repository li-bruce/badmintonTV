"""Acquire only the public BFMD annotation/source package after the main ZIP writer."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import re
import threading
import time
import uuid

from packages.library.download import DownloadError, download
from packages.library.manifest import sha256_file
from packages.library.storage import QuotaManager
from scripts.library.acquire_small_sample import MetadataBudget, write_json
from scripts.library.acquire_training_dataset import BASE as FINE_BASE, verified_acquisition


BASE = "training/bfmd"
TOTAL_BYTES = 1_825_439_459
TOTAL_FILES = 121
PEAK_BYTES = 2_500_000_000
HANDOFF_PATH = "training/handoff/bfmd.annotations.v1.json"
PROGRESS_PATH = "training/handoff/bfmd.acquisition-progress.v1.json"
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


def _strict_json(path, max_bytes=10_000_000):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key in BFMD state")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("Non-finite JSON number in BFMD state")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("BFMD state exceeds its JSON byte bound")
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=nonfinite)


@contextmanager
def _handoff_lock(quota, run_id):
    path = quota.resolve_path(HANDOFF_PATH + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            json.dump({"pid": os.getpid(), "run_id": run_id, "stop_protocol": "finish_active_v1"}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        path.unlink()


def _stop_path(quota, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("Invalid acquisition run id")
    return quota.resolve_path(BASE + "/control/stop-" + run_id + ".json")


def request_stop(quota):
    """Signal only the current new-version owner; retain the marker as evidence."""
    owner = _strict_json(quota.resolve_path(HANDOFF_PATH + ".lock"), 1024)
    if (not isinstance(owner, dict) or owner.get("stop_protocol") != "finish_active_v1"
            or type(owner.get("pid")) is not int or owner["pid"] <= 0):
        raise ValueError("The current owner does not support graceful stop; no signal written")
    path = _stop_path(quota, owner.get("run_id"))
    payload = (json.dumps({"run_id": owner["run_id"], "owner_pid": owner["pid"],
                           "requested_at": datetime.now(timezone.utc).isoformat(),
                           "action": "finish active files, publish successes, stop dispatch"}) + "\n").encode("ascii")
    with quota.reserve(65_536, purpose="BFMD run-scoped graceful stop marker"):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
    return path


def _verified_receipt(path, item):
    receipt = _strict_json(path.with_name(path.name + ".download.json"), 16_384)
    digest = receipt.get("sha256") if isinstance(receipt, dict) else None
    completed = receipt.get("completed_at") if isinstance(receipt, dict) else None
    if (not isinstance(receipt, dict) or receipt.get("state") != "succeeded"
            or receipt.get("url") != item["url"] or not path.is_file()
            or path.stat().st_size != item["expected_bytes"]
            or type(receipt.get("size_bytes")) is not int or receipt["size_bytes"] != item["expected_bytes"]
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or sha256_file(path) != digest or not isinstance(completed, str)):
        raise ValueError("Existing BFMD file does not match its original bounded receipt")
    if datetime.fromisoformat(completed.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("BFMD acquisition timestamp must include timezone")
    return receipt


def _previous_verified(config, sources, quota):
    """Validate the complete old snapshot before any acquisition/output rewrite."""
    catalog = quota.resolve_path(BASE + "/source-catalog.v1.json")
    handoff = quota.resolve_path(HANDOFF_PATH)
    if catalog.exists():
        previous_config = _strict_json(catalog, 500_000)
        validate_config(previous_config)
        if previous_config != config:
            raise ValueError("Existing BFMD source catalog differs from the reviewed current configuration")
    if not handoff.exists():
        return {}
    prior = _strict_json(handoff)
    if (not isinstance(prior, dict) or prior.get("schema_version") != "1.0"
            or prior.get("dataset_id") != "bfmd" or prior.get("usage_scope") != "training_only"
            or type(prior.get("complete")) is not bool or not isinstance(prior.get("files"), list)
            or len(prior["files"]) > len(sources) or not catalog.is_file()
            or prior.get("source_catalog_sha256") != sha256_file(catalog)
            or prior.get("rights") != config["rights"] or prior.get("video_alignment") != "unmatched"
            or any(type(prior.get(key)) is not int or prior[key] != 0
                   for key in ("media_files_downloaded", "assets_created", "converted_events"))
            or prior.get("scripts_executed") is not False or prior.get("backup_is_active_annotation") is not False):
        raise ValueError("Existing BFMD handoff has invalid schema/source/scope; preserving it unchanged")
    selected = {item["google_drive_id"]: item for item in sources}
    records, seen = {}, set()
    for record in prior["files"]:
        if not isinstance(record, dict) or not isinstance(record.get("google_drive_id"), str):
            raise ValueError("Existing BFMD handoff entry must identify a reviewed source")
        source_id = record["google_drive_id"]
        item = selected.get(source_id)
        if item is None or source_id in seen:
            raise ValueError("Existing BFMD source is unknown or duplicated")
        seen.add(source_id)
        path = quota.resolve_path(BASE + "/raw/" + item["relative_path"])
        provenance = record.get("provenance")
        if (any(record.get(key) != value for key, value in item.items() if key not in {"relative_path", "download_status"})
                or record.get("relative_path") != path.relative_to(quota.project_root).as_posix()
                or record.get("usage_scope") != "training_only" or record.get("video_alignment") != "unmatched"
                or not isinstance(provenance, dict) or provenance.get("usage_scope") != "training_only"
                or provenance.get("dataset_id") != "bfmd" or provenance.get("repository_commit") != config["repository_commit"]):
            raise ValueError("Existing BFMD entry does not match its fixed source/scope")
        status = record.get("download_status")
        if status == "failed":  # Earlier incremental summaries also contained failures.
            if not isinstance(record.get("error"), dict) or not isinstance(record["error"].get("code"), str):
                raise ValueError("Existing BFMD failure record is malformed")
            continue
        if status not in {"downloaded", "verified_existing"}:
            raise ValueError("Existing BFMD entry has an unsupported verification status")
        receipt = _verified_receipt(path, item)
        if (record.get("sha256") != receipt["sha256"] or type(record.get("size_bytes")) is not int
                or record["size_bytes"] != item["expected_bytes"] or record.get("acquired_at") != receipt["completed_at"]
                or record.get("publisher_hash_available") is not False):
            raise ValueError("Existing BFMD verified record disagrees with its bytes/receipt")
        records[source_id] = record
    if prior["complete"] and len(records) != len(sources):
        raise ValueError("Existing complete BFMD handoff omits verified sources")
    return records


def acquire_annotations(config, quota, budget, *, response_opener, workers=1):
    """Acquire an already authorized package; main enforces the prior ZIP gate."""
    if type(workers) is not int or workers not in (1, 2):
        raise ValueError("workers must be 1 or 2")
    sources = validate_config(config)
    run_id = uuid.uuid4().hex
    with quota.reserve(PEAK_BYTES, purpose="BFMD annotations and five archive-only source files; no videos"), _handoff_lock(quota, run_id):
        verified = _previous_verified(config, sources, quota)
        catalog = quota.resolve_path(BASE + "/source-catalog.v1.json")
        if not catalog.exists():
            write_json(catalog, config, quota=quota, budget=budget)
        catalog_sha = sha256_file(catalog)
        records = []
        stop_path = _stop_path(quota, run_id)
        def progress(status, *, blocked_reason=None):
            value = {"schema_version": "1.0", "dataset_id": "bfmd", "usage_scope": "training_only",
                     "run_id": run_id, "updated_at": datetime.now(timezone.utc).isoformat(),
                     "source_catalog_sha256": catalog_sha, "acquisition_status": status, "blocked_reason": blocked_reason,
                     "files_attempted_this_run": records, "not_attempted_this_run": len(sources) - len(records),
                     "verified_handoff_files": len(verified), "trusted_handoff_relative_path": "data/" + HANDOFF_PATH,
                     "workers": workers, "stop_protocol": "finish_active_v1",
                     "stop_requested": stop_path.exists(),
                     "stop_marker_relative_path": stop_path.relative_to(quota.project_root).as_posix()}
            write_json(quota.resolve_path(PROGRESS_PATH), value, quota=quota, budget=budget)
        progress("IN_PROGRESS")
        try:
            result = _acquire_items(config, sources, quota, budget, response_opener, verified, records,
                                    catalog_sha, progress, workers=workers, stop_path=stop_path)
        except BaseException as error:
            # Best-effort reporting must not hide the original failure or interrupt.
            try:
                progress("INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAIL",
                         blocked_reason=getattr(error, "code", None))
            except Exception as report_error:
                error.add_note(f"BFMD run progress could not be saved: {type(report_error).__name__}")
            raise
    print(json.dumps({"event": "bfmd_capacity_after_writer_release", "capacity": quota.snapshot()}), flush=True)
    return result


def _acquire_one(config, item, quota, response_opener, *, prior=None, halt=None):
    """Workers own only their unique file/receipt; never publish shared metadata."""
    relative = BASE + "/raw/" + item["relative_path"]
    entry = {**item, "relative_path": "data/" + relative,
             "usage_scope": "training_only", "video_alignment": "unmatched",
             "provenance": {"usage_scope": "training_only", "dataset_id": "bfmd",
                            "repository_commit": config["repository_commit"]}}
    try:
        path = quota.resolve_path(relative)
        if path.exists():
            receipt = _verified_receipt(path, item)
            reused = True
        else:
            if prior is not None:
                raise ValueError("Previously verified BFMD file disappeared after preflight")
            reused = False
            for attempt in range(1, 4):
                try:
                    result = download(item["url"], relative, quota=quota, max_bytes=item["expected_bytes"],
                                      timeout=60, response_opener=response_opener)
                    receipt = _verified_receipt(result.path, item)
                    break
                except DownloadError as error:
                    if (attempt == 3 or error.code not in {"download_failed", "incomplete", "drive_network_error"}
                            or (halt is not None and halt.wait(attempt * 3))):
                        raise
                    if halt is None:
                        time.sleep(attempt * 3)
            if path.stat().st_size != item["expected_bytes"]:
                raise ValueError("BFMD file size differs from publisher public metadata")
        if prior is not None and (receipt["sha256"] != prior["sha256"]
                                  or receipt["size_bytes"] != prior["size_bytes"]
                                  or receipt["completed_at"] != prior["acquired_at"]):
            raise ValueError("Previously verified BFMD bytes/receipt changed after preflight")
        entry.update({"download_status": "verified_existing" if reused else "downloaded",
                      "sha256": receipt["sha256"], "size_bytes": path.stat().st_size,
                      "acquired_at": receipt["completed_at"], "publisher_hash_available": False})
        return entry, None
    except BaseException as error:
        if halt is not None:
            halt.set()  # Stop dispatch immediately, even before main consumes this future.
        entry.update({"download_status": "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed",
                      "error": {"code": getattr(error, "code", type(error).__name__)}})
        return entry, error


def _acquire_items(config, sources, quota, budget, response_opener, verified, records, catalog_sha, progress,
                   *, workers, stop_path):
    blocked, pending_error = None, None
    halted = threading.Event()
    ordered = sorted(sources, key=lambda value: (value["relative_path"].startswith("annotations/"), value["expected_bytes"], value["relative_path"]))

    def publish():
        # Called only by the owner thread. MetadataBudget deliberately stays here.
        summary = {"schema_version": "1.0", "dataset_id": "bfmd", "usage_scope": "training_only",
                   "complete": len(verified) == len(sources),
                   "files": sorted(verified.values(), key=lambda value: value["relative_path"]), "source_catalog_sha256": catalog_sha,
                   "media_files_downloaded": 0, "assets_created": 0, "converted_events": 0,
                   "video_alignment": "unmatched", "rights": config["rights"],
                   "scripts_executed": False, "backup_is_active_annotation": False}
        summary["acquisition_status"] = "PASS" if summary["complete"] else "IN_PROGRESS"
        summary["run_progress_relative_path"] = "data/" + PROGRESS_PATH
        write_json(quota.resolve_path(HANDOFF_PATH), summary, quota=quota, budget=budget)

    # Recheck prior receipts without rewriting the entire handoff for each cached
    # entry. A 115-file resume must not consume its metadata budget on old files.
    pending = []
    for item in ordered:
        prior = verified.get(item["google_drive_id"])
        if prior is None:
            pending.append(item)
            continue
        entry, error = _acquire_one(config, item, quota, response_opener, prior=prior)
        records.append(entry)
        if error is not None:
            raise error
    progress("IN_PROGRESS")

    queue = iter(pending)
    inflight = {}
    completed = SimpleQueue()
    active_condition = threading.Condition()
    active_tasks = 0

    def run_item(item):
        nonlocal active_tasks
        # The dispatcher may race a peer's failure between its halt check and
        # submit(). Admission happens here; unstarted work is not an attempt.
        with active_condition:
            if halted.is_set() or stop_path.exists():
                halted.set()
                return None
            active_tasks += 1
        try:
            result = _acquire_one(config, item, quota, response_opener, halt=halted)
            # Independent of the owner's submit/assignment window. Even an
            # admitted future lost to Ctrl-C is recovered during final draining.
            completed.put((item, *result))
            return result
        finally:
            with active_condition:
                active_tasks -= 1
                active_condition.notify_all()

    def record_outcome(item, entry, error):
        nonlocal blocked, pending_error
        is_new = not any(row["google_drive_id"] == item["google_drive_id"] for row in records)
        if is_new:
            records.append(entry)
        if error is None:
            verified.setdefault(item["google_drive_id"], entry)
        else:
            halted.set()
            code = entry["error"]["code"]
            if code in BLOCKING_CODES:
                blocked = blocked or code
            if not isinstance(error, (DownloadError, ValueError, OSError)):
                pending_error = pending_error or error
        return is_new

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bfmd-file")
    try:
        exhausted = False
        while inflight or not exhausted:
            try:
                if stop_path.exists():
                    halted.set()
                while not halted.is_set() and not exhausted and len(inflight) < workers:
                    item = next(queue, None)
                    if item is None:
                        exhausted = True
                        break
                    future = pool.submit(run_item, item)
                    inflight[future] = item
                if not inflight:
                    break
                done, _ = wait(inflight, timeout=0.25, return_when=FIRST_COMPLETED)
            except BaseException as error:
                # A Ctrl-C stops dispatch, then drains owned threads before the
                # shared handoff lock/reservation can be released.
                halted.set()
                pending_error = pending_error or error
                continue
            for future in done:
                item = inflight.pop(future)
                try:
                    outcome = future.result()
                    if outcome is None:
                        continue
                    entry, error = outcome
                    record_outcome(item, entry, error)
                    publish()
                    progress("BLOCKED" if blocked else "IN_PROGRESS", blocked_reason=blocked)
                    print(json.dumps({"event": "bfmd_file_finished", "index": len(records), "total": len(sources),
                          "relative_path": entry["relative_path"], "status": entry["download_status"],
                          "error": entry.get("error")}, ensure_ascii=True), flush=True)
                except BaseException as error:
                    halted.set()
                    pending_error = pending_error or error
    except BaseException as error:
        halted.set()
        pending_error = pending_error or error
    finally:
        # CPython 3.12 Thread.join can mark a still-running thread stopped after
        # KeyboardInterrupt. An independent task counter, not join's state, is
        # the evidence that all file writers and completion producers ended.
        while True:
            try:
                with active_condition:
                    halted.set()
                break
            except (KeyboardInterrupt, SystemExit) as error:
                pending_error = pending_error or error
        while True:
            try:
                pool.shutdown(wait=False)
                break
            except (KeyboardInterrupt, SystemExit) as error:
                pending_error = pending_error or error
        while True:
            try:
                with active_condition:
                    if active_tasks == 0:
                        break
                    active_condition.wait(timeout=0.25)
            except (KeyboardInterrupt, SystemExit) as error:
                pending_error = pending_error or error
        while True:
            try:
                pool.shutdown(wait=True)
                break
            except (KeyboardInterrupt, SystemExit) as error:
                halted.set()
                pending_error = pending_error or error
    # All file writers/completion producers have ended while this owner still
    # holds its handoff lock and batch reservation. Recover results even if
    # submit raised after admitting a task, or an owner interrupt landed while
    # consuming a future.
    completion_seen = False
    while True:
        try:
            item, entry, error = completed.get_nowait()
        except Empty:
            break
        completion_seen = True
        record_outcome(item, entry, error)
    if completion_seen and pending_error is not None:
        try:
            publish()
        except BaseException as publish_error:
            pending_error.add_note("BFMD final completion publication failed: " + type(publish_error).__name__)
    if pending_error is not None:
        raise pending_error
    failures = sum(record["download_status"] in {"failed", "interrupted"} for record in records)
    stopped = stop_path.exists() and len(verified) < len(sources)
    # Also publish a fully cached rerun or a stop before the first new file.
    publish()
    status = "BLOCKED" if blocked else "FAIL" if failures else "STOPPED" if stopped else "PASS"
    progress(status, blocked_reason=blocked)
    print(json.dumps({"event": "bfmd_completed", "files": len(records), "failures": failures,
                      "blocked_reason": blocked, "not_attempted": len(sources) - len(records),
                      "verified_bytes": sum(record.get("size_bytes", 0) for record in records),
                      "capacity_during_writer": quota.snapshot(), "writer_reservation_bytes": PEAK_BYTES,
                      "workers": workers, "status": status}), flush=True)
    return 2 if blocked else 1 if failures else 3 if stopped else 0


def main():
    from packages.library.drive import open_drive_response

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1,
                        help="One owner, at most two independent bounded file downloads")
    parser.add_argument("--request-stop", action="store_true",
                        help="Signal the current supported owner to finish active files and stop dispatch")
    args = parser.parse_args()
    if args.request_stop:
        print(json.dumps({"event": "bfmd_stop_requested", "path": str(request_stop(QuotaManager()))}), flush=True)
        return 0
    config = _strict_json(Path("configs/library/bfmd_sources.json"), max_bytes=500_000)
    sources = validate_config(config)
    quota, budget = QuotaManager(), MetadataBudget(limit=50_000_000)
    if quota.resolve_path(FINE_BASE + "/source/Fine-Badminton.zip.lock").exists():
        raise ValueError("Main complete-video ZIP writer is active; BFMD must wait")
    verified_acquisition(quota)
    print(json.dumps({"event": "bfmd_preflight", "files": len(sources), "expected_bytes": TOTAL_BYTES,
                      "peak_reserved_bytes": PEAK_BYTES, "capacity": quota.snapshot()}), flush=True)
    return acquire_annotations(config, quota, budget, response_opener=open_drive_response, workers=args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
