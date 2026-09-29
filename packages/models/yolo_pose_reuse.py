"""Bounded offline YOLO11n-pose / ByteTrack comparison; no ML work on import."""
from fractions import Fraction
import hashlib
import importlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import zipfile

from .protocol import InvalidRequest, ModelBlocked, atomic_write_json, make_artifact, resolve_relative, validate_request
from .storage import reserve
from .tracknet_reuse import usage_scope

MODEL_ID, MODEL_VERSION = "yolo11n-pose-bytetrack", "0.1.0"
PACKAGE_VERSION = "8.3.203"
SOURCE_COMMIT = "6450d5c38fb4ef069e1c450930bf6bd9fc3fc59c"
WHEEL_SHA256 = "7103994cfb14f8779fa0a6b7e7908708137309645a3723dbe2ceb73ea7afc63c"
WHEEL_BYTES = 1_072_183
WEIGHT_BYTES = 6_255_593
WEIGHT_SHA256 = "869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0"
WEIGHT_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.pt"
MAX_FRAMES, MAX_DETECTIONS, RESERVE_BYTES = 100, 30, 100_000_000
TRACKER_CONFIG = {"track_high_thresh": .25, "track_low_thresh": .1, "new_track_thresh": .25,
                  "track_buffer": 30, "match_thresh": .8, "fuse_score": True}


def need(condition, code, message):
    if not condition:
        raise ModelBlocked(code, message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().casefold() not in {"unknown", "none", "null"}


def options(request):
    p = request["parameters"]
    if request["operation"] not in {"analyze", "pose", "tracking"} or p.get("model_id") != MODEL_ID or len(request["assets"]) != 1:
        raise InvalidRequest("YOLO pose requires analyze/pose/tracking and exactly one Asset")
    if set(p) - {"model_id", "model_version", "start_ms", "end_ms", "device", "imgsz", "camera_segment"}:
        raise InvalidRequest("Unsupported YOLO pose parameters")
    if p.get("model_version", MODEL_VERSION) != MODEL_VERSION:
        raise InvalidRequest("YOLO pose model_version must be 0.1.0")
    asset = request["assets"][0]
    start, end = p.get("start_ms", 0), p.get("end_ms", min(3000, asset["duration_ms"]))
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= asset["duration_ms"] or end - start > 3000:
        raise InvalidRequest("YOLO pose requires an in-range window of at most 3000 ms")
    if p.get("device", "cuda") not in {"cuda", "cpu"} or type(p.get("imgsz", 640)) is not int or p.get("imgsz", 640) != 640:
        raise InvalidRequest("YOLO pose supports cpu/cuda and fixed imgsz=640")
    need(type(asset.get("fps_num")) is int and type(asset.get("fps_den")) is int and asset["fps_num"] > 0 and asset["fps_den"] > 0,
         "YOLO_TIMELINE_INVALID", "Source frame rate is required")
    fps = Fraction(asset["fps_num"], asset["fps_den"])
    need(1 <= fps <= 120 and math.ceil((end-start)*fps/1000) <= MAX_FRAMES,
         "YOLO_FRAME_BOUND", "Shorten the window to at most 100 continuous source frames")
    camera = p.get("camera_segment")
    need(isinstance(camera, dict) and all(text(camera.get(k)) for k in ("id", "method", "evidence"))
         and camera.get("status") in {"agent_reviewed", "human_confirmed"}
         and finite(camera.get("start_ms")) and finite(camera.get("end_ms"))
         and 0 <= camera["start_ms"] <= start < end <= camera["end_ms"] <= asset["duration_ms"],
         "YOLO_CAMERA_REVIEW_MISSING", "An explicitly reviewed continuous camera segment must cover the window")
    return {"start_ms": start, "end_ms": end, "device": p.get("device", "cuda"), "imgsz": 640, "camera_segment": camera}


def verify_file(root, entry, prefix=None, expected=None, keep_bytes=False):
    need(isinstance(entry, dict) and type(entry.get("size_bytes")) is int and entry["size_bytes"] > 0
         and isinstance(entry.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
         "YOLO_MANIFEST_INVALID", "File metadata requires exact bytes and SHA256")
    if expected:
        need((entry["size_bytes"], entry["sha256"]) == expected, "YOLO_PIN_MISMATCH", "File differs from fixed official artifact pins")
    path = resolve_relative(root, entry.get("relative_path"), owner="models" if prefix else None)
    if prefix:
        need(entry["relative_path"].startswith(prefix) and path.relative_to(Path(root).resolve()).as_posix().startswith(prefix),
             "YOLO_MANIFEST_INVALID", "File is outside its designated models directory")
    need(path.is_file(), "YOLO_NOT_INSTALLED", "A required local source, wheel or checkpoint is missing")
    digest, chunks, consumed = hashlib.sha256(), [], 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        need(before.st_size == entry["size_bytes"], "YOLO_HASH_MISMATCH", "File size mismatch")
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            consumed += len(chunk)
            need(consumed <= entry["size_bytes"], "YOLO_HASH_MISMATCH", "File grew beyond its declared byte bound")
            digest.update(chunk)
            if keep_bytes:
                chunks.append(chunk)
        after = os.fstat(stream.fileno())
    need((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and digest.hexdigest() == entry["sha256"],
         "YOLO_HASH_MISMATCH", "File changed or its SHA256 mismatches")
    return (path, b"".join(chunks)) if keep_bytes else path


def read_manifest(root):
    path = resolve_relative(root, os.environ.get("BTV_YOLO_POSE_MANIFEST", "models/weights/yolo11n-pose/reuse-manifest.json"), owner="models")
    need(path.is_file(), "YOLO_NOT_INSTALLED", "YOLO pose reuse manifest is not installed")
    need(path.stat().st_size <= 64000, "YOLO_MANIFEST_INVALID", "YOLO manifest exceeds its size bound")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        need(manifest["schema_version"] == "1.0" and manifest["license"] == "AGPL-3.0"
             and manifest["model_id"] == MODEL_ID and manifest["package_version"] == PACKAGE_VERSION,
             "YOLO_MANIFEST_INVALID", "Manifest does not identify the reviewed package and license")
        _, wheel = verify_file(root, manifest["package"], "models/upstream/", (WHEEL_BYTES, WHEEL_SHA256), True)
        _, checkpoint = verify_file(root, manifest["checkpoint"], "models/weights/", (WEIGHT_BYTES, WEIGHT_SHA256), True)
        need(manifest["checkpoint"]["source_url"] == WEIGHT_URL, "YOLO_MANIFEST_INVALID", "Checkpoint source is not the reviewed official release")
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise ModelBlocked("YOLO_MANIFEST_INVALID", "Invalid YOLO pose manifest") from exc
    return manifest, wheel, checkpoint


def verify_installed_package(wheel):
    try:
        distribution = importlib.metadata.distribution("ultralytics")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ModelBlocked("DEPENDENCY_NOT_INSTALLED", "ultralytics 8.3.203 is not installed") from exc
    need(distribution.version == PACKAGE_VERSION, "YOLO_PACKAGE_VERSION", "Installed Ultralytics version must match the fixed wheel")
    checked = 0
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        for name in archive.namelist():
            if name.startswith("ultralytics/") and name.endswith((".py", ".yaml")):
                expected = archive.read(name)
                local = Path(distribution.locate_file(name))
                need(local.is_file() and local.read_bytes() == expected, "YOLO_PACKAGE_CHANGED", "Installed Ultralytics source/config differs from reviewed wheel")
                checked += 1
    need(checked > 100, "YOLO_PACKAGE_CHANGED", "Reviewed wheel has an incomplete source/config inventory")
    return checked


class IndexedDetections:
    """Carry raw indices through ByteTrack's two confidence partitions."""
    def __init__(self, boxes, indices=None):
        self.boxes = boxes
        self.source_indices = list(range(len(boxes))) if indices is None else indices

    def __len__(self):
        return len(self.boxes)

    def __getattr__(self, name):
        return getattr(self.boxes, name)

    def __getitem__(self, selection):
        values = selection.tolist() if hasattr(selection, "tolist") else selection
        if isinstance(values, slice):
            indices = self.source_indices[values]
        elif isinstance(values, list) and all(type(v) is bool for v in values):
            indices = [index for index, keep in zip(self.source_indices, values) if keep]
        else:
            raise ModelBlocked("YOLO_TRACK_OUTPUT_INVALID", "Unexpected ByteTrack detection index operation")
        return IndexedDetections(self.boxes[selection], indices)


def indexed_tracker_class(base):
    class IndexedBYTETracker(base):
        def init_track(self, results, img=None):
            tracks = super().init_track(results, img)
            need(len(tracks) == len(results.source_indices), "YOLO_TRACK_OUTPUT_INVALID", "ByteTrack changed its detection indexing contract")
            for track, index in zip(tracks, results.source_indices):
                track.idx = index
            return tracks
    return IndexedBYTETracker


def serialize_detections(boxes, scores, keypoints, tracks, segment_id):
    need(isinstance(boxes, list) and len(boxes) <= MAX_DETECTIONS and len(scores) == len(boxes) == len(keypoints),
         "YOLO_OUTPUT_INVALID", "YOLO detection array lengths disagree")
    links, used = {}, set()
    for row in tracks:
        need(isinstance(row, list) and len(row) == 8 and all(finite(v) for v in row), "YOLO_TRACK_OUTPUT_INVALID", "Invalid ByteTrack output row")
        identity, index = row[4], row[7]
        need(identity > 0 and identity == int(identity) and index == int(index) and 0 <= index < len(boxes)
             and int(index) not in links and identity not in used, "YOLO_TRACK_OUTPUT_INVALID", "Ambiguous ByteTrack-to-detection association")
        links[int(index)] = int(identity)
        used.add(identity)
    detections = []
    for index, (box, score, points) in enumerate(zip(boxes, scores, keypoints)):
        need(len(box) == 4 and all(finite(v) for v in box) and box[0] <= box[2] and box[1] <= box[3]
             and finite(score) and 0 <= score <= 1 and len(points) == 17
             and all(len(p) == 3 and all(finite(v) for v in p) and 0 <= p[2] <= 1 for p in points),
             "YOLO_OUTPUT_INVALID", "Invalid COCO17 pose or detector score")
        track_id = links.get(index)
        detections.append({"detection_id": index, "box_xyxy": box, "score": score,
                           "keypoints_xyv": points, "keypoint_scores": [p[2] for p in points],
                           "keypoint_status": ["model_visible" if p[2] >= .5 and (p[0] != 0 or p[1] != 0) else "unknown" for p in points],
                           "track_id": None if track_id is None else f"{segment_id}:anonymous-{track_id}",
                           "tracker_numeric_id": track_id, "identity_status": "anonymous",
                           "track_status": "unassigned" if track_id is None else "model_associated",
                           "missing_track_reason": "not_activated_or_unmatched" if track_id is None else None})
    return detections


class Runtime:
    def __init__(self, root, config, fps):
        self.manifest, wheel, checkpoint = read_manifest(root)
        self.verified_package_files = verify_installed_package(wheel)
        for folder in ("models/cache/yolo/config", "models/cache/yolo/tmp", "models/cache/yolo/matplotlib"):
            resolve_relative(root, folder, owner="models").mkdir(parents=True, exist_ok=True)
        os.environ.update(YOLO_AUTOINSTALL="false", YOLO_OFFLINE="true", YOLO_VERBOSE="false",
                          YOLO_CONFIG_DIR=str(resolve_relative(root, "models/cache/yolo/config", owner="models")),
                          TMPDIR=str(resolve_relative(root, "models/cache/yolo/tmp", owner="models")),
                          MPLCONFIGDIR=str(resolve_relative(root, "models/cache/yolo/matplotlib", owner="models")))
        os.environ["TEMP"] = os.environ["TMP"] = os.environ["TMPDIR"]
        tempfile.tempdir = os.environ["TMPDIR"]
        dependencies = {}
        for name in ("torch", "torchvision", "numpy", "cv2", "av", "matplotlib", "yaml", "requests", "scipy", "psutil", "polars", "thop", "lap"):
            try:
                dependencies[name] = importlib.import_module(name)
            except (ImportError, OSError, RuntimeError) as exc:
                raise ModelBlocked("DEPENDENCY_NOT_INSTALLED", "YOLO pose requires working dependency: " + name) from exc
        self.torch, self.device = dependencies["torch"], config["device"]
        need(self.device != "cuda" or self.torch.cuda.is_available(), "CUDA_UNAVAILABLE", "YOLO CUDA request requires an available CUDA device")
        if self.device == "cuda":
            self.torch.cuda.reset_peak_memory_stats()
        from ultralytics.models.yolo.pose.predict import PosePredictor
        from ultralytics.trackers.byte_tracker import BYTETracker
        # The official release is a pickled model. Only the fixed, locally verified
        # byte buffer is deserialized; requests/manifests cannot authorize a pickle.
        state = self.torch.load(io.BytesIO(checkpoint), map_location="cpu", weights_only=False)
        model = state.get("ema") or state.get("model")
        need(isinstance(model, self.torch.nn.Module) and list(getattr(model.model[-1], "kpt_shape", [])) == [17, 3]
             and getattr(model, "names", None) == {0: "person"}, "YOLO_CHECKPOINT_UNSUPPORTED", "Expected official COCO17 person-only pose model")
        model.kpt_shape = model.model[-1].kpt_shape
        self.parameter_count = sum(p.numel() for p in model.parameters())
        self.predictor = PosePredictor(overrides={"task": "pose", "mode": "predict", "device": "0" if self.device == "cuda" else "cpu",
                                                "imgsz": 640, "conf": .1, "iou": .7, "max_det": MAX_DETECTIONS,
                                                "save": False, "save_txt": False, "show": False, "verbose": False,
                                                "project": str(resolve_relative(root, "models/cache/yolo/runs", owner="models"))})
        self.predictor.setup_model(model=model.float().eval(), verbose=False)
        self.predictor.done_warmup = True  # First actual frame is the cold forward; no fabricated input.
        self.tracker = indexed_tracker_class(BYTETracker)(SimpleNamespace(**TRACKER_CONFIG), frame_rate=float(fps))
        self.segment_id = config["camera_segment"]["id"]
        self.sync()

    def sync(self):
        if self.device == "cuda":
            self.torch.cuda.synchronize()

    def predict(self, bgr):
        self.sync()
        started = time.perf_counter()
        result = self.predictor(source=bgr, stream=False)[0]
        self.sync()
        detector_seconds = time.perf_counter() - started
        started = time.perf_counter()
        boxes = result.boxes.cpu().numpy()
        points = result.keypoints.data.cpu().tolist()
        raw_boxes, raw_scores = boxes.xyxy.tolist(), boxes.conf.tolist()
        self.sync()
        transfer_seconds = time.perf_counter() - started
        started = time.perf_counter()
        tracks = self.tracker.update(IndexedDetections(boxes), bgr).tolist()
        tracking_seconds = time.perf_counter() - started
        started = time.perf_counter()
        detections = serialize_detections(raw_boxes, raw_scores, points, tracks, self.segment_id)
        serialization_seconds = time.perf_counter() - started
        return detections, {"pose_wall_seconds": detector_seconds, "tracking_seconds": tracking_seconds,
                            "transfer_seconds": transfer_seconds, "serialization_seconds": serialization_seconds,
                            "upstream_pose_milliseconds": dict(result.speed)}

    def details(self):
        return {"ultralytics": PACKAGE_VERSION, "torch": self.torch.__version__, "device": self.device,
                "parameter_count_before_fusion": self.parameter_count, "verified_package_files": self.verified_package_files,
                "peak_allocated_bytes": self.torch.cuda.max_memory_allocated() if self.device == "cuda" else None,
                "peak_reserved_bytes": self.torch.cuda.max_memory_reserved() if self.device == "cuda" else None}


def decode_frames(path, asset, config):
    try:
        import av
    except ImportError as exc:
        raise ModelBlocked("DEPENDENCY_NOT_INSTALLED", "YOLO pose decoding requires PyAV") from exc
    fps = Fraction(asset["fps_num"], asset["fps_den"])
    previous, count, decoded = None, 0, 0
    started = time.perf_counter()
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        time_base, offset = stream.time_base, stream.start_time or 0
        need(str(time_base) == asset["time_base"], "YOLO_TIMELINE_INVALID", "Decoded time base differs from Asset")
        container.seek(int(Fraction(config["start_ms"], 1000)/time_base)+offset, stream=stream, backward=True)
        for frame in container.decode(stream):
            decoded += 1
            need(decoded <= 3000 and time.perf_counter()-started <= 120, "YOLO_DECODE_BOUND", "Source decode work bound exceeded")
            need(frame.pts is not None and (previous is None or frame.pts > previous), "YOLO_TIMELINE_INVALID", "Source PTS missing or not strictly ordered")
            previous = frame.pts
            milliseconds = (frame.pts-offset)*time_base*1000
            if milliseconds >= config["end_ms"]:
                break
            if milliseconds < config["start_ms"]:
                continue
            count += 1
            need(count <= MAX_FRAMES, "YOLO_FRAME_BOUND", "Decoded window exceeds 100 frames; no frames were silently dropped")
            need((frame.width, frame.height) == (asset["width"], asset["height"]) and 0 < frame.width*frame.height <= 3840*2160,
                 "YOLO_SOURCE_DIMENSIONS", "Source dimensions changed or exceed 4K")
            index = round(milliseconds*fps/1000)
            need(abs(milliseconds-index*1000/fps) <= Fraction(11, 10), "YOLO_TIMELINE_INVALID", "VFR frame-index mapping requires a separate adapter")
            convert = time.perf_counter()
            array = frame.to_ndarray(format="bgr24")
            yield {"pts": frame.pts, "time_base": str(time_base), "source_start_pts": offset, "stream_start_pts": offset,
                   "source_ms": round(milliseconds), "source_frame_index": index,
                   "width": frame.width, "height": frame.height,
                   "pixel_conversion_seconds": time.perf_counter()-convert}, array
    need(count > 0, "YOLO_EMPTY_WINDOW", "No decoded source frame in requested interval")


def execute(request, root, output_path, progress):
    execute_started = time.perf_counter()
    validate_request(request, root)
    config = options(request)
    asset = request["assets"][0]
    output = resolve_relative(root, request["output_dir"], owner="models")
    if output != Path(output_path).resolve():
        raise InvalidRequest("YOLO output differs from validated output_dir")
    targets = [output/"features.json", output/"report.json"]
    if any(path.exists() or path.is_symlink() for path in targets):
        raise FileExistsError("YOLO attempt output already exists")
    scope = usage_scope(asset, root)
    fps = Fraction(asset["fps_num"], asset["fps_den"])
    expected_indices = list(range(math.ceil(config["start_ms"]*fps/1000), math.ceil(config["end_ms"]*fps/1000)))
    with reserve(root, RESERVE_BYTES):
        started = time.perf_counter()
        source = verify_file(root, asset)
        hash_seconds = time.perf_counter()-started
        progress("load_model", message="Load pinned local YOLO11n pose and a new anonymous ByteTrack instance")
        started = time.perf_counter()
        runtime = Runtime(root, config, fps)
        load_seconds = time.perf_counter()-started
        frames, seen = [], set()
        source_decode_seconds, pose_seconds, tracker_seconds = 0., 0., 0.
        transfer_seconds, serialization_seconds = 0., 0.
        iterator = iter(decode_frames(source, asset, config))
        while True:
            started = time.perf_counter()
            try:
                record, bgr = next(iterator)
            except StopIteration:
                break
            source_decode_seconds += time.perf_counter()-started
            need(len(frames) < len(expected_indices) and record["source_frame_index"] == expected_indices[len(frames)],
                 "YOLO_TIMELINE_GAP", "Source frames do not exactly cover the requested CFR interval, including its first frame")
            detections, timings = runtime.predict(bgr)
            ids = {d["track_id"] for d in detections if d["track_id"] is not None}
            missing = sorted(seen-ids)
            seen |= ids
            pose_seconds += timings["pose_wall_seconds"]
            tracker_seconds += timings["tracking_seconds"]
            transfer_seconds += timings["transfer_seconds"]
            serialization_seconds += timings["serialization_seconds"]
            frames.append({**record, "detections": detections, "timings": timings,
                           "missing_previously_seen_track_ids": missing,
                           "status": "model_observations" if detections else "unknown",
                           "missing_reason": None if detections else "no_person_detection",
                           "possible_detector_cap_hit": len(detections) == MAX_DETECTIONS})
            progress("pose_tracking", current=len(frames), unit="source_frame", message="Preserve source PTS, raw poses and anonymous model associations")
        need(0 < len(frames) <= MAX_FRAMES, "YOLO_EMPTY_WINDOW", "No usable decoded timeline was produced")
        need(len(frames) == len(expected_indices), "YOLO_TIMELINE_GAP", "Source frames do not reach the requested CFR interval's final frame")
        producer = {"module": "models", "model_id": MODEL_ID, "version": MODEL_VERSION,
                    "job_id": request["job_id"], "attempt_id": request["attempt_id"], "usage_scope": scope}
        common = {"schema_version": "1.0", "asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
                  "source_asset": asset, "source_rights": asset["rights"], "usage_scope": scope, "producer": producer,
                  "start_ms": config["start_ms"], "end_ms": config["end_ms"], "camera_segment": config["camera_segment"],
                  "checkpoint": runtime.manifest["checkpoint"], "package": runtime.manifest["package"],
                  "status": "experimental", "accuracy": None, "recall": None,
                  "identity_status": "anonymous", "reid": False, "fine_labels": "unknown",
                  "review_status": "unreviewed_model_output", "license": "AGPL-3.0"}
        features = {**common, "format": "yolo-coco17-bytetrack-source-v1", "frames": frames,
                    "source_start_pts": frames[0]["source_start_pts"], "frame_count": len(frames),
                    "missing_policy": "retain_missing_without_interpolation_or_filling", "events": []}
        report = {**common, "runtime": runtime.details(), "tracker": {"name": "ByteTrack", "config": TRACKER_CONFIG,
                  "reset_scope": "one_request_one_reviewed_camera_segment", "association_index_adapter": "preserve_raw_indices_across_confidence_partitions"},
                  "timings_seconds": {"source_hash": hash_seconds, "model_load_cold": load_seconds,
                                      "source_decode_and_conversion": source_decode_seconds, "pose_total": pose_seconds, "tracking_total": tracker_seconds,
                                      "d2h_and_list_transfer_total": transfer_seconds, "detection_serialization_total": serialization_seconds},
                  "timeline_verification": {"mode": "exact_cfr_interval", "expected_first_frame": expected_indices[0],
                                            "expected_last_frame": expected_indices[-1], "expected_frame_count": len(expected_indices)},
                  "source_frame_count": len(frames), "frames_without_detections": sum(not f["detections"] for f in frames),
                  "frames_with_missing_previously_seen_tracks": sum(bool(f["missing_previously_seen_track_ids"]) for f in frames),
                  "warmup": "none_first_real_frame_is_cold", "steady_state_rtf": None,
                  "limitations": ["No human identity, ReID, pose accuracy or stable association guarantee", "Camera continuity is declared review, not automatic cut detection", "No full-match or hour-runtime extrapolation"]}
        started = time.perf_counter()
        atomic_write_json(targets[0], features)
        report["timings_seconds"]["features_json_write"] = time.perf_counter()-started
        elapsed = time.perf_counter()-execute_started
        accounted = sum(report["timings_seconds"].values())
        report["timings_seconds"].update(execute_elapsed_seconds=elapsed, unattributed_seconds=elapsed-accounted)
        report["timing_measurement_boundary"] = "execute entry through features JSON write; excludes final report write, artifact hashing and worker result IPC"
        atomic_write_json(targets[1], report)
        return {"artifacts": [make_artifact(root, path, kind, producer) for path, kind in zip(targets, ("pose_features", "evaluation_report"))], "events": []}
