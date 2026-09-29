"""Synthetic read-only diagnostic tests, not recognition/identity evidence."""
import copy
import unittest

from scripts.models import compare_pose_inputs as comparison
from scripts.models import prepare_bst_window as preparation


def fixtures():
    asset = {"asset_id": "fixture-profile-only", "sha256": preparation.SOURCE_SHA, "width": 1280, "height": 720,
             "fps_num": 30, "fps_den": 1, "time_base": "1/15360", "duration_ms": 6000, "discipline": "singles"}
    detections = [{"detection_id": i, "box_xyxy": [550, y-100, 650, y+10], "keypoints_xyv": [[600,y,1]]*17,
                   "keypoint_scores": [7.]*17, "score": .9, "track_id": None} for i,y in enumerate((380,550))]
    frame = {"pts": 15360, "time_base": "1/15360", "stream_start_pts": 0, "source_ms": 1000,
             "width": 1280, "height": 720, "detections": detections}
    old = {"asset_id": asset["asset_id"], "source_sha256": asset["sha256"], "frames": [frame],
           "producer": {"model_id": "torchvision-continuous-pose"}}
    new = copy.deepcopy(old)
    new.update(source_asset=asset, producer={"model_id": "yolo11n-pose-bytetrack"})
    for i,d in enumerate(new["frames"][0]["detections"]):
        d.update(keypoint_scores=[.8]*17, track_id=f"fixture:anonymous-{i+1}")
    return old, new


class ComparisonTests(unittest.TestCase):
    def test_native_scores_are_not_converted_to_common_accuracy(self):
        old, new = fixtures()
        before = copy.deepcopy((old,new))
        result = comparison.compare(old,new)
        self.assertEqual(result["old"]["sides"]["far"]["ankle_raw_scores"]["median"], 7.)
        self.assertEqual(result["yolo"]["sides"]["far"]["ankle_raw_scores"]["median"], .8)
        self.assertIsNone(result["old"]["sides"]["far"]["both_ankles_at_least_point5_frames"])
        self.assertIsNone(result["accuracy"])
        self.assertIsNone(result["recall"])
        self.assertFalse(result["calibration"]["human_confirmed"])
        self.assertEqual((old,new), before)

    def test_different_source_hash_is_rejected(self):
        old,new = fixtures()
        old["source_sha256"] = "a"*64
        with self.assertRaisesRegex(ValueError, "same source"):
            comparison.compare(old,new)

    def test_unmatched_pts_are_not_silently_dropped(self):
        old,new = fixtures()
        extra = copy.deepcopy(new["frames"][0])
        extra.update(pts=15872,source_ms=1033)
        new["frames"].append(extra)
        with self.assertRaisesRegex(ValueError, "same source PTS"):
            comparison.compare(old,new)


if __name__ == "__main__":
    unittest.main()
