"""Regressions for CPU null-output timestamp handling and strict failures."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from packages.library.probe import ProbeError, probe_video


class DecodeTimeBaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "input.mp4"
        self.source.write_bytes(b"mock subprocess input, not a media fixture")
        self.calls = []
        self.decode_stderr = ""
        self.decode_returncode = 0

    def run_tool(self, args, **kwargs):
        self.calls.append(args)
        if "-version" in args:
            return subprocess.CompletedProcess(args, 0, "fftool test version\n", "")
        if "-show_streams" in args:
            metadata = {"streams": [
                {"index": 0, "codec_type": "audio"},
                {"index": 1, "codec_type": "video", "disposition": {"attached_pic": 1}},
                {"index": 2, "codec_type": "video", "codec_name": "h264",
                 "width": 1920, "height": 1080, "duration": "4794.28",
                 "r_frame_rate": "25/1", "avg_frame_rate": "3000375/119857",
                 "time_base": "1/90000"},
            ]}
            return subprocess.CompletedProcess(args, 0, json.dumps(metadata), "")
        return subprocess.CompletedProcess(args, self.decode_returncode,
                                           "frame=120015\nprogress=end\n", self.decode_stderr)

    def test_output_timebase_preserves_fine_source_ticks_for_selected_video(self):
        with patch("packages.library.probe.subprocess.run", side_effect=self.run_tool):
            result = probe_video(self.source)
        decode = self.calls[-1]
        self.assertEqual("0:2", decode[decode.index("-map") + 1])
        self.assertEqual("demux", decode[decode.index("-enc_time_base:v") + 1])
        self.assertGreater(decode.index("-enc_time_base:v"), decode.index("-i") + 1)
        self.assertEqual("passthrough", decode[decode.index("-fps_mode") + 1])
        self.assertEqual("none", decode[decode.index("-hwaccel") + 1])
        self.assertTrue(all(decode[i + 1] == "1" for i, arg in enumerate(decode) if arg == "-threads"))
        self.assertIn("-xerror", decode)
        self.assertNotIn("-r", decode)
        self.assertNotIn("-vf", decode)
        self.assertEqual("1/90000", result["time_base"])
        self.assertEqual((3000375, 119857), (result["fps_num"], result["fps_den"]))
        self.assertEqual("unknown", result["probe"]["vfr_status"])
        self.assertEqual(120015, result["probe"]["decode"]["frames"])

    def test_remaining_decode_errors_are_not_filtered_or_published(self):
        target = Path(self.temp.name) / "pts.jsonl"
        for error in ("damaged macroblock", "non monotonically increasing dts to muxer: 1 >= 1"):
            with self.subTest(error=error):
                self.decode_stderr = error
                with patch("packages.library.probe.subprocess.run", side_effect=self.run_tool), \
                     patch("packages.library.probe._pts_index") as pts, \
                     self.assertRaisesRegex(ProbeError, "CPU decode reported errors") as raised:
                    probe_video(self.source, pts_index_path=target, storage_root=self.temp.name)
                self.assertIn(error, str(raised.exception))
                pts.assert_not_called()
                self.assertFalse(target.exists())

    def test_unsupported_encoder_timebase_fails_closed_without_retry(self):
        self.decode_stderr = "Invalid time base: demux"
        self.decode_returncode = 1
        with patch("packages.library.probe.subprocess.run", side_effect=self.run_tool), \
             self.assertRaisesRegex(ProbeError, "exited 1"):
            probe_video(self.source)
        self.assertEqual(1, sum("-progress" in args for args in self.calls))


if __name__ == "__main__":
    unittest.main()
