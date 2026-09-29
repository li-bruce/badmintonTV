"""Read-only BFMD audit of one verified handoff snapshot; never open partials.

No network, media, author-script execution, data-root writes, or Event conversion.
Output is stdout or an explicitly selected file under this repo's docs/library.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gc
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import sys
import time

REPO = Path(__file__).resolve().parents[2]
MAX_FILE_BYTES = 200_000_000
RAW_PREFIX = "data/training/bfmd/raw/"
SHOT_LABELS = {"serve", "flick_serve", "clear", "drop", "smash", "drive", "net_shot",
               "net_kill", "lift", "push", "press", "block", "net_hit", "hit", "bounce"}
STRUCTURAL = {"Rally", "replay", "hawk_eye_challenge", "11-point interval", "21-point interval"}
HIT_KEYS = ("frame", "game", "rally", "shot_type", "player", "side")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key: " + key[:120])
        value[key] = item
    return value


def reject_constant(value):
    raise ValueError("non-finite JSON number: " + value)


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        reject_constant(value)
    return result


def strict_json(raw):
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object,
                      parse_constant=reject_constant, parse_float=finite_float)


def small_json(path):
    with path.open("rb") as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("metadata exceeds 2 MB bound")
    return strict_json(raw), hashlib.sha256(raw).hexdigest()


def require(value, kind, pointer):
    if not isinstance(value, kind):
        raise ValueError(f"schema mismatch at {pointer}: expected {kind.__name__}")
    return value


def frames(values):
    count = invalid = negative = 0
    low = high = None
    for value in values:
        count += 1
        if type(value) is not int:
            invalid += 1
            continue
        negative += value < 0
        low = value if low is None else min(low, value)
        high = value if high is None else max(high, value)
    return {"count": count, "min": low, "max": high,
            "non_integer_count": invalid, "negative_count": negative}


def signature(records):
    digest = hashlib.sha256()
    for row in records:
        digest.update(json.dumps([row.get(k) for k in HIT_KEYS], ensure_ascii=True,
                                 separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n")
    return digest.hexdigest()


def timeline(data):
    require(data, dict, "/")
    versions = []
    for i, annotation in enumerate(require(data.get("annotations"), list, "/annotations")):
        require(annotation, dict, f"/annotations/{i}")
        results = require(annotation.get("result"), list, f"/annotations/{i}/result")
        labels, ranges_by_label, origins, types = Counter(), Counter(), Counter(), Counter()
        choice_ranges, choice_results, caption_values = Counter(), 0, 0
        endpoints, duplicates = [], Counter()
        reverse = zero = unknown_value = multi_labels = 0
        for j, result in enumerate(results):
            require(result, dict, f"/annotations/{i}/result/{j}")
            types[str(result.get("type"))] += 1
            origins[str(result.get("origin"))] += 1
            value = require(result.get("value"), dict, f"/annotations/{i}/result/{j}/value")
            names = value.get("timelinelabels")
            spans = value.get("ranges")
            if result.get("type") == "choices" and isinstance(value.get("choices"), list) and isinstance(spans, list):
                # Observed in one doubles final: parallel type/caption records,
                # not additional hits. Keep this channel separate from timeline.
                if any(not isinstance(label, str) for label in value["choices"]):
                    raise ValueError("non-string choices label")
                choice_results += 1
                for span in spans:
                    require(span, dict, "/value/ranges/*")
                    choice_ranges.update(value["choices"])
                texts = value.get("manual_caption", [])
                caption_values += isinstance(texts, list) and any(isinstance(t, str) and t.strip() for t in texts)
                continue
            if not isinstance(names, list) or not isinstance(spans, list):
                unknown_value += 1
                continue
            if any(not isinstance(name, str) for name in names):
                raise ValueError("non-string timeline label")
            multi_labels += len(names) != 1
            labels.update(names)
            for span in spans:
                require(span, dict, "/value/ranges/*")
                start, end = span.get("start"), span.get("end")
                endpoints.extend((start, end))
                if type(start) is int and type(end) is int:
                    reverse += start > end
                    zero += start == end
                    duplicates[(tuple(names), start, end)] += 1
                ranges_by_label.update(names)
        versions.append({"annotation_index": i, "was_cancelled": annotation.get("was_cancelled"),
                         "ground_truth_flag": annotation.get("ground_truth"), "results": len(results),
                         "result_types": dict(types), "origins": dict(origins),
                         "label_result_counts": dict(sorted(labels.items())),
                         "label_range_counts": dict(sorted(ranges_by_label.items())),
                         "range_endpoints": frames(endpoints), "reverse_ranges": reverse,
                         "zero_width_ranges": zero, "duplicate_label_ranges": sum(n-1 for n in duplicates.values()),
                         "non_timeline_results": unknown_value, "non_single_label_results": multi_labels,
                         "parallel_choices_results": choice_results, "parallel_choices_label_ranges": dict(sorted(choice_ranges.items())),
                         "parallel_manual_caption_nonempty_records": caption_values,
                         "known_shot_label_ranges": sum(ranges_by_label[k] for k in SHOT_LABELS),
                         "other_labels": sorted(set(labels) - SHOT_LABELS - STRUCTURAL)})
    selected = versions[0] if len(versions) == 1 and versions[0]["was_cancelled"] is not True else None
    return {"provenance": "publisher_declared_manual; locally_unreviewed",
            "annotation_versions": versions, "selected_single_version": selected,
            "prediction_versions": len(require(data.get("predictions", []), list, "/predictions")),
            "frame_indexing_declaration": data.get("_frame_indexing")}


def metadata(data):
    # Observed source differs from README: one list wrapper, eleven objects.
    if isinstance(data, list):
        if len(data) != 1:
            raise ValueError("metadata list must have exactly one top-level item")
        obj = require(data[0], dict, "/0")
    else:
        obj = require(data, dict, "/")
    games = require(obj.get("games"), dict, "/0/games")
    counts, intervals = {}, []
    reversed_ranges = 0
    for name, game in games.items():
        require(game, dict, "/0/games/" + name)
        rallies = require(game.get("rallies"), list, "/0/games/" + name + "/rallies")
        counts[name] = {"rallies": len(rallies), "score_events": len(game.get("score_events", []))}
        for rally in rallies:
            require(rally, dict, "/games/*/rallies/*")
            start, end = rally.get("start"), rally.get("end")
            intervals.extend((start, end))
            if type(start) is int and type(end) is int:
                reversed_ranges += start > end
    auto = require(obj.get("auto_extracted", {}), dict, "/0/auto_extracted")
    return {"match_name": obj.get("match_name"), "top_level_count": 1,
            "wrapper": "single_item_list" if isinstance(data, list) else "object",
            "game_counts": counts, "rallies": sum(g["rallies"] for g in counts.values()),
            "auto_extracted_num_rallies": auto.get("num_rallies"),
            "rally_endpoints": frames(intervals), "reversed_ranges": reversed_ranges}


def hits(data, caption=False):
    require(data, dict, "/")
    key = "shots" if caption else "hits"
    records = require(data.get(key), list, "/" + key)
    for row in records:
        require(row, dict, "/" + key + "/*")
    result = {"match_name": data.get("match_name"), "records": len(records),
              "declared_count": data.get("n_shots" if caption else "n_hits"),
              "frame_values": frames(row.get("frame") for row in records),
              "shot_types": dict(sorted(Counter(str(row.get("shot_type")) for row in records).items())),
              "sides": dict(Counter(str(row.get("side")) for row in records)),
              "distinct_game_rally_pairs": len({(str(row.get("game")), str(row.get("rally"))) for row in records}),
              "missing_identity_fields": sum(any(k not in row for k in HIT_KEYS) for row in records),
              "ordered_hit_identity_sha256": signature(records)}
    result["declared_count_matches"] = type(result["declared_count"]) is int and result["declared_count"] == len(records)
    if caption:
        layer_counts = {}
        for layer in ("auto", "clean", "refined"):
            counts = Counter()
            for row in records:
                value = require(row.get("captions"), dict, "/shots/*/captions").get(layer)
                counts["null" if value is None else "nonempty_text" if isinstance(value, str) and value.strip()
                       else "empty_text" if isinstance(value, str) else "other_type"] += 1
            layer_counts[layer] = dict(counts)
        result.update({"provenance": {"auto": "vision_model_generated", "clean": "normalized_generated_text",
                                     "refined": "publisher_declared_manual_revision; locally_unreviewed"},
                       "caption_layers": layer_counts, "last_shot_records": sum(row.get("last_shot") is True for row in records)})
    else:
        result["provenance"] = "inferred_from_shot_type_and_player_positions"
    return result


def sequence_export(data, category):
    require(data, dict, "/")
    section = "predictions" if category == "shuttle" else "annotations"
    output = []
    for i, version in enumerate(require(data.get(section), list, "/" + section)):
        for j, result in enumerate(require(version.get("result"), list, "/result")):
            value = require(result.get("value"), dict, "/result/*/value")
            seq = require(value.get("sequence"), list, "/result/*/value/sequence")
            output.append({"version": i, "result_index": j, "labels": value.get("labels"),
                           "points": len(seq), "frames": frames(row.get("frame") for row in seq),
                           "enabled": sum(row.get("enabled") is True for row in seq)})
    return {"provenance": "TrackNet_prediction" if category == "shuttle" else "publisher_player_tracks_interpolated",
            "section": section, "sequences": output, "frame_indexing_declaration": data.get("_frame_indexing")}


def audit_json(data, category):
    if category == "metadata":
        return metadata(data)
    if category == "hit_inferred":
        return hits(data)
    if category == "caption":
        return hits(data, caption=True)
    if category in {"shot_type", "hits_doubles"}:
        return timeline(data)
    if category in {"player_bbox", "shuttle"}:
        return sequence_export(data, category)
    if category == "court_perframe":
        rows = require(data.get("frames"), list, "/frames")
        return {"provenance": "automatic_detection_and_refit", "sample_count": len(rows),
                "flags": dict(Counter(str(row.get("flag")) for row in rows)),
                "frame_values": frames(row.get("frame_idx") for row in rows),
                "declared_summary": data.get("summary"), "declared_fps": data.get("fps")}
    if category == "court":
        require(data, dict, "/")
        return {"court_keys": sorted(require(data.get("court"), dict, "/court")),
                "net_keys": sorted(require(data.get("net"), dict, "/net")),
                "resolution": data.get("resolution"), "camera_scope": "main_camera_only"}
    if category == "pose":
        # Schema is checked here; never infer frame identity from rally order.
        videos = require(data.get("videos"), dict, "/videos")
        samples, player_counts, keypoint_counts = [], Counter(), Counter()
        for key, video in videos.items():
            perframe = require(video.get("frames"), dict, "/videos/*/frames")
            parsed_frames = (int(k) if isinstance(k, str) and k.isdecimal() else None for k in perframe)
            samples.append({"rally_key": key, "frames": frames(parsed_frames), "fps": video.get("fps"),
                            "width": video.get("width"), "height": video.get("height")})
            for people in perframe.values():
                require(people, list, "/videos/*/frames/*")
                player_counts[len(people)] += 1
                for person in people:
                    keypoint_counts[len(require(person.get("keypoints"), list, "/keypoints"))] += 1
        return {"provenance": "publisher_pose_estimates; locally_unreviewed", "rally_groups": len(videos),
                "frame_records": sum(row["frames"]["count"] for row in samples),
                "non_integer_frame_keys": sum(row["frames"]["non_integer_count"] for row in samples),
                "negative_frame_keys": sum(row["frames"]["negative_count"] for row in samples),
                "people_per_frame": dict(player_counts), "keypoints_per_person": dict(keypoint_counts),
                "rally_frame_min": min((r["frames"]["min"] for r in samples if r["frames"]["min"] is not None), default=None),
                "rally_frame_max": max((r["frames"]["max"] for r in samples if r["frames"]["max"] is not None), default=None),
                "dimensions_fps": sorted({str((r["width"], r["height"], r["fps"])) for r in samples})}
    raise ValueError("unrecognized annotation category: " + category)


def audit_csv(raw, name):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), strict=True))
    if not rows or len(set(rows[0])) != len(rows[0]):
        raise ValueError("missing or duplicate CSV header")
    header = rows[0]
    records, blank = [], 0
    for line, values in enumerate(rows[1:], 2):
        if not values or not any(values):
            blank += 1
            continue
        if len(values) != len(header):
            raise ValueError(f"CSV column count mismatch at line {line}")
        records.append(dict(zip(header, values)))
    summary = {"header": header, "nonblank_records": len(records), "blank_records": blank}
    if name == "match_index.csv":
        matches = [row for row in records if row.get("match_name") != "TOTAL"]
        summary.update({"match_records": len(matches), "rallies_sum": sum(int(row["num_rallies"]) for row in matches),
                        "total_rows": [row for row in records if row.get("match_name") == "TOTAL"], "matches": matches})
    elif name == "Badminton_video_list.csv":
        summary.update({"discipline_counts": dict(Counter(row["type"] for row in records)),
                        "publisher_status_counts": dict(Counter(row["status"] for row in records)),
                        "matches": [{k: row[k] for k in ("match_name", "type", "youtube_duration_s", "local_duration_s", "status")} for row in records],
                        "duration_values_are_publisher_claims_not_local_media_verification": True})
    return summary


def verified_bytes(root, item, source):
    relative = item["relative_path"]
    if (not relative.startswith(RAW_PREFIX) or "\\" in relative
            or any(p in {"..", "."} for p in PurePosixPath(relative).parts)
            or relative != RAW_PREFIX + source["relative_path"]):
        raise ValueError("source path does not match reviewed catalog")
    if item.get("download_status") not in {"downloaded", "verified_existing"} or item.get("usage_scope") != "training_only":
        raise ValueError("entry is not verified training-only data")
    size = source["expected_bytes"]
    if type(size) is not int or not 0 < size <= MAX_FILE_BYTES or item.get("size_bytes") != size:
        raise ValueError("invalid or oversized source length")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to((root / RAW_PREFIX).resolve(strict=True)) or path.name.endswith((".part", ".lock")):
        raise ValueError("source escaped raw root or is partial")
    before = path.stat()
    if before.st_size != size:
        raise ValueError("source file length differs from verified manifest")
    with path.open("rb") as stream:
        raw = stream.read(size + 1)
    after = path.stat()
    if len(raw) != size or before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size:
        raise ValueError("source changed while reading")
    if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
        raise ValueError("source SHA256 differs from verified manifest")
    return raw


def reconcile(files):
    by_category = {}
    for file in files:
        if file.get("status") == "PASS" and not file.get("backup"):
            by_category.setdefault(file["category"], {})[file["match_key"]] = file["summary"]
    metas, inferred, captions = (by_category.get(k, {}) for k in ("metadata", "hit_inferred", "caption"))
    single, double = (by_category.get(k, {}) for k in ("shot_type", "hits_doubles"))
    def label_sum(group, label):
        return sum(v["selected_single_version"]["label_range_counts"].get(label, 0) for v in group.values() if v["selected_single_version"])
    matches = sorted(set(metas) | set(inferred) | set(captions) | set(single) | set(double))
    per_match = []
    for name in matches:
        meta, hit, caption = metas.get(name), inferred.get(name), captions.get(name)
        manual = single.get(name, double.get(name))
        selected = manual and manual["selected_single_version"]
        per_match.append({"match_key": name, "metadata_rallies": meta and meta["rallies"],
                          "auto_extracted_rallies": meta and meta["auto_extracted_num_rallies"],
                          "inferred_hits": hit and hit["records"], "caption_records": caption and caption["records"],
                          "caption_hit_identity_match": (caption["ordered_hit_identity_sha256"] == hit["ordered_hit_identity_sha256"]) if caption and hit else None,
                          "manual_label_ranges": selected and selected["label_range_counts"],
                          "parallel_choice_label_ranges": selected and selected["parallel_choices_label_ranges"],
                          "metadata_minus_manual_Rally": meta["rallies"] - selected["label_range_counts"].get("Rally", 0) if meta and selected else None})
    singles_labels = Counter()
    for value in single.values():
        if value["selected_single_version"]:
            singles_labels.update(value["selected_single_version"]["label_range_counts"])
    refined = sum(value["caption_layers"]["refined"].get("nonempty_text", 0) for value in captions.values())
    shapes = Counter(value["wrapper"] for value in metas.values())
    pose = list(by_category.get("pose", {}).values())
    people, keypoints = Counter(), Counter()
    for value in pose:
        people.update(value["people_per_frame"])
        keypoints.update(value["keypoints_per_person"])
    return {"loaded_match_counts": {k: len(v) for k, v in by_category.items() if k not in {"raw"}},
            "pose_summary": {"files": len(pose), "rally_groups": sum(v["rally_groups"] for v in pose),
                             "frame_records_across_rally_groups": sum(v["frame_records"] for v in pose),
                             "non_integer_frame_keys": sum(v["non_integer_frame_keys"] for v in pose),
                             "negative_frame_keys": sum(v["negative_frame_keys"] for v in pose),
                             "people_per_frame": dict(people), "keypoints_per_person": dict(keypoints),
                             "dimensions_fps": sorted({item for v in pose for item in v["dimensions_fps"]}),
                             "unique_source_frames_or_video_coverage_confirmed": False},
            "metadata_wrapper_counts": dict(shapes),
            "metadata_rallies": sum(v["rallies"] for v in metas.values()),
            "inferred_singles_hits": sum(v["records"] for v in inferred.values()),
            "caption_singles_records": sum(v["records"] for v in captions.values()),
            "manual_singles_Rally_ranges": label_sum(single, "Rally"),
            "manual_doubles_Rally_ranges": label_sum(double, "Rally"),
            "manual_doubles_labels": {label: label_sum(double, label) for label in ("hit", "bounce", "net_hit")},
            "manual_singles_label_range_counts": dict(sorted(singles_labels.items())),
            "manual_singles_hit_ranges": label_sum(single, "hit"),
            "combined_manual_hit_ranges": label_sum(single, "hit") + label_sum(double, "hit"),
            "combined_manual_Rally_ranges": label_sum(single, "Rally") + label_sum(double, "Rally"),
            "manual_singles_all_known_label_ranges_not_distinct_shots": sum(v["selected_single_version"]["known_shot_label_ranges"] for v in single.values() if v["selected_single_version"]),
            "refined_caption_nonempty": refined,
            "caption_hit_identity_matches": sum(row["caption_hit_identity_match"] is True for row in per_match),
            "all_required_count_modalities_loaded": all(len(group) == count for group, count in ((metas, 12), (inferred, 12), (captions, 12), (single, 12), (double, 7))),
            "per_match": per_match}


def crosscheck_hit_metadata(root, manifest, sources, files):
    """Test references and definite outliers, without selecting endpoint semantics."""
    items = {item["source_id"]: item for item in manifest["files"]}
    available = {}
    for file in files:
        if file["status"] == "PASS" and not file["backup"] and file["category"] in {"metadata", "hit_inferred"}:
            available.setdefault(file["match_key"], {})[file["category"]] = file["source_id"]
    checks = []
    for match_key, pair in sorted(available.items()):
        if set(pair) != {"metadata", "hit_inferred"}:
            checks.append({"match_key": match_key, "status": "NOT_RUN", "reason": "verified pair incomplete"})
            continue
        meta_id, hits_id = pair["metadata"], pair["hit_inferred"]
        meta = strict_json(verified_bytes(root, items[meta_id], sources[meta_id]))
        if isinstance(meta, list):
            meta = meta[0]
        data = strict_json(verified_bytes(root, items[hits_id], sources[hits_id]))
        counts = Counter()
        examples = []
        for index, hit in enumerate(data["hits"]):
            counts["records"] += 1
            game, rally, frame = hit.get("game"), hit.get("rally"), hit.get("frame")
            game_name = "game" + str(game)
            group = meta["games"].get(game_name)
            issue = None
            if type(game) is not int or type(rally) is not int or not group or not 0 <= rally < len(group["rallies"]):
                issue = "invalid_game_or_rally_reference"
            else:
                start, end = group["rallies"][rally].get("start"), group["rallies"][rally].get("end")
                if any(type(value) is not int for value in (frame, start, end)) or start > end:
                    issue = "invalid_frame_or_metadata_endpoints"
                else:
                    counts["records_with_valid_reference_and_endpoints"] += 1
                    counts["frame_equals_metadata_start"] += frame == start
                    counts["frame_equals_metadata_end"] += frame == end
                    if not start <= frame <= end:
                        issue = "definitely_outside_metadata_envelope"
            if issue:
                counts[issue] += 1
                if len(examples) < 10:
                    examples.append({"issue": issue, "hit_pointer": f"/hits/{index}",
                                     "metadata_pointer": f"/games/{game_name}/rallies/{rally}"})
        failures = sum(counts[name] for name in ("invalid_game_or_rally_reference", "invalid_frame_or_metadata_endpoints", "definitely_outside_metadata_envelope"))
        checks.append({"match_key": match_key, "status": "PASS" if failures == 0 else "FAIL",
                       "counts": dict(counts), "issue_examples": examples})
        del meta, data
        gc.collect()
    return {"method": "Observed game number maps to games.gameN; rally is a zero-based list index. Check start <= frame <= end as a conservative outer envelope only.",
            "endpoint_inclusion_semantics_confirmed": False, "pts_or_video_alignment_confirmed": False,
            "pairs_checked": sum(row["status"] != "NOT_RUN" for row in checks),
            "pairs_passed": sum(row["status"] == "PASS" for row in checks),
            "records_checked": sum(row.get("counts", {}).get("records", 0) for row in checks),
            "per_match": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-root", type=Path, default=Path("D:/video"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and not args.output.resolve().is_relative_to((REPO / "docs/library").resolve()):
        parser.error("output must remain under this repository's docs/library")
    started = time.monotonic()
    catalog, config_hash = small_json(REPO / "configs/library/bfmd_sources.json")
    manifest, manifest_hash = small_json(args.video_root / "data/training/handoff/bfmd.annotations.v1.json")
    # Acquisition reserializes the reviewed config; its raw byte hash is not
    # the repository config's hash. Bind both the saved hash and full value.
    saved_catalog, catalog_hash = small_json(args.video_root / "data/training/bfmd/source-catalog.v1.json")
    if saved_catalog != catalog:
        raise ValueError("saved acquisition catalog differs from reviewed repository config")
    if manifest.get("dataset_id") != "bfmd" or manifest.get("usage_scope") != "training_only" or manifest.get("source_catalog_sha256") != catalog_hash:
        raise ValueError("untrusted handoff scope or source catalog hash")
    sources = {item["source_id"]: item for item in catalog["files"]}
    seen, output = set(), []
    for item in manifest["files"]:
        source_id = item.get("source_id")
        if source_id not in sources or source_id in seen:
            raise ValueError("unknown or duplicate verified source id")
        seen.add(source_id)
        source = sources[source_id]
        relative = source["relative_path"]
        parts = PurePosixPath(relative)
        category = parts.parent.name if relative.startswith("annotations/") else "raw"
        backup = source["kind"] == "annotation_backup_archive_only"
        match_key = parts.name.removesuffix(".bak").removesuffix(".json")
        if category == "court":
            match_key = match_key.removesuffix("_court")
        record = {"source_id": source_id, "relative_path": item["relative_path"], "category": category,
                  "match_key": match_key, "backup": backup, "bytes": source["expected_bytes"], "sha256": item.get("sha256")}
        try:
            raw = verified_bytes(args.video_root, item, source)
            if category != "raw":
                data = strict_json(raw)
                record["schema"] = {"top_type": type(data).__name__, "top_keys": sorted(data) if isinstance(data, dict) else None}
                record["summary"] = audit_json(data, category)
                del data
            elif relative.endswith(".csv"):
                record["summary"] = audit_csv(raw, relative)
            else:
                record["summary"] = {"source_archived_not_executed": True, "text_lines": len(raw.splitlines())}
            del raw
            record["status"] = "PASS"
        except (ValueError, KeyError, TypeError, OSError, csv.Error) as error:
            record.update(status="FAIL", error=f"{type(error).__name__}: {str(error)[:300]}")
        output.append(record)
        print(f"audited {len(output)}/{len(manifest['files'])} {category}: {record['status']}", file=sys.stderr, flush=True)
        gc.collect()
    missing = [source["relative_path"] for source in catalog["files"] if source["source_id"] not in seen]
    report = {"schema_version": "1.0", "case_id": "R-04a", "dataset_id": "bfmd",
              "checked_at": datetime.now(timezone.utc).isoformat(), "usage_scope": "training_only",
              "source_catalog_sha256": catalog_hash, "repository_config_sha256": config_hash,
              "handoff_snapshot_sha256": manifest_hash,
              "handoff_complete": manifest.get("complete"), "snapshot_files": len(output),
              "strict_parse_or_integrity_failures": sum(f["status"] == "FAIL" for f in output),
              "audited_active_json": sum(f["category"] != "raw" and not f["backup"] and f["status"] == "PASS" for f in output),
              "audited_backups": sum(f["backup"] and f["status"] == "PASS" for f in output),
              "missing_count": len(missing), "missing_files": missing, "files": output,
              "reconciliation": reconcile(output),
              "hit_metadata_reference_check": crosscheck_hit_metadata(args.video_root, manifest, sources, output),
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "video_alignment": "BLOCKED:no BFMD videos acquired; no PTS or visual verification",
              "human_content_review": False, "events_created": 0, "assets_created": 0,
              "original_data_modified": False, "author_scripts_executed": False}
    payload = json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    if len(payload.encode("utf-8")) > 1_000_000:
        raise ValueError("audit summary exceeds 1 MB output bound")
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 1 if report["strict_parse_or_integrity_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
