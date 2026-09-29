"""Exercise real engine backend selection without media processes or GPU work."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from packages.render.engine import RenderConfig, render
from packages.render.timeline import RenderError


class BackendSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run_count = 0

    def invoke(self, backend, probe_error=None, segment_error=None, fps=30, preview=False):
        self.run_count += 1
        job = f"backend-selection-{self.run_count}"
        request = {
            "schema_version": "1.0", "job_id": job, "attempt_id": "attempt-1",
            "operation": "render", "output_dir": f"render/jobs/{job}/attempt-1",
            "assets": [{
                "schema_version": "1.0", "asset_id": "source",
                "relative_path": "data/raw/fixture.mp4", "sha256": "a" * 64,
                "size_bytes": 100, "duration_ms": 2000, "width": 640, "height": 360,
                "fps_num": 25, "fps_den": 1, "source_type": "synthetic",
                "usage_scope": "general",
            }],
            "parameters": {
                "export_preset": f"portrait_1080p{fps}", "preview": preview,
                "timeline": {"schema_version": "1.0", "timeline_id": "backend-selection",
                    "segments": [{"segment_id": "segment-1", "asset_id": "source",
                        "in_ms": 0, "out_ms": 1000, "review_status": "confirmed"}]},
            },
        }
        config = RenderConfig(self.root, ffmpeg="mock-ffmpeg", ffprobe="mock-ffprobe",
                              backend=backend, runtime_db=self.root / "platform/runtime.sqlite3",
                              gpu_lease_id="test-lease")
        lease = {"lease_id": "test-lease", "window_id": "test-window",
                 "model_id": "render-nvenc", "worker_id": "test-worker"}
        probe = {"streams": [{"index": 0, "codec_type": "video", "width": 640,
                              "height": 360, "duration": "2.0", "time_base": "1/25000",
                              "sample_aspect_ratio": "1:1"}],
                 "format": {"duration": "2.0"}}
        calls, events = [], []

        def capture(arguments, timeout=30):
            if "-version" in arguments:
                return "ffmpeg mock version\n"
            self.assertIn("-filters", arguments)
            return " subtitles V->V\n atempo A->A\n bwdif V->V\n"

        def ffmpeg(arguments, stage, duration_ms, log_name):
            calls.append({"args": list(arguments), "stage": stage})
            if stage == "nvenc_probe":
                if probe_error is not None:
                    raise probe_error
                return
            if stage == "segment:1":
                raise segment_error or RenderError("test_stop", "Stop after inspecting first segment arguments")
            raise AssertionError(f"Unexpected media stage: {stage}")

        with ExitStack() as stack:
            verify_lease = stack.enter_context(patch("packages.render.engine.verify_gpu_lease", return_value=lease))
            stack.enter_context(patch("packages.render.engine.shutil.which", return_value="mock-executable"))
            stack.enter_context(patch("packages.render.engine.verify_source_bytes",
                return_value={"source": self.root / "data/raw/fixture.mp4"}))
            stack.enter_context(patch("packages.render.engine.Runner.capture", side_effect=capture))
            stack.enter_context(patch("packages.render.engine.Runner.probe", return_value=probe))
            stack.enter_context(patch("packages.render.engine.Runner.ffmpeg", side_effect=ffmpeg))
            stack.enter_context(patch("packages.render.storage.shutil.disk_usage",
                return_value=SimpleNamespace(free=1_000_000_000_000)))
            popen = stack.enter_context(patch("packages.render.engine.subprocess.Popen"))
            result = render(request, config, emit=events.append)

        popen.assert_not_called()
        verify_lease.assert_any_call(config.runtime_db, "test-lease", job, "attempt-1")
        self.assertEqual(result["artifacts"], [])
        self.assertFalse((self.root / "render/.render.lock").exists(), "Engine must release its reservation")
        output = self.root / request["output_dir"]
        metadata = json.loads((output / "backend.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["gpu_lease"], lease)
        self.assertFalse(list(output.glob("*.mov")))
        self.assertFalse(list(output.glob("*.mp4")))
        return result, metadata, calls, events

    @staticmethod
    def option(arguments, key):
        return arguments[arguments.index(key) + 1]

    def test_auto_probe_encode_failure_records_cpu_fallback_and_uses_libx264(self):
        reason = "NVENC initialization failed in test"
        result, metadata, calls, events = self.invoke("auto", RenderError("encode_failed", reason))
        self.assertEqual(result["error"]["code"], "test_stop")
        self.assertEqual(metadata["requested"], "auto")
        self.assertEqual(metadata["effective"], "cpu")
        self.assertEqual(metadata["encoder"], "libx264")
        self.assertIn(reason, metadata["fallback_reason"])
        self.assertEqual([call["stage"] for call in calls], ["nvenc_probe", "segment:1"])
        self.assertEqual(self.option(calls[1]["args"], "-c:v"), "libx264")
        self.assertNotIn("h264_nvenc", calls[1]["args"])
        self.assertTrue(any(event["stage"] == "backend" and reason in event["message"] for event in events))

    def test_explicit_nvenc_probe_encode_failure_is_blocked_without_segment(self):
        result, metadata, calls, _ = self.invoke("nvenc", RenderError("encode_failed", "device unavailable"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["error"]["code"], "backend_unavailable")
        self.assertEqual(metadata["requested"], "nvenc")
        self.assertEqual(metadata["effective"], "unavailable")
        self.assertIsNone(metadata["fallback_reason"])
        self.assertIn("device unavailable", metadata["unavailable_reason"])
        self.assertEqual([call["stage"] for call in calls], ["nvenc_probe"])

    def test_probe_uses_actual_output_dimensions_and_fps(self):
        for fps, preview, dimensions in ((30, False, "1080:1920"), (60, False, "1080:1920"),
                                          (60, True, "360:640")):
            with self.subTest(fps=fps, preview=preview):
                result, _, calls, _ = self.invoke("nvenc", fps=fps, preview=preview)
                self.assertEqual(result["error"]["code"], "test_stop")
                filters = self.option(calls[0]["args"], "-vf").split(",")
                self.assertIn("scale=" + dimensions, filters)
                self.assertIn(f"fps={fps}", filters)
                self.assertIn("format=yuv420p", filters)
                self.assertEqual(self.option(calls[0]["args"], "-c:v"), "h264_nvenc")
                self.assertEqual(self.option(calls[0]["args"], "-gpu"), "0")

    def test_cancel_and_lost_gpu_lease_never_trigger_cpu_fallback(self):
        for backend in ("auto", "nvenc"):
            for code, status in (("cancelled", "cancelled"), ("GPU_LEASE_REQUIRED", "blocked")):
                with self.subTest(backend=backend, code=code):
                    result, metadata, calls, events = self.invoke(backend, RenderError(code, "stop now", status))
                    self.assertEqual(result["status"], status)
                    self.assertEqual(result["error"]["code"], code)
                    self.assertEqual(metadata["effective"], "unavailable")
                    self.assertIsNone(metadata["fallback_reason"])
                    self.assertEqual([call["stage"] for call in calls], ["nvenc_probe"])
                    self.assertFalse(any(event["stage"] == "backend" for event in events))

    def test_segment_failure_after_successful_probe_fails_without_fallback(self):
        for backend in ("auto", "nvenc"):
            with self.subTest(backend=backend):
                result, metadata, calls, events = self.invoke(backend,
                    segment_error=RenderError("encode_failed", "real segment failed"))
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"]["code"], "encode_failed")
                self.assertEqual(metadata["requested"], backend)
                self.assertEqual(metadata["effective"], "nvenc")
                self.assertEqual(metadata["encoder"], "h264_nvenc")
                self.assertIsNone(metadata["fallback_reason"])
                self.assertEqual([call["stage"] for call in calls], ["nvenc_probe", "segment:1"])
                self.assertEqual(self.option(calls[1]["args"], "-c:v"), "h264_nvenc")
                self.assertFalse(any(event["stage"] == "backend" for event in events))


if __name__ == "__main__":
    unittest.main()
