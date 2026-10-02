"""Read-only training inputs -> an AssetManifest and immutable review sidecars.

This adapter deliberately creates neither Events nor training truth. A reviewed
config pins the input manifests; hash consistency is not proof of video rights,
human annotation, match identity or CSV frame conventions.
"""
from __future__ import annotations

from collections import Counter
import copy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

from .cli import publication_audit
from .manifest import SplitRegistry, safe_asset_path, sha256_file, stable_asset_id, validate_asset
from .storage import _check_ancestors

DATASET = "fine-badminton-2026-zenodo-20292976-v1.0"
BASE = "data/training/" + DATASET
OUTPUT = "data/training/handoff/annotation-catalog.v1.json"
SIDECARS = "data/training/handoff/annotation-catalog"
MAX_BYTES = 10_000_000
PEAK_BYTES = 50_000_000
SCHEMA = "library.annotation-catalog/1"
CONFIG_SCHEMA = "library.annotation-catalog-config/1"
INPUT_PATHS = {
    "manifest": f"data/training/handoff/{DATASET}.assets.v1.json",
    "registry": "data/training/handoff/training-registry.v1.json",
    "splits": "data/training/handoff/training-splits.v1.json",
    "extracted": f"{BASE}/extracted-sources.v1.json",
    "bfmd": "data/training/handoff/bfmd.annotations.v1.json",
}


class CatalogError(ValueError):
    """The catalog or its pinned source evidence cannot be trusted."""


def require(condition, message):
    if not condition:
        raise CatalogError(message)


def encode_json(value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False) + "\n").encode("utf-8")
    require(len(raw) <= MAX_BYTES, "JSON exceeds the 10 MB bound")
    return raw


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value):
    raise CatalogError("Non-finite JSON number")


def _float(value):
    number = float(value)
    require(math.isfinite(number), "JSON number overflow")
    return number


def _decode(raw):
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique,
                          parse_constant=_nonfinite, parse_float=_float)
    except (ValueError, UnicodeError) as exc:
        raise CatalogError(f"Invalid strict JSON: {exc}") from exc


def load_json(path, max_bytes=MAX_BYTES):
    with Path(path).open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    require(len(raw) <= max_bytes, "JSON input exceeds byte bound")
    return _decode(raw)


def _path(root, relative):
    from packages.contracts.models import validate_relative_path
    validate_relative_path(relative)
    lexical = Path(root).joinpath(*relative.split("/"))
    _check_ancestors(lexical)
    return safe_asset_path(relative, root)


def reference(relative, raw):
    return {"relative_path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw)}


def _check_ref(ref):
    require(isinstance(ref, dict) and isinstance(ref.get("relative_path"), str), "Invalid file reference")
    require(type(ref.get("size_bytes")) is int and ref["size_bytes"] >= 0, "Invalid reference size")
    require(isinstance(ref.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", ref["sha256"]),
            "Invalid reference SHA256")


def _read_ref(root, ref, *, limit=MAX_BYTES):
    _check_ref(ref)
    require(ref["size_bytes"] <= limit, "Reference exceeds read bound")
    path = _path(root, ref["relative_path"])
    require(path.is_file() and path.stat().st_size == ref["size_bytes"], "Reference missing or size mismatch")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) == ref["size_bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
            "Reference SHA256 mismatch")
    return raw


def validate_config(config):
    require(isinstance(config, dict) and config.get("schema_version") == CONFIG_SCHEMA,
            "Unsupported catalog config")
    require(config.get("dataset_id") == DATASET and config.get("output") == OUTPUT,
            "Only the reviewed Fine-Badminton training catalog destination is supported")
    require(type(config.get("peak_bytes")) is int and config["peak_bytes"] == PEAK_BYTES,
            "Catalog publication requires the fixed 50 MB peak allowance")
    inputs = config.get("inputs")
    require(isinstance(inputs, dict) and {"manifest", "registry", "splits", "extracted"} <= inputs.keys()
            and inputs.keys() <= INPUT_PATHS.keys(), "Invalid catalog inputs")
    for key, ref in inputs.items():
        _check_ref(ref)
        require(ref["relative_path"] == INPUT_PATHS[key], "Unexpected trusted input path")
    return copy.deepcopy(config)


def _index(items, key):
    require(isinstance(items, list) and len(items) <= 10_000, "Invalid or oversized source list")
    result = {}
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get(key), str), "Invalid source entry")
        require(item[key] not in result, "Duplicate source " + key)
        result[item[key]] = item
    return result


def _pts(root, asset):
    probe = asset["probe"]
    index = probe.get("pts_index", {})
    _check_ref(index)
    require(index["relative_path"].startswith(BASE + "/probes/"), "PTS outside reviewed dataset")
    require(index.get("complete") is True and index.get("time_base") == asset["time_base"]
            and index.get("pts_field") == "best_effort_timestamp" and index.get("format") == "jsonl",
            "Incomplete or inconsistent original PTS index")
    count = index.get("frame_count")
    decode = probe.get("decode", {})
    require(type(count) is int and 0 < count <= 10_000_000, "Invalid PTS frame count")
    require(decode.get("status") == "passed" and decode.get("scope") == "full_video_stream"
            and decode.get("exit_code") == 0 and type(decode.get("frames")) is int
            and decode["frames"] == count, "Full decode evidence does not match PTS")
    require(probe.get("source_sha256") == asset["sha256"]
            and probe.get("source_size_bytes") == asset["size_bytes"], "Probe source mismatch")
    require(0 < index["size_bytes"] <= 512 * count, "PTS byte bound exceeded")
    path = _path(root, index["relative_path"])
    require(path.is_file() and path.stat().st_size == index["size_bytes"], "PTS missing or size mismatch")
    digest, observed, first, last, deltas = hashlib.sha256(), 0, None, None, Counter()
    with path.open("rb") as stream:
        while raw := stream.readline(513):
            require(len(raw) <= 512 and observed < count, "PTS line/count bound exceeded")
            digest.update(raw)
            row = _decode(raw)
            require(isinstance(row, dict) and set(row) == {"frame_index", "pts"}, "Unexpected PTS row")
            require(type(row["frame_index"]) is int and row["frame_index"] == observed
                    and type(row["pts"]) is int, "PTS sequence is not the original integer frame order")
            pts = row["pts"]
            if last is not None:
                require(pts > last, "PTS must be strictly increasing; do not sort or deduplicate")
                deltas[pts - last] += 1
            else:
                first = pts
            last, observed = pts, observed + 1
    require(observed == count and digest.hexdigest() == index["sha256"], "PTS count/hash mismatch")
    from fractions import Fraction
    require(type(probe.get("start_pts")) is int and first == probe["start_pts"], "PTS origin mismatch")
    require((last - first) * Fraction(asset["time_base"]) * 1000 < asset["duration_ms"],
            "PTS extends beyond asset duration")
    timing_status = "unknown"
    if count >= 3:
        if len(deltas) == 1:
            timing_status = "cfr_observed"
        elif max(deltas) - min(deltas) > 1:
            timing_status = "vfr_observed"
    require(index.get("vfr_status") == probe.get("vfr_status")
            and probe.get("vfr_status") == timing_status,
            "PTS deltas disagree with VFR evidence")
    if deltas:
        require(index.get("min_delta_ticks") == min(deltas) and index.get("max_delta_ticks") == max(deltas),
                "PTS delta bounds mismatch")
    return {"frame_count": count, "first_pts": first, "last_pts": last,
            "time_base": asset["time_base"], "delta_ticks_counts": {str(k): v for k, v in sorted(deltas.items())},
            "frame_index_base": 0, "basis": "Original best_effort_timestamp in decoded frame order; not nominal FPS"}


SEMANTICS = {
    "review_status": "unreviewed", "reviewer_type": None, "human_confirmed": False,
    "training_truth_eligible": False, "import_kind": "publisher_raw_annotation_hint",
    "time_semantics": {"unit_claim": "source frame number", "frame_base": "unverified",
                       "end_inclusive_or_exclusive": "unverified", "source_broadcast_offset_ms": None,
                       "contact_time": "not_provided", "rally_end": "not_provided",
                       "readme_claim": "start: first frame initiating stroke; end: contact and follow-through completed"},
    "location_semantics": "unverified", "label_mapping": "unverified; raw bilingual strings are not distinct semantic classes",
    "fine_hand_technique": "unknown", "footwork": "unknown", "unknown_is_negative": False,
    "conversion_policy": "No ms, Event, contact, rally or fine-label conversion until independent semantic review",
}


def _hints(root, source, asset_id):
    raw = _read_ref(root, source)
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    header = next(reader, [])
    require(header == ["start", "end", "label", "location"], "Unexpected original CSV columns")
    rows, seen, labels, diagnostics = [], {}, Counter(), Counter()
    previous = None
    for record, row in enumerate(reader, 1):
        require(record <= 100_000 and len(row) == 4, "CSV row bound or column mismatch")
        key, flags = tuple(row), []
        if key in seen:
            flags.append("exact_duplicate_preserved")
        seen.setdefault(key, record)
        if row[0] == row[1]:
            flags.append("equal_endpoints_semantics_unverified")
        # Diagnostics only; never use these integers to invent an interval.
        if re.fullmatch(r"[0-9]{1,12}", row[0]):
            current = int(row[0])
            if previous is not None and current < previous:
                flags.append("out_of_order_start_preserved")
            previous = current
        else:
            flags.append("start_not_canonical_integer")
        for flag in flags:
            diagnostics[flag] += 1
        labels[row[2]] += 1
        rows.append({"row_id": f"{source['sha256']}:{record}", "source_record": record,
                     "source_line_end": reader.line_num, "raw": dict(zip(header, row)), "diagnostics": flags})
    require(rows, "Empty original annotation CSV")
    return {"schema_version": "library.annotation-hints/1", "asset_id": asset_id,
            "usage_scope": "training_only", "source": source, "semantics": copy.deepcopy(SEMANTICS),
            "rows": rows, "row_count": len(rows), "raw_label_counts": dict(labels), "diagnostics": dict(diagnostics)}


def _sidecar(sidecars, value, kind):
    raw = encode_json(value)
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"{SIDECARS}/{digest}.{kind}.json"
    sidecars[relative] = raw
    return reference(relative, raw)


def _inputs(root, config):
    result = {key: _decode(_read_ref(root, ref)) for key, ref in config["inputs"].items()}
    require(all(isinstance(value, dict) and value.get("schema_version") == "1.0"
                for value in result.values()), "Invalid input schema")
    return result


def build_bundle(root, config):
    """Rehash original files and assemble deterministic bytes without writing."""
    from packages.contracts import AssetManifest, TrainingRegistry
    config = validate_config(config)
    data = _inputs(root, config)
    AssetManifest.model_validate(data["manifest"])
    assets = data["manifest"]["assets"]
    require(0 < len(assets) <= 100, "Catalog asset count outside bound")
    TrainingRegistry.model_validate(data["registry"])
    registry = data["registry"]["assets"]
    require(len(registry) <= 10_000, "Training registry count exceeds catalog bound")
    for registered in registry:
        _path(root, registered["relative_path"])
    require(data["extracted"].get("complete") is True, "Incomplete extraction evidence")
    sources = _index(data["extracted"].get("sources"), "relative_path")
    members = _index(list(sources.values()), "member_name")
    for source in sources.values():
        _check_ref(source)
        require(source["relative_path"].startswith(BASE + "/extracted/")
                and source.get("usage_scope") == "training_only", "Source outside training extraction")
    evidence = []
    for name in ("README.md", "LICENSE"):
        require(name in members, "Missing original README/license evidence")
        source = members[name]
        _read_ref(root, source)
        evidence.append(copy.deepcopy(source))
    rights = {"video": "research_only; copyright remains with original rights holders",
              "annotation": "Package README/LICENSE: CC BY-NC 4.0",
              "code": "No executable code imported by this adapter; code rights require separate review",
              "weights": "not_applicable; no model weights in this catalog",
              "unresolved_conflicts": ["Zenodo API cc-by-4.0 versus package CC BY-NC 4.0",
                                       "README redistribution permission requirement versus LICENSE sharing language"],
              "commercial_use": "not_authorized", "public_redistribution": "not_authorized_pending_clarification",
              "readme_restrictions": ["No commercial use", "Redistribution requires prior written permission",
                                      "No attempts to identify or contact individuals appearing in videos",
                                      "Do not misrepresent dataset source or ownership"],
              "evidence": evidence}
    sidecars, entries, all_labels, totals, hashes = {}, [], set(), Counter(), set()
    for original in sorted(assets, key=lambda a: a["asset_id"]):
        asset = validate_asset(original, storage_root=root, verify_file=False)
        require(asset["sha256"] not in hashes and asset["asset_id"] == stable_asset_id(asset["sha256"]),
                "Duplicate source bytes or unstable asset ID")
        hashes.add(asset["sha256"])
        require(asset.get("usage_scope") == "training_only" and asset["provenance"].get("usage_scope") == "training_only"
                and asset["provenance"].get("dataset_id") == DATASET and asset["split"] == "unassigned",
                "Asset must retain training_only and unassigned scope")
        require("annotation_catalog" not in asset["provenance"], "Input must be the original Asset snapshot")
        require(asset["rights"]["status"] == "research_only", "Unexpected video permission status")
        matches = [r for r in registry if r["sha256"].lower() == asset["sha256"]
                   and r["asset_id"] == asset["asset_id"] and r["relative_path"] == asset["relative_path"]]
        require(matches and all(all(r.get(k) == asset[k] for k in ("size_bytes", "match_id"))
                                and r.get("provenance", {}).get("usage_scope") == "training_only" for r in matches),
                "Asset not in trusted training registry")
        splits = data["splits"]
        require(splits.get("sha256", {}).get(asset["sha256"]) == asset["match_id"]
                and splits.get("matches", {}).get(asset["match_id"]) == "unassigned", "Source split registration mismatch")
        source = sources.get(asset["relative_path"], {})
        require(all(source.get(k) == asset[k] for k in ("sha256", "size_bytes")), "Asset is not the extracted source")
        media = _path(root, asset["relative_path"])
        require(media.is_file() and media.stat().st_size == asset["size_bytes"]
                and sha256_file(media) == asset["sha256"], "Original video size/hash mismatch")
        pts_summary = _pts(root, asset)
        member = source["member_name"]
        require(member.startswith("videos/") and member.endswith(".mp4")
                and len(PurePosixPath(member).parts) == 2, "Unexpected non-flat video archive member")
        # The extraction inventory preserves canonical ZIP Unicode names; some
        # early Asset provenance names contain decoded replacement characters.
        stem = PurePosixPath(member).stem
        csv_member = "annotations/" + stem + "_dataframe.csv"
        require(csv_member in members, "No exact canonical archive-stem CSV pairing")
        hints = _hints(root, members[csv_member], asset["asset_id"])
        hints_ref = _sidecar(sidecars, hints, "hints")
        all_labels.update(hints["raw_label_counts"])
        totals.update(hints["diagnostics"])
        totals["raw_rows"] += hints["row_count"]
        totals["frames"] += pts_summary["frame_count"]
        totals["duration_ms"] += asset["duration_ms"]
        entries.append({"asset_id": asset["asset_id"], "source_asset": asset,
                        "display_title": stem, "canonical_archive_member": member,
                        "usage_scope": "training_only", "original_pts": asset["probe"]["pts_index"],
                        "pts_verification": pts_summary, "raw_annotations": hints_ref,
                        "raw_annotation_rows": hints["row_count"], "raw_label_counts": hints["raw_label_counts"],
                        "match_group": {"status": "unconfirmed", "confirmed_group_id": None,
                                        "publisher_match_id": asset["match_id"], "source_sha256": asset["sha256"],
                                        "split": "unassigned", "independent_match_confirmed": False,
                                        "reason": "Publisher processed clip name only; original match, replay/transcode relationships and broadcast offset require human review"},
                        "training_truth_eligible": False,
                        "blockers": ["match_group_unconfirmed", "annotation_time_semantics_unverified",
                                     "raw_labels_not_human_confirmed", "fine_label_mapping_unverified"]})
    exclusions = []
    if "bfmd" in data:
        bfmd = data["bfmd"]
        require(bfmd.get("usage_scope") == "training_only" and bfmd.get("video_alignment") == "unmatched"
                and bfmd.get("assets_created") == 0 and bfmd.get("media_files_downloaded") == 0,
                "BFMD exclusion evidence has changed; review config and adapter")
        exclusions.append({"dataset_id": "bfmd", "reference": config["inputs"]["bfmd"],
                           "status": "unmatched", "playable_assets": 0, "training_truth_eligible": False,
                           "reason": "No source videos or original PTS; raw files and generated captions are not aligned visual truth",
                           "rights": bfmd.get("rights", {})})
    summary = {"asset_count": len(entries), "raw_label_strings": len(all_labels),
               **dict(totals), "human_confirmed_annotations": 0, "confirmed_match_groups": 0,
               "split": "unassigned", "media_copied": 0}
    details = {"schema_version": SCHEMA, "usage_scope": "training_only", "dataset_id": DATASET,
               "inputs": config["inputs"], "rights": rights, "semantics": copy.deepcopy(SEMANTICS),
               "assets": entries, "excluded_collections": exclusions, "summary": summary}
    detail_ref = _sidecar(sidecars, details, "details")
    manifest = {"schema_version": "1.0", "assets": []}
    for entry in entries:
        asset = copy.deepcopy(entry["source_asset"])
        asset["provenance"]["annotation_catalog"] = {"schema_version": SCHEMA, **detail_ref}
        manifest["assets"].append(asset)
    AssetManifest.model_validate(manifest)
    payload = encode_json(manifest)
    # Covers all new immutable files, one manifest temp + final, audit pairs,
    # ledger growth and a retained previous manifest generation.
    require(2 * (sum(map(len, sidecars.values())) + len(payload)) + 1_000_000 <= PEAK_BYTES,
            "Generated catalog exceeds peak budget")
    return {"manifest": manifest, "sidecars": sidecars, "summary": summary}


def _write_atomic(path, raw, *, immutable=False):
    """Never replace an existing immutable sidecar, including a racing writer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _check_ancestors(path)
    if immutable and path.exists():
        require(path.stat().st_size == len(raw), "Immutable sidecar conflict")
        with path.open("rb") as stream:
            require(stream.read(len(raw) + 1) == raw, "Immutable sidecar conflict")
        return False
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="catalog-", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            os.link(temp, path)
        else:
            os.replace(temp, path)
        return True
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def publish_catalog(quota, config):
    config = validate_config(config)
    root = quota.project_root
    output = quota.resolve_path(OUTPUT.removeprefix("data/"))
    before = quota.snapshot()
    warnings = []
    with quota.reserve(PEAK_BYTES, purpose="annotation catalog immutable metadata and atomic manifest publication"):
        # A stale lock after a killed process requires inspection; it is never
        # guessed expired or shared with the training registry's writer lock.
        with SplitRegistry(output, lock_timeout_seconds=0.2)._lock():
            bundle = build_bundle(root, config)
            written = 0
            for relative, raw in bundle["sidecars"].items():
                path = quota.resolve_path(relative.removeprefix("data/"))
                if _write_atomic(path, raw, immutable=True):
                    written += len(raw)
            raw = encode_json(bundle["manifest"])
            generation = quota.resolve_path(f"{SIDECARS.removeprefix('data/')}/{hashlib.sha256(raw).hexdigest()}.manifest.json")
            if _write_atomic(generation, raw, immutable=True):
                written += len(raw)
            # Recheck small pinned source manifests just before publication.
            # Media remain read-only; the verifier rehashes them on consumption.
            _inputs(root, config)
            changed = True
            if output.exists():
                require(output.stat().st_size <= MAX_BYTES, "Existing catalog exceeds byte bound")
                with output.open("rb") as stream:
                    previous = stream.read(MAX_BYTES + 1)
                require(len(previous) <= MAX_BYTES, "Existing catalog exceeds byte bound")
                changed = previous != raw
            if changed:
                switched = False
                try:
                    with publication_audit([output], quota, reason="Verified annotation catalog generation switch"):
                        _write_atomic(output, raw)
                        switched = True
                except (OSError, ValueError) as exc:
                    if not switched:
                        raise
                    # The atomic replace is the commit point. Rolling back
                    # here could invalidate a generation a reader has already
                    # registered. Keep the valid generation and report the
                    # bookkeeping failure explicitly; the started audit and
                    # immutable prior generations remain available.
                    warnings.append(f"Catalog committed; audit completion needs inspection: {exc}")
                written += len(raw)
    status = "published_with_audit_warning" if warnings else ("published" if changed else "unchanged")
    return {"status": status, "warnings": warnings, "catalog": reference(OUTPUT, raw),
            "summary": bundle["summary"], "metadata_bytes_written": written,
            "capacity_before": before, "capacity_after": quota.snapshot()}


def verify_catalog(root, config):
    """Rebuild from pinned originals, then compare all published bytes. No writes."""
    bundle = build_bundle(root, config)
    expected = encode_json(bundle["manifest"])
    actual = _read_ref(root, reference(OUTPUT, expected))
    require(actual == expected, "Catalog differs from trusted source snapshots")
    for relative, raw in bundle["sidecars"].items():
        require(_read_ref(root, reference(relative, raw)) == raw, "Sidecar differs from original annotations")
    generation = f"{SIDECARS}/{hashlib.sha256(expected).hexdigest()}.manifest.json"
    _read_ref(root, reference(generation, expected))
    return {"status": "verified", "catalog": reference(OUTPUT, expected), "summary": bundle["summary"],
            "verified_sidecars": len(bundle["sidecars"]), "originals_rehashed": True,
            "browser_playback": "NOT_RUN", "dataset_snapshot": "NOT_RUN"}
