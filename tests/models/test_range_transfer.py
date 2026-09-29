"""CPU network mocks for bounded parallel range transport, no real downloads."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from scripts.models import range_transfer as transfer
from scripts.models.download_weights import fetch

URL = "https://example.invalid/fixed-revision/model.safetensors"


class Response(io.BytesIO):
    def __init__(self, body, start, end, total, *, status=206, content_range=None, content_length=None):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Range": f"bytes {start}-{end}/{total}" if content_range is None else content_range,
                        "Content-Length": str(end-start+1) if content_length is None else content_length}


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.partial = self.directory / "model.safetensors.partial"
        self.pause = self.directory / "pause"

    def server(self, data, seen, *, transform=None):
        lock = threading.Lock()
        def opener(request, timeout):
            self.assertEqual(request.full_url, URL)
            self.assertGreater(timeout, 0)
            start, end = map(int, request.get_header("Range").removeprefix("bytes=").split("-"))
            with lock:
                seen.append((start, end))
            response = Response(data[start:end+1], start, end, len(data))
            return transform(response, start, end) if transform else response
        return opener

    def run_transfer(self, data, **kwargs):
        return transfer.append_ranges(URL, self.partial, len(data), chunk_bytes=kwargs.pop("chunk_bytes", 4), **kwargs)

    def test_exact_ranges_append_in_order_and_outer_fetch_verifies_full_sha(self):
        data, seen = bytes(range(39)), []
        sha = hashlib.sha256(data).hexdigest()
        marker = self.partial.with_name(self.partial.name+".source.json")
        marker.write_text(json.dumps({"url": URL, "maximum": len(data), "sha256": sha, "blob": None, "hash_prefix": None}))
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, seen)):
            stats = self.run_transfer(data)
        self.assertEqual(self.partial.read_bytes(), data)
        self.assertEqual(sorted(seen), [(i, min(i+3, 38)) for i in range(0, 39, 4)])
        self.assertEqual(stats["status"], "complete")
        self.assertEqual(stats["bytes_appended"], 39)
        self.assertEqual(stats["batches_completed"], 3)
        self.assertEqual(stats["ranges_completed"], 10)
        self.assertEqual(stats["peak_body_buffer_bytes"], 16)
        target = self.directory / "model.safetensors"
        with patch.object(transfer.urllib.request, "urlopen") as network, redirect_stdout(io.StringIO()):
            result = fetch(URL, target, len(data), expected_sha=sha)
        network.assert_not_called()
        self.assertEqual(result["sha256"], sha)
        self.assertEqual(target.read_bytes(), data)

    def test_arbitrary_prefix_byte_offset_resume(self):
        data, seen = b"abcdefghijklmnopqrstuvwxyz", []
        self.partial.write_bytes(data[:3])
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, seen)):
            stats = self.run_transfer(data)
        self.assertEqual(min(start for start, end in seen), 3)
        self.assertEqual(stats["start_offset"], 3)
        self.assertEqual(stats["bytes_appended"], len(data)-3)
        self.assertEqual(self.partial.read_bytes(), data)

    def test_four_workers_bound_and_out_of_order_completion(self):
        data, seen, active, peak = bytes(range(16)), [], 0, 0
        barrier = threading.Barrier(4, timeout=3)
        lock = threading.Lock()
        def transform(response, start, end):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait()
            # Later byte ranges finish first; append order must still be exact.
            time.sleep((12-start)*.001)
            with lock:
                active -= 1
            return response
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, seen, transform=transform)):
            stats = self.run_transfer(data)
        self.assertEqual(peak, 4)
        self.assertEqual(self.partial.read_bytes(), data)
        self.assertEqual(stats["concurrency"], 4)

    def test_one_worker_fallback(self):
        data, seen = b"abcdefghijklmnopq", []
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, seen)):
            stats = self.run_transfer(data, concurrency=1)
        self.assertEqual(stats["peak_body_buffer_bytes"], 4)
        self.assertEqual(stats["batches_completed"], 5)
        self.assertEqual(self.partial.read_bytes(), data)

    def test_pause_before_start_does_not_create_or_touch_partial(self):
        self.pause.touch()
        with patch.object(transfer.urllib.request, "urlopen") as network:
            result = self.run_transfer(b"abc", pause_file=self.pause)
        network.assert_not_called()
        self.assertEqual(result["status"], "paused")
        self.assertFalse(self.partial.exists())

    def test_pause_during_batch_commits_only_that_batch_and_fsyncs(self):
        data, seen = bytes(range(40)), []
        def transform(response, start, end):
            self.pause.touch()
            return response
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, seen, transform=transform)), \
             patch.object(transfer.os, "fsync", wraps=os.fsync) as sync:
            stats = self.run_transfer(data, pause_file=self.pause)
        self.assertEqual(stats["status"], "paused")
        self.assertEqual(sorted(seen), [(0, 3), (4, 7), (8, 11), (12, 15)])
        self.assertEqual(self.partial.read_bytes(), data[:16])
        self.assertEqual(sync.call_count, 1)

    def test_bad_second_batch_preserves_first_committed_prefix(self):
        data, seen = bytes(range(40)), []
        def transform(response, start, end):
            if start == 20:
                response.headers["Content-Range"] = "bytes 0-3/40"
            return response
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, seen, transform=transform)), self.assertRaisesRegex(ValueError, "exact bounded Range"):
            self.run_transfer(data)
        self.assertEqual(self.partial.read_bytes(), data[:16])
        self.assertEqual([p.name for p in self.directory.iterdir()], [self.partial.name])

    def test_status_wrong_range_total_or_length_discard_entire_batch(self):
        for change in (lambda r: setattr(r, "status", 200), lambda r: r.headers.update({"Content-Range": "bytes 1-4/16"}),
                       lambda r: r.headers.update({"Content-Range": "bytes 0-3/17"}), lambda r: r.headers.update({"Content-Length": "5"}),
                       lambda r: r.headers.update({"Content-Length": "garbage"})):
            self.partial.write_bytes(b"")
            def transform(response, start, end):
                if start == 0:
                    change(response)
                return response
            with self.subTest(change=change), patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(bytes(range(16)), [], transform=transform)), self.assertRaises(ValueError):
                self.run_transfer(bytes(range(16)))
            self.assertEqual(self.partial.read_bytes(), b"")

    def test_truncated_body_does_not_append_other_valid_ranges(self):
        data = bytes(range(16))
        def transform(response, start, end):
            return Response(data[start:end], start, end, len(data)) if start == 8 else response
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, [], transform=transform)), self.assertRaisesRegex(ValueError, "truncated Range"):
            self.run_transfer(data)
        self.assertEqual(self.partial.read_bytes(), b"")

    def test_overlong_body_does_not_append_corrupted_scratch_byte(self):
        data = bytes(range(16))
        def transform(response, start, end):
            return Response(data[start:end+1]+b"!", start, end, len(data)) if start == 4 else response
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, [], transform=transform)), self.assertRaisesRegex(ValueError, "exceeds requested"):
            self.run_transfer(data)
        self.assertEqual(self.partial.read_bytes(), b"")

    def test_absent_length_header_still_requires_exact_body(self):
        data = b"abcdefgh"
        def transform(response, start, end):
            del response.headers["Content-Length"]
            return response
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, [], transform=transform)):
            self.run_transfer(data)
        self.assertEqual(self.partial.read_bytes(), data)

    def test_interruption_keeps_prefix_for_new_call(self):
        data = b"abcdefghijklmnopqrstuvwxyz"
        self.partial.write_bytes(data[:3])
        with patch.object(transfer.urllib.request, "urlopen", side_effect=TimeoutError("synthetic connection timeout")), self.assertRaises(TimeoutError):
            self.run_transfer(data)
        self.assertEqual(self.partial.read_bytes(), data[:3])
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, [])):
            self.run_transfer(data)
        self.assertEqual(self.partial.read_bytes(), data)

    def test_range_deadline_includes_reads_and_keeps_prefix(self):
        data = b"abcd"
        clock = [0.0]
        response = Response(data, 0, 3, 4)
        original = response.readinto
        def slow_read(view):
            count = original(view)
            clock[0] = 181.0
            return count
        response.readinto = slow_read
        with patch.object(transfer.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(transfer.urllib.request, "urlopen", return_value=response), self.assertRaisesRegex(TimeoutError, "deadline"):
            self.run_transfer(data, concurrency=1)
        self.assertEqual(self.partial.read_bytes(), b"")

    def test_total_deadline_is_independent_of_range_deadline(self):
        data = b"abcd"
        clock = [0.0]
        response = Response(data, 0, 3, 4)
        original = response.readinto
        def slow_read(view):
            count = original(view)
            clock[0] = 3.0
            return count
        response.readinto = slow_read
        with patch.object(transfer.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(transfer.urllib.request, "urlopen", return_value=response), self.assertRaises(TimeoutError):
            self.run_transfer(data, concurrency=1, total_timeout_seconds=2)
        self.assertEqual(self.partial.read_bytes(), b"")

    def test_complete_or_oversized_partial_never_requests_network(self):
        self.partial.write_bytes(b"abcd")
        with patch.object(transfer.urllib.request, "urlopen") as network:
            stats = self.run_transfer(b"abcd")
            with self.assertRaisesRegex(ValueError, "oversize"):
                self.run_transfer(b"abc")
        network.assert_not_called()
        self.assertEqual(stats["bytes_appended"], 0)
        self.assertEqual(self.partial.read_bytes(), b"abcd")

    def test_invalid_limits_and_credential_url_refused(self):
        for kwargs in ({"concurrency": 5}, {"concurrency": True}, {"chunk_bytes": transfer.MAX_RANGE_BYTES+1},
                       {"chunk_bytes": 0}, {"range_timeout_seconds": float("inf")}, {"request_timeout_seconds": 0}):
            with self.subTest(kwargs=kwargs), patch.object(transfer.urllib.request, "urlopen") as network, self.assertRaises(ValueError):
                self.run_transfer(b"abc", **kwargs)
            network.assert_not_called()
        with self.assertRaises(ValueError):
            transfer.append_ranges("https://name:secret@example.invalid/model", self.partial, 3)

    def test_concurrent_partial_change_detected_before_batch_append(self):
        data = b"abcdefgh"
        def transform(response, start, end):
            if start == 0:
                self.partial.write_bytes(b"other writer")
            return response
        with patch.object(transfer.urllib.request, "urlopen", side_effect=self.server(data, [], transform=transform)), self.assertRaisesRegex(ValueError, "changed concurrently"):
            self.run_transfer(data)
        self.assertEqual(self.partial.read_bytes(), b"other writer")


if __name__ == "__main__":
    unittest.main()
