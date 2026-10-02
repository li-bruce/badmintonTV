"""Read-only bounded media/PTS verification for training preparation (CPU only)."""
from bisect import bisect_left
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from .protocol import resolve_relative


class SourceError(ValueError):
    pass


def require(value, message):
    if not value:
        raise SourceError(message)


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), "nonfinite JSON")
        return number
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=finite_float,
                          parse_constant=lambda _: (_ for _ in ()).throw(SourceError("nonfinite JSON")))
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise SourceError("invalid JSON structure/encoding") from exc


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def read_json(path, limit=32_000_000):
    require(type(limit) is int and limit > 0, "positive JSON byte limit required")
    with Path(path).open("rb") as stream:
        require(os.fstat(stream.fileno()).st_size <= limit, "JSON exceeds byte limit")
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "JSON grew beyond byte limit")
    return parse_json(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()


def file_identity(info):
    # Windows stat and fstat can expose different ctime semantics (creation vs
    # metadata-change time). Compare the portable identity/size/mtime fields;
    # retain the extra change timestamp on the Linux decoder host.
    return (info.st_dev, info.st_ino, info.st_mtime_ns,
            info.st_ctime_ns if os.name != "nt" else None, info.st_size)


def verify_stream(stream, size, digest):
    """Hash the same regular-file handle the consumer will read."""
    before = os.fstat(stream.fileno())
    require(stat.S_ISREG(before.st_mode) and before.st_size == size, "source size/type mismatch")
    stream.seek(0)
    result, consumed = hashlib.sha256(), 0
    while chunk := stream.read(min(1_048_576, size - consumed + 1)):
        consumed += len(chunk)
        require(consumed <= size, "source grew while hashing")
        result.update(chunk)
    require(file_identity(before) == file_identity(os.fstat(stream.fileno())), "source changed while hashing")
    require(consumed == size and result.hexdigest() == digest, "source SHA256 mismatch")
    stream.seek(0)
    return file_identity(before)


def verified_file(root, reference, maximum):
    """Check exact size/hash and stable file identity; never write the source."""
    require(isinstance(reference, dict), "source reference must be an object")
    require(type(maximum) is int and maximum > 0, "positive source byte bound required")
    size, digest = reference.get("size_bytes"), reference.get("sha256")
    require(type(size) is int and 0 < size <= maximum, "invalid or excessive declared source bytes")
    require(isinstance(digest, str) and len(digest) == 64 and
            all(c in "0123456789abcdef" for c in digest), "invalid source SHA256")
    path = resolve_relative(Path(root), reference.get("relative_path"))
    with path.open("rb") as stream:
        identity = verify_stream(stream, size, digest)
        require(file_identity(path.stat()) == identity, "source path replaced while hashing")
    return path


def verify_asset(root, asset, *, max_source_bytes=2_000_000_000, max_index_bytes=64_000_000):
    """Read every index entry; use actual source PTS, never frame/fps arithmetic."""
    require(isinstance(asset, dict), "asset must be an object")
    require(isinstance(asset.get("asset_id"), str) and asset["asset_id"].strip(), "asset_id required")
    width, height = asset.get("width"), asset.get("height")
    require(type(width) is int and type(height) is int and width > 0 and height > 0
            and width * height <= 3840 * 2160, "invalid or excessive source dimensions")
    source = verified_file(root, asset, max_source_bytes)
    probe = asset.get("probe", {})
    require(isinstance(probe, dict), "PTS probe must be an object")
    index = probe.get("pts_index", {})
    require(isinstance(index, dict), "PTS index reference must be an object")
    require(probe.get("source_sha256") == asset["sha256"] and
            probe.get("source_size_bytes") == asset["size_bytes"], "PTS probe is not bound to source identity")
    require(index.get("complete") is True and index.get("format") == "jsonl", "complete JSONL PTS index required")
    count = index.get("frame_count")
    require(type(count) is int and 0 < count <= 1_000_000, "PTS frame count exceeds bound")
    origin = probe.get("start_pts")
    require(type(origin) is int and -(2**63) <= origin < 2**63, "explicit signed 64-bit stream start_pts required")
    try:
        require(all(isinstance(value, str) and len(value) <= 64 and
                    re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", value)
                    for value in (asset.get("time_base"), index.get("time_base"))), "invalid source time base")
        tb = Fraction(asset["time_base"])
        index_tb = Fraction(index["time_base"])
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        raise SourceError("invalid source time base") from None
    require(tb > 0 and tb == index_tb, "source/index time base mismatch")
    duration = asset.get("duration_ms")
    require(type(duration) is int and duration > 0, "positive source duration required")
    index_path = verified_file(root, index, max_index_bytes)
    pts, times = [], []
    # Recheck the bytes parsed, guarding a replacement after the initial hash.
    parsed_hash = hashlib.sha256()
    with index_path.open("rb") as stream:
        identity = file_identity(os.fstat(stream.fileno()))
        consumed = 0
        for position in range(count + 1):
            line = stream.readline(4097)
            if not line:
                break
            consumed += len(line)
            require(consumed <= index["size_bytes"] and len(line) <= 4096 and position < count,
                    "PTS index work/line bound exceeded")
            parsed_hash.update(line)
            item = parse_json(line)
            require(isinstance(item, dict), "PTS index row must be an object")
            require(type(item.get("frame_index")) is int and item["frame_index"] == position,
                    "PTS frame_index must be consecutive from zero")
            tick = item.get("pts")
            require(type(tick) is int and -(2**63) <= tick < 2**63 and
                    (not pts or tick > pts[-1]), "PTS must be signed 64-bit integer and strictly increasing")
            stamp = (tick - origin) * tb
            require(0 <= stamp < Fraction(duration, 1000), "source PTS outside media duration")
            pts.append(tick)
            times.append(stamp)
        require(identity == file_identity(os.fstat(stream.fileno())) == file_identity(index_path.stat()),
                "PTS index changed while parsing")
    require(len(pts) == count and consumed == index["size_bytes"] and
            parsed_hash.hexdigest() == index["sha256"], "parsed PTS index differs from verified bytes/count")
    return {"asset_id": asset["asset_id"], "source_path": source, "index_path": index_path,
            "source_sha256": asset["sha256"], "index_sha256": index["sha256"],
            "source_size_bytes": asset["size_bytes"],
            "time_base": tb, "origin_pts": origin, "pts": pts, "times": times,
            "duration_ms": duration, "width": asset["width"], "height": asset["height"]}


def plan_window(verified, start_ms, end_ms, *, sample_count=6):
    require(type(start_ms) is int and type(end_ms) is int and
            0 <= start_ms < end_ms <= verified["duration_ms"], "invalid source window")
    require(end_ms - start_ms <= 30_000, "window exceeds 30 second CPU preparation bound")
    require(type(sample_count) is int and 1 <= sample_count <= 32, "sample_count must be 1..32")
    start, end = Fraction(start_ms, 1000), Fraction(end_ms, 1000)
    times = verified["times"]
    left, right = bisect_left(times, start), bisect_left(times, end)
    require(left < right, "window has no source frames")
    selected = []
    missed = []
    for i in range(sample_count):
        target = start + i * (end-start) / sample_count
        pos = bisect_left(times, target)
        if pos >= right or pos in selected:
            missed.append(i)
        else:
            selected.append(pos)
    return {"start_ms": start_ms, "end_ms": end_ms,
            "interval_semantics": "half_open_source_milliseconds",
            "source_frame_count": right-left,
            "first_source_frame_index": left, "last_source_frame_index": right-1,
            "requested_samples": sample_count, "missing_or_duplicate_target_indices": missed,
            "sampling_method": "first original PTS at/after uniform source-time target; no repeated or synthetic frames",
            "frames": [{"frame_index": pos, "pts": verified["pts"][pos],
                        "time_base": str(verified["time_base"]), "stream_start_pts": verified["origin_pts"],
                        "source_ms_rational": str(times[pos] * 1000)} for pos in selected]}


def decode_window(verified, plan):
    """CPU-decode from the rehashed handle, retaining only RGB hashes.

    Bounds are checked between decoded frames; this is not a hard subprocess
    timeout for a codec stalled inside one decode call. Source hashing is outside
    the 60-second decode budget.
    """
    require(isinstance(plan, dict), "frame plan must be an object")
    canonical = plan_window(verified, plan.get("start_ms"), plan.get("end_ms"),
                            sample_count=plan.get("requested_samples"))
    require(all(plan.get(key) == value for key, value in canonical.items()), "frame plan differs from verified PTS window")
    frames = canonical["frames"]
    expected = {row["pts"]: row for row in frames}
    outputs = []
    width, height = verified["width"], verified["height"]
    require(type(width) is int and type(height) is int and width > 0 and height > 0
            and width * height <= 3840 * 2160, "source dimensions exceed CPU bound")
    last_expected = max(expected)
    with Path(verified["source_path"]).open("rb") as source:
        identity = verify_stream(source, verified["source_size_bytes"], verified["source_sha256"])
        import av
        started = time.monotonic()
        with av.open(source, mode="r") as container:
            require(len(container.streams.video) > 0, "source contains no video stream")
            stream = container.streams.video[0]
            require(stream.time_base is not None and Fraction(stream.time_base) == verified["time_base"]
                    and type(stream.start_time) is int and stream.start_time == verified["origin_pts"],
                    "decoded stream origin/time base differs from PTS index")
            container.seek(min(expected), stream=stream, backward=True)
            previous_index = None
            for number, frame in enumerate(container.decode(stream), 1):
                require(number <= 10_000 and time.monotonic()-started <= 60, "CPU decode work bound exceeded")
                require(type(frame.pts) is int and frame.time_base is not None and
                        Fraction(frame.time_base) == verified["time_base"], "decoded frame lacks expected PTS/time base")
                require((frame.width, frame.height) == (width, height), "decoded dimensions changed")
                position = bisect_left(verified["pts"], frame.pts)
                require(position < len(verified["pts"]) and verified["pts"][position] == frame.pts,
                        "decoded PTS absent from complete index")
                require(previous_index is None or position == previous_index + 1,
                        "decoded PTS not consecutive in complete index")
                previous_index = position
                if frame.pts > last_expected:
                    break
                if frame.pts not in expected:
                    continue
                rgb = frame.to_ndarray(format="rgb24")
                require(rgb.shape == (height, width, 3) and str(rgb.dtype) == "uint8"
                        and rgb.nbytes == width * height * 3, "decoded RGB shape/type mismatch")
                raw = rgb.tobytes()
                require(len(raw) == width * height * 3, "decoded RGB byte count mismatch")
                outputs.append({**expected[frame.pts], "rgb_sha256": hashlib.sha256(raw).hexdigest(),
                                "width": frame.width, "height": frame.height, "pixel_format": "rgb24"})
                if len(outputs) == len(expected):
                    break
        require(identity == file_identity(os.fstat(source.fileno())) ==
                file_identity(Path(verified["source_path"]).stat()), "source changed during CPU decode")
    require({r["pts"] for r in outputs} == set(expected), "actual decoder did not produce indexed frames")
    return {"status": "verified", "device": "cpu", "decoder": "PyAV", "av_version": av.__version__,
            "frames": outputs, "images_written": False, "gpu_used": False, "model_run": False}
