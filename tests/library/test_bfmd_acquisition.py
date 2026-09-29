"""BFMD selection boundaries, using only the checked-in catalog and deep copies."""

import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
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

    def run_acquisition(self, *, config=None, writer=None, downloader=None):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(acquisition, "TOTAL_FILES", 2))
            stack.enter_context(mock.patch.object(acquisition, "TOTAL_BYTES", sum(item["expected_bytes"] for item in self.config["files"])))
            stack.enter_context(mock.patch.object(acquisition, "REVIEWED_SELECTION_SHA256", self.digest))
            stack.enter_context(mock.patch.object(acquisition, "PEAK_BYTES", 5_000_000))
            stack.enter_context(mock.patch("builtins.print"))
            download = stack.enter_context(mock.patch.object(acquisition, "download", side_effect=downloader or self.fake_download))
            if writer:
                stack.enter_context(mock.patch.object(acquisition, "write_json", side_effect=writer))
            try:
                return acquisition.acquire_annotations(config or self.config, self.quota,
                                                       acquisition.MetadataBudget(limit=50_000_000), response_opener=object())
            finally:
                self.download_calls = download.call_count

    def test_complete_handoff_keeps_both_records_when_rerun_interrupts_after_first(self):
        self.assertEqual(0, self.run_acquisition())
        prior = json.loads(self.handoff.read_text())
        real_write = acquisition.write_json
        def interrupt_after_first(path, *args, **kwargs):
            real_write(path, *args, **kwargs)
            if path == self.handoff:
                raise KeyboardInterrupt("unit-test interruption after first cached item")
        with self.assertRaises(KeyboardInterrupt):
            self.run_acquisition(writer=interrupt_after_first)
        final = json.loads(self.handoff.read_text())
        self.assertEqual(prior["files"], final["files"])
        self.assertTrue(final["complete"])
        progress = json.loads(self.progress.read_text())
        self.assertEqual("INTERRUPTED", progress["acquisition_status"])
        self.assertEqual(1, len(progress["files_attempted_this_run"]))
        self.assertEqual(1, progress["not_attempted_this_run"])
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
