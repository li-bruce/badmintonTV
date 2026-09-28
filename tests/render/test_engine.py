"""No-media safety tests for request preflight and exclusive storage reservation."""
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from packages.render.engine import RenderConfig, Runner, render
from packages.render.storage import reservation
from packages.render.timeline import RenderError


def request_fixture():
    return {
        "schema_version": "1.0", "job_id": "test-job", "attempt_id": "attempt-01",
        "operation": "render", "output_dir": "render/jobs/test-job/attempt-01",
        "assets": [{
            "schema_version": "1.0", "asset_id": "test-asset",
            "relative_path": "data/raw/fixture.mp4", "sha256": "a" * 64,
            "size_bytes": 100, "duration_ms": 2000, "width": 640, "height": 360,
            "fps_num": 25, "fps_den": 1, "source_type": "synthetic",
        }],
        "parameters": {"timeline": {
            "schema_version": "1.0", "timeline_id": "test-timeline",
            "segments": [{
                "segment_id": "test-segment", "asset_id": "test-asset",
                "in_ms": 0, "out_ms": 1000, "review_status": "confirmed",
            }],
        }},
    }


class EnginePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = RenderConfig(
            storage_root=self.root,
            ffmpeg=str(self.root / "not-installed-ffmpeg.exe"),
            ffprobe=str(self.root / "not-installed-ffprobe.exe"),
        )

    def rejected(self, request, code="invalid_request", status="failed"):
        events = []
        with patch("packages.render.engine.subprocess.Popen") as popen:
            result = render(request, self.config, emit=events.append)
        popen.assert_not_called()
        self.assertEqual(result["status"], status)
        self.assertEqual(result["error"]["code"], code)
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(events[-1]["event"], "error")
        self.assertEqual(events[-1]["message"], result["error"]["message"])
        return result

    def test_invalid_top_level_requests_fail_without_starting_processes(self):
        for request in (None, [], "request.json", {}, {"schema_version": "2.0"}):
            with self.subTest(request=request):
                self.rejected(request)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_operation_job_and_parameters_are_rejected(self):
        for key, value in (("operation", "analyze"), ("job_id", ""),
                           ("job_id", True), ("parameters", [])):
            with self.subTest(key=key, value=value):
                request = request_fixture()
                request[key] = value
                self.rejected(request)

    def test_assets_must_be_only_the_top_level_array(self):
        original = request_fixture()
        for malformed in (
            {**original, "assets": {"test-asset": original["assets"][0]}},
            {**original, "assets": []},
            {**original, "parameters": {**original["parameters"], "assets": original["assets"]}},
        ):
            with self.subTest(request=malformed):
                self.rejected(malformed)

    def test_empty_segments_are_rejected_before_environment_checks(self):
        request = request_fixture()
        request["parameters"]["timeline"]["segments"] = []
        self.rejected(request)
        self.assertFalse((self.root / "render").exists())

    def test_editorial_flags_must_be_actual_booleans(self):
        for flag in ("preview", "merge_overlaps", "deduplicate_replays"):
            for value in (1, "false", None):
                with self.subTest(flag=flag, value=value):
                    request = request_fixture()
                    request["parameters"][flag] = value
                    self.rejected(request)

    def test_attempt_id_is_required_validated_and_retained_on_failure(self):
        for value in (None, "", True, "x" * 201, "attempt\x00invalid"):
            with self.subTest(value=value):
                request = request_fixture()
                request["attempt_id"] = value
                self.rejected(request)
        request = request_fixture()
        del request["attempt_id"]
        self.rejected(request)
        valid = request_fixture()
        result = self.rejected(valid, "not_installed", "blocked")
        self.assertEqual(result["attempt_id"], "attempt-01")
        self.assertEqual(result["job_id"], "test-job")

    def test_missing_ffmpeg_is_blocked_and_does_not_create_output(self):
        self.rejected(request_fixture(), "not_installed", "blocked")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_ffprobe_is_also_blocked_before_launch(self):
        with patch("packages.render.engine.shutil.which", side_effect=["available-ffmpeg", None]):
            self.rejected(request_fixture(), "not_installed", "blocked")

    def test_output_must_be_strictly_below_render_owner(self):
        for output in ("render", "data/jobs/test-job", "../render/job", "render/../../outside",
                       "/render/job", "D:/video/render/job", "render\\job", "render//job"):
            with self.subTest(output=output):
                request = request_fixture()
                request["output_dir"] = output
                self.rejected(request, "unsafe_path")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_output_directory_is_preserved_byte_for_byte(self):
        request = request_fixture()
        output = self.root / request["output_dir"]
        output.mkdir(parents=True)
        existing = output / "export.mp4"
        existing.write_bytes(b"existing output; never overwrite")
        self.rejected(request, "output_exists")
        self.assertEqual(existing.read_bytes(), b"existing output; never overwrite")
        self.assertEqual(list(output.iterdir()), [existing])

    def test_existing_output_file_is_preserved(self):
        request = request_fixture()
        output = self.root / request["output_dir"]
        output.parent.mkdir(parents=True)
        output.write_bytes(b"existing file")
        self.rejected(request, "output_exists")
        self.assertEqual(output.read_bytes(), b"existing file")

    def test_validation_does_not_mutate_request(self):
        request = request_fixture()
        before = deepcopy(request)
        self.rejected(request, "not_installed", "blocked")
        self.assertEqual(request, before)


class RunnerProgressTests(unittest.TestCase):
    def test_fractional_duration_clamps_after_rounding_real_progress_event(self):
        duration_ms = 7166.666667
        events = []
        with tempfile.TemporaryDirectory() as directory:
            config = RenderConfig(storage_root=Path(directory))
            runner = Runner(config, "fractional-speed-job", events.append, lambda: False)
            runner.output = Path(directory)
            runner.peak = None
            with patch("packages.render.engine.subprocess.Popen") as popen:
                process = popen.return_value
                process.stdout = StringIO("out_time_us=7166667\n")
                process.returncode = 0
                process.wait.return_value = 0
                process.poll.return_value = 0
                runner.ffmpeg([], "segment:1", duration_ms, "progress.log")
        self.assertEqual(len(events), 2, "Expected parsed FFmpeg progress followed by completion")
        for event in events:
            self.assertEqual(event["event"], "progress")
            self.assertEqual(event["total"], duration_ms)
            self.assertLessEqual(event["current"], event["total"])
        self.assertEqual(events[-1]["current"], duration_ms)


class StorageReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = self.root / "render"
        self.lock = self.owner / ".render.lock"
        disk = patch("packages.render.storage.shutil.disk_usage",
                     return_value=SimpleNamespace(free=1_000_000_000_000))
        self.disk_usage = disk.start()
        self.addCleanup(disk.stop)

    def test_lock_is_exclusive_and_second_job_cannot_remove_first_lock(self):
        with reservation(self.root, "first-job", 1024) as ledger:
            before = self.lock.read_bytes()
            self.assertEqual(ledger["job_id"], "first-job")
            self.assertEqual(ledger["reserved_bytes"], 1024)
            self.assertEqual(json.loads(before), ledger)
            with self.assertRaises(RenderError) as raised:
                with reservation(self.root, "second-job", 1024):
                    self.fail("A second writer acquired the owner lock")
            self.assertEqual(raised.exception.code, "render_busy")
            self.assertEqual(raised.exception.status, "blocked")
            self.assertEqual(self.lock.read_bytes(), before)
        self.assertFalse(self.lock.exists())

    def test_preexisting_stale_lock_is_not_deleted_or_replaced(self):
        self.owner.mkdir()
        self.lock.write_bytes(b"administrator must inspect this stale lock")
        with self.assertRaises(RenderError) as raised:
            with reservation(self.root, "new-job", 1024):
                self.fail("An uninspected lock was replaced")
        self.assertEqual(raised.exception.code, "render_busy")
        self.assertEqual(self.lock.read_bytes(), b"administrator must inspect this stale lock")

    def test_owned_lock_releases_after_caller_exception_without_removing_files(self):
        with self.assertRaisesRegex(RuntimeError, "deliberate failure"):
            with reservation(self.root, "failing-job", 1024):
                (self.owner / "partial.txt").write_text("keep diagnosis", encoding="utf-8")
                raise RuntimeError("deliberate failure")
        self.assertFalse(self.lock.exists())
        self.assertEqual((self.owner / "partial.txt").read_text(encoding="utf-8"), "keep diagnosis")

    def test_owner_quota_includes_existing_files_and_releases_failed_lock(self):
        self.owner.mkdir()
        original = self.owner / "existing.bin"
        original.write_bytes(b"x" * 32)
        with self.assertRaises(RenderError) as raised:
            with reservation(self.root, "too-large", 2, owner_limit=33):
                self.fail("Existing bytes were not included in quota")
        self.assertEqual(raised.exception.code, "quota_exceeded")
        self.assertFalse(self.lock.exists())
        self.assertEqual(original.stat().st_size, 32)

    def test_global_quota_applies_even_with_room_in_render_owner(self):
        with patch("packages.render.storage.directory_bytes", side_effect=[0, 699_999_999_999]):
            with self.assertRaises(RenderError) as raised:
                with reservation(self.root, "global-full", 2):
                    self.fail("Global quota did not prevent a reservation")
        self.assertEqual(raised.exception.code, "quota_exceeded")
        self.assertFalse(self.lock.exists())

    def test_physical_free_space_includes_the_required_safety_margin(self):
        self.disk_usage.return_value = SimpleNamespace(free=256_000_100)
        with self.assertRaises(RenderError) as raised:
            with reservation(self.root, "disk-full", 101):
                self.fail("Physical free space safety margin was ignored")
        self.assertEqual(raised.exception.code, "disk_full")
        self.assertFalse(self.lock.exists())


if __name__ == "__main__":
    unittest.main()
