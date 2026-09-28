"""Instantiate the canonical render request with a real, synthetic CPU clip."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from packages.contracts import Asset, JobRequest, resolve_relative_path, validate_relative_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--ffprobe", required=True, type=Path)
    parser.add_argument("--fixture-id", required=True)
    args = parser.parse_args()
    validate_relative_path(args.fixture_id)
    if "/" in args.fixture_id:
        raise ValueError("fixture-id must be a single path component")
    root = args.storage_root.resolve(strict=True)
    prefix = f"platform/contract-fixtures/{args.fixture_id}"
    destination = resolve_relative_path(root, prefix)
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing fixture directory")
    ffmpeg = args.ffmpeg.resolve(strict=True)
    ffprobe = args.ffprobe.resolve(strict=True)
    # Optional integration command only: importing the contracts package itself
    # has no runtime dependency. Use the same atomic ledger as the platform.
    from packages.runtime.storage import CapacityLedger

    ledger = CapacityLedger(root / "platform" / "runtime.sqlite3", root)
    reservation = ledger.reserve("platform", 32_000_000, job_id=f"fixture-{args.fixture_id}")
    try:
        destination.mkdir(parents=True, exist_ok=False)
        temporary = destination / "source.tmp.mp4"
        source = destination / "source.mp4"
        subprocess.run([
            str(ffmpeg), "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
            "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "4", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-fs", "8000000", "-movflags", "+faststart", str(temporary),
        ], check=True, timeout=60, capture_output=True)
        probe = json.loads(subprocess.run([
            str(ffprobe), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(temporary),
        ], check=True, timeout=15, capture_output=True, text=True).stdout)
        video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        fps = Fraction(video["avg_frame_rate"])
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        asset = Asset(
            asset_id="asset-contract-synthetic", relative_path=f"{prefix}/source.mp4", sha256=digest.hexdigest(),
            size_bytes=temporary.stat().st_size, duration_ms=round(float(probe["format"]["duration"]) * 1000),
            width=video["width"], height=video["height"], fps_num=fps.numerator, fps_den=fps.denominator,
            time_base=video["time_base"], title="合成合同烟测片；非羽毛球识别证据", match_id="match-contract-synthetic",
            source_type="synthetic", acquired_at=datetime.now(timezone.utc),
            rights={"status": "owned", "evidence": "FFmpeg lavfi testsrc2 and sine generated locally", "allowed_uses": ["contract_test"]},
            probe=probe, provenance={"source": "contract_fixture_generator", "synthetic": True},
        )
        request_path = Path(__file__).with_name("render-request.json")
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        payload["job_id"] = f"job-{args.fixture_id}"
        payload["attempt_id"] = "attempt-01"
        payload["output_dir"] = f"render/jobs/job-{args.fixture_id}/attempt-01"
        payload["assets"] = [asset.model_dump(mode="json")]
        request = JobRequest.model_validate(payload)
        temporary.replace(source)
        target = destination / "render-request.json"
        temp_request = target.with_suffix(".json.tmp")
        temp_request.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temp_request.replace(target)
        print(str(target))
    finally:
        # Failed media is deliberately retained for investigation and capacity accounting.
        ledger.release(reservation)


if __name__ == "__main__":
    main()
