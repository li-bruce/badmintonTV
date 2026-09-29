"""R-01a configuration assertions; these do not replace real-video acceptance."""
from copy import deepcopy
import unittest

from packages.render.presets import resolve_preset, validate_duration
from packages.render.timeline import RenderError


class ExportPresetTests(unittest.TestCase):
    def test_default_is_full_hd_portrait_30fps_h264_aac(self):
        result = resolve_preset({})
        self.assertEqual(result["output"], {
            "width": 1080, "height": 1920, "fps": 30,
            "video_codec": "h264", "audio_codec": "aac",
        })
        self.assertEqual(result["export_preset"], "portrait_1080p30")
        self.assertFalse(result["preset_explicit"])
        self.assertEqual((result["maxrate"], result["bufsize"]), ("8M", "16M"))
        self.assertFalse(result["burn_in_guides"])
        self.assertIsNone(result["platform_profile"])
        self.assertIsNone(result["max_duration_ms"])

    def test_named_presets_match_requested_frame_rate_and_encoding_budget(self):
        for fps, rate, buffer in ((30, "8M", "16M"), (60, "12M", "24M")):
            with self.subTest(fps=fps):
                result = resolve_preset({"export_preset": f"portrait_1080p{fps}"})
                self.assertEqual(result["output"]["fps"], fps)
                self.assertTrue(result["preset_explicit"])
                self.assertEqual((result["maxrate"], result["bufsize"]), (rate, buffer))
                self.assertEqual(result["video_bitrate_bps"], int(rate[:-1]) * 1_000_000)

    def test_explicit_compatible_output_is_accepted_and_normalized(self):
        result = resolve_preset({"export_preset": "portrait_1080p60"}, {
            "width": 1080, "height": 1920, "fps": 60.0,
            "video_codec": "h264", "audio_codec": "aac",
        })
        self.assertEqual(result["output"]["fps"], 60)
        self.assertIs(type(result["output"]["fps"]), int)

    def test_each_explicit_conflicting_output_field_is_rejected(self):
        for key, value in (("width", 1920), ("height", 1080), ("fps", 30),
                           ("video_codec", "hevc"), ("audio_codec", "opus")):
            with self.subTest(field=key):
                with self.assertRaises(RenderError) as raised:
                    resolve_preset({"export_preset": "portrait_1080p60"}, {key: value})
                self.assertEqual(raised.exception.code, "preset_conflict")
                self.assertIn(key, str(raised.exception))

    def test_without_named_preset_preserves_all_preexisting_supported_fps(self):
        for fps in (24, 25, 30, 50, 60):
            with self.subTest(fps=fps):
                result = resolve_preset({}, {"fps": float(fps)})
                self.assertEqual(result["output"]["fps"], fps)
                self.assertIs(type(result["output"]["fps"]), int)
                self.assertFalse(result["preset_explicit"])
                self.assertEqual(result["maxrate"], "12M" if fps >= 50 else "8M")
                if fps not in (30, 60):
                    self.assertIsNone(result["export_preset"])

    def test_unknown_or_malformed_preset_parameters_are_rejected(self):
        for value in (None, [], "portrait_1080p30", 1):
            with self.subTest(parameters=value):
                with self.assertRaises(RenderError):
                    resolve_preset(value)
        for value in (None, "", "portrait_720p30", True, {}, []):
            with self.subTest(preset=value):
                with self.assertRaises(RenderError):
                    resolve_preset({"export_preset": value})

    def test_bad_output_types_dimensions_codecs_and_fps_are_rejected(self):
        for value in ([], "output", True):
            with self.subTest(output=value):
                with self.assertRaises(RenderError):
                    resolve_preset({}, value)
        for output in ({"width": 720}, {"height": 1280}, {"fps": True}, {"fps": "30"},
                       {"fps": 29.97}, {"fps": float("nan")}, {"fps": float("inf")},
                       {"video_codec": "hevc"}, {"audio_codec": "opus"}, {"frame_rate": 60}):
            with self.subTest(output=output):
                with self.assertRaises(RenderError):
                    resolve_preset({}, output)

    def test_safe_area_is_editable_normalized_metadata_without_baked_guides(self):
        rect = {"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.6}
        result = resolve_preset({"safe_area": rect})
        self.assertEqual(result["safe_area"], rect)
        self.assertFalse(result["burn_in_guides"])
        self.assertEqual(result["output"]["width"], 1080)
        self.assertEqual(result["output"]["height"], 1920)

    def test_safe_area_rejects_missing_extra_and_outside_coordinates(self):
        rect = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
        invalid = [None, [], {}, {**rect, "units": "pixels"},
                   {**rect, "width": 0}, {**rect, "height": -1},
                   {**rect, "x": 0.1}, {**rect, "y": 0.1}]
        for key in rect:
            invalid.extend({**rect, key: value} for value in
                           (True, "0.2", float("nan"), float("inf"), -0.01, 1.01))
        for value in invalid:
            with self.subTest(rect=value):
                with self.assertRaises(RenderError):
                    resolve_preset({"safe_area": value})

    def test_input_and_returned_nested_objects_are_independent(self):
        params = {"safe_area": {"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.6},
                  "timeline": {"unrelated": "preserved"}}
        output = {"fps": 30.0}
        before_params, before_output = deepcopy(params), deepcopy(output)
        result = resolve_preset(params, output)
        result["safe_area"]["x"] = 0
        result["output"]["fps"] = 60
        self.assertEqual(params, before_params)
        self.assertEqual(output, before_output)
        default = resolve_preset({})
        default["safe_area"]["width"] = 0
        self.assertGreater(resolve_preset({})["safe_area"]["width"], 0)


class PlatformDurationTests(unittest.TestCase):
    def test_shorts_profile_is_opt_in_and_has_180_second_limit(self):
        result = resolve_preset({"platform_profile": "youtube_shorts"})
        self.assertEqual(result["platform_profile"], "youtube_shorts")
        self.assertEqual(result["max_duration_ms"], 180_000)
        self.assertIsNone(validate_duration(180_000, "youtube_shorts"))
        self.assertIsNone(validate_duration(0, "youtube_shorts"))
        with self.assertRaises(RenderError) as raised:
            validate_duration(180_000.000001, "youtube_shorts")
        self.assertEqual(raised.exception.code, "platform_duration_exceeded")

    def test_general_exports_do_not_inherit_shorts_duration_limit(self):
        self.assertIsNone(validate_duration(180_001))
        self.assertIsNone(validate_duration(7_200_000, None))
        self.assertIsNone(resolve_preset({"platform_profile": None})["max_duration_ms"])

    def test_duration_must_be_finite_nonnegative_numeric_not_boolean(self):
        for value in (-1, float("nan"), float("inf"), -float("inf"), True, "180000", None):
            with self.subTest(duration=value):
                with self.assertRaises(RenderError):
                    validate_duration(value)

    def test_unknown_profile_is_rejected_by_both_entrypoints(self):
        for profile in ("", "youtube", "unknown", True, [], {}):
            with self.subTest(profile=profile):
                with self.assertRaises(RenderError):
                    resolve_preset({"platform_profile": profile})
                with self.assertRaises(RenderError):
                    validate_duration(1_000, profile)


if __name__ == "__main__":
    unittest.main()
