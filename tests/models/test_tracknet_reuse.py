"""CPU guard/algorithm tests only; fake heatmaps are never recognition evidence."""
from contextlib import nullcontext
from fractions import Fraction
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from packages.models import tracknet_reuse as tracknet
from packages.models.protocol import InvalidRequest, ModelBlocked

HAS_NUMPY = importlib.util.find_spec("numpy") is not None


def timings():
    return {key + "_seconds": 0.0 for key in ("decode", "pre", "model", "post")}


class ManualClock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def read(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.advance(seconds)


class TrackNetTestSetup:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="btv-tracknet-cpu-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        fixture = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/model-request.json"
        self.request = json.loads(fixture.read_text(encoding="utf-8"))
        self.request["parameters"] = {"model_id": tracknet.MODEL_ID, "mode": "causal_last", "start_ms": 0, "end_ms": 1000, "background_frames": 2}
        self.asset = self.request["assets"][0]
        self.asset["relative_path"] = "data/training/test.bin"
        source = self.root / self.asset["relative_path"]
        source.parent.mkdir(parents=True)
        source.write_bytes(b"structure-only-test-not-a-video")
        self.asset["size_bytes"] = source.stat().st_size
        self.asset["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.output = self.root / self.request["output_dir"]
        environment = patch.dict(os.environ, {"BTV_TRACKNET_MANIFEST": "models/weights/tracknetv3/reuse-manifest.json"})
        environment.start()
        self.addCleanup(environment.stop)


class TrackNetGuardTests(TrackNetTestSetup, unittest.TestCase):
    def test_worker_model_version_and_paced_request_guards(self):
        self.request["parameters"]["model_version"] = "0.1.0"
        self.assertFalse(tracknet.options(self.request)["paced_replay"])
        cases = ({"model_version": "0.2.0"}, {"model_version": None}, {"paced_replay": 1},
                 {"paced_replay": True, "mode": "offline_weight"}, {"replay_deadline_ms": 40},
                 {"paced_replay": True, "replay_deadline_ms": 0},
                 {"paced_replay": True, "replay_deadline_ms": float("nan")},
                 {"paced_replay": True, "replay_deadline_ms": True})
        for values in cases:
            with self.subTest(values=values):
                original = self.request["parameters"].copy()
                self.request["parameters"].update(values)
                with self.assertRaises(InvalidRequest):
                    tracknet.options(self.request)
                self.request["parameters"] = original

    def test_pacer_records_wait_late_backlog_and_no_drop(self):
        clock = ManualClock()
        pacer = tracknet.PacedReplay(0, 1000, 30)
        first, second = {"source_ms": 1000}, {"source_ms": 1040}
        with patch.object(tracknet.time, "perf_counter", clock.read), patch.object(tracknet.time, "sleep", clock.sleep):
            clock.advance(.005)
            pacer.start(first, 0, .005)
            clock.advance(.060)
            pacer.complete(first, prediction_emitted=True)
            clock.advance(.005)
            pacer.start(second, .065, .070)
            clock.advance(.010)
            pacer.complete(second, prediction_emitted=True)
            report = pacer.report()
        self.assertEqual(report["deadline_missed_frames"], 2)
        self.assertEqual(report["dropped_frames"], 0)
        self.assertAlmostEqual(second["replay"]["backlog_at_read_ms"], 25)
        self.assertEqual(first["replay"]["pending_after_completion"], 1)
        self.assertAlmostEqual(first["replay"]["decode_and_service_ms"], 65)
        self.assertAlmostEqual(second["replay"]["simulated_arrival_to_completion_ms"], 40)
        self.assertFalse(report["physical_live_end_to_end"])

    def test_pacer_sleep_chunks_and_wall_bound_are_enforced(self):
        clock = ManualClock()
        pacer = tracknet.PacedReplay(0, 0, 40)
        frame = {"source_ms": 180}
        with patch.object(tracknet.time, "perf_counter", clock.read), patch.object(tracknet.time, "sleep", clock.sleep):
            clock.advance(.005)
            pacer.start(frame, 0, .005)
            self.assertAlmostEqual(clock.now, .180)
            self.assertTrue(all(0 < delay <= .05 for delay in clock.sleeps))
            self.assertAlmostEqual(frame["replay"]["decoded_prefetch_lead_ms"], 175)
            clock.advance(121)
            with self.assertRaisesRegex(InvalidRequest, "120-second"):
                pacer.complete(frame, prediction_emitted=True)
    def test_bounds_and_unknown_parameters_fail_before_model_load(self):
        for changes in ({"end_ms": 30001}, {"start_ms": True}, {"background_frames": 0},
                        {"mode": "real_time_official"}, {"threshold": .01}, {"device": "remote"}):
            with self.subTest(changes=changes):
                original = self.request["parameters"].copy()
                self.request["parameters"].update(changes)
                with patch.object(tracknet, "Runtime", side_effect=AssertionError("must not load")):
                    with self.assertRaises(InvalidRequest):
                        tracknet.execute(self.request, self.root, self.output, Mock())
                self.request["parameters"] = original

    def test_training_scope_strictest_source_wins(self):
        self.assertEqual(tracknet.usage_scope(self.asset, self.root), "training_only")
        self.asset["relative_path"] = "data/general/test.bin"
        self.asset["usage_scope"] = "general"
        self.asset["provenance"]["usage_scope"] = "training_only"
        self.assertEqual(tracknet.usage_scope(self.asset, self.root), "training_only")
        self.asset["provenance"]["usage_scope"] = "general"
        self.asset["usage_scope"] = "training_only"
        self.assertEqual(tracknet.usage_scope(self.asset, self.root), "training_only")
        self.asset["usage_scope"] = "general"
        self.assertEqual(tracknet.usage_scope(self.asset, self.root), "general")
        self.asset["usage_scope"] = "anything"
        with self.assertRaises(InvalidRequest):
            tracknet.usage_scope(self.asset, self.root)

    def test_training_scope_resolved_alias_cannot_be_general(self):
        alias = self.root / "data/alias"
        try:
            alias.symlink_to(self.root / "data/training", target_is_directory=True)
        except OSError:
            self.skipTest("Windows account does not permit symlink creation")
        self.asset["relative_path"] = "data/alias/test.bin"
        self.assertEqual(tracknet.usage_scope(self.asset, self.root), "training_only")

    def test_missing_manifest_blocked_without_optional_imports(self):
        with self.assertRaisesRegex(ModelBlocked, "manifest is not installed") as caught:
            tracknet.read_manifest(self.root)
        self.assertEqual(caught.exception.code, "TRACKNET_NOT_INSTALLED")

    def test_source_hash_and_bytes_are_verified(self):
        tracknet.verify_file(self.root, self.asset)
        self.asset["sha256"] = "0" * 64
        with self.assertRaisesRegex(ModelBlocked, "hash differs"):
            tracknet.verify_file(self.root, self.asset)
        self.asset["size_bytes"] += 1
        with self.assertRaisesRegex(ModelBlocked, "size differs"):
            tracknet.verify_file(self.root, self.asset)

    def test_manifest_paths_cannot_escape_or_cross_owner(self):
        entry = {"relative_path": "models/../data/training/test.bin", "sha256": self.asset["sha256"], "size_bytes": self.asset["size_bytes"]}
        with self.assertRaises(InvalidRequest):
            tracknet.verify_file(self.root, entry, prefix="models/upstream/")
        entry["relative_path"] = self.asset["relative_path"]
        with self.assertRaises(InvalidRequest):
            tracknet.verify_file(self.root, entry, prefix="models/upstream/")

    def test_manifest_requires_reviewed_commit_and_both_intact_files(self):
        entries = []
        for relative, content in (("models/upstream/test/model.py", b"raise AssertionError('must not execute during metadata validation')"),
                                  ("models/weights/test/TrackNet_best.pt", b"not a checkpoint; metadata test only")):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            entries.append({"relative_path": relative, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        manifest = {"schema_version": "1.0", "source_commit": tracknet.COMMIT, "license": "MIT", "code": entries[0], "checkpoint": entries[1]}
        target = self.root / os.environ["BTV_TRACKNET_MANIFEST"]
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(manifest), encoding="utf-8")
        # Self-consistent fake code/manifest cannot satisfy the production pin.
        with self.assertRaises(ModelBlocked) as caught:
            tracknet.read_manifest(self.root)
        self.assertEqual(caught.exception.code, "TRACKNET_MANIFEST_INVALID")
        # Explicitly replace the immutable source pin only for metadata tests.
        with patch.object(tracknet, "CODE_SHA256", entries[0]["sha256"]), patch.object(tracknet, "CODE_SIZE", entries[0]["size_bytes"]):
            self.assertEqual(tracknet.read_manifest(self.root)[0], manifest)
            manifest["source_commit"] = "0" * 40
            target.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ModelBlocked) as caught:
                tracknet.read_manifest(self.root)
            self.assertEqual(caught.exception.code, "TRACKNET_MANIFEST_INVALID")
            manifest["source_commit"] = tracknet.COMMIT
            manifest["checkpoint"]["sha256"] = "0" * 64
            target.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ModelBlocked) as caught:
                tracknet.read_manifest(self.root)
            self.assertEqual(caught.exception.code, "TRACKNET_HASH_MISMATCH")

    def test_source_bytes_are_pinned_at_execution_read_even_after_prior_hash(self):
        path = self.root / "model.py"
        original, changed = b"verified-source", b"modified-source"
        path.write_bytes(original)
        with patch.object(tracknet, "CODE_SHA256", hashlib.sha256(original).hexdigest()), patch.object(tracknet, "CODE_SIZE", len(original)):
            source = tracknet.verified_code_bytes(path)
            self.assertEqual(source, original)
            path.write_bytes(changed)
            # The bytes already returned remain the verified bytes to compile.
            self.assertEqual(source, original)
            with self.assertRaises(ModelBlocked) as caught:
                tracknet.verified_code_bytes(path)
            self.assertEqual(caught.exception.code, "TRACKNET_CODE_PIN_MISMATCH")

    def test_existing_output_rejected_before_source_or_model_load(self):
        self.output.mkdir(parents=True)
        original = self.output / "tracknet-points.json"
        original.write_bytes(b"previous-attempt")
        with patch.object(tracknet, "reserve", return_value=nullcontext()), patch.object(tracknet, "Runtime", side_effect=AssertionError("must not load")):
            with self.assertRaises(FileExistsError):
                tracknet.execute(self.request, self.root, self.output, Mock())
        self.assertEqual(original.read_bytes(), b"previous-attempt")

    def fake_av(self, pts, width=16, height=16):
        stream = types.SimpleNamespace(start_time=100, time_base=Fraction(1, 1000))
        frames = [types.SimpleNamespace(pts=p, time_base=Fraction(1, 1000), width=width, height=height, to_image=Mock(return_value=Mock())) for p in pts]
        container = Mock()
        container.__enter__ = Mock(return_value=container)
        container.__exit__ = Mock(return_value=False)
        container.streams = types.SimpleNamespace(video=[stream])
        container.decode.return_value = iter(frames)
        av = types.SimpleNamespace(open=Mock(return_value=container))
        return av, frames

    def test_decode_preserves_vfr_pts_and_stream_origin(self):
        av, _ = self.fake_av([100, 133, 190, 260, 1100])
        with patch.dict("sys.modules", {"av": av}):
            result = list(tracknet.iter_frames("fake", tracknet.options(self.request), timings()))
        self.assertEqual([record["source_ms"] for record, _ in result], [0, 33, 90, 160])
        self.assertEqual([record["pts"] for record, _ in result], [100, 133, 190, 260])
        self.assertEqual(result[0][0]["time_base"], "1/1000")
        self.assertEqual(result[0][0]["stream_start_pts"], 100)

    def test_decode_missing_duplicate_pts_oversize_and_frame_cap_fail(self):
        for pts, width, cap in (([None], 16, 1800), ([100, 100], 16, 1800), ([100], 9000000, 1800), ([100, 110], 16, 1)):
            with self.subTest(pts=pts, width=width, cap=cap):
                av, frames = self.fake_av(pts, width=width)
                with patch.dict("sys.modules", {"av": av}), patch.object(tracknet, "MAX_FRAMES", cap):
                    with self.assertRaises(ValueError):
                        list(tracknet.iter_frames("fake", tracknet.options(self.request), timings()))
                if width > 16:
                    frames[0].to_image.assert_not_called()


@unittest.skipUnless(HAS_NUMPY, "NumPy absent; no installation requested")
class TrackNetAlgorithmTests(TrackNetTestSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import numpy as np
        self.np = np

    def runtime(self, bg_mode="concat"):
        np = self.np
        runtime = types.SimpleNamespace(seq_len=3, bg_mode=bg_mode, synchronize=Mock())
        runtime.resize = lambda image: image
        runtime.image_array = lambda image: np.full((1, 1, 3), image, dtype=np.uint8)
        runtime.background = lambda arrays: float(np.stack(arrays).mean())
        runtime.calls = []
        def prepare(frames, background):
            runtime.calls.append((tuple(frames), background))
            return list(frames)
        runtime.prepare = prepare
        runtime.predict = lambda frames: np.array([np.full((2, 2), frame, dtype=np.float32) for frame in frames])
        runtime.point = lambda heatmap, record: {"status": "observed", "x": float(heatmap[0, 0]), "y": 1, "response_peak": .7, "missing_reason": None}
        runtime.manifest = {"code": {"relative_path": "models/upstream/TEST-ONLY/model.py"}, "checkpoint": {"relative_path": "models/weights/TEST-ONLY/not-real.pt"}}
        runtime.details = lambda: {"device": "test-double-not-a-model"}
        return runtime

    def fake_frames(self, path, opts, clocks):
        for index in range(7):
            clocks["decode_seconds"] += .001
            yield {"frame_index": index, "source_ms": index * 40, "pts": 100 + index * 40,
                   "time_base": "1/1000", "stream_start_pts": 100, "width": 16, "height": 16}, index

    def test_triangular_and_boundary_ensembles_match_upstream(self):
        self.assertEqual(tracknet.triangular_weights(5), [1/9, 2/9, 3/9, 2/9, 1/9])
        ensemble = tracknet.Ensemble(3)
        values = [self.np.array([value], dtype=float) for value in (1, 10, 100)]
        ensemble.add(0, values)
        self.assertEqual(float(ensemble.pop(0)[0]), 1)
        ensemble.add(1, [value * 2 for value in values])
        self.assertEqual(float(ensemble.pop(1)[0]), 6)  # edge (10 + 2) / 2
        ensemble.add(2, [value * 3 for value in values])
        self.assertEqual(float(ensemble.pop(2)[0]), 35.75)  # 100*.25 + 20*.5 + 3*.25
        self.assertEqual(float(ensemble.pop(3)[0]), 115)  # tail (200 + 30) / 2
        self.assertEqual(float(ensemble.pop(4)[0]), 300)

    def test_causal_predictions_never_use_future_or_revisit_calibration(self):
        runtime = self.runtime()
        with patch.object(tracknet, "iter_frames", side_effect=self.fake_frames):
            records, report = tracknet.process("fake", tracknet.options(self.request), runtime, Mock())
        self.assertEqual([row["missing_reason"] for row in records[:2]], ["background_warmup"] * 2)
        self.assertEqual(runtime.calls, [((index-2, index-1, index), .5) for index in range(2, 7)])
        self.assertEqual([row["x"] for row in records[2:]], [2, 3, 4, 5, 6])
        self.assertTrue(all(row["available_after_source_ms"] == row["source_ms"] for row in records))
        self.assertEqual(report["background_source_ms"], [0, 40])
        self.assertEqual(report["dropped_frames_by_adapter"], 0)
        self.assertIsNone(report["live_end_to_end_latency_ms"])
        self.assertEqual(report["observed_pts_span_seconds"], .24)
        self.assertEqual(report["requested_source_window_seconds"], 1)
        self.assertEqual(report["paced_replay"], {"enabled": False})

    def timed_replay(self, model_seconds):
        clock = ManualClock()
        runtime = self.runtime()
        self.request["parameters"].update(paced_replay=True, replay_deadline_ms=40)
        original_predict = runtime.predict
        def predict(frames):
            clock.advance(model_seconds)
            return original_predict(frames)
        runtime.predict = predict
        def source(path, opts, clocks):
            for record, image in self.fake_frames(path, opts, clocks):
                clock.advance(.005)  # Actual modeled decoder work, not a wait.
                yield record, image
        with patch.object(tracknet.time, "perf_counter", clock.read), patch.object(tracknet.time, "sleep", clock.sleep), patch.object(tracknet, "iter_frames", side_effect=source):
            records, report = tracknet.process("fake", tracknet.options(self.request), runtime, Mock())
        return records, report, runtime, clock

    def test_paced_fast_pipeline_reports_arrivals_without_future_inference(self):
        records, report, runtime, clock = self.timed_replay(.010)
        self.assertEqual([row["replay"]["scheduled_arrival_ms"] for row in records], [0, 40, 80, 120, 160, 200, 240])
        self.assertTrue(all(row["replay"]["processing_started_ms"] + 1e-8 >= row["replay"]["scheduled_arrival_ms"] for row in records))
        self.assertEqual(runtime.calls, [((index-2, index-1, index), .5) for index in range(2, 7)])
        self.assertEqual(report["paced_replay"]["deadline_missed_frames"], 0)
        self.assertEqual(report["paced_replay"]["warmup_frames"], 2)
        self.assertAlmostEqual(report["paced_replay"]["decode_and_service_ms"]["mean"], 15)
        self.assertLess(report["steady_rtf"], 1)
        self.assertGreater(report["steady_wall_rtf_including_pacing"], 1)
        self.assertGreater(report["paced_replay"]["pacing_wait_seconds"], 0)
        self.assertIsNone(report["live_end_to_end_latency_ms"])

    def test_paced_slow_pipeline_keeps_late_frames_and_exposes_backlog(self):
        records, report, runtime, clock = self.timed_replay(.100)
        self.assertEqual(len(records), 7)
        self.assertEqual(report["paced_replay"]["prediction_frames"], 5)
        self.assertEqual(report["paced_replay"]["deadline_missed_prediction_frames"], 5)
        self.assertEqual(report["paced_replay"]["dropped_frames"], 0)
        self.assertGreater(report["paced_replay"]["max_pending_frames_after_completion"], 0)
        self.assertGreater(report["paced_replay"]["backlog_at_read_ms"]["max"], 100)
        self.assertGreater(report["steady_rtf"], 1)
        self.assertTrue(all(not row["replay"]["dropped"] for row in records))

    def test_offline_marks_lookahead_and_emits_all_trailing_frames(self):
        self.request["parameters"]["mode"] = "offline_weight"
        runtime = self.runtime("")
        with patch.object(tracknet, "iter_frames", side_effect=self.fake_frames):
            records, report = tracknet.process("fake", tracknet.options(self.request), runtime, Mock())
        self.assertEqual([row["x"] for row in records], list(range(7)))
        self.assertEqual(records[0]["available_after_source_ms"], 80)
        self.assertEqual(records[-1]["available_after_source_ms"], 240)
        self.assertEqual(report["model_windows"], 5)
        self.assertEqual(report["missing_count"], 0)
        self.assertTrue(all(not row["inpainted"] for row in records))

    def test_offline_background_dependency_is_in_each_availability_time(self):
        self.request["parameters"]["mode"] = "offline_weight"
        runtime = self.runtime()
        with patch.object(tracknet, "iter_frames", side_effect=self.fake_frames):
            records, report = tracknet.process("fake", tracknet.options(self.request), runtime, Mock())
        self.assertEqual(report["background_source_ms"][-1], 240)
        self.assertTrue(all(row["available_after_source_ms"] >= 240 for row in records))

    def test_causal_background_budget_fails_without_truncating(self):
        runtime = self.runtime()
        with patch.object(tracknet, "iter_frames", side_effect=self.fake_frames), patch.object(tracknet, "BACKGROUND_PIXELS", 300):
            with self.assertRaisesRegex(InvalidRequest, "pixel budget"):
                tracknet.process("fake", tracknet.options(self.request), runtime, Mock())

    def test_short_window_does_not_claim_successful_prediction(self):
        runtime = self.runtime()
        self.request["parameters"]["background_frames"] = 10
        with patch.object(tracknet, "iter_frames", side_effect=self.fake_frames):
            with self.assertRaisesRegex(InvalidRequest, "too short"):
                tracknet.process("fake", tracknet.options(self.request), runtime, Mock())

    def test_artifacts_preserve_scope_pts_and_exclusive_output(self):
        runtime = self.runtime()
        with patch.object(tracknet, "reserve", return_value=nullcontext()), patch.object(tracknet, "Runtime", return_value=runtime), patch.object(tracknet, "iter_frames", side_effect=self.fake_frames):
            result = tracknet.execute(self.request, self.root, self.output, Mock())
        self.assertEqual(result["events"], [])
        self.assertEqual(len(result["artifacts"]), 2)
        for artifact in result["artifacts"]:
            self.assertEqual(artifact["producer"]["usage_scope"], "training_only")
            content = json.loads((self.root / artifact["relative_path"]).read_text(encoding="utf-8"))
            self.assertEqual(content["usage_scope"], "training_only")
            self.assertIsNone(content["accuracy"])
        points = json.loads((self.output / "tracknet-points.json").read_text(encoding="utf-8"))
        self.assertEqual(points["frames"][0]["pts"], 100)
        self.assertIsNone(points["frames"][0]["x"])
        self.assertEqual(points["inpaintnet"], "not_run")

    @unittest.skipUnless(importlib.util.find_spec("cv2"), "OpenCV absent; no installation requested")
    def test_postprocess_empty_and_largest_rectangle_not_largest_peak(self):
        import cv2
        heatmap = self.np.zeros((288, 512), dtype=self.np.float32)
        missing = tracknet.heatmap_point(heatmap, 1024, 576, cv2)
        self.assertEqual(missing["status"], "missing")
        self.assertIsNone(missing["x"])
        heatmap[10:12, 20:22] = .99
        heatmap[30:40, 50:60] = .6
        point = tracknet.heatmap_point(heatmap, 1024, 576, cv2)
        self.assertEqual((point["x"], point["y"]), (110, 70))
        self.assertAlmostEqual(point["response_peak"], .6)


if __name__ == "__main__":
    unittest.main()
