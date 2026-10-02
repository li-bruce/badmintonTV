"""Preparation boundary tests; synthetic metadata is not real annotation truth."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from packages.models.training_prepare import bind_source, choose_records, prepare_windows
from packages.models.training_sources import SourceError
from scripts.models.build_agent_training_demo import source_usage_scope


class Value:
    def __init__(self, **data):
        self.__dict__.update(data)

    def model_dump(self, **_kwargs):
        return deepcopy(self.__dict__)


def example_snapshot():
    asset = Value(asset_id="asset-a", relative_path="data/training/a.mp4", sha256="a"*64,
                  size_bytes=100, duration_ms=2000,
                  pts_reference={"relative_path":"data/training/a.jsonl", "sha256":"b"*64,
                                 "size_bytes":80, "frame_count":20, "time_base":"1/1000"})
    def record(identifier, kind, at=None, start=None, end=None, deleted=False):
        return Value(asset_id="asset-a", record_id=identifier, revision=2, deleted=deleted,
                     kind=kind, at_ms=at, start_ms=start, end_ms=end,
                     review={"reviewer_type":"agent","status":"draft"}, visibility="unknown")
    bundle = SimpleNamespace(asset=asset, records=[record("point", "contact", at=10),
                              record("clip", "segment", start=0, end=1000),
                              record("rally", "rally", start=0, end=1500),
                              record("deleted", "segment", start=0, end=1000, deleted=True)])
    return SimpleNamespace(assets=[asset], bundles=[bundle])


class PreparationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = example_snapshot()
        self.ref = self.snapshot.assets[0].model_dump()
        self.asset = {**self.ref, "probe":{"pts_index":self.ref["pts_reference"]}}

    def test_source_hash_alone_does_not_bind_timing_or_path(self):
        for field, bad in (("relative_path", "data/other.mp4"), ("duration_ms", 1001), ("size_bytes", 101)):
            with self.subTest(field=field):
                reference = deepcopy(self.ref)
                reference[field] = bad
                with self.assertRaisesRegex(SourceError, "identity differs"):
                    bind_source(reference, self.asset)

    def test_pts_must_be_frozen_and_match_library_index(self):
        bind_source(self.ref, self.asset)
        for field in ("relative_path", "sha256", "size_bytes", "frame_count", "time_base"):
            reference = deepcopy(self.ref)
            reference["pts_reference"].pop(field)
            with self.assertRaisesRegex(SourceError, "PTS reference differs"):
                bind_source(reference, self.asset)
        reference = deepcopy(self.ref)
        reference["pts_reference"] = None
        with self.assertRaisesRegex(SourceError, "freeze a PTS"):
            bind_source(reference, self.asset)

    def test_default_does_not_invent_point_context_or_dead_ball(self):
        records = choose_records(self.snapshot, [], 8)
        self.assertEqual([r["record_id"] for r in records], ["clip"])

    def test_selection_requires_asset_identity_and_live_record(self):
        for selection in (["point"], ["asset-b/point"], ["asset-a/deleted"], ["asset-a/point"]*2):
            with self.subTest(selection=selection), self.assertRaises(SourceError):
                choose_records(self.snapshot, selection, 8)
        with self.assertRaisesRegex(SourceError, "exceed limit"):
            choose_records(self.snapshot, ["asset-a/point", "asset-a/clip"], 1)

    def test_point_context_clamped_and_global_blocker_cannot_attach_target(self):
        source = {"duration_ms":2000, "source_sha256":"a"*64, "index_sha256":"b"*64}
        target = {"asset_id":"asset-a", "record_id":"point", "record_revision":2,
                 "label_id":"stroke.net", "value":"present", "split":"train"}
        with patch("packages.models.training_prepare.verify_asset", return_value=source), \
             patch("packages.models.training_prepare.plan_window", return_value={"frames":[]}) as planner, \
             patch("packages.models.training_readiness.audit_snapshot", return_value={
                 "trainable":False, "strict_training_view":[target]}) as audit:
            results = prepare_windows(self.snapshot, {"asset-a":self.asset}, Path("unused"),
                selected=["asset-a/point"], before_ms=500, after_ms=100, decode=False)
        audit.assert_called_once_with(self.snapshot, source_assets={"asset-a":self.asset})
        planner.assert_called_once_with(source, 0, 110, sample_count=6)
        self.assertTrue(results[0]["review_only"])
        self.assertEqual(results[0]["supervision_targets"], [])
        self.assertEqual(results[0]["decode"]["status"], "not_run")
        self.assertIn("not_action", results[0]["window_semantics"])
        self.assertEqual(results[0]["context_scope"], "scope_unknown")

    def test_point_context_stays_within_its_linked_rally(self):
        point, _, rally, _ = self.snapshot.bundles[0].records
        point.rally_id = "rally"
        rally.start_ms, rally.end_ms = 1000, 1500
        source = {"duration_ms":2000, "source_sha256":"a"*64, "index_sha256":"b"*64}
        for time_ms, bounds in ((1010, (1000, 1110)), (1490, (1000, 1500))):
            point.at_ms = time_ms
            with self.subTest(point=time_ms), \
                 patch("packages.models.training_prepare.verify_asset", return_value=source), \
                 patch("packages.models.training_prepare.plan_window", return_value={"frames":[]}) as planner, \
                 patch("packages.models.training_readiness.audit_snapshot", return_value={
                     "trainable":False, "strict_training_view":[]}):
                results = prepare_windows(self.snapshot, {"asset-a":self.asset}, Path("unused"),
                    selected=["asset-a/point"], before_ms=500, after_ms=100, decode=False)
            planner.assert_called_once_with(source, *bounds, sample_count=6)
            self.assertEqual(results[0]["context_scope"], "rally_bounded")
            self.assertEqual(results[0]["rally_bounds_ms"], [1000, 1500])

    def test_callers_cannot_supply_a_training_view(self):
        with self.assertRaisesRegex(TypeError, "strict_training_view"):
            prepare_windows(self.snapshot, {}, Path("unused"), strict_training_view=[])

    def test_public_snapshot_agent_unknown_is_review_only_without_audit_mock(self):
        from packages.contracts.training import TrainingSnapshot
        fixture = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/training.snapshot.v1.json"
        snapshot = TrainingSnapshot.model_validate_json(fixture.read_text(encoding="utf-8"))
        assets = {a.asset_id: a.model_dump(mode="json") for a in snapshot.assets}
        source = {"duration_ms":10000, "source_sha256":"a"*64, "index_sha256":"b"*64}
        self.assertFalse(snapshot.quality_summary.trainable)
        # Only media I/O/PTS planning are doubles; public contract and readiness
        # derivation are real. This fixture contains no actual media or truth.
        with patch("packages.models.training_prepare.bind_source"), \
             patch("packages.models.training_prepare.verify_asset", return_value=source), \
             patch("packages.models.training_prepare.plan_window", return_value={"frames":[]}):
            results = prepare_windows(snapshot, assets, Path("unused"), decode=False)
        self.assertTrue(results)
        self.assertTrue(all(r["review_only"] and not r["supervision_targets"] for r in results))

    def test_demo_scope_preserves_top_level_and_validates_legacy_fallback(self):
        for scope in ("general", "training_only"):
            self.assertEqual(source_usage_scope({"usage_scope":scope, "provenance":{"usage_scope":"other"}}), scope)
            self.assertEqual(source_usage_scope({"provenance":{"usage_scope":scope}}), scope)
        for source in ({"usage_scope":None, "provenance":{"usage_scope":"general"}},
                       {"usage_scope":"invalid"}, {"provenance":{"usage_scope":"invalid"}},
                       {"provenance":[]}):
            with self.subTest(source=source), self.assertRaises(SourceError):
                source_usage_scope(source)

    def test_excessive_context_is_rejected_before_any_decode(self):
        with self.assertRaisesRegex(SourceError, "bounded"):
            prepare_windows(self.snapshot, {}, Path("unused"), before_ms=15001)


if __name__ == "__main__":
    unittest.main()
