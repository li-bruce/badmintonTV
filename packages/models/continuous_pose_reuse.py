"""Bounded continuous COCO17 preannotations for diagnostic downstream reuse.

No framework is imported before execute. Every source frame in the requested
window is processed once; no interpolation, tracking or identity assignment.
"""
from contextlib import closing
from fractions import Fraction
import hashlib
import importlib.metadata
import math
import os
from pathlib import Path
import time

from .protocol import InvalidRequest, ModelBlocked, atomic_write_json, make_artifact, resolve_relative
from .storage import reserve
from .vl_embedding_reuse import safe_failure, usage_scope

MODEL_ID = "torchvision-continuous-pose"
MAX_FRAMES = 100
MAX_WINDOW_MS = 3000
MAX_SELECTED_PIXELS = 100_000_000
MAX_FRAME_PIXELS = 3840 * 2160


def validate_parameters(request):
    p = request["parameters"]
    if request["operation"] not in {"pose", "analyze"} or p.get("model_id") != MODEL_ID:
        raise InvalidRequest("Continuous pose requires pose/analyze and its registered model_id")
    if set(p) - {"model_id", "model_version", "start_ms", "end_ms", "score_threshold"} or p.get("model_version", "0.1.0") != "0.1.0":
        raise InvalidRequest("Unsupported continuous pose parameter or model version")
    if len(request["assets"]) != 1:
        raise InvalidRequest("Continuous pose accepts exactly one Asset")
    asset = request["assets"][0]
    start, end = p.get("start_ms", 0), p.get("end_ms", min(asset["duration_ms"], MAX_WINDOW_MS))
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= asset["duration_ms"] or end-start > MAX_WINDOW_MS:
        raise InvalidRequest("Continuous pose requires an in-range window of at most 3000 integer milliseconds")
    threshold = p.get("score_threshold", 0.7)
    if type(threshold) not in (float, int) or not math.isfinite(threshold) or not 0.1 <= threshold <= 0.99:
        raise InvalidRequest("score_threshold must be finite within 0.1..0.99")
    return {**p, "start_ms": start, "end_ms": end, "score_threshold": threshold}


def iter_source_frames(path, parameters, timings):
    """Yield original PTS records and RGB PIL images; CPU decode only."""
    import av
    previous, dimensions, selected, selected_pixels, decoded = None, None, 0, 0, 0
    starting_decode = timings["decode_seconds"]
    began = time.perf_counter()
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise InvalidRequest("Source has no video stream")
        stream = container.streams.video[0]
        offset = stream.start_time or 0
        origin = offset * stream.time_base
        start = Fraction(parameters["start_ms"], 1000)
        end = Fraction(parameters["end_ms"], 1000)
        container.seek(int((start + origin) / stream.time_base), stream=stream, backward=True)
        timings["decode_seconds"] += time.perf_counter() - began
        iterator = iter(container.decode(stream))
        while True:
            began = time.perf_counter()
            try:
                frame = next(iterator)
            except StopIteration:
                timings["decode_seconds"] += time.perf_counter() - began
                break
            timings["decode_seconds"] += time.perf_counter() - began
            decoded += 1
            if decoded > 10000 or timings["decode_seconds"] - starting_decode > 60:
                raise InvalidRequest("Continuous decode work bound exceeded")
            if frame.pts is None or frame.time_base is None:
                raise InvalidRequest("Every continuous pose frame requires source PTS/time_base")
            stamp = frame.pts * frame.time_base - origin
            if stamp < 0 or (previous is not None and stamp <= previous):
                raise InvalidRequest("Source PTS must be strictly increasing; explicit repair required")
            previous = stamp
            if stamp >= end:
                break
            if stamp < start:
                continue
            if frame.width <= 0 or frame.height <= 0 or frame.width * frame.height > MAX_FRAME_PIXELS:
                raise InvalidRequest("Continuous pose frame exceeds the source pixel bound")
            if dimensions is not None and dimensions != (frame.width, frame.height):
                raise InvalidRequest("Continuous pose window changes image dimensions")
            dimensions = (frame.width, frame.height)
            selected += 1
            selected_pixels += frame.width * frame.height
            if selected > MAX_FRAMES or selected_pixels > MAX_SELECTED_PIXELS:
                raise InvalidRequest("Continuous pose exceeds 100 frames or 100 million selected source pixels")
            began = time.perf_counter()
            image = frame.to_image().convert("RGB")
            timings["preprocess_seconds"] += time.perf_counter()-began
            yield {"frame_index": selected-1, "pts": frame.pts, "time_base": str(frame.time_base),
                   "stream_start_pts": stream.start_time, "stream_time_base": str(stream.time_base),
                   "source_ms": round(float(stamp * 1000), 6), "width": frame.width, "height": frame.height}, image
    if not selected:
        raise InvalidRequest("Continuous pose source window has no frames")


def prediction_record(prediction, threshold, torch):
    """Copy finite raw coordinates/scores; COCO visibility is not calibration."""
    keep = (prediction["scores"] >= threshold).nonzero().flatten()
    qualified = int(keep.numel())
    detections = []
    for i in keep[:10]:
        box = prediction["boxes"][i].detach().cpu().tolist()
        keypoints = prediction["keypoints"][i].detach().cpu().tolist()
        kp_scores = prediction["keypoints_scores"][i].detach().cpu().tolist()
        score = float(prediction["scores"][i])
        if len(box) != 4 or len(keypoints) != 17 or len(kp_scores) != 17 or any(len(point) != 3 for point in keypoints):
            raise ValueError("Unexpected COCO17 prediction shape")
        values = [score, *box, *kp_scores, *(value for point in keypoints for value in point)]
        if any(not math.isfinite(value) for value in values) or not (box[2] > box[0] and box[3] > box[1]):
            raise ValueError("Nonfinite or degenerate raw pose prediction")
        detections.append({"detection_index": int(i), "track_id": None, "player_id": None,
                           "box_xyxy": box, "score": score, "keypoints_xyv": keypoints,
                           "keypoint_scores": kp_scores, "review_status": "unreviewed"})
    return detections, max(0, qualified-10)


def execute(request, root, output_path, progress):
    p = validate_parameters(request)
    root, output_path = Path(root).resolve(), Path(output_path).resolve()
    if output_path != resolve_relative(root, request["output_dir"], owner="models"):
        raise InvalidRequest("Output directory does not match request")
    asset = request["assets"][0]
    scope = usage_scope(asset, root)
    producer = {"module": "models", "model_id": MODEL_ID, "version": "0.1.0", "job_id": request["job_id"],
                "attempt_id": request["attempt_id"], "usage_scope": scope, "diagnostic_only": True}
    common = {"schema_version": "1.0", "model_id": MODEL_ID, "asset_id": asset["asset_id"],
              "source_sha256": asset["sha256"], "relative_path": asset["relative_path"], "match_id": asset["match_id"],
              "usage_scope": scope, "producer": producer, "start_ms": p["start_ms"], "end_ms": p["end_ms"]}
    timings = {key + "_seconds": 0.0 for key in ("source_verification", "framework_startup", "weight_verification", "cold", "decode", "preprocess", "model", "postprocess")}
    report = {**common, "status": "running", "parameters": p, "timings": timings, "batch_size": 1,
              "decoder": "PyAV CPU; no NVDEC", "sampling": "every decoded source frame within the explicit PTS interval",
              "max_frames": MAX_FRAMES, "max_selected_pixels": MAX_SELECTED_PIXELS, "frames_processed": 0,
              "tracking": "not_implemented", "accuracy": None, "recall": None,
              "input_distribution_caveat": "torchvision COCO Keypoint R-CNN replaces BST author's MMPose; not author pipeline reproduction",
              "timing_caveat": "cold model load and short-window forward measurements; not full-match throughput or causal latency"}
    started, stage = time.perf_counter(), "source_verification"
    with reserve(root, 100_000_000):
        output_path.mkdir(parents=True, exist_ok=True)
        if any(output_path.iterdir()):
            raise FileExistsError("Continuous pose requires a new empty output directory")
        try:
            source = resolve_relative(root, asset["relative_path"])
            began = time.perf_counter()
            with source.open("rb") as handle:
                before = os.fstat(handle.fileno())
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
                after = os.fstat(handle.fileno())
            if before.st_size != asset["size_bytes"] or digest != asset["sha256"] or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise InvalidRequest("Source checksum mismatch or file changed during verification")
            timings["source_verification_seconds"] = time.perf_counter()-began
            stage = "dependencies"
            began = time.perf_counter()
            from .inference import get_torch, weights_dir
            torch = get_torch()
            from torchvision.models.detection import keypointrcnn_resnet50_fpn
            from torchvision.transforms.functional import pil_to_tensor
            report["versions"] = {name: importlib.metadata.version(name) for name in ("torch", "torchvision", "av", "Pillow")}
            report.update(device=torch.cuda.get_device_name(), cuda_build=torch.version.cuda)
            torch.cuda.synchronize()
            timings["framework_startup_seconds"] = time.perf_counter()-began
            stage = "weight_verification"
            began = time.perf_counter()
            folder = weights_dir(root, "torchvision-pose")
            report["weight_manifest_sha256"] = hashlib.sha256((folder / "weights-manifest.json").read_bytes()).hexdigest()
            timings["weight_verification_seconds"] = time.perf_counter()-began
            stage = "cold_load"
            progress(stage, message="Load verified existing local COCO17 pose model")
            began = time.perf_counter()
            model = keypointrcnn_resnet50_fpn(weights=None, weights_backbone=None, min_size=480, max_size=854)
            state = torch.load(folder / "keypointrcnn_resnet50_fpn_coco-fc266e95.pth", map_location="cpu", weights_only=True)
            model.load_state_dict(state, strict=True)
            del state
            model.to("cuda").eval()
            torch.cuda.synchronize()
            timings["cold_seconds"] = time.perf_counter()-began
            frames = []
            try:
                stage = "decode"
                with closing(iter_source_frames(source, p, timings)) as iterator:
                    for record, image in iterator:
                        stage = "preprocess"
                        began = time.perf_counter()
                        tensor = pil_to_tensor(image).to(device="cuda", dtype=torch.float32)/255
                        torch.cuda.synchronize()
                        timings["preprocess_seconds"] += time.perf_counter()-began
                        stage = "model"
                        began = time.perf_counter()
                        with torch.inference_mode():
                            prediction = model([tensor])[0]
                        torch.cuda.synchronize()
                        timings["model_seconds"] += time.perf_counter()-began
                        stage = "postprocess"
                        began = time.perf_counter()
                        detections, omitted = prediction_record(prediction, p["score_threshold"], torch)
                        for detection in detections:
                            detection["detection_id"] = f'{record["frame_index"]}:{detection["detection_index"]}'
                        record.update(detections=detections, detections_omitted_by_cap=omitted)
                        frames.append(record)
                        del prediction, tensor
                        torch.cuda.synchronize()
                        timings["postprocess_seconds"] += time.perf_counter()-began
                        report["frames_processed"] = len(frames)
                        progress("pose", current=len(frames), total=MAX_FRAMES, unit="frame", message="Processed continuous source frame; identities remain unknown")
                        stage = "decode"
                report.update(peak_allocated_bytes=torch.cuda.max_memory_allocated(), peak_reserved_bytes=torch.cuda.max_memory_reserved())
            finally:
                del model
                torch.cuda.empty_cache()
            stage = "publish"
            payload = {**common, "format": "coco17-source-pixels", "frames": frames, "tracking": "not_implemented",
                       "sampling": "continuous_original_pts", "review_status": "unreviewed", "diagnostic_only": True,
                       "warning": "COCO visibility and raw keypoint scores are not calibrated badminton certainty; no interpolation, player identity or fine-action labels"}
            report.update(status="succeeded", elapsed_seconds=time.perf_counter()-started,
                          selected_source_pixels=sum(frame["width"]*frame["height"] for frame in frames),
                          observed_pts_span_seconds=(frames[-1]["source_ms"]-frames[0]["source_ms"])/1000)
            report["unattributed_seconds"] = max(0.0, report["elapsed_seconds"]-sum(timings.values()))
            report["elapsed_boundary"] = "before storage reservation through pre-publication; final JSON writes/artifact hashes excluded; framework_startup includes lazy imports and CUDA initialization"
            features = atomic_write_json(output_path / "features.json", payload)
            summary = atomic_write_json(output_path / "report.json", report)
            return {"artifacts": [make_artifact(root, features, "pose_features", producer),
                                  make_artifact(root, summary, "evaluation_report", producer)], "events": []}
        except BaseException as exc:
            report.update(status="failed", elapsed_seconds=time.perf_counter()-started, failure=safe_failure(exc, stage))
            report["unattributed_seconds"] = max(0.0, report["elapsed_seconds"]-sum(timings.values()))
            if isinstance(exc, ImportError):
                report["failure"]["code"] = "DEPENDENCY_NOT_INSTALLED"
            atomic_write_json(output_path / "failure.json", report)
            if isinstance(exc, ImportError):
                raise ModelBlocked("DEPENDENCY_NOT_INSTALLED", "Continuous pose environment is missing a required dependency") from None
            raise
