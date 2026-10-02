"""Synthetic engineering fixtures, never evidence of real media/annotation QA."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from packages.contracts import AssetManifest
from packages.library import annotation_catalog as catalog
from packages.library.manifest import ManifestError
from packages.library.storage import QuotaExceeded, QuotaManager, UnsafePath


class AnnotationCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=0)
        self.assets, self.sources = [], []
        self.rows = [["10", "10", "smash", "left"], ["10", "10", "smash", "left"],
                     ["2", "4", "杀球", ""], ["bad", "?", "unknown", "line\nbreak"]]
        for member in ("README.md", "LICENSE"):
            self.sources.append(self.source(member, member, b"Synthetic rights fixture, not a real license.\n"))
        self.add_asset(1)
        self.registry = {"schema_version": "1.0", "assets": []}
        self.splits = {"schema_version": "1.0", "sha256": {}, "matches": {}}
        self.bfmd = {"schema_version": "1.0", "usage_scope": "training_only",
                     "video_alignment": "unmatched", "assets_created": 0, "media_files_downloaded": 0,
                     "rights": {"status": "unresolved"}}
        self.register_assets()
        self.flush_inputs()

    def write(self, relative, raw):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"relative_path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}

    def source(self, basename, member, raw):
        return {**self.write(f"{catalog.BASE}/extracted/{basename}", raw),
                "member_name": member, "usage_scope": "training_only"}

    def csv_bytes(self, rows=None):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["start", "end", "label", "location"])
        writer.writerows(self.rows if rows is None else rows)
        return stream.getvalue().encode("utf-8")

    def pts_bytes(self, rows):
        return b"".join((json.dumps(row, separators=(",", ":")) + "\n").encode() for row in rows)

    def add_asset(self, number):
        member = f"Synthetic match！{number}"
        media = self.source(f"media-{number}.mp4", f"videos/{member}.mp4",
                            f"dummy media bytes {number}; no real decode was performed".encode())
        annotation = self.source(f"annotation-{number}.csv", f"annotations/{member}_dataframe.csv", self.csv_bytes())
        self.sources.extend((media, annotation))
        pts = self.write(f"{catalog.BASE}/probes/media-{number}.pts.jsonl", self.pts_bytes([
            {"frame_index": i, "pts": 9000 + i * 3600} for i in range(4)]))
        pts.update(format="jsonl", complete=True, frame_count=4, time_base="1/90000",
                   pts_field="best_effort_timestamp", vfr_status="cfr_observed",
                   min_delta_ticks=3600, max_delta_ticks=3600)
        asset = {"schema_version": "1.0", "asset_id": "asset-" + media["sha256"],
                 "sha256": media["sha256"], "relative_path": media["relative_path"],
                 "size_bytes": media["size_bytes"], "duration_ms": 200, "width": 32, "height": 18,
                 "fps_num": 25, "fps_den": 1, "time_base": "1/90000", "title": "Original synthetic title",
                 "match_id": f"publisher-clip-{number}", "source_type": "synthetic", "usage_scope": "training_only",
                 "source_url": None, "source_page": "https://example.invalid/synthetic-fixture",
                 "acquired_at": "2026-10-02T00:00:00Z", "camera_type": "unknown", "discipline": "unknown",
                 "players": [], "rights": {"status": "research_only", "license_url": None,
                   "evidence": "Synthetic policy fixture only", "allowed_uses": ["testing"]}, "split": "unassigned",
                 "probe": {"start_pts": 9000, "vfr_status": "cfr_observed", "pts_index": pts,
                   "source_sha256": media["sha256"], "source_size_bytes": media["size_bytes"],
                   "decode": {"status": "passed", "scope": "full_video_stream", "exit_code": 0, "frames": 4}},
                 "provenance": {"usage_scope": "training_only", "dataset_id": catalog.DATASET,
                   "archive_member": f"videos/Synthetic matchúí{number}.mp4",
                   "fixture_metadata": {"nested": [None, True, 1.5, "原始值"]}}}
        self.assets.append(asset)
        return asset

    def register_assets(self):
        self.registry["assets"] = [{key: copy.deepcopy(asset[key]) for key in
            ("asset_id", "sha256", "relative_path", "size_bytes", "match_id", "usage_scope", "provenance")}
            for asset in self.assets]
        self.splits["sha256"] = {asset["sha256"]: asset["match_id"] for asset in self.assets}
        self.splits["matches"] = {asset["match_id"]: "unassigned" for asset in self.assets}

    def flush_inputs(self):
        values = {"manifest": {"schema_version": "1.0", "assets": self.assets}, "registry": self.registry,
                  "splits": self.splits, "extracted": {"schema_version": "1.0", "complete": True, "sources": self.sources},
                  "bfmd": self.bfmd}
        self.config = {"schema_version": catalog.CONFIG_SCHEMA, "dataset_id": catalog.DATASET,
                       "output": catalog.OUTPUT, "peak_bytes": catalog.PEAK_BYTES,
                       "inputs": {key: self.write(catalog.INPUT_PATHS[key], catalog.encode_json(value))
                                  for key, value in values.items()}}

    def bundle(self):
        return catalog.build_bundle(self.root, self.config)

    def details(self, bundle):
        ref = bundle["manifest"]["assets"][0]["provenance"]["annotation_catalog"]
        return json.loads(bundle["sidecars"][ref["relative_path"]])

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file()}

    def assert_released(self):
        self.assertEqual([], self.quota.active_reservations())
        self.assertFalse((self.root / (catalog.OUTPUT + ".lock")).exists())
        self.assertEqual([], list(self.root.rglob("catalog-*.tmp")))

    def test_multiple_assets_preserve_exact_source_snapshots_and_canonical_pairing(self):
        self.add_asset(2)
        self.register_assets()
        self.flush_inputs()
        before = self.snapshot()
        bundle = self.bundle()
        self.assertEqual(before, self.snapshot(), "Building must not write files or registry state")
        self.assertEqual(bundle, self.bundle(), "Identical source snapshots must produce deterministic bytes")
        AssetManifest.model_validate(bundle["manifest"])
        details = self.details(bundle)
        self.assertEqual(2, details["summary"]["asset_count"])
        originals = {asset["asset_id"]: asset for asset in self.assets}
        for entry in details["assets"]:
            self.assertEqual(originals[entry["asset_id"]], entry["source_asset"])
            self.assertIn("match！", entry["canonical_archive_member"])
            self.assertIn("matchúí", entry["source_asset"]["provenance"]["archive_member"])
            self.assertFalse(entry["training_truth_eligible"])
            self.assertFalse(entry["match_group"]["independent_match_confirmed"])
            self.assertIsNone(entry["match_group"]["confirmed_group_id"])
        for output in bundle["manifest"]["assets"]:
            original = copy.deepcopy(output)
            original["provenance"].pop("annotation_catalog")
            self.assertEqual(originals[output["asset_id"]], original)

    def test_raw_csv_duplicates_zero_length_and_order_remain_unreviewed_hints(self):
        bundle = self.bundle()
        details = self.details(bundle)
        ref = details["assets"][0]["raw_annotations"]
        hints = json.loads(bundle["sidecars"][ref["relative_path"]])
        self.assertEqual(self.rows, [list(row["raw"].get(k) for k in ("start", "end", "label", "location"))
                                    for row in hints["rows"]])
        self.assertEqual([1, 2, 3, 4], [row["source_record"] for row in hints["rows"]])
        self.assertEqual(4, len({row["row_id"] for row in hints["rows"]}))
        self.assertEqual(1, hints["diagnostics"]["exact_duplicate_preserved"])
        self.assertEqual(2, hints["diagnostics"]["equal_endpoints_semantics_unverified"])
        self.assertEqual(1, hints["diagnostics"]["out_of_order_start_preserved"])
        for row in hints["rows"]:
            self.assertEqual({"row_id", "source_record", "source_line_end", "raw", "diagnostics"}, set(row))
            self.assertFalse({"start_ms", "end_ms", "event", "human_confirmed", "labels"} & row.keys())
        semantics = hints["semantics"]
        self.assertEqual("unreviewed", semantics["review_status"])
        self.assertIsNone(semantics["reviewer_type"])
        self.assertFalse(semantics["human_confirmed"])
        self.assertFalse(semantics["training_truth_eligible"])
        self.assertFalse(semantics["unknown_is_negative"])
        self.assertIsNone(semantics["time_semantics"]["source_broadcast_offset_ms"])
        self.assertEqual("unverified", semantics["time_semantics"]["frame_base"])
        self.assertEqual("unknown", semantics["fine_hand_technique"])
        self.assertEqual(0, details["summary"]["human_confirmed_annotations"])
        self.assertEqual(0, details["excluded_collections"][0]["playable_assets"])

    def test_original_video_same_size_hash_tamper_is_rejected(self):
        path = self.root / self.assets[0]["relative_path"]
        path.write_bytes(b"x" * path.stat().st_size)
        with self.assertRaisesRegex(catalog.CatalogError, "video size/hash"):
            self.bundle()

    def test_pts_hash_tamper_is_rejected_without_repinning(self):
        index = self.assets[0]["probe"]["pts_index"]
        path = self.root / index["relative_path"]
        path.write_bytes(path.read_bytes().replace(b"19800", b"19801"))
        with self.assertRaisesRegex(catalog.CatalogError, "PTS count/hash"):
            self.bundle()

    def test_rehashed_pts_still_rejects_nonincreasing_or_wrong_frame_order(self):
        index = self.assets[0]["probe"]["pts_index"]
        for pts, indices in (([9000, 16200, 12600, 19800], range(4)),
                             ([9000, 12600, 12600, 19800], range(4)),
                             ([9000, 12600, 16200, 19800], [0, 2, 1, 3])):
            with self.subTest(pts=pts, indices=list(indices)):
                index.update(self.write(index["relative_path"], self.pts_bytes([
                    {"frame_index": i, "pts": p} for i, p in zip(indices, pts)])))
                self.flush_inputs()
                with self.assertRaisesRegex(catalog.CatalogError, "strictly increasing|frame order"):
                    self.bundle()

    def test_decode_count_and_pts_origin_must_match(self):
        probe = self.assets[0]["probe"]
        for key, value in (("decode", {"status": "passed", "scope": "full_video_stream", "exit_code": 0, "frames": 3}),
                           ("start_pts", 0)):
            original = copy.deepcopy(probe[key])
            with self.subTest(key=key):
                probe[key] = value
                self.flush_inputs()
                with self.assertRaises(catalog.CatalogError):
                    self.bundle()
                probe[key] = original

    def test_one_tick_quantization_remains_unknown_instead_of_asserting_cfr_or_vfr(self):
        probe = self.assets[0]["probe"]
        index = probe["pts_index"]
        index.update(self.write(index["relative_path"], self.pts_bytes([
            {"frame_index": i, "pts": pts} for i, pts in enumerate([9000, 12600, 16201, 19801])])))
        index.update(vfr_status="unknown", min_delta_ticks=3600, max_delta_ticks=3601)
        probe["vfr_status"] = "unknown"
        self.flush_inputs()
        bundle = self.bundle()
        entry = self.details(bundle)["assets"][0]
        self.assertEqual({"3600": 2, "3601": 1}, entry["pts_verification"]["delta_ticks_counts"])
        self.assertEqual("unknown", entry["source_asset"]["probe"]["vfr_status"])
        self.assertEqual("unknown", bundle["manifest"]["assets"][0]["probe"]["pts_index"]["vfr_status"])
        for claimed in ("cfr_observed", "vfr_observed"):
            probe["vfr_status"] = index["vfr_status"] = claimed
            self.flush_inputs()
            with self.subTest(claimed=claimed), self.assertRaisesRegex(catalog.CatalogError, "VFR evidence"):
                self.bundle()

    def test_valid_same_sha_registry_alias_does_not_replace_the_selected_source_identity(self):
        original = copy.deepcopy(self.assets[0])
        alias = copy.deepcopy(self.registry["assets"][0])
        alias["asset_id"] = "synthetic-alias-id"
        alias["relative_path"] = f"{catalog.BASE}/extracted/same-bytes-alias.mp4"
        alias["provenance"]["alias_note"] = "Same bytes are not another independent match"
        self.write(alias["relative_path"], (self.root / original["relative_path"]).read_bytes())
        self.registry["assets"].insert(0, alias)
        self.flush_inputs()
        registry_path = self.root / catalog.INPUT_PATHS["registry"]
        before = (registry_path.read_bytes(), registry_path.stat().st_mtime_ns)
        bundle = self.bundle()
        self.assertEqual(1, bundle["summary"]["asset_count"])
        self.assertEqual(original, self.details(bundle)["assets"][0]["source_asset"])
        self.assertEqual("published", catalog.publish_catalog(self.quota, self.config)["status"])
        self.assertEqual("verified", catalog.verify_catalog(self.root, self.config)["status"])
        self.assertEqual(before, (registry_path.read_bytes(), registry_path.stat().st_mtime_ns))
        self.assertEqual(2, len(json.loads(registry_path.read_bytes())["assets"]))
        self.assert_released()

    def test_unregistered_or_non_training_registry_and_assigned_split_are_rejected(self):
        original_registry, original_splits = copy.deepcopy(self.registry), copy.deepcopy(self.splits)
        for alteration in ("missing", "registry_scope", "provenance_scope", "split"):
            self.registry, self.splits = copy.deepcopy(original_registry), copy.deepcopy(original_splits)
            if alteration == "missing":
                self.registry["assets"] = []
            elif alteration == "registry_scope":
                self.registry["assets"][0]["usage_scope"] = "general"
            elif alteration == "provenance_scope":
                self.registry["assets"][0]["provenance"]["usage_scope"] = "general"
            else:
                self.splits["matches"][self.assets[0]["match_id"]] = "train"
            self.flush_inputs()
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                self.bundle()

    def test_asset_scope_dataset_and_unassigned_requirement_cannot_be_relaxed(self):
        original = copy.deepcopy(self.assets[0])
        for alteration in ("typed_scope", "provenance_scope", "dataset", "split"):
            self.assets[0] = copy.deepcopy(original)
            if alteration == "typed_scope":
                self.assets[0]["usage_scope"] = "general"
            elif alteration == "provenance_scope":
                self.assets[0]["provenance"]["usage_scope"] = "general"
            elif alteration == "dataset":
                self.assets[0]["provenance"]["dataset_id"] = "another-dataset"
            else:
                self.assets[0]["split"] = "train"
            self.flush_inputs()
            with self.subTest(alteration=alteration), self.assertRaises(catalog.CatalogError):
                self.bundle()

    def test_unsafe_source_paths_are_rejected_before_file_access(self):
        original = self.sources[0]["relative_path"]
        for relative in (f"{catalog.BASE}/extracted/../README.md", f"{catalog.BASE}/extracted/NUL.txt",
                         f"{catalog.BASE}/extracted/README.md:stream", f"{catalog.BASE}/extracted/README.md.",
                         "../README.md", "C:/README.md", "/README.md", "data\\README.md"):
            self.sources[0]["relative_path"] = relative
            self.flush_inputs()
            with self.subTest(relative=relative), self.assertRaises((ValueError, UnsafePath)):
                self.bundle()
        self.sources[0]["relative_path"] = original

    def test_changed_pinned_inputs_and_referenced_csv_or_rights_bytes_fail_closed(self):
        paths = [self.root / self.config["inputs"]["registry"]["relative_path"]]
        paths.extend(self.root / source["relative_path"] for source in self.sources
                     if source["member_name"] in {"README.md", "LICENSE"} or source["member_name"].endswith(".csv"))
        for path in paths:
            raw = path.read_bytes()
            path.write_bytes(b"x" * len(raw))
            with self.subTest(name=path.name), self.assertRaisesRegex(catalog.CatalogError, "SHA256"):
                self.bundle()
            path.write_bytes(raw)

    def test_csv_pairing_requires_exact_canonical_member(self):
        csv_source = next(source for source in self.sources if source["member_name"].endswith(".csv"))
        csv_source["member_name"] = csv_source["member_name"].replace("！", "úí")
        self.flush_inputs()
        with self.assertRaisesRegex(catalog.CatalogError, "exact canonical"):
            self.bundle()

    def test_publish_idempotence_and_verify_are_read_only(self):
        source_files = self.snapshot()
        result = catalog.publish_catalog(self.quota, self.config)
        self.assertEqual("published", result["status"])
        self.assert_released()
        published = {name: value for name, value in self.snapshot().items() if not name.endswith(".sqlite3")}
        result = catalog.publish_catalog(self.quota, self.config)
        self.assertEqual("unchanged", result["status"])
        self.assertEqual(0, result["metadata_bytes_written"])
        self.assertEqual(published, {name: value for name, value in self.snapshot().items() if not name.endswith(".sqlite3")})
        for name, value in source_files.items():
            if not name.endswith(".sqlite3"):
                self.assertEqual(value, self.snapshot()[name])
        before = self.snapshot()
        with patch.object(catalog, "_write_atomic", side_effect=AssertionError("verify attempted a write")):
            verified = catalog.verify_catalog(self.root, self.config)
        self.assertEqual("verified", verified["status"])
        self.assertTrue(verified["originals_rehashed"])
        self.assertEqual("NOT_RUN", verified["browser_playback"])
        self.assertEqual(before, self.snapshot(), "verify must not modify even quota/registry metadata")

    def test_conflicting_immutable_sidecar_does_not_replace_old_catalog(self):
        catalog.publish_catalog(self.quota, self.config)
        output = self.root / catalog.OUTPUT
        old = output.read_bytes()
        self.assets[0]["title"] = "New candidate source snapshot"
        self.flush_inputs()
        bundle = self.bundle()
        relative = next(name for name in bundle["sidecars"] if name.endswith(".details.json"))
        conflict = self.root / relative
        conflict.write_bytes(b"preexisting conflicting bytes")
        with self.assertRaisesRegex(catalog.CatalogError, "Immutable sidecar conflict"):
            catalog.publish_catalog(self.quota, self.config)
        self.assertEqual(old, output.read_bytes())
        self.assertEqual(b"preexisting conflicting bytes", conflict.read_bytes())
        self.assert_released()

    def test_sidecar_write_failure_keeps_previous_manifest_and_registry(self):
        catalog.publish_catalog(self.quota, self.config)
        output = self.root / catalog.OUTPUT
        old = output.read_bytes()
        self.assets[0]["title"] = "Next snapshot"
        self.flush_inputs()
        registry_before = (self.root / catalog.INPUT_PATHS["registry"]).read_bytes()
        real_write = catalog._write_atomic
        def fail_details(path, raw, *, immutable=False):
            if path.name.endswith(".details.json"):
                raise OSError("injected sidecar failure")
            return real_write(path, raw, immutable=immutable)
        with patch.object(catalog, "_write_atomic", side_effect=fail_details), self.assertRaisesRegex(OSError, "sidecar failure"):
            catalog.publish_catalog(self.quota, self.config)
        self.assertEqual(old, output.read_bytes())
        self.assertEqual(registry_before, (self.root / catalog.INPUT_PATHS["registry"]).read_bytes())
        self.assert_released()

    def test_final_atomic_replace_failure_keeps_previous_manifest(self):
        catalog.publish_catalog(self.quota, self.config)
        output = self.root / catalog.OUTPUT
        old = output.read_bytes()
        self.assets[0]["title"] = "Next snapshot"
        self.flush_inputs()
        with patch.object(catalog.os, "replace", side_effect=OSError("injected final replace failure")), \
             self.assertRaisesRegex(OSError, "final replace failure"):
            catalog.publish_catalog(self.quota, self.config)
        self.assertEqual(old, output.read_bytes())
        completed = list((self.root / "data/training/handoff/audit").glob("*.completed.json"))
        self.assertEqual(1, len(completed))
        self.assertEqual("failed", json.loads(completed[0].read_bytes())["state"])
        self.assert_released()

    def test_post_commit_audit_failure_returns_warning_and_keeps_both_verified_generations(self):
        catalog.publish_catalog(self.quota, self.config)
        output = self.root / catalog.OUTPUT
        for error_type in (OSError, ValueError):
            old = output.read_bytes()
            old_generation = self.root / f"{catalog.SIDECARS}/{hashlib.sha256(old).hexdigest()}.manifest.json"
            old_generation_state = (old_generation.read_bytes(), old_generation.stat().st_mtime_ns)
            self.assets[0]["title"] = "Post-commit audit warning " + error_type.__name__
            self.flush_inputs()
            @contextmanager
            def fail_completed_audit(*args, **kwargs):
                yield
                raise error_type("injected completed audit write failure")
            with self.subTest(error=error_type.__name__), patch.object(catalog, "publication_audit", fail_completed_audit):
                result = catalog.publish_catalog(self.quota, self.config)
            self.assertEqual("published_with_audit_warning", result["status"])
            self.assertTrue(result["warnings"])
            self.assertIn("injected completed audit write failure", str(result["warnings"]))
            self.assertNotEqual(old, output.read_bytes())
            self.assertEqual("verified", catalog.verify_catalog(self.root, self.config)["status"])
            self.assertEqual(old_generation_state, (old_generation.read_bytes(), old_generation.stat().st_mtime_ns))
            self.assert_released()
        self.assertEqual("unchanged", catalog.publish_catalog(self.quota, self.config)["status"])

    def test_audit_failure_before_commit_still_raises_and_preserves_old_entry(self):
        catalog.publish_catalog(self.quota, self.config)
        output = self.root / catalog.OUTPUT
        old = output.read_bytes()
        self.assets[0]["title"] = "Candidate blocked before commit"
        self.flush_inputs()
        @contextmanager
        def fail_started_audit(*args, **kwargs):
            raise OSError("injected started audit write failure")
            yield  # Keep the injected failure at context entry, before the replace.
        with patch.object(catalog, "publication_audit", fail_started_audit), \
             self.assertRaisesRegex(OSError, "started audit write failure"):
            catalog.publish_catalog(self.quota, self.config)
        self.assertEqual(old, output.read_bytes())
        self.assert_released()

    def test_existing_owner_lock_and_insufficient_quota_prevent_publication(self):
        output = self.root / catalog.OUTPUT
        lock = output.with_name(output.name + ".lock")
        lock.write_bytes(b"do not remove this owner")
        with self.assertRaises(ManifestError):
            catalog.publish_catalog(self.quota, self.config)
        self.assertEqual(b"do not remove this owner", lock.read_bytes())
        self.assertFalse(output.exists())
        self.assertEqual([], self.quota.active_reservations())
        lock.unlink()
        self.quota.owner_limit_bytes = catalog.PEAK_BYTES - 1
        with self.assertRaises(QuotaExceeded):
            catalog.publish_catalog(self.quota, self.config)
        self.assertFalse(output.exists())
        self.assert_released()

    def test_verify_detects_sidecar_and_catalog_tampering_without_repair(self):
        catalog.publish_catalog(self.quota, self.config)
        bundle = self.bundle()
        generation = f"{catalog.SIDECARS}/{hashlib.sha256(catalog.encode_json(bundle['manifest'])).hexdigest()}.manifest.json"
        for relative in (catalog.OUTPUT, next(iter(bundle["sidecars"])), generation):
            target = self.root / relative
            original = target.read_bytes()
            target.write_bytes(b"x" * len(original))
            before = self.snapshot()
            with self.subTest(relative=relative), self.assertRaises(catalog.CatalogError):
                catalog.verify_catalog(self.root, self.config)
            self.assertEqual(before, self.snapshot(), "Failed verify must also stay read-only")
            target.write_bytes(original)

    def test_competing_publisher_cannot_replace_or_remove_active_owner_lock(self):
        admitted, release = threading.Event(), threading.Event()
        real_build = catalog.build_bundle
        def held_build(root, config):
            admitted.set()
            if not release.wait(timeout=5):
                raise AssertionError("Publisher was not released by the test")
            return real_build(root, config)
        with patch.object(catalog, "build_bundle", side_effect=held_build), ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(catalog.publish_catalog, self.quota, self.config)
            try:
                self.assertTrue(admitted.wait(timeout=5))
                lock = self.root / (catalog.OUTPUT + ".lock")
                owner_bytes = lock.read_bytes()
                with self.assertRaises(ManifestError):
                    catalog.publish_catalog(self.quota, self.config)
                self.assertEqual(owner_bytes, lock.read_bytes())
                self.assertFalse((self.root / catalog.OUTPUT).exists())
            finally:
                release.set()
            self.assertEqual("published", first.result(timeout=5)["status"])
        self.assertEqual("verified", catalog.verify_catalog(self.root, self.config)["status"])
        self.assert_released()

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_oversize(self):
        path = self.root / "strict.json"
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'\xff'):
            path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(catalog.CatalogError):
                catalog.load_json(path)
        path.write_bytes(b"[1,2,3]")
        with self.assertRaises(catalog.CatalogError):
            catalog.load_json(path, max_bytes=2)


if __name__ == "__main__":
    unittest.main()
