"""Synthetic fixtures verify evaluation logic, never model/video accuracy."""

import math
import unittest

from packages.models.evaluation import (
    EvaluationInputError,
    coco17_track_features,
    evaluate_rankings,
    precision_at_k,
    recall_from_truth,
    validate_splits,
)


def asset(asset_id, match_id, split="test", **fields):
    return {"asset_id": asset_id, "match_id": match_id, "split": split,
            "source_type": "broadcast", "discipline": "singles", "camera_type": "rear",
            **fields}


def frame(source_ms, x=0, score=1, track_id="track-a"):
    points = [[0.0, 0.0, 1.0] for _ in range(17)]
    points[11] = [x, 10.0, 1.0]
    points[12] = [x + 2, 10.0, 1.0]
    points[15] = [x - 2, 20.0, score]
    points[16] = [x + 4, 20.0, score]
    return {"source_ms": source_ms, "track_id": track_id, "keypoints": points}


class SplitTests(unittest.TestCase):
    def test_independent_whole_matches_can_have_different_splits(self):
        report = validate_splits([asset("a", "m1", "train"), asset("b", "m2", "test")])
        self.assertEqual(report["group_count"], 2)

    def test_same_match_cannot_cross_splits(self):
        with self.assertRaises(EvaluationInputError) as raised:
            validate_splits([asset("a", "m1", "train"), asset("b", "m1", "test")])
        self.assertIn("split_leakage", {issue["code"] for issue in raised.exception.issues})

    def test_missing_match_rejected_for_formal_evaluation(self):
        with self.assertRaises(EvaluationInputError):
            validate_splits([asset("a", None)])
        report = validate_splits([asset("a", None)], formal=False)
        self.assertEqual(report["warnings"][0]["code"], "missing_match_id")

    def test_same_hash_different_match_still_leaks(self):
        with self.assertRaises(EvaluationInputError):
            validate_splits([asset("a", "m1", "train", sha256="a" * 64),
                             asset("b", "m2", "test", sha256="A" * 64)])

    def test_transitive_source_match_and_hash_grouping(self):
        rows = [asset("original", "m1", "train"),
                asset("clip", "m2", "train", provenance={"source_asset_id": "original"}),
                asset("replay", "m2", "train", sha256="a" * 64),
                asset("copy", "m3", "test", sha256="a" * 64)]
        with self.assertRaises(EvaluationInputError) as raised:
            validate_splits(rows)
        leakage = next(issue for issue in raised.exception.issues if issue["code"] == "split_leakage")
        self.assertEqual(set(leakage["asset_ids"]), {"original", "clip", "replay", "copy"})

    def test_shared_external_source_group(self):
        with self.assertRaises(EvaluationInputError):
            validate_splits([asset("a", "m1", "train", provenance={"source_asset_id": "outside"}),
                             asset("b", "m2", "test", provenance={"source_asset_id": "outside"})])

    def test_same_split_source_group_is_accepted(self):
        result = validate_splits([asset("a", "m1"),
                                  asset("b", "m2", provenance={"source_asset_id": "a"})])
        self.assertEqual(result["group_count"], 1)

    def test_unassigned_empty_and_duplicate_manifest_rejected(self):
        for rows in ([], [asset("a", "m1", "unassigned")], [asset("a", "m1"), asset("a", "m1")]):
            with self.subTest(rows=rows), self.assertRaises(EvaluationInputError):
                validate_splits(rows)

    def test_malformed_provenance_is_not_silently_discarded(self):
        for provenance in ([], False, ""):
            with self.subTest(provenance=provenance), self.assertRaises(EvaluationInputError):
                validate_splits([asset("a", "m1", provenance=provenance)])


class MetricTests(unittest.TestCase):
    def test_unknown_is_not_negative(self):
        result = precision_at_k([{"relevance": "positive"}, {"relevance": "unknown"},
                                 {"relevance": "negative"}], k=20)
        self.assertEqual((result["positive"], result["negative"], result["unknown"]), (1, 1, 1))
        self.assertIsNone(result["precision"])
        self.assertAlmostEqual(result["lower_bound"], 1 / 3)
        self.assertAlmostEqual(result["upper_bound"], 2 / 3)
        self.assertAlmostEqual(result["known_coverage"], 2 / 3)
        self.assertEqual(result["known_precision"], 0.5)
        self.assertEqual(result["k"], 3)

    def test_k_truncates_and_missing_is_unknown(self):
        result = precision_at_k([{}, {"relevance": None}, {"relevance": "negative"}], k=2)
        self.assertEqual(result["unknown"], 2)
        self.assertEqual(result["negative"], 0)
        self.assertEqual(result["known_coverage"], 0)
        self.assertEqual(result["upper_bound"], 1)

    def test_empty_results_and_empty_truth_are_not_perfect(self):
        result = precision_at_k([])
        self.assertEqual(result["k"], 0)
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["known_coverage"])
        self.assertIsNone(recall_from_truth([], [], complete_truth=True))

    def test_no_recall_without_complete_truth(self):
        self.assertIsNone(recall_from_truth(["t1"], ["t1", "t2"]))
        self.assertEqual(recall_from_truth(["t1", "t1"], ["t1", "t2"], complete_truth=True), 0.5)

    def test_bad_parameters_cannot_be_silently_interpreted(self):
        for k in (0, -1, True, 2.5):
            with self.subTest(k=k), self.assertRaises(EvaluationInputError):
                precision_at_k([], k=k)
        with self.assertRaises(EvaluationInputError):
            precision_at_k([{"relevance": "high_confidence"}])
        with self.assertRaises(EvaluationInputError):
            recall_from_truth([], [], complete_truth="true")


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.assets = [asset("a", "m1"), asset("b", "m2", source_type="personal",
                       discipline="doubles", camera_type="side")]
        self.query = {"query_id": "q1", "candidates": [
            {"asset_id": "a", "relevance": "positive", "truth_id": "t1"},
            {"asset_id": "b", "relevance": "unknown"},
            {"asset_id": "b", "relevance": "positive", "truth_id": "t2"}],
            "truth": [{"asset_id": "a", "truth_id": "t1"}, {"asset_id": "b", "truth_id": "t2"}]}

    def test_strata_share_global_review_budget(self):
        report = evaluate_rankings([self.query], assets=self.assets, k=2, complete_truth=True)
        query = report["queries"][0]
        self.assertEqual(query["overall"]["recall_at_k"], 0.5)
        for dimension, value in (("source_type", "personal"), ("discipline", "doubles"), ("camera_type", "side")):
            strata = query["strata"][dimension][value]
            self.assertEqual(strata["k"], 1)
            self.assertEqual(strata["unknown"], 1)
            self.assertEqual(strata["positive"], 0)
            self.assertEqual(strata["recall_at_k"], 0)

    def test_incomplete_truth_yields_no_recall_in_any_stratum(self):
        result = evaluate_rankings([self.query], assets=self.assets)["queries"][0]
        self.assertIsNone(result["overall"]["recall_at_k"])
        for strata in result["strata"].values():
            self.assertTrue(all(value["recall_at_k"] is None for value in strata.values()))

    def test_empty_return_stratum_preserves_missed_truth(self):
        query = dict(self.query, candidates=[])
        result = evaluate_rankings([query], assets=self.assets, complete_truth=True)["queries"][0]
        self.assertEqual(result["strata"]["source_type"]["personal"]["recall_at_k"], 0)
        self.assertIsNone(result["strata"]["source_type"]["personal"]["precision"])

    def test_unknown_candidate_with_truth_id_does_not_raise_recall(self):
        query = dict(self.query, candidates=[{"asset_id": "a", "relevance": "unknown", "truth_id": "t1"}])
        result = evaluate_rankings([query], assets=self.assets, complete_truth=True)["queries"][0]
        self.assertEqual(result["overall"]["recall_at_k"], 0)

    def test_formal_pipeline_rejects_leakage_train_and_synthetic(self):
        for assets in ([asset("a", "same", "train"), asset("b", "same")],
                       [asset("a", "m1", "train"), self.assets[1]],
                       [asset("a", "m1", source_type="synthetic"), self.assets[1]]):
            with self.subTest(assets=assets), self.assertRaises(EvaluationInputError):
                evaluate_rankings([self.query], assets=assets)

    def test_unknown_assets_and_duplicate_matches_rejected(self):
        for candidates in ([{"asset_id": "absent", "relevance": "unknown"}],
                           [self.query["candidates"][0], self.query["candidates"][0]]):
            with self.subTest(candidates=candidates), self.assertRaises(EvaluationInputError):
                evaluate_rankings([dict(self.query, candidates=candidates)], assets=self.assets)

    def test_positive_must_exist_in_complete_truth(self):
        with self.assertRaises(EvaluationInputError):
            evaluate_rankings([dict(self.query, truth=[])], assets=self.assets, complete_truth=True)


class SkeletonFeatureTests(unittest.TestCase):
    def test_source_time_velocity_and_relative_coordinates(self):
        result = coco17_track_features([frame(1000, x=0), frame(1100, x=2)], identity_confirmed=True)
        self.assertEqual(result["status"], "observed")
        features = result["frames"][1]["features"]
        self.assertEqual(features["hip_midpoint_px"], [3, 10])
        self.assertEqual(features["left_ankle_relative_hip_px"], [-3, 10])
        self.assertEqual(features["hip_velocity_px_s"], [20, 0])
        self.assertEqual(features["left_relative_velocity_px_s"], [0, 0])
        self.assertNotIn("labels", result)
        self.assertNotIn("events", result)

    def test_low_feet_visibility_unknown_and_no_gap_interpolation(self):
        result = coco17_track_features([frame(0), frame(100, score=0.1), frame(200, x=5)], identity_confirmed=True)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("low_ankle_visibility", result["unknown_reasons"])
        self.assertIsNone(result["frames"][1]["features"])
        self.assertIsNone(result["frames"][2]["features"]["hip_velocity_px_s"])

    def test_unconfirmed_identity_and_long_gap_return_unknown(self):
        self.assertEqual(coco17_track_features([frame(0), frame(100)])["status"], "unknown")
        result = coco17_track_features([frame(0), frame(1000)], identity_confirmed=True)
        self.assertIn("timestamp_gap", result["unknown_reasons"])
        self.assertIsNone(result["frames"][1]["features"]["hip_velocity_px_s"])

    def test_hidden_hip_and_single_frame_are_unknown(self):
        hidden = frame(100)
        hidden["keypoints"][11][2] = 0.2
        result = coco17_track_features([frame(0), hidden], identity_confirmed=True)
        self.assertIn("low_hip_visibility", result["unknown_reasons"])
        self.assertIsNone(result["frames"][1]["features"])
        self.assertIn("insufficient_frames", coco17_track_features([frame(0)], identity_confirmed=True)["unknown_reasons"])

    def test_mixed_tracks_bad_time_and_nonfinite_points_rejected(self):
        invalid = frame(100)
        invalid["keypoints"][0][0] = math.nan
        for frames in ([frame(0), frame(100, track_id="b")], [frame(100), frame(100)], [frame(0), invalid]):
            with self.subTest(frames=frames), self.assertRaises(EvaluationInputError):
                coco17_track_features(frames, identity_confirmed=True)


if __name__ == "__main__":
    unittest.main()
