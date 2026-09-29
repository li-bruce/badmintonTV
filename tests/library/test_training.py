"""R-04b library publication assertions; temporary dummy files, never media QA."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from packages.library.manifest import build_asset, sha256_file
from packages.library.storage import QuotaExceeded, QuotaManager
from packages.library import training


class TypedFixture:
    """Test the validator boundary without pretending this is platform's schema."""
    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def model_dump(self, *, mode):
        assert mode == "json"
        return copy.deepcopy(self.value)


class TrainingTests(unittest.TestCase):
    version = "fine-badminton-2026-v1"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=0)
        self.registry = self.quota.resolve_path(training.REGISTRY_RELATIVE_PATH)
        self.manifest = self.quota.resolve_path(f"training/handoff/{self.version}.assets.v1.json")

    def source(self, name="one.bin", payload=b"dummy source for registry unit tests", match="match-01"):
        path = self.quota.resolve_path(f"training/{self.version}/raw/{name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        sha = sha256_file(path)
        return {"asset_id": "asset-" + sha, "sha256": sha,
                "relative_path": path.relative_to(self.root).as_posix(),
                "usage_scope": "training_only", "match_id": match,
                "provenance": {"usage_scope": "training_only", "source": "unit-test fixture"}}

    def asset(self, source=None):
        source = source or self.source()
        path = self.root / source["relative_path"]
        metadata = {"title": "Test fixture only", "match_id": source["match_id"],
                    "source_type": "synthetic", "source_url": None, "source_page": None,
                    "acquired_at": "2026-09-29T00:00:00Z", "camera_type": "unknown",
                    "discipline": "unknown", "players": [], "rights": {"status": "owned",
                    "license_url": None, "evidence": "Generated dummy unit-test bytes", "allowed_uses": ["testing"]},
                    "split": "unassigned", "provenance": source["provenance"]}
        probe = {"duration_ms": 1000, "width": 10, "height": 10, "fps_num": 30,
                 "fps_den": 1, "time_base": "1/30", "probe": {"decode": {"status": "passed"},
                 "source_sha256": source["sha256"], "source_size_bytes": path.stat().st_size}}
        asset = build_asset(path, metadata, probe, storage_root=self.root)
        return training.tag_training_asset(asset)

    def register(self, entries, **kwargs):
        return training.register_training_sources(entries, dataset_version=self.version,
                                                  quota=self.quota, **kwargs)

    def publish(self, assets, **kwargs):
        kwargs.setdefault("asset_validator", TypedFixture)
        return training.publish_training_manifest(assets, dataset_version=self.version,
                                                   quota=self.quota, **kwargs)

    def test_empty_initialization_and_empty_retry_never_drop_old_entries(self):
        initial = self.register([])
        self.assertEqual({"schema_version": "1.0", "assets": []}, initial["registry"])
        source = self.source()
        self.register([source])
        before = self.registry.read_bytes()
        self.register([])
        self.assertEqual(before, self.registry.read_bytes())
        self.assertEqual([], self.quota.active_reservations())

    def test_minimal_registry_verifies_bytes_without_requiring_probe(self):
        source = self.source()
        source.pop("match_id")
        source.pop("provenance")
        result = self.register([source])
        self.assertEqual(source["sha256"], result["registry"]["assets"][0]["sha256"])
        self.assertFalse(self.manifest.exists())
        self.assertNotIn("probe", result["registry"]["assets"][0])
        (self.root / source["relative_path"]).write_bytes(b"changed")
        old = self.registry.read_bytes()
        with self.assertRaises(training.TrainingError):
            self.register([source])
        self.assertEqual(old, self.registry.read_bytes())

    def test_same_sha_adds_aliases_without_changing_original_identity_or_scope(self):
        source = self.source()
        self.register([source])
        alias = self.source(name="alias.bin")
        alias["asset_id"] = "renamed-id"
        alias["provenance"]["source"] = "alias import evidence"
        self.register([alias])
        rows = json.loads(self.registry.read_text())["assets"]
        self.assertEqual(2, len(rows))
        row = rows[0]
        self.assertEqual(source["asset_id"], row["asset_id"])
        self.assertEqual(source["relative_path"], row["relative_path"])
        # This is the exact scalar-field indexing used by platform's helper.
        self.assertEqual({source["asset_id"], alias["asset_id"]}, {row["asset_id"] for row in rows})
        self.assertEqual({source["relative_path"], alias["relative_path"]}, {row["relative_path"] for row in rows})
        self.assertEqual({source["sha256"]}, {row["sha256"] for row in rows})
        self.assertTrue(all(row["usage_scope"] == "training_only" for row in rows))
        self.assertTrue(all("asset_ids" not in row and "relative_paths" not in row for row in rows))
        self.assertEqual(source["provenance"], rows[0]["provenance"])
        self.assertEqual(alias["provenance"], rows[1]["provenance"])

    def test_legacy_alias_arrays_become_scalar_rows_without_losing_restrictions(self):
        source = self.source()
        legacy = dict(source, asset_ids=[source["asset_id"], "legacy-id"],
                      relative_paths=[source["relative_path"], f"data/training/{self.version}/raw/legacy.bin"])
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps({"schema_version": "1.0", "assets": [legacy]}), encoding="utf-8")
        rows = self.register([])["registry"]["assets"]
        self.assertEqual(3, len(rows))
        self.assertEqual(set(legacy["asset_ids"]), {row["asset_id"] for row in rows})
        self.assertEqual(set(legacy["relative_paths"]), {row["relative_path"] for row in rows})
        self.assertTrue(all(row["provenance"] == source["provenance"] for row in rows))
        self.assertEqual(source["relative_path"], rows[0]["relative_path"])
        self.assertEqual(source["asset_id"], rows[0]["asset_id"])

    def test_repeated_scalar_identity_preserves_all_provenance(self):
        source = self.source()
        self.register([source])
        second = copy.deepcopy(source)
        second["provenance"]["source"] = "new supporting record"
        self.register([second])
        rows = json.loads(self.registry.read_text())["assets"]
        self.assertEqual(1, len(rows))
        self.assertEqual(source["provenance"], rows[0]["provenance"])
        self.assertEqual([second["provenance"]], rows[0]["provenance_history"])

    def test_one_bad_existing_row_rejects_whole_registry_without_pruning(self):
        source = self.source()
        state = {"schema_version": "1.0", "assets": [source, dict(source, asset_id="bad-id", usage_scope="general")]}
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps(state), encoding="utf-8")
        before = self.registry.read_bytes()
        with self.assertRaises(training.TrainingError):
            self.register([self.source("other.bin", b"other bytes", "match-02")])
        self.assertEqual(before, self.registry.read_bytes())

    def test_duplicate_json_keys_nonfinite_and_unknown_top_fields_fail_closed(self):
        bad_values = [b'{"schema_version":"1.0","assets":[],"assets":[]}',
                      b'{"schema_version":"1.0","assets":[],"extra":NaN}',
                      b'{"schema_version":"1.0","assets":[],"extra":Infinity}',
                      b'{"schema_version":"1.0","assets":[{"usage_scope":"general","usage_scope":"training_only"}]}',
                      b'{"schema_version":"1.0","assets":[],"extra":"unexpected"}']
        self.registry.parent.mkdir(parents=True)
        for raw in bad_values:
            self.registry.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(training.TrainingError):
                self.register([])
            self.assertEqual(raw, self.registry.read_bytes())

    def test_unknown_entry_json_fields_are_preserved_on_append(self):
        source = self.source()
        source["source_archive"] = {"sha256": "a" * 64, "metadata": [True, None, 3.5]}
        self.register([source])
        result = self.register([self.source("second.bin", b"second", "match-02")])
        self.assertEqual(source["source_archive"], result["registry"]["assets"][0]["source_archive"])

    def invalid_source_references(self, source):
        for container in ("provenance", "provenance_history"):
            for field, value in (("source_asset_id", 123), ("source_asset_id", ""),
                                 ("source_asset_id", " \t"), ("source_sha256", "not-a-sha256"),
                                 ("source_sha256", 123), ("source_sha256", "a" * 63),
                                 ("source_sha256", "a" * 65), ("source_sha256", "g" * 64)):
                item = copy.deepcopy(source)
                evidence = {"usage_scope": "training_only", field: value}
                item[container] = evidence if container == "provenance" else [evidence]
                yield container, field, value, item

    def test_bad_incoming_source_reference_never_replaces_valid_registry(self):
        source = self.source()
        self.register([source])
        before = self.registry.read_bytes()
        for container, field, value, bad in self.invalid_source_references(source):
            with self.subTest(container=container, field=field, value=value), self.assertRaises(training.TrainingError):
                self.register([bad])
            self.assertEqual(before, self.registry.read_bytes())

    def test_bad_existing_source_reference_rejects_all_rows_without_overwrite(self):
        source = self.source()
        self.registry.parent.mkdir(parents=True)
        for container, field, value, bad in self.invalid_source_references(source):
            state = {"schema_version": "1.0", "assets": [source, dict(bad, asset_id="bad-source-reference")]}
            self.registry.write_text(json.dumps(state), encoding="utf-8")
            before = self.registry.read_bytes()
            with self.subTest(container=container, field=field, value=value), self.assertRaises(training.TrainingError):
                self.register([])
            self.assertEqual(before, self.registry.read_bytes())

    def test_bad_full_asset_source_reference_cannot_initialize_registry_or_manifest(self):
        asset = self.asset()
        asset["provenance"]["source_sha256"] = "not-a-sha256"
        with self.assertRaises(training.TrainingError):
            self.publish([asset])
        self.assertFalse(self.registry.exists())
        self.assertFalse(self.manifest.exists())

    def test_nullable_and_valid_source_references_remain_contract_compatible(self):
        source = self.source()
        source["provenance"].update(source_asset_id=None, source_sha256=None)
        source["provenance_history"] = [
            {"source_asset_id": None, "source_sha256": None},
            {"source_asset_id": "original-source", "source_sha256": "Ab" * 32},
        ]
        rows = self.register([source])["registry"]["assets"]
        self.assertEqual(source["provenance"], rows[0]["provenance"])
        self.assertEqual(source["provenance_history"], rows[0]["provenance_history"])

    def test_absent_match_can_be_filled_but_explicit_match_cannot_change(self):
        source = self.source()
        early = dict(source)
        early.pop("match_id")
        self.register([early])
        self.publish([self.asset(source)])
        self.assertEqual("match-01", json.loads(self.registry.read_text())["assets"][0]["match_id"])
        with self.assertRaises(training.TrainingError):
            self.register([dict(source, match_id="different-match")])

    def test_append_does_not_require_old_files_and_never_forgets_their_sha(self):
        old = self.source()
        self.register([old])
        (self.root / old["relative_path"]).unlink()
        newer = self.source("new.bin", b"new bytes", "new-match")
        self.register([newer])
        rows = json.loads(self.registry.read_text())["assets"]
        self.assertEqual({old["sha256"], newer["sha256"]}, {row["sha256"] for row in rows})

    def test_downgrade_malformed_and_corrupt_existing_registry_fail_closed(self):
        source = self.source()
        for mutation in (lambda r: r["assets"][0].update(usage_scope="general"),
                         lambda r: r["assets"][0].update(provenance={"usage_scope": "general"}),
                         lambda r: r.update(schema_version="2.0"),
                         lambda r: r["assets"][0].update(relative_paths="bad")):
            state = {"schema_version": "1.0", "assets": [copy.deepcopy(source)]}
            mutation(state)
            self.registry.parent.mkdir(parents=True, exist_ok=True)
            self.registry.write_text(json.dumps(state), encoding="utf-8")
            before = self.registry.read_bytes()
            with self.assertRaises(training.TrainingError):
                self.register([])
            self.assertEqual(before, self.registry.read_bytes())
        self.registry.write_bytes(b"broken")
        with self.assertRaises(ValueError):
            self.register([])
        self.assertEqual(b"broken", self.registry.read_bytes())

    def test_id_and_path_cannot_be_rebound_to_another_hash(self):
        source = self.source()
        self.register([source])
        other = self.source("two.bin", b"different", "match-02")
        with self.assertRaises(training.TrainingError):
            self.register([dict(other, asset_id=source["asset_id"])])
        (self.root / source["relative_path"]).write_bytes(b"replacement")
        replacement = dict(source, sha256=sha256_file(self.root / source["relative_path"]), asset_id="new-id")
        with self.assertRaises(training.TrainingError):
            self.register([replacement])

    def test_safe_dataset_and_source_paths(self):
        source = self.source()
        for version in ("../escape", "handoff", "a/b", "a..b", "version.", "AUX.v1", "NUL", "COM1", ""):
            with self.subTest(version=version), self.assertRaises(training.TrainingError):
                training.register_training_sources([], dataset_version=version, quota=self.quota)
        for path in ("data/raw/a.mp4", "data/training/handoff/registry.json",
                     "data/training/other-version/a.mp4", "data/training/" + self.version + "/../outside"):
            with self.subTest(path=path), self.assertRaises((training.TrainingError, RuntimeError)):
                self.register([dict(source, relative_path=path)])

    def test_actual_dotted_dataset_version_is_preserved_and_accepted(self):
        version = "fine-badminton-2026-zenodo-20292976-v1.0"
        path = self.quota.resolve_path(f"training/{version}/source.bin")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"dotted-version fixture")
        sha = sha256_file(path)
        result = training.register_training_sources(
            [{"asset_id": "asset-" + sha, "sha256": sha, "relative_path": path.relative_to(self.root).as_posix(),
              "usage_scope": "training_only"}], dataset_version=version, quota=self.quota)
        self.assertEqual(path.relative_to(self.root).as_posix(), result["registry"]["assets"][0]["relative_path"])

    def test_tagger_copies_requires_unassigned_and_rejects_scope_conflicts(self):
        asset = self.asset()
        del asset["usage_scope"]
        del asset["provenance"]["usage_scope"]
        tagged = training.tag_training_asset(asset)
        self.assertNotIn("usage_scope", asset)
        self.assertNotIn("usage_scope", asset["provenance"])
        self.assertEqual("training_only", tagged["usage_scope"])
        for bad in (dict(asset, split="train"), dict(asset, usage_scope="general"),
                    dict(asset, provenance={"usage_scope": "general"})):
            with self.assertRaises(training.TrainingError):
                training.tag_training_asset(bad)

    def test_new_typed_validator_is_required_and_old_contract_cannot_drop_scope(self):
        asset = self.asset()
        def old_contract(value):
            value.pop("usage_scope")
            return value
        def change_identity(value):
            value["asset_id"] = "changed-by-validator"
            return value
        for callback in (None, lambda value: None, old_contract, change_identity):
            with self.subTest(callback=callback), self.assertRaises(training.TrainingError):
                self.publish([asset], asset_validator=callback)
            self.assertFalse(self.registry.exists())
            self.assertFalse(self.manifest.exists())

    def test_registry_is_durable_before_manifest_and_typed_values_survive(self):
        asset = self.asset()
        original_write = training.write_manifest
        def inspect_order(path, assets, **kwargs):
            registry = json.loads(self.registry.read_text())
            self.assertEqual(asset["sha256"], registry["assets"][0]["sha256"])
            self.assertEqual("training_only", registry["assets"][0]["usage_scope"])
            self.assertFalse(Path(path).exists())
            return original_write(path, assets, **kwargs)
        with patch.object(training, "write_manifest", side_effect=inspect_order):
            result = self.publish([asset])
        self.assertEqual(str(self.manifest), result["manifest_path"])
        final = result["manifest"]["assets"][0]
        self.assertEqual("training_only", final["usage_scope"])
        self.assertEqual("training_only", final["provenance"]["usage_scope"])
        self.assertEqual("unassigned", final["split"])
        self.assertEqual(sha256_file(self.registry), result["registry_sha256"])

    def test_manifest_failure_retains_restrictions_and_existing_manifest(self):
        first = self.asset()
        self.publish([first])
        before = self.manifest.read_bytes()
        second = self.asset(self.source("two.bin", b"second", "match-02"))
        with patch.object(training, "write_manifest", side_effect=OSError("injected publication failure")):
            with self.assertRaises(OSError):
                self.publish([second])
        self.assertEqual(before, self.manifest.read_bytes())
        self.assertEqual(2, len(json.loads(self.registry.read_text())["assets"]))
        self.assertEqual([], self.quota.active_reservations())
        audits = list(self.quota.resolve_path("training/handoff/audit").glob("*.completed.json"))
        self.assertTrue(any(json.loads(path.read_text())["state"] == "failed" for path in audits))
        self.assertFalse(self.quota.resolve_path("handoff/audit").exists())

    def test_same_hash_cannot_cross_match_in_early_or_full_publication(self):
        source = self.source()
        self.register([source])
        asset = self.asset(source)
        asset["match_id"] = "another-match"
        with self.assertRaises(training.TrainingError):
            self.publish([asset])
        self.assertFalse(self.manifest.exists())

    def test_budget_byte_limit_and_stale_lock_refuse_publication(self):
        source = self.source()
        with self.assertRaises(training.TrainingError):
            self.register([source], max_json_bytes=20)
        tiny_quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=0,
                                  owner_limit_bytes=100_000)
        with self.assertRaises(QuotaExceeded):
            training.register_training_sources([], dataset_version=self.version, quota=tiny_quota)
        self.assertFalse(self.registry.exists())
        lock = self.registry.with_name(self.registry.name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("99999", encoding="ascii")
        with self.assertRaises(training.TrainingError):
            self.register([], lock_timeout_seconds=0)
        self.assertTrue(lock.exists())

    def test_competing_writers_merge_without_losing_existing_source(self):
        first = self.source()
        second = self.source("two.bin", b"second", "match-02")
        barrier, errors = threading.Barrier(2), []
        def worker(source):
            try:
                barrier.wait(timeout=5)
                self.register([source])
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(source,)) for source in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual([], errors)
        self.assertEqual({first["sha256"], second["sha256"]},
                         {row["sha256"] for row in json.loads(self.registry.read_text())["assets"]})


if __name__ == "__main__":
    unittest.main()
