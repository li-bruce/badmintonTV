"""Synthetic CPU transport, provenance and index guards, not pose accuracy."""
from contextlib import nullcontext
import copy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from packages.models import yolo_pose_reuse as yolo
from packages.models.protocol import InvalidRequest, ModelBlocked


def fixture():
    path = Path(__file__).resolve().parents[2]/"packages/contracts/fixtures/model-request.json"
    request = json.loads(path.read_text(encoding="utf-8"))
    request["operation"] = "pose"
    request["parameters"] = {"model_id": yolo.MODEL_ID, "model_version": "0.1.0", "start_ms": 0, "end_ms": 100,
                              "camera_segment": {"id": "fixture-shot", "start_ms": 0, "end_ms": 4000,
                                                 "status": "agent_reviewed", "method": "synthetic fixture", "evidence": "not visual evidence"}}
    return request


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.request = fixture()

    def test_worker_envelope_operations_and_optional_version(self):
        for operation in ("analyze", "pose", "tracking"):
            self.request["operation"] = operation
            self.assertEqual(yolo.options(self.request)["imgsz"], 640)
        del self.request["parameters"]["model_version"]
        yolo.options(self.request)

    def test_bad_version_and_parameters(self):
        for extra in ({"model_version": None}, {"model_version": "0.2.0"}, {"imgsz": True}, {"imgsz": 1280},
                      {"device": "remote"}, {"fill_missing": True}, {"end_ms": 3001}, {"start_ms": True}):
            request = copy.deepcopy(self.request)
            request["parameters"].update(extra)
            with self.subTest(extra=extra), self.assertRaises(InvalidRequest):
                yolo.options(request)

    def test_camera_review_is_required_without_promoting_agent(self):
        original = self.request["parameters"].pop("camera_segment")
        with self.assertRaises(ModelBlocked) as caught:
            yolo.options(self.request)
        self.assertEqual(caught.exception.code, "YOLO_CAMERA_REVIEW_MISSING")
        self.request["parameters"]["camera_segment"] = original
        self.assertEqual(yolo.options(self.request)["camera_segment"]["status"], "agent_reviewed")
        original["end_ms"] = 50
        with self.assertRaises(ModelBlocked):
            yolo.options(self.request)

    def test_high_fps_cannot_silently_drop_to_frame_cap(self):
        self.request["assets"][0].update(fps_num=60, fps_den=1)
        self.request["parameters"]["end_ms"] = 2000
        with self.assertRaises(ModelBlocked) as caught:
            yolo.options(self.request)
        self.assertEqual(caught.exception.code, "YOLO_FRAME_BOUND")


class AssociationTests(unittest.TestCase):
    def test_confidence_partition_preserves_raw_indices(self):
        class Boxes:
            def __init__(self, values): self.values = values
            def __len__(self): return len(self.values)
            def __getitem__(self, values):
                return Boxes([v for v, keep in zip(self.values, values) if keep])
        class UpstreamFixture:
            def init_track(self, results, img=None):
                return [SimpleNamespace(idx=i) for i in range(len(results))]
        detections = yolo.IndexedDetections(Boxes(["low", "high", "low", "high"]))
        tracker = yolo.indexed_tracker_class(UpstreamFixture)()
        high = tracker.init_track(detections[[False, True, False, True]])
        low = tracker.init_track(detections[[True, False, True, False]])
        self.assertEqual([t.idx for t in high], [1, 3])
        self.assertEqual([t.idx for t in low], [0, 2])

    def test_raw_pose_and_unassigned_detection_are_retained(self):
        points = [[[10., 20., .1] for _ in range(17)] for _ in range(2)]
        output = yolo.serialize_detections([[0., 0., 20., 30.]]*2, [.2, .9], points,
                                         [[0., 0., 20., 30., 7., .9, 0., 1.]], "fixture")
        self.assertIsNone(output[0]["track_id"])
        self.assertEqual(output[1]["track_id"], "fixture:anonymous-7")
        self.assertEqual(output[0]["keypoints_xyv"], points[0])
        self.assertEqual(set(output[0]["keypoint_status"]), {"unknown"})
        self.assertEqual(output[1]["identity_status"], "anonymous")

    def test_empty_detection_is_not_a_synthetic_person(self):
        self.assertEqual(yolo.serialize_detections([], [], [], [], "fixture"), [])

    def test_invalid_duplicate_or_outside_index_blocks(self):
        box = [[0., 0., 20., 30.]]
        points = [[[10., 20., .9] for _ in range(17)]]
        row = [0., 0., 20., 30., 1., .9, 0., 0.]
        for tracks in ([row, row], [[*row[:7], 2.]], [[*row[:4], -1., *row[5:]]]):
            with self.subTest(tracks=tracks), self.assertRaises(ModelBlocked):
                yolo.serialize_detections(box, [.9], points, tracks, "fixture")

    def test_nonfinite_pose_is_rejected(self):
        points = [[[10., 20., .9] for _ in range(17)]]
        points[0][0][0] = float("nan")
        with self.assertRaises(ModelBlocked):
            yolo.serialize_detections([[0., 0., 20., 30.]], [.9], points, [], "fixture")


class DecodeTests(unittest.TestCase):
    def run_decode(self, stamps, start_pts=0):
        request = fixture()
        asset = request["assets"][0]
        asset.update(fps_num=25, fps_den=1, time_base="1/1000")
        class Container:
            streams = SimpleNamespace(video=[SimpleNamespace(time_base=Fraction(1,1000), start_time=start_pts)])
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def seek(self, *args, **kwargs): pass
            def decode(self, stream):
                return iter(SimpleNamespace(pts=t, width=320, height=180, to_ndarray=lambda **kwargs: None) for t in stamps)
        with patch.dict(sys.modules, {"av": SimpleNamespace(open=lambda path: Container())}):
            return list(yolo.decode_frames("fixture-only", asset, yolo.options(request)))

    def test_original_pts_and_offset_are_preserved(self):
        frames = self.run_decode([1000, 1040, 1080, 1120], 1000)
        self.assertEqual([f[0]["pts"] for f in frames], [1000, 1040, 1080])
        self.assertEqual([f[0]["source_ms"] for f in frames], [0, 40, 80])
        self.assertEqual([f[0]["source_frame_index"] for f in frames], [0, 1, 2])
        self.assertEqual(frames[0][0]["stream_start_pts"], 1000)

    def test_duplicate_pts_rejected(self):
        with self.assertRaises(ModelBlocked) as caught:
            self.run_decode([0, 40, 40])
        self.assertEqual(caught.exception.code, "YOLO_TIMELINE_INVALID")

    def test_empty_window_rejected(self):
        with self.assertRaises(ModelBlocked) as caught:
            self.run_decode([1000])
        self.assertEqual(caught.exception.code, "YOLO_EMPTY_WINDOW")


class FileAndExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="yolo-cpu-guards-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def entry(self, relative, data):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"relative_path": relative, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def test_same_checkpoint_bytes_are_returned_after_pin_verification(self):
        entry = self.entry("models/weights/fixture.pt", b"fixture only")
        path, data = yolo.verify_file(self.root, entry, "models/weights/", (len(b"fixture only"), entry["sha256"]), True)
        path.write_bytes(b"replaced")
        self.assertEqual(data, b"fixture only")
        with self.assertRaises(ModelBlocked):
            yolo.verify_file(self.root, entry, "models/weights/", (entry["size_bytes"], "0"*64), True)

    def test_manifest_cannot_authorize_arbitrary_pickle(self):
        manifest = {"schema_version": "1.0", "model_id": yolo.MODEL_ID, "package_version": yolo.PACKAGE_VERSION,
                    "license": "AGPL-3.0", "package": self.entry("models/upstream/fake.whl", b"fake"),
                    "checkpoint": self.entry("models/weights/fake.pt", b"fake")}
        self.entry("models/weights/yolo11n-pose/reuse-manifest.json", json.dumps(manifest).encode())
        with patch.dict(os.environ, {"BTV_YOLO_POSE_MANIFEST": "models/weights/yolo11n-pose/reuse-manifest.json"}):
            with self.assertRaises(ModelBlocked) as caught:
                yolo.read_manifest(self.root)
        self.assertEqual(caught.exception.code, "YOLO_PIN_MISMATCH")

    def test_full_worker_request_keeps_missing_frames_and_training_scope(self):
        request = fixture()
        request["parameters"]["end_ms"] = 80
        asset = request["assets"][0]
        asset.update(self.entry("data/training/fixture.bin", b"not real media"))
        detections = yolo.serialize_detections([[0., 0., 20., 30.]], [.9], [[[10.,20.,.9]]*17],
                                             [[0.,0.,20.,30.,1.,.9,0.,0.]], "fixture-shot")
        timings = {"pose_wall_seconds": 0., "tracking_seconds": 0., "transfer_seconds": 0., "serialization_seconds": 0., "upstream_pose_milliseconds": {}}
        runtime = Mock(manifest={"checkpoint": {"scope": "fixture"}, "package": {"scope": "fixture"}},
                       predict=Mock(side_effect=[(detections,timings),([],timings)]), details=Mock(return_value={"scope":"fixture"}))
        frames = [({"pts": i*512, "time_base": "1/12800", "source_start_pts": 0, "stream_start_pts": 0,
                    "source_ms": i*40, "source_frame_index": i, "width": 320, "height": 180}, None) for i in range(2)]
        output = self.root/request["output_dir"]
        with patch.object(yolo, "Runtime", return_value=runtime), patch.object(yolo, "decode_frames", return_value=iter(frames)), \
             patch.object(yolo, "reserve", return_value=nullcontext()) as reservation:
            result = yolo.execute(request, self.root, output, Mock())
            reservation.assert_called_once_with(self.root, 100_000_000)
            features = json.loads((output/"features.json").read_text(encoding="utf-8"))
            self.assertEqual(result["events"], [])
            self.assertEqual(features["usage_scope"], "training_only")
            self.assertEqual(features["frame_count"], 2)
            self.assertEqual(features["frames"][1]["detections"], [])
            self.assertEqual(features["frames"][1]["missing_previously_seen_track_ids"], ["fixture-shot:anonymous-1"])
            self.assertEqual(features["frames"][1]["status"], "unknown")
            self.assertIsNone(features["accuracy"])
            self.assertIsNone(features["recall"])
            self.assertFalse(features["reid"])
            self.assertEqual(features["source_asset"], asset)
            report = json.loads((output/"report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["timeline_verification"]["expected_frame_count"], 2)
            self.assertGreaterEqual(report["timings_seconds"]["execute_elapsed_seconds"], report["timings_seconds"]["unattributed_seconds"])
            self.assertGreaterEqual(report["timings_seconds"]["unattributed_seconds"], 0)
            self.assertIn("excludes final report write", report["timing_measurement_boundary"])
            with self.assertRaises(FileExistsError):
                yolo.execute(request, self.root, output, Mock())

    def test_missing_first_or_final_cfr_frame_blocks_without_artifacts(self):
        for indices in ([0, 1], [1, 2], [0, 2]):
            with self.subTest(indices=indices):
                request = fixture()
                request["assets"][0].update(self.entry("data/fixture.bin", b"not real media"))
                frames = [({"source_frame_index": index}, None) for index in indices]
                runtime = Mock(predict=Mock(return_value=([], {"pose_wall_seconds": 0., "tracking_seconds": 0., "transfer_seconds": 0., "serialization_seconds": 0.})))
                output = self.root/request["output_dir"]
                with patch.object(yolo, "Runtime", return_value=runtime), patch.object(yolo, "decode_frames", return_value=iter(frames)), \
                     patch.object(yolo, "reserve", return_value=nullcontext()):
                    with self.assertRaises(ModelBlocked) as caught:
                        yolo.execute(request, self.root, output, Mock())
                self.assertEqual(caught.exception.code, "YOLO_TIMELINE_GAP")
                self.assertFalse((output/"features.json").exists())


if __name__ == "__main__":
    unittest.main()
