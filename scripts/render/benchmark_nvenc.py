"""Administrator-only benchmark through the existing shared Windows GPU worker.

The coordination note must record the already granted human/module GPU window;
this script cannot infer permission from an idle device. No training assets.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmark_presets import (REQUEST_PATH, StageObserver, build_request, persist,
                               read_json, resolve_batch_dir, runtime_fingerprint,
                               source_preflight, summarize_run, log)
from packages.contracts import JobRequest
from packages.render.storage import sha256, utcnow
from packages.render.timeline import require
from packages.runtime import Queue
from packages.runtime.gpu import GPUCoordinator
from packages.runtime.worker import run_once


def apply_runtime_checks(summary, job, expected_attempt):
    """A successful CLI result cannot override the authoritative worker outcome."""
    summary["runtime_job_status"] = job.get("status")
    summary["runtime_job_attempt"] = job.get("attempt")
    summary["checks"].update(
        runtime_job_succeeded=job.get("status") == "succeeded",
        runtime_attempt_matches=type(job.get("attempt")) is int and job["attempt"] == expected_attempt,
    )
    summary["technical_status"] = "PASS" if all(summary["checks"].values()) else "FAIL"
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordination-note", required=True)
    parser.add_argument("--backend", choices=("cpu", "nvenc"), default="nvenc")
    parser.add_argument("--storage-root", type=Path, default=Path("D:/video"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--environment", type=Path, default=Path("environments/render-runtime.json"))
    args = parser.parse_args()
    require(1 <= args.repeats <= 3, "controlled benchmark repeats must be 1..3")
    require(len(args.coordination_note.strip()) >= 15, "Record explicit models coordination before running")
    root = args.storage_root.resolve()
    base = JobRequest.model_validate(read_json(REQUEST_PATH)).model_dump(mode="json")
    sources = source_preflight(base, root)
    env = read_json(args.environment)
    runtime = runtime_fingerprint(env)
    os.environ.update(BTV_RENDER_BACKEND=args.backend, BTV_STORAGE_ROOT=str(root),
                      BTV_FFMPEG=runtime["ffmpeg"]["path"], BTV_FFPROBE=runtime["ffprobe"]["path"],
                      BTV_RENDER_COMMAND_JSON=json.dumps([sys.executable, "-m", "packages.render"]))
    q = Queue(root / "platform/runtime.sqlite3")
    with q.connection() as db:
        require(db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] == 0,
                "shared queue must be idle; coordinate resident workers first")
    gpu = GPUCoordinator(q.db_path)
    state = gpu.status()
    require(state["lease"] is None and state["active_window"] is None, "GPU ledger must be clear")
    token = uuid.uuid4().hex[:12]
    batch = resolve_batch_dir(root, root / "render/benchmarks" / ("presets-controlled-" + args.backend + "-" + token))
    window_id = "render-benchmark-" + token
    window = None
    rows = []
    persist(root, batch, {"batch.json": dict(schema_version="1.0", backend=args.backend, sources=sources,
        created_at=utcnow(), runtime_db=str(q.db_path), coordination_note=args.coordination_note,
        first_observed_cache="uncontrolled; each source SHA is pre-read; fresh CLI/FFmpeg per job",
        script_sha256=sha256(Path(__file__)),
        renderer_sha256={str(p.relative_to(Path(__file__).resolve().parents[2])).replace('\\', '/'): sha256(p)
                         for p in (Path(__file__).resolve().parents[2]/"packages/render").glob("*.py")},
        runtime=runtime, ffmpeg=env["checks"])})
    try:
        if args.backend == "nvenc":
            window = gpu.grant_window(window_id, ["render-nvenc"], 600, coordination_note=args.coordination_note)
            persist(root, batch, {"window.json": window})
        log("controlled_benchmark_start", batch_dir=str(batch), backend=args.backend, window_id=window_id if window else None)
        for fps in (30, 60):
            for repeat in range(args.repeats + 1):
                slot = f"fps{fps}-{'first' if repeat == 0 else 'repeat'+str(repeat)}"
                request = build_request(base, fps, "pending")
                payload = dict(assets=request["assets"], parameters=request["parameters"], render_backend=args.backend,
                               gpu_required=args.backend == "nvenc")
                if args.backend == "nvenc":
                    payload["model_id"] = "render-nvenc"
                job = q.enqueue("render", payload)
                request.update(job_id=job["job_id"], attempt_id="attempt-1", output_dir=f"render/jobs/{job['job_id']}/attempt-1")
                observer = StageObserver(slot)
                start = time.perf_counter()
                done = run_once(q, str(root), worker_id=window_id, lease_seconds=30)
                elapsed = time.perf_counter()-start
                require(done is not None and done["job_id"] == job["job_id"], "another worker took the queued benchmark job")
                require(gpu.status()["lease"] is None, "worker did not verify stopped compute/release lease")
                result = done.get("result") or dict(status=done["status"], artifacts=[], error=done.get("error"))
                summary = summarize_run(root, request, result, fps, elapsed, observer, expected_backend=args.backend)
                summary["observed_progress_stages"] = None
                summary["progress_collection"] = "Not collected by benchmark observer; full structured events are in the shared Queue job logs"
                summary.update(slot=slot, fps=fps, phase="first_observed" if repeat == 0 else "repeat",
                               repeat_index=repeat, job_id=job["job_id"], output_dir=request["output_dir"],
                               elapsed_includes="same controlled worker + fresh CLI startup + render + result verification")
                apply_runtime_checks(summary, done, expected_attempt=1)
                persist(root, batch, {slot+".request.json":request, slot+".result.json":done, slot+".summary.json":summary})
                rows.append(summary)
                log("controlled_run_complete", slot=slot, status=summary["technical_status"], elapsed_seconds=elapsed,
                    video_size_bytes=summary["video_size_bytes"], output_dir=request["output_dir"])
                require(summary["technical_status"] == "PASS", f"Controlled benchmark failed at {slot}: {done.get('error')}")
    finally:
        state = gpu.status()
        if window and state["lease"] is None:
            gpu.revoke_window(window_id, reason="Every controlled render process stopped and GPU lease released")
        persist(root, batch, {"completion.json": dict(created_at=utcnow(), completed_runs=len(rows),
            status="PASS" if len(rows) == 2*(args.repeats+1) and all(r["technical_status"] == "PASS" for r in rows) else "INCOMPLETE",
            gpu_state_after=gpu.status(), window=gpu.get_window(window_id) if window else None,
            groups={str(fps):dict(first_observed_seconds=next((r["elapsed_seconds"] for r in rows if r["fps"]==fps and r["repeat_index"]==0),None),
                repeats_seconds=[r["elapsed_seconds"] for r in rows if r["fps"]==fps and r["repeat_index"]>0]) for fps in (30,60)})})
        log("controlled_benchmark_finished", batch_dir=str(batch), runs=len(rows), gpu_state=gpu.status())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
