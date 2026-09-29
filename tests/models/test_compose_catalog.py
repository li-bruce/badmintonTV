"""CPU metadata/evidence guards using explicit synthetic fixtures, no inference."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from packages import contracts
from scripts.models import compose_catalog as catalog


def snapshots():
    result = {}
    versions = {"torch": "2.8.0+cu128", "torchvision": "0.23.0+cu128", "transformers": "4.57.3", "qwen-vl-utils": "0.0.14", "ultralytics": "8.3.203"}
    for owner, ids in catalog.OWNERS.items():
        observation = {"environment_id": owner, "prefix": catalog.PREFIXES[owner], "base_prefix": catalog.PREFIXES[owner],
                       "platform": "linux", "storage_root": "/mnt/d/video", "no_user_site": True,
                       "python": "3.11.16", "executable": catalog.PREFIXES[owner] + "/bin/python",
                       "checked_at": "2026-09-29T00:00:00+00:00", "check_method": "SYNTHETIC CPU FIXTURE",
                       "source_files": [{"relative_path": "fixture.py", "sha256": "a" * 64, "size_bytes": 1}],
                       "distributions": {k: {"version": v, "location": "synthetic"} for k, v in versions.items()}}
        cards = [{"schema_version": "1.0", "model_id": mid, "version": "0.1.0", "display_name": "fixture " + mid,
                  "capabilities": [], "status": "experimental", "reason": "fixture only",
                  "environment": copy.deepcopy(observation), "evaluation_report": "fixture-not-real-evidence"} for mid in ids]
        result[owner] = {"schema_version": "1.0", "environment_id": owner, "observation": observation, "models": cards}
    return result


def fixture_attempt(root, model_id="yolo11n-pose-bytetrack"):
    attempt = "platform/jobs/job-fixture/attempt-1"
    directory = root / attempt
    directory.mkdir(parents=True)
    request = {"schema_version": "1.0", "job_id": "job-fixture", "attempt_id": "attempt-1", "operation": "analyze",
               "assets": [], "parameters": {"model_id": model_id, "model_version": "0.1.0"},
               "output_dir": "models/jobs/job-fixture/attempt-1"}
    producer = {"module": "models", "model_id": model_id, "version": "0.1.0", "job_id": "job-fixture", "attempt_id": "attempt-1"}
    payload = {"fixture_only": True, "producer": producer}
    artifact_path = "models/jobs/job-fixture/attempt-1/report.json"
    path = root / artifact_path
    path.parent.mkdir(parents=True)
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    result = {"schema_version": "1.0", "job_id": "job-fixture", "attempt_id": "attempt-1", "status": "succeeded",
              "artifacts": [{"artifact_id": "artifact-fixture", "kind": "evaluation_report", "relative_path": artifact_path,
                             "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                             "created_at": "2026-09-29T00:00:00Z", "producer": producer}], "events": [], "error": None}
    receipt = {"job_id": "job-fixture", "attempt_id": "attempt-1", "compute_stopped": True,
               "reason": "completed", "exit_code": 0, "token": "MUST-NOT-LEAK"}
    for name, document in (("request.json", request), ("result.json", result), ("bridge.done.json", receipt)):
        (directory / name).write_text(json.dumps(document), encoding="utf-8")
    return attempt, directory


class CompositionTests(unittest.TestCase):
    def test_eleven_contract_valid_cards_and_no_vl_promotion_before_real_run(self):
        output = catalog.compose(snapshots())
        self.assertEqual(len(output["models"]), 11)
        for card in output["models"]:
            contracts.ModelManifest.model_validate(card)
        by_id = {c["model_id"]: c for c in output["models"]}
        self.assertEqual(by_id["qwen3-vl-embedding-2b"]["status"], "unavailable")
        self.assertIn("25", by_id["bst-cg-ap-reuse"]["reason"])
        self.assertEqual(by_id["bst-cg-ap-reuse"]["status"], "unavailable")

    def test_missing_duplicate_wrong_owner_and_mixed_interpreter_rejected(self):
        for mutate in (lambda s: s.pop("vl"),
                       lambda s: s["base"]["models"].append(s["base"]["models"][0]),
                       lambda s: s["yolo"]["models"][0].update(model_id="qwen3-vl-embedding-2b"),
                       lambda s: s["vl"]["observation"].update(prefix=catalog.PREFIXES["base"]),
                       lambda s: s["vl"]["models"][0]["environment"].update(prefix="C:/Windows/Python"),
                       lambda s: s["vl"]["observation"].update(platform="win32")):
            data = snapshots()
            mutate(data)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                catalog.compose(data)

    def test_probe_code_must_match_between_environments(self):
        data = snapshots()
        data["vl"]["observation"]["source_files"][0]["sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "Probe code differs"):
            catalog.compose(data)

    def test_old_transformers_in_vl_not_accepted(self):
        data = snapshots()
        for item in [data["vl"]["observation"], data["vl"]["models"][0]["environment"]]:
            item["distributions"]["transformers"]["version"] = "4.51.3"
        card = catalog.compose(data)["models"][-1]
        self.assertEqual(card["status"], "unavailable")
        self.assertIn("vl-env", card["reason"])

    def test_successful_vl_metadata_never_means_ready_or_accuracy(self):
        data = snapshots()
        evidence = {"real_video_window_count": 1, "reported_versions":
                    {k: v["version"] for k, v in data["vl"]["observation"]["distributions"].items()}}
        card = catalog.compose(data, {"qwen3-vl-embedding-2b": evidence})["models"][-1]
        self.assertEqual(card["status"], "experimental")
        self.assertFalse(card["evaluation_report"]["accuracy_validated"])
        evidence["reported_versions"]["torch"] = "2.7.1+cu128"
        with self.assertRaisesRegex(ValueError, "versions differ"):
            catalog.compose(data, {"qwen3-vl-embedding-2b": evidence})

    def test_missing_packages_stay_not_installed_even_with_prior_evidence(self):
        data = snapshots()
        data["vl"]["models"][0].update(status="not_installed", reason="Actual vl-env lacks packages")
        card = catalog.compose(data, {"qwen3-vl-embedding-2b": {}})["models"][-1]
        self.assertEqual(card["status"], "not_installed")

    def test_vl_ready_cannot_bypass_evidence_gate(self):
        data = snapshots()
        data["vl"]["models"][0]["status"] = "ready"
        with self.assertRaisesRegex(ValueError, "cannot enter catalog as ready"):
            catalog.compose(data)

    def test_yolo_wrong_actual_version_is_unavailable(self):
        data = snapshots()
        for item in [data["yolo"]["observation"], data["yolo"]["models"][0]["environment"]]:
            item["distributions"]["ultralytics"]["version"] = "0.0.0-fixture"
        card = next(c for c in catalog.compose(data)["models"] if c["model_id"] == "yolo11n-pose-bytetrack")
        self.assertEqual(card["status"], "unavailable")


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="catalog-cpu-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.relative, self.directory = fixture_attempt(self.root)

    def test_independent_exit_and_artifacts_verified_without_receipt_token(self):
        proof = catalog.job_evidence(self.root, self.relative, "yolo11n-pose-bytetrack", contracts)
        self.assertTrue(proof["checked_artifact_hashes"])
        self.assertNotIn("MUST-NOT-LEAK", json.dumps(proof))
        self.assertFalse(proof["accuracy_validated"])

    def test_result_success_without_receipt_exit_is_not_execution_evidence(self):
        path = self.directory / "bridge.done.json"
        data = json.loads(path.read_text())
        del data["exit_code"]
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "independent successful exit"):
            catalog.job_evidence(self.root, self.relative, "yolo11n-pose-bytetrack", contracts)

    def test_tampered_artifact_rejected(self):
        (self.root / "models/jobs/job-fixture/attempt-1/report.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "hash/size"):
            catalog.job_evidence(self.root, self.relative, "yolo11n-pose-bytetrack", contracts)

    def test_wrong_request_or_attempt_rejected(self):
        with self.assertRaisesRegex(ValueError, "model/version"):
            catalog.job_evidence(self.root, self.relative, "qwen3-vl-embedding-2b", contracts)
        path = self.directory / "bridge.done.json"
        receipt = json.loads(path.read_text())
        receipt["attempt_id"] = "attempt-2"
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "job/attempt"):
            catalog.job_evidence(self.root, self.relative, "yolo11n-pose-bytetrack", contracts)

    def test_duplicate_kind_and_internal_identity_rejected(self):
        result_path = self.directory / "result.json"
        result = json.loads(result_path.read_text())
        duplicate = copy.deepcopy(result["artifacts"][0])
        duplicate["artifact_id"] = "artifact-other"
        result["artifacts"].append(duplicate)
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, "Duplicate artifact kind"):
            catalog.job_evidence(self.root, self.relative, "yolo11n-pose-bytetrack", contracts)
        result["artifacts"].pop()
        path = self.root / result["artifacts"][0]["relative_path"]
        data = json.loads(path.read_text())
        data["producer"]["job_id"] = "wrong-job"
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        result["artifacts"][0].update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, "Internal artifact identity"):
            catalog.job_evidence(self.root, self.relative, "yolo11n-pose-bytetrack", contracts)

    def test_traversal_and_duplicate_json_rejected(self):
        for relative in ("../outside.json", "C:/outside.json", "/tmp/outside.json", "models\\bad.json"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                catalog.contained(self.root, relative)
        path = self.directory / "duplicate.json"
        path.write_text('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            catalog.read_json(path)


class VLSourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="catalog-vl-cpu-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.relative, self.directory = fixture_attempt(self.root, "qwen3-vl-embedding-2b")
        self.request = json.loads((self.directory / "request.json").read_text())
        asset = json.loads((catalog.REPO / "packages/contracts/fixtures/model-request.json").read_text())["assets"][0]
        asset.update(time_base="1/1000", duration_ms=2000)
        self.request["assets"] = [asset]
        self.wanted = {"asset_id": asset["asset_id"], "start_ms": 0, "end_ms": 1000}
        self.request["parameters"].update(windows=[self.wanted], num_frames=2)
        self.window = {**self.wanted, "source_sha256": asset["sha256"], "source_points": [
            {"pts": pts, "time_base": "1/1000", "stream_start_pts": 0, "stream_time_base": "1/1000",
             "source_seconds": pts/1000, "window_seconds": pts/1000, "original_size": [asset["width"], asset["height"]]}
            for pts in (0, 500)]}
        self.producer = {"module": "models", "model_id": "qwen3-vl-embedding-2b", "version": "0.1.0", "job_id": "job-fixture", "attempt_id": "attempt-1"}

    def write_payloads(self):
        (self.directory / "request.json").write_text(json.dumps(self.request))
        result = json.loads((self.directory / "result.json").read_text())
        result["artifacts"] = []
        for kind, payload in [("evaluation_report", {"status": "succeeded", "windows": [self.window]}),
                              ("video_embedding", {"windows": [self.window], "dimension": 2048,
                                                   "video_vectors": [[1.0] + [0.0] * 2047]})]:
            payload.update(producer=self.producer, model_id="qwen3-vl-embedding-2b", fixture_only=True)
            rel = self.request["output_dir"] + "/" + kind + ".json"
            raw = json.dumps(payload).encode()
            (self.root / rel).write_bytes(raw)
            result["artifacts"].append({"artifact_id": "artifact-" + kind, "kind": kind, "relative_path": rel,
                                        "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                                        "created_at": "2026-09-29T00:00:00Z", "producer": self.producer})
        (self.directory / "result.json").write_text(json.dumps(result))

    def test_valid_fixture_checks_source_points_without_claiming_real_inference(self):
        self.write_payloads()
        proof = catalog.job_evidence(self.root, self.relative, "qwen3-vl-embedding-2b", contracts)
        self.assertEqual(proof["real_video_window_count"], 1)
        self.assertFalse(proof["accuracy_validated"])

    def test_missing_source_hash_unknown_asset_and_bad_pts_fail(self):
        original = copy.deepcopy(self.window)
        changes = [lambda w: w.pop("source_sha256"),
                   lambda w: w.update(asset_id="asset-not-in-request"),
                   lambda w: w.update(source_points=["bad", "bad"]),
                   lambda w: w["source_points"][1].update(pts=0),
                   lambda w: w["source_points"][1].update(time_base="0/1"),
                   lambda w: w["source_points"][1].update(source_seconds=99),
                   lambda w: w.update(start_ms=50)]
        for mutate in changes:
            self.window = copy.deepcopy(original)
            mutate(self.window)
            self.write_payloads()
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                catalog.job_evidence(self.root, self.relative, "qwen3-vl-embedding-2b", contracts)


if __name__ == "__main__":
    unittest.main()
