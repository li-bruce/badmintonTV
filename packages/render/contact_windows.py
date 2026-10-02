"""Training-only source windows. No media decoder, Timeline, or filesystem writes.

The core operates on an explicit current-revision view; the CLI verifies the
existing source/PTS bytes. This adapter does not define the shared snapshot
contract and never promotes annotations to human truth.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

from .timeline import RenderError

FORMAT = "badmintonTV.training-contact-windows"
RULE_VERSION = "contact-windows/1.0.1"
PHASE_ORDER = ("preparation", "initiation", "arrival", "stroke_support", "landing", "recovery")
PHASES = set(PHASE_ORDER)
DEFAULT_RULES = dict(hand_before_ms=500, hand_after_ms=500, footwork_before_ms=2000,
                     footwork_after_ms=2000, rally_before_ms=0, rally_after_ms=0)
POINTS = {"contact", "serve", "dead_ball"}


class WindowError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def check(condition, message, code="invalid_window_input"):
    if not condition:
        raise WindowError(code, message)


def integer(value, name, minimum=0):
    check(type(value) is int and value >= minimum, f"{name} must be an integer >= {minimum}")
    return value


def identifier(value, name):
    check(isinstance(value, str) and value.strip() and len(value) <= 200
          and not any(ord(c) < 32 for c in value), f"{name} must be nonempty text")
    return value


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class SourceClock:
    """Display-order integer source PTS; time zero is explicit, never frame/fps."""
    def __init__(self, pts, time_base, origin_pts=None, reference=None):
        self.pts = tuple(pts)
        check(self.pts and len(self.pts) <= 5_000_000 and all(type(p) is int for p in self.pts), "PTS must be a bounded integer sequence", "invalid_pts")
        check(all(a < b for a, b in zip(self.pts, self.pts[1:])), "PTS must strictly increase", "invalid_pts")
        try:
            self.time_base = Fraction(time_base)
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            raise WindowError("invalid_pts", "Invalid source time_base") from exc
        check(self.time_base > 0, "time_base must be positive", "invalid_pts")
        self.origin_pts = self.pts[0] if origin_pts is None else origin_pts
        check(type(self.origin_pts) is int and self.origin_pts <= self.pts[0], "Invalid source origin PTS", "invalid_pts")
        self.reference = deepcopy(reference or {})

    def time_ms(self, pts):
        return (pts - self.origin_pts) * self.time_base * 1000

    def select(self, start_ms, end_ms):
        # Integer PTS and rational thresholds avoid rounding at a half-open end.
        first = bisect_left(self.pts, self.origin_pts + Fraction(start_ms, 1000) / self.time_base)
        end = bisect_left(self.pts, self.origin_pts + Fraction(end_ms, 1000) / self.time_base)
        return dict(status="mapped", time_base=str(self.time_base), origin_pts=self.origin_pts,
                    first_frame_index=first, end_frame_index_exclusive=end, frame_count=end-first,
                    first_pts=self.pts[first] if first < end else None,
                    last_pts=self.pts[end-1] if first < end else None,
                    next_pts=self.pts[end] if end < len(self.pts) else None,
                    reference=deepcopy(self.reference), selection="start_ms <= source_time_ms < end_ms")


def bounds(record):
    uncertainty = record.get("uncertainty")
    if uncertainty:
        return uncertainty["start_ms"], uncertainty["end_ms"]
    return record["time_ms"], record["time_ms"]


def evidence_end(record):
    """Declared source evidence participates in the causal watermark too."""
    times = []
    if record.get("latest_evidence_ms") is not None:
        times.append(integer(record["latest_evidence_ms"], "latest_evidence_ms"))
    evidence = record.get("evidence", [])
    check(isinstance(evidence, list), "evidence must be a list")
    for item in evidence:
        check(isinstance(item, dict), "Evidence must be an object")
        check(item.get("asset_id", record["asset_id"]) == record["asset_id"], "Cross-source evidence needs an explicit clock adapter", "relation_mismatch")
        point_times = [integer(item[key], "evidence." + key)
                       for key in ("time_ms", "at_ms") if key in item]
        check(len(set(point_times)) <= 1, "Evidence point-time aliases conflict", "invalid_boundary")
        has_interval = "start_ms" in item or "end_ms" in item
        if has_interval:
            check("start_ms" in item and "end_ms" in item,
                  "Evidence interval requires both endpoints", "invalid_boundary")
            start = integer(item["start_ms"], "evidence.start_ms")
            end = integer(item["end_ms"], "evidence.end_ms")
            check(start < end, "Invalid evidence half-open range", "invalid_boundary")
            check(all(start <= point < end for point in point_times),
                  "Evidence point lies outside its half-open interval", "invalid_boundary")
            times.append(end)
        times.extend(point_times)
        if not has_interval and not point_times:
            check(record.get("latest_evidence_ms") is not None,
                  "Evidence without source times requires latest_evidence_ms", "unknown_evidence_time")
    return max(times, default=0)


def _bound_frame_evidence(record, clock, duration):
    evidence = record.get("evidence", [])
    check(isinstance(evidence, list), "evidence must be a list")
    for item in evidence:
        check(isinstance(item, dict), "Evidence must be an object")
        frame = item.get("source_frame_index", item.get("frame_index"))
        pts = item.get("source_pts")
        check(not ("source_frame_index" in item and "frame_index" in item)
              or item["source_frame_index"] == item["frame_index"], "Evidence frame-index aliases conflict", "invalid_pts")
        if frame is None and pts is None:
            continue
        if frame is not None:
            integer(frame, "evidence.source_frame_index")
        if pts is not None:
            check(type(pts) is int, "Evidence PTS must be integer", "invalid_pts")
        if clock is None:
            record["latest_evidence_ms"] = duration
            record["evidence_time_status"] = "unresolved_bounded_by_source_duration"
            continue
        if frame is not None:
            check(frame < len(clock.pts), "Evidence frame is outside source index", "invalid_pts")
            check(pts is None or clock.pts[frame] == pts, "Evidence frame/PTS conflict", "invalid_pts")
            pts = clock.pts[frame]
        index = bisect_left(clock.pts, pts)
        check(index < len(clock.pts) and clock.pts[index] == pts, "Evidence PTS not in source index", "invalid_pts")
        ms = clock.time_ms(pts)
        for key in ("time_ms", "at_ms"):
            if item.get(key) is not None:
                check(abs(integer(item[key], "evidence."+key)-ms) <= 1, "Evidence time/PTS conflict", "invalid_pts")
        if "end_ms" in item:
            check(item.get("start_ms", 0) <= ms < item["end_ms"], "Evidence PTS outside its half-open interval", "invalid_pts")
        record["latest_evidence_ms"] = max(record.get("latest_evidence_ms", 0), math.ceil(ms))


def _validate(asset, records, clock):
    from packages.contracts import Asset
    try:
        asset = Asset.model_validate(asset).model_dump(mode="json")
        # Also reject NaN and non-JSON side information before deriving hashes.
        content_hash(records)
    except (ValueError, TypeError) as exc:
        raise WindowError("invalid_window_input", str(exc)) from exc
    duration = integer(asset["duration_ms"], "duration_ms", 1)
    check(isinstance(records, list) and 1 <= len(records) <= 10000, "Expected 1..10000 current annotation records")
    records = deepcopy(records)
    by_id, rallies = {}, {}
    for r in records:
        check(isinstance(r, dict), "Record must be an object")
        rid = identifier(r.get("record_id"), "record_id")
        check(rid not in by_id, "Duplicate record_id/current revision", "revision_conflict")
        integer(r.get("revision"), "revision", 1)
        check(r.get("asset_id") == asset["asset_id"], "Cross-asset record", "relation_mismatch")
        identifier(r.get("rally_id"), "rally_id")
        for field in ("player_id", "team_id"):
            if r.get(field) is not None:
                identifier(r[field], field)
        kind = r.get("kind")
        check(kind in POINTS | {"rally", "movement"}, "Unsupported annotation kind")
        _bound_frame_evidence(r, clock, duration)
        check(evidence_end(r) <= duration, "Evidence exceeds media", "invalid_boundary")
        if kind in POINTS:
            check("start_ms" not in r and "end_ms" not in r, "Point must not masquerade as an interval")
            t = integer(r.get("time_ms"), "time_ms")
            check(t <= duration if kind == "dead_ball" else t < duration, "Point outside media", "invalid_boundary")
            if r.get("uncertainty") is not None:
                u = r["uncertainty"]
                check(isinstance(u, dict) and set(u) == {"start_ms", "end_ms"}, "Invalid point uncertainty")
                lo, hi = integer(u["start_ms"], "uncertainty.start_ms"), integer(u["end_ms"], "uncertainty.end_ms")
                check(lo <= t <= hi <= duration, "Invalid point uncertainty envelope", "invalid_boundary")
            if r.get("source_pts") is not None:
                p = r["source_pts"]
                check(type(p) is int, "source_pts must be integer", "invalid_pts")
                if clock:
                    index = bisect_left(clock.pts, p)
                    check(index < len(clock.pts) and clock.pts[index] == p
                          and abs(clock.time_ms(p) - t) <= 1, "Mark PTS does not match source time", "invalid_pts")
            na = r.get("phase_not_applicable", [])
            check(isinstance(na, list) and all(isinstance(p, str) and p in PHASES for p in na)
                  and len(na) == len(set(na)), "Invalid explicit not-applicable phases")
        else:
            check("time_ms" not in r and "uncertainty" not in r, "Interval must not masquerade as a point")
            start = integer(r.get("start_ms"), "start_ms")
            end = r.get("end_ms")
            r["end_ms"] = end
            check(start < duration, "Interval starts outside media", "invalid_boundary")
            if end is not None:
                integer(end, "end_ms", 1)
                check(start < end <= duration, "Invalid interval boundary", "invalid_boundary")
            if kind == "rally":
                check(rid == r["rally_id"], "Rally record_id must match rally_id", "relation_mismatch")
                rallies[rid] = r
            else:
                check(end is not None, "Movement requires an interval", "invalid_boundary")
                identifier(r.get("anchor_id"), "anchor_id")
                identifier(r.get("player_id"), "movement.player_id")
                check(r.get("phase") in PHASES | {"unknown"}, "Unsupported movement phase")
        by_id[rid] = r
    ordered = sorted(rallies.values(), key=lambda r: (r["start_ms"], r["record_id"]))
    caps = {}
    for i, rally in enumerate(ordered):
        next_start = ordered[i+1]["start_ms"] if i+1 < len(ordered) else duration
        check(i == 0 or rally["start_ms"] > ordered[i-1]["start_ms"], "Ambiguous rally starts", "invalid_boundary")
        check(rally["end_ms"] is None or rally["end_ms"] <= next_start, "Rallies overlap", "invalid_boundary")
        caps[rally["record_id"]] = rally["end_ms"] if rally["end_ms"] is not None else next_start
    for r in records:
        check(r["rally_id"] in rallies, "Missing referenced rally", "relation_mismatch")
        rally, cap = rallies[r["rally_id"]], caps[r["rally_id"]]
        if r["kind"] in POINTS:
            lo, hi = bounds(r)
            check(rally["start_ms"] <= lo <= hi <= cap and
                  (r["kind"] == "dead_ball" or r["time_ms"] < cap), "Point/uncertainty crosses rally boundary", "invalid_boundary")
        if r["kind"] == "movement":
            a = by_id.get(r["anchor_id"])
            check(a is not None and a["kind"] in {"contact", "serve"}
                  and a["rally_id"] == r["rally_id"] and a.get("player_id") == r["player_id"],
                  "Movement anchor must match rally and player", "relation_mismatch")
            check(r["phase"] not in a.get("phase_not_applicable", []), "Phase is both annotated and not applicable", "relation_mismatch")
            check(rally["start_ms"] <= r["start_ms"] < r["end_ms"] <= cap,
                  "Movement crosses rally boundary", "invalid_boundary")
    for rally_id in rallies:
        terminal_times = [r["time_ms"] for r in records if r["rally_id"] == rally_id and r["kind"] == "dead_ball"]
        contacts = [r for r in records if r["rally_id"] == rally_id and r["kind"] in {"serve", "contact"}]
        check(not terminal_times or all(r["time_ms"] < min(terminal_times) for r in contacts),
              "Contact must precede the rally dead-ball mark", "invalid_boundary")
    if clock:
        check(asset.get("time_base") is None or Fraction(asset["time_base"]) == clock.time_base,
              "Asset and PTS time bases differ", "invalid_pts")
        check(clock.time_ms(clock.pts[-1]) < duration, "PTS index exceeds media duration", "invalid_pts")
    return asset, sorted(records, key=lambda r: r["record_id"]), rallies


def derive_contact_windows(asset, records, *, project_id, vocabulary_version, rules=None,
                           clock=None, available_until_ms=None):
    """Return a deterministic training-window manifest; inputs remain unchanged.

    Optional cutoff filters records BEFORE derivation. It is a source-time
    evidence watermark, not an annotation creation timestamp or live detector.
    """
    identifier(project_id, "project_id")
    identifier(vocabulary_version, "vocabulary_version")
    check(rules is None or isinstance(rules, dict), "rules must be an object")
    check(set(rules or {}) <= set(DEFAULT_RULES), "Unknown rule parameter")
    config = {**DEFAULT_RULES, **(rules or {})}
    for key, value in config.items():
        check(integer(value, key) <= 10000, "Context exceeds 10000ms")
    check(clock is None or isinstance(clock, SourceClock), "Invalid SourceClock")
    asset, all_records, rallies = _validate(asset, records, clock)
    if available_until_ms is not None:
        integer(available_until_ms, "available_until_ms")
        check(available_until_ms <= asset["duration_ms"], "Watermark outside media", "invalid_boundary")
    # Do not consult future contact identity/labels/revision to choose a range.
    visible = []
    for r in all_records:
        latest = max(evidence_end(r), bounds(r)[1] if r["kind"] in POINTS else r["start_ms"] if r["kind"] == "rally" else r["end_ms"])
        if available_until_ms is None or latest <= available_until_ms:
            copy = deepcopy(r)
            if r["kind"] == "rally" and available_until_ms is not None and (r["end_ms"] is None or r["end_ms"] > available_until_ms):
                copy["end_ms"] = None
            visible.append(copy)
    active_rallies = {r["record_id"]: r for r in visible if r["kind"] == "rally"}
    by_rally = {rid: [r for r in visible if r["rally_id"] == rid and r["kind"] != "rally"] for rid in active_rallies}
    source = {k: deepcopy(asset[k]) for k in ("asset_id", "sha256", "relative_path", "duration_ms", "time_base", "usage_scope", "provenance", "rights", "match_id")}
    windows = []

    def emit(strategy, anchor, rally, interval, reasons, used):
        reasons = list(dict.fromkeys(reasons))
        if any(r.get("evidence_time_status") == "unresolved_bounded_by_source_duration" for r in [anchor, rally, *used]):
            reasons.append("evidence_time_unresolved")
        anchor_time = anchor.get("time_ms", anchor.get("start_ms", 0))
        ambiguous_rally = any(reason in reasons for reason in (
            "ambiguous_rally_terminals", "serve_not_first_contact", "ambiguous_serve_order"))
        status = "candidate" if ambiguous_rally else "unavailable" if interval is None else "candidate" if reasons else "ready"
        if interval is not None:
            lo, hi = interval
            if hi <= lo:
                interval, status = None, "unavailable"
                reasons.append("empty_range")
        wait_ms = None if "evidence_time_unresolved" in reasons else 0
        if available_until_ms is not None and (interval is None or interval[1] > available_until_ms):
            wait_ms = max(0, interval[1] - available_until_ms) if interval else None
            status, interval = "pending", None
            reasons.append("awaiting_source_context")
        latest = max([interval[1] if interval else anchor_time] + [evidence_end(r) for r in [rally, anchor, *used]] + [
            bounds(r)[1] if r["kind"] in POINTS else (r.get("end_ms") or r["start_ms"])
            for r in used if r["kind"] != "rally"])
        check(available_until_ms is None or latest <= available_until_ms,
              "Window would consume evidence beyond its watermark", "future_evidence")
        refs = [{"record_id": r["record_id"], "revision": r["revision"]} for r in sorted({r["record_id"]: r for r in [rally, anchor, *used]}.values(), key=lambda r: r["record_id"])]
        row = dict(strategy=strategy, anchor_id=anchor["record_id"], rally_id=rally["record_id"],
                   player_id=anchor.get("player_id"), team_id=anchor.get("team_id"), status=status,
                   range=dict(start_ms=interval[0], end_ms=interval[1]) if interval else None,
                   reasons=reasons, annotation_refs=refs, source=deepcopy(source), labels=deepcopy(anchor.get("labels", {})),
                   usage_scope="training_only", production_eligible=False, rule_version=RULE_VERSION,
                   pts=clock.select(*interval) if clock and interval else {"status": "not_provided" if not clock else "no_range"},
                   future_context_used=latest > anchor_time, latest_source_time_ms=latest,
                   lookahead_ms=max(0, latest-anchor_time), wait_ms=wait_ms)
        row["anchor_source_pts"] = anchor.get("source_pts")
        row["anchor_time_rounding_delta_ms"] = str(Fraction(anchor_time)-clock.time_ms(anchor["source_pts"])) if clock and anchor.get("source_pts") is not None else None
        if interval and clock and anchor.get("source_pts") is not None and not interval[0] <= clock.time_ms(anchor["source_pts"]) < interval[1]:
            row["status"] = "candidate"
            row["reasons"].append("anchor_pts_outside_millisecond_range")
        if interval and clock and row["pts"]["frame_count"] == 0:
            row["status"] = "candidate"
            row["reasons"].append("no_source_frames")
        row["window_id"] = "window-" + content_hash({**row, "project_id": project_id, "vocabulary_version": vocabulary_version,
                                                     "rules": config, "annotations": [r for r in visible if r["record_id"] in {x["record_id"] for x in refs}]})[:24]
        windows.append(row)

    def context(point, rally, before, after, dead):
        if rally["end_ms"] is None:
            return None, ["rally_end_unknown"]
        lo, hi = bounds(point)
        cap = min([rally["end_ms"], *[bounds(r)[1] for r in dead]])
        start, end = max(rally["start_ms"], lo-before), min(cap, hi+after)
        reasons = ["context_clipped_to_rally"] if start != lo-before or end != hi+after else []
        if len(dead) > 1:
            reasons.append("ambiguous_dead_ball_marks")
        if lo != hi:
            reasons.append("uncertain_contact")
        return (start, end), reasons

    for rid, rally in sorted(active_rallies.items(), key=lambda item: (item[1]["start_ms"], item[0])):
        related = by_rally[rid]
        contacts = sorted([r for r in related if r["kind"] in {"contact", "serve"}], key=lambda r: (r["time_ms"], r["record_id"]))
        dead = [r for r in related if r["kind"] == "dead_ball"]
        for mark in contacts:
            reasons, used = [], [mark]
            same_time = [r for r in contacts if r["time_ms"] == mark["time_ms"] and r is not mark]
            terminals = [r for r in [*contacts, *dead] if r["time_ms"] > mark["time_ms"]]
            if same_time:
                reasons.append("simultaneous_contacts")
                used.extend(same_time)
            if terminals:
                # A later nominal point may be the true next point when its
                # uncertainty overlaps an earlier one. Retain all competitors.
                earliest_upper = min(bounds(r)[1] for r in terminals)
                ends = [r for r in terminals if bounds(r)[0] <= earliest_upper]
                used.extend(ends)
                lo, hi = bounds(mark)[0], max(bounds(r)[1] for r in ends)
                if dead:
                    hi = min(hi, min(bounds(r)[1] for r in dead))
                previous = [r for r in contacts if r["time_ms"] < mark["time_ms"] and bounds(r)[1] >= bounds(mark)[0]]
                if previous:
                    reasons.append("overlapping_previous_contact")
                    used.extend(previous)
                if len(ends) != 1:
                    reasons.append("ambiguous_terminal")
                if bounds(mark)[0] != bounds(mark)[1] or any(bounds(r)[0] != bounds(r)[1] for r in ends):
                    reasons.append("uncertain_contact_or_terminal")
                if any(bounds(r)[0] <= bounds(mark)[1] for r in ends):
                    reasons.append("overlapping_uncertainty")
                if any(r["kind"] != "dead_ball" and r.get("player_id") == mark.get("player_id") and mark.get("player_id") for r in ends):
                    reasons.append("same_player_consecutive_contacts")
                interval = (lo, hi)
            else:
                interval = None
                reasons.append("missing_next_contact_or_dead_ball")
            if len(dead) > 1:
                reasons.append("ambiguous_dead_ball_marks")
                used.extend(dead)
            if not mark.get("player_id"):
                reasons.append("player_unknown")
            emit("ball_flight", mark, rally, interval, reasons, used)
            interval, reasons = context(mark, rally, config["hand_before_ms"], config["hand_after_ms"], dead)
            emit("hand_technique", mark, rally, interval, reasons, [mark, *dead])
            stages = [r for r in related if r["kind"] == "movement" and r["anchor_id"] == mark["record_id"]]
            if stages:
                interval = (min(r["start_ms"] for r in stages), max(r["end_ms"] for r in stages))
                reasons = []
                missing = sorted(PHASES - {r["phase"] for r in stages} - set(mark.get("phase_not_applicable", [])))
                if missing:
                    reasons.append("missing_phases:" + ",".join(missing))
                ordered_starts = [min(r["start_ms"] for r in stages if r["phase"] == p)
                                  for p in PHASE_ORDER if any(r["phase"] == p for r in stages)]
                if any(a > b for a, b in zip(ordered_starts, ordered_starts[1:])):
                    reasons.append("phase_order_conflict")
                if any(sum(r["phase"] == p for r in stages) > 1 for p in PHASES):
                    reasons.append("repeated_phase_intervals")
                if not interval[0] <= bounds(mark)[0] <= bounds(mark)[1] < interval[1]:
                    reasons.append("phases_do_not_cover_contact")
                if bounds(mark)[0] != bounds(mark)[1]:
                    reasons.append("uncertain_contact")
                if any(r.get("unknown_reason") or r.get("visibility") in {"insufficient", "unobservable", "unknown"} or r["phase"] == "unknown" for r in stages):
                    reasons.append("uncertain_phases")
                if rally["end_ms"] is None:
                    interval = None
                    reasons.append("rally_end_unknown")
                elif dead:
                    cap = min(bounds(r)[1] for r in dead)
                    if interval[1] > cap:
                        interval = interval[0], cap
                        reasons.append("phases_clipped_to_dead_ball")
                if len(dead) > 1:
                    reasons.append("ambiguous_dead_ball_marks")
            else:
                interval, reasons = context(mark, rally, config["footwork_before_ms"], config["footwork_after_ms"], dead)
                reasons.append("conservative_context_without_phases")
                if not mark.get("player_id"):
                    reasons.append("player_unknown")
            emit("footwork", mark, rally, interval, reasons, [mark, *stages, *dead])
        serves = [r for r in contacts if r["kind"] == "serve"]
        # A unique serve label does not establish the first contact. Closed
        # uncertainty envelopes must be strictly separated to prove its order;
        # nominally later contacts can still conflict with that first boundary.
        start_conflicts = [r for r in contacts if len(serves) == 1 and r is not serves[0]
                           and bounds(r)[0] <= bounds(serves[0])[1]]
        reasons = []
        if len(serves) != 1 or len(dead) != 1:
            interval = None
            if not serves:
                reasons.append("missing_serve")
            if not dead:
                reasons.append("missing_dead_ball")
            if len(serves) > 1 or len(dead) > 1:
                reasons.append("ambiguous_rally_terminals")
        elif serves[0]["time_ms"] >= dead[0]["time_ms"]:
            interval, reasons = None, ["invalid_serve_dead_ball_order"]
        elif start_conflicts:
            interval = None
            reasons = ["serve_not_first_contact" if bounds(r)[1] < bounds(serves[0])[0]
                       else "ambiguous_serve_order" for r in start_conflicts]
        elif rally["end_ms"] is None:
            interval, reasons = None, ["rally_end_unknown"]
        else:
            lo, hi = bounds(serves[0])[0]-config["rally_before_ms"], bounds(dead[0])[1]+config["rally_after_ms"]
            interval = max(rally["start_ms"], lo), min(rally["end_ms"], hi)
            if interval != (lo, hi):
                reasons.append("context_clipped_to_rally")
            if any(bounds(r)[0] != bounds(r)[1] for r in [serves[0], dead[0]]):
                reasons.append("uncertain_rally_terminals")
        emit("rally", serves[0] if len(serves) == 1 else rally, rally, interval, reasons, [*serves, *dead, *start_conflicts])
    result = dict(format=FORMAT, schema_version="1.0", project_id=project_id, vocabulary_version=vocabulary_version,
                  usage_scope="training_only", production_eligible=False, rule_version=RULE_VERSION, rules=config,
                  source=source, annotations=visible, windows=windows, available_until_ms=available_until_ms,
                  training_truth="not_determined_by_window_derivation")
    result["content_sha256"] = content_hash(result)
    return result


def read_verified_clock(asset, root):
    """Read the existing complete library index, bounded and hash-checked."""
    from .storage import sha256
    from .timeline import safe_path
    ref = asset.get("probe", {}).get("pts_index")
    check(isinstance(ref, dict), "Asset has no complete PTS index", "invalid_pts")
    probe = asset["probe"]
    check(ref.get("complete") is True and ref.get("format") == "jsonl"
          and probe.get("source_sha256", "").lower() == asset["sha256"].lower()
          and probe.get("source_size_bytes") == asset["size_bytes"],
          "PTS index lacks complete, source-bound probe metadata", "invalid_pts")
    path = safe_path(root, ref.get("relative_path"))
    check(path.is_file() and path.stat().st_size == ref.get("size_bytes") and path.stat().st_size <= 256_000_000,
          "PTS index size mismatch/limit", "invalid_pts")
    check(sha256(path) == ref.get("sha256"), "PTS index hash mismatch", "invalid_pts")
    pts = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            check(len(line) <= 4096 and len(pts) < 5_000_000, "PTS index limit exceeded", "invalid_pts")
            row = json.loads(line)
            check(type(row.get("frame_index")) is int and row["frame_index"] == len(pts), "Non-contiguous source frame indexes", "invalid_pts")
            pts.append(row.get("pts"))
    check(len(pts) == ref.get("frame_count"), "PTS index frame count mismatch", "invalid_pts")
    origin = probe.get("start_pts")
    check(type(origin) is int, "Probe must declare source origin start_pts", "invalid_pts")
    clock = SourceClock(pts, ref.get("time_base"), origin_pts=origin, reference=ref)
    if probe.get("start_time") is not None:
        check(abs(Fraction(probe["start_time"]) - clock.origin_pts * clock.time_base) <= clock.time_base,
              "Probe start_time/start_pts conflict", "invalid_pts")
    return clock


def derive_verified_request(request, storage_root):
    """Filesystem adapter for CLI/platform callers; never invokes render."""
    from packages.contracts import Asset
    from packages.contracts.usage import UsageScopeGuard
    from .storage import sha256
    from .timeline import safe_path
    check(isinstance(request, dict), "Request must be an object")
    check(set(request) <= {"asset", "records", "project_id", "vocabulary_version", "rules", "available_until_ms"}, "Unknown request field")
    asset = Asset.model_validate(request["asset"]).model_dump(mode="json")
    root = Path(storage_root).resolve(strict=True)
    path = safe_path(root, asset["relative_path"])
    check(path.is_file() and path.stat().st_size == asset["size_bytes"], "Source size mismatch", "asset_mismatch")
    check(sha256(path) == asset["sha256"].lower(), "Source hash mismatch", "asset_mismatch")
    decision = UsageScopeGuard(root).check(asset)
    clock = read_verified_clock(asset, root)
    result = derive_contact_windows(asset, request["records"], project_id=request["project_id"],
                                    vocabulary_version=request["vocabulary_version"], rules=request.get("rules"),
                                    clock=clock, available_until_ms=request.get("available_until_ms"))
    result["source_verification"] = dict(actual_sha256=asset["sha256"].lower(), size_bytes=asset["size_bytes"],
        effective_source_usage_scope=decision.usage_scope, registry_sha256=decision.registry_sha256,
        usage_reasons=list(decision.reasons), pts_index_sha256=clock.reference["sha256"], media_copied=False)
    result.pop("content_sha256")
    result["content_sha256"] = content_hash(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        check(args.request.is_file() and args.request.stat().st_size <= 16_000_000, "Request missing or exceeds 16MB")
        result = derive_verified_request(json.loads(args.request.read_text(encoding="utf-8-sig")), args.storage_root)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, OSError, TypeError, RenderError) as exc:
        print(json.dumps({"status": "failed", "error": {"code": getattr(exc, "code", "invalid_window_input"), "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
