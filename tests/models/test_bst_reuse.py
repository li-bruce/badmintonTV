"""CPU-only synthetic guard/math fixtures, never badminton recognition evidence."""
import copy
import builtins
from contextlib import nullcontext
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from packages.models import bst_reuse as bst
from packages.models.protocol import InvalidRequest, ModelBlocked


def fixture():
    asset = {"asset_id": "fixture-only", "sha256": "a" * 64, "width": 100, "height": 100,
             "fps_num": 10, "fps_den": 1, "duration_ms": 1000, "time_base": "1/1000", "discipline": "singles"}
    review = {"status": "agent_reviewed", "method": "synthetic CPU fixture", "evidence": "not real observations or human review"}
    pack = {"schema_version": "1.0", "format": "bst-source-features-v1", "asset_id": asset["asset_id"],
            "source_sha256": asset["sha256"], "source_start_pts": 0, "usage_scope": "training_only",
            "camera_segment": {"id": "fixture-camera", "start_ms": 0, "end_ms": 1000},
            "shot_boundaries": {**review, "current_frame": 2, "previous_frame": 1, "next_frame": 3},
            "track_assignment": {**review, "track_ids": ["fixture-top", "fixture-bottom"]},
            "calibration": {**review, "id": "fixture-calibration", "camera_segment_id": "fixture-camera",
                            "coordinate_space": "source_pixels_to_unit_court", "source_width": 100, "source_height": 100,
                            "valid_start_ms": 0, "valid_end_ms": 1000,
                            "source_points": [[0, 0], [100, 0], [100, 100], [0, 100]],
                            "court_points": [[0, 0], [1, 0], [1, 1], [0, 1]],
                            "homography": [[.01, 0, 0], [0, .01, 0], [0, 0, 1]]},
            "provenance": {name: {"model_id": "fixture-only", "artifact_sha256": "b" * 64} for name in ("pose", "shuttle")},
            "frames": []}
    for index in range(1, 5):
        players = []
        for track_id, x, y in (("fixture-top", 20, 20), ("fixture-bottom", 60, 70)):
            players.append({"track_id": track_id, "box_xyxy": [x - 10, y - 10, x + 20, y + 20], "ankles_status": "observed",
                            "keypoints_xyv": [[x + j * .1, y + j * .1, 2] for j in range(17)]})
        pack["frames"].append({"source_frame_index": index, "pts": index * 100, "time_base": "1/1000", "source_ms": index * 100,
                               "width": 100, "height": 100, "players": players,
                               "shuttle": {"pts": index * 100, "time_base": "1/1000", "status": "observed", "x": 30 + index,
                                           "y": 40, "available_at_source_ms": index * 100 + 100}})
    return pack, asset


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.pack, self.asset = fixture()

    def blocked(self, code):
        with self.assertRaises(ModelBlocked) as caught:
            bst.prepare_features(self.pack, self.asset)
        self.assertEqual(caught.exception.code, code)

    def test_fixture_shapes_tail_padding_and_no_input_mutation(self):
        before = copy.deepcopy(self.pack)
        result = bst.prepare_features(self.pack, self.asset)
        self.assertEqual(self.pack, before)
        self.assertEqual(result["valid_length"], 4)
        self.assertEqual(result["selection_indices"], [0, 1, 2, 3])
        self.assertEqual([len(result["pose"]), len(result["pose"][0]), len(result["pose"][0][0])], [100, 2, 72])
        self.assertEqual(result["pose"][4], [[0] * 72, [0] * 72])
        self.assertEqual(result["positions"][4], [[0, 0], [0, 0]])
        self.assertEqual(result["shuttle"][0], [.31, .4])
        self.assertEqual(result["review_status"]["calibration"], "agent_reviewed")

    def test_labels_are_merged_author_order_not_fine_actions(self):
        self.assertEqual(len(bst.LABELS), 25)
        self.assertEqual(bst.LABELS[0], "未知球種")
        self.assertEqual(bst.LABELS[1], "Top_放小球")
        self.assertEqual(bst.LABELS[13], "Bottom_放小球")
        self.assertFalse(any(label in bst.LABELS for label in ("展搓", "收搓", "后退小跳")))

    def test_bbox_diagonal_and_center_are_not_video_normalization(self):
        points = [[20., 30., 2.] for _ in range(17)]
        result = bst.normalize_pose(points, [10., 10., 30., 50.])
        self.assertAlmostEqual(result[0], 0)
        self.assertAlmostEqual(result[1], 0)
        points[0][0] = 0
        result = bst.normalize_pose(points, [10., 10., 30., 50.])
        self.assertAlmostEqual(result[0], -10 / (2000 ** .5))

    def test_project_ankles_then_average_not_project_pixel_midpoint(self):
        h = [[1, 0, 0], [0, 1, 0], [.1, 0, 1]]
        a, b = bst.project([1, 2], h), bst.project([5, 2], h)
        midpoint = bst.project([3, 2], h)
        self.assertNotAlmostEqual((a[0] + b[0]) / 2, midpoint[0])

    def test_wrong_asset_or_source_hash_blocked(self):
        self.pack["source_sha256"] = "c" * 64
        self.blocked("BST_SOURCE_MISMATCH")

    def test_doubles_not_silently_reduced_to_two_players(self):
        self.asset["discipline"] = "doubles"
        self.blocked("BST_DISCIPLINE_UNSUPPORTED")

    def test_missing_calibration_and_unreviewed_calibration_blocked(self):
        for value in (None, {}, {"status": "unreviewed", "method": "auto", "evidence": "candidate"}):
            with self.subTest(value=value):
                self.pack["calibration"] = value
                self.blocked("BST_REVIEW_MISSING")

    def test_fake_homography_and_wrong_camera_rejected(self):
        self.pack["calibration"]["homography"][0][0] = 1
        self.blocked("BST_CALIBRATION_INVALID")
        self.pack, self.asset = fixture()
        self.pack["calibration"]["camera_segment_id"] = "other"
        self.blocked("BST_CALIBRATION_INVALID")

    def test_calibration_does_not_cover_window(self):
        self.pack["calibration"]["valid_end_ms"] = 300
        self.blocked("BST_CALIBRATION_INVALID")

    def test_degenerate_corners_rejected(self):
        self.pack["calibration"]["source_points"][1] = [0, 0]
        self.blocked("BST_CALIBRATION_INVALID")

    def test_track_ids_must_remain_stable(self):
        self.pack["frames"][1]["players"][0]["track_id"] = "new-detection-index"
        self.blocked("BST_TRACKS_MISSING")

    def test_player_order_cannot_swap_behind_stable_ids(self):
        players = self.pack["frames"][1]["players"]
        players[0]["keypoints_xyv"], players[1]["keypoints_xyv"] = players[1]["keypoints_xyv"], players[0]["keypoints_xyv"]
        self.blocked("BST_TRACK_ORDER_CHANGED")

    def test_sparse_pts_and_missing_source_frame_rejected(self):
        self.pack["frames"].pop()
        self.blocked("BST_TIMELINE_INCOMPLETE")
        self.pack, self.asset = fixture()
        self.pack["frames"][1]["pts"] += 20
        self.blocked("BST_TIMELINE_INVALID")

    def test_pts_not_replaced_by_source_milliseconds(self):
        self.pack["frames"][1]["shuttle"]["pts"] += 1
        self.blocked("BST_SHUTTLE_PTS_MISMATCH")

    def test_nonzero_stream_start_pts_keeps_asset_relative_time(self):
        self.pack["source_start_pts"] = 700
        for frame in self.pack["frames"]:
            frame["pts"] += 700
            frame["shuttle"]["pts"] += 700
        result = bst.prepare_features(self.pack, self.asset)
        self.assertEqual(result["source_timeline"][0]["pts"], 800)
        self.assertEqual(result["source_timeline"][0]["source_ms"], 100)

    def test_shuttle_availability_cannot_precede_observation(self):
        self.pack["frames"][0]["shuttle"]["available_at_source_ms"] = 99
        self.blocked("BST_AVAILABILITY_MISSING")

    def test_missing_or_imputed_shuttle_is_not_zero_observation(self):
        for status in ("missing", "imputed", "unknown"):
            with self.subTest(status=status):
                self.pack["frames"][0]["shuttle"]["status"] = status
                self.blocked("BST_SHUTTLE_MISSING")

    def test_low_ankle_visibility_and_origin_pose_block(self):
        self.pack["frames"][0]["players"][0]["ankles_status"] = "unknown"
        self.blocked("BST_ANKLES_UNKNOWN")
        self.pack, self.asset = fixture()
        self.pack["frames"][0]["players"][0]["keypoints_xyv"][15] = [0, 0, 2]
        self.blocked("BST_POSE_MISSING")

    def test_nonfinite_or_boolean_coordinates_block(self):
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value):
                self.pack["frames"][0]["shuttle"]["x"] = value
                self.blocked("BST_SHUTTLE_MISSING")

    def test_missing_shot_not_assumed_rally_edge(self):
        self.pack["shot_boundaries"]["next_frame"] = None
        self.blocked("BST_SHOT_BOUNDARIES_MISSING")

    def test_author_window_is_offline_and_capped(self):
        review = {"status": "agent_reviewed", "method": "fixture", "evidence": "fixture"}
        self.assertEqual(bst.shot_window({**review, "current_frame": 100, "previous_frame": 1, "next_frame": 200}, Fraction(30)), (55, 152))
        self.assertEqual(bst.shot_window({**review, "current_frame": 100, "previous_frame": None, "next_frame": None,
                                         "previous_missing_reason": "rally_start", "next_missing_reason": "rally_end"}, Fraction(30)), (85, 115))

    def test_author_overlong_sampling_indices(self):
        self.asset.update(fps_num=60, duration_ms=10000)
        self.pack["shot_boundaries"].update(current_frame=90, previous_frame=0, next_frame=149)
        self.pack["camera_segment"]["end_ms"] = 10000
        self.pack["calibration"]["valid_end_ms"] = 10000
        sample = self.pack["frames"][0]
        self.pack["frames"] = []
        self.asset["time_base"] = "1/6000"
        for i in range(164):
            frame = copy.deepcopy(sample)
            frame.update(source_frame_index=i, pts=i * 100, source_ms=round(i * 1000 / 60), time_base="1/6000")
            frame["shuttle"].update(pts=i * 100, time_base="1/6000", available_at_source_ms=round(i * 1000 / 60) + 50)
            self.pack["frames"].append(frame)
        result = bst.prepare_features(self.pack, self.asset)
        self.assertEqual(result["selection_indices"], list(range(0, 164, 2)))
        self.assertEqual(result["valid_length"], 82)


class FileAndExecutionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="bst-cpu-guards-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def entry(self, relative, content):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {"relative_path": relative, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

    def test_local_file_hash_size_and_owner(self):
        entry = self.entry("models/fixtures/input.json", b"{}")
        bst.verified_file(self.root, entry, "models/", 100)
        with self.assertRaises(ModelBlocked):
            bst.verified_file(self.root, {**entry, "sha256": "0" * 64}, "models/")
        with self.assertRaises(ModelBlocked):
            bst.verified_file(self.root, {**entry, "size_bytes": 3}, "models/")
        with self.assertRaises(ModelBlocked):
            bst.verified_file(self.root, entry, "models/weights/")
        with self.assertRaises(InvalidRequest):
            bst.verified_file(self.root, {**entry, "relative_path": "models/../other"}, "models/")

    def test_duplicate_json_keys_and_nonfinite_are_blocked(self):
        for value in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            entry = self.entry("models/fixtures/invalid.json", value)
            with self.assertRaises(ModelBlocked):
                bst._json(self.root / entry["relative_path"], 100)

    def test_manifest_cannot_authorize_arbitrary_python(self):
        code = {name: self.entry("models/upstream/fixture/" + name, b"raise AssertionError('must not run')") for name in bst.CODE_HASHES}
        manifest = {"schema_version": "1.0", "source_commit": bst.COMMIT, "license": "MIT", "architecture": "BST_CG_AP",
                    "pose_style": "JnB_bone", "seq_len": 100, "n_classes": 25, "code": code, "checkpoint": {}}
        self.entry("models/weights/bst/reuse-manifest.json", json.dumps(manifest).encode())
        with patch.dict(os.environ, {"BTV_BST_MANIFEST": "models/weights/bst/reuse-manifest.json"}):
            with self.assertRaises(ModelBlocked) as caught:
                bst.read_manifest(self.root)
        self.assertEqual(caught.exception.code, "BST_SOURCE_UNREVIEWED")

    def test_executable_source_is_the_same_verified_buffer(self):
        source = b"result = 'reviewed fixture'\n"
        entry = self.entry("models/upstream/fixture/bst.py", source)
        path = self.root / entry["relative_path"]
        real_compile = builtins.compile
        def replace_after_check(buffer, filename, mode):
            path.write_bytes(b"raise AssertionError('replaced source must not execute')\n")
            return real_compile(buffer, filename, mode)
        namespace = {}
        with patch.dict(bst.CODE_HASHES, {"bst.py": entry["sha256"]}), \
             patch.dict(bst.CODE_SIZES, {"bst.py": len(source)}), \
             patch.object(builtins, "compile", side_effect=replace_after_check):
            bst._exec_reviewed_source(path, "bst.py", namespace)
        self.assertEqual(namespace["result"], "reviewed fixture")

    def test_source_replaced_since_manifest_check_is_blocked(self):
        source = b"result = 1\n"
        entry = self.entry("models/upstream/fixture/bst.py", source)
        path = bst.verified_file(self.root, entry, "models/upstream/")
        path.write_bytes(b"result = 2\n")
        with patch.dict(bst.CODE_HASHES, {"bst.py": entry["sha256"]}), \
             patch.dict(bst.CODE_SIZES, {"bst.py": len(source)}):
            with self.assertRaises(ModelBlocked) as caught:
                bst._exec_reviewed_source(path, "bst.py", {})
        self.assertEqual(caught.exception.code, "BST_SOURCE_UNREVIEWED")

    def test_executable_source_rejects_fixed_size_mismatch(self):
        source = b"result = 1\n"
        entry = self.entry("models/upstream/fixture/bst.py", source)
        with patch.dict(bst.CODE_HASHES, {"bst.py": entry["sha256"]}), \
             patch.dict(bst.CODE_SIZES, {"bst.py": len(source) - 1}):
            with self.assertRaises(ModelBlocked) as caught:
                bst._exec_reviewed_source(self.root / entry["relative_path"], "bst.py", {})
        self.assertEqual(caught.exception.code, "BST_SOURCE_UNREVIEWED")

    def test_dependency_block_names_the_actual_missing_module(self):
        with patch.object(bst, "read_manifest", return_value=({}, {}, Path("unused"))), \
             patch.object(bst.importlib, "import_module", side_effect=ImportError("fixture unavailable")):
            with self.assertRaisesRegex(ModelBlocked, "dependency: torch") as caught:
                bst.Runtime(self.root, "cpu")
        self.assertEqual(caught.exception.code, "DEPENDENCY_NOT_INSTALLED")

    def test_actual_decoder_catches_forged_dense_timeline(self):
        pack, asset = fixture()
        prepared = bst.prepare_features(pack, asset)
        class Container:
            streams = types.SimpleNamespace(video=[types.SimpleNamespace(time_base=Fraction(1, 1000), start_time=0)])
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def seek(self, *args, **kwargs): pass
            def decode(self, stream):
                return iter(types.SimpleNamespace(pts=p, width=100, height=100) for p in (0, 100, 150, 200, 300, 400, 500))
        with patch.dict(sys.modules, {"av": types.SimpleNamespace(open=lambda path: Container())}):
            with self.assertRaises(ModelBlocked) as caught:
                bst.verify_source_timeline("fixture-only", asset, pack, prepared)
        self.assertEqual(caught.exception.code, "BST_TIMELINE_INCOMPLETE")

    def test_execute_missing_features_blocks_before_model_load(self):
        request = {"operation": "analyze", "parameters": {"model_id": bst.MODEL_ID}, "assets": [{}]}
        with patch.object(bst, "validate_request"), patch.object(bst, "Runtime", side_effect=AssertionError("must not load")):
            with self.assertRaises(ModelBlocked) as caught:
                bst.execute(request, self.root, self.root / "models/output", Mock())
        self.assertEqual(caught.exception.code, "BST_INPUT_MISSING")

    def test_worker_envelope_supports_operations_and_strict_optional_version(self):
        envelope = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/model-request.json"
        request = json.loads(envelope.read_text(encoding="utf-8"))
        request["parameters"] = {"model_id": bst.MODEL_ID}
        for operation in ("analyze", "movement_classification", "stroke_classification"):
            for version in ({}, {"model_version": "0.1.0"}):
                with self.subTest(operation=operation, version=version):
                    request["operation"] = operation
                    request["parameters"] = {"model_id": bst.MODEL_ID, **version}
                    with self.assertRaises(ModelBlocked) as caught:
                        bst.execute(request, self.root, self.root / request["output_dir"], Mock())
                    self.assertEqual(caught.exception.code, "BST_INPUT_MISSING")
        for version in (None, "0.2.0", 1, True):
            with self.subTest(invalid_version=version):
                request["parameters"]["model_version"] = version
                with self.assertRaisesRegex(InvalidRequest, "model_version"):
                    bst.execute(request, self.root, self.root / request["output_dir"], Mock())

    def test_fixture_execution_keeps_metrics_null_and_training_scope(self):
        pack, asset = fixture()
        envelope = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/model-request.json"
        request = json.loads(envelope.read_text(encoding="utf-8"))
        asset = {**request["assets"][0], **asset}
        asset.update(self.entry("data/training/fixture.bin", b"not a real video"))
        pack["source_sha256"] = asset["sha256"]
        features = self.entry("models/fixtures/features.json", json.dumps(pack).encode())
        request = {"schema_version": "1.0", "operation": "stroke_classification", "parameters": {"model_id": bst.MODEL_ID, "model_version": "0.1.0", "features": features},
                   "assets": [asset], "output_dir": "models/handoff/fixture/attempt-01", "job_id": "fixture", "attempt_id": "attempt-01"}
        output = self.root / request["output_dir"]
        runtime = Mock(manifest={"checkpoint": {"sha256": "fixture-only"}, "code": {}}, predict=Mock(return_value=list(range(25))), details=Mock(return_value={"device": "fixture"}))
        with patch.object(bst, "verify_source_timeline", return_value={"scope": "fixture"}), \
             patch.object(bst, "Runtime", return_value=runtime), patch.object(bst, "reserve", return_value=nullcontext()):
            result = bst.execute(request, self.root, output, Mock())
            prediction = json.loads((output / "bst-prediction.json").read_text(encoding="utf-8"))
            self.assertEqual(result["events"], [])
            self.assertEqual(prediction["usage_scope"], "training_only")
            self.assertIsNone(prediction["accuracy"])
            self.assertIsNone(prediction["recall"])
            self.assertEqual(prediction["fine_labels"], "unknown")
            self.assertFalse(prediction["causal"])
            self.assertEqual(prediction["epistemic_status"], "unreviewed")
            self.assertEqual(prediction["review_status"]["calibration"], "agent_reviewed")
            with self.assertRaises(FileExistsError):
                bst.execute(request, self.root, output, Mock())


if __name__ == "__main__":
    unittest.main()
