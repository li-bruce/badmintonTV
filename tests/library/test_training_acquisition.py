"""Training acquisition receipt boundaries; no network or large package I/O."""

import copy
from concurrent.futures import Future
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from packages.library import training
from packages.library.manifest import build_asset, sha256_file
from packages.library.storage import QuotaManager
from scripts.library import acquire_training_dataset as acquisition


class TrainingAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.archive = mock.Mock(spec=Path)
        self.archive.stat.return_value = SimpleNamespace(st_size=acquisition.ZIP_BYTES)
        self.quota = mock.Mock(spec=QuotaManager)
        self.quota.resolve_path.side_effect = lambda value: (
            self.archive if value.endswith("/Fine-Badminton.zip") else Path("unused-acquisition.json")
        )

    def report(self):
        return {
            "schema_version": "1.0", "dataset_id": acquisition.DATASET,
            "usage_scope": "training_only", "source_url": acquisition.CONTENT_URL,
            "archive_relative_path": "data/" + acquisition.BASE + "/source/Fine-Badminton.zip",
            "sha256": "a" * 64, "status": "passed", "size_bytes": acquisition.ZIP_BYTES,
            "publisher_md5": acquisition.PUBLISHER_MD5, "actual_md5": acquisition.PUBLISHER_MD5,
        }

    def verify(self, report):
        with mock.patch.object(acquisition, "read_json_bounded", return_value=report):
            return acquisition.verified_acquisition(self.quota)

    def test_complete_publisher_receipt_preserves_required_sha_binding(self):
        report = self.report()
        archive, checked = self.verify(report)
        self.assertIs(archive, self.archive)
        self.assertIs(checked, report)
        self.assertEqual(checked["sha256"], "a" * 64)
        self.archive.open.assert_not_called()

    def test_null_missing_or_invalid_sha_never_disables_archive_verification(self):
        for value in (None, "", "a" * 63, "a" * 65, "g" * 64, "A" * 64, 123):
            with self.subTest(sha=value), self.assertRaises(ValueError):
                self.verify(dict(self.report(), sha256=value))
        report = self.report()
        del report["sha256"]
        with self.assertRaises(ValueError):
            self.verify(report)

    def test_report_schema_dataset_usage_and_source_must_match_exact_training_package(self):
        conflicts = {
            "schema_version": "2.0", "dataset_id": "another-dataset", "usage_scope": "general",
            "source_url": "https://example.invalid/replacement.zip",
            "archive_relative_path": "data/handoff/Fine-Badminton.zip",
        }
        for key, value in conflicts.items():
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.verify(dict(self.report(), **{key: value}))
            missing = self.report()
            del missing[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.verify(missing)
        with self.assertRaises(ValueError):
            self.verify([])

    def test_failed_or_conflicting_publisher_md5_and_sizes_are_rejected(self):
        for key, value in (
            ("status", "failed"), ("publisher_md5", "0" * 32),
            ("actual_md5", "0" * 32), ("size_bytes", acquisition.ZIP_BYTES - 1),
        ):
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.verify(dict(self.report(), **{key: value}))
        self.archive.stat.return_value = SimpleNamespace(st_size=acquisition.ZIP_BYTES - 1)
        with self.assertRaises(ValueError):
            self.verify(self.report())

    def test_publisher_long_and_unicode_titles_have_short_paths_including_sidecars(self):
        members = [
            "2011 OSIM BWF World Superseries Finals-MS-MS - Group A-Chong Wei Lee vs. Peter Hoeg Gade.mp4",
            "[4K50FPS] BEST MS MATCH！Lin Dan vs Lee Chong Wei _ 2011 World Championships.mp4",
            "README.md", "README", "LICENSE",
        ]
        suffixes = ("", ".lock", ".extract.part", ".extract.json",
                    ".extract.json.tmp." + "f" * 32, ".download.json.tmp." + "f" * 32)
        for member in members:
            relative = acquisition.extracted_relative_path(member)
            with self.subTest(member=member):
                self.assertTrue(relative.startswith(acquisition.BASE + "/extracted/"))
                self.assertRegex(Path(relative).name, r"^[0-9a-f]{24}\.[a-z0-9]{1,10}$")
                self.assertEqual(Path(member).suffix.lower() or ".bin", Path(relative).suffix)
                for suffix in suffixes:
                    full = "D:\\video\\data\\" + relative.replace("/", "\\") + suffix
                    self.assertLess(len(full), 260, full)

    def test_short_member_paths_are_stable_and_distinct_for_distinct_original_names(self):
        members = ["one/match.mp4", "two/match.mp4", "one/MATCH.mp4", "one/match.csv",
                   "one/羽毛球.mp4", "two/羽毛球.mp4", "README", "LICENSE"]
        paths = [acquisition.extracted_relative_path(member) for member in members]
        self.assertEqual(len(members), len(set(paths)))
        self.assertEqual(paths, [acquisition.extracted_relative_path(member) for member in members])


class TypedProbeFixture:
    """Exercise the callback boundary; actual contract integration is separate."""
    model_fields = {"usage_scope": object()}

    def __init__(self, value):
        self.value = copy.deepcopy(value)

    @classmethod
    def model_validate(cls, value):
        return cls(value)

    def model_dump(self, *, mode):
        assert mode == "json"
        return copy.deepcopy(self.value)


class DeterministicExecutor:
    """Run bounded fake work now, then expose futures in the chosen test order."""
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except BaseException as error:
            future.set_exception(error)
        return future


class ProbeManifestResumeTests(unittest.TestCase):
    """Real temporary JSON/bytes and publisher; cached decode reports are fixtures."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=0)
        self.manifest = self.quota.resolve_path(f"training/handoff/{acquisition.DATASET}.assets.v1.json")
        self.items, self.assets, self.report_paths = [], [], []
        for index in range(10):
            source = self.quota.resolve_path(f"{acquisition.BASE}/extracted/{index}.mp4")
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(f"Dummy bytes {index}; not playable media".encode())
            digest = sha256_file(source)
            item = {"member_name": source.name, "sha256": digest, "relative_path": source.relative_to(self.root).as_posix(),
                    "title": f"Fixture {index}", "match_id": f"match-{index}", "players": [],
                    "identity_basis": "unit test", "provenance": {"usage_scope": "training_only"}}
            report = {"duration_ms": 1000, "width": 10, "height": 10, "fps_num": 30, "fps_den": 1,
                      "time_base": "1/30", "probe": {"decode": {"status": "passed", "frames": 30},
                      "source_sha256": digest, "source_size_bytes": source.stat().st_size}}
            report_path = self.quota.resolve_path(f"{acquisition.BASE}/probes/{digest}.probe.json")
            self.save(report_path, report)
            metadata = {**{key: item[key] for key in ("title", "match_id", "players", "provenance")},
                        "usage_scope": "training_only", "source_type": "synthetic", "source_url": None,
                        "source_page": None, "acquired_at": "2026-09-29T00:00:00Z", "camera_type": "unknown",
                        "discipline": "unknown", "split": "unassigned",
                        "rights": {"status": "owned", "license_url": None, "evidence": "Dummy unit-test bytes", "allowed_uses": ["testing"]}}
            self.items.append(item)
            self.assets.append(build_asset(source, metadata, report, storage_root=self.root))
            self.report_paths.append(report_path)
        self.save(self.quota.resolve_path(f"{acquisition.BASE}/extracted-sources.v1.json"),
                  {"complete": True, "sources": self.items})
        self.save(self.quota.resolve_path(f"{acquisition.BASE}/source/Fine-Badminton.zip.download.json"),
                  {"completed_at": "2026-09-29T00:00:00Z"})
        self.publications = []

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def prior(self, indexes):
        self.save(self.manifest, {"schema_version": "1.0", "assets": [self.assets[i] for i in indexes]})

    def run_probe(self, order, *, error=None):
        contracts = ModuleType("packages.contracts")
        contracts.Asset = TypedProbeFixture
        real_publish = training.publish_training_manifest
        def capture(assets, **kwargs):
            result = real_publish(assets, **kwargs)
            self.publications.append({asset["sha256"] for asset in result["manifest"]["assets"]})
            return result
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict("sys.modules", {"packages.contracts": contracts}))
            stack.enter_context(mock.patch.object(acquisition, "ROOT", self.root))
            stack.enter_context(mock.patch.object(acquisition, "verified_acquisition", return_value=(None, {"sha256": "a" * 64})))
            stack.enter_context(mock.patch.object(acquisition, "announce"))
            stack.enter_context(mock.patch.object(acquisition, "ThreadPoolExecutor", DeterministicExecutor))
            stack.enter_context(mock.patch.object(acquisition, "as_completed", side_effect=lambda futures: (futures[i] for i in order)))
            stack.enter_context(mock.patch.object(training, "publish_training_manifest", side_effect=capture))
            probe = stack.enter_context(mock.patch.object(acquisition, "probe_video", side_effect=error or AssertionError("Unexpected media probing")))
            try:
                return acquisition.probe_dataset({"source_page": "https://example.invalid/fixture", "source_claims": {}},
                                                 self.quota, acquisition.MetadataBudget(), ffprobe="unused", ffmpeg="unused", workers=2)
            finally:
                self.probe_calls = probe.call_count

    def test_complete_prior_manifest_never_shrinks_when_cache_finishes_out_of_order(self):
        self.prior(range(10))
        assets = self.run_probe([9, 2, 7, 0, 8, 1, 6, 3, 5, 4])
        expected = {item["sha256"] for item in self.items}
        self.assertEqual([expected] * 10, self.publications)
        self.assertEqual(expected, {asset["sha256"] for asset in assets})
        self.assertEqual(0, self.probe_calls)
        self.assertEqual([], self.quota.active_reservations())

    def test_partial_prior_and_new_completed_asset_survive_later_worker_failure(self):
        self.prior([0, 1])
        self.report_paths[8].unlink()
        with self.assertRaisesRegex(RuntimeError, "injected worker failure"):
            self.run_probe([9, 1, 8, 0, 2, 3, 4, 5, 6, 7], error=RuntimeError("injected worker failure"))
        expected = {self.items[i]["sha256"] for i in (0, 1, 9)}
        self.assertEqual([expected, expected], self.publications)
        saved = json.loads(self.manifest.read_text())
        self.assertEqual(expected, {asset["sha256"] for asset in saved["assets"]})
        self.assertEqual([], self.quota.active_reservations())
        self.assertFalse(self.quota.resolve_path(f"{acquisition.BASE}/probe-summary.v1.json").exists())

    def test_invalid_prior_manifest_is_preserved_before_any_probe_or_publication(self):
        self.prior([0, 1])
        invalid = json.loads(self.manifest.read_text())
        invalid["assets"][1]["usage_scope"] = "general"
        self.save(self.manifest, invalid)
        before = self.manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, "conflicting scope"):
            self.run_probe(range(10))
        self.assertEqual(before, self.manifest.read_bytes())
        self.assertEqual([], self.publications)
        self.assertEqual(0, self.probe_calls)
        self.assertEqual([], self.quota.active_reservations())

    def test_probe_failure_cancels_work_that_has_not_started(self):
        self.prior([0, 1])
        before = self.manifest.read_bytes()
        futures = [Future() for _ in range(10)]
        futures[0].set_exception(RuntimeError("early failure"))
        with mock.patch.object(DeterministicExecutor, "submit", side_effect=futures):
            with self.assertRaisesRegex(RuntimeError, "early failure"):
                self.run_probe(range(10))
        self.assertTrue(all(future.cancelled() for future in futures[1:]))
        self.assertEqual(before, self.manifest.read_bytes())
        self.assertEqual([], self.publications)
        self.assertEqual([], self.quota.active_reservations())


if __name__ == "__main__":
    unittest.main()
