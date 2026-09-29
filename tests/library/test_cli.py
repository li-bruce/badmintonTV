"""Bounds, publication ownership and acquisition recovery; all media are fixtures."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from packages.library import cli
from packages.library.manifest import ManifestError, SplitRegistry, build_asset, sha256_file
from packages.library.storage import QuotaManager
from scripts.library import acquire_small_sample as sample


CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs/library/small_sample.json"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=0)
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def invoke_cli(self, argv):
        with patch.object(cli, "QuotaManager", return_value=self.quota), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(argv)

    def test_cli_manifest_rejects_other_owner_raw_and_registry(self):
        input_path = self.root / "input.json"
        input_path.write_text('{"schema_version":"1.0","assets":[]}', encoding="utf-8")
        for output in ("raw/original.mp4", "handoff/splits.v1.json", "../models/wrong.json",
                       str(self.root / "models" / "wrong.json"), "handoff/subdir/wrong.json"):
            with self.subTest(output=output):
                self.assertEqual(1, self.invoke_cli(["manifest", str(input_path), output]))
        self.assertEqual([], self.quota.active_reservations())
        self.assertFalse((self.root / "models").exists())

    def test_manifest_cli_reserves_and_audits_snapshot_regeneration(self):
        input_path = self.root / "input.json"
        input_path.write_text('{"schema_version":"1.0","assets":[]}', encoding="utf-8")
        target = self.quota.data_root / "handoff" / "assets.json"
        for _ in range(2):
            self.assertEqual(0, self.invoke_cli(["manifest", str(input_path), "handoff/assets.json"]))
        self.assertEqual({"schema_version": "1.0", "assets": []}, json.loads(target.read_text()))
        audit_files = list((target.parent / "audit").glob("*.json"))
        self.assertEqual(2, len(audit_files))
        completed = next(json.loads(path.read_text()) for path in audit_files if "completed" in path.name)
        self.assertEqual("succeeded", completed["state"])
        self.assertEqual(sha256_file(target), completed["after"][0]["sha256"])
        self.assertEqual([], self.quota.active_reservations())

    def test_training_json_regeneration_keeps_audits_in_training_subtree(self):
        target = self.quota.resolve_path("training/dataset-v1/acquisition.json")
        budget = sample.MetadataBudget()
        with self.quota.reserve(1_000_000, purpose="training audit test"):
            sample.write_json(target, {"revision": 1}, quota=self.quota, budget=budget)
            self.assertFalse((self.quota.data_root / "training/handoff/audit").exists())
            sample.write_json(target, {"revision": 2}, quota=self.quota, budget=budget)
        audit_files = list((self.quota.data_root / "training/handoff/audit").glob("*.json"))
        self.assertEqual(2, len(audit_files))
        completed = next(json.loads(path.read_text()) for path in audit_files if "completed" in path.name)
        self.assertEqual("succeeded", completed["state"])
        self.assertEqual("data/training/dataset-v1/acquisition.json", completed["after"][0]["relative_path"])
        self.assertEqual(sha256_file(target), completed["after"][0]["sha256"])
        self.assertFalse((self.quota.data_root / "handoff").exists())
        self.assertEqual([], self.quota.active_reservations())

    def test_training_publication_failure_record_stays_with_training(self):
        target = self.quota.resolve_path("training/handoff/registry.json")
        target.parent.mkdir(parents=True)
        target.write_text("before", encoding="utf-8")
        with self.quota.reserve(1_000_000, purpose="failed training audit test"):
            with self.assertRaisesRegex(RuntimeError, "publication failed"):
                with cli.publication_audit([target], self.quota, reason="test failed publication"):
                    raise RuntimeError("publication failed")
        audits = list((self.quota.data_root / "training/handoff/audit").glob("*.completed.json"))
        self.assertEqual(1, len(audits))
        completed = json.loads(audits[0].read_text())
        self.assertEqual("failed", completed["state"])
        self.assertEqual(completed["before"], completed["after"])
        self.assertFalse((self.quota.data_root / "handoff").exists())

    def test_mixed_audit_batch_is_rejected_before_first_or_repeat_publication(self):
        training = self.quota.resolve_path("training/dataset-v1/report.json")
        ordinary = self.quota.resolve_path("handoff/report.json")
        for existing in (False, True):
            if existing:
                for target in (training, ordinary):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"original")
            with self.subTest(existing=existing), self.assertRaisesRegex(ValueError, "cannot mix"):
                with cli.publication_audit([training, ordinary], self.quota, reason="invalid mixed batch"):
                    self.fail("Mixed publication body must never run")
            self.assertFalse((self.quota.data_root / "handoff/audit").exists())
            self.assertFalse((self.quota.data_root / "training/handoff/audit").exists())
            if existing:
                self.assertEqual(training.read_bytes(), b"original")
                self.assertEqual(ordinary.read_bytes(), b"original")

    def test_training_audit_retains_record_byte_bound_before_mutation(self):
        target = self.quota.resolve_path("training/dataset-v1/report.json")
        target.parent.mkdir(parents=True)
        target.write_bytes(b"original")
        with patch.object(cli, "AUDIT_MAX_BYTES", 16), self.assertRaisesRegex(ValueError, "bounded allowance"):
            with cli.publication_audit([target], self.quota, reason="bounded training audit"):
                self.fail("Over-budget publication body must never run")
        self.assertEqual(target.read_bytes(), b"original")
        self.assertFalse((self.quota.data_root / "handoff").exists())
        self.assertFalse((self.quota.data_root / "training/handoff/audit").exists())

    def test_bounded_input_rejects_before_output_or_reservation(self):
        target = self.root / "big.json"
        target.write_bytes(b" " * 30)
        with self.assertRaises(ValueError):
            cli.read_json_bounded(target, max_bytes=20)

    def test_config_rejects_traversal_changed_pins_and_underreservation(self):
        mutations = [lambda c: c.update(batch_peak_bytes=1),
                     lambda c: c.update(hf_revision="main"),
                     lambda c: c["videos"][0].update(video_uid="../models/escape"),
                     lambda c: c["videos"][0].update(sha256="0" * 64),
                     lambda c: c["qa_files"].append("../../escape.json"),
                     lambda c: c["videos"][0].update(visual_observation={"discipline": "football"}),
                     lambda c: c["videos"][0].update(visual_observation={"still_relative_path": "data/../models/a.jpg"})]
        for mutate in mutations:
            config = copy.deepcopy(self.config)
            mutate(config)
            with self.assertRaises(ValueError):
                sample.validate_config(config)
        sample.validate_config(self.config)

    def test_bounded_writer_preserves_existing_when_budget_or_cap_fails(self):
        target = self.quota.resolve_path("handoff/example.json")
        target.parent.mkdir()
        target.write_bytes(b"previous")
        for budget in (sample.MetadataBudget(1), sample.MetadataBudget(1000)):
            with patch.object(sample, "MAX_JSON_BYTES", 20), self.assertRaises(ValueError):
                sample.write_json(target, {"large": "x" * 30}, quota=self.quota, budget=budget)
            self.assertEqual(b"previous", target.read_bytes())
        self.assertEqual([], list(target.parent.glob("*.tmp")))

    def test_split_registry_byte_bound_preserves_old_snapshot(self):
        path = self.quota.resolve_path("handoff/splits.v1.json")
        path.parent.mkdir()
        registry = SplitRegistry(path, max_bytes=100)
        registry.register_many([])
        original = path.read_bytes()
        with self.assertRaises(ManifestError):
            registry.register({"sha256": "a" * 64, "match_id": "long-match", "split": "train"})
        self.assertEqual(original, path.read_bytes())

    def test_orphan_pts_preserved_then_report_reused_with_original_acquired_time(self):
        config = copy.deepcopy(self.config)
        config["videos"] = [copy.deepcopy(config["videos"][0])]
        payload = b"test-only dummy bytes"
        digest = hashlib.sha256(payload).hexdigest()
        config["videos"][0].update(size_bytes=len(payload), sha256=digest)
        config["qa_files"] = [config["qa_files"][0]]
        config["shuttleset_files"] = ["LICENSE"]
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        original_time = "2026-09-28T01:02:03+00:00"
        uid = config["videos"][0]["video_uid"]
        orphan = self.quota.resolve_path("probes/" + uid + ".pts.jsonl")
        orphan.parent.mkdir()
        orphan.write_bytes(b"preserved orphan")

        def download(url, relative, **kwargs):
            path = self.quota.resolve_path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            content = payload if path.suffix == ".mp4" else (b"[]" if path.suffix == ".json" else b"source fixture")
            path.write_bytes(content)
            sha = sha256_file(path)
            receipt_path = path.with_name(path.name + ".download.json")
            receipt_path.write_text(json.dumps({"url": url, "state": "succeeded", "sha256": sha,
                                               "completed_at": original_time}), encoding="utf-8")
            return SimpleNamespace(size_bytes=len(content), sha256=sha)

        def probe(path, *, pts_index_path, **kwargs):
            self.assertNotEqual(orphan, pts_index_path)
            pts_index_path.write_bytes(b'{"frame_index":0,"pts":0}\n')
            return {"duration_ms": 1000, "width": 640, "height": 360, "fps_num": 30,
                    "fps_den": 1, "time_base": "1/30", "probe": {"decode": {"status": "passed"},
                    "source_sha256": digest, "source_size_bytes": len(payload), "vfr_status": "unknown",
                    "pts_index": {"relative_path": pts_index_path.relative_to(self.root).as_posix(),
                                  "sha256": sha256_file(pts_index_path), "size_bytes": pts_index_path.stat().st_size}}}

        with patch.object(sample, "ROOT", self.root), patch.object(sample, "DATA", self.quota.data_root), \
             patch.object(sample, "QuotaManager", return_value=self.quota), \
             patch.object(sample, "validate_config", side_effect=lambda value: value), \
             patch.object(sample, "download", side_effect=download) as downloads, \
             patch.object(sample, "probe_video", side_effect=probe) as probes, \
             patch("sys.argv", ["sample", "--config", str(config_path)]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, sample.main())
            download_count = downloads.call_count
            first = json.loads((self.quota.data_root / "handoff/assets.v1.json").read_text())
            self.assertEqual(0, sample.main())
            self.assertEqual(download_count, downloads.call_count)
            self.assertEqual(1, probes.call_count)
        second = json.loads((self.quota.data_root / "handoff/assets.v1.json").read_text())
        self.assertEqual(first, second)
        asset = second["assets"][0]
        self.assertEqual(original_time, asset["acquired_at"])
        self.assertEqual([], asset["players"])
        self.assertEqual("rear", asset["camera_type"])
        self.assertEqual("unconfirmed", asset["provenance"]["visual_observation"]["identity_status"])
        self.assertIn("recovery", asset["probe"])
        self.assertEqual(b"preserved orphan", orphan.read_bytes())
        self.assertEqual([], self.quota.active_reservations())


if __name__ == "__main__":
    unittest.main()
