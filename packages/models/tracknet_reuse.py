"""Bounded, provenance-preserving reuse of the reviewed official TrackNetV3 model.

No optional dependencies, network requests, or model code execute on import.
The causal configuration is a project experiment, not the paper's evaluation.
"""
from collections import deque
from bisect import bisect_right
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import types

from .protocol import InvalidRequest, ModelBlocked, atomic_write_json, make_artifact, resolve_relative, validate_request
from .storage import reserve

COMMIT = "6eda442ada1740573f200f836d93edc9a541ee86"
CODE_SHA256 = "04fd51ff88e58189474677dbf11f81e52b78df00226fb97ea0678b31ef7284e3"
CODE_SIZE = 5890
MODEL_ID = "tracknetv3-reuse"
MODEL_VERSION = "0.1.0"
WIDTH, HEIGHT = 512, 288
MAX_FRAMES = 1800
MAX_PIXELS = 3840 * 2160
BACKGROUND_PIXELS = 96_000_000
MAX_REPLAY_SECONDS = 120


def options(request):
    p = request["parameters"]
    if request["operation"] not in {"analyze", "tracking"} or p.get("model_id") != MODEL_ID or len(request["assets"]) != 1:
        raise InvalidRequest("TrackNet reuse requires analyze/tracking and exactly one Asset")
    allowed = {"model_id", "model_version", "mode", "start_ms", "end_ms", "device", "background_frames", "paced_replay", "replay_deadline_ms"}
    if set(p) - allowed:
        raise InvalidRequest("TrackNet parameters contain unsupported fields")
    if p.get("model_version", MODEL_VERSION) != MODEL_VERSION:
        raise InvalidRequest("TrackNet model_version must be 0.1.0")
    asset = request["assets"][0]
    start, end = p.get("start_ms", 0), p.get("end_ms", min(asset["duration_ms"], 10000))
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= asset["duration_ms"] or end - start > 30000:
        raise InvalidRequest("TrackNet interval must be inside source duration and at most 30 seconds")
    mode, device, background = p.get("mode", "offline_weight"), p.get("device", "cuda"), p.get("background_frames", 8)
    if mode not in {"offline_weight", "causal_last"} or device not in {"cuda", "cpu"}:
        raise InvalidRequest("Unsupported TrackNet mode or device")
    if type(background) is not int or not 1 <= background <= 64:
        raise InvalidRequest("background_frames must be 1..64")
    paced, deadline = p.get("paced_replay", False), p.get("replay_deadline_ms", 40)
    if type(paced) is not bool or (paced and mode != "causal_last"):
        raise InvalidRequest("paced_replay must be boolean and requires causal_last")
    if type(deadline) not in (int, float) or not math.isfinite(deadline) or not 1 <= deadline <= 1000:
        raise InvalidRequest("replay_deadline_ms must be finite and between 1 and 1000")
    if "replay_deadline_ms" in p and not paced:
        raise InvalidRequest("replay_deadline_ms requires paced_replay")
    return {"start_ms": start, "end_ms": end, "mode": mode, "device": device, "background_frames": background,
            "paced_replay": paced, "replay_deadline_ms": deadline}


def usage_scope(asset, root):
    scopes = [asset.get("usage_scope", "general"), asset.get("provenance", {}).get("usage_scope", "general")]
    if any(scope not in {"general", "training_only"} for scope in scopes):
        raise InvalidRequest("Unsupported Asset usage_scope")
    logical = asset["relative_path"].split("/")
    physical = resolve_relative(root, asset["relative_path"]).relative_to(Path(root).resolve()).parts
    training_path = any(tuple(part.casefold() for part in parts[:2]) == ("data", "training") for parts in (logical, physical))
    return "training_only" if training_path or "training_only" in scopes else "general"


def verify_file(root, entry, *, prefix=None):
    if not isinstance(entry, dict) or not {"relative_path", "sha256", "size_bytes"} <= set(entry):
        raise ModelBlocked("TRACKNET_MANIFEST_INVALID", "TrackNet manifest requires file path, bytes and SHA256")
    path = resolve_relative(root, entry["relative_path"], owner="models" if prefix else None)
    if prefix and (not entry["relative_path"].startswith(prefix) or not path.relative_to(Path(root).resolve()).as_posix().startswith(prefix)):
        raise ModelBlocked("TRACKNET_MANIFEST_INVALID", "TrackNet file is outside its designated owner subdirectory")
    if type(entry["size_bytes"]) is not int or entry["size_bytes"] < 1 or not isinstance(entry["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", entry["sha256"]):
        raise ModelBlocked("TRACKNET_MANIFEST_INVALID", "TrackNet file metadata is invalid")
    if not path.is_file():
        raise ModelBlocked("TRACKNET_NOT_INSTALLED", "A required local TrackNet file is missing")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size != entry["size_bytes"]:
            raise ModelBlocked("TRACKNET_HASH_MISMATCH", "TrackNet/source file size differs from manifest")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or digest.hexdigest() != entry["sha256"]:
        raise ModelBlocked("TRACKNET_HASH_MISMATCH", "TrackNet/source file hash differs from manifest")
    return path


def read_manifest(root):
    path = resolve_relative(root, os.environ.get("BTV_TRACKNET_MANIFEST", "models/weights/tracknetv3/reuse-manifest.json"), owner="models")
    if not path.is_file():
        raise ModelBlocked("TRACKNET_NOT_INSTALLED", "Verified TrackNet reuse manifest is not installed")
    if path.stat().st_size > 64_000:
        raise ModelBlocked("TRACKNET_MANIFEST_INVALID", "TrackNet manifest exceeds its size bound")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["schema_version"] != "1.0" or manifest["source_commit"] != COMMIT or manifest["license"] != "MIT":
            raise ValueError()
        if manifest["code"]["size_bytes"] != CODE_SIZE or manifest["code"]["sha256"] != CODE_SHA256 or not 0 < manifest["checkpoint"]["size_bytes"] <= 1_000_000_000:
            raise ValueError()
        code = verify_file(root, manifest["code"], prefix="models/upstream/")
        checkpoint = verify_file(root, manifest["checkpoint"], prefix="models/weights/")
        if code.name != "model.py":
            raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise ModelBlocked("TRACKNET_MANIFEST_INVALID", "TrackNet manifest does not identify the reviewed source and weights") from exc
    return manifest, code, checkpoint


def verified_code_bytes(path):
    """Verify the exact bytes compiled, not an earlier read or self-signed manifest."""
    with path.open("rb") as stream:
        source = stream.read(CODE_SIZE + 1)
    if len(source) != CODE_SIZE or hashlib.sha256(source).hexdigest() != CODE_SHA256:
        raise ModelBlocked("TRACKNET_CODE_PIN_MISMATCH", "TrackNet executable source differs from the reviewed official byte pin")
    return source


class Runtime:
    """Only the hash-verified upstream model.py executes; no upstream CLI imports."""
    def __init__(self, root, device):
        self.manifest, code, checkpoint = read_manifest(root)
        try:
            import numpy as np
            import torch
            import cv2
            import av
            from PIL import Image
        except (ImportError, OSError) as exc:
            raise ModelBlocked("DEPENDENCY_NOT_INSTALLED", "TrackNet needs working torch, NumPy, Pillow, PyAV and OpenCV") from exc
        if device == "cuda" and not torch.cuda.is_available():
            raise ModelBlocked("CUDA_UNAVAILABLE", "TrackNet CUDA configuration requires an available CUDA device")
        self.np, self.torch, self.cv2, self.Image, self.device = np, torch, cv2, Image, device
        try:
            state = torch.load(checkpoint, map_location="cpu", weights_only=True)
            self.seq_len = state["param_dict"]["seq_len"]
            self.bg_mode = state["param_dict"]["bg_mode"]
        except Exception as exc:
            raise ModelBlocked("TRACKNET_CHECKPOINT_UNSUPPORTED", "TrackNet checkpoint failed restricted weights-only loading") from exc
        if type(self.seq_len) is not int or not 1 <= self.seq_len <= 16 or self.bg_mode not in {"", "concat"}:
            raise ModelBlocked("TRACKNET_CHECKPOINT_UNSUPPORTED", "TrackNet reuse supports seq_len 1..16 and empty/concat background mode")
        # compile/exec avoids importlib creating a __pycache__ in read-only
        # upstream storage. This is the one reviewed, hash-verified code file.
        module = types.ModuleType("btv_reviewed_tracknet_model")
        module.__file__ = str(code)
        exec(compile(verified_code_bytes(code), str(code), "exec"), module.__dict__)
        channels = (self.seq_len + (self.bg_mode == "concat")) * 3
        self.model = module.TrackNet(in_dim=channels, out_dim=self.seq_len)
        self.model.load_state_dict(state["model"], strict=True)
        self.model.to(device).eval()
        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        # Shape/device warmup only. This synthetic tensor never becomes evidence.
        with torch.inference_mode():
            self.model(torch.zeros((1, channels, HEIGHT, WIDTH), device=device))
        self.synchronize()

    def synchronize(self):
        if self.device == "cuda":
            self.torch.cuda.synchronize()

    def image_array(self, image):
        return self.np.asarray(image.convert("RGB"), dtype=self.np.uint8)

    def resize(self, image):
        return self.np.asarray(image.resize((WIDTH, HEIGHT)), dtype=self.np.uint8)

    def background(self, arrays):
        median = self.np.median(self.np.stack(arrays), axis=0).astype(self.np.uint8)
        return self.resize(self.Image.fromarray(median))

    def prepare(self, frames, background):
        arrays = ([background] if self.bg_mode == "concat" else []) + list(frames)
        array = self.np.concatenate([a.transpose(2, 0, 1) for a in arrays], axis=0)
        return self.torch.from_numpy(array).to(device=self.device, dtype=self.torch.float32).div_(255).unsqueeze(0)

    def predict(self, tensor):
        self.synchronize()
        with self.torch.inference_mode():
            output = self.model(tensor)[0].detach().cpu().numpy()
        self.synchronize()
        if output.shape != (self.seq_len, HEIGHT, WIDTH) or not self.np.isfinite(output).all():
            raise ValueError("TrackNet returned invalid heatmaps")
        return output

    def point(self, heatmap, record):
        return heatmap_point(heatmap, record["width"], record["height"], self.cv2)

    def details(self):
        return {"torch": self.torch.__version__, "device": self.device,
                "cuda_build": self.torch.version.cuda,
                "peak_allocated_bytes": self.torch.cuda.max_memory_allocated() if self.device == "cuda" else None,
                "peak_reserved_bytes": self.torch.cuda.max_memory_reserved() if self.device == "cuda" else None}


def heatmap_point(heatmap, width, height, cv2):
    binary = (heatmap > 0.5).astype("uint8") * 255
    contours, _ = cv2.findContours(binary.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects = [cv2.boundingRect(contour) for contour in contours]
    if not rects:
        return {"status": "missing", "x": None, "y": None, "response_peak": float(heatmap.max()), "missing_reason": "no_heatmap_component"}
    x, y, w, h = max(rects, key=lambda rect: rect[2] * rect[3])
    # Preserve upstream integer center-before-rescale postprocessing.
    cx, cy = int(x + w / 2), int(y + h / 2)
    if cx == cy == 0:
        return {"status": "missing", "x": None, "y": None, "response_peak": float(heatmap.max()), "missing_reason": "upstream_origin_sentinel"}
    return {"status": "observed", "x": int(cx * width / WIDTH), "y": int(cy * height / HEIGHT),
            "response_peak": float(heatmap[y:y+h, x:x+w].max()), "missing_reason": None}


def triangular_weights(length):
    values = [min(index + 1, length - index) for index in range(length)]
    return [value / sum(values) for value in values]


class Ensemble:
    """At most L frames of heatmap accumulators; upstream edge averages preserved."""
    def __init__(self, length):
        self.length, self.weights, self.pending = length, triangular_weights(length), {}

    def add(self, start, predictions):
        for position, heatmap in enumerate(predictions):
            index = start + position
            if index not in self.pending:
                self.pending[index] = [heatmap.copy(), heatmap * self.weights[position], 1]
            else:
                item = self.pending[index]
                item[0] += heatmap
                item[1] += heatmap * self.weights[position]
                item[2] += 1

    def pop(self, index):
        equal, weighted, count = self.pending.pop(index)
        return equal / count if count < self.length else weighted


def metric_summary(values):
    ordered = sorted(values)
    if not ordered:
        return {"mean": None, "p95": None, "max": None}
    return {"mean": sum(ordered) / len(ordered), "p95": ordered[max(0, math.ceil(len(ordered) * .95) - 1)], "max": ordered[-1]}


class PacedReplay:
    """One decoded frame of lookahead, released at source PTS; no future inference.

    The scheduler measures this process's file replay, not physical live capture.
    It never drops a frame to make a timing result look better.
    """
    def __init__(self, epoch, start_ms, deadline_ms):
        self.epoch, self.start_ms, self.deadline_ms = epoch, start_ms, deadline_ms
        self.wait_seconds, self.rows = 0.0, []

    def check_deadline(self):
        if time.perf_counter() - self.epoch > MAX_REPLAY_SECONDS:
            raise InvalidRequest("paced TrackNet replay exceeded the 120-second wall bound")

    def start(self, record, read_started, decoded_at):
        self.check_deadline()
        arrival_ms = record["source_ms"] - self.start_ms
        if not 0 <= arrival_ms <= 30000 or len(self.rows) >= MAX_FRAMES:
            raise InvalidRequest("paced TrackNet replay exceeds source time/frame bounds")
        arrival = self.epoch + arrival_ms / 1000
        waited = 0.0
        while True:
            remaining = arrival - time.perf_counter()
            if remaining <= 0:
                break
            # Small sleeps remain responsive to the standard cancellation path.
            wait_start = time.perf_counter()
            time.sleep(min(remaining, .05))
            waited += time.perf_counter() - wait_start
            self.check_deadline()
        ready = time.perf_counter()
        self.wait_seconds += waited
        row = {"scheduled_arrival_ms": arrival_ms,
               "read_started_ms": (read_started - self.epoch) * 1000,
               "decoded_ready_ms": (decoded_at - self.epoch) * 1000,
               "processing_started_ms": (ready - self.epoch) * 1000,
               "pacing_wait_ms": waited * 1000,
               "decoded_prefetch_lead_ms": max(0.0, (arrival - decoded_at) * 1000),
               "backlog_at_read_ms": max(0.0, (read_started - arrival) * 1000),
               "processing_start_lag_ms": max(0.0, (ready - arrival) * 1000),
               "deadline_ms": arrival_ms + self.deadline_ms}
        record["replay"] = row
        self.rows.append(row)

    def complete(self, record, *, prediction_emitted):
        self.check_deadline()
        row = record["replay"]
        completion = (time.perf_counter() - self.epoch) * 1000
        row.update(completed_ms=completion,
                   simulated_arrival_to_completion_ms=max(0.0, completion - row["scheduled_arrival_ms"]),
                   decode_and_service_ms=max(0.0, row["decoded_ready_ms"] - row["read_started_ms"] + completion - row["processing_started_ms"]),
                   deadline_lateness_ms=max(0.0, completion - row["deadline_ms"]),
                   deadline_missed=completion > row["deadline_ms"], prediction_emitted=prediction_emitted,
                   dropped=False)

    def report(self):
        # These counts use timestamps after the run, never future images in an
        # inference input. A queued source frame may not yet have been decoded.
        arrivals = [row["scheduled_arrival_ms"] for row in self.rows]
        for index, row in enumerate(self.rows):
            row["queued_behind_current_at_start"] = max(0, bisect_right(arrivals, row["processing_started_ms"]) - index - 1)
            row["pending_after_completion"] = max(0, bisect_right(arrivals, row["completed_ms"]) - index - 1)
        emitted = [row for row in self.rows if row["prediction_emitted"]]
        return {"enabled": True, "kind": "source_pts_paced_file_replay", "physical_live_end_to_end": False,
                "arrival_boundary": "one decoded frame may be read ahead; image enters model history only after its scheduled source PTS",
                "backlog_definition": "source schedule lag and post-hoc pending frame counts; not an allocated media queue",
                "deadline_budget_ms": self.deadline_ms, "wall_bound_seconds": MAX_REPLAY_SECONDS,
                "pacing_wait_seconds": self.wait_seconds, "processed_frames": len(self.rows), "prediction_frames": len(emitted),
                "warmup_frames": len(self.rows) - len(emitted), "deadline_missed_frames": sum(row["deadline_missed"] for row in self.rows),
                "deadline_missed_prediction_frames": sum(row["deadline_missed"] for row in emitted),
                "dropped_frames": 0, "drop_policy": "none; process every decoded frame or fail whole request at a bound",
                "max_pending_frames_after_completion": max((row["pending_after_completion"] for row in self.rows), default=0),
                "backlog_at_read_ms": metric_summary([row["backlog_at_read_ms"] for row in self.rows]),
                "simulated_arrival_to_completion_ms": metric_summary([row["simulated_arrival_to_completion_ms"] for row in emitted]),
                "decode_and_service_ms": metric_summary([row["decode_and_service_ms"] for row in emitted])}


def iter_frames(path, opts, timings):
    """Continuous presentation-order software decode; never fabricate a source PTS."""
    import av
    decoded, selected, previous, dimensions = 0, 0, None, None
    prior_decode_seconds = timings["decode_seconds"]
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("source has no video stream")
        stream = container.streams.video[0]
        offset = stream.start_time or 0
        container.seek(int(opts["start_ms"] / 1000 / stream.time_base) + offset, stream=stream, backward=True)
        iterator = iter(container.decode(stream))
        while True:
            t = time.perf_counter()
            try:
                frame = next(iterator)
            except StopIteration:
                timings["decode_seconds"] += time.perf_counter() - t
                break
            timings["decode_seconds"] += time.perf_counter() - t
            decoded += 1
            # Runtime waiting on consumers is excluded from this decoder budget.
            if decoded > 10000 or timings["decode_seconds"] - prior_decode_seconds > 60:
                raise ValueError("TrackNet decode work bound exceeded")
            if frame.width <= 0 or frame.height <= 0 or frame.width * frame.height > MAX_PIXELS:
                raise ValueError("TrackNet source frame exceeds pixel bound")
            if frame.pts is None or frame.time_base is None:
                raise ValueError("TrackNet source frame lacks PTS/time_base")
            timestamp = frame.pts * frame.time_base - offset * stream.time_base
            if timestamp < 0 or (previous is not None and timestamp <= previous):
                raise ValueError("TrackNet requires strictly increasing source presentation times")
            previous = timestamp
            if timestamp * 1000 >= opts["end_ms"]:
                break
            if timestamp * 1000 < opts["start_ms"]:
                continue
            if dimensions is not None and dimensions != (frame.width, frame.height):
                raise ValueError("TrackNet window changes image dimensions")
            dimensions = (frame.width, frame.height)
            selected += 1
            if selected > MAX_FRAMES:
                raise ValueError("TrackNet continuous window exceeds 1800 frames; shorten the interval")
            t = time.perf_counter()
            image = frame.to_image().convert("RGB")
            timings["pre_seconds"] += time.perf_counter() - t
            yield {"frame_index": selected - 1, "source_ms": round(float(timestamp) * 1000, 6),
                   "pts": frame.pts, "time_base": str(frame.time_base), "stream_start_pts": offset,
                   "width": frame.width, "height": frame.height}, image
    if not selected:
        raise ValueError("TrackNet window has no decodable source frames")


def offline_background(path, opts, runtime, timings):
    arrays, stamps, maximum, next_ms = [], [], None, opts["start_ms"]
    for record, image in iter_frames(path, opts, timings):
        if maximum is None:
            maximum = min(32, BACKGROUND_PIXELS // (record["width"] * record["height"]))
        if record["source_ms"] >= next_ms and len(arrays) < maximum:
            t = time.perf_counter()
            arrays.append(runtime.image_array(image))
            stamps.append(record["source_ms"])
            timings["pre_seconds"] += time.perf_counter() - t
            step = (opts["end_ms"] - opts["start_ms"]) / maximum
            next_ms = opts["start_ms"] + (math.floor((record["source_ms"] - opts["start_ms"]) / step) + 1) * step
    t = time.perf_counter()
    background = runtime.background(arrays)
    timings["pre_seconds"] += time.perf_counter() - t
    return background, stamps


def process(path, opts, runtime, progress):
    timings = {key + "_seconds": 0.0 for key in ("decode", "pre", "model", "post")}
    beginning = time.perf_counter()
    if opts.get("paced_replay") and opts["mode"] != "causal_last":
        raise InvalidRequest("paced replay cannot measure an offline model as causal")
    replay = PacedReplay(beginning, opts["start_ms"], opts["replay_deadline_ms"]) if opts.get("paced_replay") else None
    background, background_pts, calibration, background_wall = None, [], [], 0.0
    if runtime.bg_mode and opts["mode"] == "offline_weight":
        progress("background", message="Decode bounded offline background samples from the full requested window")
        background, background_pts = offline_background(path, opts, runtime, timings)
        background_wall = time.perf_counter() - beginning
    ring, records, latencies = deque(maxlen=runtime.seq_len), [], []
    ensemble = Ensemble(runtime.seq_len)
    inference_count, steady_start, steady_source_ms, steady_wait_baseline = 0, None, None, 0.0
    iterator = iter(iter_frames(path, opts, timings))
    while True:
        read_started = time.perf_counter()
        try:
            record, image = next(iterator)
        except StopIteration:
            break
        decoded_at = time.perf_counter()
        wait_before = replay.wait_seconds if replay else 0.0
        if replay:
            replay.start(record, read_started, decoded_at)
        frame_started = time.perf_counter()
        index = record["frame_index"]
        record.update(status="missing", x=None, y=None, response_peak=None, confidence=None,
                      inpainted=False, missing_reason="sequence_warmup", available_after_source_ms=record["source_ms"])
        records.append(record)
        t = time.perf_counter()
        ring.append(runtime.resize(image))
        if runtime.bg_mode and opts["mode"] == "causal_last" and index < opts["background_frames"]:
            if (len(calibration) + 1) * record["width"] * record["height"] > BACKGROUND_PIXELS:
                raise InvalidRequest("causal background_frames exceeds background pixel budget")
            calibration.append(runtime.image_array(image))
            background_pts.append(record["source_ms"])
            record["missing_reason"] = "background_warmup"
            if index + 1 == opts["background_frames"]:
                background = runtime.background(calibration)
                calibration.clear()
                background_wall = time.perf_counter() - beginning
            timings["pre_seconds"] += time.perf_counter() - t
            if replay:
                replay.complete(record, prediction_emitted=False)
            continue
        if len(ring) < runtime.seq_len:
            timings["pre_seconds"] += time.perf_counter() - t
            if replay:
                replay.complete(record, prediction_emitted=False)
            continue
        if steady_start is None:
            steady_start, steady_source_ms = (read_started if replay else frame_started), record["source_ms"]
            steady_wait_baseline = wait_before
        tensor = runtime.prepare(ring, background)
        runtime.synchronize()
        timings["pre_seconds"] += time.perf_counter() - t
        t = time.perf_counter()
        predictions = runtime.predict(tensor)
        timings["model_seconds"] += time.perf_counter() - t
        inference_count += 1
        t = time.perf_counter()
        if opts["mode"] == "causal_last":
            record.update(runtime.point(predictions[-1], record))
        else:
            start = index - runtime.seq_len + 1
            ensemble.add(start, predictions)
            target = records[start]
            target.update(runtime.point(ensemble.pop(start), target), available_after_source_ms=max([record["source_ms"], *background_pts]))
        timings["post_seconds"] += time.perf_counter() - t
        latencies.append((time.perf_counter() - frame_started) * 1000)
        if replay:
            replay.complete(record, prediction_emitted=True)
        if inference_count == 1 or inference_count % 30 == 0:
            progress("tracknet", current=index + 1, unit="frame", message="Processed real source window; output remains unreviewed preannotation")
    t = time.perf_counter()
    for index in sorted(ensemble.pending):
        target = records[index]
        target.update(runtime.point(ensemble.pop(index), target), available_after_source_ms=max([records[-1]["source_ms"], *background_pts]))
    timings["post_seconds"] += time.perf_counter() - t
    finished = time.perf_counter()
    if replay:
        replay.check_deadline()
    if not inference_count:
        raise InvalidRequest("TrackNet window is too short for checkpoint sequence/background warmup")
    requested_duration = (opts["end_ms"] - opts["start_ms"]) / 1000
    # Use observed PTS span: an early decoder EOF must not improve the RTF by
    # borrowing requested video time that was never actually processed.
    duration = (records[-1]["source_ms"] - records[0]["source_ms"]) / 1000
    steady_duration = (records[-1]["source_ms"] - steady_source_ms) / 1000
    replay_wait = replay.wait_seconds if replay else 0.0
    steady_active_seconds = finished - steady_start - (replay_wait - steady_wait_baseline)
    ordered = sorted(latencies)
    report = {"timings": timings, "pipeline_wall_seconds": finished - beginning,
              "background_wall_seconds": background_wall, "rtf_including_background": (finished - beginning) / duration if duration > 0 else None,
              "steady_rtf": max(0.0, steady_active_seconds) / steady_duration if steady_duration > 0 else None,
              "steady_rtf_basis": "actual sequential decode/pre/model/post wall time excluding explicit pacing waits" if replay else "unpaced sequential pipeline wall time",
              "steady_wall_rtf_including_pacing": (finished - steady_start) / steady_duration if steady_duration > 0 else None,
              "pipeline_rtf_excluding_pacing_wait": max(0.0, finished - beginning - replay_wait) / duration if duration > 0 else None,
              "steady_source_duration_seconds": steady_duration, "observed_pts_span_seconds": duration,
              "requested_source_window_seconds": requested_duration,
              "frames": len(records), "model_windows": inference_count,
              "window_service_latency_ms": {"mean": sum(latencies) / len(latencies), "p95": ordered[max(0, math.ceil(len(ordered) * .95) - 1)], "max": max(latencies)},
              "live_end_to_end_latency_ms": None, "latency_measurement": "source-PTS paced file replay; separate simulated arrival latency includes backlog" if replay else "unpaced file replay; window service excludes preceding decode",
              "paced_replay": replay.report() if replay else {"enabled": False},
              "dropped_frames_by_adapter": 0, "codec_internal_dropped_frames": None, "drop_policy": "process every decoded frame or fail the whole bounded request",
              "decoder": "PyAV software decode; NVDEC not requested or measured", "background_source_ms": background_pts,
              "background_policy": "none" if not runtime.bg_mode else ("bounded_full_window_sample_median" if opts["mode"] == "offline_weight" else "historical_prefix_median"),
              "observation_count": sum(row["status"] == "observed" for row in records),
              "missing_count": sum(row["status"] == "missing" for row in records), "inpainted_count": 0}
    return records, report


def execute(request, root, output_path, progress):
    validate_request(request, root)
    opts = options(request)
    asset = request["assets"][0]
    scope = usage_scope(asset, root)
    output = resolve_relative(root, request["output_dir"], owner="models")
    if output != Path(output_path).resolve():
        raise InvalidRequest("TrackNet output does not match validated output_dir")
    with reserve(root, 20_000_000):
        targets = [output / "tracknet-points.json", output / "tracknet-report.json"]
        if any(target.exists() or target.is_symlink() for target in targets):
            raise FileExistsError("TrackNet attempt output already exists")
        cold = time.perf_counter()
        path = verify_file(root, asset)
        progress("load_model", message="Verify local TrackNet source/checkpoint and perform device shape warmup")
        runtime = Runtime(root, opts["device"])
        cold = time.perf_counter() - cold
        records, report = process(path, opts, runtime, progress)
        producer = {"module": "models", "model_id": MODEL_ID, "version": MODEL_VERSION, "source_commit": COMMIT,
                    "job_id": request["job_id"], "attempt_id": request["attempt_id"], "usage_scope": scope}
        common = {"schema_version": "1.0", "usage_scope": scope, "asset_id": asset["asset_id"], "match_id": asset["match_id"],
                  "source_sha256": asset["sha256"], "start_ms": opts["start_ms"], "end_ms": opts["end_ms"], "producer": producer,
                  "mode": opts["mode"], "causal_image_dependencies": opts["mode"] == "causal_last",
                  "inpaintnet": "not_run", "manual_review_required": True, "accuracy": None, "recall": None,
                  "quality_status": "unvalidated project inference configuration", "checkpoint": runtime.manifest["checkpoint"],
                  "code": runtime.manifest["code"], "source_rights": asset["rights"],
                  "source_type": asset["source_type"], "camera_type": asset["camera_type"], "discipline": asset["discipline"]}
        payload = {**common, "format": "tracknet-observation-source-pixels-v1", "frames": records,
                   "coordinate_space": "source image pixels; not calibrated court coordinates",
                   "response_semantics": "uncalibrated sigmoid heatmap peak; confidence remains null"}
        report.update(common, cold_seconds=cold, runtime=runtime.details(), seq_len=runtime.seq_len, bg_mode=runtime.bg_mode,
                      acceptance={"R-07a": "requires real source review", "R-07c": "not established by replay throughput alone"})
        t = time.perf_counter()
        atomic_write_json(targets[0], payload)
        report["points_publish_seconds"] = time.perf_counter() - t
        atomic_write_json(targets[1], report)
        artifacts = [make_artifact(root, target, kind, producer) for target, kind in zip(targets, ("shuttle_observations", "evaluation_report"))]
        return {"artifacts": artifacts, "events": []}
