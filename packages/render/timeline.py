"""Pure timeline validation and explicit editorial operations."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import math
from pathlib import Path, PurePosixPath


class RenderError(Exception):
    def __init__(self, code, message, status="failed"):
        super().__init__(message)
        self.code, self.status = code, status


def require(ok, message, code="invalid_request"):
    if not ok:
        raise RenderError(code, message)


def integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, f"{name} must be an integer >= {minimum}")
    return value


def text(value, name, limit=500):
    require(isinstance(value, str) and len(value) <= limit, f"{name} must be text <= {limit} characters")
    require(not any(ord(c) < 32 and c not in "\n\t" for c in value), f"{name} contains control characters")
    return value


def safe_path(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "relative_path must be a POSIX relative path", "unsafe_path")
    p = PurePosixPath(relative)
    require(not any(ord(c) < 32 or c in '*?"<>|' for c in relative), "unsafe path character", "unsafe_path")
    devices = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}
    require(all(not part.endswith((" ",".")) and part.split(".")[0].upper() not in devices for part in relative.split("/")), "noncanonical Windows path", "unsafe_path")
    require(not p.is_absolute() and all(x not in ("..", ".", "") for x in relative.split("/")),
            "relative_path contains traversal", "unsafe_path")
    result = (root / Path(*p.parts)).resolve()
    require(result.is_relative_to(root.resolve()), "path escapes storage root", "unsafe_path")
    return result


def assets_by_id(raw):
    if isinstance(raw, dict):
        if "assets" in raw:
            raw = raw["assets"]
        else:
            require(all(isinstance(v, dict) and k == v.get("asset_id") for k, v in raw.items()),
                    "assets mapping keys must match asset_id")
            raw = list(raw.values())
    require(isinstance(raw, list) and raw, "assets must be a non-empty list or asset_id mapping")
    result = {}
    for asset in raw:
        require(isinstance(asset, dict), "Asset must be an object")
        aid = text(asset.get("asset_id"), "asset_id", 200)
        require(aid and aid not in result, "asset_id missing or duplicated")
        require(asset.get("schema_version") == "1.0", "Asset schema_version must be 1.0")
        integer(asset.get("duration_ms"), "duration_ms", 1)
        integer(asset.get("size_bytes"), "size_bytes", 1)
        integer(asset.get("width"), "width", 1)
        integer(asset.get("height"), "height", 1)
        integer(asset.get("fps_num"), "fps_num", 1)
        integer(asset.get("fps_den"), "fps_den", 1)
        sha = asset.get("sha256")
        require(isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdefABCDEF" for c in sha),
                "Asset sha256 must contain 64 hex characters")
        require(asset.get("source_type") in ("broadcast", "personal", "dataset", "synthetic"),
                "invalid Asset source_type")
        result[aid] = deepcopy(asset)
    return result


def _review_input(segment):
    return {key: deepcopy(segment.get(key)) for key in
            ("segment_id", "asset_id", "in_ms", "out_ms", "review_status", "editorial_review")}


def _input_human_confirmed(item):
    if not isinstance(item, dict):
        return False
    provenance = item.get("editorial_review") or {}
    if not isinstance(provenance, dict) or item.get("review_status") != "confirmed" or provenance.get("reviewer_type") != "human":
        return False
    # Preserve conservative provenance when a previously merged project is reopened.
    inputs = provenance.get("inputs")
    return inputs is None or (isinstance(inputs, list) and bool(inputs) and
                              all(_input_human_confirmed(source) for source in inputs))


def _aggregate_review(kept, incoming):
    inputs = deepcopy(kept["review_inputs"] + incoming["review_inputs"])
    kept["review_inputs"] = inputs
    kept["review_status"] = "confirmed" if all(s["review_status"] == "confirmed" for s in inputs) else "unreviewed"
    actors = {(s.get("editorial_review") or {}).get("reviewer_type", "unknown") for s in inputs}
    kept["editorial_review"] = {
        "reviewer_type": next(iter(actors)) if len(actors) == 1 else "mixed",
        "aggregation": "all_input_segments",
        "inputs": inputs,
    }


def selection_review_summary(segments):
    """Human confirmation covers every contributing interval, never just the first."""
    return {
        "human_confirmed_segments": bool(segments) and all(
            s.get("review_status") == "confirmed" and bool(s.get("review_inputs", [_review_input(s)])) and all(
                _input_human_confirmed(item) for item in s.get("review_inputs", [_review_input(s)]))
            for s in segments),
        "selection_review": [dict(segment_id=s["segment_id"], review_status=s["review_status"],
                                  provenance=deepcopy(s.get("editorial_review", {})),
                                  inputs=deepcopy(s.get("review_inputs", [_review_input(s)]))) for s in segments],
    }


def export_timeline(timeline):
    """Keep the reusable project independent of the current preview resolution."""
    canonical = {key: deepcopy(timeline[key]) for key in
                 ("schema_version", "timeline_id", "title", "output") if key in timeline}
    fields = ("segment_id", "asset_id", "in_ms", "out_ms", "speed", "event_ids", "fit", "crop", "title", "audio", "review_status")
    canonical["segments"] = [{key: deepcopy(s[key]) for key in fields if key in s} for s in timeline["segments"]]
    return canonical


def normalize_timeline(timeline, assets, *, merge_overlaps=False, deduplicate_replays=False, preview=False, research_preview=False):
    require(isinstance(timeline, dict) and timeline.get("schema_version") == "1.0", "Timeline schema_version must be 1.0")
    t = deepcopy(timeline)
    require(text(t.get("timeline_id"), "timeline_id", 200), "timeline_id is required")
    text(t.get("title", ""), "title", 100)
    out = t.get("output", {})
    require(isinstance(out, dict), "output must be an object")
    out = {"width": 1080, "height": 1920, "fps": 30, "video_codec": "h264", "audio_codec": "aac", **out}
    require(out["width"] == 1080 and out["height"] == 1920, "v1 export requires 1080x1920")
    require(type(out["fps"]) in (int, float) and out["fps"] in (24, 25, 30, 50, 60), "unsupported output fps")
    out["fps"] = int(out["fps"])
    require(out["video_codec"] == "h264" and out["audio_codec"] == "aac", "v1 requires h264/aac")
    effective_output = {**out, "width": 360, "height": 640} if preview else deepcopy(out)
    t["output"] = out
    segments = t.get("segments")
    require(isinstance(segments, list) and 1 <= len(segments) <= 200, "Timeline requires 1..200 segments")
    ids, checked = set(), []
    for s in segments:
        require(isinstance(s, dict), "segment must be an object")
        sid = text(s.get("segment_id"), "segment_id", 200)
        require(sid and sid not in ids, "segment_id missing or duplicated")
        ids.add(sid)
        require(s.get("asset_id") in assets, "unknown asset_id", "unknown_asset")
        a = assets[s["asset_id"]]
        start, end = integer(s.get("in_ms"), "in_ms"), integer(s.get("out_ms"), "out_ms", 1)
        require(start < end <= a["duration_ms"], "segment boundary exceeds Asset duration", "invalid_boundary")
        speed = s.setdefault("speed", 1.0)
        require(type(speed) in (int, float) and math.isfinite(speed) and 0.125 <= speed <= 8,
                "supported speed is 0.125..8")
        require(s.get("review_status") == "confirmed" or (research_preview and s.get("review_status") == "unreviewed"), "render requires confirmed segments (or explicit research_preview)", "review_required")
        require(isinstance(s.get("editorial_review", {}), dict), "editorial_review must be an object")
        require(isinstance(s.get("editorial_review", {}).get("reviewer_type", "unknown"), str), "reviewer_type must be text")
        require(s.setdefault("audio", "source") in ("source", "mute"), "invalid audio strategy")
        require(s.setdefault("fit", "contain") in ("contain", "crop"), "invalid fit")
        text(s.setdefault("title", ""), "segment title", 100)
        events = s.setdefault("event_ids", [])
        require(isinstance(events, list) and all(isinstance(e, str) for e in events), "event_ids must be text list")
        if s["fit"] == "crop":
            crop = s.get("crop")
            require(isinstance(crop, dict), "crop requires an explicit source pixel window")
            for key in ("x", "y", "width", "height"):
                value = crop.get(key)
                require(type(value) in (int,float) and math.isfinite(value) and 0 <= value <= 1, f"crop.{key} must be normalized 0..1")
            require(crop["width"] > 0 and crop["height"] > 0, "crop dimensions must be positive")
            require(crop["x"] + crop["width"] <= 1 and crop["y"] + crop["height"] <= 1,
                    "crop exceeds source dimensions")
        duration = Fraction(end-start, 1000) / Fraction(str(speed))
        frames = max(1, int(duration * out["fps"] + Fraction(1, 2)))
        s["output_frames"] = frames
        s["output_duration_ms"] = round(frames * 1000 / out["fps"], 6)
        subtitles = s.setdefault("subtitles", [])
        require(isinstance(subtitles, list) and len(subtitles) <= 200, "invalid subtitles")
        for sub in subtitles:
            require(isinstance(sub, dict), "subtitle must be an object")
            lo, hi = integer(sub.get("start_ms"), "subtitle start"), integer(sub.get("end_ms"), "subtitle end", 1)
            require(lo < hi <= s["output_duration_ms"] + 0.01, "subtitle exceeds output segment")
            text(sub.get("text"), "subtitle text", 500)
        if "replay_group_id" in s:
            require(text(s["replay_group_id"], "replay_group_id", 200), "empty replay_group_id")
        s["source_segment_ids"] = [sid]
        s["review_inputs"] = [_review_input(s)]
        checked.append(s)

    original_segments = deepcopy(checked)
    excluded, groups, normalized = [], {}, []
    for s in checked:
        group = s.get("replay_group_id")
        if deduplicate_replays and group and group in groups:
            kept = groups[group]
            kept["event_ids"] = list(dict.fromkeys(kept["event_ids"] + s["event_ids"]))
            _aggregate_review(kept, s)
            excluded.append({"reason": "explicit_replay_group", "kept_segment_id": kept["segment_id"], "segment": s})
            continue
        if group:
            groups[group] = s
        prev = normalized[-1] if normalized else None
        keys = ("asset_id", "speed", "audio", "fit", "crop", "title", "replay_group_id")
        if merge_overlaps and prev and all(prev.get(k) == s.get(k) for k in keys) and not prev["subtitles"] and not s["subtitles"] and s["in_ms"] <= prev["out_ms"] and s["out_ms"] >= prev["in_ms"]:
            _aggregate_review(prev, s)
            prev["in_ms"] = min(prev["in_ms"], s["in_ms"])
            prev["out_ms"] = max(prev["out_ms"], s["out_ms"])
            prev["source_segment_ids"] += s["source_segment_ids"]
            prev["event_ids"] = list(dict.fromkeys(prev["event_ids"] + s["event_ids"]))
            frames = max(1, int(Fraction(prev["out_ms"]-prev["in_ms"], 1000) / Fraction(str(prev["speed"])) * out["fps"] + Fraction(1, 2)))
            prev["output_frames"] = frames
            prev["output_duration_ms"] = round(frames * 1000 / out["fps"], 6)
            if group:
                groups[group] = prev
        else:
            normalized.append(s)
    t["segments"] = normalized
    t["render_metadata"] = {"preview": preview, "effective_output": effective_output, "research_preview": research_preview, "excluded_replays": excluded, "input_segments": original_segments,
                            "merge_overlaps": merge_overlaps, "deduplicate_replays": deduplicate_replays}
    return t
