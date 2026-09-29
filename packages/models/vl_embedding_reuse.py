"""Bounded, offline reuse of the reviewed Qwen3-VL embedding implementation.

Importing this module needs only the standard library. This is a diagnostic
adapter, not a classifier or a source of production edit candidates.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import traceback
import types

from .protocol import InvalidRequest, ModelBlocked, atomic_write_json, make_artifact, resolve_relative
from .storage import reserve

MODEL_ID = "qwen3-vl-embedding-2b"
SOURCE = "https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B"
REVISION = "9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda"
CODE_SHA256 = "8ffa74a1a6bb759610c57865ea416fd4daf9936cb787520e1112a3e1d547f36a"
# Official pinned metadata. Small files use Git blob SHA1; LFS files use SHA256.
FILES = {
    ".gitattributes": (1570, "52373fe24473b1aa44333d318f578ae6bf04b49b"),
    "1_Pooling/config.json": (96, "4a43bdd1fde87716f74fb5e1c7324b933288b93b"),
    "README.md": (24249, "85aa7367947398b90add631415cf8e7b12a86cff"),
    "added_tokens.json": (707, "b54f9135e44c1e81047e8d05cb027af8bc039eed"),
    "chat_template.jinja": (5519, "a0b161f8af53a32ce7e659103babce500990a863"),
    "config.json": (1570, "e426469143f8255335f039fa32c959584558d1cc"),
    "config_sentence_transformers.json": (238, "45201cb7fdb6b2546b0887a0f4f29d01df334ca4"),
    "merges.txt": (1671853, "31349551d90c7606f325fe0f11bbb8bd5fa0d7c7"),
    "model.safetensors": (4255140312, "c73fa9caeddeb3ff831d46c085a7a5708343248ca777e90f2d486964464509c1"),
    "modules.json": (429, "0de5a64717df8bf17171bd792d02296e76b83c06"),
    "preprocessor_config.json": (783, "0dfe4c69669474dcbc3a9cb2880759b51c888973"),
    "scripts/qwen3_vl_embedding.py": (13258, "36d45865735be96a1278a21c132ff640e2ae68ca"),
    "sentence_bert_config.json": (770, "17ab6283e805090588f5c045177996d0140ac267"),
    "special_tokens_map.json": (613, "ac23c0aaa2434523c494330aeb79c58395378103"),
    "tokenizer.json": (11423705, "def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a"),
    "tokenizer_config.json": (5404, "1d4fba2de0e94e8f97e08927cfb7d084160c2880"),
    "video_preprocessor_config.json": (817, "e32b1d90356f74457edbfca27aa1e121dab7cdc7"),
    "vocab.json": (2776833, "4783fe10ac3adce15ac8f358ef5462739852c569"),
}


def validate_parameters(request):
    p = request["parameters"]
    allowed = {"model_id", "model_version", "windows", "queries", "num_frames", "max_pixels", "compare_clip"}
    if set(p) - allowed or p.get("model_id") != MODEL_ID:
        raise InvalidRequest("Unsupported embedding parameters")
    if p.get("model_version", "0.1.0") != "0.1.0":
        raise InvalidRequest("Embedding model_version must be 0.1.0")
    if request["operation"] not in {"analyze", "video_embedding"}:
        raise InvalidRequest("Embedding requires video_embedding or analyze")
    count, pixels = p.get("num_frames", 6), p.get("max_pixels", 262144)
    if type(count) is not int or count not in {2, 4, 6, 8}:
        raise InvalidRequest("num_frames must be 2, 4, 6 or 8")
    if type(pixels) is not int or not 4096 <= pixels <= 262144:
        raise InvalidRequest("max_pixels must be 4096..262144")
    if type(p.get("compare_clip", False)) is not bool:
        raise InvalidRequest("compare_clip must be boolean")
    assets = {a["asset_id"]: a for a in request["assets"]}
    windows = p.get("windows")
    if not isinstance(windows, list) or not 1 <= len(windows) <= 4:
        raise InvalidRequest("windows must contain 1..4 explicit intervals")
    used = set()
    for w in windows:
        if not isinstance(w, dict) or set(w) != {"asset_id", "start_ms", "end_ms"}:
            raise InvalidRequest("Each window requires asset_id, start_ms and end_ms")
        if not isinstance(w["asset_id"], str) or w["asset_id"] not in assets:
            raise InvalidRequest("Window asset_id must reference an input Asset")
        start, end = w["start_ms"], w["end_ms"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= assets[w["asset_id"]]["duration_ms"] or end-start > 30000:
            raise InvalidRequest("Windows require in-range integer milliseconds and at most 30 seconds")
        identity = (w["asset_id"], start, end)
        if identity in used:
            raise InvalidRequest("Duplicate window")
        used.add(identity)
    if {w["asset_id"] for w in windows} != set(assets):
        raise InvalidRequest("Every input Asset must be used by a window")
    queries = p.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 8:
        raise InvalidRequest("queries must contain 1..8 local text probes")
    ids = set()
    for q in queries:
        if not isinstance(q, dict) or set(q) != {"query_id", "text", "language"}:
            raise InvalidRequest("Each query requires query_id, text and language")
        if not isinstance(q["query_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", q["query_id"]) or q["query_id"] in ids:
            raise InvalidRequest("query_id must be unique and contain 1..64 safe characters")
        ids.add(q["query_id"])
        if not isinstance(q["text"], str) or not q["text"].strip() or len(q["text"]) > 512 or any(ord(c) < 32 for c in q["text"]):
            raise InvalidRequest("Query text requires 1..512 printable characters")
        if not isinstance(q["language"], str) or q["language"] not in {"zh", "en"} or (q["language"] == "zh" and not re.search(r"[\u3400-\u9fff]", q["text"])):
            raise InvalidRequest("Query language must be zh (with Chinese characters) or en")
    if not any(q["language"] == "zh" for q in queries):
        raise InvalidRequest("At least one Chinese query is required")
    return {**p, "num_frames": count, "max_pixels": pixels, "compare_clip": p.get("compare_clip", False)}


def usage_scope(asset, root):
    """Compatibility guard until the shared contracts helper reaches this branch."""
    provenance = asset.get("provenance", {})
    declared = [asset.get("usage_scope"), provenance.get("usage_scope")]
    for value in declared:
        if value is not None and (not isinstance(value, str) or value not in {"general", "training_only"}):
            raise InvalidRequest("Unknown usage_scope")
    logical = Path(asset["relative_path"]).parts
    physical = resolve_relative(root, asset["relative_path"])
    training = (Path(root).resolve() / "data" / "training").resolve()
    if "training_only" in declared or tuple(p.lower() for p in logical[:2]) == ("data", "training") or physical.is_relative_to(training):
        return "training_only"
    return "general"


def verify_weights(root):
    prefix = f"models/weights/{MODEL_ID}/"
    folder = resolve_relative(root, prefix.rstrip("/"), owner="models")
    manifest_path = resolve_relative(root, prefix + "weights-manifest.json", owner="models")
    if not manifest_path.is_file():
        raise ModelBlocked("MODEL_NOT_INSTALLED", "Missing local Qwen3-VL weights manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["source"] != SOURCE or manifest["revision"] != REVISION or manifest["schema_version"] != "1.0":
            raise ValueError("source mismatch")
        entries = manifest["files"]
        if not isinstance(entries, list) or len(entries) != len(FILES):
            raise ValueError("incomplete manifest")
        seen = set()
        for item in entries:
            relative = item["relative_path"]
            if not relative.startswith(prefix):
                raise ValueError("wrong directory")
            name = relative[len(prefix):]
            if name not in FILES or name in seen:
                raise ValueError("unexpected or duplicate file")
            seen.add(name)
            size, upstream_hash = FILES[name]
            path = resolve_relative(root, relative, owner="models")
            if not path.is_relative_to(folder) or path.stat().st_size != size or item["size_bytes"] != size:
                raise ValueError("file size or path mismatch")
            if item["source_url"] != f"{SOURCE}/resolve/{REVISION}/{name}":
                raise ValueError("unfixed source")
            sha = hashlib.sha256()
            git = hashlib.sha1(f"blob {size}\0".encode())
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                    sha.update(block)
                    if len(upstream_hash) == 40:
                        git.update(block)
                after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("weights changed while verifying")
            upstream = git.hexdigest() if len(upstream_hash) == 40 else sha.hexdigest()
            if sha.hexdigest() != item["sha256"] or upstream != upstream_hash:
                raise ModelBlocked("WEIGHT_HASH_MISMATCH", "Pinned weight checksum mismatch")
    except FileNotFoundError:
        raise ModelBlocked("MODEL_NOT_INSTALLED", "Local Qwen3-VL weight file is missing") from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ModelBlocked("WEIGHT_MANIFEST_INVALID", "Invalid pinned Qwen3-VL weight manifest") from None
    return folder, hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def load_reviewed_module(folder):
    source = (folder / "scripts" / "qwen3_vl_embedding.py").read_bytes()
    if hashlib.sha256(source).hexdigest() != CODE_SHA256:
        raise ModelBlocked("SOURCE_HASH_MISMATCH", "Reviewed embedding code checksum mismatch")
    name = "_btv_reviewed_qwen3_vl_embedding"
    module = types.ModuleType(name)
    module.__file__ = str(folder / "scripts" / "qwen3_vl_embedding.py")
    sys.modules[name] = module
    # Preserve the upstream module's annotation semantics: inheriting this
    # adapter's future annotations makes Transformers derive a string config_class.
    # Execute precisely the reviewed bytes, never a stale .pyc or remote AutoClass.
    exec(compile(source, module.__file__, "exec", dont_inherit=True), module.__dict__)
    return module


def bounded_size(width, height, maximum):
    if width <= 0 or height <= 0 or width * height > 3840 * 2160:
        raise InvalidRequest("Source frame dimensions exceed the diagnostic bound")
    scale = min(1.0, math.sqrt(maximum / (width * height)))
    w, h = max(32, int(width * scale) // 32 * 32), max(32, int(height * scale) // 32 * 32)
    while w * h > maximum:
        if w >= h:
            w -= 32
        else:
            h -= 32
    return w, h


def decode_window(path, window, count, pixels):
    import av
    from PIL import Image
    started = time.perf_counter()
    decode_seconds = preprocess_seconds = 0.0
    frames, points, previous = [], [], None
    start, end = Fraction(window["start_ms"], 1000), Fraction(window["end_ms"], 1000)
    targets = [start + i * (end - start) / count for i in range(count)]
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        origin = (stream.start_time or 0) * stream.time_base
        container.seek(int((start + origin) / stream.time_base), stream=stream, backward=True)
        for decoded, frame in enumerate(container.decode(stream), 1):
            if decoded > 10000 or time.perf_counter() - started > 60:
                raise InvalidRequest("Decode work bound exceeded")
            if frame.pts is None or frame.time_base is None:
                raise InvalidRequest("Missing source frame PTS/time_base")
            bounded_size(frame.width, frame.height, pixels)
            stamp = frame.pts * frame.time_base - origin
            if previous is not None and stamp <= previous:
                raise InvalidRequest("Non-monotonic source PTS requires explicit repair")
            previous = stamp
            if stamp >= end:
                break
            if stamp < targets[len(frames)]:
                continue
            # A sparse source cannot reuse the same frame for two requested samples.
            if len(frames) + 1 < count and stamp >= targets[len(frames) + 1]:
                raise InvalidRequest("Source has insufficient frames for requested sampling")
            size = bounded_size(frame.width, frame.height, pixels)
            before_pre = time.perf_counter()
            image = frame.to_image().convert("RGB").resize(size, Image.Resampling.BICUBIC)
            preprocess_seconds += time.perf_counter() - before_pre
            frames.append(image)
            points.append({"pts": frame.pts, "time_base": str(frame.time_base),
                           "stream_start_pts": stream.start_time, "stream_time_base": str(stream.time_base),
                           "source_seconds": float(stamp), "window_seconds": float(stamp-start),
                           "original_size": [frame.width, frame.height], "processed_size": list(size)})
            if len(frames) == count:
                break
    if len(frames) != count or len({im.size for im in frames}) != 1:
        raise InvalidRequest("Incomplete or dimension-changing source window")
    decode_seconds = time.perf_counter() - started - preprocess_seconds
    return frames, points, {"decode_seconds": decode_seconds, "frame_preprocess_seconds": preprocess_seconds}


def pts_timestamps(points):
    """Instance override for the reviewed transformers 4.57.3 processor only."""
    times = [point["window_seconds"] for point in points]
    if len(times) not in {2, 4, 6, 8} or any(not math.isfinite(t) or t < 0 for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise InvalidRequest("Invalid sampled source times")
    def calculate(indices, fps, merge_size=2):
        if list(indices) != list(range(len(times))) or merge_size != 2:
            raise InvalidRequest("Processor changed sampled frame order or temporal merge")
        return [(times[i] + times[i+1]) / 2 for i in range(0, len(times), 2)]
    return calculate


def check_vector(vector, dimension):
    if len(vector) != dimension or any(not math.isfinite(v) for v in vector):
        raise ValueError("Embedding is not a finite vector of expected dimension")
    if abs(math.sqrt(sum(v * v for v in vector)) - 1) > 0.002:
        raise ValueError("Embedding norm is not approximately one")
    return vector


def rankings(queries, windows, query_vectors, video_vectors):
    return [{"query_id": q["query_id"], "matches": sorted(
        [{"window_id": w["window_id"], "cosine_similarity": sum(a*b for a, b in zip(query_vectors[i], video_vectors[j]))}
         for j, w in enumerate(windows)], key=lambda item: (-item["cosine_similarity"], item["window_id"]))}
        for i, q in enumerate(queries)]


def embed_one(model, processor, torch, *, text=None, frames=None, points=None, duration=None):
    import numpy as np
    began = time.perf_counter()
    content = [{"type": "text", "text": text}] if text is not None else [{"type": "video", "video": "local-sampled-frames"}]
    messages = [{"role": "system", "content": [{"type": "text", "text": "Represent the user's input."}]},
                {"role": "user", "content": content}]
    prompt = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    kwargs = {"text": [prompt], "padding": True, "truncation": False, "return_tensors": "pt"}
    if frames is not None:
        processor._calculate_timestamps = pts_timestamps(points)
        kwargs.update(videos=[np.stack([np.asarray(frame) for frame in frames])],
                      videos_kwargs={"do_sample_frames": False, "do_resize": False,
                                     "input_data_format": "channels_last",
                                     "video_metadata": [{"total_num_frames": len(frames), "frames_indices": list(range(len(frames))),
                                                         "fps": len(frames)/duration, "duration": duration,
                                                         "width": frames[0].width, "height": frames[0].height,
                                                         "video_backend": "pyav_source_pts"}]})
    batch = processor(**kwargs)
    if batch["input_ids"].shape[-1] > 4096:
        raise InvalidRequest("Processor sequence exceeds 4096 tokens; no implicit truncation")
    batch = batch.to("cuda")
    torch.cuda.synchronize()
    pre_seconds = time.perf_counter() - began
    began = time.perf_counter()
    with torch.inference_mode():
        output = model(**batch)
    torch.cuda.synchronize()
    model_seconds = time.perf_counter() - began
    began = time.perf_counter()
    mask = output.attention_mask
    if mask.shape[0] != 1 or not mask.any():
        raise ValueError("Invalid embedding attention mask")
    last = mask.shape[1] - mask.flip([1]).long().argmax(1) - 1
    hidden = output.last_hidden_state[torch.arange(1, device=last.device), last].float()
    vector = torch.nn.functional.normalize(hidden, p=2, dim=-1)[0].cpu().tolist()
    check_vector(vector, 2048)
    return vector, {"preprocess_seconds": pre_seconds, "model_seconds": model_seconds,
                    "postprocess_seconds": time.perf_counter()-began, "input_tokens": int(batch["input_ids"].shape[-1])}


def safe_failure(exc, stage):
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    for name, value in os.environ.items():
        if value and len(value) >= 4 and any(word in name.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            detail = detail.replace(value, "[REDACTED]")
    detail = re.sub(r"hf_[A-Za-z0-9]{8,}", "[REDACTED]", detail)
    return {"stage": stage, "type": type(exc).__name__, "code": getattr(exc, "code", "execution_failed"),
            "traceback": detail[-16000:]}


def clip_comparison(root, torch, queries, windows, frame_sets):
    """Time each model input separately from video pooling and its CPU transfer."""
    from transformers import CLIPModel, CLIPProcessor
    from .inference import weights_dir
    started = time.perf_counter()
    folder = weights_dir(root, "clip-vit-base-patch32")
    verify_seconds = time.perf_counter()-started
    started = time.perf_counter()
    model = CLIPModel.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False).to("cuda").eval()
    processor = CLIPProcessor.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False)
    torch.cuda.synchronize()
    cold = time.perf_counter()-started
    videos, texts, timings, aggregation_timings = [], [], [], []
    try:
        for window, frames in zip(windows, frame_sets):
            features = []
            for frame in frames:
                start = time.perf_counter()
                inputs = processor(images=frame, return_tensors="pt").to("cuda")
                torch.cuda.synchronize()
                pre = time.perf_counter()-start
                start = time.perf_counter()
                with torch.inference_mode():
                    vec = model.get_image_features(**inputs).float()
                torch.cuda.synchronize()
                forward = time.perf_counter()-start
                start = time.perf_counter()
                features.append(torch.nn.functional.normalize(vec, dim=-1))
                torch.cuda.synchronize()
                timings.append({"preprocess_seconds": pre, "model_seconds": forward, "postprocess_seconds": time.perf_counter()-start})
            start = time.perf_counter()
            vector = torch.nn.functional.normalize(torch.cat(features).mean(0), dim=-1).cpu().tolist()
            videos.append(check_vector(vector, 512))
            aggregation_timings.append({"window_id": window["window_id"],
                                        "postprocess_seconds": time.perf_counter()-start})
        for query in queries:
            start = time.perf_counter()
            inputs = processor(text=[query["text"]], return_tensors="pt", padding=True, truncation=False).to("cuda")
            if inputs["input_ids"].shape[-1] > 77:
                raise InvalidRequest("CLIP text exceeds 77 tokens; no silent truncation")
            torch.cuda.synchronize()
            pre = time.perf_counter()-start
            start = time.perf_counter()
            with torch.inference_mode():
                vector = model.get_text_features(**inputs).float()
            torch.cuda.synchronize()
            forward = time.perf_counter()-start
            start = time.perf_counter()
            texts.append(check_vector(torch.nn.functional.normalize(vector, dim=-1)[0].cpu().tolist(), 512))
            timings.append({"preprocess_seconds": pre, "model_seconds": forward, "postprocess_seconds": time.perf_counter()-start})
        return {"status": "succeeded", "model_id": "clip-frame-mean", "query_vectors": texts, "video_vectors": videos,
                "rankings": rankings(queries, windows, texts, videos), "timings": timings,
                "video_aggregation_timings": aggregation_timings,
                "timing_scope": "timings covers each frame/text input; video_aggregation_timings separately covers frame pooling, normalization, GPU-to-CPU transfer and vector validation; neither sum is end-to-end wall time",
                "weight_verification_seconds": verify_seconds, "cold_seconds": cold,
                "peak_allocated_bytes": torch.cuda.max_memory_allocated(), "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                "language_caveat": "Original CLIP Chinese text is diagnostic only; optional English probes are not translations generated by the adapter",
                "temporal_method": "mean of normalized single-frame features, then normalize; same Qwen sampled frames"}
    finally:
        del model, processor


def execute(request, root, output_path, progress):
    """Report elapsed wall time through computation, excluding artifact publication.

    The clock starts before storage reservation, after request parameter/scope
    validation. It includes source/weight checks, dependency checks, decode,
    cold loads, embeddings, ranking and an optional CLIP comparison. Individual
    stage timings are diagnostic subsets, not an end-to-end throughput metric.
    """
    p = validate_parameters(request)
    root, output_path = Path(root).resolve(), Path(output_path).resolve()
    if output_path != resolve_relative(root, request["output_dir"], owner="models"):
        raise InvalidRequest("Output directory does not match validated request")
    assets = {a["asset_id"]: a for a in request["assets"]}
    scopes = {key: usage_scope(asset, root) for key, asset in assets.items()}
    scope = "training_only" if "training_only" in scopes.values() else "general"
    producer = {"module": "models", "model_id": MODEL_ID, "version": "0.1.0", "job_id": request["job_id"],
                "attempt_id": request["attempt_id"], "usage_scope": scope, "diagnostic_only": True}
    report = {"schema_version": "1.0", "model_id": MODEL_ID, "source": SOURCE, "revision": REVISION,
              "reviewed_code_sha256": CODE_SHA256, "usage_scope": scope, "producer": producer,
              "status": "running", "batch_size": 1, "decode_backend": "PyAV CPU", "timings": [],
              "timing_scope": "elapsed_seconds runs from before storage reservation to before artifact publication; includes verification, dependency checks, decode, cold loads, embeddings/ranking and requested CLIP comparison; excludes initial parameter/scope validation and artifact JSON I/O",
              "parameters": p,
              "accuracy": None, "precision_at_k": None, "truth_status": "no_frozen_human_ground_truth",
              "caveat": "Finite local diagnostic only; no NVDEC, full-match throughput or fine-technique accuracy claim"}
    stage, began = "validation", time.perf_counter()
    with reserve(root, 100_000_000):
        output_path.mkdir(parents=True, exist_ok=True)
        if any(output_path.iterdir()):
            raise FileExistsError("Embedding output directory must be new and empty")
        try:
            stage = "source_verification"
            started = time.perf_counter()
            paths = {}
            for key, asset in assets.items():
                path = resolve_relative(root, asset["relative_path"])
                with path.open("rb") as source:
                    before = os.fstat(source.fileno())
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                    after = os.fstat(source.fileno())
                    if before.st_size != asset["size_bytes"] or digest != asset["sha256"] or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise InvalidRequest("Source asset checksum mismatch")
                paths[key] = path
            report["source_verification_seconds"] = time.perf_counter()-started
            stage = "weight_verification"
            progress(stage, message="Verify pinned local embedding weights and reviewed source")
            started = time.perf_counter()
            folder, manifest_hash = verify_weights(root)
            report.update(weight_manifest_sha256=manifest_hash, weight_verification_seconds=time.perf_counter()-started)
            stage = "dependencies"
            import transformers
            if transformers.__version__ != "4.57.3":
                raise ModelBlocked("DEPENDENCY_VERSION", "This adapter audits transformers 4.57.3 exactly")
            from .inference import get_torch
            torch = get_torch()
            if not torch.__version__.split("+")[0].startswith("2.8."):
                raise ModelBlocked("DEPENDENCY_VERSION", "This adapter requires the isolated torch 2.8 environment")
            report["versions"] = {name: importlib.metadata.version(name) for name in ("torch", "torchvision", "transformers", "qwen-vl-utils", "av", "Pillow", "numpy", "safetensors")}
            report.update(device=torch.cuda.get_device_name(), cuda_build=torch.version.cuda)
            stage = "decode"
            windows, frame_sets = [], []
            for i, window in enumerate(p["windows"]):
                progress(stage, current=i, total=len(p["windows"]), unit="window", message="Decode bounded original PTS window on CPU")
                frames, points, timing = decode_window(paths[window["asset_id"]], window, p["num_frames"], p["max_pixels"])
                asset = assets[window["asset_id"]]
                windows.append({**window, "window_id": f"window-{i+1:02d}", "source_sha256": asset["sha256"],
                                "relative_path": asset["relative_path"], "match_id": asset["match_id"],
                                "usage_scope": scopes[asset["asset_id"]], "source_type": asset["source_type"],
                                "source_points": points, "timings": timing})
                frame_sets.append(frames)
            report["windows"] = windows
            stage = "cold_load"
            started = time.perf_counter()
            official = load_reviewed_module(folder)
            config = transformers.Qwen3VLConfig.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False)
            model = official.Qwen3VLForEmbedding.from_pretrained(str(folder), config=config, local_files_only=True, trust_remote_code=False,
                       use_safetensors=True, torch_dtype=torch.bfloat16, attn_implementation="sdpa").to("cuda").eval()
            processor = transformers.Qwen3VLProcessor.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False, padding_side="right")
            torch.cuda.synchronize()
            report["cold_seconds"] = time.perf_counter()-started
            videos, texts = [], []
            try:
                stage = "video_embedding"
                for i, (window, frames) in enumerate(zip(windows, frame_sets)):
                    progress(stage, current=i, total=len(windows), unit="window", message="Embed sampled video, batch one")
                    vector, timing = embed_one(model, processor, torch, frames=frames, points=window["source_points"], duration=(window["end_ms"]-window["start_ms"])/1000)
                    videos.append(vector)
                    report["timings"].append({"window_id": window["window_id"], **timing})
                stage = "text_embedding"
                for query in p["queries"]:
                    vector, timing = embed_one(model, processor, torch, text=query["text"])
                    texts.append(vector)
                    report["timings"].append({"query_id": query["query_id"], **timing})
                report.update(peak_allocated_bytes=torch.cuda.max_memory_allocated(), peak_reserved_bytes=torch.cuda.max_memory_reserved())
            finally:
                del model, processor
                torch.cuda.empty_cache()
            stage = "ranking"
            payload = {"schema_version": "1.0", "model_id": MODEL_ID, "producer": producer, "usage_scope": scope,
                       "diagnostic_only": True, "windows": windows, "queries": p["queries"], "dimension": 2048,
                       "video_vectors": videos, "query_vectors": texts, "rankings": rankings(p["queries"], windows, texts, videos),
                       "timestamp_method": "source PTS relative to stream origin; pair-mean window seconds in processor; exact PTS retained",
                       "comparison": {"status": "not_requested"}}
            if p["compare_clip"]:
                stage = "clip_comparison"
                torch.cuda.reset_peak_memory_stats()
                try:
                    payload["comparison"] = clip_comparison(root, torch, p["queries"], windows, frame_sets)
                except Exception as exc:
                    payload["comparison"] = {"status": "failed", "failure": safe_failure(exc, stage)}
                    progress(stage, event="warning", message="CLIP comparison failed; original error retained in local diagnostic")
            stage = "publish"
            report.update(status="succeeded", elapsed_seconds=time.perf_counter()-began, comparison_status=payload["comparison"]["status"])
            features_path = atomic_write_json(output_path / "features.json", payload)
            report_path = atomic_write_json(output_path / "report.json", report)
            return {"artifacts": [make_artifact(root, features_path, "video_embedding", producer),
                                  make_artifact(root, report_path, "evaluation_report", producer)], "events": []}
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "blocked" if isinstance(exc, (ModelBlocked, ImportError)) else "failed"
            report.update(status=status, elapsed_seconds=time.perf_counter()-began, failure=safe_failure(exc, stage))
            if isinstance(exc, ImportError):
                report["failure"]["code"] = "DEPENDENCY_NOT_INSTALLED"
            elif isinstance(exc, KeyboardInterrupt):
                report["failure"]["code"] = "cancelled"
            atomic_write_json(output_path / "failure.json", report)
            if isinstance(exc, ImportError):
                raise ModelBlocked("DEPENDENCY_NOT_INSTALLED", "The isolated embedding environment is missing a required dependency") from None
            raise
