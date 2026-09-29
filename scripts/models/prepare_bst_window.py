"""CPU review aid for video_001951 only; never runs models or fills missing data.

Inputs/outputs are storage-root-relative paths. Automatic associations remain
proposals until an explicit scoped assignment-review JSON is supplied.
"""
from collections import Counter
from fractions import Fraction
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.models import bst_reuse as bst
from packages.models.protocol import InvalidRequest, ModelBlocked, atomic_write_json, resolve_relative, storage_root
from packages.models.storage import reserve
from packages.models.vl_embedding_reuse import usage_scope

SOURCE_SHA = "5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90"
SOURCE_POINTS = [[380, 327], [896, 327], [1050, 668], [221, 668]]
COURT_POINTS = [[0, 0], [1, 0], [1, 1], [0, 1]]
CALIBRATION_ID = "video001951-root-agent-proposed-20260929"
CAMERA_ID = "video001951-continuous-camera-proposed"
MAX_JSON_BYTES = 12_000_000
MAX_COURT_SPEED = 6.0  # unit-court distance / second; diagnostic association guard, not trained threshold
MAX_IMAGE_SPEED = 2.5  # normalized image diagonal / second


def need(value, message):
    if not value:
        raise InvalidRequest(message, "bst_preparation_invalid")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def homography(source, target):
    """Solve the eight point constraints using pivoted elimination (stdlib)."""
    rows = []
    for (x, y), (u, v) in zip(source, target):
        rows.extend([[x, y, 1, 0, 0, 0, -u*x, -u*y, u],
                     [0, 0, 0, x, y, 1, -v*x, -v*y, v]])
    for col in range(8):
        pivot = max(range(col, 8), key=lambda i: abs(rows[i][col]))
        need(abs(rows[pivot][col]) > 1e-12, "Degenerate calibration geometry")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v/divisor for v in rows[col]]
        for i in range(8):
            if i != col:
                factor = rows[i][col]
                rows[i] = [a-factor*b for a, b in zip(rows[i], rows[col])]
    values = [rows[i][8] for i in range(8)] + [1.0]
    return [values[:3], values[3:6], values[6:]]


def calibration(asset):
    need(asset.get("sha256") == SOURCE_SHA and asset.get("width") == 1280 and asset.get("height") == 720
         and asset.get("fps_num") == 30 and asset.get("fps_den") == 1 and asset.get("time_base") == "1/15360"
         and asset.get("duration_ms") == 6000 and asset.get("discipline") == "singles",
         "This proposed calibration is restricted to the verified video_001951 Asset")
    return {"id": CALIBRATION_ID, "status": "agent_reviewed", "proposal": True,
            "human_confirmed": False, "method": "Root agent visually proposed four outer-court source-pixel corners",
            "evidence": "Root agent reports viewing source at 0,1,2,3,5 seconds; camera/court stable. Corners supplied in task instruction; not human calibration truth.",
            "camera_segment_id": CAMERA_ID, "coordinate_space": "source_pixels_to_unit_court",
            "source_width": 1280, "source_height": 720, "valid_start_ms": 0, "valid_end_ms": 6000,
            "source_points": copy.deepcopy(SOURCE_POINTS), "court_points": copy.deepcopy(COURT_POINTS),
            "homography": homography(SOURCE_POINTS, COURT_POINTS)}


def read_json(root, relative, maximum=MAX_JSON_BYTES):
    path = resolve_relative(root, relative)
    need(path.is_file() and path.stat().st_size <= maximum, "Missing or oversized input JSON")
    raw = path.read_bytes()
    need(len(raw) <= maximum, "JSON changed beyond input limit")
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(InvalidRequest("Nonfinite JSON")))
    return payload, {"relative_path": relative, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def timeline(document, asset):
    need(document.get("asset_id") == asset["asset_id"] and document.get("source_sha256") == asset["sha256"], "Input feature source identity mismatch")
    frames = document.get("frames")
    need(isinstance(frames, list) and 1 <= len(frames) <= 600, "Expected bounded real feature frames")
    rows, last, offset = {}, None, None
    for frame in frames:
        need(type(frame.get("pts")) is int and frame.get("time_base") == asset["time_base"]
             and type(frame.get("stream_start_pts")) is int, "Exact source PTS/time_base/start PTS required")
        need(frame.get("width") == asset["width"] and frame.get("height") == asset["height"], "Source frame dimensions differ")
        if offset is None:
            offset = frame["stream_start_pts"]
        need(frame["stream_start_pts"] == offset and (last is None or frame["pts"] > last), "Duplicate, changing-origin or nonmonotonic PTS")
        stamp = Fraction(frame["pts"]-offset) * Fraction(asset["time_base"])
        number = stamp * Fraction(asset["fps_num"], asset["fps_den"])
        need(number.denominator == 1 and 0 <= stamp*1000 < asset["duration_ms"], "This asset-specific adapter requires exact original CFR frame indices")
        need(finite(frame.get("source_ms")) and abs(frame["source_ms"]-float(stamp*1000)) <= .501, "Declared source milliseconds disagree with PTS")
        key = (frame["pts"], frame["time_base"])
        need(key not in rows, "Duplicate source PTS")
        rows[key] = (int(number), frame)
        last = frame["pts"]
    return rows, offset


def candidate_player(detection, h, asset):
    box, points = detection.get("box_xyxy"), detection.get("keypoints_xyv")
    if not isinstance(box, list) or len(box) != 4 or not all(finite(v) for v in box) or not 0 <= box[0] < box[2] <= asset["width"] or not 0 <= box[1] < box[3] <= asset["height"]:
        return None, "invalid_bbox"
    if not isinstance(points, list) or len(points) != 17 or any(not isinstance(p, list) or len(p) != 3 or not all(finite(v) for v in p)
           or not 0 <= p[0] <= asset["width"] or not 0 <= p[1] <= asset["height"] or p[2] <= 0 or (p[0] == p[1] == 0) for p in points):
        return None, "missing_or_invalid_pose_points"
    feet = [bst.project(p[:2], h) for p in points[-2:]]
    position = [sum(p[axis] for p in feet)/2 for axis in (0, 1)]
    if not all(-.01 < coordinate < 1.01 for coordinate in position):
        return None, "outside_court"
    return {"detection_id": detection.get("detection_id"), "box_xyxy": copy.deepcopy(box),
            "keypoints_xyv": copy.deepcopy(points), "keypoint_scores": copy.deepcopy(detection.get("keypoint_scores")),
            "detector_score": detection.get("score"), "ankles_status": "observed",
            "ankles_definition": "raw model-predicted points; not human visibility confirmation",
            "court_position": position, "image_center": [(box[0]+box[2])/2, (box[1]+box[3])/2],
            "association_status": "proposed", "player_id": None}, None


def contiguous_runs(rows):
    runs, current = [], []
    for row in rows:
        continuous = current and row["source_frame_index"] == current[-1]["source_frame_index"]+1 and row.get("track_ids") == current[-1].get("track_ids")
        if not row["usable"] or (current and not continuous):
            if current:
                runs.append(current)
                current = []
        if row["usable"]:
            current.append(row)
    if current:
        runs.append(current)
    return [{"start_frame": run[0]["source_frame_index"], "end_frame": run[-1]["source_frame_index"]+1,
             "frame_count": len(run), "start_pts": run[0]["pts"], "last_pts": run[-1]["pts"],
             "time_base": run[0]["time_base"], "track_ids": run[0]["track_ids"]} for run in runs]


def prepare_review(asset, pose, shuttle, provenance, *, root, boundaries=None, assignment_review=None, review_range=None):
    cal = calibration(asset)
    need(pose.get("sampling") == "continuous_original_pts" and pose.get("producer", {}).get("model_id") == "torchvision-continuous-pose", "Use real continuous pose features, not sparse poses relabelled as dense")
    need(shuttle.get("format") == "tracknet-observation-source-pixels-v1" and shuttle.get("producer", {}).get("model_id") == "tracknetv3-reuse", "Expected TrackNet source-pixel observations")
    poses, pose_origin = timeline(pose, asset)
    balls, ball_origin = timeline(shuttle, asset)
    need(pose_origin == ball_origin, "Pose and shuttle stream origins differ")
    if review_range is not None:
        need(isinstance(review_range, (list, tuple)) and len(review_range) == 2 and all(type(v) is int for v in review_range)
             and 0 <= review_range[0] < review_range[1] <= 180, "Review interval requires explicit source frame bounds")
        poses = {key: value for key, value in poses.items() if review_range[0] <= value[0] < review_range[1]}
        need(len(poses) > 0, "No real pose frames in requested review interval")
    scopes = [usage_scope(asset, root), pose.get("usage_scope"), shuttle.get("usage_scope"),
              pose.get("producer", {}).get("usage_scope"), shuttle.get("producer", {}).get("usage_scope")]
    need(all(scope in {None, "general", "training_only"} for scope in scopes), "Unknown feature usage_scope")
    scope = "training_only" if "training_only" in scopes else "general"
    rows, previous, segment = [], None, 0
    for key, (index, raw_pose) in poses.items():
        reasons, candidates, excluded, checks = [], [], [], []
        detections = raw_pose.get("detections")
        need(isinstance(detections, list) and len(detections) <= 10, "Malformed raw pose detections")
        for detection in detections:
            player, reason = candidate_player(detection, cal["homography"], asset)
            if player is not None:
                candidates.append(player)
            else:
                excluded.append({"detection_id": detection.get("detection_id"), "reason": reason})
                if reason != "outside_court":
                    reasons.append(reason)
        if raw_pose.get("detections_omitted_by_cap", 0):
            reasons.append("pose_detection_cap_omitted_candidates")
        if len(candidates) != 2:
            reasons.append("court_person_count_not_two")
        candidates.sort(key=lambda person: person["court_position"][1])
        if len(candidates) == 2 and (candidates[1]["court_position"][1]-candidates[0]["court_position"][1] < .05
                or not candidates[0]["court_position"][1] < .5 < candidates[1]["court_position"][1]):
            reasons.append("top_bottom_side_ambiguous")
        if not reasons and previous is not None:
            if index != previous["source_frame_index"]+1:
                reasons.append("pose_source_frame_gap")
            else:
                dt = (key[0]-previous["pts"]) * Fraction(key[1])
                for side, old, current in zip(("top", "bottom"), previous["players"], candidates):
                    court_speed = math.dist(old["court_position"], current["court_position"])/float(dt)
                    image_speed = math.dist(old["image_center"], current["image_center"])/math.hypot(asset["width"], asset["height"])/float(dt)
                    accepted = court_speed <= MAX_COURT_SPEED and image_speed <= MAX_IMAGE_SPEED
                    checks.append({"side": side, "previous_detection_id": old["detection_id"], "current_detection_id": current["detection_id"],
                                   "court_units_per_second": court_speed, "image_diagonals_per_second": image_speed, "accepted": accepted})
                    if not accepted:
                        reasons.append("anonymous_track_continuity_disagreement")
        if reasons:
            previous = None
            track_ids = None
        else:
            if previous is None:
                segment += 1
            track_ids = [f"video001951-segment-{segment}-{side}-candidate" for side in ("top", "bottom")]
            for player, track in zip(candidates, track_ids):
                player["track_id"] = track
            previous = {"source_frame_index": index, "pts": key[0], "players": candidates}
        raw_ball = balls.get(key, (None, None))[1]
        if raw_ball is None:
            reasons.append("shuttle_pts_missing")
        elif raw_ball.get("status") != "observed" or raw_ball.get("inpainted") is not False:
            reasons.append("shuttle_missing_or_imputed")
        elif not finite(raw_ball.get("x")) or not finite(raw_ball.get("y")) or not 0 <= raw_ball["x"] <= asset["width"] or not 0 <= raw_ball["y"] <= asset["height"] or raw_ball["x"] == raw_ball["y"] == 0:
            reasons.append("shuttle_coordinates_invalid")
        elif not finite(raw_ball.get("available_after_source_ms")) or not raw_pose["source_ms"]-.001 <= raw_ball["available_after_source_ms"] <= asset["duration_ms"]:
            reasons.append("shuttle_availability_invalid")
        rows.append({"source_frame_index": index, "pts": key[0], "time_base": key[1],
                     "source_ms": round((key[0]-pose_origin)*float(Fraction(key[1]))*1000),
                     "width": asset["width"], "height": asset["height"], "players": candidates,
                     "track_ids": track_ids, "raw_pose_frame_index": raw_pose.get("frame_index"),
                     "raw_shuttle_frame_index": raw_ball.get("frame_index") if raw_ball else None,
                     "excluded_detections": excluded, "association_checks": checks, "usable": not reasons, "blocked_reasons": sorted(set(reasons)),
                     "shuttle": {**copy.deepcopy(raw_ball), "available_at_source_ms": raw_ball.get("available_after_source_ms")} if raw_ball else None})
    counts = Counter(reason for row in rows for reason in row["blocked_reasons"])
    report = {"schema_version": "1.0", "format": "bst-window-review-v1", "asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
              "usage_scope": scope, "calibration": cal, "provenance": provenance, "rows": rows,
              "statistics": {"pose_frames": len(rows), "shuttle_frames": len(balls), "exact_pts_joined": sum(row["shuttle"] is not None for row in rows),
                             "usable_frames": sum(row["usable"] for row in rows), "usable_fraction": sum(row["usable"] for row in rows)/len(rows),
                             "blocked_reason_counts": dict(counts)}, "usable_continuous_windows": contiguous_runs(rows),
              "association_method": {"kind": "proposed court Top/Bottom plus adjacent source-frame center continuity", "max_court_units_per_second": MAX_COURT_SPEED,
                                     "max_image_diagonals_per_second": MAX_IMAGE_SPEED, "thresholds_status": "developer-authored diagnostic guards; unvalidated", "identity": "anonymous candidates only"},
              "human_review_claim": False, "status": "review_required", "blocked_reasons": [],
              "reviewed_source_frame_interval": list(review_range) if review_range is not None else None,
              "missing_policy": "No interpolation, synthetic zeros, substitution, dropping of bad frames inside a selected shot, or automatic review promotion"}
    candidate = {"schema_version": "1.0", "format": "bst-source-features-v1", "asset_id": asset["asset_id"],
                 "source_sha256": asset["sha256"], "usage_scope": scope, "source_start_pts": pose_origin,
                 "camera_segment": {"id": CAMERA_ID, "start_ms": 0, "end_ms": 6000}, "calibration": cal,
                 "provenance": provenance, "shot_boundaries": boundaries,
                 "selection": {"method": "explicit reviewed shot bounds; joined original observations only", "coverage_claim": "single diagnostic window; no accuracy/recall claim"}}
    final = None
    if boundaries is None:
        report["blocked_reasons"].append("explicit_shot_boundaries_missing")
    else:
        try:
            start, end = bst.shot_window(boundaries, Fraction(asset["fps_num"], asset["fps_den"]))
            selected = [row for row in rows if start <= row["source_frame_index"] < end]
            report["selected_shot_window"] = {"start_frame": start, "end_frame": end, "observed_rows": len(selected)}
            if len(selected) != end-start or not selected or any(not row["usable"] for row in selected):
                report["blocked_reasons"].append("selected_shot_incomplete_or_has_blocked_observations")
            else:
                ids = selected[0]["track_ids"]
                if any(row["track_ids"] != ids for row in selected):
                    report["blocked_reasons"].append("selected_shot_crosses_anonymous_track_segments")
                template = {"asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
                            "pose_artifact_sha256": provenance["pose"]["artifact_sha256"], "shuttle_artifact_sha256": provenance["shuttle"]["artifact_sha256"],
                            "reviewed_frame_range": [start, end], "track_ids": ids, "status": "unreviewed",
                            "method": "Review source overlays and proposed Top/Bottom continuity", "evidence": ""}
                report["assignment_review_template"] = template
                if not isinstance(assignment_review, dict) or assignment_review.get("status") not in bst.REVIEWED or not all(assignment_review.get(k) == v for k, v in template.items() if k not in {"status", "method", "evidence"}):
                    report["blocked_reasons"].append("explicit_scoped_assignment_review_missing")
                if not report["blocked_reasons"]:
                    candidate.update(track_assignment=assignment_review, frames=selected)
                    prepared = bst.prepare_features(candidate, asset)
                    final = candidate
                    report.update(status="prepared", strict_prepare_summary={"valid_length": prepared["valid_length"], "start_frame": start, "end_frame": end})
        except ModelBlocked as exc:
            report["blocked_reasons"].append(exc.code)
    return report, final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("asset-file", "pose-features", "shuttle-features", "output-dir"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--shot-boundaries")
    parser.add_argument("--assignment-review")
    parser.add_argument("--review-start-frame", type=int, help="Optional diagnostic view interval; does not define a shot boundary")
    parser.add_argument("--review-end-frame", type=int, help="Exclusive source frame end for diagnostic view interval")
    args = parser.parse_args(argv)
    root = storage_root()
    asset_doc, asset_ref = read_json(root, args.asset_file)
    if isinstance(asset_doc, dict) and "assets" in asset_doc:
        need(len(asset_doc["assets"]) == 1, "Asset file request must contain one source Asset")
        asset = asset_doc["assets"][0]
    else:
        asset = asset_doc
    pose, pose_ref = read_json(root, args.pose_features)
    shuttle, ball_ref = read_json(root, args.shuttle_features)
    boundaries, shot_ref = read_json(root, args.shot_boundaries, 64000) if args.shot_boundaries else (None, None)
    review, review_ref = read_json(root, args.assignment_review, 64000) if args.assignment_review else (None, None)
    provenance = {"pose": {**pose_ref, "artifact_sha256": pose_ref["sha256"], "model_id": pose.get("producer", {}).get("model_id")},
                  "shuttle": {**ball_ref, "artifact_sha256": ball_ref["sha256"], "model_id": shuttle.get("producer", {}).get("model_id")}}
    need((args.review_start_frame is None) == (args.review_end_frame is None), "Both review frame bounds are required")
    review_range = [args.review_start_frame, args.review_end_frame] if args.review_start_frame is not None else None
    report, final = prepare_review(asset, pose, shuttle, provenance, root=root, boundaries=boundaries, assignment_review=review, review_range=review_range)
    report["input_files"] = {"asset": asset_ref, "pose": pose_ref, "shuttle": ball_ref, "shot_boundaries": shot_ref, "assignment_review": review_ref}
    output = resolve_relative(root, args.output_dir, owner="models")
    with reserve(root, 100_000_000):
        output.mkdir(parents=True, exist_ok=True)
        need(not any(output.iterdir()), "Use a new empty preparation directory; old results are preserved")
        # Preserve complete original JSON observations, including excluded and missing records.
        atomic_write_json(output / "raw-inputs.json", {"schema_version": "1.0", "usage_scope": report["usage_scope"],
                          "asset": asset, "pose": pose, "shuttle": shuttle, "input_files": report["input_files"]})
        atomic_write_json(output / "review.json", report)
        if final is not None:
            target = atomic_write_json(output / "bst-features.json", final)
            raw = target.read_bytes()
            atomic_write_json(output / "bst-features-entry.json", {"relative_path": target.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
    print(json.dumps({"status": report["status"], "statistics": report["statistics"], "usable_continuous_windows": report["usable_continuous_windows"],
                      "blocked_reasons": report["blocked_reasons"], "output_dir": args.output_dir}, ensure_ascii=False))
    return 0 if final is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
