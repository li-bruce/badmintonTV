"""CPU-only boundary tests. Fake frames are not video/model accuracy evidence."""
import copy
from contextlib import nullcontext
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from packages.models import vl_embedding_reuse as vl
from packages.models.protocol import InvalidRequest, ModelBlocked


def request():
    return {"schema_version": "1.0", "job_id": "j", "attempt_id": "a", "operation": "video_embedding",
            "assets": [{"asset_id": "asset", "relative_path": "data/source.mp4", "duration_ms": 60000,
                        "provenance": {}, "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
            "parameters": {"model_id": vl.MODEL_ID, "windows": [{"asset_id": "asset", "start_ms": 5000, "end_ms": 11000}],
                           "queries": [{"query_id": "zh-1", "text": "羽毛球后退杀球", "language": "zh"}]},
            "output_dir": "models/handoff/new-attempt"}


class ParameterTests(unittest.TestCase):
    def test_conservative_defaults(self):
        result = vl.validate_parameters(request())
        self.assertEqual(result["num_frames"], 6)
        self.assertEqual(result["max_pixels"], 262144)
        self.assertFalse(result["compare_clip"])

    def test_worker_model_version_snapshot(self):
        r = request()
        r["parameters"]["model_version"] = "0.1.0"
        vl.validate_parameters(r)
        r["parameters"]["model_version"] = "other"
        with self.assertRaises(InvalidRequest):
            vl.validate_parameters(r)

    def test_unknown_and_remote_controls_rejected(self):
        for name in ("trust_remote_code", "device", "model_path", "video_url", "download"):
            r = request()
            r["parameters"][name] = True
            with self.subTest(name=name), self.assertRaises(InvalidRequest):
                vl.validate_parameters(r)

    def test_bounds_and_types(self):
        for key, value in (("num_frames", 9), ("num_frames", True), ("num_frames", 3),
                           ("max_pixels", 262145), ("max_pixels", 0), ("compare_clip", 1)):
            r = request()
            r["parameters"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(InvalidRequest):
                vl.validate_parameters(r)
        r = request()
        r["parameters"]["windows"][0]["end_ms"] = 35001
        with self.assertRaises(InvalidRequest):
            vl.validate_parameters(r)

    def test_no_unused_duplicate_or_unknown_assets(self):
        r = request()
        r["parameters"]["windows"] *= 2
        with self.assertRaises(InvalidRequest):
            vl.validate_parameters(r)
        r = request()
        r["parameters"]["windows"][0]["asset_id"] = "unknown"
        with self.assertRaises(InvalidRequest):
            vl.validate_parameters(r)
        r = request()
        r["assets"].append({**r["assets"][0], "asset_id": "unused"})
        with self.assertRaises(InvalidRequest):
            vl.validate_parameters(r)

    def test_chinese_query_required_and_bounded(self):
        for text, language in (("badminton smash", "en"), ("badminton", "zh"), ("中" * 513, "zh"), ("中\n文", "zh")):
            r = request()
            r["parameters"]["queries"][0].update(text=text, language=language)
            with self.subTest(text=text[:20]), self.assertRaises(InvalidRequest):
                vl.validate_parameters(r)


class ScopeTests(unittest.TestCase):
    def test_each_training_signal_overrides_general(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = request()["assets"][0]
            self.assertEqual(vl.usage_scope(asset, directory), "general")
            for changes in ({"usage_scope": "training_only"}, {"provenance": {"usage_scope": "training_only"}},
                            {"relative_path": "data/training/match/source.mp4"}):
                self.assertEqual(vl.usage_scope({**asset, "usage_scope": "general", **changes}, directory), "training_only")

    def test_resolved_training_path(self):
        with tempfile.TemporaryDirectory() as directory:
            physical = Path(directory).resolve() / "data" / "training" / "a.mp4"
            with patch.object(vl, "resolve_relative", return_value=physical):
                self.assertEqual(vl.usage_scope(request()["assets"][0], directory), "training_only")

    def test_unknown_scope_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InvalidRequest):
            vl.usage_scope({**request()["assets"][0], "usage_scope": "allow-anything"}, directory)


class IntegrityTests(unittest.TestCase):
    def test_upstream_inventory_exact(self):
        self.assertEqual(len(vl.FILES), 18)
        self.assertEqual(sum(size for size, _ in vl.FILES.values()), 4271068726)

    def test_missing_weights_explicit(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ModelBlocked) as raised:
            vl.verify_weights(directory)
        self.assertEqual(raised.exception.code, "MODEL_NOT_INSTALLED")

    def fixture(self, directory):
        folder = Path(directory) / "models" / "weights" / vl.MODEL_ID
        folder.mkdir(parents=True)
        name, data = "scripts/fixture.py", b"# Synthetic integrity fixture; never executed\n"
        path = folder / name
        path.parent.mkdir()
        path.write_bytes(data)
        manifest = {"schema_version": "1.0", "source": vl.SOURCE, "revision": vl.REVISION,
                    "files": [{"relative_path": f"models/weights/{vl.MODEL_ID}/{name}",
                               "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                               "source_url": f"{vl.SOURCE}/resolve/{vl.REVISION}/{name}"}]}
        target = folder / "weights-manifest.json"
        target.write_text(json.dumps(manifest), encoding="utf-8")
        files = {name: (len(data), hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest())}
        return folder, path, target, manifest, files

    def test_nested_reviewed_file_is_verified_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, _, _, _, files = self.fixture(directory)
            with patch.object(vl, "FILES", files):
                result, digest = vl.verify_weights(directory)
            self.assertEqual(result, folder.resolve())
            self.assertEqual(len(digest), 64)

    def test_changed_file_still_rejected_if_manifest_hash_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            _, path, target, manifest, files = self.fixture(directory)
            changed = b"!" + path.read_bytes()[1:]
            path.write_bytes(changed)
            manifest["files"][0]["sha256"] = hashlib.sha256(changed).hexdigest()
            target.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(vl, "FILES", files), self.assertRaises(ModelBlocked) as raised:
                vl.verify_weights(directory)
            self.assertEqual(raised.exception.code, "WEIGHT_HASH_MISMATCH")

    def test_wrong_revision_and_duplicate_file_rejected(self):
        for mutate in (lambda m: m.update(revision="main"), lambda m: m["files"].append(copy.deepcopy(m["files"][0]))):
            with tempfile.TemporaryDirectory() as directory:
                _, _, target, manifest, files = self.fixture(directory)
                mutate(manifest)
                target.write_text(json.dumps(manifest), encoding="utf-8")
                with patch.object(vl, "FILES", files), self.assertRaises(ModelBlocked) as raised:
                    vl.verify_weights(directory)
                self.assertEqual(raised.exception.code, "WEIGHT_MANIFEST_INVALID")

    def test_unreviewed_code_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "scripts").mkdir()
            (folder / "scripts" / "qwen3_vl_embedding.py").write_text("raise AssertionError('executed')", encoding="utf-8")
            with self.assertRaises(ModelBlocked) as raised:
                vl.load_reviewed_module(folder)
            self.assertEqual(raised.exception.code, "SOURCE_HASH_MISMATCH")


class SamplingTests(unittest.TestCase):
    def test_pixels_and_grid_bounded(self):
        for width, height in ((1920, 1080), (3840, 2160), (100, 50), (1, 500)):
            w, h = vl.bounded_size(width, height, 262144)
            self.assertEqual(w % 32, 0)
            self.assertEqual(h % 32, 0)
            self.assertLessEqual(w*h, 262144)
        with self.assertRaises(InvalidRequest):
            vl.bounded_size(4000, 3000, 262144)

    def test_vfr_timestamps_use_real_pts_not_ordinal_fps(self):
        calculate = vl.pts_timestamps([{"window_seconds": t} for t in (0.03, 0.81, 2.05, 2.91)])
        actual = calculate([0, 1, 2, 3], 999, 2)
        self.assertAlmostEqual(actual[0], 0.42)
        self.assertAlmostEqual(actual[1], 2.48)
        with self.assertRaises(InvalidRequest):
            calculate([3, 2, 1, 0], 1, 2)
        with self.assertRaises(InvalidRequest):
            calculate([0, 1, 2, 3], 1, 1)

    def test_mock_decode_preserves_pts_and_rejects_insufficient_frames(self):
        image = types.SimpleNamespace(convert=lambda mode: image, resize=lambda size, method: types.SimpleNamespace(size=size))
        def frame(pts):
            return types.SimpleNamespace(pts=pts, time_base=Fraction(1, 1000), width=320, height=192, to_image=lambda: image)
        class Container:
            streams = types.SimpleNamespace(video=[types.SimpleNamespace(start_time=1000, time_base=Fraction(1, 1000))])
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def seek(self, *args, **kwargs): pass
            def decode(self, stream): return iter([frame(n) for n in (1000, 1040, 2010, 2020)])
        fake_av = types.SimpleNamespace(open=lambda path: Container())
        fake_pil = types.SimpleNamespace(Image=types.SimpleNamespace(Resampling=types.SimpleNamespace(BICUBIC=3)))
        with patch.dict("sys.modules", {"av": fake_av, "PIL": fake_pil}):
            frames, points, _ = vl.decode_window(Path("fake.mp4"), {"start_ms": 0, "end_ms": 2000}, 2, 262144)
            self.assertEqual([p["pts"] for p in points], [1000, 2010])
            self.assertEqual([p["source_seconds"] for p in points], [0, 1.01])
            self.assertEqual(len(frames), 2)
            with self.assertRaises(InvalidRequest):
                vl.decode_window(Path("fake.mp4"), {"start_ms": 0, "end_ms": 2000}, 4, 262144)

    def test_nonfinite_vectors_fail_and_rank_deterministic(self):
        for vector in ([float("nan"), 0], [0, 0], [1]):
            with self.assertRaises(ValueError):
                vl.check_vector(vector, 2)
        result = vl.rankings([{"query_id": "q"}], [{"window_id": "b"}, {"window_id": "a"}], [[1, 0]], [[0, 1], [0, 1]])
        self.assertEqual([m["window_id"] for m in result[0]["matches"]], ["a", "b"])


class FailureTests(unittest.TestCase):
    def test_mock_execution_preserves_strict_scope_in_all_artifacts(self):
        # Transport/inheritance fixture only: no model prediction is exercised.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            r = request()
            r["assets"][0].update(usage_scope="general", provenance={"usage_scope": "training_only"}, match_id="m", source_type="synthetic")
            source = root / r["assets"][0]["relative_path"]
            source.parent.mkdir(parents=True)
            source.write_bytes(b"")
            torch = MagicMock()
            torch.__version__ = "2.8.0+fixture"
            torch.version.cuda = "fixture"
            torch.cuda.get_device_name.return_value = "fake GPU; no execution"
            torch.cuda.max_memory_allocated.return_value = 0
            torch.cuda.max_memory_reserved.return_value = 0
            transformers = types.SimpleNamespace(__version__="4.57.3", Qwen3VLProcessor=MagicMock())
            official = types.SimpleNamespace(Qwen3VLForEmbedding=MagicMock())
            timing = {"decode_seconds": 0, "frame_preprocess_seconds": 0}
            output = root / r["output_dir"]
            with patch.object(vl, "reserve", return_value=nullcontext()), \
                 patch.object(vl, "verify_weights", return_value=(root, "fixture")), \
                 patch.dict("sys.modules", {"transformers": transformers}), \
                 patch("packages.models.inference.get_torch", return_value=torch), \
                 patch.object(vl.importlib.metadata, "version", return_value="fixture"), \
                 patch.object(vl, "decode_window", return_value=([], [], timing)), \
                 patch.object(vl, "load_reviewed_module", return_value=official), \
                 patch.object(vl, "embed_one", return_value=([1.0]+[0.0]*2047, {})):
                result = vl.execute(r, root, output, lambda *args, **kwargs: None)
            self.assertEqual(result["events"], [])
            for artifact in result["artifacts"]:
                self.assertEqual(artifact["producer"]["usage_scope"], "training_only")
                payload = json.loads((root / artifact["relative_path"]).read_text(encoding="utf-8"))
                self.assertEqual(payload["usage_scope"], "training_only")
                self.assertEqual(payload["windows"][0]["usage_scope"], "training_only")
            kwargs = official.Qwen3VLForEmbedding.from_pretrained.call_args.kwargs
            self.assertTrue(kwargs["local_files_only"])
            self.assertTrue(kwargs["use_safetensors"])
            self.assertFalse(kwargs["trust_remote_code"])

    def test_failure_redacts_secrets_but_retains_original_type_and_stage(self):
        with patch.dict(os.environ, {"HF_TOKEN": "hf_testSecretLongValue"}):
            result = vl.safe_failure(ValueError("diagnostic hf_testSecretLongValue"), "decode")
        self.assertNotIn("hf_testSecretLongValue", json.dumps(result))
        self.assertEqual(result["stage"], "decode")
        self.assertEqual(result["type"], "ValueError")
        self.assertIn("diagnostic", result["traceback"])

    def test_missing_weight_failure_keeps_scope_and_one_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            r = request()
            r["assets"][0]["usage_scope"] = "training_only"
            source = root / r["assets"][0]["relative_path"]
            source.parent.mkdir(parents=True)
            source.write_bytes(b"")
            output = root / r["output_dir"]
            with patch.object(vl, "reserve", return_value=nullcontext()) as reserve, self.assertRaises(ModelBlocked):
                vl.execute(r, root, output, lambda *args, **kwargs: None)
            reserve.assert_called_once_with(root, 100000000)
            failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["usage_scope"], "training_only")
            self.assertEqual(failure["producer"]["usage_scope"], "training_only")
            self.assertEqual(failure["failure"]["code"], "MODEL_NOT_INSTALLED")
            self.assertFalse((output / "features.json").exists())

    def test_output_reuse_does_not_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            r = request()
            output = root / r["output_dir"]
            output.mkdir(parents=True)
            original = output / "failure.json"
            original.write_text("original", encoding="utf-8")
            with patch.object(vl, "reserve", return_value=nullcontext()), self.assertRaises(FileExistsError):
                vl.execute(r, root, output, lambda *args, **kwargs: None)
            self.assertEqual(original.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
