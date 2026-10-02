"""Public training fixtures stay revision-bound, lossless review-window inputs."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from packages.contracts import Asset
from packages.contracts.training import (
    TrainingAnnotationBundle, TrainingSnapshot, training_content_sha256,
)
from packages.render.contact_windows import SourceClock, WindowError
from packages.render.training_window_adapter import derive_training_bundle, derive_training_snapshot


FIXTURES = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def canonical_asset(reference):
    # Contract fixtures contain references only; these dimensions/identity describe
    # a synthetic test source and do not claim that a real media file exists.
    return Asset.model_validate({
        **{key: deepcopy(reference[key]) for key in (
            "asset_id", "relative_path", "sha256", "size_bytes", "duration_ms", "usage_scope",
        )},
        "schema_version": "1.0", "width": 640, "height": 360, "fps_num": 25, "fps_den": 1,
        "time_base": "1/1000", "source_type": "synthetic", "match_id": "synthetic-unconfirmed-fixture",
        "provenance": {"fixture": "Metadata only; no real media or expert truth"},
    }).model_dump(mode="json")


def record(bundle, record_id):
    return next(item for item in bundle["records"] if item["record_id"] == record_id)


def phase_binding(**changes):
    return {"record_id": "segment-1", "revision": 1, "anchor_id": "contact-1",
            "anchor_revision": 1, "phase": "stroke_support", **changes}


def find_window(result, strategy, anchor_id):
    key = "rally_id" if strategy == "rally" else "anchor_id"
    values = [item for item in result["windows"] if item["strategy"] == strategy and item[key] == anchor_id]
    if len(values) != 1:
        raise AssertionError(f"Expected one {strategy}/{anchor_id} window, got {len(values)}")
    return values[0]


def bound_clock(bundle, pts, time_base="1/1000", origin_pts=None):
    """Freeze synthetic index metadata before supplying its in-memory clock."""
    reference = deepcopy(bundle["asset"]["pts_reference"])
    reference.update(frame_count=len(pts), time_base=time_base, size_bytes=4096, complete=True)
    bundle["asset"]["pts_reference"] = reference
    return SourceClock(pts, time_base, origin_pts=origin_pts, reference=reference)


class TrainingBundleAdapterTests(unittest.TestCase):
    def setUp(self):
        self.bundle = fixture("training.annotations.v1.json")
        self.asset = canonical_asset(self.bundle["asset"])
        self.version = fixture("training.taxonomy.provisional.v1.json")["version"]

    def adapt(self, bundle=None, asset=None, **options):
        return derive_training_bundle(self.asset if asset is None else asset,
                                      self.bundle if bundle is None else bundle,
                                      vocabulary_version=self.version, **options)

    def test_contract_fixture_maps_point_interval_person_without_media_or_input_changes(self):
        before = deepcopy((self.bundle, self.asset))
        canonical = TrainingAnnotationBundle.model_validate(self.bundle).model_dump(mode="json")
        for typed in (False, True):
            with self.subTest(typed=typed), patch("subprocess.run") as run, \
                    patch("subprocess.Popen") as popen, patch("packages.render.storage.reservation") as reserve:
                bundle = TrainingAnnotationBundle.model_validate(self.bundle) if typed else self.bundle
                asset = Asset.model_validate(self.asset) if typed else self.asset
                result = self.adapt(bundle, asset, phase_bindings=[phase_binding()])
                run.assert_not_called()
                popen.assert_not_called()
                reserve.assert_not_called()
                mapped = {item["record_id"]: item for item in result["annotations"]}
                self.assertEqual(mapped["contact-1"]["time_ms"], 2000)
                self.assertNotIn("start_ms", mapped["contact-1"])
                self.assertEqual(mapped["contact-1"]["player_id"], "person-a")
                self.assertEqual(mapped["contact-1"]["team_id"], "team-a")
                self.assertEqual(mapped["rally-1"]["rally_id"], "rally-1")
                self.assertEqual(mapped["rally-1"]["start_ms"], 1000)
                self.assertEqual(mapped["rally-1"]["end_ms"], 5000)
                self.assertEqual(mapped["dead-1"]["time_ms"], 5000)
                self.assertEqual(mapped["segment-1"]["kind"], "movement")
                self.assertEqual(mapped["segment-1"]["anchor_id"], "contact-1")
                self.assertEqual(mapped["segment-1"]["start_ms"], 1800)
                self.assertEqual(mapped["segment-1"]["end_ms"], 2300)
                self.assertEqual(result["training_adapter"]["annotation_bundle"], canonical)
                self.assertEqual(result["usage_scope"], "training_only")
                self.assertFalse(result["production_eligible"])
                self.assertNotIn("segments", result)
                self.assertEqual((self.bundle, self.asset), before)

    def test_unknown_coarse_labels_and_multiple_subjects_remain_distinct_list_entries(self):
        mark = record(self.bundle, "contact-1")
        mark["state"] = deepcopy(record(self.bundle, "state-1")["state"])
        for person_id, team_id, role in (("person-c", "team-a", "partner"),
                                         ("person-d", "team-b", "opponent_partner")):
            self.bundle["people"].append({"person_id": person_id, "display_name": "Synthetic " + person_id,
                                          "team_id": team_id, "identity_status": "confirmed"})
            mark["state"][role] = {"person_id": person_id, "team_id": team_id}
        mark["judgements"][0].update(subject_person_id="person-a", mapping_status="coarse", source_label="legacy-net")
        for role, person_id, value, reason in (("opponent", "person-b", "unknown", "Opponent racket hidden"),
                                               ("partner", "person-c", "not_applicable", "Partner is not hitting"),
                                               ("opponent_partner", "person-d", "unobservable", "Outside frame")):
            mark["judgements"].append({
                "label_id": "stroke.net_shot", "subject_role": role, "subject_person_id": person_id,
                "value": value, "reason": reason, "mapping_status": "unverified",
            })
        mark["raw_labels"] = ["legacy-net"]
        mark["unknown_reasons"] = ["Fine wrist detail unavailable"]
        canonical = TrainingAnnotationBundle.model_validate(self.bundle).model_dump(mode="json")
        expected = record(canonical, "contact-1")
        result = self.adapt()
        for strategy in ("ball_flight", "hand_technique", "footwork"):
            row = find_window(result, strategy, "contact-1")
            self.assertIsInstance(row["labels"], list)
            self.assertEqual(row["labels"], expected["judgements"])
            self.assertEqual({label["subject_role"] for label in row["labels"]},
                             {"self", "opponent", "partner", "opponent_partner"})
        mapped = next(item for item in result["annotations"] if item["record_id"] == "contact-1")
        self.assertEqual(mapped["original_record"], expected)
        self.assertEqual(mapped["review"], expected["review"])
        self.assertEqual(mapped["unknown_reason"], "Fine wrist detail unavailable")
        self.assertEqual(result["training_adapter"]["annotation_bundle"], canonical)

    def test_serve_requires_explicit_revision_reference_not_first_contact_inference(self):
        implicit = self.adapt()
        rally = find_window(implicit, "rally", "rally-1")
        self.assertEqual(rally["status"], "unavailable")
        self.assertIsNone(rally["range"])
        self.assertIn("missing_serve", rally["reasons"])
        explicit = self.adapt(serve_mark_refs=[{"record_id": "contact-1", "revision": 1}])
        rally = find_window(explicit, "rally", "rally-1")
        self.assertEqual(rally["range"], {"start_ms": 2000, "end_ms": 5000})
        self.assertEqual(rally["status"], "ready")
        self.assertEqual(explicit["training_adapter"]["serve_mark_refs"], [{"record_id": "contact-1", "revision": 1}])

    def test_stale_serve_segment_and_anchor_revisions_reject_before_derivation(self):
        cases = (
            {"serve_mark_refs": [{"record_id": "contact-1", "revision": 2}]},
            {"phase_bindings": [phase_binding(revision=2)]},
            {"phase_bindings": [phase_binding(anchor_revision=2)]},
        )
        for options in cases:
            with self.subTest(options=options), patch("packages.render.training_window_adapter.derive_contact_windows") as derive:
                with self.assertRaises(WindowError) as raised:
                    self.adapt(**options)
                self.assertEqual(raised.exception.code, "revision_conflict")
                derive.assert_not_called()

    def test_mapping_missing_revision_wrong_kind_and_inactive_records_are_rejected(self):
        cases = [
            (self.bundle, {"serve_mark_refs": [{"record_id": "contact-1"}]}),
            (self.bundle, {"serve_mark_refs": [{"record_id": "dead-1", "revision": 1}]}),
            (self.bundle, {"phase_bindings": [phase_binding(record_id="state-1")]}),
        ]
        for flag in ("deleted", "rejected"):
            bundle = deepcopy(self.bundle)
            mark = record(bundle, "contact-1")
            if flag == "deleted":
                mark["deleted"] = True
            else:
                mark["review"]["status"] = "rejected"
            cases.append((bundle, {"serve_mark_refs": [{"record_id": "contact-1", "revision": 1}]}))
        for index, (bundle, options) in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(WindowError):
                self.adapt(bundle, **options)

    def test_phase_anchor_must_match_person(self):
        with self.assertRaises(WindowError) as raised:
            self.adapt(phase_bindings=[phase_binding(anchor_id="contact-2")])
        self.assertEqual(raised.exception.code, "relation_mismatch")

    def test_phase_anchor_must_match_rally_even_for_the_same_person(self):
        second_rally = deepcopy(record(self.bundle, "rally-1"))
        second_rally.update(record_id="rally-2", start_ms=6000, end_ms=9000, dead_ball_id="dead-2")
        second_dead = deepcopy(record(self.bundle, "dead-1"))
        second_dead.update(record_id="dead-2", rally_id="rally-2", at_ms=9000)
        second_contact = deepcopy(record(self.bundle, "contact-1"))
        second_contact.update(record_id="contact-3", rally_id="rally-2", at_ms=7000)
        self.bundle["records"].extend([second_rally, second_dead, second_contact])
        TrainingAnnotationBundle.model_validate(self.bundle)
        with self.assertRaises(WindowError) as raised:
            self.adapt(phase_bindings=[phase_binding(anchor_id="contact-3")])
        self.assertEqual(raised.exception.code, "relation_mismatch")

    def test_complete_six_phases_with_unknown_or_unobservable_visibility_are_candidates(self):
        template = deepcopy(record(self.bundle, "segment-1"))
        self.bundle["records"] = [item for item in self.bundle["records"] if item["record_id"] != "segment-1"]
        bindings = []
        for phase, start, end in (("preparation", 1200, 1400), ("initiation", 1400, 1600),
                                  ("arrival", 1600, 1800), ("stroke_support", 1800, 2100),
                                  ("landing", 2100, 2300), ("recovery", 2300, 2600)):
            stage = deepcopy(template)
            stage.update(record_id="phase-" + phase, start_ms=start, end_ms=end, unknown_reasons=[])
            self.bundle["records"].append(stage)
            bindings.append(phase_binding(record_id=stage["record_id"], phase=phase))
        for visibility in ("clear", "unknown", "unobservable"):
            with self.subTest(visibility=visibility):
                for item in self.bundle["records"]:
                    if item["kind"] == "segment":
                        item["visibility"] = visibility
                result = self.adapt(phase_bindings=bindings)
                item = find_window(result, "footwork", "contact-1")
                self.assertEqual(item["range"], {"start_ms": 1200, "end_ms": 2600})
                if visibility == "clear":
                    self.assertEqual(item["status"], "ready")
                else:
                    self.assertEqual(item["status"], "candidate")
                    self.assertIn("uncertain_phases", item["reasons"])

    def test_excluded_records_have_reasons_and_remain_in_original_bundle(self):
        record(self.bundle, "contact-2")["deleted"] = True
        rejected = deepcopy(record(self.bundle, "contact-1"))
        rejected.update(record_id="contact-rejected", at_ms=3500)
        rejected["review"]["status"] = "rejected"
        unassigned = deepcopy(record(self.bundle, "contact-1"))
        unassigned.update(record_id="contact-unassigned", rally_id=None, at_ms=4000)
        self.bundle["records"].extend([rejected, unassigned])
        canonical = TrainingAnnotationBundle.model_validate(self.bundle).model_dump(mode="json")
        result = self.adapt()
        excluded = {item["record_id"]: item["reason"] for item in result["training_adapter"]["excluded_records"]}
        self.assertEqual(excluded, {
            "contact-2": "deleted_or_rejected", "contact-rejected": "deleted_or_rejected",
            "contact-unassigned": "no_active_rally_assignment",
            "state-1": "state_retained_as_annotation_not_a_boundary",
            "segment-1": "segment_has_no_explicit_phase_binding",
        })
        self.assertEqual(result["training_adapter"]["annotation_bundle"], canonical)
        self.assertFalse(set(excluded) & {item["record_id"] for item in result["annotations"]})

    def test_unassigned_contact_inside_range_prevents_ready_without_inventing_rally_assignment(self):
        boundary = record(self.bundle, "contact-2")
        boundary.update(rally_id=None, at_ms=6000)
        before = find_window(self.adapt(), "ball_flight", "contact-1")
        self.assertEqual(before["range"], {"start_ms": 2000, "end_ms": 5000})
        self.assertEqual(before["status"], "ready")
        boundary["at_ms"] = 3000
        canonical = TrainingAnnotationBundle.model_validate(self.bundle).model_dump(mode="json")
        result = self.adapt()
        item = find_window(result, "ball_flight", "contact-1")
        self.assertEqual(item["range"], before["range"])
        self.assertEqual(item["status"], "candidate")
        self.assertIn("unassigned_boundary_in_range", item["reasons"])
        self.assertEqual(item["unresolved_boundary_refs"], [{"record_id": "contact-2", "revision": 1}])
        self.assertIn({"record_id": "contact-2", "revision": 1}, item["annotation_refs"])
        self.assertNotEqual(item["window_id"], before["window_id"])
        self.assertFalse(any(row["record_id"] == "contact-2" for row in result["annotations"]))
        self.assertEqual(result["training_adapter"]["annotation_bundle"], canonical)
        self.assertIsNone(record(result["training_adapter"]["annotation_bundle"], "contact-2")["rally_id"])

    def test_edit_to_excluded_annotation_invalidates_window_id_without_changing_range(self):
        before = find_window(self.adapt(), "ball_flight", "contact-1")
        self.bundle["revision"] = 2
        record(self.bundle, "state-1").update(revision=2, previous_revision=1,
                                              provenance={"note": "New state evidence; retained for review"})
        after = find_window(self.adapt(), "ball_flight", "contact-1")
        self.assertEqual(after["range"], before["range"])
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["annotation_refs"], before["annotation_refs"])
        self.assertNotEqual(after["window_id"], before["window_id"])

    def test_public_at_ms_and_frame_index_evidence_map_to_source_time_without_mutating_raw(self):
        clock = bound_clock(self.bundle, [9000, 11000, 12000, 14000, 17500])
        for evidence, supplied_clock in (({"at_ms": 8500}, None), ({"source_frame_index": 4}, clock),
                                         ({"frame_index": 4}, clock), ({"source_pts": 17500}, clock)):
            with self.subTest(evidence=evidence):
                bundle = deepcopy(self.bundle)
                record(bundle, "contact-1")["evidence"] = [deepcopy(evidence)]
                result = self.adapt(bundle, clock=supplied_clock)
                mapped = next(item for item in result["annotations"] if item["record_id"] == "contact-1")
                self.assertEqual(mapped["original_record"]["evidence"], [evidence])
                self.assertEqual(record(result["training_adapter"]["annotation_bundle"], "contact-1")["evidence"], [evidence])
                item = find_window(result, "hand_technique", "contact-1")
                self.assertEqual(item["latest_source_time_ms"], 8500)
                self.assertEqual(item["lookahead_ms"], 6500)
                self.assertTrue(item["future_context_used"])
                self.assertNotIn("evidence_time_unresolved", item["reasons"])
                self.assertEqual(record(bundle, "contact-1")["evidence"], [evidence])

    def test_declared_evidence_time_cannot_override_conflicting_frame_or_pts(self):
        clock = bound_clock(self.bundle, list(range(0, 10000, 40)))
        for evidence in ({"at_ms": 1000, "source_frame_index": 199, "source_pts": 7960},
                         {"at_ms": 1000, "frame_index": 199, "source_pts": 7960},
                         {"at_ms": 1000, "source_pts": 7960}):
            with self.subTest(evidence=evidence):
                bundle = deepcopy(self.bundle)
                record(bundle, "contact-1")["evidence"] = [evidence]
                with self.assertRaises(WindowError) as raised:
                    self.adapt(bundle, clock=clock)
                self.assertEqual(raised.exception.code, "invalid_pts")
        record(self.bundle, "contact-1")["evidence"] = [{"at_ms": 7960, "source_frame_index": 199, "source_pts": 7960}]
        result = self.adapt(clock=clock)
        self.assertEqual(find_window(result, "hand_technique", "contact-1")["latest_source_time_ms"], 7960)

    def test_conflicting_frame_index_aliases_are_rejected(self):
        clock = bound_clock(self.bundle, list(range(0, 10000, 40)))
        record(self.bundle, "contact-1")["evidence"] = [
            {"at_ms": 1000, "source_frame_index": 25, "frame_index": 199},
        ]
        with self.assertRaises(WindowError) as raised:
            self.adapt(clock=clock)
        self.assertEqual(raised.exception.code, "invalid_pts")

    def test_frame_or_pts_evidence_without_clock_keeps_unknown_full_source_watermark(self):
        for evidence in ({"at_ms": 1000, "source_frame_index": 199}, {"at_ms": 1000, "source_pts": 7960}):
            with self.subTest(evidence=evidence):
                bundle = deepcopy(self.bundle)
                record(bundle, "contact-1")["evidence"] = [evidence]
                item = find_window(self.adapt(bundle), "hand_technique", "contact-1")
                self.assertEqual(item["status"], "candidate")
                self.assertIn("evidence_time_unresolved", item["reasons"])
                self.assertEqual(item["latest_source_time_ms"], self.asset["duration_ms"])

    def test_external_reference_only_keeps_unknown_timing_and_conservative_source_bound(self):
        evidence = {"reference": "review-note-synthetic"}
        record(self.bundle, "contact-1")["evidence"] = [evidence]
        result = self.adapt()
        mapped = next(item for item in result["annotations"] if item["record_id"] == "contact-1")
        self.assertEqual(mapped["evidence"], [evidence])
        self.assertEqual(mapped["latest_evidence_ms"], self.asset["duration_ms"])
        self.assertEqual(mapped["evidence_time_status"], "unresolved_bounded_by_source_duration")
        item = find_window(result, "hand_technique", "contact-1")
        self.assertEqual(item["status"], "candidate")
        self.assertIn("evidence_time_unresolved", item["reasons"])
        self.assertEqual(item["latest_source_time_ms"], self.asset["duration_ms"])
        self.assertIsNone(item["wait_ms"])
        self.assertEqual(record(result["training_adapter"]["annotation_bundle"], "contact-1")["evidence"], [evidence])

    def test_unassigned_boundary_evidence_updates_window_watermark_without_losing_roi_or_unknown(self):
        boundary = record(self.bundle, "contact-2")
        boundary["rally_id"] = None
        boundary["evidence"] = [{"type": "source_time", "at_ms": 8500,
                                 "roi": {"x": 10, "y": 20, "width": 30, "height": 40},
                                 "visibility": "unknown"}]
        original = deepcopy(self.bundle)
        canonical = TrainingAnnotationBundle.model_validate(self.bundle).model_dump(mode="json")
        result = self.adapt()
        item = find_window(result, "ball_flight", "contact-1")
        self.assertEqual(item["range"], {"start_ms": 2000, "end_ms": 5000})
        self.assertEqual(item["status"], "candidate")
        self.assertEqual(item["latest_source_time_ms"], 8500)
        self.assertEqual(item["lookahead_ms"], 6500)
        self.assertTrue(item["future_context_used"])
        self.assertEqual(item["wait_ms"], 0)
        self.assertIn({"record_id": "contact-2", "revision": 1}, item["annotation_refs"])
        self.assertNotIn("evidence_time_unresolved", item["reasons"])
        # The shorter hand window does not use this unassigned point.
        hand = find_window(result, "hand_technique", "contact-1")
        self.assertEqual(hand["latest_source_time_ms"], 5000)
        self.assertNotIn({"record_id": "contact-2", "revision": 1}, hand["annotation_refs"])
        self.assertEqual(result["training_adapter"]["annotation_bundle"], canonical)
        self.assertEqual(self.bundle, original)

    def test_unassigned_boundary_uses_uncertainty_upper_bound_as_evidence(self):
        boundary = record(self.bundle, "contact-2")
        boundary.update(rally_id=None, uncertainty_start_ms=2500, uncertainty_end_ms=8800)
        boundary["evidence"] = [{"at_ms": 8500}]
        item = find_window(self.adapt(), "ball_flight", "contact-1")
        self.assertEqual(item["latest_source_time_ms"], 8800)
        self.assertEqual(item["lookahead_ms"], 6800)

    def test_unassigned_frame_pts_evidence_uses_the_same_clock_and_alias_checks(self):
        clock = bound_clock(self.bundle, list(range(0, 10000, 40)))
        boundary = record(self.bundle, "contact-2")
        boundary["rally_id"] = None
        for evidence in ({"source_frame_index": 199}, {"frame_index": 199}, {"source_pts": 7960},
                         {"at_ms": 7960, "time_ms": 7960, "source_pts": 7960, "source_frame_index": 199}):
            with self.subTest(evidence=evidence):
                boundary["evidence"] = [evidence]
                item = find_window(self.adapt(clock=clock), "ball_flight", "contact-1")
                self.assertEqual(item["latest_source_time_ms"], 7960)
                self.assertEqual(item["lookahead_ms"], 5960)
                self.assertNotIn("evidence_time_unresolved", item["reasons"])
        for evidence in ({"at_ms": 1000, "source_frame_index": 199},
                         {"source_frame_index": 25, "frame_index": 199},
                         {"source_frame_index": 199, "source_pts": 1000}):
            with self.subTest(conflicting_evidence=evidence):
                boundary["evidence"] = [evidence]
                with self.assertRaises(WindowError) as raised:
                    self.adapt(clock=clock)
                self.assertEqual(raised.exception.code, "invalid_pts")

    def test_unassigned_unknown_evidence_remains_candidate_with_full_source_watermark(self):
        boundary = record(self.bundle, "contact-2")
        boundary["rally_id"] = None
        for evidence in ({"reference": "unresolved-review", "roi": [10, 20, 30, 40]},
                         {"at_ms": 1000, "source_frame_index": 199}):
            with self.subTest(evidence=evidence):
                boundary["evidence"] = [deepcopy(evidence)]
                result = self.adapt()
                item = find_window(result, "ball_flight", "contact-1")
                self.assertEqual(item["status"], "candidate")
                self.assertEqual(item["latest_source_time_ms"], self.asset["duration_ms"])
                self.assertEqual(item["lookahead_ms"], 8000)
                self.assertIn("evidence_time_unresolved", item["reasons"])
                self.assertIsNone(item["wait_ms"])
                self.assertEqual(record(result["training_adapter"]["annotation_bundle"], "contact-2")["evidence"], [evidence])

    def test_unassigned_time_alias_and_interval_conflicts_are_rejected_by_shared_rules(self):
        boundary = record(self.bundle, "contact-2")
        boundary["rally_id"] = None
        for evidence in ({"at_ms": 8500, "time_ms": 1000},
                         {"at_ms": 8500, "start_ms": 1000, "end_ms": 2000}):
            with self.subTest(evidence=evidence):
                boundary["evidence"] = [evidence]
                with self.assertRaises(WindowError):
                    self.adapt()
        boundary["evidence"] = [{"at_ms": 8200, "time_ms": 8200, "start_ms": 8000, "end_ms": 8500}]
        item = find_window(self.adapt(), "ball_flight", "contact-1")
        self.assertEqual(item["latest_source_time_ms"], 8500)

    def test_frozen_pts_path_alias_and_equivalent_time_base_are_bound(self):
        clock = bound_clock(self.bundle, list(range(0, 10000, 40)))
        reference = self.bundle["asset"]["pts_reference"]
        reference["path"] = reference.pop("relative_path")
        clock.reference["time_base"] = "2/2000"
        clock.reference["sha256"] = clock.reference["sha256"].upper()
        self.assertEqual(find_window(self.adapt(clock=clock), "ball_flight", "contact-1")["pts"]["status"], "mapped")
        clock.reference["path"] = "data/training/synthetic/wrong-index.jsonl"
        with self.assertRaises(WindowError) as raised:
            self.adapt(clock=clock)
        self.assertEqual(raised.exception.code, "invalid_pts")

    def test_source_asset_must_match_reference_identity_hash_path_and_measurements(self):
        for key, value in (("asset_id", "another-asset"), ("sha256", "c" * 64),
                           ("relative_path", "data/training/another.mp4"), ("size_bytes", 1001),
                           ("duration_ms", 10001)):
            with self.subTest(field=key), patch("packages.render.training_window_adapter.derive_contact_windows") as derive:
                asset = {**self.asset, key: value}
                with self.assertRaises(WindowError) as raised:
                    self.adapt(asset=asset)
                self.assertEqual(raised.exception.code, "asset_mismatch")
                derive.assert_not_called()


class TrainingSnapshotAdapterTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = fixture("training.snapshot.v1.json")
        self.asset = canonical_asset(self.snapshot["assets"][0])

    def test_snapshot_reference_keeps_hash_scope_and_quality_blockers(self):
        original = deepcopy(self.snapshot)
        validated = TrainingSnapshot.model_validate(self.snapshot)
        for snapshot in (self.snapshot, validated):
            with self.subTest(typed=isinstance(snapshot, TrainingSnapshot)):
                result = derive_training_snapshot(self.asset, snapshot)
                ref = result["snapshot_reference"]
                self.assertEqual(ref["snapshot_id"], original["snapshot_id"])
                self.assertEqual(ref["content_sha256"], original["content_sha256"])
                self.assertEqual(ref["project_revision"], original["project"]["revision"])
                self.assertEqual(ref["taxonomy_version"], original["taxonomy"]["version"])
                self.assertEqual(ref["quality_summary"], original["quality_summary"])
                self.assertFalse(ref["quality_summary"]["trainable"])
                self.assertEqual(ref["quality_summary"]["eligible_judgement_count"], 0)
                self.assertTrue(ref["quality_summary"]["blockers"])
                self.assertEqual(result["usage_scope"], "training_only")
                self.assertFalse(result["production_eligible"])
                self.assertEqual(result["training_truth"], "not_determined_by_window_derivation")
                self.assertEqual(self.snapshot, original)
                self.assertEqual(validated.model_dump(mode="json"), original)

    def snapshot_clock(self):
        clock = bound_clock(self.snapshot["bundles"][0], list(range(0, 10000, 40)))
        self.snapshot["assets"][0]["pts_reference"] = deepcopy(self.snapshot["bundles"][0]["asset"]["pts_reference"])
        self.snapshot["content_sha256"] = training_content_sha256(self.snapshot)
        TrainingSnapshot.model_validate(self.snapshot)
        return clock

    def test_frozen_snapshot_reference_rejects_another_or_unidentified_clock(self):
        clock = self.snapshot_clock()
        original = deepcopy(self.snapshot)
        for changes in ({"format": "different-format"}, {"relative_path": "data/training/different.pts"},
                        {"sha256": "c" * 64}, {"size_bytes": 4097}, {"frame_count": 249},
                        {"time_base": "1/2000"}, {"complete": False},
                        {"source_sha256": "d" * 64}):
            with self.subTest(changes=changes):
                other = SourceClock(clock.pts, clock.time_base, reference={**clock.reference, **changes})
                with self.assertRaises(WindowError) as raised:
                    derive_training_snapshot(self.asset, self.snapshot, clock=other)
                self.assertEqual(raised.exception.code, "invalid_pts")
        for missing in (None, "format", "relative_path", "sha256", "size_bytes", "frame_count", "time_base", "complete"):
            with self.subTest(missing=missing):
                reference = deepcopy(clock.reference) if missing else {}
                if missing:
                    reference.pop(missing)
                other = SourceClock(clock.pts, clock.time_base, reference=reference)
                with self.assertRaises(WindowError) as raised:
                    derive_training_snapshot(self.asset, self.snapshot, clock=other)
                self.assertEqual(raised.exception.code, "invalid_pts")
        self.assertEqual(self.snapshot, original)

    def test_frozen_snapshot_count_and_time_base_are_checked_against_actual_clock(self):
        clock = self.snapshot_clock()
        for pts, time_base in ((clock.pts[:-1], clock.time_base), (clock.pts, "1/2000")):
            with self.subTest(count=len(pts), time_base=str(time_base)):
                other = SourceClock(pts, time_base, reference=clock.reference)
                with self.assertRaises(WindowError) as raised:
                    derive_training_snapshot(self.asset, self.snapshot, clock=other)
                self.assertEqual(raised.exception.code, "invalid_pts")

    def test_matching_frozen_snapshot_clock_maps_and_omitted_clock_remains_not_provided(self):
        clock = self.snapshot_clock()
        original = deepcopy(self.snapshot)
        mapped = derive_training_snapshot(self.asset, self.snapshot, clock=clock)
        item = find_window(mapped, "ball_flight", "contact-1")
        self.assertEqual(item["pts"]["status"], "mapped")
        self.assertEqual(item["pts"]["reference"], original["assets"][0]["pts_reference"])
        self.assertEqual(item["pts"]["frame_count"], 25)
        omitted = derive_training_snapshot(self.asset, self.snapshot)
        self.assertTrue(all(item["pts"]["status"] == "not_provided" for item in omitted["windows"]))
        self.assertEqual(mapped["snapshot_reference"]["content_sha256"], original["content_sha256"])
        self.assertEqual(self.snapshot, original)

    def test_changed_snapshot_without_new_hash_is_rejected_before_bundle_adapter(self):
        self.snapshot["snapshot_id"] = "tampered-snapshot"
        with patch("packages.render.training_window_adapter.derive_training_bundle") as adapt:
            with self.assertRaises(ValueError):
                derive_training_snapshot(self.asset, self.snapshot)
        adapt.assert_not_called()

    def test_recomputed_hash_cannot_relax_scope_or_forge_quality(self):
        for field in ("usage_scope", "quality_summary"):
            with self.subTest(field=field):
                snapshot = deepcopy(self.snapshot)
                if field == "usage_scope":
                    snapshot[field] = "general"
                else:
                    snapshot[field]["trainable"] = True
                    snapshot[field]["blockers"] = []
                snapshot["content_sha256"] = training_content_sha256(snapshot)
                with patch("packages.render.training_window_adapter.derive_training_bundle") as adapt:
                    with self.assertRaises(ValueError):
                        derive_training_snapshot(self.asset, snapshot)
                adapt.assert_not_called()

    def test_snapshot_does_not_select_a_different_asset_bundle(self):
        with self.assertRaises(WindowError) as raised:
            derive_training_snapshot({**self.asset, "asset_id": "missing-source"}, self.snapshot)
        self.assertEqual(raised.exception.code, "relation_mismatch")


if __name__ == "__main__":
    unittest.main()
