"""Read-only same-PTS pose diagnostics; prints JSON and never creates BST inputs."""
from collections import Counter
import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.models import prepare_bst_window as preparation


def distribution(values):
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {"count": len(values), "min": min(values), "median": statistics.median(values), "max": max(values)}


def compact_row(row):
    result = {key: value for key, value in row.items() if key != "players"}
    result["players"] = [{key: person[key] for key in ("detection_id", "box_xyxy", "court_position", "raw_track_id", "ankle_scores", "detector_score")} for person in row["players"]]
    return result


def summarize(document, asset):
    timeline, _ = preparation.timeline(document, asset)
    calibration = preparation.calibration(asset)
    rows, previous = [], None
    for key, (index, frame) in timeline.items():
        candidates, excluded, reasons, checks = [], [], [], []
        for detection in frame["detections"]:
            candidate, reason = preparation.candidate_player(detection, calibration["homography"], asset)
            if candidate is not None:
                candidate["raw_track_id"] = detection.get("track_id")
                candidate["ankle_scores"] = detection["keypoint_scores"][-2:]
                candidates.append(candidate)
            else:
                excluded.append(reason)
                if reason != "outside_court":
                    reasons.append(reason)
        candidates.sort(key=lambda item: item["court_position"][1])
        if len(candidates) != 2:
            reasons.append("court_person_count_not_two")
        if len(candidates) == 2 and (candidates[1]["court_position"][1]-candidates[0]["court_position"][1] < .05
                                    or not candidates[0]["court_position"][1] < .5 < candidates[1]["court_position"][1]):
            reasons.append("top_bottom_side_ambiguous")
        if not reasons and previous is not None:
            if index != previous["source_frame_index"]+1:
                reasons.append("pose_source_frame_gap")
            else:
                dt = float((key[0]-previous["pts"])*Fraction(key[1]))
                for side, old, current in zip(("far", "near"), previous["players"], candidates):
                    court_speed = math.dist(old["court_position"],current["court_position"])/dt
                    image_speed = math.dist(old["image_center"],current["image_center"])/math.hypot(asset["width"],asset["height"])/dt
                    accepted = court_speed <= preparation.MAX_COURT_SPEED and image_speed <= preparation.MAX_IMAGE_SPEED
                    checks.append({"side": side, "court_units_per_second": court_speed, "image_diagonals_per_second": image_speed, "accepted": accepted})
                    if not accepted:
                        reasons.append("anonymous_track_continuity_disagreement")
        row = {"source_frame_index": index, "pts": key[0], "source_ms": frame["source_ms"],
               "raw_detection_count": len(frame["detections"]), "court_candidate_count": len(candidates),
               "players": candidates, "exclusions": dict(Counter(excluded)), "blocked_reasons": sorted(set(reasons)), "association_checks": checks}
        rows.append(row)
        previous = None if reasons else row
    side_rows = [row for row in rows if len(row["players"]) == 2 and "top_bottom_side_ambiguous" not in row["blocked_reasons"]]
    sides = {}
    for position, side in enumerate(("far", "near")):
        scores = [s for row in side_rows for s in row["players"][position]["ankle_scores"]]
        ids = [row["players"][position]["raw_track_id"] for row in side_rows]
        changes = []
        for before, after in zip(side_rows, side_rows[1:]):
            a, b = before["players"][position]["raw_track_id"], after["players"][position]["raw_track_id"]
            if after["source_frame_index"] == before["source_frame_index"]+1 and a is not None and b is not None and a != b:
                changes.append(after["source_frame_index"])
        sides[side] = {"selected_frames": len(side_rows), "ankle_raw_scores": distribution(scores),
                       "both_ankles_at_least_point5_frames": sum(min(row["players"][position]["ankle_scores"]) >= .5 for row in side_rows)
                       if document.get("producer", {}).get("model_id") == "yolo11n-pose-bytetrack" else None,
                       "non_null_track_counts": dict(Counter(identity for identity in ids if identity is not None)),
                       "null_track_frames": sum(identity is None for identity in ids), "adjacent_model_id_change_frames": changes}
    summary = {"frames": len(rows), "first_frame": rows[0]["source_frame_index"], "last_frame": rows[-1]["source_frame_index"],
               "raw_non_null_track_counts": dict(Counter(d["track_id"] for f in document["frames"] for d in f["detections"] if d.get("track_id") is not None)),
               "raw_missing_track_frames": {str(index): frame["missing_previously_seen_track_ids"] for index, frame in timeline.values() if frame.get("missing_previously_seen_track_ids")},
               "raw_detections": distribution([row["raw_detection_count"] for row in rows]),
               "court_count_histogram": dict(Counter(row["court_candidate_count"] for row in rows)),
               "pose_geometry_guard_pass_frames": sum(not row["blocked_reasons"] for row in rows),
               "blocked_frames": {str(row["source_frame_index"]): row["blocked_reasons"] for row in rows if row["blocked_reasons"]},
               "sides": sides, "focus": {str(row["source_frame_index"]): compact_row(row) for row in rows if row["source_frame_index"] in {31,32,54,65,66}}}
    return summary, timeline


def compare(old, new):
    asset = new["source_asset"]
    if old.get("source_sha256") != new.get("source_sha256") or old.get("asset_id") != new.get("asset_id"):
        raise ValueError("Pose comparisons must use the exact same source Asset/hash")
    old_summary, old_timeline = summarize(old, asset)
    new_summary, new_timeline = summarize(new, asset)
    if set(old_timeline) != set(new_timeline):
        raise ValueError("Comparison requires exactly the same source PTS set; no unmatched frames dropped")
    return {"status": "diagnostic_only_no_ground_truth", "asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
            "calibration": preparation.calibration(asset), "exact_pts_pairs": len(old_timeline),
            "old": old_summary, "yolo": new_summary, "accuracy": None, "recall": None,
            "warning": "Same projection/continuity guards, not human calibration, identity truth, confidence calibration, or BST readiness"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--old", required=True)
    parser.add_argument("--yolo", required=True)
    args = parser.parse_args()
    old, old_provenance = preparation.read_json(args.root, args.old)
    new, new_provenance = preparation.read_json(args.root, args.yolo)
    result = compare(old, new)
    result["input_artifacts"] = {"old": old_provenance, "yolo": new_provenance}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
