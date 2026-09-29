"""CPU-only contracts and synthetic decoder fixtures, not model/video accuracy."""
from contextlib import nullcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from packages.models import continuous_pose_reuse as pose
from packages.models.protocol import InvalidRequest, ModelBlocked


def request():
    return {"schema_version": "1.0", "job_id": "j", "attempt_id": "a", "operation": "pose",
            "assets": [{"asset_id": "asset", "relative_path": "data/source.mp4", "duration_ms": 6000,
                        "provenance": {}, "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest(), "match_id": "m"}],
            "parameters": {"model_id": pose.MODEL_ID, "start_ms": 0, "end_ms": 3000},
            "output_dir": "models/handoff/continuous-new"}


def frame(pts, width=1280, height=720, base=Fraction(1, 15360)):
    image = types.SimpleNamespace(convert=lambda mode: image)
    return types.SimpleNamespace(pts=pts, time_base=base, width=width, height=height, to_image=lambda: image)


def decoder(frames, offset=0, base=Fraction(1, 15360)):
    class Container:
        streams = types.SimpleNamespace(video=[types.SimpleNamespace(start_time=offset, time_base=base)])
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def seek(self, *args, **kwargs): pass
        def decode(self, stream): return iter(frames)
    return types.SimpleNamespace(open=lambda path: Container())


def read_frames(frames, start_ms=0, end_ms=3000, offset=0):
    timing = {"decode_seconds": 0.0, "preprocess_seconds": 0.0}
    with patch.dict("sys.modules", {"av": decoder(frames, offset)}):
        return list(pose.iter_source_frames(Path("synthetic.mp4"), {"start_ms": start_ms, "end_ms": end_ms}, timing)), timing


class Raw:
    def __init__(self, value): self.value = value
    def detach(self): return self
    def cpu(self): return self
    def tolist(self): return self.value


class Indices(list):
    def nonzero(self): return self
    def flatten(self): return self
    def numel(self): return len(self)


class Scores(list):
    def __ge__(self, minimum):
        return Indices(i for i, value in enumerate(self) if value >= minimum)


def raw_prediction(count=1):
    return {"scores": Scores([0.9]*count), "boxes": [Raw([1.0, 2.0, 80.0, 100.0]) for _ in range(count)],
            "keypoints": [Raw([[10.0, 20.0, 1.0] for _ in range(17)]) for _ in range(count)],
            "keypoints_scores": [Raw([7.5]*17) for _ in range(count)]}


class BoundsTests(unittest.TestCase):
    def test_defaults_and_worker_version(self):
        r = request()
        r["parameters"] = {"model_id": pose.MODEL_ID, "model_version": "0.1.0"}
        p = pose.validate_parameters(r)
        self.assertEqual((p["start_ms"], p["end_ms"], p["score_threshold"]), (0, 3000, 0.7))

    def test_time_and_type_bounds(self):
        for change in ({"end_ms": 3001}, {"start_ms": True}, {"start_ms": -1}, {"end_ms": 0},
                       {"score_threshold": float("nan")}, {"score_threshold": True}, {"score_threshold": 1.0},
                       {"model_version": "other"}, {"sample_fps": 30}, {"trust_remote_code": True}):
            r = request()
            r["parameters"].update(change)
            with self.subTest(change=change), self.assertRaises(InvalidRequest):
                pose.validate_parameters(r)

    def test_wrong_capability_or_asset_count(self):
        r = request()
        r["operation"] = "video_embedding"
        with self.assertRaises(InvalidRequest): pose.validate_parameters(r)
        r = request()
        r["assets"] *= 2
        with self.assertRaises(InvalidRequest): pose.validate_parameters(r)


class ContinuousDecoderTests(unittest.TestCase):
    def test_30fps_preserves_every_original_pts_no_rounded_ms_sampling(self):
        original = [frame(i * 512) for i in range(91)]
        values, timing = read_frames(original)
        self.assertEqual(len(values), 90)
        self.assertEqual([record["pts"] for record, _ in values], [i*512 for i in range(90)])
        self.assertEqual([record["frame_index"] for record, _ in values], list(range(90)))
        self.assertAlmostEqual(values[1][0]["source_ms"], 33.333333, places=6)
        self.assertLessEqual(sum(r["width"]*r["height"] for r, _ in values), 100000000)
        self.assertGreaterEqual(timing["decode_seconds"], 0)

    def test_exact_window_boundaries_and_stream_origin(self):
        # Origin 1 second; a 100..200ms relative interval includes only three frames.
        original = [frame(15360+i*512) for i in range(10)]
        values, _ = read_frames(original, 100, 200, offset=15360)
        self.assertEqual([r["pts"] for r, _ in values], [16896, 17408, 17920])
        self.assertEqual(values[0][0]["source_ms"], 100.0)
        self.assertEqual(values[0][0]["stream_start_pts"], 15360)

    def test_vfr_source_times_preserved_without_duplicate_or_interpolation(self):
        original = [frame(n) for n in (0, 100, 601, 999, 2510)]
        values, _ = read_frames(original)
        self.assertEqual([r["pts"] for r, _ in values], [0, 100, 601, 999, 2510])

    def test_more_than_100_frames_fails_instead_of_truncating_success(self):
        with self.assertRaisesRegex(InvalidRequest, "100 frames"):
            read_frames([frame(i*200, width=32, height=32) for i in range(101)])

    def test_cumulative_source_pixels_enforced_before_image_conversion(self):
        with self.assertRaisesRegex(InvalidRequest, "100 million"):
            read_frames([frame(i*512, width=3840, height=2160) for i in range(13)])

    def test_missing_nonmonotonic_or_changing_frames_fail(self):
        for original in ([frame(None)], [frame(0), frame(0)], [frame(512), frame(0)],
                         [frame(0), frame(512, width=640)], [frame(0, width=5000, height=3000)], []):
            with self.subTest(count=len(original)), self.assertRaises(InvalidRequest):
                read_frames(original)


class FailureTests(unittest.TestCase):
    def test_mock_success_preserves_artifact_scope_pts_and_no_identity(self):
        # This verifies the artifact boundary only; the model call is mocked.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            r = request()
            r["assets"][0]["provenance"] = {"usage_scope": "training_only"}
            source = root / r["assets"][0]["relative_path"]
            source.parent.mkdir(parents=True)
            source.write_bytes(b"")
            folder = root / "models" / "weights" / "fixture"
            folder.mkdir(parents=True)
            (folder / "weights-manifest.json").write_text("{}", encoding="utf-8")
            torch = MagicMock()
            torch.cuda.get_device_name.return_value = "fixture; no GPU execution"
            torch.cuda.max_memory_allocated.return_value = 0
            torch.cuda.max_memory_reserved.return_value = 0
            torch.version.cuda = "fixture"
            torch.inference_mode.side_effect = nullcontext
            torch.load.return_value = {}
            model = MagicMock(return_value=[raw_prediction()])
            factory = MagicMock(return_value=model)
            transform = MagicMock(return_value=MagicMock())
            modules = {"torchvision.models.detection": types.SimpleNamespace(keypointrcnn_resnet50_fpn=factory),
                       "torchvision.transforms.functional": types.SimpleNamespace(pil_to_tensor=transform)}
            record = {"frame_index": 0, "pts": 512, "time_base": "1/15360", "stream_start_pts": 0,
                      "stream_time_base": "1/15360", "source_ms": 33.333333, "width": 1280, "height": 720}
            output = root / r["output_dir"]
            with patch.object(pose, "reserve", return_value=nullcontext()), \
                 patch("packages.models.inference.get_torch", return_value=torch), \
                 patch("packages.models.inference.weights_dir", return_value=folder), \
                 patch.dict("sys.modules", modules), \
                 patch.object(pose.importlib.metadata, "version", return_value="fixture"), \
                 patch.object(pose, "iter_source_frames", return_value=((record, None) for _ in [0])):
                result = pose.execute(r, root, output, lambda *args, **kwargs: None)
            self.assertEqual(result["events"], [])
            for artifact in result["artifacts"]:
                self.assertEqual(artifact["producer"]["usage_scope"], "training_only")
                payload = json.loads((root / artifact["relative_path"]).read_text(encoding="utf-8"))
                self.assertEqual(payload["usage_scope"], "training_only")
            features = json.loads((output / "features.json").read_text(encoding="utf-8"))
            self.assertEqual(features["frames"][0]["pts"], 512)
            detection = features["frames"][0]["detections"][0]
            self.assertIsNone(detection["track_id"])
            self.assertIsNone(detection["player_id"])
            self.assertEqual(detection["detection_id"], "0:0")
            model.load_state_dict.assert_called_once_with({}, strict=True)
            self.assertTrue(torch.load.call_args.kwargs["weights_only"])

    def test_missing_dependency_preserves_training_scope_and_one_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            r = request()
            r["assets"][0]["provenance"] = {"usage_scope": "training_only"}
            source = root / r["assets"][0]["relative_path"]
            source.parent.mkdir(parents=True)
            source.write_bytes(b"")
            output = root / r["output_dir"]
            with patch.object(pose, "reserve", return_value=nullcontext()) as reserve, \
                 patch("packages.models.inference.get_torch", side_effect=ModelBlocked("CUDA_UNAVAILABLE", "fixture")), \
                 self.assertRaises(ModelBlocked):
                pose.execute(r, root, output, lambda *args, **kwargs: None)
            reserve.assert_called_once_with(root, 100000000)
            failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["usage_scope"], "training_only")
            self.assertEqual(failure["producer"]["usage_scope"], "training_only")
            self.assertEqual(failure["failure"]["code"], "CUDA_UNAVAILABLE")
            self.assertEqual(failure["frames_processed"], 0)
            self.assertFalse((output / "features.json").exists())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            r = request()
            output = root / r["output_dir"]
            output.mkdir(parents=True)
            target = output / "features.json"
            target.write_text("original", encoding="utf-8")
            with patch.object(pose, "reserve", return_value=nullcontext()), self.assertRaises(FileExistsError):
                pose.execute(r, root, output, lambda *args, **kwargs: None)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")


class PredictionTests(unittest.TestCase):
    def test_raw_score_visibility_and_no_identity_preserved(self):
        detections, omitted = pose.prediction_record(raw_prediction(), 0.7, None)
        self.assertEqual(omitted, 0)
        self.assertEqual(detections[0]["keypoint_scores"], [7.5]*17)
        self.assertEqual(detections[0]["keypoints_xyv"], [[10.0, 20.0, 1.0]]*17)
        self.assertIsNone(detections[0]["track_id"])
        self.assertIsNone(detections[0]["player_id"])

    def test_detection_cap_reports_omissions(self):
        detections, omitted = pose.prediction_record(raw_prediction(12), 0.7, None)
        self.assertEqual(len(detections), 10)
        self.assertEqual(omitted, 2)

    def test_nonfinite_degenerate_or_wrong_shape_not_silently_published(self):
        for key, replacement in (("boxes", Raw([0, 0, 0, 2])), ("boxes", Raw([0, 0, float("inf"), 2])),
                                 ("keypoints", Raw([[1, 2, 1]]*16)), ("keypoints_scores", Raw([float("nan")]*17))):
            prediction = raw_prediction()
            prediction[key][0] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):
                pose.prediction_record(prediction, 0.7, None)

    def test_no_detections_remain_empty_unknown(self):
        self.assertEqual(pose.prediction_record(raw_prediction(0), 0.7, None), ([], 0))


if __name__ == "__main__":
    unittest.main()
