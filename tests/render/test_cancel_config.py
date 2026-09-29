"""No-media tests for trusted worker and standalone cancellation paths."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.render.__main__ import resolve_cancel_file
from packages.render.engine import RenderConfig, Runner
from packages.render.timeline import RenderError


class CancelFileConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.request = {"job_id": "cancel-test-job", "attempt_id": "attempt-3"}
        self.expected = (self.root / "platform/jobs/cancel-test-job/attempt-3/cancel.request")

    def resolve(self, relative=None, environment_file=None):
        return resolve_cancel_file(self.root, relative, environment_file, self.request)

    def test_exact_absolute_worker_path_is_allowed_before_file_exists(self):
        self.assertEqual(self.resolve(environment_file=str(self.expected)), self.expected)
        self.assertFalse(self.expected.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_worker_path_must_match_job_attempt_and_filename(self):
        candidates = (
            self.root / "platform/jobs/another-job/attempt-3/cancel.request",
            self.root / "platform/jobs/cancel-test-job/attempt-2/cancel.request",
            self.expected.with_name("cancel.json"),
            self.root / "render/jobs/cancel-test-job/attempt-3/cancel.request",
        )
        for path in candidates:
            with self.subTest(path=path), self.assertRaises(RenderError):
                self.resolve(environment_file=str(path))

    def test_worker_path_outside_storage_root_is_rejected(self):
        outside = (self.root.parent / (self.root.name + "-outside") /
                   "platform/jobs/cancel-test-job/attempt-3/cancel.request")
        with self.assertRaises(RenderError):
            self.resolve(environment_file=str(outside))

    def test_worker_environment_path_must_be_absolute(self):
        with self.assertRaises(RenderError):
            self.resolve(environment_file="platform/jobs/cancel-test-job/attempt-3/cancel.request")

    def test_trusted_environment_takes_priority_over_cli_relative_path(self):
        for relative in ("render/handoff/standalone.cancel", "../invalid-cli-path"):
            with self.subTest(relative=relative):
                self.assertEqual(self.resolve(relative, str(self.expected)), self.expected)

    def test_invalid_environment_does_not_fall_back_to_valid_cli_path(self):
        with self.assertRaises(RenderError):
            self.resolve("render/handoff/standalone.cancel", str(self.expected.with_name("wrong")))

    def test_standalone_render_relative_path_remains_supported(self):
        relative = "render/handoff/standalone.cancel"
        for environment_file in (None, ""):
            with self.subTest(environment_file=environment_file):
                self.assertEqual(self.resolve(relative, environment_file), self.root / relative)

    def test_standalone_paths_cannot_escape_render_owner(self):
        for relative in ("platform/jobs/cancel-test-job/attempt-3/cancel.request",
                         "data/raw/source.cancel", "../outside.cancel",
                         "render/../platform/cancel.request"):
            with self.subTest(relative=relative), self.assertRaises(RenderError):
                self.resolve(relative)

    def test_no_cancel_configuration_returns_none(self):
        self.assertIsNone(self.resolve())
        self.assertIsNone(self.resolve("", ""))

    def test_worker_file_creation_cancels_runner_before_any_gpu_or_process_work(self):
        cancel_file = self.resolve(environment_file=str(self.expected))
        runner = Runner(RenderConfig(storage_root=self.root, cancel_file=cancel_file),
                        self.request["job_id"], lambda event: None, lambda: False,
                        attempt=self.request["attempt_id"])
        runner.check()
        cancel_file.parent.mkdir(parents=True)
        cancel_file.write_text("cancel requested\n", encoding="utf-8")
        runner.gpu_required = True
        with patch("packages.render.engine.verify_gpu_lease") as verify_lease, \
                patch("packages.render.engine.subprocess.Popen") as popen:
            with self.assertRaises(RenderError) as raised:
                runner.check()
        self.assertEqual(raised.exception.code, "cancelled")
        self.assertEqual(raised.exception.status, "cancelled")
        verify_lease.assert_not_called()
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
