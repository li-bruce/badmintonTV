"""Adapt platform-owned training bundles/snapshots to logical source windows.

Serve and footwork phase bindings are explicit, revision-bound inputs. There
is deliberately no inference from the first contact or a coarse stroke label.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

from .contact_windows import (
    SourceClock, WindowError, _bound_frame_evidence, check, content_hash,
    derive_contact_windows, evidence_end,
)

ADAPTER_VERSION = "training-window-adapter/1.0.1"


def _bind_frozen_clock(asset_reference, clock):
    """A supplied clock must describe the index frozen in the public bundle."""
    if clock is None:
        return
    check(isinstance(clock, SourceClock), "Invalid SourceClock", "invalid_pts")
    frozen = asset_reference.get("pts_reference")
    actual = clock.reference
    check(isinstance(actual, dict), "Clock reference must be an object", "invalid_pts")
    if frozen:
        check(actual, "Frozen PTS reference requires an identified clock", "invalid_pts")

    def path(reference):
        paths = [reference[key] for key in ("relative_path", "path") if key in reference]
        check(not paths or all(isinstance(value, str) and value == paths[0] for value in paths),
              "PTS path aliases conflict", "invalid_pts")
        return paths[0] if paths else None

    def time_base(value):
        try:
            result = Fraction(value)
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            raise WindowError("invalid_pts", "Invalid referenced PTS time_base") from exc
        check(result > 0, "Referenced PTS time_base must be positive", "invalid_pts")
        return result

    for reference in (frozen or {}, actual):
        path(reference)
        if "frame_count" in reference:
            check(type(reference["frame_count"]) is int and reference["frame_count"] == len(clock.pts),
                  "Referenced PTS count differs from actual clock", "invalid_pts")
        if "time_base" in reference:
            check(time_base(reference["time_base"]) == clock.time_base,
                  "Referenced PTS time_base differs from actual clock", "invalid_pts")
        if "size_bytes" in reference:
            check(type(reference["size_bytes"]) is int and reference["size_bytes"] > 0,
                  "Invalid referenced PTS size", "invalid_pts")
        if "complete" in reference:
            check(reference["complete"] is True, "Incomplete PTS reference", "invalid_pts")
        if "source_sha256" in reference:
            check(isinstance(reference["source_sha256"], str)
                  and reference["source_sha256"].lower() == asset_reference["sha256"].lower(),
                  "PTS reference belongs to a different source", "invalid_pts")
    if not frozen:
        return
    if path(frozen) is not None:
        check(path(actual) == path(frozen), "Clock PTS path differs from frozen reference", "invalid_pts")
    for key in ("format", "sha256", "size_bytes", "frame_count", "time_base", "complete"):
        if key not in frozen:
            continue
        check(key in actual, "Clock is missing frozen PTS field: " + key, "invalid_pts")
        expected, supplied = frozen[key], actual[key]
        if key == "sha256":
            check(isinstance(supplied, str), "Invalid clock PTS hash", "invalid_pts")
            expected, supplied = expected.lower(), supplied.lower()
        elif key == "time_base":
            expected, supplied = time_base(expected), time_base(supplied)
        check(expected == supplied, "Clock PTS field differs from frozen reference: " + key, "invalid_pts")


def _normalize_evidence(record, clock, duration):
    """Use core evidence rules for every record that influences a window."""
    for item in record["evidence"]:
        if "at_ms" in item and "time_ms" not in item:
            item["time_ms"] = item["at_ms"]
    _bound_frame_evidence(record, clock, duration)
    for item in record["evidence"]:
        if not any(key in item for key in ("end_ms", "time_ms", "at_ms")):
            has_frame = any(item.get(key) is not None for key in ("source_frame_index", "frame_index", "source_pts"))
            if clock is None or not has_frame:
                record["latest_evidence_ms"] = duration
                record["evidence_time_status"] = "unresolved_bounded_by_source_duration"
    check(evidence_end(record) <= duration, "Evidence exceeds media", "invalid_boundary")
    return record


def derive_training_bundle(asset, bundle, *, vocabulary_version, serve_mark_refs=(),
                           phase_bindings=(), rules=None, clock=None):
    """Consume a validated canonical bundle; return training-only review windows.

    serve_mark_refs=[{record_id, revision}]
    phase_bindings=[{record_id, revision, anchor_id, anchor_revision, phase}]
    These mappings belong in the caller's immutable project/snapshot settings.
    """
    try:
        from packages.contracts.training import TrainingAnnotationBundle
    except ImportError as exc:
        raise WindowError("training_contract_unavailable", "Install the platform-owned training contract before adapting a bundle") from exc
    raw = TrainingAnnotationBundle.model_validate(bundle).model_dump(mode="json")
    bundle_digest = content_hash(raw)
    if hasattr(asset, "model_dump"):
        asset = asset.model_dump(mode="json")
    for key in ("asset_id", "sha256", "relative_path", "size_bytes", "duration_ms"):
        check(asset.get(key) == raw["asset"][key], "Canonical Asset differs from training reference: " + key, "asset_mismatch")
    _bind_frozen_clock(raw["asset"], clock)
    current = {r["record_id"]: r for r in raw["records"]}

    def live_ref(ref, kind):
        check(isinstance(ref, dict), "Mapping reference must be an object")
        r = current.get(ref.get("record_id"))
        check(r is not None and r["revision"] == ref.get("revision"), "Mapping references a stale/missing revision", "revision_conflict")
        check(r["kind"] == kind and not r["deleted"] and r["review"]["status"] != "rejected", "Mapping references an inactive/wrong-kind annotation", "relation_mismatch")
        return r

    serves, phases = {}, {}
    for ref in serve_mark_refs:
        check(set(ref) == {"record_id", "revision"}, "Invalid serve mapping fields")
        r = live_ref(ref, "contact")
        check(r["record_id"] not in serves, "Duplicate serve mapping")
        serves[r["record_id"]] = ref
    for binding in phase_bindings:
        check(set(binding) == {"record_id", "revision", "anchor_id", "anchor_revision", "phase"}, "Invalid phase mapping fields")
        r = live_ref(binding, "segment")
        check(r["segment_type"] == "footwork", "Phase mapping requires a footwork segment", "relation_mismatch")
        live_ref({"record_id": binding["anchor_id"], "revision": binding["anchor_revision"]}, "contact")
        check(r["record_id"] not in phases, "Duplicate phase mapping")
        phases[r["record_id"]] = binding
    records, excluded = [], []
    active_rallies = {r["record_id"] for r in raw["records"] if r["kind"] == "rally" and not r["deleted"] and r["review"]["status"] != "rejected"}
    for r in raw["records"]:
        reason = None
        if r["deleted"] or r["review"]["status"] == "rejected":
            reason = "deleted_or_rejected"
        elif r["kind"] != "rally" and r["rally_id"] not in active_rallies:
            reason = "no_active_rally_assignment"
        elif r["kind"] == "state":
            reason = "state_retained_as_annotation_not_a_boundary"
        elif r["kind"] == "segment" and r["record_id"] not in phases:
            reason = "segment_has_no_explicit_phase_binding"
        if reason:
            excluded.append(dict(record_id=r["record_id"], revision=r["revision"], reason=reason))
            continue
        mapped = dict(record_id=r["record_id"], revision=r["revision"], asset_id=r["asset_id"],
                      rally_id=r["record_id"] if r["kind"] == "rally" else r["rally_id"],
                      player_id=r["person_id"], team_id=r["team_id"], kind=r["kind"],
                      labels=deepcopy(r["judgements"]),
                      visibility=r["visibility"], unknown_reason="; ".join(r["unknown_reasons"]),
                      review=deepcopy(r["review"]), provenance=deepcopy(r["provenance"]),
                      evidence=deepcopy(r["evidence"]), original_record=deepcopy(r))
        _normalize_evidence(mapped, clock, asset["duration_ms"])
        if r["kind"] in {"contact", "dead_ball"}:
            mapped["time_ms"] = r["at_ms"]
            if r["uncertainty_start_ms"] is not None:
                mapped["uncertainty"] = dict(start_ms=r["uncertainty_start_ms"], end_ms=r["uncertainty_end_ms"])
            if r["record_id"] in serves:
                mapped["kind"] = "serve"
        else:
            mapped.update(start_ms=r["start_ms"], end_ms=r["end_ms"])
            if r["kind"] == "segment":
                binding = phases[r["record_id"]]
                mapped.update(kind="movement", anchor_id=binding["anchor_id"], phase=binding["phase"])
        records.append(mapped)
    check(records, "Bundle contains no active, assigned window annotations", "no_window_annotations")
    result = derive_contact_windows(asset, records, project_id=raw["project_id"], vocabulary_version=vocabulary_version,
                                    rules=rules, clock=clock)
    unassigned = [current[e["record_id"]] for e in excluded
                  if e["reason"] == "no_active_rally_assignment" and current[e["record_id"]]["kind"] in {"contact", "dead_ball"}]
    normalized_competitors = {}
    for window in result["windows"]:
        interval = window["range"]
        competitors = [r for r in unassigned if interval is not None
            and (r["uncertainty_start_ms"] if r["uncertainty_start_ms"] is not None else r["at_ms"]) < interval["end_ms"]
            and (r["uncertainty_end_ms"] if r["uncertainty_end_ms"] is not None else r["at_ms"]) >= interval["start_ms"]]
        if competitors:
            window["status"] = "candidate"
            window["reasons"].append("unassigned_boundary_in_range")
            window["unresolved_boundary_refs"] = [{"record_id": r["record_id"], "revision": r["revision"]} for r in competitors]
            window["annotation_refs"].extend(window["unresolved_boundary_refs"])
            latest = window["latest_source_time_ms"]
            for competitor in competitors:
                rid = competitor["record_id"]
                if rid not in normalized_competitors:
                    normalized_competitors[rid] = _normalize_evidence(deepcopy(competitor), clock, asset["duration_ms"])
                observed = normalized_competitors[rid]
                latest = max(latest, evidence_end(observed), observed["uncertainty_end_ms"]
                             if observed["uncertainty_end_ms"] is not None else observed["at_ms"])
                if observed.get("evidence_time_status") and "evidence_time_unresolved" not in window["reasons"]:
                    window["reasons"].append("evidence_time_unresolved")
                if observed.get("evidence_time_status"):
                    window["wait_ms"] = None
            anchor = current[window["anchor_id"]]
            anchor_time = anchor["at_ms"] if anchor["at_ms"] is not None else anchor["start_ms"]
            window["latest_source_time_ms"] = latest
            window["future_context_used"] = latest > anchor_time
            window["lookahead_ms"] = max(0, latest - anchor_time)
        # Bundle changes, including excluded but competing marks, invalidate
        # derived IDs. Never silently reuse a cached "ready" window after edit.
        window.pop("window_id")
        window["window_id"] = "window-" + content_hash(dict(window=window, bundle_sha256=bundle_digest,
            adapter_version=ADAPTER_VERSION, serve_mark_refs=list(serve_mark_refs), phase_bindings=list(phase_bindings)))[:24]
    result["training_adapter"] = dict(version=ADAPTER_VERSION, bundle_format=raw["format"], bundle_revision=raw["revision"],
        bundle_sha256=bundle_digest, serve_mark_refs=deepcopy(list(serve_mark_refs)), phase_bindings=deepcopy(list(phase_bindings)),
        excluded_records=excluded, annotation_bundle=raw,
        note="Mappings are explicit review inputs; windows do not certify human truth or snapshot training eligibility")
    result.pop("content_sha256")
    result["content_sha256"] = content_hash(result)
    return result


def derive_training_snapshot(asset, snapshot, *, serve_mark_refs=(), phase_bindings=(), rules=None, clock=None):
    """Consume one asset's bundle from an immutable, hash-validated snapshot."""
    try:
        from packages.contracts.training import TrainingSnapshot
    except ImportError as exc:
        raise WindowError("training_contract_unavailable", "Install the platform-owned training contract before adapting a snapshot") from exc
    frozen = TrainingSnapshot.model_validate(snapshot)
    source_id = asset.asset_id if hasattr(asset, "asset_id") else asset["asset_id"]
    bundles = [b for b in frozen.bundles if b.asset.asset_id == source_id]
    check(len(bundles) == 1, "Snapshot must contain exactly one matching annotation bundle", "relation_mismatch")
    result = derive_training_bundle(asset, bundles[0], vocabulary_version=frozen.taxonomy.version,
        serve_mark_refs=serve_mark_refs, phase_bindings=phase_bindings, rules=rules, clock=clock)
    result["snapshot_reference"] = dict(snapshot_id=frozen.snapshot_id, content_sha256=frozen.content_sha256,
        project_revision=frozen.project.revision, taxonomy_id=frozen.taxonomy.taxonomy_id, taxonomy_version=frozen.taxonomy.version,
        quality_summary=frozen.quality_summary.model_dump(mode="json"),
        note="Original eligibility is unchanged; this output is a review window list, not a new training truth view")
    result.pop("content_sha256")
    result["content_sha256"] = content_hash(result)
    return result
