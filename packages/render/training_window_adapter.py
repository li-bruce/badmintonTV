"""Adapt platform-owned training bundles/snapshots to logical source windows.

Serve and footwork phase bindings are explicit, revision-bound inputs. There
is deliberately no inference from the first contact or a coarse stroke label.
"""
from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
import math

from .contact_windows import WindowError, check, content_hash, derive_contact_windows

ADAPTER_VERSION = "training-window-adapter/1.0.0"


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
        for evidence in mapped["evidence"]:
            if "at_ms" in evidence and "time_ms" not in evidence:
                evidence["time_ms"] = evidence["at_ms"]
            if not any(key in evidence for key in ("end_ms", "time_ms")):
                index = evidence.get("source_frame_index", evidence.get("frame_index"))
                if index is None and clock is not None and type(evidence.get("source_pts")) is int:
                    found = bisect_left(clock.pts, evidence["source_pts"])
                    if found < len(clock.pts) and clock.pts[found] == evidence["source_pts"]:
                        index = found
                if clock is not None and type(index) is int and 0 <= index < len(clock.pts):
                    evidence["time_ms"] = math.ceil(clock.time_ms(clock.pts[index]))
                else:
                    # A reference alone does not prove when evidence was seen.
                    # This offline adapter bounds it by the entire source and
                    # keeps its timing unknown; it has no realtime mode.
                    mapped["latest_evidence_ms"] = asset["duration_ms"]
                    mapped["evidence_time_status"] = "unresolved_bounded_by_source_duration"
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
