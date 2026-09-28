"""Contract and editorial behavior tests; no media or FFmpeg required."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from packages.render.timeline import (
    RenderError,
    assets_by_id,
    export_timeline,
    normalize_timeline,
    safe_path,
    selection_review_summary,
)


def asset(**changes):
    value = {
        "schema_version": "1.0", "asset_id": "court-a",
        "relative_path": "data/raw/court-a.mp4", "sha256": "a" * 64,
        "size_bytes": 1024, "duration_ms": 10000,
        "width": 1920, "height": 1080, "fps_num": 30000, "fps_den": 1001,
        "time_base": "1/30000", "source_type": "synthetic",
        "title": "Contract fixture", "match_id": "fixture-match",
        "rights": {"status": "unknown", "allowed_uses": []},
    }
    value.update(changes)
    return value


def segment(segment_id="clip-a", **changes):
    value = {
        "segment_id": segment_id, "asset_id": "court-a",
        "in_ms": 1000, "out_ms": 2000, "review_status": "confirmed",
        "event_ids": ["event-a"],
    }
    value.update(changes)
    return value


def timeline(*segments, **changes):
    value = {
        "schema_version": "1.0", "timeline_id": "timeline-test",
        "title": "Test timeline", "segments": list(segments or [segment()]),
    }
    value.update(changes)
    return value


class SafePathTests(unittest.TestCase):
    def test_posix_relative_path_resolves_within_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                safe_path(root, "data/raw/court-a.mp4"),
                root.resolve() / "data" / "raw" / "court-a.mp4",
            )

    def test_traversal_and_absolute_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for relative in (
                "../outside.mp4", "data/../../outside.mp4", "/outside.mp4",
                "C:/outside.mp4", "data\\court-a.mp4", "//server/share/file",
                "data/./file", "data//file", "data/", "", None,
            ):
                with self.subTest(path=relative):
                    with self.assertRaises(RenderError) as raised:
                        safe_path(Path(directory), relative)
                    self.assertEqual(raised.exception.code, "unsafe_path")

    def test_existing_symlink_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, outside = parent / "storage", parent / "outside"
            root.mkdir()
            outside.mkdir()
            try:
                (root / "linked").symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Creating symlinks unavailable: {exc}")
            with self.assertRaises(RenderError) as raised:
                safe_path(root, "linked/private.mp4")
            self.assertEqual(raised.exception.code, "unsafe_path")


class AssetTests(unittest.TestCase):
    def test_assets_are_indexed_and_detached_from_callers(self):
        original = asset()
        indexed = assets_by_id([original])
        self.assertEqual(list(indexed), ["court-a"])
        indexed["court-a"]["rights"]["allowed_uses"].append("local_test")
        self.assertEqual(original["rights"]["allowed_uses"], [])

    def test_duplicate_identity_and_malformed_assets_are_rejected(self):
        for raw in ([], [None], [asset(), asset()], [asset(asset_id="")]):
            with self.subTest(raw=raw):
                with self.assertRaises(RenderError):
                    assets_by_id(raw)

    def test_invalid_asset_measurements_are_rejected(self):
        for key in ("size_bytes", "duration_ms", "width", "height", "fps_num", "fps_den"):
            for value in (None, 0, -1, True, 1.5, "30"):
                with self.subTest(field=key, value=value):
                    with self.assertRaises(RenderError):
                        assets_by_id([asset(**{key: value})])

    def test_schema_hash_and_source_type_are_validated(self):
        for changes in (
            {"schema_version": "2.0"}, {"sha256": "a" * 63},
            {"sha256": "g" * 64}, {"sha256": None}, {"source_type": "download_candidate"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(RenderError):
                    assets_by_id([asset(**changes)])


class TimelineFixture:
    def setUp(self):
        self.assets = assets_by_id([asset(), asset(asset_id="court-b")])

    def normalize(self, *segments, **options):
        return normalize_timeline(timeline(*segments), self.assets, **options)


class TimelineTests(TimelineFixture, unittest.TestCase):
    def test_defaults_order_and_input_immutability(self):
        source = timeline(segment("second", in_ms=4000, out_ms=5000), segment("first"))
        before = deepcopy(source)
        result = normalize_timeline(source, self.assets)
        self.assertEqual(source, before)
        self.assertEqual([s["segment_id"] for s in result["segments"]], ["second", "first"])
        self.assertEqual(result["output"], {
            "width": 1080, "height": 1920, "fps": 30,
            "video_codec": "h264", "audio_codec": "aac",
        })
        self.assertEqual(result["segments"][0]["fit"], "contain")
        self.assertEqual(result["segments"][0]["audio"], "source")

    def test_unreviewed_rejected_and_missing_review_cannot_render(self):
        for review in ("unreviewed", "rejected", "unknown", None):
            with self.subTest(review=review):
                with self.assertRaises(RenderError) as raised:
                    self.normalize(segment(review_status=review))
                self.assertEqual(raised.exception.code, "review_required")

    def test_research_preview_defaults_off_and_regular_preview_does_not_bypass_review(self):
        self.assertFalse(self.normalize()["render_metadata"]["research_preview"])
        for options in ({}, {"research_preview": False}, {"preview": True}):
            with self.subTest(options=options):
                with self.assertRaises(RenderError) as raised:
                    self.normalize(segment(review_status="unreviewed"), **options)
                self.assertEqual(raised.exception.code, "review_required")

    def test_explicit_research_preview_allows_unreviewed_without_claiming_confirmation(self):
        result = self.normalize(segment(review_status="unreviewed"), research_preview=True)
        self.assertTrue(result["render_metadata"]["research_preview"])
        self.assertEqual(result["segments"][0]["review_status"], "unreviewed")
        self.assertEqual(result["render_metadata"]["input_segments"][0]["review_status"], "unreviewed")

    def test_research_preview_still_rejects_rejected_or_missing_review(self):
        for review in ("rejected", "unknown", None):
            with self.subTest(review=review):
                with self.assertRaises(RenderError) as raised:
                    self.normalize(segment(review_status=review), research_preview=True)
                self.assertEqual(raised.exception.code, "review_required")

    def test_unknown_asset_and_duplicate_segment_ids_are_rejected(self):
        with self.assertRaises(RenderError) as raised:
            self.normalize(segment(asset_id="missing"))
        self.assertEqual(raised.exception.code, "unknown_asset")
        with self.assertRaises(RenderError):
            self.normalize(segment(), segment())

    def test_boundaries_reject_empty_reversed_and_past_end(self):
        for start, end in ((1000, 1000), (2000, 1000), (0, 10001)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(RenderError) as raised:
                    self.normalize(segment(in_ms=start, out_ms=end))
                self.assertEqual(raised.exception.code, "invalid_boundary")
        self.assertEqual(
            self.normalize(segment(in_ms=0, out_ms=10000))["segments"][0]["output_frames"],
            300,
        )

    def test_time_boundaries_require_nonnegative_integers(self):
        for field, value in (("in_ms", -1), ("in_ms", True), ("in_ms", 0.5), ("out_ms", "2000")):
            with self.subTest(field=field, value=value):
                with self.assertRaises(RenderError):
                    self.normalize(segment(**{field: value}))

    def test_speed_rejects_nonfinite_bool_zero_and_out_of_range(self):
        for speed in (float("nan"), float("inf"), -float("inf"), True, 0, -1, 0.124, 8.01, "0.5"):
            with self.subTest(speed=speed):
                with self.assertRaises(RenderError):
                    self.normalize(segment(speed=speed))

    def test_crop_must_have_explicit_positive_normalized_in_bounds_window(self):
        for crop in (None, {}, {"x": 0, "y": 0, "width": 0, "height": 1},
                     {"x": 0, "y": 0, "width": 1, "height": 0},
                     {"x": -0.01, "y": 0, "width": 0.5, "height": 0.5},
                     {"x": 0.8, "y": 0, "width": 0.21, "height": 0.5},
                     {"x": 0, "y": 0.8, "width": 0.5, "height": 0.21},
                     {"x": 0, "y": 0, "width": 1.01, "height": 1}):
            with self.subTest(crop=crop):
                with self.assertRaises(RenderError):
                    self.normalize(segment(fit="crop", crop=crop))
        for crop in ({"x": 0, "y": 0, "width": 1, "height": 1},
                     {"x": 0.5, "y": 0.5, "width": 0.5, "height": 0.5}):
            with self.subTest(crop=crop):
                self.assertEqual(self.normalize(segment(fit="crop", crop=crop))["segments"][0]["crop"], crop)

    def test_normalized_crop_rejects_nonfinite_bool_and_nonnumeric_coordinates(self):
        for field in ("x", "y", "width", "height"):
            for value in (float("nan"), float("inf"), -float("inf"), True, "0.5", None):
                with self.subTest(field=field, value=value):
                    crop = {"x": 0, "y": 0, "width": 1, "height": 1, field: value}
                    with self.assertRaises(RenderError):
                        self.normalize(segment(fit="crop", crop=crop))

    def test_contract_float_30_fps_fixture_normalizes_without_changing_frame_count(self):
        source = timeline(segment(in_ms=0, out_ms=2000, speed=0.5), output={
            "width": 1080, "height": 1920, "fps": 30.0,
            "video_codec": "h264", "audio_codec": "aac",
        })
        result = normalize_timeline(source, self.assets)
        self.assertIs(type(result["output"]["fps"]), int)
        self.assertEqual(result["output"]["fps"], 30)
        self.assertEqual(result["segments"][0]["output_frames"], 120)
        self.assertEqual(result["segments"][0]["output_duration_ms"], 4000)
        self.assertIs(type(source["output"]["fps"]), float)

    def test_durations_round_to_output_frames_and_slowdown_is_applied(self):
        for end, speed, frames, milliseconds in (
            (1000, 0.5, 60, 2000), (1010, 1, 30, 1000),
            (1050, 1, 32, 1066.666667), (1, 8, 1, 33.333333),
        ):
            with self.subTest(end=end, speed=speed):
                result = self.normalize(segment(in_ms=0, out_ms=end, speed=speed))["segments"][0]
                self.assertEqual(result["output_frames"], frames)
                self.assertAlmostEqual(result["output_duration_ms"], milliseconds, places=6)

    def test_preview_changes_effective_dimensions_but_preserves_project(self):
        result = self.normalize(preview=True)
        self.assertEqual((result["output"]["width"], result["output"]["height"]), (1080, 1920))
        actual = result["render_metadata"]["effective_output"]
        self.assertEqual((actual["width"], actual["height"]), (360, 640))
        self.assertTrue(result["render_metadata"]["preview"])

    def test_preview_exported_project_can_be_reopened_for_preview_and_final(self):
        preview = self.normalize(segment(speed=0.5), preview=True)
        saved = export_timeline(preview)
        self.assertNotIn("render_metadata", saved)
        for as_preview, dimensions in ((True, (360, 640)), (False, (1080, 1920))):
            with self.subTest(preview=as_preview):
                reopened = normalize_timeline(saved, self.assets, preview=as_preview)
                actual = reopened["render_metadata"]["effective_output"]
                self.assertEqual((actual["width"], actual["height"]), dimensions)
                self.assertEqual(reopened["segments"][0]["output_frames"], preview["segments"][0]["output_frames"])
                self.assertEqual(export_timeline(reopened), saved)

    def test_subtitles_use_output_time_and_allow_the_exact_end(self):
        sub = {"start_ms": 1500, "end_ms": 2000, "text": "Slow motion"}
        result = self.normalize(segment(in_ms=0, out_ms=1000, speed=0.5, subtitles=[sub]))
        self.assertEqual(result["segments"][0]["subtitles"], [sub])

    def test_subtitles_reject_empty_negative_and_past_quantized_end(self):
        for start, end in ((0, 1001), (100, 100), (200, 100), (-1, 500), (True, 500)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(RenderError):
                    self.normalize(segment(in_ms=0, out_ms=1010,
                                           subtitles=[{"start_ms": start, "end_ms": end, "text": "Caption"}]))


class EditorialTests(TimelineFixture, unittest.TestCase):
    def test_merge_unreviewed_coverage_never_inherits_human_confirmation_in_either_order(self):
        human = segment("human", in_ms=1000, out_ms=2000,
                        editorial_review={"reviewer_type": "human", "reviewer": "reviewer-1"})
        agent = segment("agent", in_ms=1500, out_ms=2500, review_status="unreviewed",
                        editorial_review={"reviewer_type": "agent", "note": "candidate only"})
        for inputs in ((human, agent), (agent, human)):
            with self.subTest(first=inputs[0]["segment_id"]):
                result = self.normalize(*inputs, merge_overlaps=True, research_preview=True)
                merged = result["segments"][0]
                self.assertEqual((merged["in_ms"], merged["out_ms"]), (1000, 2500))
                self.assertEqual(merged["review_status"], "unreviewed")
                self.assertEqual(merged["editorial_review"]["reviewer_type"], "mixed")
                audit = merged["editorial_review"]["inputs"]
                self.assertEqual([(s["segment_id"], s["in_ms"], s["out_ms"], s["review_status"]) for s in audit],
                                 [(s["segment_id"], s["in_ms"], s["out_ms"], s["review_status"]) for s in inputs])
                self.assertEqual([s["editorial_review"] for s in audit], [s["editorial_review"] for s in inputs])
                self.assertFalse(selection_review_summary(result["segments"])["human_confirmed_segments"])

    def test_confirmed_mixed_reviewers_never_become_all_human_in_either_order(self):
        for actor in ("agent", "unknown"):
            first = segment("human", editorial_review={"reviewer_type": "human"})
            second = segment("other", in_ms=1500, out_ms=2500, editorial_review={"reviewer_type": actor})
            for inputs in ((first, second), (second, first)):
                with self.subTest(actor=actor, first=inputs[0]["segment_id"]):
                    result = self.normalize(*inputs, merge_overlaps=True)
                    self.assertEqual(result["segments"][0]["review_status"], "confirmed")
                    self.assertFalse(selection_review_summary(result["segments"])["human_confirmed_segments"])
                    self.assertEqual(len(result["segments"][0]["editorial_review"]["inputs"]), 2)

    def test_all_human_confirmed_inputs_retain_confirmation_and_all_provenance(self):
        inputs = [segment(f"human-{i}", in_ms=1000+i*500, out_ms=2000+i*500,
                          editorial_review={"reviewer_type": "human", "reviewer": f"person-{i}"}) for i in range(3)]
        result = self.normalize(*inputs, merge_overlaps=True)
        self.assertEqual(len(result["segments"]), 1)
        self.assertTrue(selection_review_summary(result["segments"])["human_confirmed_segments"])
        self.assertEqual([s["editorial_review"]["reviewer"] for s in result["segments"][0]["editorial_review"]["inputs"]],
                         ["person-0", "person-1", "person-2"])

    def test_reopened_merged_review_cannot_upgrade_its_unreviewed_source(self):
        provenance = {"reviewer_type": "human", "aggregation": "all_input_segments", "inputs": [
            {"review_status": "confirmed", "editorial_review": {"reviewer_type": "human"}},
            {"review_status": "unreviewed", "editorial_review": {"reviewer_type": "agent"}},
        ]}
        result = self.normalize(segment(editorial_review=provenance))
        self.assertFalse(selection_review_summary(result["segments"])["human_confirmed_segments"])

    def test_replay_event_aggregation_preserves_review_uncertainty(self):
        result = self.normalize(
            segment("human", replay_group_id="r", editorial_review={"reviewer_type": "human"}),
            segment("agent", replay_group_id="r", review_status="unreviewed", editorial_review={"reviewer_type": "agent"}),
            deduplicate_replays=True, research_preview=True)
        self.assertEqual(result["segments"][0]["review_status"], "unreviewed")
        self.assertFalse(selection_review_summary(result["segments"])["human_confirmed_segments"])

    def test_deduplication_requires_an_explicit_group_and_opt_in(self):
        first = segment("first", replay_group_id="shot-1")
        replay = segment("replay", replay_group_id="shot-1", asset_id="court-b")
        self.assertEqual(len(self.normalize(first, replay)["segments"]), 2)
        self.assertEqual(len(self.normalize(segment("a"), segment("b"), deduplicate_replays=True)["segments"]), 2)

    def test_replay_deduplication_preserves_events_and_excluded_source(self):
        first = segment("first", replay_group_id="shot-1", event_ids=["event-a", "shared"])
        replay = segment("replay", replay_group_id="shot-1", asset_id="court-b",
                         in_ms=3000, out_ms=4500, event_ids=["shared", "event-b"])
        result = self.normalize(first, replay, deduplicate_replays=True)
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["event_ids"], ["event-a", "shared", "event-b"])
        excluded = result["render_metadata"]["excluded_replays"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["kept_segment_id"], "first")
        self.assertEqual(excluded[0]["segment"]["asset_id"], "court-b")
        self.assertEqual(excluded[0]["segment"]["in_ms"], 3000)
        self.assertEqual(excluded[0]["segment"]["source_segment_ids"], ["replay"])

    def test_adjacent_overlap_merges_union_retimes_and_keeps_source_ids(self):
        result = self.normalize(
            segment("first", in_ms=1000, out_ms=2000, event_ids=["a", "shared"]),
            segment("second", in_ms=1500, out_ms=2500, event_ids=["shared", "b"]),
            segment("third", in_ms=2500, out_ms=3000, event_ids=["c"]),
            merge_overlaps=True,
        )
        self.assertEqual(len(result["segments"]), 1)
        merged = result["segments"][0]
        self.assertEqual((merged["in_ms"], merged["out_ms"]), (1000, 3000))
        self.assertEqual(merged["source_segment_ids"], ["first", "second", "third"])
        self.assertEqual(merged["event_ids"], ["a", "shared", "b", "c"])
        self.assertEqual((merged["output_frames"], merged["output_duration_ms"]), (60, 2000))

    def test_merge_preserves_original_input_boundaries_and_events_for_audit(self):
        first = segment("first", in_ms=1000, out_ms=2000, event_ids=["event-a"])
        second = segment("second", in_ms=1500, out_ms=2500, event_ids=["event-b"])
        result = self.normalize(first, second, merge_overlaps=True)
        originals = result["render_metadata"]["input_segments"]
        self.assertEqual([(s["in_ms"], s["out_ms"]) for s in originals], [(1000, 2000), (1500, 2500)])
        self.assertEqual([s["event_ids"] for s in originals], [["event-a"], ["event-b"]])
        self.assertEqual([s["source_segment_ids"] for s in originals], [["first"], ["second"]])

    def test_overlaps_merge_only_when_adjacent_and_opted_in(self):
        first, overlap = segment("first"), segment("overlap", in_ms=1500, out_ms=2500)
        self.assertEqual(len(self.normalize(first, overlap)["segments"]), 2)
        result = self.normalize(first, segment("middle", in_ms=5000, out_ms=6000), overlap,
                                merge_overlaps=True)
        self.assertEqual([s["segment_id"] for s in result["segments"]], ["first", "middle", "overlap"])

    def test_merge_respects_editing_differences_and_subtitles(self):
        for changes in (
            {"asset_id": "court-b"}, {"speed": 0.5}, {"audio": "mute"},
            {"title": "A different caption"}, {"replay_group_id": "another-shot"},
            {"fit": "crop", "crop": {"x": 0, "y": 0, "width": 0.5, "height": 0.5}},
            {"subtitles": [{"start_ms": 0, "end_ms": 500, "text": "Caption"}]},
        ):
            with self.subTest(changes=changes):
                result = self.normalize(segment("first"), segment("second", **changes), merge_overlaps=True)
                self.assertEqual(len(result["segments"]), 2)


if __name__ == "__main__":
    unittest.main()
