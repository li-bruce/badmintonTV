"""Bounded R-01a CPU benchmark of the three legacy general-use real clips.

Assertions fixed before execution: both outputs must be 1080x1920 H.264/AAC,
30/60fps respectively, pass full decode QA, preserve the same source intervals,
and map continuous output frames with <= half an output-frame timing error per
segment. Safe-area metadata must not turn contain into crop. Human viewing and
platform upload acceptance remain pending, even when these technical checks pass.

Each preset has one first-observed slot and --repeats further slots. Sources are
SHA256-read before timing; no OS cache flush is attempted. This is NOT a true cold
cache benchmark. GPU backends are intentionally unavailable in this script.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time
import uuid

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from packages.render.engine import RenderConfig, render
from packages.render.presets import resolve_preset
from packages.render.storage import atomic_json, directory_bytes, reservation, sha256, utcnow
from packages.render.timeline import RenderError, assets_by_id, require, safe_path
from packages.render.usage import check_usage, verify_source_bytes

REQUEST_PATH = REPO_ROOT / "configs/render/real-research.request.json"
METADATA_LIMIT = 2_000_000
SOURCE_PATHS = {
    "data/raw/finebadmintonbenchmark/video_001951.mp4",
    "data/raw/finebadmintonbenchmark/video_000002.mp4",
    "data/raw/finebadmintonbenchmark/video_000003.mp4",
}
CACHE_NOTE = "Source hashes were pre-read; first-observed is not an OS cold-cache measurement."


def log(event, **values):
    print(json.dumps({"event": event, **values}, ensure_ascii=False, allow_nan=False), flush=True)


def read_json(path, limit=METADATA_LIMIT):
    require(path.stat().st_size <= limit, f"JSON input exceeds {limit} bytes: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def runtime_fingerprint(environment):
    """Verify declared hashes before executing either version-only query."""
    checks = environment["checks"]
    fingerprint = {}
    for name in ("ffmpeg", "ffprobe"):
        binary = Path(checks[name]).resolve()
        require(binary.is_file(), f"Runtime executable unavailable: {name}", "not_installed")
        digest = sha256(binary)
        declared = checks.get(name + "_sha256")
        require(isinstance(declared, str) and digest == declared.lower(),
                f"Actual {name} SHA256 differs from the environment declaration", "runtime_hash_mismatch")
        fingerprint[name] = {"path": str(binary), "sha256": digest}
    for name, binary in fingerprint.items():
        try:
            completed = subprocess.run([binary["path"], "-version"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RenderError("runtime_version_failed", f"Cannot query actual {name} version: {exc}") from exc
        version = completed.stdout.strip()
        require(completed.returncode == 0 and version.startswith(name + " version "),
                f"Cannot verify actual {name} version", "runtime_version_failed")
        declared_version = checks.get("version" if name == "ffmpeg" else "ffprobe_version")
        require(declared_version is None or declared_version == version.splitlines()[0],
                f"Actual {name} version differs from the environment declaration", "runtime_version_mismatch")
        binary["version"] = version
    return fingerprint


def resolve_batch_dir(root, batch):
    """Keep every physical batch parent within the fixed render owner tree."""
    root = Path(root).resolve()
    owner = root / "render"
    parent = owner / "benchmarks"
    require(owner.resolve() == owner and parent.resolve() == parent,
            "render/benchmarks parents must not redirect", "unsafe_path")
    batch = Path(batch).resolve()
    require(batch.parent == parent and batch.name.startswith("presets-")
            and all(c.isalnum() or c == "-" for c in batch.name),
            "batch-dir must resolve directly below render/benchmarks as presets-<id>", "unsafe_path")
    return batch


def persist(root, batch, records):
    """Short metadata-only reservation; never held while calling render()."""
    batch = resolve_batch_dir(root, batch)
    for name in records:
        require(Path(name).name == name, "metadata name must be a basename", "unsafe_path")
        require(not (batch / name).exists(), f"Preserve existing metadata: {name}", "output_exists")
    bytes_to_write = sum(len((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
                         for value in records.values())
    with reservation(root, "benchmark-metadata-" + uuid.uuid4().hex[:12], bytes_to_write + 4096):
        require(directory_bytes(batch) + bytes_to_write + 4096 <= METADATA_LIMIT,
                "benchmark metadata would exceed the 2MB batch limit", "quota_exceeded")
        batch.mkdir(parents=True, exist_ok=True)
        for name, value in records.items():
            require(not (batch / name).exists(), f"Preserve existing metadata: {name}", "output_exists")
            atomic_json(batch / name, value)


def source_preflight(base, root):
    """Only the frozen legacy three-clip fixture is accepted; never training data."""
    assets = assets_by_id(base.get("assets"))
    require(len(assets) == 3 and {a["relative_path"] for a in assets.values()} == SOURCE_PATHS,
            "benchmark must use the three legacy general-use source clips")
    segments = base["parameters"]["timeline"]["segments"]
    require(len(segments) == 3 and {s["asset_id"] for s in segments} == set(assets),
            "benchmark fixture must contain exactly one segment for each source")
    require(all(s.get("fit", "contain") == "contain" for s in segments),
            "R-01a benchmark requires contain for every source")
    started = time.perf_counter()
    selected = list(assets.values())
    research_preview = base["parameters"].get("research_preview", False)
    # Reconsult the shared registry on every invocation. Old general-use paths
    # are not permanent permission: actual bytes may have become restricted.
    check_usage(selected, assets, root, research_preview)
    paths = verify_source_bytes(selected, assets, root, lambda: None, research_preview)
    sources = []
    for asset in assets.values():
        path = paths[asset["asset_id"]]
        require(path.relative_to(root).as_posix() in SOURCE_PATHS,
                "source resolves outside its legacy general-use location", "usage_scope_forbidden")
        sources.append({"asset_id": asset["asset_id"], "relative_path": asset["relative_path"],
                        "sha256": asset["sha256"].lower(), "size_bytes": path.stat().st_size,
                        "source_fps": f"{asset['fps_num']}/{asset['fps_den']}"})
    return {"sources": sources, "elapsed_seconds": round(time.perf_counter() - started, 6),
            "cache_note": CACHE_NOTE, "os_cache_flushed": False}


def build_request(base, fps, job):
    result = deepcopy(base)
    result.update(job_id=job, attempt_id="attempt-01", output_dir=f"render/jobs/{job}/attempt-01")
    params = result["parameters"]
    params["export_preset"] = f"portrait_1080p{fps}"
    params["preview"] = False
    # Replace the old 30fps output as a whole; an explicit 60fps preset must not
    # silently disagree with that earlier fixture field.
    params["timeline"]["output"] = resolve_preset({"export_preset": params["export_preset"]})["output"]
    params["timeline"]["timeline_id"] = "benchmark-" + job
    return result


class StageObserver:
    def __init__(self, run_id):
        self.run_id = run_id
        self.started = time.perf_counter()
        self.stages = {}
        self.last_stage = None

    def __call__(self, event):
        elapsed = round(time.perf_counter() - self.started, 6)
        stage = event.get("stage", "unknown")
        item = self.stages.setdefault(stage, {"stage": stage, "event_count": 0,
                                              "first_observed_seconds": elapsed})
        item.update(last_observed_seconds=elapsed, last_event=event)
        item["event_count"] += 1
        if stage != self.last_stage or event.get("event") in {"error", "warning"}:
            log("render_stage", run_id=self.run_id, elapsed_seconds=elapsed, render_event=event)
        self.last_stage = stage


def compact_mapping(mapping):
    keys = ("segment_id", "source_segment_ids", "asset_id", "relative_path", "source_sha256",
            "source_in_ms", "source_out_ms", "speed", "output_in_frame", "output_out_frame",
            "output_in_ms", "output_out_ms", "timing_error_ms", "fit", "crop", "audio_strategy")
    return [{key: segment.get(key) for key in keys} for segment in mapping.get("segments", [])]


def expected_maps(request, fps):
    expected, cursor = [], 0
    for segment in request["parameters"]["timeline"]["segments"]:
        duration = Fraction(segment["out_ms"] - segment["in_ms"], 1000) / Fraction(str(segment.get("speed", 1)))
        frames = max(1, int(duration * fps + Fraction(1, 2)))
        expected.append({"segment_id": segment["segment_id"], "asset_id": segment["asset_id"],
                         "source_in_ms": segment["in_ms"], "source_out_ms": segment["out_ms"],
                         "speed": segment.get("speed", 1), "output_in_frame": cursor,
                         "output_out_frame": cursor + frames})
        cursor += frames
    return expected, cursor


def summarize_run(root, request, result, fps, elapsed, observer, expected_backend="cpu"):
    output = safe_path(root, request["output_dir"])
    qa_path, mapping_path = output / "qa.json", output / "source_map.json"
    qa = read_json(qa_path) if qa_path.is_file() else {}
    mapping = read_json(mapping_path) if mapping_path.is_file() else {}
    mapped = compact_mapping(mapping)
    expected, frames = expected_maps(request, fps)
    timing_path = output / "stage_timings.json"
    timings = qa.get("stage_timings") or (read_json(timing_path) if timing_path.is_file() else [])
    stages = [{key: stage.get(key) for key in ("stage", "elapsed_seconds", "returncode", "log")}
              for stage in timings]
    video_artifact = next((a for a in result.get("artifacts", []) if a.get("kind") == "video/mp4"), None)
    video = next((s for s in qa.get("probe", {}).get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in qa.get("probe", {}).get("streams", []) if s.get("codec_type") == "audio"), {})
    checks = {
        "render_succeeded": result.get("status") == "succeeded",
        "technical_qa": qa.get("technical_pass") is True,
        "full_decode": qa.get("checks", {}).get("full_decode") is True,
        "backend_matches_expected": qa.get("backend", {}).get("effective") == expected_backend,
        "dimensions": video.get("width") == 1080 and video.get("height") == 1920,
        "codecs_and_pixel_format": video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p"
                                   and audio.get("codec_name") == "aac" and audio.get("sample_rate") == "48000",
        "fps": Fraction(video.get("avg_frame_rate", "0")) == fps and Fraction(video.get("r_frame_rate", "0")) == fps,
        "expected_frame_count": int(video.get("nb_frames", -1)) == frames,
        "source_intervals_and_continuous_frame_mapping": len(mapped) == len(expected) and all(
            all(actual.get(key) == value for key, value in wanted.items()) for actual, wanted in zip(mapped, expected)),
        "source_hash_mapping": len(mapped) == len(expected) and all(
            actual.get("source_sha256") == next(a["sha256"] for a in request["assets"] if a["asset_id"] == actual["asset_id"])
            for actual in mapped),
        "quantization_error_within_half_frame": len(mapped) == len(expected) and all(
            isinstance(s.get("timing_error_ms"), (int, float)) and abs(s["timing_error_ms"]) <= 500 / fps + 0.000001 for s in mapped),
        "contain_retained": len(mapped) == len(expected) and all(s.get("fit") == "contain" and s.get("crop") is None for s in mapped),
        "safe_area_not_burned_as_guides": qa.get("preset", {}).get("burn_in_guides") is False,
        "output_duration": abs(qa.get("actual_duration_ms", -1) - frames * 1000 / fps) <= 1000 / fps + 50,
    }
    video_path = safe_path(root, video_artifact["relative_path"]) if video_artifact else None
    checks["output_file_size"] = bool(video_path and video_path.is_file() and video_path.stat().st_size == video_artifact["size_bytes"])
    stage_sum = sum(s.get("elapsed_seconds", 0) for s in stages)
    return {
        "status": result.get("status"), "error": result.get("error"), "technical_status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "engine_qa_checks": qa.get("checks", {}), "elapsed_seconds": round(elapsed, 6),
        "elapsed_includes": "engine startup/probes/source hash checks/encoding/assembly/decode QA/artifact hashing; excludes this summary",
        "output_duration_ms": qa.get("actual_duration_ms"), "expected_duration_ms": frames * 1000 / fps,
        "output_frames": frames, "output_fps": fps, "end_to_end_rtf": round(elapsed / (frames / fps), 6),
        "video_size_bytes": video_artifact.get("size_bytes") if video_artifact else None,
        "video_sha256": video_artifact.get("sha256") if video_artifact else None,
        "video_relative_path": video_artifact.get("relative_path") if video_artifact else None,
        "stage_timings": stages, "other_engine_seconds": round(max(0, elapsed - stage_sum), 6),
        "stage_timing_note": "segment stages combine decode, filters and encode; they are not isolated decoder measurements",
        "observed_progress_stages": list(observer.stages.values()), "mapping": mapped,
        "qa_relative_path": qa_path.relative_to(root).as_posix() if qa_path.is_file() else None,
        "source_map_relative_path": mapping_path.relative_to(root).as_posix() if mapping_path.is_file() else None,
        "backend": qa.get("backend"), "preset": qa.get("preset"), "cache_note": CACHE_NOTE,
        "frame_rate_note": "60fps can duplicate the 30fps sources; it adds no source action detail",
        "human_selection_confirmed": qa.get("human_confirmed_segments", False),
        "visual_review": "pending", "platform_upload_acceptance": "not_tested", "acceptance_case": "R-01a",
        "full_case_status": "NOT_RUN", "remaining_assertion": "independent visual review of safety margins and full match-frame preservation",
    }


def batch_summary(batch, session, plan):
    rows = [read_json(path) for path in sorted(batch.glob("*.summary.json"))]
    by_slot = {row["slot"]: row for row in rows}
    groups = {}
    for fps in (30, 60):
        selected = [r for r in rows if r["fps"] == fps]
        repeats = [r["elapsed_seconds"] for r in selected if r["phase"] == "repeat" and r["technical_status"] == "PASS"]
        groups[str(fps)] = {
            "completed_slots": len(selected), "passing_slots": sum(r["technical_status"] == "PASS" for r in selected),
            "first_observed": next((r["elapsed_seconds"] for r in selected if r["phase"] == "first_observed"), None),
            "repeat_count": len(repeats),
            "repeat_elapsed_seconds": {"min": min(repeats), "median": statistics.median(repeats),
                                        "mean": statistics.mean(repeats), "max": max(repeats)} if repeats else None,
        }
    passing = [row for row in rows if row["technical_status"] == "PASS"]
    source_keys = ("asset_id", "source_sha256", "source_in_ms", "source_out_ms", "speed", "fit", "crop")
    signatures = [[{k: s[k] for k in source_keys} for s in row["mapping"]] for row in passing]
    mapping_consistent = bool(signatures) and all(signature == signatures[0] for signature in signatures)
    complete = len(by_slot) == len(plan)
    return {"schema_version": "1.0", "batch_id": batch.name, "session_id": session, "created_at": utcnow(),
            "backend": "cpu", "planned_slots": len(plan), "completed_slots": len(by_slot),
            "pending_slots": [s["slot"] for s in plan if s["slot"] not in by_slot], "groups": groups,
            "same_source_intervals_across_completed_passing_runs": mapping_consistent,
            "technical_status": "PASS" if complete and len(passing) == len(plan) and mapping_consistent else "FAIL" if any(r["technical_status"] == "FAIL" for r in rows) else "NOT_RUN",
            "run_summaries": [r["summary_file"] for r in rows], "cache_note": CACHE_NOTE,
            "acceptance_case": "R-01a", "full_case_status": "NOT_RUN", "visual_review": "pending",
            "platform_upload_acceptance": "not_tested"}


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("cpu",), default="cpu")
    parser.add_argument("--repeats", type=int, default=3, help="repeat slots after one first-observed slot, per fps (1..10)")
    parser.add_argument("--environment", type=Path, default=REPO_ROOT / "environments/render-runtime.json")
    parser.add_argument("--storage-root", type=Path, default=Path("D:/video" if os.name == "nt" else "/mnt/d/video"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batch-dir", type=Path, help="existing batch to continue, or a new presets-* directory below render/benchmarks")
    args = parser.parse_args()
    require(1 <= args.repeats <= 10 and 1 <= args.threads <= 16, "repeats must be 1..10 and threads 1..16")
    root = args.storage_root.resolve()
    batch = resolve_batch_dir(root, args.batch_dir or root / "render/benchmarks" / ("presets-" + uuid.uuid4().hex[:12]))
    session = uuid.uuid4().hex[:12]
    env = read_json(args.environment)
    base = read_json(REQUEST_PATH)
    # No batch creation or capacity reservation precedes the shared usage gate.
    preflight = source_preflight(base, root)
    runtime = runtime_fingerprint(env)
    cfg = RenderConfig(storage_root=root, ffmpeg=runtime["ffmpeg"]["path"], ffprobe=runtime["ffprobe"]["path"],
                       threads=args.threads, backend="cpu")
    fixture_hash = sha256(REQUEST_PATH)
    plan = [{"slot": f"fps{fps}-{'first' if repeat == 0 else 'repeat'+str(repeat)}", "fps": fps,
             "phase": "first_observed" if repeat == 0 else "repeat", "repeat_index": repeat}
            for fps in (30, 60) for repeat in range(args.repeats + 1)]
    code_files = [Path(__file__), REPO_ROOT / "packages/render/engine.py", REPO_ROOT / "packages/render/presets.py",
                  REPO_ROOT / "packages/render/timeline.py", REPO_ROOT / "packages/render/backends.py",
                  REPO_ROOT / "packages/render/usage.py"]
    config = {"backend": "cpu", "repeats": args.repeats, "threads": args.threads,
              "fixture_sha256": fixture_hash, "ffmpeg": cfg.ffmpeg, "ffprobe": cfg.ffprobe,
              "runtime": runtime,
              "code_sha256": {p.relative_to(REPO_ROOT).as_posix(): sha256(p) for p in code_files}}
    if batch.exists():
        manifest = read_json(batch / "batch.json")
        require(manifest["config"] == config and manifest["plan"] == plan,
                "continuation arguments/source fixture/code/runtime fingerprint differ; start a new batch")
    else:
        manifest = {"schema_version": "1.0", "batch_id": batch.name, "created_at": utcnow(),
                    "config": config, "plan": plan, "metadata_limit_bytes": METADATA_LIMIT,
                    "cache_note": CACHE_NOTE, "original_request": str(REQUEST_PATH),
                    "gpu_execution": "not_implemented", "source_files_copied": False}
        persist(root, batch, {"batch.json": manifest})
    lock = batch / ".benchmark.lock"
    fd = None
    owned_lock = False
    cancelled = False
    def stop(signum, frame):
        nonlocal cancelled
        cancelled = True
    old_handlers = {signum: signal.signal(signum, stop) for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        # This batch-level lock only prevents duplicate orchestrators. It does
        # not reserve render capacity while the engine owns .render.lock.
        with reservation(root, "benchmark-lock-" + session, 4096):
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            owned_lock = True
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = None
                json.dump({"pid": os.getpid(), "session": session, "created_at": utcnow()}, stream)
        persist(root, batch, {f"session-{session}.json": {"created_at": utcnow(), "source_preflight": preflight,
                    "config": config}})
        log("benchmark_start", batch_dir=str(batch), session_id=session, slots=len(plan), cache_note=CACHE_NOTE)
        completed = {read_json(path)["slot"] for path in batch.glob("*.summary.json")}
        for slot in plan:
            if slot["slot"] in completed:
                log("slot_already_completed", slot=slot["slot"])
                continue
            if cancelled:
                break
            run_id = slot["slot"] + "-" + uuid.uuid4().hex[:10]
            job = batch.name + "-" + run_id
            request = build_request(base, slot["fps"], job)
            prior_requests = list(batch.glob(slot["slot"] + "-*.request.json"))
            persist(root, batch, {run_id + ".request.json": request})
            observer = StageObserver(run_id)
            started = time.perf_counter()
            result = render(request, cfg, emit=observer, cancelled=lambda: cancelled)
            elapsed = time.perf_counter() - started
            # Engine reservation is now released. Store results before summary
            # parsing so an unexpected QA shape cannot lose the actual result.
            persist(root, batch, {run_id + ".result.json": result})
            summary = summarize_run(root, request, result, slot["fps"], elapsed, observer)
            summary.update(schema_version="1.0", **slot, run_id=run_id, job_id=job, session_id=session,
                           request_file=run_id + ".request.json", result_file=run_id + ".result.json",
                           summary_file=run_id + ".summary.json", previous_incomplete_attempts=len(prior_requests),
                           first_observed_caveat="retry after an interrupted attempt" if prior_requests else CACHE_NOTE)
            persist(root, batch, {run_id + ".summary.json": summary})
            log("run_complete", run_id=run_id, status=summary["status"], technical_status=summary["technical_status"],
                elapsed_seconds=summary["elapsed_seconds"], video_size_bytes=summary["video_size_bytes"])
            if summary["technical_status"] != "PASS":
                break
        summary = batch_summary(batch, session, plan)
        persist(root, batch, {f"batch-report-{session}.json": summary})
        log("benchmark_complete", batch_dir=str(batch), report=f"batch-report-{session}.json",
            technical_status=summary["technical_status"], completed_slots=summary["completed_slots"])
        return 130 if cancelled else 0 if summary["technical_status"] == "PASS" else 1
    finally:
        if fd is not None:
            os.close(fd)
        if owned_lock:
            lock.unlink()
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(run())
    except (RenderError, OSError, ValueError, KeyError) as exc:
        log("benchmark_error", code=getattr(exc, "code", type(exc).__name__), message=str(exc))
        raise SystemExit(2 if getattr(exc, "status", None) == "blocked" else 1)
