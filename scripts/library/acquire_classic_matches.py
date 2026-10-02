"""Sequential, bounded public-file acquisition; local review handoff only."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import uuid

from packages.contracts import Asset, AssetManifest
from packages.library.download import download, _SafeRedirect, _validate_url
from packages.library.manifest import build_asset, sha256_file, validate_asset
from packages.library.probe import probe_video
from packages.library.storage import QuotaManager, directory_bytes
from packages.library.training import tag_training_asset

BATCH_LIMIT = 30_000_000_000
FILE_LIMIT = 4_000_000_000
PTS_LIMIT = 128_000_000
JSON_LIMIT = 1_000_000
META_PEAK = 4_000_000


def announce(event, source_id, **values):
    print(json.dumps({"event": event, "source_id": source_id, **values}, ensure_ascii=True), flush=True)


def read_json(path, limit=JSON_LIMIT):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("JSON byte limit exceeded")
    return json.loads(raw)


def _stable_url(url):
    _validate_url(url)
    fields = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    if any(re.search(r"token|sig|auth|credential|secret|expire|deadline|uuid|key", key, re.I) for key in fields):
        raise ValueError("Source page must be a stable public URL without credentials or signed parameters")


def _metadata(value):
    """Only the small reviewed publisher fields; never copy an API response."""
    allowed = {"title", "owner", "rights", "cid", "bvid", "published_at", "duration", "quality", "size"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Unsupported publisher metadata fields")
    def check(node, depth=0):
        if depth > 5:
            raise ValueError("Publisher metadata nesting exceeds bound")
        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str) or re.search(r"url|token|sign|auth|cookie|credential|secret", key, re.I):
                    raise ValueError("Publisher metadata cannot contain transport/credential fields")
                check(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                check(child, depth + 1)
        elif isinstance(node, str):
            if "://" in node:
                raise ValueError("Publisher metadata cannot contain transport URLs")
        elif node is not None and type(node) not in (int, float, bool):
            raise ValueError("Unsupported publisher metadata type")
    check(value)
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 8192:
        raise ValueError("Publisher metadata exceeds 8 KB")
    return value


def validate_config(config):
    version = config.get("dataset_version")
    if (not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", version)
            or version.lower() == "handoff"):
        raise ValueError("Invalid new batch dataset_version")
    sources = config.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 5:
        raise ValueError("A batch requires one to five public sources")
    stable, transports, seen = [], {}, set()
    for source in sources:
        item = {}
        for key in ("source_page_url", "provider", "match_id", "match_title", "event_date", "rights_statement"):
            value = source.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 4096:
                raise ValueError("Missing or oversized public source descriptor")
            item[key] = value
        _stable_url(item["source_page_url"])
        date.fromisoformat(item["event_date"])
        resolved = source.get("resolved_url")
        if not isinstance(resolved, str):
            raise ValueError("An in-memory resolved public-file URL is required")
        _validate_url(resolved)
        if item["source_page_url"].startswith("https:") and not resolved.startswith("https:"):
            raise ValueError("HTTPS source cannot downgrade its transport")
        identifier = source.get("source_id", hashlib.sha256(item["source_page_url"].encode()).hexdigest()[:24])
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", identifier) or identifier in seen:
            raise ValueError("Invalid or duplicate source_id")
        seen.add(identifier)
        item["source_id"] = identifier
        maximum = source.get("max_bytes")
        if type(maximum) is not int or not 0 < maximum <= FILE_LIMIT:
            raise ValueError("Each source needs a positive byte cap at most 4 GB")
        item["max_bytes"] = maximum
        expected = source.get("expected_size_bytes")
        if expected is not None and (type(expected) is not int or not 0 < expected <= maximum):
            raise ValueError("Expected size must be within the file cap")
        item["expected_size_bytes"] = expected
        item["source_metadata"] = _metadata(source.get("source_metadata", {}))
        if resolved != item["source_page_url"] and resolved in json.dumps(item, ensure_ascii=False):
            raise ValueError("Resolved transport URL cannot occur in persisted descriptors")
        stable.append(item)
        transports[identifier] = resolved
    return version, stable, transports


def public_response_opener(resolved_url, source_page_url):
    """Resolved URLs stay in this closure; the core receipt sees the stable page."""
    opener = urllib.request.build_opener(_SafeRedirect())
    def open_response(request, *, timeout):
        headers = {key: value for key, value in request.header_items()
                   if key.lower() in {"range", "if-range", "accept-encoding"}}
        headers.update({"User-Agent": "badmintonTV-library/0.1", "Referer": source_page_url})
        return opener.open(urllib.request.Request(resolved_url, headers=headers), timeout=timeout)
    return open_response


def ensure_room(base, additional):
    if directory_bytes(base) + additional > BATCH_LIMIT:
        raise ValueError("New batch including partials, PTS and metadata would exceed 30 GB")


def append_audit(base, quota, value):
    path = quota.resolve_path(str(base.relative_to(quota.data_root)) + "/handoff/metadata-audit.jsonl")
    payload = (json.dumps({"at": datetime.now(timezone.utc).isoformat(), "usage_scope": "training_only", **value},
                          ensure_ascii=True, allow_nan=False) + "\n").encode()
    if (path.stat().st_size if path.exists() else 0) + len(payload) > JSON_LIMIT:
        raise ValueError("Batch metadata audit exceeds its fixed byte bound")
    ensure_room(base, len(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def write_json(path, value, *, quota, base):
    quota.resolve_path(path.relative_to(quota.data_root))
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > JSON_LIMIT:
        raise ValueError("Generated metadata exceeds 1 MB")
    previous = None
    if path.is_file():
        if path.stat().st_size > JSON_LIMIT:
            raise ValueError("Existing metadata exceeds byte bound; preserved unchanged")
        with path.open("rb") as stream:
            previous = stream.read(JSON_LIMIT + 1)
        if previous == raw:
            return
    ensure_room(base, 2 * len(raw))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = quota.resolve_path(str(path.relative_to(quota.data_root)) + ".tmp." + uuid.uuid4().hex)
    audit = {"audit_id": uuid.uuid4().hex, "relative_path": path.relative_to(quota.project_root).as_posix(),
             "old_sha256": hashlib.sha256(previous).hexdigest() if previous is not None else None,
             "new_sha256": hashlib.sha256(raw).hexdigest()}
    if previous is not None:
        append_audit(base, quota, {**audit, "state": "started"})
    committed = False
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        committed = True
    finally:
        temporary.unlink(missing_ok=True)
        if previous is not None:
            append_audit(base, quota, {**audit, "state": "succeeded" if committed else "failed"})


def verified_file(path, item):
    receipt = read_json(path.with_name(path.name + ".download.json"), 16_384)
    if (receipt.get("state") != "succeeded" or receipt.get("url") != item["source_page_url"]
            or receipt.get("max_bytes") != item["max_bytes"] or not path.is_file()
            or not 0 < path.stat().st_size <= item["max_bytes"]
            or receipt.get("size_bytes") != path.stat().st_size or sha256_file(path) != receipt.get("sha256")
            or (item["expected_size_bytes"] is not None and path.stat().st_size != item["expected_size_bytes"])):
        raise ValueError("Original file does not match its bounded download receipt")
    return receipt


def verified_success_record(prior, item, path, version, quota):
    if not isinstance(prior, dict) or prior.get("state") != "succeeded" or prior.get("source") != item:
        raise ValueError("Published asset requires its matching successful source record")
    receipt = verified_file(path, item)
    asset = validate_asset(prior["asset"], storage_root=quota.project_root)
    Asset.model_validate(asset)
    if (asset["sha256"] != receipt["sha256"]
            or asset["relative_path"] != path.relative_to(quota.project_root).as_posix()
            or asset.get("usage_scope") != "training_only"
            or asset["provenance"].get("usage_scope") != "training_only"
            or asset["provenance"].get("dataset_id") != version or asset["split"] != "unassigned"
            or asset["match_id"] != item["match_id"] or asset["title"] != item["match_title"]
            or asset["source_url"] != item["source_page_url"] or asset["source_page"] != item["source_page_url"]
            or asset["probe"].get("source_sha256") != receipt["sha256"]
            or asset["probe"].get("decode", {}).get("status") != "passed"
            or asset["probe"].get("decode", {}).get("scope") != "full_video_stream"
            or asset["probe"].get("pts_index", {}).get("complete") is not True):
        raise ValueError("Existing review asset conflicts with its original source")
    return asset, receipt


def prior_manifest_assets(base, sources, version, quota):
    """Validate every published entry before any mutable handoff is rewritten."""
    manifest_path = quota.resolve_path(str(base.relative_to(quota.data_root)) + "/handoff/assets.v1.json")
    if not manifest_path.exists():
        return []
    manifest = read_json(manifest_path)
    AssetManifest.model_validate(manifest)
    by_path = {f"data/training/{version}/raw/{item['source_id']}.mp4": item for item in sources}
    checked = []
    for published in manifest["assets"]:
        item = by_path.get(published["relative_path"])
        if item is None:
            raise ValueError("Existing manifest contains a source outside the current batch plan")
        record = quota.resolve_path(f"training/{version}/handoff/{item['source_id']}.json")
        path = quota.resolve_path(published["relative_path"].removeprefix("data/"))
        asset, _ = verified_success_record(read_json(record), item, path, version, quota)
        if asset != published:
            raise ValueError("Existing manifest and successful source record disagree")
        checked.append(asset)
    return checked


def acquire(config, *, quota, ffmpeg, ffprobe):
    """Acquire sequentially and emit only a batch-local review AssetManifest.

    The caller supplies transient resolved_url values in memory. No central
    training registry/splits or pinned annotation catalog are modified.
    """
    version, sources, transports = validate_config(config)
    base = quota.resolve_path("training/" + version)
    plan = {"schema_version": "1.0", "dataset_version": version, "usage_scope": "training_only",
            "batch_limit_bytes": BATCH_LIMIT, "sources": sources}
    plan_path = base / "source-catalog.v1.json"
    before = quota.snapshot()
    with quota.reserve(PTS_LIMIT + META_PEAK, purpose="Classic batch sequential CPU PTS and review metadata"):
        ensure_room(base, META_PEAK)
        base.mkdir(parents=True, exist_ok=True)
        lock = quota.resolve_path("training/" + version + "/.acquire.lock")
        with lock.open("xb") as stream:
            stream.write(b"Sequential classic acquisition owner; inspect before recovery\n")
        try:
            if plan_path.exists():
                if read_json(plan_path) != plan:
                    raise ValueError("Existing batch source plan differs; originals preserved")
            # A legitimate interrupted manifest may contain only a subset.
            # Keep that verified subset even if an earlier pending source fails.
            records, assets = [], prior_manifest_assets(base, sources, version, quota)
            if not plan_path.exists():
                write_json(plan_path, plan, quota=quota, base=base)
            for item in sources:
                identifier = item["source_id"]
                record_path = quota.resolve_path(f"training/{version}/handoff/{identifier}.json")
                path = quota.resolve_path(f"training/{version}/raw/{identifier}.mp4")
                if record_path.exists():
                    prior = read_json(record_path)
                    if prior.get("source") != item:
                        raise ValueError("Existing source record has conflicting provenance")
                    if prior.get("state") == "succeeded":
                        asset, receipt = verified_success_record(prior, item, path, version, quota)
                        if not any(existing["asset_id"] == asset["asset_id"] for existing in assets):
                            assets.append(asset)
                        records.append(prior)
                        announce("source_reused", identifier, size_bytes=receipt["size_bytes"], sha256=receipt["sha256"])
                        continue
                record = {"schema_version": "1.0", "usage_scope": "training_only", "source": item,
                          "provenance": {"usage_scope": "training_only", "dataset_id": version},
                          "state": "started", "human_confirmed_annotations": 0}
                try:
                    # Account for the transient second hard-link name too.
                    ensure_room(base, 2 * item["max_bytes"] + PTS_LIMIT + META_PEAK)
                    write_json(record_path, record, quota=quota, base=base)
                    if not path.exists():
                        announce("download_started", identifier, max_bytes=item["max_bytes"])
                        download(item["source_page_url"], path.relative_to(quota.data_root), quota=quota,
                                 max_bytes=item["max_bytes"], timeout=60,
                                 response_opener=public_response_opener(transports[identifier], item["source_page_url"]))
                    receipt = verified_file(path, item)
                    announce("download_completed", identifier, size_bytes=receipt["size_bytes"], sha256=receipt["sha256"])
                    record["downloaded_file"] = {"relative_path": path.relative_to(quota.project_root).as_posix(),
                                                  "sha256": receipt["sha256"], "size_bytes": receipt["size_bytes"]}
                    pts = quota.resolve_path(f"training/{version}/probes/{identifier}.{uuid.uuid4().hex}.pts.jsonl")
                    announce("probe_started", identifier, device="cpu", max_pts_bytes=PTS_LIMIT)
                    report = probe_video(path, ffprobe=ffprobe, ffmpeg=ffmpeg, timeout_seconds=7200,
                                         pts_index_path=pts, storage_root=quota.project_root,
                                         max_pts_frames=2_000_000, max_pts_bytes=PTS_LIMIT)
                    announce("probe_completed", identifier, duration_ms=report["duration_ms"],
                             frames=report["probe"]["decode"]["frames"])
                    metadata = {"title": item["match_title"], "match_id": item["match_id"],
                                "source_type": "broadcast", "usage_scope": "training_only",
                                "source_url": item["source_page_url"], "source_page": item["source_page_url"],
                                "acquired_at": receipt["completed_at"], "camera_type": "unknown",
                                "discipline": "singles", "players": [], "split": "unassigned",
                                "rights": {"status": "unknown", "license_url": None,
                                           "evidence": item["rights_statement"], "allowed_uses": []},
                                "provenance": {"usage_scope": "training_only", "dataset_id": version,
                                               "provider": item["provider"], "event_date": item["event_date"],
                                               "publisher_metadata": item["source_metadata"],
                                               "identity_basis": "Publisher source metadata; independently unconfirmed",
                                               "annotation_alignment": "unverified", "human_confirmed_annotations": 0}}
                    asset = tag_training_asset(build_asset(path, metadata, report, storage_root=quota.project_root))
                    Asset.model_validate(asset)
                    record.update(state="succeeded", actual_duration_ms=asset["duration_ms"], asset=asset)
                    write_json(record_path, record, quota=quota, base=base)
                    assets.append(asset)
                except Exception as error:
                    record.pop("asset", None)
                    record.update(state="failed", error={"code": getattr(error, "code", type(error).__name__),
                                                          "error_type": type(error).__name__})
                    write_json(record_path, record, quota=quota, base=base)
                    announce("source_failed", identifier, error_type=type(error).__name__, code=record["error"]["code"])
                records.append(record)
                write_json(base / "handoff/assets.v1.json", {"schema_version": "1.0", "assets": assets}, quota=quota, base=base)
                if record["state"] == "failed":
                    break  # A blocked/invalid transport never starts the rest of the batch.
            write_json(base / "handoff/assets.v1.json", {"schema_version": "1.0", "assets": assets}, quota=quota, base=base)
            summary = {"schema_version": "1.0", "dataset_version": version, "usage_scope": "training_only",
                       "status": "complete" if len(assets) == len(sources) else "partial" if assets else "failed",
                       "handoff_status": "review_only", "central_registry_published": False,
                       "central_registry_reason": "Preserve pinned annotation catalog compatibility; separate reviewed import required",
                       "source_count": len(sources), "succeeded": len(assets), "attempted": len(records),
                       "human_confirmed_annotations": 0, "split": "unassigned", "records": records,
                       "batch_bytes": directory_bytes(base), "capacity_before": before}
            write_json(base / "handoff/acquisition.v1.json", summary, quota=quota, base=base)
            return summary
        finally:
            lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="JSON path, or - for bounded stdin; resolved URLs remain memory-only")
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    args = parser.parse_args(argv)
    try:
        if args.config == "-":
            raw = sys.stdin.buffer.read(JSON_LIMIT + 1)
            if len(raw) > JSON_LIMIT:
                raise ValueError("Config exceeds byte bound")
            config = json.loads(raw)
        else:
            config = read_json(args.config)
        result = acquire(config, quota=QuotaManager(), ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
        print(json.dumps({key: result[key] for key in ("status", "dataset_version", "succeeded", "source_count", "handoff_status")}))
        return 0 if result["status"] == "complete" else 2
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
