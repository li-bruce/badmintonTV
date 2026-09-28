"""Transport and quota safety tests; fixtures are bytes, not video evidence."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from packages.library.download import DownloadError, download
from packages.library.storage import QuotaExceeded, QuotaManager, UnsafePath


PAYLOAD = bytes(range(256)) * 512
PARTIAL_BYTES = 24_576


def quota_for(root: str | Path, **kwargs) -> QuotaManager:
    return QuotaManager(Path(root) / "data", allow_test_root=True, min_free_bytes=0, **kwargs)


def reserve_worker(root, ready, release, outcomes):
    """Each process opens its own connection, as real download workers do."""
    try:
        quota = quota_for(root, owner_limit_bytes=300_000)
        ready.wait(15)
        reservation = quota.reserve(100_000, purpose="multiprocess safety test")
        outcomes.put(("reserved", reservation.reservation_id))
        release.wait(15)
        reservation.release("test completed")
    except QuotaExceeded:
        outcomes.put(("denied", None))
    except Exception as error:
        outcomes.put(("error", repr(error)))


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        self.server.requests.append({"route": route, "range": self.headers.get("Range"), "if_range": self.headers.get("If-Range")})
        with self.server.counter_lock:
            count = self.server.counts.get(route, 0)
            self.server.counts[route] = count + 1
        if route == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok?token=DO_NOT_RECORD_THIS_TOKEN")
            self.end_headers()
            return
        if route == "/oversize":
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(PAYLOAD)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        interrupted = route in ("/interrupt", "/bad-range", "/changed", "/ignore-range", "/no-validator", "/last-modified")
        range_header = self.headers.get("Range")
        if range_header and route != "/ignore-range":
            offset = int(range_header.split("=")[1].split("-")[0])
            self.send_response(206)
            start = offset + 1 if route == "/bad-range" else offset
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
            self.send_header("Content-Length", str(len(PAYLOAD) - offset))
            if route == "/last-modified":
                self.send_header("Last-Modified", "Mon, 28 Sep 2026 00:00:00 GMT")
            else:
                self.send_header("ETag", '"changed"' if route == "/changed" else '"fixture-v1"')
            self.end_headers()
            self.wfile.write(PAYLOAD[offset:])
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        if route == "/last-modified":
            self.send_header("Last-Modified", "Mon, 28 Sep 2026 00:00:00 GMT")
        elif route != "/no-validator":
            self.send_header("ETag", '"fixture-v1"')
        self.end_headers()
        if interrupted and count == 0:
            self.wfile.write(PAYLOAD[:PARTIAL_BYTES])
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
            self.connection.close()
        else:
            try:
                self.wfile.write(PAYLOAD)
            except (BrokenPipeError, ConnectionResetError):
                pass


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="library-download-test-")
        self.root = Path(self.temporary.name)
        self.quota = quota_for(self.root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.server.daemon_threads = True
        self.server.requests = []
        self.server.counts = {}
        self.server.counter_lock = threading.Lock()
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        self.temporary.cleanup()

    def get(self, route="/ok", filename="raw/sample.bin", **kwargs):
        return download(self.url + route, filename, quota=self.quota, max_bytes=len(PAYLOAD), **kwargs)

    def metadata(self, filename="raw/sample.bin"):
        return json.loads((self.quota.data_root / (filename + ".download.json")).read_text(encoding="utf-8"))

    def test_success_hash_metadata_and_no_overwrite(self):
        digest = hashlib.sha256(PAYLOAD).hexdigest()
        result = self.get(expected_sha256=digest)
        self.assertEqual(result.path.read_bytes(), PAYLOAD)
        self.assertEqual(result.sha256, digest)
        self.assertEqual(result.size_bytes, len(PAYLOAD))
        self.assertEqual(result.resumed_bytes, 0)
        self.assertEqual(self.metadata()["state"], "succeeded")
        self.assertFalse(Path(str(result.path) + ".part").exists())
        self.assertFalse(Path(str(result.path) + ".lock").exists())
        self.assertEqual(self.quota.active_reservations(), [])
        with self.assertRaises(FileExistsError):
            self.get()
        self.assertEqual(result.path.read_bytes(), PAYLOAD)
        self.assertEqual(len(self.server.requests), 1)

    def test_stream_without_content_length_cannot_write_above_cap(self):
        with self.assertRaises(DownloadError) as caught:
            download(self.url + "/oversize", "bounded.bin", quota=self.quota, max_bytes=100_000)
        self.assertEqual(caught.exception.code, "size_limit")
        self.assertLessEqual((self.quota.data_root / "bounded.bin.part").stat().st_size, 100_000)
        self.assertFalse((self.quota.data_root / "bounded.bin").exists())
        self.assertEqual(self.metadata("bounded.bin")["error"]["code"], "size_limit")
        self.assertEqual(self.quota.active_reservations(), [])

    def test_declared_oversize_is_refused_before_creating_partial(self):
        with self.assertRaises(DownloadError) as caught:
            download(self.url + "/ok", "large.bin", quota=self.quota, max_bytes=1024)
        self.assertEqual(caught.exception.code, "size_limit")
        self.assertFalse((self.quota.data_root / "large.bin.part").exists())
        self.assertEqual(self.metadata("large.bin")["state"], "failed")

    def test_interrupted_transfer_resumes_using_saved_etag_and_offset(self):
        with self.assertRaises(DownloadError) as caught:
            self.get("/interrupt")
        self.assertEqual(caught.exception.code, "incomplete")
        self.assertEqual(self.metadata()["validator"], '"fixture-v1"')
        self.assertEqual(self.metadata()["size_bytes"], PARTIAL_BYTES)
        self.assertEqual(self.quota.active_reservations(), [])
        result = self.get("/interrupt")
        self.assertEqual(result.resumed_bytes, PARTIAL_BYTES)
        self.assertEqual(result.path.read_bytes(), PAYLOAD)
        self.assertEqual(self.server.requests[-1]["range"], f"bytes={PARTIAL_BYTES}-")
        self.assertEqual(self.server.requests[-1]["if_range"], '"fixture-v1"')
        self.assertEqual(len(self.metadata()["attempts"]), 2)

    def test_last_modified_is_supported_as_fallback_validator(self):
        with self.assertRaises(DownloadError):
            self.get("/last-modified")
        self.assertEqual(self.metadata()["validator_header"], "Last-Modified")
        result = self.get("/last-modified")
        self.assertEqual(result.path.read_bytes(), PAYLOAD)

    def test_invalid_resume_responses_never_append_bytes(self):
        for route, expected_code in (("/bad-range", "invalid_range"), ("/changed", "validator_changed"), ("/ignore-range", "unsafe_resume"), ("/no-validator", "unsafe_resume")):
            filename = route[1:] + ".bin"
            with self.subTest(route=route):
                with self.assertRaises(DownloadError):
                    self.get(route, filename)
                partial = self.quota.data_root / (filename + ".part")
                before = partial.read_bytes()
                with self.assertRaises(DownloadError) as caught:
                    self.get(route, filename)
                self.assertEqual(caught.exception.code, expected_code)
                self.assertEqual(partial.read_bytes(), before)
                self.assertFalse((self.quota.data_root / filename).exists())

    def test_wrong_hash_never_publishes_or_restarts_partial(self):
        for _ in range(2):
            with self.assertRaises(DownloadError) as caught:
                self.get(expected_sha256="0" * 64)
            self.assertEqual(caught.exception.code, "checksum_mismatch")
        self.assertFalse((self.quota.data_root / "raw/sample.bin").exists())
        self.assertEqual((self.quota.data_root / "raw/sample.bin.part").read_bytes(), PAYLOAD)
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.metadata()["sha256"], hashlib.sha256(PAYLOAD).hexdigest())

    def test_unsafe_partial_or_foreign_metadata_is_retained(self):
        partial = self.quota.data_root / "existing.bin.part"
        partial.write_bytes(b"unregistered data")
        with self.assertRaises(DownloadError) as caught:
            self.get(filename="existing.bin")
        self.assertEqual(caught.exception.code, "missing_metadata")
        self.assertEqual(partial.read_bytes(), b"unregistered data")
        self.assertEqual(self.server.requests, [])

    def test_per_file_lock_refuses_another_writer(self):
        lock = self.quota.data_root / "locked.bin.lock"
        lock.write_text("existing writer", encoding="utf-8")
        with self.assertRaises(DownloadError) as caught:
            self.get(filename="locked.bin")
        self.assertEqual(caught.exception.code, "locked")
        self.assertEqual(lock.read_text(encoding="utf-8"), "existing writer")
        self.assertEqual(self.quota.active_reservations(), [])
        self.assertEqual(self.server.requests, [])

    def test_response_identity_is_durable_before_first_payload_write(self):
        original_open = Path.open
        observed = []

        def guarded_open(path, mode="r", *args, **kwargs):
            if path.name.endswith(".part") and mode in ("xb", "ab"):
                stored = self.metadata()
                observed.append((stored["state"], stored["validator"], stored["expected_total"]))
            return original_open(path, mode, *args, **kwargs)

        with mock.patch.object(Path, "open", guarded_open):
            self.get()
        self.assertEqual(observed, [("downloading", '"fixture-v1"', len(PAYLOAD))])

    def test_redirect_signed_url_is_not_persisted(self):
        result = self.get("/redirect")
        contents = result.metadata_path.read_text(encoding="utf-8")
        self.assertNotIn("DO_NOT_RECORD_THIS_TOKEN", contents)
        self.assertEqual(self.metadata()["url"], self.url + "/redirect")
        self.assertEqual(self.metadata()["final_origin"], self.url)

    def test_atomic_publication_cannot_replace_a_racing_destination(self):
        original_link = __import__("os").link

        def race_link(source, destination, **kwargs):
            Path(destination).write_bytes(b"another owner's file")
            return original_link(source, destination, **kwargs)

        with mock.patch("packages.library.download.os.link", side_effect=race_link):
            with self.assertRaises(FileExistsError):
                self.get()
        self.assertEqual((self.quota.data_root / "raw/sample.bin").read_bytes(), b"another owner's file")
        self.assertEqual((self.quota.data_root / "raw/sample.bin.part").read_bytes(), PAYLOAD)


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="library-quota-test-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_existing_partial_and_active_reservations_count_together(self):
        quota = quota_for(self.root, owner_limit_bytes=200_000)
        (quota.data_root / "existing.part").write_bytes(b"x" * 80_000)
        reservation = quota.reserve(60_000)
        snapshot = quota.snapshot()
        self.assertGreaterEqual(snapshot["owner_used_bytes"], 80_000)
        self.assertEqual(snapshot["active_reserved_bytes"], 60_000)
        with self.assertRaises(QuotaExceeded):
            quota.reserve(60_000)
        # A newly created manager does not infer that an old reservation is stale.
        reopened = quota_for(self.root, owner_limit_bytes=200_000)
        self.assertEqual(reopened.active_reservations()[0]["reservation_id"], reservation.reservation_id)
        reopened.release(reservation.reservation_id, reason="verified writer stopped")
        self.assertEqual(reopened.active_reservations(), [])
        self.assertTrue((quota.data_root / "existing.part").exists())

    def test_project_capacity_counts_other_owners(self):
        quota = quota_for(self.root, owner_limit_bytes=1_000_000, project_limit_bytes=200_000)
        other_owner = self.root / "models"
        other_owner.mkdir()
        (other_owner / "weights.bin").write_bytes(b"x" * 100_000)
        with self.assertRaises(QuotaExceeded):
            quota.reserve(100_000)

    def test_opaque_foreign_owner_uses_whole_allocation_and_reports_assumption(self):
        quota = quota_for(self.root)
        (self.root / "runtime").mkdir()
        from packages.library import storage
        scan = storage.directory_bytes

        def foreign_link_failure(path):
            if Path(path).name == "runtime":
                raise OSError(1920, "Windows cannot read a WSL runtime link")
            return scan(path)

        with mock.patch("packages.library.storage.directory_bytes", side_effect=foreign_link_failure):
            snapshot = quota.snapshot()
            self.assertEqual(snapshot["opaque_project_owners"], ["runtime"])
            self.assertEqual(snapshot["project_used_bytes"], snapshot["owner_used_bytes"] + 70_000_000_000)
            self.assertEqual(snapshot["project_accounting"]["runtime"]["mode"], "allocated_upper_bound")
            with quota.reserve(100_000):
                pass

    def test_unknown_project_directory_and_own_directory_still_fail_closed(self):
        quota = quota_for(self.root)
        (self.root / "unallocated").mkdir()
        from packages.library import storage
        scan = storage.directory_bytes
        for blocked in ("data", "unallocated"):
            def unreadable(path):
                if Path(path).name == blocked:
                    raise OSError(1920, "unreadable")
                return scan(path)

            with self.subTest(blocked=blocked), mock.patch("packages.library.storage.directory_bytes", side_effect=unreadable):
                with self.assertRaises(OSError):
                    quota.reserve(100_000)

    def test_physical_disk_free_and_safety_floor_are_enforced(self):
        quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=50_000)
        usage = shutil._ntuple_diskusage(total=1_000_000, used=900_000, free=100_000)
        with mock.patch("packages.library.storage.shutil.disk_usage", return_value=usage):
            with self.assertRaises(QuotaExceeded):
                quota.reserve(60_000)

    def test_path_traversal_devices_and_production_root_are_rejected(self):
        quota = quota_for(self.root)
        for path in ("../escape", "/absolute", "D:/outside", "x/../bad", "x//bad", "x/./bad", "x:file", "NUL.mp4", "CON/out", "trailing. /file", "file."):
            with self.subTest(path=path), self.assertRaises(UnsafePath):
                quota.resolve_path(path)
        with self.assertRaises(UnsafePath):
            QuotaManager(self.root / "outside" / "data")
        with self.assertRaises(ValueError):
            quota_for(self.root, owner_limit_bytes=300_000_000_001)

    def test_directory_symlink_or_windows_junction_is_rejected(self):
        quota = quota_for(self.root)
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "preserve.txt"
        marker.write_bytes(b"target contents must survive link cleanup")
        link = quota.data_root / "linked"
        try:
            if os.name == "nt":
                # Directory junctions exercise the Windows reparse-point guard
                # without requiring SeCreateSymbolicLinkPrivilege or admin.
                subprocess.run(
                    ["cmd", "/d", "/c", "mklink", "/J", str(link), str(outside)],
                    check=True, capture_output=True, text=True,
                )
                self.assertTrue(link.is_junction())
            else:
                link.symlink_to(outside, target_is_directory=True)
                self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), outside.resolve())
            with self.assertRaises(UnsafePath):
                quota.resolve_path("linked/file.bin")
            with self.assertRaises(UnsafePath):
                quota.reserve(1000)
        finally:
            # Remove only the verified link entry; never recurse through it.
            if getattr(link, "is_junction", lambda: False)():
                link.rmdir()
            elif link.is_symlink():
                link.unlink()
        self.assertEqual(marker.read_bytes(), b"target contents must survive link cleanup")

    def test_concurrent_process_reservations_cannot_overbook(self):
        # 300000 permits two 100000 reservations plus SQLite; never three.
        quota = quota_for(self.root, owner_limit_bytes=300_000)
        context = multiprocessing.get_context("spawn")
        ready, release, outcomes = context.Event(), context.Event(), context.Queue()
        processes = [context.Process(target=reserve_worker, args=(str(self.root), ready, release, outcomes)) for _ in range(4)]
        try:
            for process in processes:
                process.start()
            ready.set()
            results = [outcomes.get(timeout=25) for _ in processes]
            self.assertEqual([kind for kind, _ in results].count("reserved"), 2, results)
            self.assertEqual([kind for kind, _ in results].count("denied"), 2, results)
            self.assertEqual(len(quota.active_reservations()), 2)
            self.assertEqual(quota.snapshot()["active_reserved_bytes"], 200_000)
        finally:
            release.set()
            for process in processes:
                process.join(timeout=20)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        self.assertTrue(all(process.exitcode == 0 for process in processes))
        self.assertEqual(quota.active_reservations(), [])


if __name__ == "__main__":
    unittest.main()
