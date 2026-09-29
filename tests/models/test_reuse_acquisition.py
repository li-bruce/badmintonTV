"""CPU/network-mock acquisition boundaries; no real download or model inference."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.models import acquire_vl_weights as acquire
from scripts.models import acquire_tracknet_reuse as tracknet


URL = f"{acquire.SOURCE}/resolve/{acquire.REVISION}/model.safetensors"
RANGE_BYTES = 8_388_608


class Response(io.BytesIO):
    def __init__(self, body, start, end, total, *, status=206, content_range=None, content_length=None):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Range": content_range if content_range is not None else f"bytes {start}-{end}/{total}",
                        "Content-Length": str(end-start+1) if content_length is None else content_length}


class InterruptedResponse(Response):
    """Return a bounded prefix then simulate a network interruption."""
    def __init__(self, prefix, start, end, total):
        super().__init__(prefix, start, end, total)
        self.delivered = False

    def read(self, amount=-1):
        if self.delivered:
            raise TimeoutError("synthetic network interruption")
        self.delivered = True
        return super().read(amount)


class RangeDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name) / "model.safetensors"
        self.partial = self.target.with_name(self.target.name + ".partial")
        self.marker = self.partial.with_name(self.partial.name + ".source.json")
        self.output = io.StringIO()
        self.quiet = redirect_stdout(self.output)
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def identity(self, data, **changes):
        return {"url": URL, "maximum": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "blob": None, "hash_prefix": None, **changes}

    def seed(self, data, prefix, **changes):
        self.partial.write_bytes(prefix)
        self.marker.write_text(json.dumps(self.identity(data, **changes)), encoding="utf-8")

    def call(self, data, **kwargs):
        return acquire.fetch_large_ranges(URL, self.target, len(data), kwargs.get("sha", hashlib.sha256(data).hexdigest()))

    def server(self, data, seen):
        def open_request(request, timeout):
            self.assertEqual(request.full_url, URL)
            self.assertEqual(timeout, 30)
            header = request.get_header("Range")
            start, end = map(int, header.removeprefix("bytes=").split("-"))
            seen.append((start, end))
            self.assertLessEqual(end-start+1, RANGE_BYTES)
            self.assertLess(end, len(data))
            return Response(data[start:end+1], start, end, len(data))
        return open_request

    def test_exact_206_multiple_ranges_full_sha_and_exclusive_publication(self):
        data = b"x" * RANGE_BYTES + b"last-range"
        seen = []
        with patch.object(acquire.urllib.request, "urlopen", side_effect=self.server(data, seen)) as network:
            result = self.call(data)
        self.assertEqual(seen, [(0, RANGE_BYTES-1), (RANGE_BYTES, len(data)-1)])
        self.assertEqual(network.call_count, 2)
        self.assertEqual(self.target.read_bytes(), data)
        self.assertFalse(self.partial.exists())
        self.assertEqual(result, {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.assertEqual(json.loads(self.marker.read_text()), self.identity(data))

    def test_interruption_retains_prefix_and_next_call_resumes_exact_offset(self):
        data = b"0123456789"
        with patch.object(acquire.urllib.request, "urlopen", return_value=InterruptedResponse(data[:3], 0, 9, 10)), self.assertRaises(TimeoutError):
            self.call(data)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.partial.read_bytes(), b"012")
        seen = []
        with patch.object(acquire.urllib.request, "urlopen", side_effect=self.server(data, seen)):
            self.call(data)
        self.assertEqual(seen, [(3, 9)])
        self.assertEqual(self.target.read_bytes(), data)

    def test_zero_byte_interruption_can_resume(self):
        data = b"0123456789"
        with patch.object(acquire.urllib.request, "urlopen", side_effect=TimeoutError("before response")), self.assertRaises(TimeoutError):
            self.call(data)
        self.assertEqual(self.partial.read_bytes(), b"")
        seen = []
        with patch.object(acquire.urllib.request, "urlopen", side_effect=self.server(data, seen)):
            self.call(data)
        self.assertEqual(seen, [(0, 9)])

    def test_wrong_content_range_refused_before_write(self):
        data = b"0123456789"
        for header in ("bytes 1-9/10", "bytes 0-8/10", "bytes 0-9/11", "bytes 0-9/*", ""):
            with self.subTest(header=header), patch.object(acquire.urllib.request, "urlopen", return_value=Response(data, 0, 9, 10, content_range=header)), self.assertRaisesRegex(ValueError, "exact bounded Range"):
                self.call(data)
            self.assertFalse(self.target.exists())
            self.assertEqual(self.partial.read_bytes(), b"")

    def test_http_200_refused_even_with_range_shaped_headers(self):
        data = b"abc"
        with patch.object(acquire.urllib.request, "urlopen", return_value=Response(data, 0, 2, 3, status=200)), self.assertRaisesRegex(ValueError, "exact bounded Range"):
            self.call(data)
        self.assertEqual(self.partial.read_bytes(), b"")

    def test_wrong_content_length_refused_before_write(self):
        data = b"abc"
        with patch.object(acquire.urllib.request, "urlopen", return_value=Response(data, 0, 2, 3, content_length="4")), self.assertRaisesRegex(ValueError, "Range length"):
            self.call(data)
        self.assertEqual(self.partial.read_bytes(), b"")
        self.assertFalse(self.target.exists())

    def test_missing_content_length_still_requires_exact_body(self):
        data = b"abc"
        with patch.object(acquire.urllib.request, "urlopen", return_value=Response(data, 0, 2, 3, content_length="")):
            self.call(data)
        self.assertEqual(self.target.read_bytes(), data)

    def test_truncated_body_retained_for_later_resume(self):
        data = b"abcdef"
        with patch.object(acquire.urllib.request, "urlopen", return_value=Response(b"abc", 0, 5, 6)), self.assertRaisesRegex(ValueError, "truncated Range"):
            self.call(data)
        self.assertEqual(self.partial.read_bytes(), b"abc")
        self.assertFalse(self.target.exists())
        self.assertEqual(json.loads(self.marker.read_text()), self.identity(data))

    def test_overlong_body_refused_without_writing_excess(self):
        data = b"abc"
        with patch.object(acquire.urllib.request, "urlopen", return_value=Response(b"abcdef", 0, 2, 3)), self.assertRaisesRegex(ValueError, "exceeds requested byte interval"):
            self.call(data)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.partial.read_bytes(), data)

    def test_source_identity_change_preserves_partial_without_network(self):
        data = b"abcdef"
        for change in ({"url": URL + "?different"}, {"maximum": 7}, {"sha256": "0"*64}, {"blob": "changed"}, {"hash_prefix": "abcd"}):
            self.seed(data, b"abc", **change)
            with self.subTest(change=change), patch.object(acquire.urllib.request, "urlopen") as network, self.assertRaisesRegex(ValueError, "source differs"):
                self.call(data)
            network.assert_not_called()
            self.assertEqual(self.partial.read_bytes(), b"abc")
            self.assertFalse(self.target.exists())

    def test_unverified_partial_preserved_without_network(self):
        self.partial.write_bytes(b"unverified")
        with patch.object(acquire.urllib.request, "urlopen") as network, self.assertRaisesRegex(ValueError, "unverified existing partial"):
            self.call(b"abc")
        network.assert_not_called()
        self.assertEqual(self.partial.read_bytes(), b"unverified")
        self.assertFalse(self.marker.exists())

    def test_oversized_partial_preserved_without_network(self):
        data = b"abc"
        self.seed(data, b"abcdef")
        with patch.object(acquire.urllib.request, "urlopen") as network, self.assertRaisesRegex(ValueError, "oversize partial"):
            self.call(data)
        network.assert_not_called()
        self.assertEqual(self.partial.read_bytes(), b"abcdef")

    def test_corrupted_prefix_fails_full_hash_after_resume(self):
        data = b"abcdef"
        self.seed(data, b"xxx")
        with patch.object(acquire.urllib.request, "urlopen", side_effect=self.server(data, [])), self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.call(data)
        self.assertEqual(self.partial.read_bytes(), b"xxxdef")
        self.assertFalse(self.target.exists())

    def test_complete_partial_checks_sha_without_any_network(self):
        data = b"abcdef"
        self.seed(data, data)
        with patch.object(acquire.urllib.request, "urlopen") as network:
            self.call(data)
        network.assert_not_called()
        self.assertEqual(self.target.read_bytes(), data)

    def test_existing_target_is_verified_not_replaced(self):
        data = b"abcdef"
        self.target.write_bytes(data)
        with patch.object(acquire.urllib.request, "urlopen") as network:
            self.call(data)
            with self.assertRaisesRegex(ValueError, "existing weight hash mismatch"):
                self.call(data, sha="0"*64)
        network.assert_not_called()
        self.assertEqual(self.target.read_bytes(), data)
        self.assertFalse(self.partial.exists())

    def test_segment_deadline_retains_partial_before_write(self):
        data = b"abc"
        with patch.object(acquire.urllib.request, "urlopen", return_value=Response(data, 0, 2, 3)), \
             patch.object(acquire.time, "monotonic", side_effect=[0.0, 0.0, 181.0]), \
             self.assertRaisesRegex(TimeoutError, "transfer deadline"):
            self.call(data)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.partial.read_bytes(), b"")


class CheckpointExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name) / "TrackNet_best.pt"
        self.partial = self.target.with_name(self.target.name + ".extract.partial")
        self.data = b"synthetic checkpoint bytes; never loaded"
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("public-folder/TrackNet_best.pt", self.data)
        archive.seek(0)
        self.archive = zipfile.ZipFile(archive)
        self.addCleanup(self.archive.close)
        self.info = self.archive.getinfo("public-folder/TrackNet_best.pt")

    def test_extracts_exact_bytes_and_hash(self):
        digest = tracknet.extract_verified(self.archive, self.info, self.target)
        self.assertEqual(digest, hashlib.sha256(self.data).hexdigest())
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertFalse(self.partial.exists())

    def test_identical_existing_checkpoint_reused_without_rewrite(self):
        self.target.write_bytes(self.data)
        before = self.target.stat().st_mtime_ns
        with patch.object(tracknet.os, "link") as publish:
            digest = tracknet.extract_verified(self.archive, self.info, self.target)
        publish.assert_not_called()
        self.assertEqual(digest, hashlib.sha256(self.data).hexdigest())
        self.assertEqual(self.target.stat().st_mtime_ns, before)

    def test_same_size_corrupt_checkpoint_preserved_and_refused(self):
        corrupt = b"!" + self.data[1:]
        self.target.write_bytes(corrupt)
        with self.assertRaisesRegex(ValueError, "differs from archive; preserved"):
            tracknet.extract_verified(self.archive, self.info, self.target)
        self.assertEqual(self.target.read_bytes(), corrupt)
        self.assertFalse(self.partial.exists())

    def test_different_size_checkpoint_preserved(self):
        self.target.write_bytes(b"not the checkpoint")
        with self.assertRaisesRegex(ValueError, "differs from archive; preserved"):
            tracknet.extract_verified(self.archive, self.info, self.target)
        self.assertEqual(self.target.read_bytes(), b"not the checkpoint")

    def test_linked_target_refused_before_reading_archive(self):
        with patch.object(Path, "is_symlink", return_value=True), \
             patch.object(self.archive, "open") as read, self.assertRaisesRegex(ValueError, "linked extraction target"):
            tracknet.extract_verified(self.archive, self.info, self.target)
        read.assert_not_called()

    def test_existing_partial_never_overwritten(self):
        self.partial.write_bytes(b"retained interrupted extraction")
        with self.assertRaises(FileExistsError):
            tracknet.extract_verified(self.archive, self.info, self.target)
        self.assertEqual(self.partial.read_bytes(), b"retained interrupted extraction")
        self.assertFalse(self.target.exists())

    def test_publish_collision_keeps_other_file_and_verified_partial(self):
        def collide(source, target):
            target.write_bytes(b"concurrently created file")
            raise FileExistsError("publication race")
        with patch.object(tracknet.os, "link", side_effect=collide), self.assertRaises(FileExistsError):
            tracknet.extract_verified(self.archive, self.info, self.target)
        self.assertEqual(self.target.read_bytes(), b"concurrently created file")
        self.assertEqual(self.partial.read_bytes(), self.data)


if __name__ == "__main__":
    unittest.main()
