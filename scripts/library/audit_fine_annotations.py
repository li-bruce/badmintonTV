"""Read-only Fine-Badminton CSV/PTS audit; reports may only be saved in repo docs.

No download, extraction, media decode, Event conversion or source-file write.
Run again after extraction/probing to replace the repository's current report.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import heapq
import io
import json
import math
from pathlib import Path
import re

from packages.library.manifest import safe_asset_path


DATASET = "fine-badminton-2026-zenodo-20292976-v1.0"
BASE = "data/training/" + DATASET
ARCHIVE_SHA256 = "a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439"
PUBLISHER_MD5 = "cb3fcaca0ae9b08c564ac2a19ae4e7a0"
MAX_JSON = 10_000_000
MAX_CSV = 10_000_000
MAX_ROWS = 100_000
MAX_EXAMPLES = 20
CONVENTIONS = {
    "zero_based_inclusive": (0, False), "zero_based_exclusive": (0, True),
    "one_based_inclusive": (1, False), "one_based_exclusive": (1, True),
}


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key")
        value[key] = item
    return value


def _nonfinite(value):
    raise ValueError("Non-finite JSON number")


def _finite_float(raw):
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("JSON exponent overflows a finite number")
    return value


def read_json(path, limit=MAX_JSON):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("JSON input exceeds audit bound")
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique, parse_constant=_nonfinite,
                      parse_float=_finite_float), hashlib.sha256(raw).hexdigest()


def _source(entry, root, *, read_bytes=False):
    relative = entry["relative_path"]
    if not relative.startswith(BASE + "/extracted/") or entry.get("usage_scope") != "training_only":
        raise ValueError("Extracted source is outside the reviewed dataset/scope")
    path = safe_asset_path(relative, root)
    if not path.is_file() or path.stat().st_size != entry["size_bytes"]:
        raise ValueError("Extracted source is missing or has changed size")
    if read_bytes:
        if entry["size_bytes"] > MAX_CSV:
            raise ValueError("Annotation/document source exceeds audit byte bound")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Annotation/document source SHA mismatch")
        return raw
    return path


def _number(raw):
    if not raw.strip() or len(raw) > 80:
        raise ValueError("missing_or_oversized_number")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError("not_numeric") from None
    if not value.is_finite():
        raise ValueError("nonfinite_number")
    if value.copy_abs() > 10**12:
        raise ValueError("numeric_magnitude_exceeds_audit_bound")
    return value


def _overlaps(intervals):
    active, count, examples = [], 0, []
    for start, end, line in sorted(intervals):
        while active and active[0][0] <= start:
            heapq.heappop(active)
        count += len(active)
        if active and len(examples) < MAX_EXAMPLES:
            examples.append([active[0][1], line])
        heapq.heappush(active, (end, line))
    return {"strict_overlap_pairs": count, "example_line_pairs": examples,
            "interpretation": "Diagnostic only; touching endpoints excluded, no automatic merge or error label."}


def audit_csv(entry, raw, categories):
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header = next(reader, [])
    expected = ["start", "end", "label", "location"]
    if header != expected:
        raise ValueError(f"Unexpected CSV header in {entry['member_name']}: {header!r}")
    labels, locations, issues, examples = Counter(), Counter(), Counter(), defaultdict(list)
    seen, interval_labels, interval_lines, by_location, numeric = {}, defaultdict(set), defaultdict(list), defaultdict(list), []
    rows = blanks = duplicates = out_of_order = 0
    previous_start, previous_line = None, None
    def issue(kind, line):
        issues[kind] += 1
        if len(examples[kind]) < MAX_EXAMPLES:
            examples[kind].append(line)
    for row in reader:
        if rows + blanks >= MAX_ROWS:
            raise ValueError("CSV row bound exceeded")
        line = reader.line_num
        if not row or all(not value.strip() for value in row):
            blanks += 1
            continue
        rows += 1
        key = tuple(row)
        if key in seen:
            duplicates += 1
            if len(examples["exact_duplicate_lines"]) < MAX_EXAMPLES:
                examples["exact_duplicate_lines"].append([seen[key], line])
        else:
            seen[key] = line
        if len(row) != len(header):
            issue("column_count_mismatch", line)
            continue
        start_raw, end_raw, label, location = row
        labels[label] += 1
        locations[location] += 1
        for name, value in zip(header, row):
            if not value.strip():
                issue("missing_" + name, line)
        if label not in categories:
            issue("label_not_in_readme", line)
        try:
            start, end = _number(start_raw), _number(end_raw)
        except ValueError as error:
            issue(str(error), line)
            continue
        if start != start.to_integral_value() or end != end.to_integral_value():
            issue("noninteger_frame_value", line)
            continue
        start, end = int(start), int(end)
        if min(start, end) < 0:
            issue("negative_frame_value", line)
        if end < start:
            issue("reversed_interval", line)
        if end == start:
            issue("equal_start_end_semantics_unverified", line)
        if previous_start is not None and start < previous_start:
            out_of_order += 1
            if len(examples["out_of_order_start_line_pairs"]) < MAX_EXAMPLES:
                examples["out_of_order_start_line_pairs"].append([previous_line, line])
        previous_start, previous_line = start, line
        numeric.append({"csv_line": line, "start": start, "end": end, "label": label, "location": location})
        interval_labels[(start, end, location)].add(label)
        interval_lines[(start, end, location)].append(line)
        if start < end:
            by_location[location].append((start, end, line))
    conflicts = [{"start": key[0], "end": key[1], "location": key[2], "labels": sorted(values), "csv_lines": interval_lines[key][:MAX_EXAMPLES]}
                 for key, values in interval_labels.items() if len(values) > 1]
    result = {"member_name": entry["member_name"], "relative_path": entry["relative_path"],
              "sha256": entry["sha256"], "size_bytes": len(raw), "encoding": "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8",
              "delimiter": ",", "header": header, "data_rows": rows, "blank_records": blanks,
              "integer_interval_rows": len(numeric), "exact_duplicate_rows": duplicates,
              "unique_exact_rows": rows - duplicates, "out_of_order_start_rows": out_of_order,
              "label_counts": dict(sorted(labels.items())), "location_counts": dict(sorted(locations.items())),
              "numeric_range": {"min_start": min((r["start"] for r in numeric), default=None),
                                "max_end": max((r["end"] for r in numeric), default=None)},
              "issue_counts": dict(issues), "issue_examples_csv_lines": dict(examples), "max_examples_per_kind": MAX_EXAMPLES,
              "conflicting_interval_location_groups": len(conflicts), "conflict_examples": conflicts[:MAX_EXAMPLES],
              "overlap_all_locations": _overlaps([v for group in by_location.values() for v in group]),
              "overlap_by_location": {key: _overlaps(value) for key, value in sorted(by_location.items())},
              "sample_rows": [numeric[index] for index in sorted({0, len(numeric)//2, len(numeric)-1}) if numeric and index >= 0]}
    return result, numeric


def audit_probe(asset, video, root, numeric):
    if (asset.get("sha256") != video["sha256"] or asset.get("relative_path") != video["relative_path"]
            or asset.get("size_bytes") != video["size_bytes"] or asset.get("split") != "unassigned"
            or asset.get("usage_scope") != "training_only" or asset.get("provenance", {}).get("usage_scope") != "training_only"):
        raise ValueError("Probe Asset is not bound to the extracted training video")
    _source(video, root)
    probe = asset["probe"]
    decode, index = probe.get("decode", {}), probe.get("pts_index", {})
    count = decode.get("frames")
    if (decode.get("status") != "passed" or decode.get("scope") != "full_video_stream"
            or type(count) is not int or count <= 0 or probe.get("source_sha256") != video["sha256"]
            or probe.get("source_size_bytes") != video["size_bytes"] or not index or index.get("complete") is not True
            or index.get("frame_count") != count or index.get("time_base") != asset["time_base"]):
        raise ValueError("A completed byte-bound full decode and PTS report is required")
    index_relative = index["relative_path"]
    if not index_relative.startswith(BASE + "/probes/"):
        raise ValueError("PTS index must be in this dataset's probe directory")
    index_path = safe_asset_path(index_relative, root)
    if index_path.stat().st_size != index["size_bytes"] or index["size_bytes"] > 128_000_000:
        raise ValueError("PTS size mismatch or bound exceeded")
    samples = [numeric[i] for i in sorted({0, len(numeric)//2, len(numeric)-1}) if numeric and i >= 0]
    candidates, requested = {}, set()
    for name, (base, exclusive) in CONVENTIONS.items():
        invalid = [row["csv_line"] for row in numeric
                   if not (0 <= row["start"] - base <= row["end"] - base - int(exclusive) < count)]
        mapped = []
        for row in samples:
            start, end = row["start"] - base, row["end"] - base - int(exclusive)
            if 0 <= start <= end < count:
                requested.update((start, end))
                mapped.append({"csv_line": row["csv_line"], "candidate_start_index": start, "candidate_last_included_index": end})
        candidates[name] = {"out_of_bounds_or_empty_rows": len(invalid), "example_csv_lines": invalid[:MAX_EXAMPLES], "sample_candidates": mapped}
    found, digest, previous, first, pts_count = {}, hashlib.sha256(), None, None, 0
    min_delta, max_delta = None, None
    with index_path.open("rb") as stream:
        for line in iter(lambda: stream.readline(4097), b""):
            if len(line) > 4096 or pts_count >= 2_000_000:
                raise ValueError("PTS record bound exceeded")
            digest.update(line)
            value = json.loads(line, object_pairs_hook=_unique, parse_constant=_nonfinite, parse_float=_finite_float)
            if not isinstance(value, dict):
                raise ValueError("PTS record must be an object")
            pts = value.get("pts")
            if type(value.get("frame_index")) is not int or value["frame_index"] != pts_count or type(pts) is not int or (previous is not None and pts <= previous):
                raise ValueError("PTS sequence is not complete and strictly increasing")
            if previous is not None:
                delta = pts - previous
                min_delta = delta if min_delta is None else min(min_delta, delta)
                max_delta = delta if max_delta is None else max(max_delta, delta)
            if pts_count in requested:
                found[pts_count] = pts
            if first is None:
                first = pts
            previous = pts
            pts_count += 1
    if pts_count != count or digest.hexdigest() != index["sha256"]:
        raise ValueError("PTS hash/frame count differs from the full probe")
    for evidence in candidates.values():
        for row in evidence["sample_candidates"]:
            row["candidate_start_pts"] = found[row["candidate_start_index"]]
            row["candidate_last_included_pts"] = found[row["candidate_last_included_index"]]
    return {"status": "PASS", "status_scope": "full_decode_and_pts_integrity_only", "decoded_frames": count, "duration_ms": asset["duration_ms"],
            "width": asset["width"], "height": asset["height"], "fps_num": asset["fps_num"], "fps_den": asset["fps_den"],
            "time_base": asset["time_base"], "pts_index_relative_path": index_relative, "pts_sha256": index["sha256"],
            "pts_count": pts_count, "first_pts": first, "last_pts": previous,
            "pts_delta_ticks": {"count": max(0, pts_count - 1), "min": min_delta, "max": max_delta},
            "source_probe_vfr_status": probe.get("vfr_status", "unknown"),
            "boundary_conventions": candidates, "selected_convention": None,
            "note": "Four diagnostic hypotheses, not confirmed annotation-to-time mappings. Raw media SHA reused from extraction/probe evidence; media not rehashed by this audit."}


def published_duration_comparison(total_ms, *, complete):
    """Project assertion at the author's displayed precision; no inferred tolerance."""
    if type(total_ms) is not int or total_ms < 0:
        raise ValueError("Duration evidence must be nonnegative integer milliseconds")
    with localcontext() as context:
        context.prec = 50
        published = Decimal("10.72")
        hours = Decimal(total_ms) / Decimal(3_600_000)
        rounded = hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        difference_seconds = Decimal(total_ms) / Decimal(1000) - published * Decimal(3600)
        difference_hours = difference_seconds / Decimal(3600)
    return {"author_claim_approximate": "10.72", "actual_duration_ms": total_ms,
            "actual_from_probed_duration": format(hours, "f"),
            "actual_hours_exact_ratio": {"numerator": total_ms, "denominator": 3_600_000},
            "decimal_calculation_precision": 50, "rounded_hours": format(rounded, ".2f"),
            "difference_seconds": format(difference_seconds, "f") if complete else None,
            "difference_hours": format(difference_hours, "f") if complete else None,
            "assertion": "published-precision consistency",
            "rule": "Decimal(total_duration_ms) / Decimal(3600000), quantized to 0.01 hours with ROUND_HALF_UP, equals Decimal('10.72')",
            "status": ("PASS" if rounded == published else "FAIL") if complete else "NOT_RUN",
            "reason": "Project mechanical comparison at the author's two displayed decimals; not an author-defined tolerance or exact-second equality."}


def audit(root):
    root = Path(root).resolve()
    extraction, extraction_sha = read_json(safe_asset_path(BASE + "/extracted-sources.v1.json", root))
    acquisition, acquisition_sha = read_json(safe_asset_path(BASE + "/acquisition.v1.json", root))
    if (acquisition.get("status") != "passed" or acquisition.get("sha256") != ARCHIVE_SHA256
            or acquisition.get("actual_md5") != PUBLISHER_MD5 or acquisition.get("publisher_md5") != PUBLISHER_MD5):
        raise ValueError("Reviewed complete archive integrity evidence is required")
    if extraction.get("schema_version") != "1.0" or type(extraction.get("complete")) is not bool:
        raise ValueError("Invalid extraction inventory")
    sources = extraction["sources"]
    by_name = {entry["member_name"]: entry for entry in sources}
    if len(by_name) != len(sources):
        raise ValueError("Duplicate original extraction member name")
    documents = {}
    for name in ("README.md", "LICENSE"):
        entry = by_name[name]
        raw = _source(entry, root, read_bytes=True)
        documents[name] = {"sha256": entry["sha256"], "relative_path": entry["relative_path"], "text": raw.decode("utf-8-sig")}
    readme = documents["README.md"]["text"].replace("\r\n", "\n").replace("\r", "\n")
    section = readme.split("## Action Categories", 1)[1].split("## Annotation Principle", 1)[0]
    categories = re.findall(r"^\d+\.\s+(.+)$", section, flags=re.MULTILINE)
    if len(categories) != 29 or len(set(categories)) != 29:
        raise ValueError("README category list differs from the reviewed 29 names")
    csv_entries, video_entries = {}, {}
    for name, entry in by_name.items():
        if name.startswith("annotations/") and name.endswith("_dataframe.csv"):
            csv_entries[name[len("annotations/"):-len("_dataframe.csv")]] = entry
        elif name.startswith("videos/") and name.endswith(".mp4"):
            video_entries[name[len("videos/"):-len(".mp4")]] = entry
    assets, manifest_sha = {}, None
    manifest_path = safe_asset_path("data/training/handoff/" + DATASET + ".assets.v1.json", root)
    if manifest_path.exists():
        manifest, manifest_sha = read_json(manifest_path)
        if manifest.get("schema_version") != "1.0":
            raise ValueError("Invalid training manifest version")
        for asset in manifest["assets"]:
            if asset["sha256"] in assets:
                raise ValueError("Duplicate SHA in training manifest")
            assets[asset["sha256"]] = asset
    files, all_labels, all_locations, all_issues, totals = [], Counter(), Counter(), Counter(), Counter()
    failures = []
    for stem, entry in sorted(csv_entries.items()):
        try:
            stats, numeric = audit_csv(entry, _source(entry, root, read_bytes=True), categories)
            stats["canonical_original_stem"] = stem
            video = video_entries.get(stem)
            stats["video_member_name"] = video["member_name"] if video else None
            stats["video_sha256"] = video["sha256"] if video else None
            stats["probe"] = {"status": "NOT_RUN", "reason": "Paired verified media/full probe not yet available"}
            if video and video["sha256"] in assets:
                try:
                    stats["probe"] = audit_probe(assets[video["sha256"]], video, root, numeric)
                except (OSError, ValueError, KeyError) as error:
                    stats["probe"] = {"status": "FAIL", "reason": str(error)}
                    failures.append({"scope": "probe", "member_name": video["member_name"], "error_type": type(error).__name__, "message": str(error)})
            files.append(stats)
            all_labels.update(stats["label_counts"])
            all_locations.update(stats["location_counts"])
            all_issues.update(stats["issue_counts"])
            for field in ("data_rows", "blank_records", "exact_duplicate_rows", "unique_exact_rows", "integer_interval_rows", "conflicting_interval_location_groups", "out_of_order_start_rows"):
                totals[field] += stats[field]
        except (OSError, ValueError, KeyError, csv.Error) as error:
            failures.append({"scope": "csv", "member_name": entry["member_name"], "error_type": type(error).__name__, "message": str(error)})
    complete_csv = len(csv_entries) == 10 and len(files) == 10 and not any(error["scope"] == "csv" for error in failures)
    probed = [file["probe"] for file in files if file["probe"]["status"] == "PASS"]
    complete_probe = complete_csv and len(probed) == 10
    paired = len(set(csv_entries) & set(video_entries))
    comparisons = {
        "exact_original_stem_pairs": {"author_claim": 10, "actual": paired,
                                      "status": "PASS" if extraction["complete"] and len(csv_entries) == len(video_entries) == paired == 10
                                      else "FAIL" if extraction["complete"] else "NOT_RUN"},
        "annotation_rows": {"author_claim": 9817, "actual": totals["data_rows"], "status": "PASS" if complete_csv and totals["data_rows"] == 9817 else "FAIL" if complete_csv else "NOT_RUN"},
        "category_mapping": {"author_claim": 29, "actual": 29 if complete_csv and set(all_labels) == set(categories) else None,
                             "observed_raw_label_strings": len(all_labels), "readme_names_observed": len(set(all_labels) & set(categories)),
                             "unmapped_raw_label_strings": sorted(set(all_labels) - set(categories)),
                             "status": "PASS" if complete_csv and set(all_labels) == set(categories) else "BLOCKED" if complete_csv else "NOT_RUN",
                             "reason": "Distinct label strings are not semantic category count; untranslated/unmapped originals must not be silently merged."},
        "decoded_frames": {"author_claim": 980703, "actual": sum(p["decoded_frames"] for p in probed), "status": "PASS" if complete_probe and sum(p["decoded_frames"] for p in probed) == 980703 else "FAIL" if complete_probe else "NOT_RUN"},
        "duration_hours": published_duration_comparison(sum(p["duration_ms"] for p in probed), complete=complete_probe),
    }
    return {"schema_version": "1.0", "case_id": "R-04a", "dataset_id": DATASET, "usage_scope": "training_only",
            "split": "unassigned", "generated_at": datetime.now(timezone.utc).isoformat(), "converted_events": 0,
            "extraction_complete": extraction["complete"], "snapshot_counts": {"extracted_members": len(sources), "csv_files": len(csv_entries), "video_files": len(video_entries), "exact_stem_pairs": paired, "full_probes_audited": len(probed)},
            "input_evidence": {"extraction_inventory_sha256": extraction_sha, "acquisition_report_sha256": acquisition_sha,
                               "archive_sha256": ARCHIVE_SHA256, "publisher_md5": PUBLISHER_MD5, "archive_rehashed_by_audit": False,
                               "training_manifest_sha256": manifest_sha, "documents": {name: {k: v for k, v in value.items() if k != "text"} for name, value in documents.items()}},
            "author_semantics": {"unit": "frames", "start": "First frame initiating the complete stroke motion", "end": "Frame completing racket-shuttle interaction and immediate follow-through",
                                 "frame_index_base": "unverified", "end_inclusive_or_exclusive": "unverified", "location_meaning": "unverified",
                                 "distributed_video_form": "processed video clips", "original_broadcast_time_offset": "unverified",
                                 "source_match_count_claim": 10, "uncut_full_matches_confirmed": False, "readme_categories_in_document_order": categories},
            "rights_evidence": {"package_license": "CC BY-NC 4.0", "readme_restrictions": "Noncommercial research/education; no substantial redistribution without written permission; no identifying/contacting individuals",
                                "api_license": acquisition.get("license_api"), "third_party_video_rights": "Remain with original owners",
                                "unresolved_conflicts": ["API CC BY 4.0 versus package CC BY-NC 4.0", "LICENSE sharing permission versus README redistribution restriction"],
                                "policy": "Keep separate evidence; no new permission inferred; training_only"},
            "aggregate": {**dict(totals), "issue_counts": dict(all_issues), "unique_raw_label_strings": len(all_labels),
                          "label_counts": dict(sorted(all_labels.items())), "location_counts": dict(sorted(all_locations.items()))},
            "comparisons": comparisons, "files": files, "failures": failures,
            "unpaired_csv_stems": sorted(set(csv_entries)-set(video_entries)), "unpaired_video_stems": sorted(set(video_entries)-set(csv_entries)),
            "semantic_conversion": {"status": "BLOCKED", "reasons": ["0/1 frame basis unverified", "Endpoint inclusion unverified", "Processed-clip to original-broadcast mapping unavailable", "Location semantics not documented", "Non-README raw label strings lack authoritative category mapping"],
                                    "fine_hand_technique": "unknown", "fine_footwork": "unknown"},
            "visual_boundary_review": "NOT_RUN", "claim_scope": "File/annotation/probe audit only; not human-label validation or proof of ten uncut matches."}


def markdown(report):
    counts = report["snapshot_counts"]
    lines = ["# Fine-Badminton 2026 实际数据核验", "", f"生成时间：{report['generated_at']}。固定用例 R-04a；用途 training_only，split=unassigned。", "",
             f"本快照已提取 {counts['extracted_members']} 项：{counts['csv_files']} CSV、{counts['video_files']} MP4；原 member stem 精确配对 {counts['exact_stem_pairs']} 组，完整 probe/PTS 已核验 {counts['full_probes_audited']} 组。解压完成标志：{report['extraction_complete']}。", "",
             "包内 README 明确分发的是 processed video clips，不能将10个视频称为10场无剪辑整场。start表示启动击球动作的第一帧，end表示球拍—球接触及紧接随挥完成的帧；0/1基、结束端点开闭、location含义及原转播偏移尚未确认。类别顺序仅复录README，不构造数字ID。", "",
             "LICENSE和README均指向CC BY-NC 4.0；API的CC BY 4.0另行保留。LICENSE允许Share与README限制未经书面许可再分发也有冲突；这里仅记录证据，不推断新的画面或再分发授权。", "",
             "| 项目 | 作者声明 | 本快照实测 | 状态 |", "|---|---:|---:|---|"]
    for name, value in report["comparisons"].items():
        actual = value.get('actual', value.get('actual_from_probed_duration'))
        if name == "duration_hours":
            actual = f"约{Decimal(actual):.9f}"
        if name == "category_mapping" and actual is None:
            actual = f"语义类别未确认；{value['observed_raw_label_strings']}种原始字符串"
        lines.append(f"| {name} | {value.get('author_claim', value.get('author_claim_approximate'))} | {actual} | {value['status']} |")
    duration = report["comparisons"]["duration_hours"]
    lines.extend(["", "未完成时上表实际值只是已就绪子集，不能将差值解释为完整包缺失。时长采用本项目公开的机械断言 published-precision consistency：整数毫秒经Decimal除以3600000换算小时，以ROUND_HALF_UP保留两位小数，与作者显示的10.72比较。这不是作者给定容差，也不表示精确秒数相同。",
                  f"原始实测{duration['actual_duration_ms']} ms；舍入后{duration['rounded_hours']}小时；与10.72小时的精确差值为{duration['difference_seconds']}秒，断言状态{duration['status']}。整数毫秒和精确分数保存在JSON中；小时十进制计算精度为50位。",
                  "归档完整性沿用已验证获取报告，本脚本不重复读取整包或重哈希媒体；CSV/README/LICENSE及就绪PTS均实际读取并校验SHA。", "",
                  f"README外原始标签有{len(report['comparisons']['category_mapping']['unmapped_raw_label_strings'])}种，不能擅自翻译合并后宣布29类已对齐。总数据行包含{report['aggregate']['exact_duplicate_rows']}条精确重复；不删除、不以去重数替换作者总量。数值/结构诊断：`" + json.dumps(report['aggregate']['issue_counts'], ensure_ascii=False) + "`。", "",
                  "| 原 member stem | 数据行 | 精确重复 | 原值标签数/README外 | 最小start / 最大end | probe |", "|---|---:|---:|---|---|---|"])
    for file in report["files"]:
        outside = len(set(file['label_counts']) - set(report['author_semantics']['readme_categories_in_document_order']))
        lines.append(f"| {file['canonical_original_stem'].replace('|', '&#124;')} | {file['data_rows']} | {file['exact_duplicate_rows']} | {len(file['label_counts'])}/{outside} | {file['numeric_range']['min_start']} / {file['numeric_range']['max_end']} | {file['probe']['status']} |")
    lines.extend(["", "已就绪视频的完整解码与PTS实测如下。末列依次为0基闭、0基开、1基闭、1基开的越界或空区间数；只是四种假设的诊断，不选择真实约定。", "",
                  "| 原 member stem | 解码帧数/PTS行数 | 时长秒 | 分辨率 | 元数据fps | time_base | PTS delta最小/最大 | probe VFR判定 | 四种假设异常行数 |",
                  "|---|---:|---:|---|---|---|---|---|---|"])
    for file in report["files"]:
        probe = file["probe"]
        if probe["status"] == "PASS":
            invalid = "/".join(str(probe["boundary_conventions"][name]["out_of_bounds_or_empty_rows"]) for name in CONVENTIONS)
            lines.append(f"| {file['canonical_original_stem'].replace('|', '&#124;')} | {probe['decoded_frames']}/{probe['pts_count']} | {probe['duration_ms']/1000:.3f} | {probe['width']}×{probe['height']} | {probe['fps_num']}/{probe['fps_den']} | {probe['time_base']} | {probe['pts_delta_ticks']['min']}/{probe['pts_delta_ticks']['max']} | {probe['source_probe_vfr_status']} | {invalid} |")
    lines.extend(["", "| 实际标签 | 行数 |", "|---|---:|"])
    for label, count in report["aggregate"]["label_counts"].items():
        lines.append(f"| {label.replace('|', '&#124;')} | {count} |")
    lines.extend(["", "位置原值频数：`" + json.dumps(report["aggregate"]["location_counts"], ensure_ascii=False) + "`。", "",
                  "重复、冲突、乱序、严格重叠及数值异常逐文件明细、原CSV行号、首/中/末抽样和四种帧边界假设保存在同名JSON。表中probe PASS只表示完整解码证据及PTS索引完整性通过；不表示标注时间映射已确认。重叠不自动判错；四种边界假设不选定任何一种，不转换Event。", "",
                  f"文件解析/完整性失败数：{len(report['failures'])}。语义转换BLOCKED；真实画面边界抽检NOT_RUN；三细标签保持unknown。", "",
                  "复跑命令：`python -B -m scripts.library.audit_fine_annotations`。仅从共享盘读取，两个报告写入本仓库docs/library。", "",
                  f"归档SHA256：`{ARCHIVE_SHA256}`；作者MD5：`{PUBLISHER_MD5}`。输入清单、README、LICENSE及训练manifest的SHA见JSON evidence。", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", default="D:/video")
    args = parser.parse_args()
    report = audit(args.storage_root)
    output = Path(__file__).resolve().parents[2] / "docs/library"
    storage = Path(args.storage_root).resolve()
    if output.resolve().is_relative_to(storage):
        raise ValueError("Reports must not be written into the shared storage tree")
    payload = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_JSON:
        raise ValueError("Audit report exceeds 10 MB")
    (output / "FINE_BADMINTON_2026_DATA_REPORT.json").write_bytes(payload)
    (output / "FINE_BADMINTON_2026_DATA_REPORT.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"counts": report["snapshot_counts"], "comparisons": report["comparisons"], "failures": report["failures"]}, ensure_ascii=True))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
