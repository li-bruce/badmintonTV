"""No-network, no-ML adapter guards; fixtures never represent model accuracy."""

from contextlib import redirect_stdout
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from packages.models import inference, protocol, registry, storage
from packages.models.protocol import InvalidRequest, ModelBlocked
from scripts.models import download_weights


class Response(io.BytesIO):
    """An in-memory HTTP body; no request reaches a remote service."""

    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


class AdapterGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="btv-adapter-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "storage"
        self.root.mkdir()
        environment = patch.dict(os.environ, {"BTV_STORAGE_ROOT": str(self.root), "BTV_LLM_CONFIG": ""})
        environment.start()
        self.addCleanup(environment.stop)
        disk = patch.object(storage.shutil, "disk_usage", return_value=types.SimpleNamespace(free=1_000_000_000_000))
        disk.start()
        self.addCleanup(disk.stop)
        self.output = self.root / "models/jobs/mock-job/mock-attempt"
        self.progress = Mock()

    def request(self, model_id="query-rule-v1", operation="query_parse"):
        return {"schema_version": "1.0", "job_id": "mock-job", "attempt_id": "mock-attempt",
                "operation": operation, "assets": [],
                "parameters": {"model_id": model_id, "text": "展搓然后收搓"},
                "output_dir": "models/jobs/mock-job/mock-attempt"}

    def assert_no_writer_lock(self):
        self.assertFalse((self.root / "models/.writer-reservation.json").exists())

    def fake_video(self, timestamps, width=16, height=16):
        stream = types.SimpleNamespace(start_time=0, time_base=Fraction(1, 1000))
        to_image = Mock(return_value=types.SimpleNamespace(width=width, height=height))
        frames = (types.SimpleNamespace(pts=pts, width=width, height=height, to_image=to_image) for pts in timestamps)
        container = Mock()
        container.__enter__ = Mock(return_value=container)
        container.__exit__ = Mock(return_value=False)
        container.streams = types.SimpleNamespace(video=[stream])
        container.decode.return_value = frames
        av = types.ModuleType("av")
        av.open = Mock(return_value=container)
        return av, to_image

    def partial_metadata(self, partial, maximum, expected_sha=None, url="https://invalid.test/mock"):
        metadata = {"url": url, "maximum": maximum, "sha256": expected_sha, "blob": None, "hash_prefix": None}
        partial.with_name(partial.name + ".source.json").write_text(json.dumps(metadata), encoding="utf-8")

    def canonical_request(self):
        default = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures"
        fixtures = Path(os.environ.get("BTV_CONTRACT_FIXTURES_DIR", str(default)))
        fixture = fixtures / "model-request.json"
        if not fixture.is_file():
            self.skipTest("Set BTV_CONTRACT_FIXTURES_DIR to the shared canonical fixtures directory")
        return json.loads(fixture.read_text(encoding="utf-8"))

    def test_shared_canonical_analyze_fixture_reports_blocked_with_attempt(self):
        request = self.canonical_request()
        self.assertEqual(request["operation"], "analyze")
        protocol.validate_request(request, self.root)
        request_path, result_path = self.base / "canonical-request.json", self.base / "canonical-result.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        with redirect_stdout(io.StringIO()), patch.object(inference, "get_torch", side_effect=AssertionError("uninstalled fixture must not load ML")):
            exit_code = protocol.run_request(request_path, result_path)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual((exit_code, result["status"]), (2, "blocked"))
        self.assertEqual(result["job_id"], request["job_id"])
        self.assertEqual(result["attempt_id"], request["attempt_id"])
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(result["events"], [])
        self.assertTrue(result["error"]["code"])

    def test_complete_assets_preserve_shared_nullable_metadata(self):
        request = self.canonical_request()
        asset = request["assets"][0]
        asset.update(fps_num=None, fps_den=None, time_base=None, acquired_at=None)
        protocol.validate_request(request, self.root)
        asset["fps_num"] = 25
        with self.assertRaises(InvalidRequest):
            protocol.validate_request(request, self.root)

    def test_portable_paths_and_identifiers_reject_shared_unsafe_characters(self):
        request = self.request()
        for control in ("\x00", "\t", "\n", "\x1f"):
            request["job_id"] = "job" + control + "suffix"
            with self.subTest(control=repr(control)), self.assertRaises(InvalidRequest):
                protocol.validate_request(request, self.root)
        for character in '\x00\t\n\x1f:*?"<>|':
            with self.subTest(character=repr(character)), self.assertRaises(InvalidRequest):
                protocol.resolve_relative(self.root, f"models/file{character}name")

    def test_unknown_and_untrained_models_block_before_work(self):
        cases = [("unregistered", "pose", "MODEL_NOT_REGISTERED"),
                 ("skeleton-temporal-v1", "movement_classification", "TRAINING_DATA_REQUIRED")]
        for model_id, operation, code in cases:
            with self.subTest(model=model_id), patch.object(inference, "get_torch", side_effect=AssertionError("must not import torch")):
                with self.assertRaises(ModelBlocked) as caught:
                    inference.execute(self.request(model_id, operation), self.root, self.output, self.progress)
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(self.output.exists())
                self.assert_no_writer_lock()

    def test_capability_mismatch_is_rejected_before_model_load(self):
        with patch.object(inference, "get_torch", side_effect=AssertionError("must not import torch")):
            with self.assertRaises(ValueError):
                inference.execute(self.request("query-rule-v1", "pose"), self.root, self.output, self.progress)
        self.assert_no_writer_lock()

    def test_missing_endpoint_is_blocked_and_reservation_released(self):
        with self.assertRaises(ModelBlocked) as caught:
            inference.execute(self.request("query-endpoint-v1"), self.root, self.output, self.progress)
        self.assertEqual(caught.exception.code, "ENDPOINT_NOT_CONFIGURED")
        self.assert_no_writer_lock()

    def test_rule_parser_artifacts_are_explicitly_not_video_evidence_and_not_replaced(self):
        request = self.request()
        result = inference.execute(request, self.root, self.output, self.progress)
        self.assertEqual(result["events"], [])
        self.assertEqual(len(result["artifacts"]), 2)
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        report = json.loads((self.output / "query-report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["is_video_evidence"])
        self.assertTrue(report["human_review_required"])
        with self.assertRaises(FileExistsError):
            inference.execute(request, self.root, self.output, self.progress)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, before)
        self.assert_no_writer_lock()

    def test_asset_hash_mismatch_prevents_decode_and_preserves_source(self):
        path = self.root / "data/synthetic.bin"
        path.parent.mkdir()
        content = b"in-memory protocol fixture, not a video"
        path.write_bytes(content)
        request = self.request("torchvision-keypointrcnn", "pose")
        request["assets"] = [{"relative_path": "data/synthetic.bin", "sha256": "0" * 64}]
        with patch.object(inference, "decode_samples", side_effect=AssertionError("must not decode")), \
             patch.object(inference, "get_torch", side_effect=AssertionError("must not import torch")):
            with self.assertRaisesRegex(ValueError, "SHA256"):
                inference.execute(request, self.root, self.output, self.progress)
        self.assertEqual(path.read_bytes(), content)
        self.assert_no_writer_lock()

    def test_missing_torch_and_unavailable_cuda_are_distinct_blocked_states(self):
        with patch.dict(sys.modules, {"torch": None}):
            with self.assertRaises(ModelBlocked) as caught:
                inference.get_torch()
            self.assertEqual(caught.exception.code, "DEPENDENCY_NOT_INSTALLED")
        fake = types.ModuleType("torch")
        fake.cuda = types.SimpleNamespace(is_available=lambda: False)
        with patch.dict(sys.modules, {"torch": fake}):
            with self.assertRaises(ModelBlocked) as caught:
                inference.get_torch()
            self.assertEqual(caught.exception.code, "CUDA_UNAVAILABLE")

    def test_binary_dependency_load_errors_are_blocked_without_leaking_details(self):
        for error in (OSError('private binary path'), RuntimeError('private driver detail')):
            with self.subTest(error=type(error).__name__), patch('builtins.__import__', side_effect=error):
                with self.assertRaises(ModelBlocked) as caught:
                    inference.get_torch()
            self.assertEqual(caught.exception.code, 'DEPENDENCY_UNAVAILABLE')
            self.assertNotIn('private', caught.exception.message)

    def test_weights_require_manifest_and_expected_files(self):
        with self.assertRaises(ModelBlocked):
            inference.weights_dir(self.root, "qwen3-0.6b")
        folder = self.root / "models/weights/qwen3-0.6b"
        folder.mkdir(parents=True)
        (folder / "weights-manifest.json").write_text('{"schema_version":"1.0","files":[]}', encoding="utf-8")
        with self.assertRaises(ModelBlocked):
            inference.weights_dir(self.root, "qwen3-0.6b")

    def test_catalog_corrupt_manifest_isolated_to_one_model(self):
        folder = self.root / "models/weights/qwen3-0.6b"
        folder.mkdir(parents=True)
        (folder / "weights-manifest.json").write_text("broken JSON", encoding="utf-8")
        with patch.object(registry.importlib.util, "find_spec", return_value=object()):
            catalog = registry.catalog()
        by_id = {model["model_id"]: model for model in catalog["models"]}
        self.assertEqual(by_id["query-rule-v1"]["status"], "ready")
        self.assertIn(by_id["qwen3-0.6b"]["status"], ("unavailable", "not_installed"))
        self.assertTrue(by_id["qwen3-0.6b"]["reason"])

    def test_reservation_is_exclusive_and_preserves_preexisting_ledger(self):
        with storage.reserve(self.root, 1000):
            ledger = self.root / "models/.writer-reservation.json"
            original = ledger.read_bytes()
            with self.assertRaises(ModelBlocked) as caught:
                with storage.reserve(self.root, 1000):
                    self.fail("nested writer must not acquire the reservation")
            self.assertEqual(caught.exception.code, "OWNER_BUSY")
            self.assertEqual(ledger.read_bytes(), original)
        self.assert_no_writer_lock()

    def test_real_query_run_with_busy_owner_reports_blocked_and_preserves_lock(self):
        request = self.request()
        request["attempt_id"] = "attempt-busy-owner"
        request_path = self.base / "owner-busy-request.json"
        result_path = self.base / "owner-busy-result.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        with storage.reserve(self.root, 1000):
            ledger = self.root / "models/.writer-reservation.json"
            original = ledger.read_bytes()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = protocol.run_request(request_path, result_path)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual((exit_code, result["status"]), (2, "blocked"))
            self.assertEqual(result["error"]["code"], "OWNER_BUSY")
            self.assertEqual(result["job_id"], request["job_id"])
            self.assertEqual(result["attempt_id"], "attempt-busy-owner")
            self.assertEqual(result["artifacts"], [])
            self.assertEqual(result["events"], [])
            self.assertEqual(ledger.read_bytes(), original)
            self.assertFalse((self.output / "query.json").exists())
            progress = [json.loads(line) for line in stdout.getvalue().splitlines()]
            self.assertEqual(progress[-1]["stage"], "blocked")
        self.assert_no_writer_lock()

    def test_reservation_released_after_body_error_and_quota_failure(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with storage.reserve(self.root, 1000):
                raise RuntimeError("synthetic failure")
        self.assert_no_writer_lock()
        with patch.object(storage, "tree_bytes", return_value=storage.LIMITS["models"]):
            with self.assertRaisesRegex(OSError, "quota"):
                with storage.reserve(self.root, 1000):
                    self.fail("over-budget writer must not start")
        self.assert_no_writer_lock()

    def test_low_disk_space_releases_reservation(self):
        with patch.object(storage.shutil, "disk_usage", return_value=types.SimpleNamespace(free=0)):
            with self.assertRaises(OSError):
                with storage.reserve(self.root, 1000):
                    self.fail("writer must not start on a full disk")
        self.assert_no_writer_lock()

    def test_decode_guards_reject_unbounded_windows_without_opening_media(self):
        av = types.ModuleType("av")
        av.open = Mock(side_effect=AssertionError("invalid parameters must not open media"))
        cases = [{"start_ms": -1}, {"end_ms": 30001}, {"start_ms": True},
                 {"end_ms": 0}, {"end_ms": 60001}, {"sample_fps": True}, {"sample_fps": 31},
                 {"sample_fps": float("nan")}, {"max_frames": 121}, {"max_frames": False},
                 {"sample_fps": 30, "max_frames": 1}]
        with patch.dict(sys.modules, {"av": av}):
            for params in cases:
                with self.subTest(params=params), self.assertRaises(ValueError):
                    inference.decode_samples(self.base / "not-a-video", {"duration_ms": 60000}, params)
        av.open.assert_not_called()

    def test_decoder_uses_source_pts_and_half_open_interval(self):
        stream = types.SimpleNamespace(start_time=100, time_base=Fraction(1, 1000))
        images = []
        def frame(pts):
            def image():
                images.append(pts)
                return types.SimpleNamespace(width=16, height=16)
            return types.SimpleNamespace(pts=pts, width=16, height=16, to_image=image)
        container = Mock()
        container.__enter__ = Mock(return_value=container)
        container.__exit__ = Mock(return_value=False)
        container.streams = types.SimpleNamespace(video=[stream])
        container.decode.return_value = iter([frame(100), frame(200), frame(500), frame(700), frame(1000)])
        av = types.ModuleType("av")
        av.open = Mock(return_value=container)
        with patch.dict(sys.modules, {"av": av}):
            frames, start, end = inference.decode_samples(self.base / "not-a-video", {"duration_ms": 1000},
                                                          {"start_ms": 100, "end_ms": 900, "sample_fps": 2, "max_frames": 2})
        self.assertEqual((start, end), (100, 900))
        self.assertEqual([frame[0] for frame in frames], [100, 600])
        self.assertEqual(images, [200, 700])
        container.seek.assert_called_once_with(200, stream=stream, backward=True)

    def test_decoder_stops_excessive_keyframe_preroll(self):
        av, to_image = self.fake_video(range(10001))
        with patch.dict(sys.modules, {"av": av}):
            with self.assertRaisesRegex(ValueError, "work bound"):
                inference.decode_samples(self.base / "not-a-video", {"duration_ms": 30000},
                                         {"start_ms": 20000, "end_ms": 21000, "sample_fps": 1, "max_frames": 1})
        to_image.assert_not_called()

    def test_decoder_stops_after_deadline(self):
        av, to_image = self.fake_video([0])
        with patch.dict(sys.modules, {"av": av}), patch.object(inference.time, "monotonic", side_effect=[0, 61]):
            with self.assertRaisesRegex(ValueError, "work bound"):
                inference.decode_samples(self.base / "not-a-video", {"duration_ms": 1000}, {})
        to_image.assert_not_called()

    def test_decoder_rejects_missing_duplicate_or_backward_pts(self):
        for timestamps in ([None], [0, 0], [2, 1], [-1]):
            av, _ = self.fake_video(timestamps)
            with self.subTest(pts=timestamps), patch.dict(sys.modules, {"av": av}):
                with self.assertRaises(ValueError):
                    inference.decode_samples(self.base / "not-a-video", {"duration_ms": 1000},
                                             {"sample_fps": 2, "max_frames": 2})

    def test_decoder_rejects_pixel_budget_before_image_conversion(self):
        av, to_image = self.fake_video([0], width=9000, height=9000)
        with patch.dict(sys.modules, {"av": av}):
            with self.assertRaisesRegex(ValueError, "pixel budget"):
                inference.decode_samples(self.base / "not-a-video", {"duration_ms": 1000}, {})
        to_image.assert_not_called()

    def test_decoder_bounds_total_retained_image_pixels(self):
        av, to_image = self.fake_video(range(0, 10000, 1000), width=3840, height=2160)
        with patch.dict(sys.modules, {"av": av}):
            with self.assertRaisesRegex(ValueError, "pixel budget"):
                inference.decode_samples(self.base / "not-a-video", {"duration_ms": 10000},
                                         {"sample_fps": 1, "max_frames": 10})
        self.assertEqual(to_image.call_count, 9)

    def test_decoder_does_not_burst_sample_after_variable_frame_rate_gap(self):
        av, _ = self.fake_video([0, 1000, 1001, 1002, 1003, 1250, 1500, 1750, 2000])
        with patch.dict(sys.modules, {"av": av}):
            frames, _, _ = inference.decode_samples(self.base / "not-a-video", {"duration_ms": 2000},
                                                    {"sample_fps": 4, "max_frames": 8})
        self.assertEqual([frame[0] for frame in frames], [0, 1000, 1250, 1500, 1750])

    def test_download_refuses_oversize_stream_before_publishing(self):
        target = self.root / "models/weights/mock.bin"
        with patch.object(download_weights.urllib.request, "urlopen", return_value=Response(b"12345")), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "byte limit"):
                download_weights.fetch("https://invalid.test/mock", target, 4)
        self.assertFalse(target.exists())
        self.assertLessEqual(target.with_name(target.name + ".partial").stat().st_size, 4)

    def test_download_uses_verified_range_resume_and_keeps_existing_file(self):
        target = self.root / "models/weights/mock.bin"
        target.parent.mkdir(parents=True)
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(b"abc")
        expected = hashlib.sha256(b"abcdef").hexdigest()
        self.partial_metadata(partial, 6, expected)
        response = Response(b"def", status=206, headers={"Content-Range": "bytes 3-5/6", "Content-Length": "3"})
        with patch.object(download_weights.urllib.request, "urlopen", return_value=response) as urlopen, redirect_stdout(io.StringIO()):
            result = download_weights.fetch("https://invalid.test/mock", target, 6, expected)
        self.assertEqual(urlopen.call_args.args[0].get_header("Range"), "bytes=3-")
        self.assertEqual(target.read_bytes(), b"abcdef")
        self.assertEqual(result["sha256"], expected)
        self.assertFalse(partial.exists())
        with patch.object(download_weights.urllib.request, "urlopen", side_effect=AssertionError("must reuse verified file")):
            download_weights.fetch("https://invalid.test/mock", target, 6, expected)
        self.assertEqual(target.read_bytes(), b"abcdef")

    def test_download_server_ignoring_range_preserves_partial(self):
        target = self.root / "models/weights/mock.bin"
        target.parent.mkdir(parents=True)
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(b"abc")
        self.partial_metadata(partial, 6)
        with patch.object(download_weights.urllib.request, "urlopen", return_value=Response(b"abcdef", status=200)), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "resume"):
                download_weights.fetch("https://invalid.test/mock", target, 6)
        self.assertEqual(partial.read_bytes(), b"abc")
        self.assertFalse(target.exists())

    def test_download_rejects_preexisting_size_mismatch(self):
        target = self.root / "models/weights/mock.bin"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"too large")
        with patch.object(download_weights.urllib.request, "urlopen", side_effect=AssertionError("must not download")):
            with self.assertRaises(ValueError):
                download_weights.fetch("https://invalid.test/mock", target, 4)
        self.assertEqual(target.read_bytes(), b"too large")

    def test_complete_verified_partial_publishes_without_network(self):
        target = self.root / "models/weights/mock.bin"
        target.parent.mkdir(parents=True)
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(b"abcdef")
        expected = hashlib.sha256(b"abcdef").hexdigest()
        self.partial_metadata(partial, 6, expected)
        with patch.object(download_weights.urllib.request, "urlopen", side_effect=AssertionError("completed partial must not request an invalid Range")), redirect_stdout(io.StringIO()):
            download_weights.fetch("https://invalid.test/mock", target, 6, expected)
        self.assertEqual(target.read_bytes(), b"abcdef")
        self.assertFalse(partial.exists())

    def test_changed_partial_revision_is_rejected_without_mutation(self):
        target = self.root / "models/weights/mock.bin"
        target.parent.mkdir(parents=True)
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(b"abc")
        self.partial_metadata(partial, 6, url="https://invalid.test/old-revision/mock")
        with patch.object(download_weights.urllib.request, "urlopen", side_effect=AssertionError("must not mix revisions")):
            with self.assertRaisesRegex(ValueError, "source identity"):
                download_weights.fetch("https://invalid.test/mock", target, 6)
        self.assertEqual(partial.read_bytes(), b"abc")
        self.assertFalse(target.exists())

    def test_zero_byte_partial_from_read_timeout_can_retry_same_source(self):
        target = self.root / "models/weights/mock.bin"
        partial = target.with_name(target.name + ".partial")
        metadata = partial.with_name(partial.name + ".source.json")
        expected = hashlib.sha256(b"abc").hexdigest()
        interrupted = Response(b"")
        interrupted.read = Mock(side_effect=TimeoutError("synthetic first-read timeout"))
        with patch.object(download_weights.urllib.request, "urlopen", return_value=interrupted), redirect_stdout(io.StringIO()):
            with self.assertRaises(TimeoutError):
                download_weights.fetch("https://invalid.test/mock", target, 3, expected)
        self.assertFalse(target.exists())
        self.assertEqual(partial.read_bytes(), b"")
        self.assertTrue(metadata.is_file())
        original_metadata = metadata.read_bytes()
        with patch.object(download_weights.urllib.request, "urlopen", return_value=Response(b"abc")) as urlopen, redirect_stdout(io.StringIO()):
            result = download_weights.fetch("https://invalid.test/mock", target, 3, expected)
        self.assertIsNone(urlopen.call_args.args[0].get_header("Range"))
        self.assertEqual(target.read_bytes(), b"abc")
        self.assertEqual(result["sha256"], expected)
        self.assertEqual(metadata.read_bytes(), original_metadata)
        self.assertFalse(partial.exists())
        self.assertEqual(list(target.parent.glob("mock.bin.partial.unverified-*")), [])

    def test_zero_byte_partial_without_source_is_retained_before_fresh_download(self):
        target = self.root / "models/weights/mock.bin"
        target.parent.mkdir(parents=True)
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(b"")
        expected = hashlib.sha256(b"abc").hexdigest()
        with patch.object(download_weights.urllib.request, "urlopen", return_value=Response(b"abc")), redirect_stdout(io.StringIO()):
            download_weights.fetch("https://invalid.test/mock", target, 3, expected)
        retained = list(target.parent.glob("mock.bin.partial.unverified-*"))
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), b"")
        self.assertEqual(target.read_bytes(), b"abc")
        self.assertFalse(partial.exists())

    def test_zero_byte_partial_with_different_source_is_preserved_and_rejected(self):
        target = self.root / "models/weights/mock.bin"
        target.parent.mkdir(parents=True)
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(b"")
        self.partial_metadata(partial, 3, url="https://invalid.test/old-revision/mock")
        metadata = partial.with_name(partial.name + ".source.json")
        original_metadata = metadata.read_bytes()
        with patch.object(download_weights.urllib.request, "urlopen", side_effect=AssertionError("different source must not be downloaded")):
            with self.assertRaisesRegex(ValueError, "source identity"):
                download_weights.fetch("https://invalid.test/mock", target, 3)
        self.assertEqual(partial.read_bytes(), b"")
        self.assertEqual(metadata.read_bytes(), original_metadata)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob("mock.bin.partial.unverified-*")), [])

    def test_download_truncated_body_and_hash_mismatch_never_publish(self):
        for name, content, expected_size, expected_hash in (
                ("short.bin", b"abc", 4, None),
                ("bad-hash.bin", b"abcd", 4, "0" * 64)):
            target = self.root / "models/weights" / name
            with self.subTest(name=name), patch.object(download_weights.urllib.request, "urlopen", return_value=Response(content)), redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError):
                    download_weights.fetch("https://invalid.test/mock", target, expected_size, expected_hash)
            self.assertFalse(target.exists())
            self.assertEqual(target.with_name(target.name + ".partial").read_bytes(), content)

    def test_reservation_and_partial_symlinks_cannot_write_outside_owner(self):
        outside = self.base / "outside"
        outside.mkdir()
        models = self.root / "models"
        try:
            models.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlink creation unavailable: {type(exc).__name__}")
        with self.assertRaises((InvalidRequest, ValueError, OSError)):
            with storage.reserve(self.root, 1000):
                self.fail("escaped reservation must be rejected")
        self.assertFalse((outside / ".writer-reservation.json").exists())
        models.unlink()
        models.mkdir()
        target = models / "mock.bin"
        victim = outside / "existing.bin"
        victim.write_bytes(b"abc")
        partial = target.with_name(target.name + ".partial")
        partial.symlink_to(victim)
        with patch.object(download_weights.urllib.request, "urlopen", return_value=Response(b"def", status=206, headers={"Content-Range": "bytes 3-5/6"})), redirect_stdout(io.StringIO()):
            with self.assertRaises((InvalidRequest, ValueError, OSError)):
                download_weights.fetch("https://invalid.test/mock", target, 6, hashlib.sha256(b"abcdef").hexdigest())
        self.assertEqual(victim.read_bytes(), b"abc")


if __name__ == "__main__":
    unittest.main()
