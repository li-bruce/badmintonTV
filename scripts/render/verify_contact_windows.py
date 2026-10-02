"""Read-only A-07/A-08 render checks against existing real source/PTS bytes.

Run with the existing platform environment, from any directory:
  python -B scripts/render/verify_contact_windows.py --storage-root D:/video

Only docs/render/CONTACT_WINDOWS_VALIDATION.json is written (under 500 KB).
Marks, phases, players and rallies below are agent technical fixtures, never
human action truth. This script neither invokes media tools nor copies media.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
REPORT = REPO / "docs/render/CONTACT_WINDOWS_VALIDATION.json"
REPORT_LIMIT = 500_000
TRAINING_MANIFEST = "data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json"
REGISTRY = "data/training/handoff/training-registry.v1.json"
TRAINING_SHA = "b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913"
VFR_SHA = "80d9c5be022baef9ce57773cbadfb28647d8e11c651fc4528eec5d8e7b32c4b7"
GENERAL_SHA = "5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90"
UI_SNAPSHOT_PATH = "platform/integration-20261002/snapshot-before-restart.json"
UI_SNAPSHOT_FILE_SHA = "5f471b166151172accb35764be2993945c991707ff9a6d49ce02a162d1e2e460"
UI_SNAPSHOT_CONTENT_SHA = "d2deb51291cbb8ad5ac100e7a95d60afb6670e8c3762f05304daee77410a67dd"


def now():
    return datetime.now(timezone.utc).isoformat()


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    require(path.stat().st_size <= 2_000_000, f"Oversize input JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


class ReadOnlyAudit:
    """Guard this Python process; counters describe attempted calls, not mocks."""
    def __init__(self):
        self.process_attempts = []
        self.forbidden_write_attempts = []
        self.allowed_report_open_count = 0

    def __call__(self, event, args):
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.startfile"}:
            self.process_attempts.append(event)
            raise RuntimeError(f"Process execution forbidden during verification: {event}")
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not writing:
                return
            if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).resolve() == REPORT:
                self.allowed_report_open_count += 1
                return
            self.forbidden_write_attempts.append({"event": event, "path": str(path)})
            raise RuntimeError(f"Only the fixed workspace report may be written: {path}")
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.truncate", "shutil.copyfile"}:
            self.forbidden_write_attempts.append({"event": event, "path": str(args[0])})
            raise RuntimeError(f"Filesystem mutation forbidden during verification: {event}")


def technical_records(asset, clock):
    """Invented A-B-A fixture; times reference real PTS, actions do not."""
    aid, rally_id = asset["asset_id"], "technical-rally-1"

    def record(rid, kind, **fields):
        return dict(record_id=rid, revision=2, asset_id=aid, rally_id=rally_id, kind=kind,
                    labels={"hand_technique": "unknown", "footwork": "unknown"},
                    review_status="unreviewed", visibility="not_reviewed",
                    unknown_reason="agent technical fixture; action and identity not reviewed",
                    provenance={"reviewer_type": "agent", "purpose": "technical_fixture_only",
                                "human_action_truth": False}, **fields)

    rows = [record(rally_id, "rally", start_ms=0, end_ms=6000)]
    for rid, kind, ms, player in (("technical-serve", "serve", 1000, "fixture-A"),
                                  ("technical-contact-2", "contact", 2000, "fixture-B"),
                                  ("technical-contact-3", "contact", 3000, "fixture-A"),
                                  ("technical-dead", "dead_ball", 6000, None)):
        tick = clock.origin_pts + Fraction(ms, 1000) / clock.time_base
        index = bisect_left(clock.pts, tick)
        fields = dict(time_ms=ms, player_id=player)
        if index < len(clock.pts) and clock.pts[index] == tick:
            fields["source_pts"] = int(tick)
        else:
            require(kind == "dead_ball" and ms == asset["duration_ms"], "Missing nominal mark PTS")
            fields["source_pts_unavailable_reason"] = "media_end_boundary_is_not_a_displayed_frame"
        rows.append(record(rid, kind, **fields))
    phases = (("preparation", 2200, 2400), ("initiation", 2400, 2600),
              ("arrival", 2600, 2840), ("stroke_support", 2840, 3080),
              ("landing", 3080, 3280), ("recovery", 3280, 3600))
    rows.extend(record("technical-phase-" + phase, "movement", start_ms=start, end_ms=end,
                       anchor_id="technical-contact-3", phase=phase, player_id="fixture-A")
                for phase, start, end in phases)
    return rows


def request_for(asset, records):
    return dict(asset=deepcopy(asset), records=deepcopy(records),
                project_id="render-contact-technical-verification", vocabulary_version="technical-unknown-v1")


def one_window(result, strategy, anchor):
    matches = [w for w in result["windows"] if w["strategy"] == strategy and w["anchor_id"] == anchor]
    require(len(matches) == 1, f"Expected one {strategy}/{anchor}")
    return matches[0]


def check_all_windows(result, clock):
    """Independently enumerate source PTS instead of repeating binary search."""
    require(result["usage_scope"] == "training_only" and result["production_eligible"] is False,
            "Derived manifest lost training-only restriction")
    rallies = {r["record_id"]: r for r in result["annotations"] if r["kind"] == "rally"}
    refs = {r["record_id"]: r["revision"] for r in result["annotations"]}
    rows = []
    for window in result["windows"]:
        require(window["usage_scope"] == "training_only" and window["production_eligible"] is False,
                "Derived window lost training-only restriction")
        require(all(refs[x["record_id"]] == x["revision"] for x in window["annotation_refs"]), "Revision lost")
        if window["range"] is None:
            rows.append({key: window[key] for key in (
                "window_id", "strategy", "anchor_id", "range", "status", "reasons")})
            continue
        lo, hi = window["range"]["start_ms"], window["range"]["end_ms"]
        rally = rallies[window["rally_id"]]
        require(0 <= rally["start_ms"] <= lo < hi <= rally["end_ms"] <= result["source"]["duration_ms"],
                "Window crosses rally/media")
        expected = [i for i, pts in enumerate(clock.pts) if lo <= clock.time_ms(pts) < hi]
        mapped = window["pts"]
        actual = list(range(mapped["first_frame_index"], mapped["end_frame_index_exclusive"]))
        require(expected == actual and len(expected) == mapped["frame_count"], "Incorrect half-open PTS mapping")
        require(mapped["first_pts"] == (clock.pts[expected[0]] if expected else None), "Incorrect first PTS")
        require(mapped["last_pts"] == (clock.pts[expected[-1]] if expected else None), "Incorrect last PTS")
        rows.append(dict(window_id=window["window_id"], strategy=window["strategy"], anchor_id=window["anchor_id"],
                         range=window["range"], status=window["status"], reasons=window["reasons"],
                         first_frame_index=mapped["first_frame_index"], frame_count=len(expected),
                         end_frame_index_exclusive=mapped["end_frame_index_exclusive"]))
    return rows


def ordinary_timeline(asset):
    return dict(schema_version="1.0", timeline_id="technical-production-denial-check", segments=[
        dict(segment_id="technical-segment", asset_id=asset["asset_id"], in_ms=1000, out_ms=2000,
             review_status="unreviewed", editorial_review={"reviewer_type": "agent"})])


def verify_canonical_adapter(asset, records, clock, direct, report):
    """Exercise the frozen public contract with local agent metadata only."""
    from packages.contracts.training import (
        TrainingAnnotationBundle, TrainingAssetRef, TrainingProject, TrainingSnapshot,
        build_training_snapshot, get_default_training_taxonomy, training_content_sha256)
    from packages.render.contact_windows import content_hash
    from packages.render.training_window_adapter import derive_training_bundle, derive_training_snapshot

    project_id = direct["project_id"]
    timestamp = "2026-10-02T00:00:00Z"
    group_id = "technical-unconfirmed-b210-source-group"
    taxonomy = get_default_training_taxonomy()
    require(taxonomy.status == "provisional", "Default taxonomy changed; review verifier fixture")
    reference = TrainingAssetRef(
        **{key: asset[key] for key in ("asset_id", "sha256", "relative_path", "size_bytes", "duration_ms", "title")},
        usage_scope="training_only", source_usage_scope="training_only", match_id=asset["match_id"],
        group_id=group_id, group_status="unconfirmed", root_asset_ids=[asset["asset_id"]],
        source_sha256s=[asset["sha256"]], pts_reference=deepcopy(asset["probe"]["pts_index"]),
        provenance={**deepcopy(asset["provenance"]), "fixture": "agent-only local contract verification",
                    "group_assignment": "unconfirmed; publisher identity is not independent match evidence"})
    canonical = []
    serve_refs, phase_bindings = [], []
    for record in records:
        kind = {"serve": "contact", "movement": "segment"}.get(record["kind"], record["kind"])
        row = dict(record_id=record["record_id"], project_id=project_id, asset_id=asset["asset_id"], kind=kind,
            revision=record["revision"], previous_revision=record["revision"]-1,
            person_id=record.get("player_id"), team_id=record.get("team_id"),
            judgements=[], visibility="unknown", unknown_reasons=[record["unknown_reason"]],
            raw_labels=[f"{key}={value}" for key, value in sorted(record["labels"].items())],
            review=dict(status="pending", reviewer_type="agent", reviewer="contact-window-verifier",
                        note="Local technical fixture; no human judgement or UI save occurred"),
            provenance={**deepcopy(record["provenance"]), "original_technical_record": deepcopy(record)})
        if kind in {"contact", "dead_ball"}:
            row.update(at_ms=record["time_ms"], rally_id=record["rally_id"])
            pts = record["source_pts"]
            frame = bisect_left(clock.pts, pts)
            require(frame < len(clock.pts) and clock.pts[frame] == pts, "Fixture point has no real PTS")
            row["evidence"] = [dict(asset_id=asset["asset_id"], at_ms=record["time_ms"],
                source_pts=pts, source_frame_index=frame, reference=clock.reference["relative_path"],
                note="PTS alignment evidence only; no observed action claim")]
            if record["kind"] == "serve":
                serve_refs.append(dict(record_id=record["record_id"], revision=record["revision"]))
        else:
            row.update(start_ms=record["start_ms"], end_ms=record["end_ms"])
            row["evidence"] = [dict(asset_id=asset["asset_id"], start_ms=record["start_ms"],
                end_ms=record["end_ms"], reference=clock.reference["relative_path"],
                note="Invented technical interval over existing source clock")]
            if kind == "rally":
                row["dead_ball_id"] = "technical-dead"
            else:
                row.update(rally_id=record["rally_id"], segment_type="footwork")
                phase_bindings.append(dict(record_id=record["record_id"], revision=record["revision"],
                    anchor_id=record["anchor_id"], anchor_revision=2, phase=record["phase"]))
        canonical.append(row)
    people = [dict(person_id=pid, display_name="Anonymous technical role " + pid.rsplit("-", 1)[-1],
                   identity_status="unconfirmed", provenance={"reviewer_type": "agent", "human_action_truth": False})
              for pid in sorted({r["player_id"] for r in records if r.get("player_id")})]
    bundle = TrainingAnnotationBundle(project_id=project_id, asset=reference, revision=2,
                                      people=people, records=canonical)
    bundle_json = bundle.model_dump(mode="json")
    project = TrainingProject(project_id=project_id, name="Local agent contact-window contract fixture",
        catalog_version="fine-badminton-2026-zenodo-20292976-v1.0/final-20260929",
        taxonomy_id=taxonomy.taxonomy_id, taxonomy_version=taxonomy.version, asset_ids=[asset["asset_id"]],
        created_at=timestamp, updated_at=timestamp, provenance={
            "source_manifest_sha256": report["inputs"]["training_manifest"]["sha256"],
            "fixture": "local agent-only metadata; no service registration or human truth",
            "window_settings": {"serve_mark_refs": serve_refs, "phase_bindings": phase_bindings}})
    snapshot_inputs = dict(snapshot_id="snapshot-render-contact-b210-technical-v1", project=project,
        taxonomy=taxonomy, assets=[reference], bundles=[bundle], splits=[{"group_id": group_id, "split": "unassigned"}],
        created_at=timestamp)
    snapshot = build_training_snapshot(**snapshot_inputs)
    snapshot_json = snapshot.model_dump(mode="json")
    require(build_training_snapshot(**snapshot_inputs).model_dump(mode="json") == snapshot_json,
            "Fixed canonical snapshot was not repeatable")
    require(training_content_sha256(snapshot_json) == snapshot.content_sha256, "Public snapshot hash mismatch")
    roundtrip = TrainingSnapshot.model_validate_json(json.dumps(snapshot_json, ensure_ascii=False))
    require(roundtrip.model_dump(mode="json") == snapshot_json, "Public snapshot round trip changed")
    quality = snapshot.quality_summary.model_dump(mode="json")
    expected_blockers = {"no_human_confirmed_semantically_defined_judgements", "unassigned_or_unconfirmed_groups",
                         "independent_match_group_unconfirmed"}
    require(quality["eligible_judgement_count"] == 0 and len(snapshot.training_view) == 0 and not quality["trainable"],
            "Agent fixture entered eligible training view")
    require(expected_blockers <= set(quality["blockers"]), "Missing quality blockers")
    require(quality["missing_dead_ball_rally_ids"] == [], "Canonical rally lost independent dead-ball reference")
    mappings = dict(serve_mark_refs=serve_refs, phase_bindings=phase_bindings, clock=clock)
    adapted = derive_training_bundle(asset, bundle, vocabulary_version=taxonomy.version, **mappings)
    frozen = derive_training_snapshot(asset, snapshot_json, **mappings)
    checks = {}
    direct_windows = {(w["strategy"], w["anchor_id"]): w for w in direct["windows"]}
    for name, value in (("bundle", adapted), ("snapshot", frozen)):
        checks[name] = check_all_windows(value, clock)
        require(len(value["windows"]) == len(direct_windows), "Canonical adapter lost windows")
        for window in value["windows"]:
            original = direct_windows[(window["strategy"], window["anchor_id"])]
            for key in ("range", "pts", "rally_id", "player_id", "status", "reasons"):
                require(window[key] == original[key], f"Canonical {name} changed window {key}")
        metadata = value["training_adapter"]
        require(metadata["annotation_bundle"] == bundle_json, "Canonical bundle was not retained exactly")
        require(metadata["bundle_sha256"] == content_hash(bundle_json) and metadata["bundle_revision"] == 2,
                "Canonical bundle hash/revision reference incorrect")
        require(metadata["serve_mark_refs"] == serve_refs and metadata["phase_bindings"] == phase_bindings,
                "Explicit revision-bound mapping was lost")
        require(metadata["excluded_records"] == [], "Assigned canonical fixture records unexpectedly excluded")
        mapped = {r["record_id"]: r for r in value["annotations"]}
        for old in records:
            new = mapped[old["record_id"]]
            require(new["provenance"]["original_technical_record"] == old, "Original fixture/unknown/source_pts lost")
            require(new["unknown_reason"] == old["unknown_reason"] and new["review"]["reviewer_type"] == "agent"
                    and new["review"]["status"] == "pending" and new["revision"] == 2, "Review/revision promoted or lost")
            require(new["original_record"]["previous_revision"] == 1 and new["original_record"]["judgements"] == [],
                    "Canonical previous revision or empty judgements lost")
            if "source_pts" in old:
                require(new["evidence"][0]["source_pts"] == old["source_pts"], "Canonical PTS evidence lost")
        require(value["source"]["usage_scope"] == "training_only", "Canonical source usage downgraded")
    require(adapted["windows"] == frozen["windows"], "Bundle and snapshot adapter outputs disagree")
    reference_back = frozen["snapshot_reference"]
    require(reference_back["snapshot_id"] == snapshot.snapshot_id and reference_back["content_sha256"] == snapshot.content_sha256,
            "Adapter cannot trace immutable snapshot ID/hash")
    require(reference_back["quality_summary"] == quality and reference_back["project_revision"] == project.revision,
            "Adapter changed original quality blockers/project revision")
    require(snapshot.model_dump(mode="json") == snapshot_json and bundle.model_dump(mode="json") == bundle_json,
            "Adapter mutated canonical input")
    report["A07_public_contract_adapter"] = dict(status="PASS", scope="Local agent contract fixture over verified real b210 source/PTS",
        contract_format=bundle.format, snapshot=snapshot_json, adapter_version=adapted["training_adapter"]["version"],
        bundle_sha256=adapted["training_adapter"]["bundle_sha256"], bundle_revision=2,
        serve_mark_refs=serve_refs, phase_bindings=phase_bindings, snapshot_reference=reference_back,
        bundle_window_manifest_sha256=adapted["content_sha256"], snapshot_window_manifest_sha256=frozen["content_sha256"],
        independent_half_open_frame_checks=checks, direct_range_and_pts_mapping_equal=True,
        bundle_and_snapshot_windows_equal=True, snapshot_rebuild_and_roundtrip_equal=True,
        original_unknown_agent_provenance_and_revision_preserved=True,
        anchor_pts_note="Canonical source_pts retained in original_record/provenance/evidence; adapter does not promote it to anchor_source_pts",
        eligible_judgements_before_and_after=0, service_or_ui_registration=False, human_action_truth=False,
        limitations=["Not a UI save, project registration, persisted revision history, or human annotation acceptance",
                     "Judgements intentionally empty; original unknown labels remain raw_labels and provenance",
                     "ready is range availability only; provisional taxonomy, unconfirmed group and unassigned split remain blockers"])


def verify_root_ui_snapshot(asset, clock, root, report):
    """Consume one fixed root-provided UI artifact, without replaying its UI."""
    from packages.contracts.training import TrainingSnapshot, training_content_sha256
    from packages.render.contact_windows import content_hash
    from packages.render.training_window_adapter import derive_training_snapshot

    path = root / UI_SNAPSHOT_PATH
    require(sha256(path) == UI_SNAPSHOT_FILE_SHA, "Root UI snapshot file bytes changed")
    snapshot = TrainingSnapshot.model_validate(read_json(path))
    original = snapshot.model_dump(mode="json")
    require(snapshot.content_sha256 == UI_SNAPSHOT_CONTENT_SHA == training_content_sha256(snapshot),
            "Root UI snapshot canonical content hash differs")
    require(len(snapshot.bundles) == 1 and len(snapshot.assets) == 1, "Unexpected UI snapshot asset count")
    bundle = snapshot.bundles[0]
    require(bundle.asset.asset_id == asset["asset_id"] and bundle.asset.sha256 == TRAINING_SHA,
            "Root UI snapshot source differs from real verified b210 source")
    require(bundle.revision == 2 and len(bundle.records) == 6, "Root UI bundle revision/records changed")
    require(Counter(r.kind for r in bundle.records) == {"rally": 1, "contact": 2, "dead_ball": 1, "segment": 2},
            "Unexpected UI record kinds")
    rally = next(r for r in bundle.records if r.kind == "rally")
    contacts = sorted((r for r in bundle.records if r.kind == "contact"), key=lambda r: r.at_ms)
    dead = next(r for r in bundle.records if r.kind == "dead_ball")
    require((rally.start_ms, rally.end_ms, dead.at_ms) == (60000, 70000, 70000), "UI rally/terminal changed")
    require([r.at_ms for r in contacts] == [63000, 65000], "UI contacts changed")
    require(sorted((r.start_ms, r.end_ms) for r in bundle.records if r.kind == "segment") ==
            [(62000, 64000), (62500, 64000)], "UI segment ranges changed")
    require(all(r.review.reviewer_type == "agent" and r.review.status == "pending" for r in bundle.records),
            "UI records are no longer the expected agent review view")
    judgements = [j for r in bundle.records for j in r.judgements]
    require(Counter(j.value for j in judgements) == {"unknown": 2, "unobservable": 1},
            "UI unknown/unobservable judgements changed")
    quality = snapshot.quality_summary.model_dump(mode="json")
    require(quality["eligible_judgement_count"] == 0 and quality["excluded_judgement_count"] == 3
            and not quality["trainable"] and not snapshot.training_view, "UI snapshot unexpectedly trainable")

    # Deliberately do not infer a serve or a phase binding from UI row order/labels.
    derived = derive_training_snapshot(asset, snapshot, clock=clock)
    require(len(derived["windows"]) == 7, "UI snapshot should produce two contacts x three strategies plus rally")
    mapped = check_all_windows(derived, clock)
    for contact, flight_end in zip(contacts, (65000, 70000)):
        flight = one_window(derived, "ball_flight", contact.record_id)
        hand = one_window(derived, "hand_technique", contact.record_id)
        foot = one_window(derived, "footwork", contact.record_id)
        require(flight["range"] == {"start_ms": contact.at_ms, "end_ms": flight_end}, "Incorrect UI flight range")
        require(hand["range"] == {"start_ms": contact.at_ms-500, "end_ms": contact.at_ms+500}, "Incorrect UI hand range")
        require(foot["range"] == {"start_ms": contact.at_ms-2000, "end_ms": contact.at_ms+2000}
                and foot["status"] == "candidate" and "conservative_context_without_phases" in foot["reasons"],
                "UI unbound segments were inferred into complete footwork phases")
    rally_window = one_window(derived, "rally", rally.record_id)
    require(rally_window["status"] == "unavailable" and rally_window["range"] is None
            and "missing_serve" in rally_window["reasons"], "UI first contact was incorrectly inferred as serve")
    metadata = derived["training_adapter"]
    require(metadata["serve_mark_refs"] == [] and metadata["phase_bindings"] == [], "UI bindings unexpectedly invented")
    require(metadata["annotation_bundle"] == bundle.model_dump(mode="json"), "UI bundle/unknown/state/provenance not retained")
    require(metadata["bundle_sha256"] == content_hash(bundle.model_dump(mode="json")), "UI bundle content hash incorrect")
    require(len(metadata["excluded_records"]) == 2, "UI unbound segments were unexpectedly consumed")
    reference = derived["snapshot_reference"]
    require(reference["snapshot_id"] == snapshot.snapshot_id and reference["content_sha256"] == UI_SNAPSHOT_CONTENT_SHA
            and reference["quality_summary"] == quality, "UI snapshot reference or eligibility changed")
    require(derived["source"]["usage_scope"] == "training_only" and snapshot.usage_scope == "training_only",
            "UI source/snapshot usage downgraded")
    require(snapshot.model_dump(mode="json") == original, "UI snapshot mutated by adapter")
    report["A07_root_ui_snapshot"] = dict(status="PASS", provenance="Root-provided existing training-workbench UI snapshot artifact",
        snapshot_path=UI_SNAPSHOT_PATH, snapshot_file_bytes=path.stat().st_size, snapshot_file_sha256=UI_SNAPSHOT_FILE_SHA,
        snapshot_id=snapshot.snapshot_id, snapshot_content_sha256=UI_SNAPSHOT_CONTENT_SHA,
        source_asset_id=asset["asset_id"], source_sha256=TRAINING_SHA, pts_index_sha256=clock.reference["sha256"],
        bundle_revision=bundle.revision, records_count=len(bundle.records), bundle_sha256=metadata["bundle_sha256"],
        serve_mark_refs=[], phase_bindings=[], windows_count=len(derived["windows"]),
        independent_half_open_frame_checks=mapped, excluded_records=metadata["excluded_records"],
        snapshot_reference=reference, original_snapshot_unchanged=True, full_original_bundle_retained_by_adapter=True,
        judgement_values={"unknown": 2, "unobservable": 1}, eligible_judgements_before_and_after=0,
        derived_manifest_content_sha256=derived["content_sha256"],
        ui_executed_by_this_script=False, restart_executed_by_this_script=False, human_action_truth=False,
        limitations=["Root supplied the UI/restart evidence; this script only reads and validates its frozen artifact",
                     "No serve or phase bindings supplied; missing serve stays unavailable and footwork remains a conservative candidate",
                     "The UI snapshot is referenced by fixed file/content hashes, not embedded or rewritten"])


def verify(root, audit, report):
    from packages.render.contact_windows import (
        WindowError, content_hash, derive_contact_windows, derive_verified_request, read_verified_clock)
    from packages.render import engine
    from packages.render.timeline import assets_by_id, normalize_timeline
    from packages.render.usage import check_usage, verify_source_bytes

    training = read_json(root / TRAINING_MANIFEST)
    asset = next(a for a in training["assets"] if a["sha256"] == TRAINING_SHA)
    vfr_asset = next(a for a in training["assets"] if a["sha256"] == VFR_SHA)
    general_request = read_json(REPO / "configs/render/real-research.request.json")
    general_asset = next(a for a in general_request["assets"] if a["sha256"] == GENERAL_SHA)
    tracked = [root / TRAINING_MANIFEST, root / REGISTRY, root / "data/handoff/assets.v1.json", root / UI_SNAPSHOT_PATH]
    tracked += [root / a[key] for a in [asset, *general_request["assets"]] for key in ("relative_path",)]
    tracked += [root / a["probe"]["pts_index"]["relative_path"] for a in [asset, vfr_asset, *general_request["assets"]]]
    before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in tracked}
    registry_before = sha256(root / REGISTRY)
    report["inputs"] = dict(training_manifest=dict(path=TRAINING_MANIFEST, sha256=sha256(root / TRAINING_MANIFEST)),
                            registry=dict(path=REGISTRY, sha256=registry_before),
                            general_request_sha256=sha256(REPO / "configs/render/real-research.request.json"))
    clock = read_verified_clock(asset, root)
    records = technical_records(asset, clock)
    request = request_for(asset, records)
    original = deepcopy(request)
    started = time.perf_counter()
    derived = derive_verified_request(request, root)
    require(request == original, "Input request mutated")
    require(derived["annotations"] == sorted(records, key=lambda r: r["record_id"]), "Agent/unknown/source_pts fields lost")
    hashed = deepcopy(derived)
    supplied_hash = hashed.pop("content_sha256")
    require(content_hash(hashed) == supplied_hash, "Manifest content hash incorrect")
    pure = derive_contact_windows(asset, records, project_id=request["project_id"],
                                  vocabulary_version=request["vocabulary_version"], clock=clock)
    repeated = derive_contact_windows(asset, list(reversed(records)), project_id=request["project_id"],
                                      vocabulary_version=request["vocabulary_version"], clock=clock)
    require(pure == repeated, "Pure derivation changed with input record order")
    source_verified = derived["source_verification"]
    require(source_verified["actual_sha256"] == TRAINING_SHA and
            source_verified["effective_source_usage_scope"] == "training_only", "Source verification incorrect")
    checks = check_all_windows(derived, clock)
    expectations = [("ball_flight", "technical-serve", 1000, 2000),
                    ("ball_flight", "technical-contact-2", 2000, 3000),
                    ("ball_flight", "technical-contact-3", 3000, 6000),
                    ("hand_technique", "technical-contact-3", 2500, 3500),
                    ("footwork", "technical-contact-3", 2200, 3600),
                    ("rally", "technical-serve", 1000, 6000)]
    for strategy, anchor, lo, hi in expectations:
        require(one_window(derived, strategy, anchor)["range"] == {"start_ms": lo, "end_ms": hi},
                f"Unexpected {strategy} range")
    foot = one_window(derived, "footwork", "technical-contact-3")
    require(foot["status"] == "candidate" and "uncertain_phases" in foot["reasons"],
            "Unknown agent phases were promoted to precise action evidence")
    require("technical-contact-2" in {x["record_id"] for x in one_window(derived, "ball_flight", "technical-serve")["annotation_refs"]},
            "Opposing player's next contact was skipped")
    report["A07_real_source"] = dict(status="PASS", elapsed_seconds=round(time.perf_counter()-started, 6),
        request=request, derived=derived, independent_half_open_frame_checks=checks,
        source_rows=len(clock.pts), source_first_pts=clock.pts[0], source_last_pts=clock.pts[-1],
        order_independent_pure_result=True, input_unchanged=True,
        readiness_note="ready means logical range availability; annotations remain agent/unreviewed/unknown")
    verify_canonical_adapter(asset, records, clock, derived, report)
    verify_root_ui_snapshot(asset, clock, root, report)

    missing = [deepcopy(r) for r in records if r["kind"] != "dead_ball"]
    next(r for r in missing if r["kind"] == "rally")["end_ms"] = None
    unavailable = derive_contact_windows(asset, missing, project_id=request["project_id"],
                                         vocabulary_version=request["vocabulary_version"], clock=clock)
    for strategy in ("ball_flight", "hand_technique", "footwork"):
        w = one_window(unavailable, strategy, "technical-contact-3")
        require(w["range"] is None and w["status"] == "unavailable", "Missing endpoint became precise")
    require(one_window(unavailable, "rally", "technical-serve")["range"] is None, "Rally inferred a missing dead ball")
    invalid = deepcopy(records)
    next(r for r in invalid if r["record_id"] == "technical-contact-2")["source_pts"] += 1
    try:
        derive_contact_windows(asset, invalid, project_id=request["project_id"],
                               vocabulary_version=request["vocabulary_version"], clock=clock)
    except WindowError as exc:
        require(exc.code == "invalid_pts", "Unexpected invalid mark error")
        invalid_code = exc.code
    else:
        raise AssertionError("Invalid mark PTS was accepted")
    report["A07_missing_and_invalid"] = dict(status="PASS", missing_terminal_windows=[
        {k: w[k] for k in ("strategy", "anchor_id", "status", "range", "reasons")}
        for w in unavailable["windows"]], invalid_mark_pts_error=invalid_code)

    vfr_clock = read_verified_clock(vfr_asset, root)
    selected = vfr_clock.select(9160, 9220)
    require((selected["first_frame_index"], selected["end_frame_index_exclusive"], selected["frame_count"]) == (229, 231, 2),
            "Real VFR half-open selection incorrect")
    require(vfr_clock.time_ms(vfr_clock.pts[230]) == 9180 and vfr_clock.time_ms(vfr_clock.pts[231]) == 9220,
            "Unexpected real VFR PTS values")
    report["A07_vfr_index_only"] = dict(status="PASS", asset_id=vfr_asset["asset_id"],
        source_path=vfr_asset["relative_path"], source_sha256_from_manifest=vfr_asset["sha256"],
        source_bytes_rehashed_this_run=False, full_index_sha256_verified=True,
        pts_rows=len(vfr_clock.pts), delta_ticks=dict(Counter(b-a for a, b in zip(vfr_clock.pts, vfr_clock.pts[1:]))),
        selection=selected, excluded_endpoint=dict(frame_index=231, pts=vfr_clock.pts[231], time_ms=9220),
        limitation="Existing source-bound full PTS only; 1,055,036,097-byte original not rehashed or decoded in this run")

    general_clock = read_verified_clock(general_asset, root)
    general_records = technical_records(general_asset, general_clock)
    general_derived = derive_verified_request(request_for(general_asset, general_records), root)
    require(general_derived["source_verification"]["effective_source_usage_scope"] == "general", "Old source now restricted")
    check_all_windows(general_derived, general_clock)
    report["general_source_training_derivation"] = dict(status="PASS", manifest=general_derived,
        dead_ball_note="6000ms is an exclusive media-end boundary; no displayed source_pts invented for this terminal")

    hook_counts = Counter()

    def forbidden(name):
        def stop(*args, **kwargs):
            hook_counts[name] += 1
            raise RuntimeError(f"Forbidden renderer media/reservation call: {name}")
        return stop

    segment_training = ordinary_timeline(general_asset)
    segment_training["segments"][0]["usage_scope"] = "training_only"
    segment_provenance = ordinary_timeline(general_asset)
    segment_provenance["segments"][0]["provenance"] = {"usage_scope": "training_only"}
    variants = [
        ("training_window_manifest", derived, [asset]),
        ("explicit_training_segment", segment_training, [general_asset]),
        ("provenance_training_segment", segment_provenance, [general_asset]),
        ("general_source_training_window_manifest", general_derived, [general_asset]),
        ("original_training_asset", ordinary_timeline(asset), [asset]),
    ]
    # In-memory lineage fixture only: no derivative file or registry entry is created.
    derivative = deepcopy(general_asset)
    derivative["asset_id"] = "technical-derivative-of-training"
    derivative["provenance"].update(source_asset_id=asset["asset_id"], source_sha256=asset["sha256"])
    variants.append(("metadata_lineage_to_training", ordinary_timeline(derivative), [derivative, asset]))
    denials = []
    with ExitStack() as stack:
        for name in ("capture", "probe", "ffmpeg"):
            stack.enter_context(patch.object(engine.Runner, name, side_effect=forbidden(name)))
        stack.enter_context(patch.object(engine, "reservation", side_effect=forbidden("engine.reservation")))
        stack.enter_context(patch("packages.render.storage.reservation", side_effect=forbidden("storage.reservation")))
        for name, timeline, inputs in variants:
            for mode, params in (("normal", {}), ("preview", {"preview": True}),
                                 ("research_preview", {"preview": True, "research_preview": True})):
                job = f"contact-readonly-{name}-{mode}"
                output = f"render/jobs/{job}/attempt-1"
                require(not (root / output).exists(), "Verification output path unexpectedly exists")
                req = dict(schema_version="1.0", job_id=job, attempt_id="attempt-1", operation="render",
                           assets=deepcopy(inputs), output_dir=output,
                           parameters={"timeline": deepcopy(timeline), **params})
                result = engine.render(req, engine.RenderConfig(storage_root=root, backend="cpu"))
                require(result["status"] == "blocked" and result["error"]["code"] == "TRAINING_ONLY",
                        f"{name}/{mode} was not blocked by training gate: {result}")
                require(result["artifacts"] == [] and not (root / output).exists(), "Denial created an artifact/directory")
                require(not hook_counts and not audit.process_attempts, "Media/reservation attempted before denial")
                denials.append(dict(variant=name, mode=mode, status=result["status"], error=result["error"],
                                    artifacts=[], output_directory_created=False, media_attempts=0, reservation_attempts=0))
    report["A08_render_denials"] = dict(status="PASS", cases=denials, cases_passed=len(denials),
                                       hook_call_counts=dict(hook_counts),
                                       lineage_case_scope="in-memory metadata fixture; no physical derivative created")

    general_assets = assets_by_id(general_request["assets"])
    selected_general = list(general_assets.values())
    check_usage(selected_general, general_assets, root, research_preview=True)
    verified_paths = verify_source_bytes(selected_general, general_assets, root, lambda: None, research_preview=True)
    normalized = normalize_timeline(general_request["parameters"]["timeline"], general_assets, research_preview=True)
    require(len(verified_paths) == 3 and len(normalized["segments"]) == 3, "Old general logical regression changed")
    report["A08_general_logical_regression"] = dict(status="PASS", new_encoding_executed=False,
        scope="Current shared guard + actual three original hashes + logical research-preview normalization only",
        sources=[dict(asset_id=a["asset_id"], sha256=a["sha256"], relative_path=a["relative_path"]) for a in selected_general],
        output=normalized["output"], total_output_frames=sum(s["output_frames"] for s in normalized["segments"]),
        segments=[{k: s[k] for k in ("segment_id", "asset_id", "in_ms", "out_ms", "output_frames")} for s in normalized["segments"]])
    from packages.render.contact_windows import main as contact_cli_main
    sample_path = REPO / "configs/render/contact-windows.example.json"
    sample = read_json(sample_path)
    require(sample["asset"]["sha256"] == TRAINING_SHA, "CLI sample no longer targets fixed verified source")
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        cli_exit = contact_cli_main(["--request", str(sample_path), "--storage-root", str(root)])
    output_bytes = stdout.getvalue().encode("utf-8")
    require(cli_exit == 0 and not stderr.getvalue(), "Example CLI main returned an error")
    require(len(output_bytes) < REPORT_LIMIT, "Unexpectedly large CLI output")
    cli_result = json.loads(output_bytes)
    cli_checks = check_all_windows(cli_result, clock)
    require(cli_result["source_verification"]["actual_sha256"] == TRAINING_SHA,
            "CLI main did not return actual source verification")
    require(cli_result["source_verification"]["effective_source_usage_scope"] == "training_only",
            "CLI main downgraded source usage")
    report["A07_example_cli_main"] = dict(status="PASS", execution="in-process public main(argv), no shell/subprocess",
        request_path="configs/render/contact-windows.example.json", request_sha256=sha256(sample_path),
        request_bytes=sample_path.stat().st_size, argv=["--request", str(sample_path), "--storage-root", str(root)],
        exit_code=cli_exit, stdout_bytes=len(output_bytes), stdout_sha256=hashlib.sha256(output_bytes).hexdigest(),
        stderr_bytes=0, windows_count=len(cli_result["windows"]), usage_scope=cli_result["usage_scope"],
        source_verification=cli_result["source_verification"], content_sha256=cli_result["content_sha256"],
        independent_half_open_frame_checks=cli_checks,
        limitation="Exercises the real CLI parser/main adapter in this interpreter; not a separate launched CLI process")
    after = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in tracked}
    require(before == after, "Tracked input metadata changed during run")
    require(sha256(root / REGISTRY) == registry_before, "Trusted registry bytes changed")
    source_hash_after = sha256(root / asset["relative_path"])
    ui_hash_after = sha256(root / UI_SNAPSHOT_PATH)
    require(source_hash_after == source_verified["actual_sha256"] == TRAINING_SHA, "Verified b210 source bytes changed")
    require(ui_hash_after == UI_SNAPSHOT_FILE_SHA, "Root UI snapshot bytes changed during verification")
    require(not audit.process_attempts and not audit.forbidden_write_attempts and not hook_counts,
            "Read-only/media-free safety checks failed")
    report["read_only_evidence"] = dict(tracked_input_stat_entries=len(before), input_sizes_and_mtimes_unchanged=True,
        registry_sha256_after=registry_before, process_attempts=audit.process_attempts,
        forbidden_write_attempts=audit.forbidden_write_attempts, renderer_hook_attempts=dict(hook_counts),
        shared_storage_files_written=0, shared_storage_reservations=0,
        real_source_sha256_before=source_verified["actual_sha256"], real_source_sha256_after=source_hash_after,
        root_ui_snapshot_sha256_before=UI_SNAPSHOT_FILE_SHA, root_ui_snapshot_sha256_after=ui_hash_after)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, default=Path("D:/video" if os.name == "nt" else "/mnt/d/video"))
    args = parser.parse_args(argv)
    root = args.storage_root.resolve(strict=True)
    audit = ReadOnlyAudit()
    sys.addaudithook(audit)
    report = dict(schema_version="1.0", format="badmintonTV.render-contact-windows-verification",
        started_at=now(), status="RUNNING", storage_root=str(root), python=sys.executable,
        command="python -B scripts/render/verify_contact_windows.py --storage-root D:/video",
        technical_marks_origin="agent_fixture_not_human_action_truth", gpu_used=False, media_processes_allowed=False,
        code_sha256={name: sha256(REPO / name) for name in (
            "scripts/render/verify_contact_windows.py", "packages/render/contact_windows.py",
            "packages/render/training_window_adapter.py", "packages/contracts/training.py",
            "packages/contracts/fixtures/training.taxonomy.provisional.v1.json",
            "packages/render/usage.py", "packages/render/timeline.py", "packages/render/engine.py")},
        limits=dict(report_max_bytes=REPORT_LIMIT, shared_storage_new_bytes=0),
        limitations=["No human action/identity/rally truth, training accuracy, or annotation semantics validated",
            "No new media decoding, encoding, ffprobe, image extraction or general-output playback",
            "A08 covers render boundary only; platform import/candidate/Timeline APIs and browser chain require separate verification",
            "VFR original is not rehashed; only its existing source-bound complete PTS is verified",
            "Python audit hook and renderer sentinels observe this verifier process, not other concurrent processes"])
    try:
        verify(root, audit, report)
        report["code_sha256_after"] = {name: sha256(REPO / name) for name in report["code_sha256"]}
        require(report["code_sha256"] == report["code_sha256_after"], "Verified source code changed during this run")
        report["status"] = "PASS"
    except Exception as exc:
        report["status"] = "FAIL"
        report["failure"] = dict(type=type(exc).__name__, message=str(exc))
    report["completed_at"] = now()
    report["audit"] = dict(process_attempts=audit.process_attempts, forbidden_write_attempts=audit.forbidden_write_attempts,
                           report_write_policy="only fixed workspace JSON allowed; no shared storage writes")
    encoded = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    require(len(encoded) < REPORT_LIMIT, "Report exceeds fixed 500 KB bound")
    REPORT.write_bytes(encoded)
    print(json.dumps(dict(status=report["status"], report=str(REPORT), report_bytes=len(encoded),
                          failure=report.get("failure"),
                          render_denials=report.get("A08_render_denials", {}).get("cases_passed", 0)), ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
