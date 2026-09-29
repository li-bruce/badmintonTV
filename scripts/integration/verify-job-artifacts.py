"""Read-only verification of completed jobs; does not run models or claim accuracy."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.contracts import JobRequest, JobResult, resolve_relative_path, validate_job_result


def verify(root: Path, job_id: str, attempt_id: str, require_bridge: bool) -> dict:
    directory = resolve_relative_path(root, f"platform/jobs/{job_id}/{attempt_id}", must_exist=True)
    request = JobRequest.model_validate_json((directory / "request.json").read_text(encoding="utf-8"))
    result = JobResult.model_validate_json((directory / "result.json").read_text(encoding="utf-8"))
    if (request.job_id, request.attempt_id) != (job_id, attempt_id):
        raise ValueError("request identity differs from requested directory")
    if result.status != "succeeded":
        raise ValueError(f"job did not succeed: {result.status}")
    if (result.job_id, result.attempt_id) != (job_id, attempt_id):
        raise ValueError("result identity differs from requested directory")
    bridge_path = directory / "bridge.done.json"
    bridge_verified = False
    if bridge_path.exists():
        bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
        started = json.loads((directory / "bridge.started.json").read_text(encoding="utf-8"))
        for key, value in (("job_id", job_id), ("attempt_id", attempt_id)):
            if bridge.get(key) != value or started.get(key) != value:
                raise ValueError(f"bridge identity mismatch: {key}")
        if not started.get("token") or bridge.get("token") != started["token"]:
            raise ValueError("bridge completion token mismatch")
        if bridge.get("compute_stopped") is not True or bridge.get("reason") != "completed":
            raise ValueError("bridge does not confirm completed/stopped computation")
        validate_job_result(request, result, returncode=bridge["exit_code"])
        bridge_verified = True
    elif require_bridge:
        raise ValueError("required bridge completion evidence is missing")
    artifacts = []
    for artifact in result.artifacts:
        path = resolve_relative_path(root, artifact.relative_path, must_exist=True)
        if not path.is_file() or path.stat().st_size != artifact.size_bytes:
            raise ValueError(f"artifact size/type mismatch: {artifact.relative_path}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != artifact.sha256:
            raise ValueError(f"artifact SHA256 mismatch: {artifact.relative_path}")
        artifacts.append({"kind": artifact.kind, "relative_path": artifact.relative_path,
                          "size_bytes": artifact.size_bytes, "sha256": digest})
    return {"job_id": job_id, "attempt_id": attempt_id, "status": "PASS",
            "model_id": request.parameters.get("model_id"), "events_count": len(result.events),
            "bridge_completion_verified": bridge_verified, "artifacts": artifacts,
            "model_accuracy_verified": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", default="D:/video")
    parser.add_argument("--job-id", action="append", required=True)
    parser.add_argument("--attempt-id", default="attempt-1")
    parser.add_argument("--require-bridge", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional new JSON receipt; existing files are not overwritten")
    args = parser.parse_args()
    receipt = {"schema_version": "1.0", "verified_at": datetime.now(timezone.utc).isoformat(),
               "scope": "Saved contracts, artifact bytes and optional bridge completion; not inference quality",
               "jobs": [verify(Path(args.storage_root), job, args.attempt_id, args.require_bridge)
                        for job in args.job_id]}
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
    print(encoded)


if __name__ == "__main__":
    main()
