"""R-03a backend safety and MP4 box checks; never starts a GPU or media process."""
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

from packages.render.backends import encoder_args, mp4_faststart, verify_gpu_lease
from packages.render.timeline import RenderError
from packages.runtime.gpu import GPUCoordinator
from packages.runtime.queue import Queue


class GPULeaseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "test-runtime.sqlite3"
        self.now = time.time()
        self.queue = Queue(self.db_path)
        self.gpu = GPUCoordinator(self.db_path, clock=lambda: self.now)
        process_guard = patch("packages.runtime.gpu.subprocess.run",
                              side_effect=AssertionError("Unit tests must not start GPU processes"))
        process_guard.start()
        self.addCleanup(process_guard.stop)

    def active_lease(self, model="render-nvenc"):
        self.gpu.grant_window("unit-test-window", [model], 120,
                              granted_by="unit-test", coordination_note="Temporary database only; no real GPU grant")
        queued = self.queue.enqueue("render", {"model_id": model})
        job = self.queue.claim("unit-test-worker", lease_seconds=600)
        self.assertEqual(job["job_id"], queued["job_id"])
        lease = self.gpu.claim(model, job["job_id"], job["attempt"], job["worker_id"], lease_seconds=30)
        return job, lease

    def snapshot(self):
        # Coordinator.get/status can expire records; read SQL directly so this
        # test can prove verification itself never changes scheduler state.
        with self.queue.connection() as db:
            return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                    for table in ("jobs", "job_logs", "gpu_windows", "gpu_window_revocations", "resource_leases")}

    def blocked(self, lease_id, job_id, attempt_id, now=None):
        before = self.snapshot()
        with patch("packages.render.backends.time.time", return_value=self.now if now is None else now):
            with self.assertRaises(RenderError) as raised:
                verify_gpu_lease(self.db_path, lease_id, job_id, attempt_id)
        self.assertEqual(raised.exception.code, "GPU_LEASE_REQUIRED")
        self.assertEqual(raised.exception.status, "blocked")
        self.assertEqual(self.snapshot(), before)

    def test_empty_scheduler_does_not_authorize_or_create_a_lease(self):
        self.blocked("absent-lease", "absent-job", "attempt-1")
        self.assertEqual(self.snapshot()["resource_leases"], [])

    def test_window_without_a_worker_claim_is_insufficient(self):
        self.gpu.grant_window("unit-test-window", ["render-nvenc"], 120,
                              coordination_note="Temporary scheduler fixture only")
        self.blocked("absent-lease", "absent-job", "attempt-1")

    def test_matching_running_attempt_returns_lease_identity_without_writing(self):
        job, lease = self.active_lease()
        before = self.snapshot()
        with patch("packages.render.backends.time.time", return_value=self.now):
            result = verify_gpu_lease(self.db_path, lease["lease_id"], job["job_id"], "attempt-1")
        self.assertEqual(result, {key: lease[key] for key in ("lease_id", "window_id", "model_id", "worker_id")})
        self.assertEqual(self.snapshot(), before)

    def test_wrong_requested_job_or_attempt_is_blocked(self):
        job, lease = self.active_lease()
        self.blocked(lease["lease_id"], "some-other-job", "attempt-1")
        for attempt in ("attempt-2", "attempt-01", "1", None):
            with self.subTest(attempt=attempt):
                self.blocked(lease["lease_id"], job["job_id"], attempt)

    def test_a_real_lease_for_another_model_cannot_authorize_nvenc(self):
        job, lease = self.active_lease(model="another-approved-model")
        self.blocked(lease["lease_id"], job["job_id"], "attempt-1")

    def test_changed_worker_attempt_status_or_resource_is_blocked(self):
        job, lease = self.active_lease()
        mutations = (
            ("jobs", "worker_id", "another-worker", job["worker_id"]),
            ("jobs", "attempt", 2, 1),
            ("jobs", "status", "queued", "running"),
            ("resource_leases", "resource", "gpu1", "gpu0"),
        )
        for table, column, changed, original in mutations:
            with self.subTest(table=table, column=column):
                with self.queue.connection(write=True) as db:
                    db.execute(f"UPDATE {table} SET {column}=?", (changed,))
                self.blocked(lease["lease_id"], job["job_id"], "attempt-1")
                with self.queue.connection(write=True) as db:
                    db.execute(f"UPDATE {table} SET {column}=?", (original,))

    def test_gpu_lease_expiration_is_rejected_without_marking_it_orphaned(self):
        job, lease = self.active_lease()
        self.blocked(lease["lease_id"], job["job_id"], "attempt-1", now=self.now + 31)
        with self.queue.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM resource_leases").fetchone()[0], "active")

    def test_window_and_job_lease_expiration_are_each_enforced(self):
        job, lease = self.active_lease()
        for table, column in (("gpu_windows", "expires_at"), ("jobs", "lease_expires_at")):
            with self.subTest(table=table):
                with self.queue.connection() as db:
                    original = db.execute(f"SELECT {column} FROM {table}").fetchone()[0]
                with self.queue.connection(write=True) as db:
                    db.execute(f"UPDATE {table} SET {column}=?", (self.now - 1,))
                self.blocked(lease["lease_id"], job["job_id"], "attempt-1")
                with self.queue.connection(write=True) as db:
                    db.execute(f"UPDATE {table} SET {column}=?", (original,))

    def test_released_lease_remains_released_after_verification(self):
        job, lease = self.active_lease()
        self.assertTrue(self.gpu.release(lease["lease_id"], job["worker_id"], compute_stopped=True))
        self.blocked(lease["lease_id"], job["job_id"], "attempt-1")

    def test_orphaned_lease_is_never_treated_as_reusable(self):
        job, lease = self.active_lease()
        self.assertTrue(self.gpu.mark_orphaned(lease["lease_id"], job["worker_id"], "Synthetic lost worker"))
        self.blocked(lease["lease_id"], job["job_id"], "attempt-1")

    def test_finished_job_with_null_job_lease_returns_a_blocked_error(self):
        job, lease = self.active_lease()
        finished = self.queue.finish(job["job_id"], job["worker_id"], "failed",
                                     error={"code": "synthetic_failure"}, expected_attempt=1)
        self.assertIsNone(finished["lease_expires_at"])
        self.blocked(lease["lease_id"], job["job_id"], "attempt-1")

    def test_missing_database_is_not_created_and_malformed_database_is_blocked(self):
        missing = Path(self.temp.name) / "not-created.sqlite3"
        for path, lease_id in ((None, "lease"), (missing, "lease"), (self.db_path, None)):
            with self.subTest(path=path, lease_id=lease_id):
                with self.assertRaises(RenderError) as raised:
                    verify_gpu_lease(path, lease_id, "job", "attempt-1")
                self.assertEqual((raised.exception.code, raised.exception.status), ("GPU_LEASE_REQUIRED", "blocked"))
        self.assertFalse(missing.exists())
        malformed = Path(self.temp.name) / "malformed.sqlite3"
        malformed.write_bytes(b"not a SQLite database")
        before = malformed.read_bytes()
        with self.assertRaises(RenderError) as raised:
            verify_gpu_lease(malformed, "lease", "job", "attempt-1")
        self.assertEqual((raised.exception.code, raised.exception.status), ("GPU_LEASE_REQUIRED", "blocked"))
        self.assertEqual(malformed.read_bytes(), before)


class EncoderArgumentsTests(unittest.TestCase):
    def test_cpu_uses_x264_crf_and_preset_rate_limits(self):
        preset = {"maxrate": "8M", "bufsize": "16M"}
        arguments = encoder_args("cpu", preset)
        options = dict(zip(arguments[::2], arguments[1::2]))
        self.assertEqual(options["-c:v"], "libx264")
        self.assertEqual(options["-crf"], "21")
        self.assertEqual(options["-preset"], "veryfast")
        self.assertEqual((options["-maxrate"], options["-bufsize"]), ("8M", "16M"))
        self.assertEqual(options["-pix_fmt"], "yuv420p")
        self.assertNotIn("-cq", options)
        self.assertNotIn("-rc", options)
        self.assertEqual(preset, {"maxrate": "8M", "bufsize": "16M"})

    def test_nvenc_uses_vbr_and_selected_rates_without_enabling_hardware_decode(self):
        for rate, buffer in (("8M", "16M"), ("12M", "24M")):
            with self.subTest(rate=rate):
                arguments = encoder_args("nvenc", {"maxrate": rate, "bufsize": buffer})
                options = dict(zip(arguments[::2], arguments[1::2]))
                self.assertEqual(options["-c:v"], "h264_nvenc")
                self.assertEqual((options["-preset"], options["-tune"], options["-rc"]), ("p5", "hq", "vbr"))
                self.assertEqual(options["-cq"], "21")
                self.assertEqual((options["-b:v"], options["-maxrate"], options["-bufsize"]), (rate, rate, buffer))
                self.assertEqual(options["-pix_fmt"], "yuv420p")
                self.assertNotIn("-crf", options)
                self.assertFalse(any("hwaccel" in argument or "cuvid" in argument for argument in arguments))
        self.assertFalse(any("hwaccel" in argument for argument in encoder_args("cpu", {"maxrate": "8M", "bufsize": "16M"})))

    def test_unknown_backend_is_rejected(self):
        for backend in ("auto", "cuda", "nvdec", None):
            with self.subTest(backend=backend):
                with self.assertRaises(RenderError):
                    encoder_args(backend, {"maxrate": "8M", "bufsize": "16M"})


def box(name, payload=b"", extended=False):
    if extended:
        return struct.pack(">I4sQ", 1, name, 16 + len(payload)) + payload
    return struct.pack(">I4s", 8 + len(payload), name) + payload


class MP4FaststartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "container-boxes.bin"
        self.ftyp = box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")

    def check_boxes(self, payload, expected):
        self.path.write_bytes(payload)
        self.assertEqual(mp4_faststart(self.path), expected)
        self.assertEqual(self.path.read_bytes(), payload, "Container inspection must be read-only")

    def test_actual_top_level_moov_before_mdat_is_faststart(self):
        self.check_boxes(self.ftyp + box(b"free", b"padding") + box(b"moov") + box(b"mdat", b"sample"), True)

    def test_mdat_before_moov_is_not_faststart(self):
        self.check_boxes(self.ftyp + box(b"mdat", b"sample") + box(b"moov"), False)

    def test_box_names_inside_payload_do_not_count_as_top_level_boxes(self):
        self.check_boxes(self.ftyp + box(b"mdat", box(b"moov")), False)
        self.check_boxes(self.ftyp + box(b"moov", box(b"mdat")), False)

    def test_valid_extended_size_boxes_are_parsed_in_real_order(self):
        self.check_boxes(self.ftyp + box(b"moov", extended=True) + box(b"mdat", b"sample", extended=True), True)
        self.check_boxes(self.ftyp + box(b"mdat", b"sample", extended=True) + box(b"moov", extended=True), False)

    def test_zero_size_mdat_extends_to_eof(self):
        self.check_boxes(self.ftyp + box(b"moov") + struct.pack(">I4s", 0, b"mdat") + b"sample", True)
        self.check_boxes(self.ftyp + struct.pack(">I4s", 0, b"mdat") + box(b"moov"), False)

    def test_missing_required_boxes_and_empty_files_are_not_faststart(self):
        for payload in (b"", b"short", self.ftyp, self.ftyp + box(b"moov"), self.ftyp + box(b"mdat")):
            with self.subTest(payload=payload):
                self.check_boxes(payload, False)

    def test_truncated_payload_and_invalid_sizes_are_rejected(self):
        for malformed in (
            struct.pack(">I4s", 7, b"mdat"),
            struct.pack(">I4s", 100, b"mdat") + b"short",
            struct.pack(">I4s", 1, b"mdat"),
            struct.pack(">I4sQ", 1, b"mdat", 15),
            struct.pack(">I4sQ", 1, b"mdat", 100) + b"short",
        ):
            with self.subTest(malformed=malformed):
                self.check_boxes(self.ftyp + box(b"moov") + malformed, False)

    def test_trailing_partial_box_header_is_rejected_even_after_valid_moov_mdat(self):
        valid = self.ftyp + box(b"moov") + box(b"mdat", b"sample")
        for length in range(1, 8):
            with self.subTest(partial_header_bytes=length):
                self.check_boxes(valid + struct.pack(">I4s", 16, b"free")[:length], False)


if __name__ == "__main__":
    unittest.main()
