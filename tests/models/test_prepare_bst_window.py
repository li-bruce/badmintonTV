"""Synthetic CPU geometry/schema fixtures; no badminton/video accuracy claims."""
import copy
from pathlib import Path
import unittest

from scripts.models import prepare_bst_window as prepare
from packages.models.protocol import InvalidRequest


def fixture():
    asset = {"asset_id": "synthetic-schema-fixture", "sha256": prepare.SOURCE_SHA, "width": 1280, "height": 720,
             "fps_num": 30, "fps_den": 1, "time_base": "1/15360", "duration_ms": 6000, "discipline": "singles",
             "relative_path": "data/fixture-only.mp4", "usage_scope": "training_only", "provenance": {}}
    pose = {"asset_id": asset["asset_id"], "source_sha256": asset["sha256"], "sampling": "continuous_original_pts",
            "producer": {"model_id": "torchvision-continuous-pose", "usage_scope": "general"}, "usage_scope": "general", "frames": []}
    shuttle = {"asset_id": asset["asset_id"], "source_sha256": asset["sha256"], "format": "tracknet-observation-source-pixels-v1",
               "producer": {"model_id": "tracknetv3-reuse", "usage_scope": "general"}, "usage_scope": "general", "frames": []}
    for index in range(21, 111):
        common = {"frame_index": index-21, "pts": index*512, "time_base": "1/15360", "stream_start_pts": 0,
                  "source_ms": round(index*1000/30, 6), "width": 1280, "height": 720}
        detections = [{"detection_id": f"{index}:{i}", "box_xyxy": [x-40, y-70, x+40, y+10],
                       "keypoints_xyv": [[x, y, 2.0] for _ in range(17)], "keypoint_scores": [7.5]*17, "score": .95}
                      for i, (x, y) in enumerate(((600., 400.), (650., 560.)))]
        pose["frames"].append({**common, "detections": detections, "detections_omitted_by_cap": 0})
        shuttle["frames"].append({**common, "status": "observed", "x": 620, "y": 340,
                                   "inpainted": False, "available_after_source_ms": 5833.333333})
    provenance = {name: {"model_id": "synthetic-fixture", "artifact_sha256": digest*64} for name, digest in (("pose", "a"), ("shuttle", "b"))}
    boundaries = {"status": "agent_reviewed", "method": "synthetic boundary fixture", "evidence": "not real human truth",
                  "current_frame": 30, "previous_frame": 27, "next_frame": 32}
    return asset, pose, shuttle, provenance, boundaries


class PrepareWindowTests(unittest.TestCase):
    def run_review(self, asset, pose, shuttle, provenance, **kwargs):
        return prepare.prepare_review(asset, pose, shuttle, provenance, root=Path.cwd(), **kwargs)

    def test_homography_maps_pinned_source_corners(self):
        h = prepare.homography(prepare.SOURCE_POINTS, prepare.COURT_POINTS)
        for point, expected in zip(prepare.SOURCE_POINTS, prepare.COURT_POINTS):
            for value, target in zip(prepare.bst.project(point, h), expected):
                self.assertAlmostEqual(value, target, places=8)

    def test_unknown_asset_does_not_reuse_camera_geometry(self):
        asset, pose, shuttle, provenance, _ = fixture()
        asset["sha256"] = "0"*64
        with self.assertRaises(InvalidRequest):
            self.run_review(asset, pose, shuttle, provenance)

    def test_candidates_keep_raw_points_and_do_not_auto_review(self):
        asset, pose, shuttle, provenance, _ = fixture()
        before = copy.deepcopy((pose, shuttle))
        report, final = self.run_review(asset, pose, shuttle, provenance)
        self.assertIsNone(final)
        self.assertEqual(report["statistics"]["usable_frames"], 90)
        self.assertEqual(report["usage_scope"], "training_only")
        self.assertFalse(report["human_review_claim"])
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["rows"][0]["players"][0]["association_status"], "proposed")
        self.assertIsNone(report["rows"][0]["players"][0]["player_id"])
        self.assertEqual((pose, shuttle), before)

    def test_explicit_scoped_review_and_boundaries_make_strict_pack(self):
        asset, pose, shuttle, provenance, boundaries = fixture()
        report, final = self.run_review(asset, pose, shuttle, provenance, boundaries=boundaries)
        self.assertIsNone(final)
        review = report["assignment_review_template"]
        review.update(status="agent_reviewed", evidence="synthetic scoped review fixture; no human review")
        report, final = self.run_review(asset, pose, shuttle, provenance, boundaries=boundaries, assignment_review=review)
        self.assertEqual(report["status"], "prepared")
        self.assertEqual(len(final["frames"]), 12)
        self.assertEqual(final["frames"][0]["source_frame_index"], 27)
        self.assertEqual(final["frames"][-1]["source_frame_index"], 38)
        prepared = prepare.bst.prepare_features(final, asset)
        self.assertEqual(prepared["valid_length"], 12)

    def test_missing_ball_splits_available_runs_without_fill(self):
        asset, pose, shuttle, provenance, boundaries = fixture()
        shuttle["frames"][9].update(status="missing", x=None, y=None)
        report, final = self.run_review(asset, pose, shuttle, provenance, boundaries=boundaries)
        self.assertIsNone(final)
        self.assertEqual(report["statistics"]["usable_frames"], 89)
        self.assertIsNone(report["rows"][9]["shuttle"]["x"])
        self.assertEqual([(w["start_frame"], w["end_frame"]) for w in report["usable_continuous_windows"]], [(21, 30), (31, 111)])
        self.assertIn("selected_shot_incomplete_or_has_blocked_observations", report["blocked_reasons"])

    def test_imputation_and_pts_nonmatch_are_not_observations(self):
        asset, pose, shuttle, provenance, _ = fixture()
        shuttle["frames"][0]["inpainted"] = True
        shuttle["frames"].pop(1)
        report, _ = self.run_review(asset, pose, shuttle, provenance)
        self.assertIn("shuttle_missing_or_imputed", report["rows"][0]["blocked_reasons"])
        self.assertIn("shuttle_pts_missing", report["rows"][1]["blocked_reasons"])

    def test_three_people_not_silently_top_two_and_continuity_restarts(self):
        asset, pose, shuttle, provenance, _ = fixture()
        pose["frames"][1]["detections"].append(copy.deepcopy(pose["frames"][1]["detections"][0]))
        report, _ = self.run_review(asset, pose, shuttle, provenance)
        self.assertIn("court_person_count_not_two", report["rows"][1]["blocked_reasons"])
        self.assertNotEqual(report["rows"][0]["track_ids"], report["rows"][2]["track_ids"])

    def test_large_candidate_jump_blocks(self):
        asset, pose, shuttle, provenance, _ = fixture()
        person = pose["frames"][1]["detections"][0]
        person["box_xyxy"] = [800, 330, 880, 410]
        person["keypoints_xyv"] = [[840., 400., 2.0] for _ in range(17)]
        report, _ = self.run_review(asset, pose, shuttle, provenance)
        self.assertIn("anonymous_track_continuity_disagreement", report["rows"][1]["blocked_reasons"])

    def test_duplicate_pts_wrong_source_or_timebase_rejected(self):
        for mutation in (lambda p: p["frames"].insert(1, copy.deepcopy(p["frames"][0])),
                         lambda p: p.update(source_sha256="c"*64),
                         lambda p: p["frames"][0].update(time_base="1/30000")):
            asset, pose, shuttle, provenance, _ = fixture()
            mutation(pose)
            with self.assertRaises(InvalidRequest):
                self.run_review(asset, pose, shuttle, provenance)

    def test_two_second_review_is_view_not_fabricated_shot(self):
        asset, pose, shuttle, provenance, _ = fixture()
        report, final = self.run_review(asset, pose, shuttle, provenance, review_range=[30, 90])
        self.assertEqual(report["statistics"]["pose_frames"], 60)
        self.assertEqual(report["rows"][0]["source_frame_index"], 30)
        self.assertIsNone(final)
        self.assertIn("explicit_shot_boundaries_missing", report["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
