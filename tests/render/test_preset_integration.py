"""R-01a preset entrypoint regressions; all media processes are mocked.

These assertions cover configuration, timing gates, ASS layout and GPU-lease
ordering. They do not replace the separate real-video benchmark or viewing QA.
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.render.engine import RenderConfig, render, write_ass
from packages.render.presets import resolve_preset, validate_duration
from packages.render.timeline import RenderError, assets_by_id, export_timeline, normalize_timeline


def request_fixture(fps=60, out_ms=90_000, speed=0.5):
    return {
        "schema_version": "1.0", "job_id": "preset-integration", "attempt_id": "attempt-1",
        "operation": "render", "output_dir": "render/jobs/preset-integration/attempt-1",
        "assets": [{
            "schema_version": "1.0", "asset_id": "source", "relative_path": "data/raw/mock.mp4",
            "sha256": "a" * 64, "size_bytes": 100, "duration_ms": 200_000,
            "width": 1280, "height": 720, "fps_num": 30, "fps_den": 1,
            "source_type": "synthetic", "usage_scope": "general",
        }],
        "parameters": {
            "export_preset": f"portrait_1080p{fps}", "platform_profile": "youtube_shorts",
            "timeline": {
                "schema_version": "1.0", "timeline_id": "preset-integration-timeline",
                "title": "Layout fixture", "segments": [{
                    "segment_id": "segment-1", "asset_id": "source", "in_ms": 0,
                    "out_ms": out_ms, "speed": speed, "review_status": "confirmed",
                    "title": "Title", "subtitles": [{"start_ms": 0, "end_ms": 10, "text": "Subtitle"}],
                }],
            },
        },
    }


class PresetEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def invoke(self, request, backend="cpu"):
        """Run real preset/timeline/duration checks, then stop before FFmpeg."""
        normalized = []
        def observe_normalize(*args, **kwargs):
            value = normalize_timeline(*args, **kwargs)
            normalized.append(value)
            return value
        config = RenderConfig(storage_root=self.root, ffmpeg="mock-ffmpeg", ffprobe="mock-ffprobe",
                              backend=backend, runtime_db=None, gpu_lease_id=None)
        with ExitStack() as stack:
            mocks = {
                "usage": stack.enter_context(patch("packages.render.engine.check_usage")),
                "sources": stack.enter_context(patch("packages.render.engine.verify_source_bytes",
                    return_value={"source": self.root / "data/raw/mock.mp4"})),
                "which": stack.enter_context(patch("packages.render.engine.shutil.which", return_value="mock-executable")),
                "normalize": stack.enter_context(patch("packages.render.engine.normalize_timeline", side_effect=observe_normalize)),
                "duration": stack.enter_context(patch("packages.render.engine.validate_duration", wraps=validate_duration)),
                "capture": stack.enter_context(patch("packages.render.engine.Runner.capture",
                    side_effect=RenderError("test_stop_after_duration", "Deliberate test stop before any media subprocess"))),
                "reservation": stack.enter_context(patch("packages.render.engine.reservation")),
                "popen": stack.enter_context(patch("packages.render.engine.subprocess.Popen")),
            }
            result = render(request, config)
        mocks["popen"].assert_not_called()
        mocks["reservation"].assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [], "Preflight tests must not create job output")
        return result, mocks, normalized

    def assert_duration_accepted(self, request, expected_ms):
        result, mocks, normalized = self.invoke(request)
        self.assertEqual(result["error"]["code"], "test_stop_after_duration")
        mocks["capture"].assert_called_once()
        mocks["duration"].assert_called_once_with(expected_ms, "youtube_shorts")
        return normalized[0]

    def test_slowed_output_exactly_180_seconds_is_allowed_for_both_presets(self):
        for fps in (30, 60):
            with self.subTest(fps=fps):
                request = request_fixture(fps=fps, out_ms=90_000, speed=0.5)
                before = deepcopy(request)
                timeline = self.assert_duration_accepted(request, 180_000.0)
                self.assertEqual(sum(s["output_frames"] for s in timeline["segments"]), fps * 180)
                self.assertEqual(request, before)

    def test_duration_gate_uses_quantized_output_instead_of_unrounded_slowdown(self):
        # 90.001s at half speed is nominally 180.002s. Both presets round it to
        # exactly 180s, so a check against raw source/speed would wrongly reject.
        for fps in (30, 60):
            with self.subTest(fps=fps):
                self.assert_duration_accepted(request_fixture(fps=fps, out_ms=90_001), 180_000.0)

    def test_duration_comes_from_total_frames_not_sum_of_rounded_segment_ms(self):
        request = request_fixture(fps=60)
        prototype = request["parameters"]["timeline"]["segments"][0]
        request["parameters"]["timeline"]["segments"] = [
            {**deepcopy(prototype), "segment_id": f"segment-{i}", "out_ms": end}
            for i, end in enumerate((8, 8, 89_983), 1)
        ]
        timeline = self.assert_duration_accepted(request, 180_000.0)
        self.assertEqual([s["output_frames"] for s in timeline["segments"]], [1, 1, 10_798])
        self.assertGreater(sum(s["output_duration_ms"] for s in timeline["segments"]), 180_000)

    def test_slowed_output_above_180_seconds_is_rejected_before_media_or_reservation(self):
        for fps in (30, 60):
            with self.subTest(fps=fps):
                result, mocks, _ = self.invoke(request_fixture(fps=fps, out_ms=90_009))
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"]["code"], "platform_duration_exceeded")
                self.assertEqual(result["artifacts"], [])
                self.assertGreater(mocks["duration"].call_args.args[0], 180_000)
                mocks["capture"].assert_not_called()

    def test_preview_60fps_keeps_canonical_1080p_and_uses_effective_360p(self):
        request = request_fixture(fps=60, out_ms=1000, speed=1)
        request["parameters"]["preview"] = True
        timeline = self.assert_duration_accepted(request, 1000.0)
        self.assertEqual(timeline["output"], {
            "width": 1080, "height": 1920, "fps": 60, "video_codec": "h264", "audio_codec": "aac",
        })
        effective = timeline["render_metadata"]["effective_output"]
        self.assertEqual((effective["width"], effective["height"], effective["fps"]), (360, 640, 60))
        self.assertEqual(export_timeline(timeline)["output"], timeline["output"])
        self.assertEqual(timeline["segments"][0]["output_frames"], 60)

    def test_explicit_preset_conflict_stops_before_source_reads_or_media(self):
        request = request_fixture(fps=60)
        request["parameters"]["timeline"]["output"] = {"fps": 30}
        result, mocks, normalized = self.invoke(request)
        self.assertEqual(result["error"]["code"], "preset_conflict")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(normalized, [])
        mocks["sources"].assert_not_called()
        mocks["duration"].assert_not_called()
        mocks["capture"].assert_not_called()

    def test_nvenc_and_auto_without_lease_are_blocked_before_any_media_work(self):
        for backend in ("nvenc", "auto"):
            with self.subTest(backend=backend):
                result, mocks, normalized = self.invoke(request_fixture(), backend)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["error"]["code"], "GPU_LEASE_REQUIRED")
                self.assertEqual(result["artifacts"], [])
                self.assertEqual(normalized, [])
                mocks["sources"].assert_not_called()
                mocks["which"].assert_not_called()
                mocks["capture"].assert_not_called()


class SafeAreaAssIntegrationTests(unittest.TestCase):
    @staticmethod
    def styles(document):
        section = document.split("[V4+ Styles]", 1)[1].split("[Events]", 1)[0]
        columns = next(line.removeprefix("Format: ").split(", ") for line in section.splitlines() if line.startswith("Format: "))
        rows = [dict(zip(columns, line.removeprefix("Style: ").split(",")))
                for line in section.splitlines() if line.startswith("Style: ")]
        return {row["Name"]: row for row in rows}

    def test_safe_area_changes_ass_text_margins_without_drawing_guides(self):
        request = request_fixture(out_ms=1000, speed=1)
        assets = assets_by_id(request["assets"])
        documents = []
        with tempfile.TemporaryDirectory() as directory:
            for index, area in enumerate((None, {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5})):
                params = deepcopy(request["parameters"])
                if area is not None:
                    params["safe_area"] = area
                preset = resolve_preset(params)
                source_timeline = deepcopy(params["timeline"])
                source_timeline["output"] = preset["output"]
                timeline = normalize_timeline(source_timeline, assets)
                timeline["render_metadata"]["preset"] = preset
                path = Path(directory) / f"layout-{index}.ass"
                write_ass(path, timeline, timeline["segments"][0], 0, 1, "Test Font")
                document = path.read_text(encoding="utf-8")
                documents.append(document)
                self.assertFalse(preset["burn_in_guides"])
                self.assertNotIn("drawbox", document)
                self.assertNotIn("\\p1", document, "ASS vector drawing must not render safe-area guides")
                self.assertEqual(timeline["segments"][0]["fit"], "contain")
                self.assertNotIn("crop", timeline["segments"][0])
        normal, inset = map(self.styles, documents)
        for name in ("Title", "Subtitle", "Info"):
            self.assertEqual((int(inset[name]["MarginL"]), int(inset[name]["MarginR"])), (270, 270))
            self.assertGreaterEqual(int(inset[name]["MarginV"]), 480)
            self.assertGreater(int(inset[name]["MarginL"]), int(normal[name]["MarginL"]))
            self.assertGreater(int(inset[name]["MarginR"]), int(normal[name]["MarginR"]))
            self.assertGreater(int(inset[name]["MarginV"]), int(normal[name]["MarginV"]))


if __name__ == "__main__":
    unittest.main()
