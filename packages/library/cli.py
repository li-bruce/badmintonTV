"""Small standard-library CLI for source acquisition and verification."""

import argparse
from contextlib import contextmanager
import dataclasses
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from .download import download
from .manifest import SplitRegistry, safe_asset_path, sha256_file, write_manifest
from .probe import probe_video
from .storage import QuotaManager


MAX_JSON_BYTES = 10_000_000
MANIFEST_PEAK_BYTES = 5 * MAX_JSON_BYTES
AUDIT_MAX_BYTES = 64_000


@contextmanager
def publication_audit(paths, quota, *, reason, charge=None):
    """Retain bounded before/after records when replacing mutable handoff files.

    The caller must already hold capacity for both records. A killed process
    leaves its started record, including hashes before any replacement.
    """
    paths = [quota.resolve_path(Path(path).relative_to(quota.data_root)) for path in paths]
    def snapshot():
        return [{"relative_path": path.relative_to(quota.project_root).as_posix(),
                 "sha256": sha256_file(path) if path.exists() else None,
                 "size_bytes": path.stat().st_size if path.exists() else None} for path in paths]
    previous = snapshot()
    if not any(item["sha256"] for item in previous):
        yield
        return
    audit_id = uuid.uuid4().hex
    def record(stage, value):
        value.update({"schema_version": "1.0", "audit_id": audit_id,
                      "created_at": datetime.now(timezone.utc).isoformat(), "reason": reason})
        payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if len(payload) > AUDIT_MAX_BYTES:
            raise ValueError("Publication audit exceeds bounded allowance")
        if charge:
            charge(len(payload))
        target = quota.resolve_path(f"handoff/audit/{audit_id}.{stage}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    record("started", {"state": "started", "before": previous})
    state = "failed"
    try:
        yield
        state = "succeeded"
    finally:
        record("completed", {"state": state, "before": previous, "after": snapshot()})


def read_json_bounded(path, max_bytes=MAX_JSON_BYTES):
    with Path(path).open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"JSON input exceeds {max_bytes} bytes")
    return json.loads(raw.decode("utf-8-sig"))


def manifest_output_path(output, quota):
    path = Path(output)
    if path.is_absolute():
        try:
            path = path.relative_to(quota.data_root)
        except ValueError:
            raise ValueError("Manifest output must be inside data/handoff") from None
    resolved = quota.resolve_path(path)
    relative = resolved.relative_to(quota.data_root)
    if (len(relative.parts) != 2 or relative.parts[0].lower() != "handoff"
            or relative.suffix.lower() != ".json"
            or relative.name.lower() == "splits.v1.json"):
        raise ValueError("Manifest output must be data/handoff/*.json, excluding splits.v1.json")
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    acquire = commands.add_parser("download", help="Download one bounded public source")
    acquire.add_argument("url")
    acquire.add_argument("relative_path", help="Relative to D:/video/data")
    acquire.add_argument("--max-bytes", type=int, required=True)
    acquire.add_argument("--peak-bytes", type=int)
    acquire.add_argument("--sha256")
    commands.add_parser("quota", help="Read owner usage and persistent reservations")
    probe = commands.add_parser("probe", help="Probe and fully decode a downloaded video")
    probe.add_argument("relative_path", help="Relative to D:/video")
    probe.add_argument("--ffprobe", default="ffprobe")
    probe.add_argument("--ffmpeg", default="ffmpeg")
    asset = commands.add_parser("manifest", help="Validate Asset objects and export a manifest")
    asset.add_argument("input", help="JSON object with assets array")
    asset.add_argument("output", help="data-owner-relative handoff/*.json or absolute data/handoff/*.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "download":
            result = download(args.url, args.relative_path, quota=QuotaManager(),
                              max_bytes=args.max_bytes, peak_bytes=args.peak_bytes,
                              expected_sha256=args.sha256)
            payload = dataclasses.asdict(result)
        elif args.command == "quota":
            payload = QuotaManager().snapshot()
        elif args.command == "probe":
            source = safe_asset_path(args.relative_path, "D:/video")
            payload = probe_video(source, ffprobe=args.ffprobe, ffmpeg=args.ffmpeg)
        else:
            data = read_json_bounded(args.input)
            if not isinstance(data, dict) or data.get("schema_version") != "1.0" or not isinstance(data.get("assets"), list):
                raise ValueError("Input must be a v1.0 manifest with an assets array")
            quota = QuotaManager()
            output = manifest_output_path(args.output, quota)
            registry_path = quota.resolve_path("handoff/splits.v1.json")
            for entry in data["assets"]:
                if output == safe_asset_path(entry["relative_path"], quota.project_root):
                    raise ValueError("Manifest output cannot replace an original asset")
                pts = entry.get("probe", {}).get("pts_index")
                if pts and output == safe_asset_path(pts["relative_path"], quota.project_root):
                    raise ValueError("Manifest output cannot replace a PTS index")
            # Both new files are capped at 10 MB. Fifty MB covers their full
            # temporary/final serialization plus locks and ledger growth.
            with quota.reserve(MANIFEST_PEAK_BYTES, purpose="bounded manifest and split registry publication"):
                with publication_audit([output, registry_path], quota, reason="CLI manifest regeneration"):
                    write_manifest(output, data["assets"], storage_root=quota.project_root,
                                   registry=SplitRegistry(registry_path, max_bytes=MAX_JSON_BYTES),
                                   max_bytes=MAX_JSON_BYTES)
            payload = {"status": "verified", "path": str(output)}
        print(json.dumps(payload, ensure_ascii=True, default=str))
        return 0
    except (Exception,) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__,
                          "message": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
