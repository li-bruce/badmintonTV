"""Strict offline BST reuse. Importing this module performs no ML/network work.

Only observed, source-aligned features enter the classifier. Tail padding is the
reviewed author's length padding, never a replacement for missing observations.
The stdlib preparation functions are usable in CPU guard tests, not accuracy tests.
"""
from fractions import Fraction
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import types

from .protocol import InvalidRequest, ModelBlocked, atomic_write_json, make_artifact, resolve_relative, validate_request
from .storage import reserve

MODEL_ID = "bst-cg-ap-reuse"
COMMIT = "fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df"
CODE_HASHES = {
    "bst.py": "4313f9f411a90da24bfeead81f88b83894363bfd5248a75132a8c60ec3905b74",
    "tempose.py": "0f3274bb4c0ec1b3f4a068b066993b7f1c0d58349bb580b55d0e0919e3821bc6",
}
CODE_SIZES = {"bst.py": 33_050, "tempose.py": 24_519}
CHECKPOINT_SHA256 = "997f43e52b20cb47517132c71d3e147d7d717a2d9651cfbe7651a5003bd66809"
CHECKPOINT_BYTES = 7_514_133
FILE_ID = "1snqpEEww-GG6xFUBzkuctYAPHcBP360B"
SEQ_LEN, MAX_FRAMES = 100, 600
STROKES = ("放小球", "擋小球", "殺球", "挑球", "長球", "平球", "切球", "推球", "撲球", "勾球", "發短球", "發長球")
LABELS = ("未知球種",) + tuple(side + kind for side in ("Top_", "Bottom_") for kind in STROKES)
BONES = ((0, 1), (0, 2), (1, 2), (1, 3), (2, 4), (3, 5), (4, 6),
         (5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12),
         (11, 12), (11, 13), (13, 15), (12, 14), (14, 16))
REVIEWED = {"human_confirmed", "agent_reviewed"}


def _need(condition, code, message):
    if not condition:
        raise ModelBlocked(code, message)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().casefold() not in {"unknown", "none", "null", "unassigned"}


def _review(record, name):
    _need(isinstance(record, dict) and record.get("status") in REVIEWED
          and _text(record.get("method")) and _text(record.get("evidence")),
          "BST_REVIEW_MISSING", name + " requires explicit reviewed status, method and evidence")


def _fraction(value, name):
    _need(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", value),
          "BST_TIMELINE_INVALID", name + " must be a positive rational string")
    return Fraction(value)


def verified_file(root, entry, prefix=None, maximum=None):
    _need(isinstance(entry, dict) and type(entry.get("size_bytes")) is int
          and entry["size_bytes"] > 0 and isinstance(entry.get("sha256"), str)
          and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
          "BST_MANIFEST_INVALID", "Local file requires exact bytes and SHA256")
    if maximum is not None:
        _need(entry["size_bytes"] <= maximum, "BST_INPUT_TOO_LARGE", "Local file exceeds its byte bound")
    path = resolve_relative(root, entry.get("relative_path"), owner="models" if prefix else None)
    if prefix:
        _need(entry["relative_path"].startswith(prefix) and path.relative_to(Path(root).resolve()).as_posix().startswith(prefix),
              "BST_MANIFEST_INVALID", "Local file is outside its designated models directory")
    _need(path.is_file(), "BST_NOT_INSTALLED", "Required local source, weights or input file is missing")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        _need(before.st_size == entry["size_bytes"], "BST_HASH_MISMATCH", "Local file size differs from manifest")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    _need((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
          and digest.hexdigest() == entry["sha256"], "BST_HASH_MISMATCH", "Local file hash differs from manifest")
    return path


def _json(path, maximum):
    _need(path.is_file(), "BST_INPUT_MISSING", "Required local JSON file is missing")
    _need(path.stat().st_size <= maximum, "BST_INPUT_TOO_LARGE", "JSON exceeds its byte bound")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ModelBlocked("BST_INPUT_INVALID", "JSON must have unique keys and finite numbers") from exc


def read_manifest(root):
    path = resolve_relative(root, os.environ.get("BTV_BST_MANIFEST", "models/weights/bst/reuse-manifest.json"), owner="models")
    manifest = _json(path, 64_000)
    _need(isinstance(manifest, dict) and all(manifest.get(key) == value for key, value in {
        "schema_version": "1.0", "source_commit": COMMIT, "license": "MIT", "architecture": "BST_CG_AP",
        "pose_style": "JnB_bone", "seq_len": 100, "n_classes": 25}.items()),
        "BST_MANIFEST_INVALID", "BST manifest does not specify the reviewed architecture and commit")
    code, checkpoint = manifest.get("code"), manifest.get("checkpoint")
    _need(isinstance(code, dict) and set(code) == set(CODE_HASHES) and isinstance(checkpoint, dict),
          "BST_MANIFEST_INVALID", "BST needs exactly the two reviewed model source files and a checkpoint")
    paths = {}
    for name, digest in CODE_HASHES.items():
        _need(isinstance(code[name], dict) and code[name].get("sha256") == digest
              and code[name].get("size_bytes") == CODE_SIZES[name],
              "BST_SOURCE_UNREVIEWED", "BST source does not match the reviewed fixed commit")
        paths[name] = verified_file(root, code[name], "models/upstream/", 100_000)
        _need(paths[name].name == name, "BST_MANIFEST_INVALID", "BST source filename differs from reviewed module")
    _need(checkpoint.get("sha256") == CHECKPOINT_SHA256 and checkpoint.get("size_bytes") == CHECKPOINT_BYTES
          and checkpoint.get("drive_file_id") == FILE_ID, "BST_CHECKPOINT_UNSUPPORTED", "BST requires the reviewed 25-class CG/AP checkpoint")
    weight = verified_file(root, checkpoint, "models/weights/", 10_000_000)
    return manifest, paths, weight


def _exec_reviewed_source(path, name, namespace):
    """Compile exactly the bounded bytes checked against our fixed source pins."""
    _need(name in CODE_HASHES and name in CODE_SIZES, "BST_SOURCE_UNREVIEWED", "Unknown BST source module")
    with path.open("rb") as stream:
        source = stream.read(CODE_SIZES[name] + 1)
    _need(len(source) == CODE_SIZES[name] and hashlib.sha256(source).hexdigest() == CODE_HASHES[name],
          "BST_SOURCE_UNREVIEWED", "BST executable source changed or does not match the fixed reviewed bytes")
    exec(compile(source, str(path), "exec"), namespace)


def project(point, homography):
    x, y = point
    vector = [sum(row[i] * (x, y, 1)[i] for i in range(3)) for row in homography]
    _need(abs(vector[2]) > 1e-12, "BST_CALIBRATION_INVALID", "Point projects to the homography horizon")
    result = [vector[i] / vector[2] for i in (0, 1)]
    _need(all(_number(v) for v in result), "BST_CALIBRATION_INVALID", "Court projection is not finite")
    return result


def validate_calibration(calibration, asset, start_ms, end_ms):
    _review(calibration, "Court calibration")
    _need(_text(calibration.get("id")) and calibration.get("coordinate_space") == "source_pixels_to_unit_court"
          and calibration.get("source_width") == asset["width"] and calibration.get("source_height") == asset["height"],
          "BST_CALIBRATION_INVALID", "Calibration must specify the source dimensions and source-pixel homography")
    _need(_number(calibration.get("valid_start_ms")) and _number(calibration.get("valid_end_ms"))
          and 0 <= calibration["valid_start_ms"] <= start_ms < end_ms <= calibration["valid_end_ms"] <= asset["duration_ms"],
          "BST_CALIBRATION_INVALID", "Calibration does not cover the entire selected shot window")
    source, target, h = calibration.get("source_points"), calibration.get("court_points"), calibration.get("homography")
    _need(target == [[0, 0], [1, 0], [1, 1], [0, 1]], "BST_CALIBRATION_INVALID", "Court corner order must be far-left, far-right, near-right, near-left")
    _need(isinstance(source, list) and len(source) == 4 and all(isinstance(p, list) and len(p) == 2
          and all(_number(v) for v in p) and 0 <= p[0] <= asset["width"] and 0 <= p[1] <= asset["height"] for p in source),
          "BST_CALIBRATION_INVALID", "Four finite source court corners are required")
    _need(isinstance(h, list) and len(h) == 3 and all(isinstance(row, list) and len(row) == 3
          and all(_number(v) for v in row) for row in h), "BST_CALIBRATION_INVALID", "Homography must be finite 3 by 3")
    cross = []
    for i in range(4):
        a, b, c = source[i], source[(i + 1) % 4], source[(i + 2) % 4]
        cross.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    _need(all(v > 1 for v in cross) or all(v < -1 for v in cross), "BST_CALIBRATION_INVALID", "Court corners must form a nondegenerate convex quadrilateral")
    for point, expected in zip(source, target):
        actual = project(point, h)
        _need(max(abs(a - b) for a, b in zip(actual, expected)) <= 1e-5,
              "BST_CALIBRATION_INVALID", "Homography does not map the supplied four points to the claimed court")
    return h


def shot_window(boundaries, fps):
    _review(boundaries, "Shot boundaries")
    current, previous, following = (boundaries.get(k) for k in ("current_frame", "previous_frame", "next_frame"))
    _need(type(current) is int and current >= 0, "BST_SHOT_BOUNDARIES_MISSING", "A reviewed current shot frame is required")
    for value, name, reason in ((previous, "previous", "rally_start"), (following, "next", "rally_end")):
        _need((type(value) is int and value >= 0) or (value is None and boundaries.get(name + "_missing_reason") == reason),
              "BST_SHOT_BOUNDARIES_MISSING", "Missing neighboring shot requires an explicit rally-edge reason")
    _need((previous is None or previous < current) and (following is None or following > current),
          "BST_SHOT_BOUNDARIES_INVALID", "Shot boundaries must be chronologically ordered")
    half, limit = int(fps // 2), int((fps * 3) // 2)
    eps = half // 2
    start = max(previous if previous is not None else current - half, current - limit)
    end = min(following + eps if following is not None else current + half, current + limit + eps)
    _need(0 <= start < current < end and 2 <= end - start <= MAX_FRAMES,
          "BST_SHOT_BOUNDARIES_INVALID", "Author shot window is outside the supported source interval")
    return start, end


def normalize_pose(points, bbox):
    """BBox diagonal and center alignment; retain author's per-coordinate sentinel."""
    diagonal = math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1])
    center = [(bbox[2] - bbox[0]) / (2 * diagonal), (bbox[3] - bbox[1]) / (2 * diagonal)]
    joints = [[((point[axis] - bbox[axis]) / diagonal if point[axis] != 0 else 0.0) - center[axis]
               for axis in (0, 1)] for point in points]
    bones = [[joints[end][axis] - joints[start][axis] if joints[start][axis] != 0 and joints[end][axis] != 0 else 0.0
              for axis in (0, 1)] for start, end in BONES]
    return [value for point in joints + bones for value in point]


def prepare_features(pack, asset):
    """Validate a complete observed shot window and return stdlib tensor lists."""
    _need(isinstance(pack, dict) and pack.get("schema_version") == "1.0" and pack.get("format") == "bst-source-features-v1",
          "BST_INPUT_MISSING", "A bst-source-features-v1 pack is required")
    _need(pack.get("asset_id") == asset["asset_id"] and pack.get("source_sha256") == asset["sha256"],
          "BST_SOURCE_MISMATCH", "Features must identify the exact source Asset and SHA256")
    _need(asset["discipline"] == "singles", "BST_DISCIPLINE_UNSUPPORTED", "The reviewed BST checkpoint supports two-player singles only")
    _need(type(asset.get("fps_num")) is int and type(asset.get("fps_den")) is int and asset["fps_den"] > 0,
          "BST_TIMELINE_INVALID", "Source frame rate is required")
    fps = Fraction(asset["fps_num"], asset["fps_den"])
    _need(10 <= fps <= 120, "BST_TIMELINE_INVALID", "BST input must retain a 10..120 fps source timeline")
    start, end = shot_window(pack.get("shot_boundaries"), fps)
    start_ms, end_ms = float(start * 1000 / fps), float(end * 1000 / fps)
    next_shot = pack["shot_boundaries"].get("next_frame")
    next_shot_ms = float(next_shot * 1000 / fps) if next_shot is not None else end_ms
    _need(next_shot_ms <= asset["duration_ms"], "BST_SHOT_BOUNDARIES_INVALID", "The reviewed next shot lies outside the source")
    _need(end_ms <= asset["duration_ms"] and end_ms - start_ms <= 5000,
          "BST_SHOT_BOUNDARIES_INVALID", "Shot window must fit the source and the five-second bound")
    camera = pack.get("camera_segment")
    _need(isinstance(camera, dict) and _text(camera.get("id")) and _number(camera.get("start_ms"))
          and _number(camera.get("end_ms")) and 0 <= camera["start_ms"] <= start_ms < end_ms <= camera["end_ms"] <= asset["duration_ms"],
          "BST_CAMERA_SEGMENT_MISSING", "One identified continuous camera segment must cover the shot")
    h = validate_calibration(pack.get("calibration"), asset, start_ms, end_ms)
    _need(pack["calibration"].get("camera_segment_id") == camera["id"], "BST_CALIBRATION_INVALID", "Calibration belongs to a different camera segment")
    assignment = pack.get("track_assignment")
    _review(assignment, "Track assignment")
    ids = assignment.get("track_ids")
    _need(isinstance(ids, list) and len(ids) == 2 and all(_text(v) for v in ids) and len(set(ids)) == 2,
          "BST_TRACKS_MISSING", "Two distinct stable track IDs in Top/Bottom order are required")
    provenance = pack.get("provenance")
    _need(isinstance(provenance, dict) and all(isinstance(provenance.get(k), dict)
          and _text(provenance[k].get("model_id")) and isinstance(provenance[k].get("artifact_sha256"), str)
          and re.fullmatch(r"[0-9a-f]{64}", provenance[k]["artifact_sha256"]) for k in ("pose", "shuttle")),
          "BST_PROVENANCE_MISSING", "Pose and shuttle source artifact hashes and model IDs are required")
    frames = pack.get("frames")
    _need(isinstance(frames, list) and len(frames) == end - start, "BST_TIMELINE_INCOMPLETE", "Feature pack must contain every source frame in the author shot window")
    offset = pack.get("source_start_pts")
    _need(type(offset) is int, "BST_TIMELINE_INVALID", "Source stream start PTS is required")
    time_base = _fraction(asset.get("time_base"), "Asset time_base")
    pose, positions, shuttle, timeline, available = [], [], [], [], []
    last_pts = None
    for index, frame in enumerate(frames):
        _need(isinstance(frame, dict) and type(frame.get("source_frame_index")) is int
              and frame["source_frame_index"] == start + index, "BST_TIMELINE_INCOMPLETE", "Source frame indices must be consecutive and cover the shot window")
        pts = frame.get("pts")
        _need(type(pts) is int and (last_pts is None or pts > last_pts) and frame.get("time_base") == asset["time_base"]
              and type(frame.get("source_ms")) is int, "BST_TIMELINE_INVALID", "Frame PTS and source milliseconds must be finite and strictly ordered")
        actual_ms = float((pts - offset) * time_base * 1000)
        _need(abs(frame["source_ms"] - actual_ms) <= 0.501 and abs(actual_ms - float((start + index) * 1000 / fps)) <= 1.1,
              "BST_TIMELINE_INVALID", "Sparse/VFR features or inconsistent source PTS require a separately validated adapter")
        _need(frame.get("width") == asset["width"] and frame.get("height") == asset["height"],
              "BST_COORDINATE_MISMATCH", "Feature dimensions must match the original source")
        last_pts = pts
        players = frame.get("players")
        _need(isinstance(players, list) and len(players) == 2 and all(isinstance(p, dict) for p in players)
              and [p.get("track_id") for p in players] == ids, "BST_TRACKS_MISSING", "Every frame requires the same reviewed two-track assignment")
        frame_pose, frame_positions = [], []
        for player in players:
            box, joints = player.get("box_xyxy"), player.get("keypoints_xyv")
            _need(isinstance(box, list) and len(box) == 4 and all(_number(v) for v in box)
                  and 0 <= box[0] < box[2] <= asset["width"] and 0 <= box[1] < box[3] <= asset["height"],
                  "BST_POSE_MISSING", "Each observed pose requires a nondegenerate source-pixel bbox")
            _need(isinstance(joints, list) and len(joints) == 17 and all(isinstance(p, list) and len(p) == 3
                  and all(_number(v) for v in p) and 0 <= p[0] <= asset["width"] and 0 <= p[1] <= asset["height"] and p[2] > 0
                  and (p[0] != 0 or p[1] != 0) for p in joints),
                  "BST_POSE_MISSING", "Strict BST input needs 17 observed COCO points, without zero/missing substitutes")
            _need(player.get("ankles_status") == "observed", "BST_ANKLES_UNKNOWN", "Both ankles must be observed for court positioning")
            feet = [project(point[:2], h) for point in joints[-2:]]
            position = [sum(point[axis] for point in feet) / 2 for axis in (0, 1)]
            _need(all(-.01 < value < 1.01 for value in position), "BST_PLAYER_OUTSIDE_COURT", "Selected track is outside the author's soft court border")
            frame_pose.append(normalize_pose(joints, box))
            frame_positions.append(position)
        _need(frame_positions[0][1] < frame_positions[1][1], "BST_TRACK_ORDER_CHANGED", "Top/Bottom assignment crossed or became ambiguous")
        ball = frame.get("shuttle")
        _need(isinstance(ball, dict) and ball.get("status") == "observed", "BST_SHUTTLE_MISSING", "Strict BST input requires a real observed shuttle point on every selected source frame")
        _need(ball.get("pts") == pts and type(ball.get("pts")) is int and ball.get("time_base") == asset["time_base"],
              "BST_SHUTTLE_PTS_MISMATCH", "Shuttle and pose must use exactly the same source PTS")
        _need(_number(ball.get("x")) and _number(ball.get("y")) and 0 <= ball["x"] <= asset["width"]
              and 0 <= ball["y"] <= asset["height"] and (ball["x"] != 0 or ball["y"] != 0),
              "BST_SHUTTLE_MISSING", "Shuttle coordinates are invalid or use an origin missing sentinel")
        _need(_number(ball.get("available_at_source_ms")) and frame["source_ms"] <= ball["available_at_source_ms"] <= asset["duration_ms"],
              "BST_AVAILABILITY_MISSING", "Shuttle lookahead availability must be recorded")
        pose.append(frame_pose)
        positions.append(frame_positions)
        shuttle.append([ball["x"] / asset["width"], ball["y"] / asset["height"]])
        available.append(ball["available_at_source_ms"])
        timeline.append({key: frame[key] for key in ("source_frame_index", "pts", "time_base", "source_ms")})
    length = len(frames)
    stride = length // SEQ_LEN + int(length % SEQ_LEN > SEQ_LEN // 2) if length > SEQ_LEN else 1
    indices = list(range(0, length, stride))[:SEQ_LEN]
    valid = len(indices)
    tensors = {"pose": [pose[i] for i in indices], "positions": [positions[i] for i in indices], "shuttle": [shuttle[i] for i in indices]}
    tensors["pose"].extend([[[0.0] * 72 for _ in range(2)] for _ in range(SEQ_LEN - valid)])
    tensors["positions"].extend([[[0.0] * 2 for _ in range(2)] for _ in range(SEQ_LEN - valid)])
    tensors["shuttle"].extend([[0.0] * 2 for _ in range(SEQ_LEN - valid)])
    return {**tensors, "valid_length": valid, "source_frame_count": length, "selection_indices": indices,
            "source_timeline": timeline, "start_frame": start, "end_frame": end, "start_ms": start_ms, "end_ms": end_ms,
            "available_at_source_ms": max(end_ms, next_shot_ms, *available), "review_status": {name: pack[name]["status"] for name in ("calibration", "track_assignment", "shot_boundaries")}}


def verify_source_timeline(path, asset, pack, prepared):
    """Decode real source PTS to reject sparse features relabelled as dense frames."""
    try:
        import av
    except (ImportError, OSError) as exc:
        raise ModelBlocked("DEPENDENCY_NOT_INSTALLED", "BST source verification requires working PyAV") from exc
    expected = prepared["source_timeline"]
    found, decoded = [], 0
    started = time.monotonic()
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        _need(str(stream.time_base) == asset["time_base"] and (stream.start_time or 0) == pack["source_start_pts"],
              "BST_TIMELINE_INVALID", "Decoded stream time base/start PTS differs from feature metadata")
        container.seek(expected[0]["pts"], stream=stream, backward=True)
        for frame in container.decode(stream):
            decoded += 1
            _need(decoded <= 10000 and time.monotonic() - started <= 60,
                  "BST_DECODE_BOUND_EXCEEDED", "BST source timeline verification exceeded its work bound")
            _need(frame.pts is not None, "BST_TIMELINE_INVALID", "Decoded frame has no source PTS")
            source_ms = float((frame.pts - pack["source_start_pts"]) * stream.time_base * 1000)
            if source_ms >= prepared["end_ms"] - .01:
                break
            if source_ms < prepared["start_ms"] - .01:
                continue
            _need(frame.width == asset["width"] and frame.height == asset["height"], "BST_COORDINATE_MISMATCH", "Decoded source size differs from pose coordinates")
            found.append(frame.pts)
            _need(len(found) <= MAX_FRAMES, "BST_DECODE_BOUND_EXCEEDED", "Too many source frames")
    _need(found == [item["pts"] for item in expected], "BST_TIMELINE_INCOMPLETE", "Feature PTS do not cover every actual decoded source frame")
    return {"decoded_frames_including_seek_preroll": decoded, "verified_window_frames": len(found)}


class Runtime:
    def __init__(self, root, device):
        self.manifest, paths, checkpoint = read_manifest(root)
        dependencies = {}
        for name in ("torch", "positional_encodings.torch_encodings", "torchinfo", "torch.utils.flop_counter"):
            try:
                dependencies[name] = importlib.import_module(name)
            except (ImportError, OSError, RuntimeError) as exc:
                raise ModelBlocked("DEPENDENCY_NOT_INSTALLED", "BST requires working dependency: " + name) from exc
        self.torch, self.device = dependencies["torch"], device
        _need(device != "cuda" or self.torch.cuda.is_available(), "CUDA_UNAVAILABLE", "BST CUDA configuration requires an available CUDA device")
        if device == "cuda":
            self.torch.cuda.reset_peak_memory_stats()
        previous = {name: sys.modules.get(name) for name in ("model", "model.tempose")}
        try:
            package = types.ModuleType("model")
            package.__path__ = []
            sys.modules["model"] = package
            tempose = types.ModuleType("model.tempose")
            tempose.__file__ = str(paths["tempose.py"])
            _exec_reviewed_source(paths["tempose.py"], "tempose.py", tempose.__dict__)
            sys.modules["model.tempose"] = tempose
            module = types.ModuleType("btv_reviewed_bst")
            module.__file__ = str(paths["bst.py"])
            _exec_reviewed_source(paths["bst.py"], "bst.py", module.__dict__)
            self.model = module.BST_CG_AP(in_dim=72, seq_len=100, n_class=25, depth_tem=2, depth_inter=1)
        finally:
            for name, value in previous.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value
        try:
            state = self.torch.load(checkpoint, map_location="cpu", weights_only=True)
            self.model.load_state_dict(state, strict=True)
        except Exception as exc:
            raise ModelBlocked("BST_CHECKPOINT_UNSUPPORTED", "BST checkpoint failed restricted loading or strict architecture matching") from exc
        self.model.to(device).eval()
        self.parameter_count = sum(p.numel() for p in self.model.parameters())
        self.sync()

    def sync(self):
        if self.device == "cuda":
            self.torch.cuda.synchronize()

    def predict(self, features):
        torch = self.torch
        tensors = [torch.tensor([features[key]], dtype=torch.float32, device=self.device) for key in ("pose", "shuttle", "positions")]
        tensors.append(torch.tensor([features["valid_length"]], dtype=torch.long, device=self.device))
        self.sync()
        with torch.inference_mode():
            logits = self.model(*tensors)
        self.sync()
        _need(tuple(logits.shape) == (1, 25) and bool(torch.isfinite(logits).all()), "BST_OUTPUT_INVALID", "BST returned invalid logits")
        return logits[0].detach().cpu().tolist()

    def details(self):
        return {"torch": self.torch.__version__, "device": self.device, "parameter_count": self.parameter_count,
                "peak_allocated_bytes": self.torch.cuda.max_memory_allocated() if self.device == "cuda" else None,
                "peak_reserved_bytes": self.torch.cuda.max_memory_reserved() if self.device == "cuda" else None}


def execute(request, root, output_path, progress):
    validate_request(request, root)
    p = request["parameters"]
    if request["operation"] not in {"analyze", "movement_classification", "stroke_classification"} or p.get("model_id") != MODEL_ID or len(request["assets"]) != 1:
        raise InvalidRequest("BST requires analyze/movement_classification/stroke_classification and exactly one source Asset")
    if set(p) - {"model_id", "model_version", "device", "features"} or p.get("device", "cpu") not in {"cpu", "cuda"}:
        raise InvalidRequest("Unsupported BST parameter or device")
    if "model_version" in p and p["model_version"] != "0.1.0":
        raise InvalidRequest("BST model_version must be 0.1.0 when supplied")
    _need(isinstance(p.get("features"), dict), "BST_INPUT_MISSING", "BST requires a hashed real feature pack: pose, shuttle, calibration, tracks and shot boundaries")
    output = resolve_relative(root, request["output_dir"], owner="models")
    if output != Path(output_path).resolve():
        raise InvalidRequest("BST output does not match validated output_dir")
    targets = [output / "bst-prediction.json", output / "bst-report.json"]
    if any(target.exists() or target.is_symlink() for target in targets):
        raise FileExistsError("BST attempt output already exists")
    asset = request["assets"][0]
    started = time.perf_counter()
    feature_path = verified_file(root, p["features"], "models/", 12_000_000)
    pack = _json(feature_path, 12_000_000)
    features = prepare_features(pack, asset)
    prep_seconds = time.perf_counter() - started
    hash_start = time.perf_counter()
    source = verified_file(root, asset)
    hash_seconds = time.perf_counter() - hash_start
    decode_start = time.perf_counter()
    timeline_check = verify_source_timeline(source, asset, pack, features)
    decode_seconds = time.perf_counter() - decode_start
    from .tracknet_reuse import usage_scope
    scope = usage_scope(asset, root)
    _need(pack.get("usage_scope") in {"general", "training_only"}, "BST_PROVENANCE_MISSING", "Feature pack usage_scope is required")
    if pack["usage_scope"] == "training_only":
        scope = "training_only"
    with reserve(root, 8_000_000):
        progress("load_model", message="Load reviewed BST code and checkpoint after source feature guards")
        load_start = time.perf_counter()
        runtime = Runtime(root, p.get("device", "cpu"))
        load_seconds = time.perf_counter() - load_start
        infer_start = time.perf_counter()
        logits = runtime.predict(features)
        infer_seconds = time.perf_counter() - infer_start
        _need(isinstance(logits, list) and len(logits) == 25 and all(_number(v) for v in logits), "BST_OUTPUT_INVALID", "BST output must contain 25 finite logits")
        peak = max(logits)
        exp = [math.exp(value - peak) for value in logits]
        probabilities = [value / sum(exp) for value in exp]
        best = max(range(25), key=logits.__getitem__)
        producer = {"module": "models", "model_id": MODEL_ID, "version": "0.1.0", "source_commit": COMMIT,
                    "job_id": request["job_id"], "attempt_id": request["attempt_id"], "usage_scope": scope}
        common = {"schema_version": "1.0", "asset_id": asset["asset_id"], "source_sha256": asset["sha256"], "usage_scope": scope,
                  "producer": producer, "source_rights": asset["rights"], "features": p["features"],
                  "checkpoint": runtime.manifest["checkpoint"], "code": runtime.manifest["code"],
                  "start_ms": features["start_ms"], "end_ms": features["end_ms"], "available_at_source_ms": features["available_at_source_ms"],
                  "mode": "offline_author_window", "causal": False, "status": "experimental",
                  "accuracy": None, "recall": None, "fine_labels": "unknown", "review_status": features["review_status"],
                  "warning": "Coarse model prediction; no confirmed technique, identity, tactic, precision or recall"}
        prediction = {**common, "format": "bst-coarse-stroke-candidate-v1", "labels": list(LABELS), "logits": logits,
                      "softmax_uncalibrated": probabilities, "predicted_index": best, "predicted_label": LABELS[best],
                      "epistemic_status": "unreviewed", "valid_length": features["valid_length"],
                      "source_frame_count": features["source_frame_count"], "source_timeline": features["source_timeline"],
                      "selection_indices": features["selection_indices"], "calibration": pack["calibration"],
                      "track_assignment": pack["track_assignment"], "shot_boundaries": pack["shot_boundaries"], "provenance": pack["provenance"],
                      "selection": pack.get("selection", {"method": "provided_author_shot_window", "coverage_claim": "one window only"})}
        report = {**common, "timeline_verification": timeline_check, "runtime": runtime.details(),
                  "timings_seconds": {"feature_validation_preprocess": prep_seconds, "source_hash_verification": hash_seconds,
                                      "source_decode_verification": decode_seconds,
                                      "model_load_cold": load_seconds, "single_forward_including_tensor_transfer": infer_seconds},
                  "steady_state_rtf": None, "warmup": "not_run", "synthetic_model_inputs": False,
                  "acceptance": {"R-07b": "requires source review", "R-07c": "not_pass_causal_future_window", "S2-04": "unknown_fine_labels"}}
        atomic_write_json(targets[0], prediction)
        atomic_write_json(targets[1], report)
        progress("analyze", current=1, total=1, unit="window", message="Produced unvalidated offline coarse-stroke candidate")
        return {"artifacts": [make_artifact(root, target, kind, producer) for target, kind in zip(targets, ("coarse_stroke_prediction", "evaluation_report"))], "events": []}
