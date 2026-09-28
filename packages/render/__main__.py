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


def main():
    parser = argparse.ArgumentParser(description="badmintonTV CPU renderer (contract 1.0)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--result", type=Path, required=True)
    run.add_argument("--storage-root", type=Path, default=Path(os.environ.get("BTV_STORAGE_ROOT", "D:/video" if os.name == "nt" else "/mnt/d/video")))
    run.add_argument("--ffmpeg", default=os.environ.get("BTV_FFMPEG", "ffmpeg"))
    run.add_argument("--ffprobe", default=os.environ.get("BTV_FFPROBE", "ffprobe"))
    run.add_argument("--threads", type=int, default=4)
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
        cancel_file = safe_path(root, args.cancel_file) if args.cancel_file else None
        require(not cancel_file or cancel_file.is_relative_to(root / "render"), "cancel_file must be below render/")
        cfg = RenderConfig(root, args.ffmpeg, args.ffprobe, args.threads, font_name=args.font_name, cancel_file=cancel_file)
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
