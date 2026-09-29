from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys

from .engine import RenderConfig, render
from .storage import atomic_json
from .timeline import safe_path, require


def resolve_cancel_file(root, relative, environment_file, request):
    if environment_file:
        path = Path(environment_file)
        require(path.is_absolute(), "BTV_RENDER_CANCEL_FILE must be absolute")
        expected = safe_path(root, f"platform/jobs/{request.get('job_id')}/{request.get('attempt_id')}/cancel.request")
        require(path.resolve() == expected, "BTV_RENDER_CANCEL_FILE must match this job/attempt exchange directory")
        return path.resolve()
    path = safe_path(root, relative) if relative else None
    require(not path or path.is_relative_to(root / "render"), "cancel_file must be below render/")
    return path


def main():
    parser = argparse.ArgumentParser(description="badmintonTV renderer (contract 1.0)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--result", type=Path, required=True)
    run.add_argument("--storage-root", type=Path, default=Path(os.environ.get("BTV_STORAGE_ROOT", "D:/video" if os.name == "nt" else "/mnt/d/video")))
    run.add_argument("--ffmpeg", default=os.environ.get("BTV_FFMPEG", "ffmpeg"))
    run.add_argument("--ffprobe", default=os.environ.get("BTV_FFPROBE", "ffprobe"))
    run.add_argument("--threads", type=int, default=4)
    run.add_argument("--backend", choices=("cpu", "nvenc", "auto"), default=os.environ.get("BTV_RENDER_BACKEND", "cpu"))
    run.add_argument("--cancel-file", help="storage-root relative path below render/")
    run.add_argument("--font-name", default="Microsoft YaHei" if os.name == "nt" else "Noto Sans CJK SC")
    args = parser.parse_args()
    cancelled = False
    def stop(signum, frame):
        nonlocal cancelled
        cancelled = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    def emit(event):
        print(json.dumps(event, ensure_ascii=False, allow_nan=False), flush=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    request = None
    try:
        require(not args.result.exists(), "result file already exists; preserve it and choose a new path", "output_exists")
        require(args.request.stat().st_size <= 10_000_000, "request exceeds 10MB")
        request = json.loads(args.request.read_text(encoding="utf-8-sig"))
        root = args.storage_root.resolve()
        cancel_file = resolve_cancel_file(root, args.cancel_file, os.environ.get("BTV_RENDER_CANCEL_FILE"), request)
        cfg = RenderConfig(root, args.ffmpeg, args.ffprobe, args.threads, font_name=args.font_name, cancel_file=cancel_file,
                           backend=args.backend, runtime_db=Path(os.environ["BTV_RUNTIME_DB"]) if os.environ.get("BTV_RUNTIME_DB") else None,
                           gpu_lease_id=os.environ.get("BTV_GPU_LEASE_ID"))
        result = render(request, cfg, emit, lambda: cancelled)
        atomic_json(args.result, result)
        return {"succeeded": 0, "failed": 1, "cancelled": 130, "blocked": 2}[result["status"]]
    except Exception as exc:
        job = request.get("job_id", "unknown") if isinstance(request, dict) else "unknown"
        attempt = request.get("attempt_id", "unknown") if isinstance(request, dict) else "unknown"
        result = dict(schema_version="1.0", job_id=job, attempt_id=attempt, status="failed", artifacts=[], events=[], error=dict(code=getattr(exc,"code","invalid_request"),message=str(exc)))
        emit(dict(schema_version="1.0", job_id=job, seq=1, event="error", stage="request", current=None,total=None,unit=None,message=str(exc)))
        if not args.result.exists():
            atomic_json(args.result, result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
