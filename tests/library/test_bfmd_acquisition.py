"""BFMD selection boundaries, using only the checked-in catalog and deep copies."""

import copy
from contextlib import ExitStack
import hashlib
import io
import inspect
import json
from pathlib import Path
import tempfile
import threading
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from packages.library.manifest import sha256_file
from packages.library.storage import QuotaManager
from scripts.library import acquire_bfmd_annotations as acquisition


class BfmdAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        cls.reviewed = json.loads((root / "configs/library/bfmd_sources.json").read_text(encoding="utf-8-sig"))

    def changed(self, **fields):
        config = copy.deepcopy(self.reviewed)
        config["files"][0].update(fields)
        return config

    def test_reviewed_annotation_and_archive_only_source_selection_is_accepted(self):
        sources = acquisition.validate_config(copy.deepcopy(self.reviewed))
        self.assertEqual(121, len(sources))
        self.assertEqual(1_825_439_459, sum(item["expected_bytes"] for item in sources))
        self.assertEqual(115, sum(Path(item["relative_path"]).suffix == ".json" for item in sources))
        self.assertEqual(1, sum(Path(item["relative_path"]).suffix == ".bak" for item in sources))

    def test_media_and_nonportable_paths_are_rejected(self):
        for path in ("match.mp4", "annotations/match.MKV", "../escape.json", "/absolute.json",
                     "annotations/../escape.json", "annotations\\file.json", "D:/source.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                acquisition.validate_config(self.changed(relative_path=path))

    def test_url_must_bind_the_selected_public_drive_id(self):
        for url in ("https://example.invalid/source.json", "http://drive.usercontent.google.com/uc",
                    self.reviewed["files"][0]["url"] + "&other=1", self.reviewed["files"][1]["url"]):
            with self.subTest(url=url), self.assertRaises(ValueError):
                acquisition.validate_config(self.changed(url=url))

    def test_media_kind_or_mime_is_rejected_even_under_json_filename(self):
        for fields in ({"kind": "media"}, {"mime_type": "video/mp4"},
                       {"kind": "media", "mime_type": "video/mp4"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                acquisition.validate_config(self.changed(**fields))

    def test_same_size_substitute_drive_id_and_matching_url_is_rejected(self):
        substituted = "unreviewedDriveFile123456789"
        changed = self.changed(google_drive_id=substituted,
                               url=f"https://drive.usercontent.google.com/uc?id={substituted}&export=download")
        self.assertEqual(self.reviewed["files"][0]["expected_bytes"], changed["files"][0]["expected_bytes"])
        with self.assertRaisesRegex(ValueError, "identities changed"):
            acquisition.validate_config(changed)

    def test_sizes_require_finite_integer_bound_and_exact_reviewed_total(self):
        for value in (False, 0, -1, 200_000_001, float("inf"),
                      self.reviewed["files"][0]["expected_bytes"] + 1):
            with self.subTest(size=value), self.assertRaises(ValueError):
                acquisition.validate_config(self.changed(expected_bytes=value))

    def test_duplicate_case_insensitive_paths_and_drive_ids_are_rejected(self):
        config = copy.deepcopy(self.reviewed)
        config["files"][1]["relative_path"] = config["files"][0]["relative_path"].upper()
        with self.assertRaises(ValueError):
            acquisition.validate_config(config)
        config = copy.deepcopy(self.reviewed)
        config["files"][1].update(google_drive_id=config["files"][0]["google_drive_id"],
                                  url=config["files"][0]["url"])
        with self.assertRaises(ValueError):
            acquisition.validate_config(config)

    def test_dataset_scope_revision_and_file_count_are_fixed(self):
        for key, value in (("schema_version", "2.0"), ("dataset_id", "other"),
                           ("usage_scope", "general"), ("repository_commit", "0" * 40)):
            config = copy.deepcopy(self.reviewed)
            config[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                acquisition.validate_config(config)
        config = copy.deepcopy(self.reviewed)
        config["files"].pop()
        with self.assertRaises(ValueError):
            acquisition.validate_config(config)


class BfmdResumeTests(unittest.TestCase):
    """Small real files/receipts/atomic writes; no Drive traffic or media."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=0)
        root = Path(__file__).resolve().parents[2]
        self.config = json.loads((root / "configs/library/bfmd_sources.json").read_text(encoding="utf-8-sig"))
        self.config["files"] = self.config["files"][:2]
        for index, item in enumerate(self.config["files"]):
            item.update(relative_path=f"annotations/sample-{index}.json", expected_bytes=len(self.payload(item)))
        selected = sorted([{key: item[key] for key in ("relative_path", "google_drive_id", "expected_bytes", "kind", "mime_type", "url")}
                           for item in self.config["files"]], key=lambda item: item["relative_path"])
        self.digest = hashlib.sha256(json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.handoff = self.quota.resolve_path(acquisition.HANDOFF_PATH)
        self.catalog = self.quota.resolve_path(acquisition.BASE + "/source-catalog.v1.json")
        self.progress = self.quota.resolve_path(acquisition.PROGRESS_PATH)

    def payload(self, item):
        return json.dumps({"fixture": item["google_drive_id"]}).encode()

    def fake_download(self, url, relative, **kwargs):
        item = next(item for item in self.config["files"] if item["url"] == url)
        path = self.quota.resolve_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.payload(item))
        receipt = path.with_name(path.name + ".download.json")
        receipt.write_text(json.dumps({"state": "succeeded", "url": url, "sha256": sha256_file(path),
                                       "size_bytes": path.stat().st_size, "completed_at": "2026-09-29T00:00:00Z"}), encoding="utf-8")
        return SimpleNamespace(path=path, metadata_path=receipt)

    def run_acquisition(self, *, config=None, writer=None, downloader=None, workers=1, opener=None):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(acquisition, "TOTAL_FILES", len(self.config["files"])))
            stack.enter_context(mock.patch.object(acquisition, "TOTAL_BYTES", sum(item["expected_bytes"] for item in self.config["files"])))
            stack.enter_context(mock.patch.object(acquisition, "REVIEWED_SELECTION_SHA256", self.digest))
            stack.enter_context(mock.patch.object(acquisition, "PEAK_BYTES", 5_000_000))
            stack.enter_context(mock.patch("builtins.print"))
            download = stack.enter_context(mock.patch.object(acquisition, "download", side_effect=downloader or self.fake_download))
            if writer:
                stack.enter_context(mock.patch.object(acquisition, "write_json", side_effect=writer))
            try:
                return acquisition.acquire_annotations(config or self.config, self.quota,
                                                       acquisition.MetadataBudget(limit=50_000_000),
                                                       response_opener=opener or object(), workers=workers)
            finally:
                self.download_calls = download.call_count

    def test_complete_handoff_keeps_both_records_when_cached_rerun_publish_interrupts(self):
        self.assertEqual(0, self.run_acquisition())
        prior = json.loads(self.handoff.read_text())
        real_write = acquisition.write_json
        def interrupt_after_first(path, *args, **kwargs):
            real_write(path, *args, **kwargs)
            if path == self.handoff:
                raise KeyboardInterrupt("unit-test interruption after cached verification")
        with self.assertRaises(KeyboardInterrupt):
            self.run_acquisition(writer=interrupt_after_first)
        final = json.loads(self.handoff.read_text())
        self.assertEqual(prior["files"], final["files"])
        self.assertTrue(final["complete"])
        progress = json.loads(self.progress.read_text())
        self.assertEqual("INTERRUPTED", progress["acquisition_status"])
        self.assertEqual(2, len(progress["files_attempted_this_run"]))
        self.assertEqual(0, progress["not_attempted_this_run"])
        self.assertEqual(0, self.download_calls)
        self.assertEqual([], self.quota.active_reservations())
        self.assertFalse(self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").exists())

    def test_partial_handoff_preserves_success_while_blocked_attempt_stays_in_progress_file(self):
        first = self.config["files"][0]["url"]
        def block_second(url, *args, **kwargs):
            if url == first:
                return self.fake_download(url, *args, **kwargs)
            raise acquisition.DownloadError("drive_access_denied", "test access denial")
        self.assertEqual(2, self.run_acquisition(downloader=block_second))
        final = json.loads(self.handoff.read_text())
        self.assertEqual(1, len(final["files"]))
        self.assertFalse(final["complete"])
        self.assertTrue(all(row["download_status"] != "failed" for row in final["files"]))
        progress = json.loads(self.progress.read_text())
        self.assertEqual("BLOCKED", progress["acquisition_status"])
        self.assertEqual("drive_access_denied", progress["blocked_reason"])
        self.assertEqual(2, len(progress["files_attempted_this_run"]))
        self.assertEqual(0, self.run_acquisition())
        self.assertEqual(2, len(json.loads(self.handoff.read_text())["files"]))

    def test_interrupt_during_cached_recheck_preserves_full_prior_handoff_bytes(self):
        self.assertEqual(0, self.run_acquisition())
        prior = self.handoff.read_bytes()
        real_one = acquisition._acquire_one
        cached_calls = []
        def stop_before_second(*args, **kwargs):
            cached_calls.append(True)
            if len(cached_calls) == 2:
                raise KeyboardInterrupt("interrupt after first cached recheck")
            return real_one(*args, **kwargs)
        with mock.patch.object(acquisition, "_acquire_one", side_effect=stop_before_second), self.assertRaises(KeyboardInterrupt):
            self.run_acquisition()
        self.assertEqual(prior, self.handoff.read_bytes())
        progress = json.loads(self.progress.read_text())
        self.assertEqual("INTERRUPTED", progress["acquisition_status"])
        self.assertEqual(1, len(progress["files_attempted_this_run"]))
        self.assertEqual(1, progress["not_attempted_this_run"])
        self.assertEqual(2, progress["verified_handoff_files"])
        self.assertEqual(0, self.download_calls)
        self.assertEqual([], self.quota.active_reservations())

    def test_cached_batch_rechecks_all_receipts_with_one_final_handoff_write(self):
        self.expand_to_four()
        self.assertEqual(0, self.run_acquisition())
        prior = json.loads(self.handoff.read_text())["files"]
        real_write, real_receipt = acquisition.write_json, acquisition._verified_receipt
        handoff_writes, receipts = [], []
        def writer(path, value, **kwargs):
            if path == self.handoff:
                handoff_writes.append(len(value["files"]))
            return real_write(path, value, **kwargs)
        def receipt(path, item):
            receipts.append(path)
            return real_receipt(path, item)
        with mock.patch.object(acquisition, "_verified_receipt", side_effect=receipt):
            self.assertEqual(0, self.run_acquisition(workers=2, writer=writer))
        self.assertEqual([4], handoff_writes)
        self.assertEqual(8, len(receipts))  # Prior snapshot validation plus current recheck.
        self.assertEqual(0, self.download_calls)
        self.assertEqual(prior, json.loads(self.handoff.read_text())["files"])

    def test_interrupted_active_download_is_counted_as_attempted_without_trusting_it(self):
        first = self.config["files"][0]["url"]
        def interrupt_second(url, *args, **kwargs):
            if url == first:
                return self.fake_download(url, *args, **kwargs)
            raise KeyboardInterrupt("simulated active download interruption")
        with self.assertRaises(KeyboardInterrupt):
            self.run_acquisition(downloader=interrupt_second)
        self.assertEqual(1, len(json.loads(self.handoff.read_text())["files"]))
        progress = json.loads(self.progress.read_text())
        self.assertEqual("INTERRUPTED", progress["acquisition_status"])
        self.assertEqual(0, progress["not_attempted_this_run"])
        self.assertEqual("interrupted", progress["files_attempted_this_run"][-1]["download_status"])
        self.assertEqual([], self.quota.active_reservations())

    def test_missing_or_changed_trusted_file_rejects_before_rewrite(self):
        self.run_acquisition()
        prior, catalog = self.handoff.read_bytes(), self.catalog.read_bytes()
        item = self.config["files"][0]
        path = self.quota.resolve_path(acquisition.BASE + "/raw/" + item["relative_path"])
        for changed in (False, True):
            if changed:
                path.write_bytes(b"x" * item["expected_bytes"])
            else:
                path.unlink()
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.run_acquisition()
            self.assertEqual(prior, self.handoff.read_bytes())
            self.assertEqual(catalog, self.catalog.read_bytes())
            self.assertEqual(0, self.download_calls)
            self.assertEqual([], self.quota.active_reservations())

    def expand_to_four(self):
        root = Path(__file__).resolve().parents[2]
        original = json.loads((root / "configs/library/bfmd_sources.json").read_text(encoding="utf-8-sig"))
        self.config["files"] = original["files"][:4]
        for index, item in enumerate(self.config["files"]):
            item.update(relative_path=f"annotations/sample-{index}.json", expected_bytes=len(self.payload(item)))
        selected = sorted([{key: item[key] for key in ("relative_path", "google_drive_id", "expected_bytes", "kind", "mime_type", "url")}
                           for item in self.config["files"]], key=lambda item: item["relative_path"])
        self.digest = hashlib.sha256(json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def test_two_real_downloads_resume_with_separate_receipts_and_owner_only_publication(self):
        """Real bounded core/SQLite/partials; the HTTP response alone is in memory."""
        real_download, real_write = acquisition.download, acquisition.write_json
        owner = threading.get_ident()
        barrier = threading.Barrier(2)
        observed, counts = [], []
        modified = "Tue, 29 Sep 2026 00:00:00 GMT"
        for item in self.config["files"]:
            path = self.quota.resolve_path(acquisition.BASE + "/raw/" + item["relative_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_name(path.name + ".part").write_bytes(self.payload(item)[:7])
            path.with_name(path.name + ".download.json").write_text(json.dumps({
                "schema_version": "1.0", "url": item["url"], "max_bytes": item["expected_bytes"],
                "expected_sha256": None, "validator_header": "Last-Modified", "validator": modified,
                "expected_total": item["expected_bytes"], "attempts": []}), encoding="utf-8")
        class Response(io.BytesIO):
            def __init__(inner, request):
                item = next(row for row in self.config["files"] if row["url"] == request.full_url)
                payload = self.payload(item)
                self.assertEqual("bytes=7-", request.get_header("Range"))
                self.assertEqual(modified, request.get_header("If-range"))
                self.assertNotEqual(owner, threading.get_ident())
                observed.append(threading.get_ident())
                self.assertGreaterEqual(len(self.quota.active_reservations()), 2)
                barrier.wait(timeout=5)
                super().__init__(payload[7:])
                inner.status, inner.url = 206, request.full_url
                inner.headers = {"Last-Modified": modified, "Content-Length": str(len(payload) - 7),
                                 "Content-Range": f"bytes 7-{len(payload)-1}/{len(payload)}"}
        def writer(path, value, **kwargs):
            self.assertEqual(owner, threading.get_ident())
            if path == self.handoff:
                counts.append(len(value["files"]))
            return real_write(path, value, **kwargs)
        self.assertEqual(0, self.run_acquisition(workers=2, downloader=real_download,
                                               opener=lambda request, **kwargs: Response(request), writer=writer))
        self.assertEqual(2, len(set(observed)))
        self.assertEqual(sorted(counts), counts)
        self.assertEqual(2, counts[-1])
        for item in self.config["files"]:
            path = self.quota.resolve_path(acquisition.BASE + "/raw/" + item["relative_path"])
            self.assertEqual(self.payload(item), path.read_bytes())
            receipt = json.loads(path.with_name(path.name + ".download.json").read_text())
            self.assertEqual(7, receipt["attempts"][-1]["resumed_bytes"])
            self.assertEqual("succeeded", receipt["state"])
            self.assertFalse(path.with_name(path.name + ".part").exists())
        self.assertEqual([], self.quota.active_reservations())

    def test_failure_stops_dispatch_preserves_prior_and_drains_other_active_success(self):
        self.expand_to_four()
        first_url = self.config["files"][0]["url"]
        def seed_one(url, relative, **kwargs):
            if url == first_url:
                return self.fake_download(url, relative, **kwargs)
            raise acquisition.DownloadError("size_limit", "fixture failure")
        self.assertEqual(1, self.run_acquisition(downloader=seed_one))
        prior = json.loads(self.handoff.read_text())["files"][0]
        barrier, failed_published = threading.Barrier(2), threading.Event()
        real_write = acquisition.write_json
        started = []
        failed_url = self.config["files"][1]["url"]
        failed_part = self.quota.resolve_path(acquisition.BASE + "/raw/" + self.config["files"][1]["relative_path"] + ".part")
        def downloader(url, relative, **kwargs):
            started.append(url)
            barrier.wait(timeout=5)
            if url == failed_url:
                failed_part.write_bytes(b"retained-partial")
                raise acquisition.DownloadError("drive_rate_limited", "fixture limit")
            self.assertTrue(failed_published.wait(timeout=5))
            self.assertTrue(self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").exists())
            return self.fake_download(url, relative, **kwargs)
        def writer(path, value, **kwargs):
            result = real_write(path, value, **kwargs)
            if path == self.progress and any(row["download_status"] == "failed" for row in value["files_attempted_this_run"]):
                failed_published.set()
            return result
        self.assertEqual(2, self.run_acquisition(workers=2, downloader=downloader, writer=writer))
        final = json.loads(self.handoff.read_text())
        self.assertEqual(2, len(final["files"]))
        self.assertIn(prior, final["files"])
        self.assertEqual(2, len(started))
        self.assertNotIn(self.config["files"][3]["url"], started)
        self.assertEqual(b"retained-partial", failed_part.read_bytes())
        self.assertEqual(1, json.loads(self.progress.read_text())["not_attempted_this_run"])
        self.assertEqual([], self.quota.active_reservations())

    def test_graceful_stop_drains_two_files_and_next_run_ignores_old_run_marker(self):
        self.expand_to_four()
        barrier = threading.Barrier(2)
        marker_ready = threading.Event()
        markers, started = [], []
        first_url = self.config["files"][0]["url"]
        def downloader(url, relative, **kwargs):
            started.append(url)
            barrier.wait(timeout=5)
            if url == first_url:
                markers.append(acquisition.request_stop(self.quota))
                marker_ready.set()
            else:
                self.assertTrue(marker_ready.wait(timeout=5))
            return self.fake_download(url, relative, **kwargs)
        self.assertEqual(3, self.run_acquisition(workers=2, downloader=downloader))
        self.assertEqual(2, len(started))
        self.assertEqual(2, len(json.loads(self.handoff.read_text())["files"]))
        self.assertEqual("STOPPED", json.loads(self.progress.read_text())["acquisition_status"])
        self.assertTrue(markers[0].is_file())
        self.assertEqual([], self.quota.active_reservations())
        self.assertEqual(0, self.run_acquisition(workers=2))
        self.assertEqual(4, len(json.loads(self.handoff.read_text())["files"]))
        self.assertTrue(markers[0].is_file())

    def test_owner_interrupt_drains_admitted_workers_before_releasing_lock(self):
        self.expand_to_four()
        barrier = threading.Barrier(2)
        real_wait = acquisition.wait
        calls, started = [], []
        def interrupt_once(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise KeyboardInterrupt("fixture owner interrupt")
            return real_wait(*args, **kwargs)
        def downloader(url, relative, **kwargs):
            started.append(url)
            barrier.wait(timeout=5)
            self.assertTrue(self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").exists())
            return self.fake_download(url, relative, **kwargs)
        with mock.patch.object(acquisition, "wait", side_effect=interrupt_once), self.assertRaises(KeyboardInterrupt):
            self.run_acquisition(workers=2, downloader=downloader)
        self.assertEqual(2, len(started))
        self.assertEqual(2, len(json.loads(self.handoff.read_text())["files"]))
        self.assertEqual("INTERRUPTED", json.loads(self.progress.read_text())["acquisition_status"])
        self.assertEqual([], self.quota.active_reservations())
        self.assertFalse(self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").exists())

    def test_publication_failure_stops_dispatch_but_drains_and_preserves_completed_receipts(self):
        self.expand_to_four()
        barrier, release_peer = threading.Barrier(2), threading.Event()
        started, writer_failures = [], []
        first_url = self.config["files"][0]["url"]
        real_write = acquisition.write_json
        def downloader(url, relative, **kwargs):
            started.append(url)
            barrier.wait(timeout=5)
            if url != first_url:
                self.assertTrue(release_peer.wait(timeout=5))
                self.assertTrue(self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").exists())
            return self.fake_download(url, relative, **kwargs)
        def writer(path, value, **kwargs):
            if path == self.handoff and not writer_failures:
                writer_failures.append(True)
                release_peer.set()
                raise OSError("fixture metadata publish failure")
            return real_write(path, value, **kwargs)
        with self.assertRaisesRegex(OSError, "metadata publish failure"):
            self.run_acquisition(workers=2, downloader=downloader, writer=writer)
        self.assertEqual(2, len(started))
        self.assertEqual(2, len(json.loads(self.handoff.read_text())["files"]))
        self.assertEqual("FAIL", json.loads(self.progress.read_text())["acquisition_status"])
        self.assertEqual([], self.quota.active_reservations())

    def test_interrupt_after_submit_before_future_registration_still_publishes_completion(self):
        self.expand_to_four()
        real_submit = acquisition.ThreadPoolExecutor.submit
        admitted, finished = [], []
        active = threading.Event()
        def interrupt_after_submit(pool, *args, **kwargs):
            future = real_submit(pool, *args, **kwargs)
            admitted.append(future)
            self.assertTrue(active.wait(timeout=5))
            raise KeyboardInterrupt("fixture interrupt after actual submit")
        def downloader(url, relative, **kwargs):
            active.set()
            self.assertTrue(self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").exists())
            result = self.fake_download(url, relative, **kwargs)
            finished.append(url)
            return result
        with mock.patch.object(acquisition.ThreadPoolExecutor, "submit", new=interrupt_after_submit), self.assertRaises(KeyboardInterrupt):
            self.run_acquisition(workers=2, downloader=downloader)
        self.assertEqual(1, len(admitted))
        self.assertTrue(admitted[0].done())
        self.assertEqual(1, len(finished))
        self.assertEqual(1, len(json.loads(self.handoff.read_text())["files"]))
        progress = json.loads(self.progress.read_text())
        self.assertEqual("INTERRUPTED", progress["acquisition_status"])
        self.assertEqual(1, len(progress["files_attempted_this_run"]))
        self.assertEqual(3, progress["not_attempted_this_run"])
        self.assertEqual([], self.quota.active_reservations())
        self.assertFalse(self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").exists())

    def test_failure_between_dispatch_check_and_worker_start_skips_unstarted_file(self):
        self.expand_to_four()
        real_submit = acquisition.ThreadPoolExecutor.submit
        release_failure, failed = threading.Event(), threading.Event()
        submitted, downloads = [], []
        def submit_after_peer_fails(pool, *args, **kwargs):
            submitted.append(args[1])
            if len(submitted) == 2:
                # Owner already passed its halt check. Release the first worker
                # and wait until _acquire_one records its fatal failure.
                release_failure.set()
                self.assertTrue(failed.wait(timeout=5))
            return real_submit(pool, *args, **kwargs)
        real_one = acquisition._acquire_one
        def observed_one(*args, **kwargs):
            result = real_one(*args, **kwargs)
            if result[1] is not None:
                failed.set()
            return result
        def downloader(url, relative, **kwargs):
            downloads.append(url)
            self.assertTrue(release_failure.wait(timeout=5))
            raise acquisition.DownloadError("drive_rate_limited", "fixture failure at dispatch boundary")
        with mock.patch.object(acquisition.ThreadPoolExecutor, "submit", new=submit_after_peer_fails), \
                mock.patch.object(acquisition, "_acquire_one", side_effect=observed_one):
            self.assertEqual(2, self.run_acquisition(workers=2, downloader=downloader))
        self.assertEqual(2, len(submitted))
        self.assertEqual(1, len(downloads))
        progress = json.loads(self.progress.read_text())
        self.assertEqual(1, len(progress["files_attempted_this_run"]))
        self.assertEqual(3, progress["not_attempted_this_run"])
        self.assertEqual([], self.quota.active_reservations())

    def test_stop_marker_between_dispatch_check_and_worker_start_skips_unstarted_file(self):
        self.expand_to_four()
        real_submit = acquisition.ThreadPoolExecutor.submit
        release_first, first_active = threading.Event(), threading.Event()
        submitted, downloads = [], []
        def stop_before_second_starts(pool, *args, **kwargs):
            submitted.append(args[1])
            if len(submitted) == 2:
                self.assertTrue(first_active.wait(timeout=5))
                acquisition.request_stop(self.quota)
                release_first.set()
            return real_submit(pool, *args, **kwargs)
        def downloader(url, relative, **kwargs):
            downloads.append(url)
            first_active.set()
            self.assertTrue(release_first.wait(timeout=5))
            return self.fake_download(url, relative, **kwargs)
        with mock.patch.object(acquisition.ThreadPoolExecutor, "submit", new=stop_before_second_starts):
            self.assertEqual(3, self.run_acquisition(workers=2, downloader=downloader))
        self.assertEqual(2, len(submitted))
        self.assertEqual(1, len(downloads))
        progress = json.loads(self.progress.read_text())
        self.assertEqual("STOPPED", progress["acquisition_status"])
        self.assertEqual(1, len(progress["files_attempted_this_run"]))
        self.assertEqual(3, progress["not_attempted_this_run"])
        self.assertEqual(1, len(json.loads(self.handoff.read_text())["files"]))
        self.assertEqual([], self.quota.active_reservations())

    @unittest.skipUnless(hasattr(threading.Thread, "_wait_for_tstate_lock"), "CPython join implementation differs")
    def test_repeated_interrupt_at_real_join_boundary_cannot_release_running_writer(self):
        """Inject the CPython 3.12 interrupted-join bug, not a mocked shutdown."""
        self.expand_to_four()
        join_code = threading.Thread._wait_for_tstate_lock.__code__
        lines, first_line = inspect.getsourcelines(threading.Thread._wait_for_tstate_lock)
        acquire_line = next(first_line + index for index, line in enumerate(lines)
                            if "if lock.acquire(block, timeout):" in line)
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        join_interrupted, owner_returned = threading.Event(), threading.Event()
        real_submit = acquisition.ThreadPoolExecutor.submit
        admitted, ownership_before_release = [], []
        def interrupt_after_submit(pool, *args, **kwargs):
            future = real_submit(pool, *args, **kwargs)
            admitted.append(future)
            self.assertTrue(started.wait(timeout=5))
            raise KeyboardInterrupt("first interrupt after admitted task")
        def downloader(url, relative, **kwargs):
            started.set()
            self.assertTrue(release.wait(timeout=5))
            result = self.fake_download(url, relative, **kwargs)
            finished.set()
            return result
        def release_after_observation():
            # Old code reaches join while this writer is blocked. New code
            # waits on its independent task counter, so join is reached later.
            if join_interrupted.wait(timeout=0.3):
                owner_returned.wait(timeout=1)
            ownership_before_release.append((self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").exists(),
                                             bool(self.quota.active_reservations()), finished.is_set()))
            release.set()
        helper = threading.Thread(target=release_after_observation)
        helper.start()
        original_trace = sys.gettrace()
        def trace(frame, event, arg):
            if (event == "line" and frame.f_code is join_code and frame.f_lineno == acquire_line
                    and not join_interrupted.is_set()):
                join_interrupted.set()
                raise KeyboardInterrupt("second interrupt at real Thread.join acquire boundary")
            return trace
        finished_at_owner_return = None
        try:
            sys.settrace(trace)
            with mock.patch.object(acquisition.ThreadPoolExecutor, "submit", new=interrupt_after_submit):
                with self.assertRaises(KeyboardInterrupt):
                    self.run_acquisition(workers=2, downloader=downloader)
            finished_at_owner_return = finished.is_set()
            owner_returned.set()
        finally:
            sys.settrace(original_trace)
            release.set()
            owner_returned.set()
            helper.join(timeout=5)
            for future in admitted:
                future.result(timeout=5)
        self.assertTrue(join_interrupted.is_set(), "Regression must execute the actual join boundary")
        self.assertTrue(finished_at_owner_return, "Owner returned while its file writer was still running")
        self.assertEqual([(True, True, False)], ownership_before_release)
        self.assertEqual(1, len(json.loads(self.handoff.read_text())["files"]))
        self.assertEqual(1, len(json.loads(self.progress.read_text())["files_attempted_this_run"]))
        self.assertEqual([], self.quota.active_reservations())

    def test_second_owner_and_invalid_workers_cannot_dispatch(self):
        for workers in (0, 3, True, 1.0):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                self.run_acquisition(workers=workers)
            self.assertEqual(0, self.download_calls)
        with acquisition._handoff_lock(self.quota, "a" * 32):
            before = self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").read_bytes()
            with self.assertRaises(FileExistsError):
                self.run_acquisition(workers=2)
            self.assertEqual(before, self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock").read_bytes())
            self.assertEqual(0, self.download_calls)
        self.assertEqual([], self.quota.active_reservations())

    def test_stop_control_refuses_legacy_owner_without_writing_marker(self):
        lock = self.quota.resolve_path(acquisition.HANDOFF_PATH + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("1234", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "does not support"):
            acquisition.request_stop(self.quota)
        self.assertFalse(self.quota.resolve_path(acquisition.BASE + "/control").exists())

    def test_config_or_old_source_identity_change_rejects_without_rewrite(self):
        self.run_acquisition()
        prior, catalog = self.handoff.read_bytes(), self.catalog.read_bytes()
        changed = copy.deepcopy(self.config)
        changed["source_page"] = "https://example.invalid/changed-evidence"
        with self.assertRaisesRegex(ValueError, "catalog differs"):
            self.run_acquisition(config=changed)
        self.assertEqual(prior, self.handoff.read_bytes())
        self.assertEqual(catalog, self.catalog.read_bytes())
        malformed = json.loads(prior)
        malformed["files"][1]["url"] = self.config["files"][0]["url"]
        self.handoff.write_text(json.dumps(malformed), encoding="utf-8")
        before = self.handoff.read_bytes()
        with self.assertRaisesRegex(ValueError, "fixed source/scope"):
            self.run_acquisition()
        self.assertEqual(before, self.handoff.read_bytes())
        self.assertEqual(0, self.download_calls)

    def test_trusted_file_cannot_be_redownloaded_or_rebound_after_preflight(self):
        self.run_acquisition()
        before = self.handoff.read_bytes()
        item = self.config["files"][0]
        relative = acquisition.BASE + "/raw/" + item["relative_path"]
        path = self.quota.resolve_path(relative)
        real_previous = acquisition._previous_verified
        for changed in (False, True):
            self.fake_download(item["url"], relative)
            def change_after_validation(*args):
                verified = real_previous(*args)
                if changed:
                    path.write_bytes(b"x" * item["expected_bytes"])
                    receipt_path = path.with_name(path.name + ".download.json")
                    receipt = json.loads(receipt_path.read_text())
                    receipt["sha256"] = sha256_file(path)
                    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                else:
                    path.unlink()
                return verified
            with self.subTest(changed=changed), mock.patch.object(acquisition, "_previous_verified", side_effect=change_after_validation):
                with self.assertRaisesRegex(ValueError, "after preflight"):
                    self.run_acquisition()
            self.assertEqual(before, self.handoff.read_bytes())
            self.assertEqual(0, self.download_calls)
            self.assertEqual([], self.quota.active_reservations())


if __name__ == "__main__":
    unittest.main()
