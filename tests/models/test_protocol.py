"""Synthetic transport tests only: these do not evaluate a real model or video."""

from __future__ import annotations

import contextlib
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from packages.models import protocol


def request_fixture() -> dict:
    return {
        "schema_version": "1.0", "job_id": "job-protocol-test",
        "attempt_id": "attempt-protocol-test", "operation": "query_parse",
        "assets": [], "parameters": {"model_id": "mock-query", "text": "后退后上网"},
        "output_dir": "models/jobs/job-protocol-test/attempt-protocol-test",
    }


def asset_fixture() -> dict:
    # Metadata describes only an invented test fixture, not an acquired asset.
    return {
        "schema_version": "1.0", "asset_id": "asset-synthetic-test",
        "relative_path": "data/test/synthetic.mp4", "sha256": "0" * 64,
        "size_bytes": 0, "duration_ms": 1000, "width": 16, "height": 16,
        "fps_num": 30, "fps_den": 1, "time_base": "1/30000", "title": "protocol fixture",
        "match_id": "match-synthetic-test", "source_type": "synthetic",
        "source_url": None, "source_page": None, "acquired_at": "2026-09-28T00:00:00Z",
        "camera_type": "unknown", "discipline": "unknown", "players": [],
        "rights": {"status": "unknown", "license_url": None, "evidence": [], "allowed_uses": []},
        "split": "unassigned", "probe": {}, "provenance": {"source": "protocol_test"},
    }


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="btv-models-protocol-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "storage"
        self.root.mkdir()
        self.env = patch.dict(os.environ, {"BTV_STORAGE_ROOT": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def call_run(self, execute, request=None, raw=None, result_path=None):
        request_path = self.base / "request.json"
        request_path.write_text(raw if raw is not None else json.dumps(request or request_fixture()), encoding="utf-8")
        result_path = result_path or (self.base / "result.json")
        fake_inference = types.ModuleType("packages.models.inference")
        fake_inference.execute = execute
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(sys.modules, {"packages.models.inference": fake_inference}), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = protocol.main(["run", "--request", str(request_path), "--result", str(result_path)])
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
        records = [json.loads(line) for line in stdout.getvalue().splitlines()]
        return code, result, records, stderr.getvalue()

    def assert_progress_schema(self, records):
        keys = {"schema_version", "job_id", "seq", "event", "stage", "current", "total", "unit", "message"}
        self.assertEqual([record["seq"] for record in records], list(range(1, len(records) + 1)))
        for record in records:
            self.assertEqual(set(record), keys)
            self.assertEqual(record["schema_version"], "1.0")

    def test_success_uses_adapter_and_publishes_correlated_result(self):
        received = []
        def execute(request, root, output, progress):
            received.append((request, root, output))
            progress("parsed", current=1, total=1, unit="query", message="Mock protocol step")
            print("adapter diagnostic")
            return {"artifacts": [], "events": []}
        code, result, records, stderr = self.call_run(execute)
        self.assertEqual(code, 0)
        self.assertEqual(result, {
            "schema_version": "1.0", "job_id": "job-protocol-test", "attempt_id": "attempt-protocol-test",
            "status": "succeeded", "artifacts": [], "events": [], "error": None,
        })
        self.assertEqual(received[0][1], self.root.resolve())
        self.assertEqual(received[0][2], self.root / request_fixture()["output_dir"])
        self.assertEqual([r["stage"] for r in records], ["starting", "parsed", "completed"])
        self.assertIn("adapter diagnostic", stderr)
        self.assert_progress_schema(records)

    def test_missing_prerequisite_is_blocked_exit_two(self):
        def execute(*args):
            raise protocol.ModelBlocked("not_installed", "Model weights are not installed")
        code, result, records, _ = self.call_run(execute)
        self.assertEqual((code, result["status"]), (2, "blocked"))
        self.assertEqual(result["error"]["code"], "not_installed")
        self.assertEqual(records[-1]["stage"], "blocked")
        self.assert_progress_schema(records)

    def test_cancellation_is_published_and_exit_130(self):
        def execute(*args):
            raise KeyboardInterrupt
        code, result, records, _ = self.call_run(execute)
        self.assertEqual((code, result["status"]), (130, "cancelled"))
        self.assertEqual(result["attempt_id"], request_fixture()["attempt_id"])
        self.assertEqual(records[-1]["stage"], "cancelled")

    def test_unexpected_exception_does_not_leak_secret(self):
        def execute(*args):
            raise RuntimeError("Bearer test-secret-must-not-leak")
        code, result, records, stderr = self.call_run(execute)
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertNotIn("test-secret-must-not-leak", json.dumps(result) + json.dumps(records) + stderr)

    def test_invalid_request_returns_known_job_and_attempt(self):
        request = request_fixture()
        request["operation"] = "shell"
        def execute(*args):
            self.fail("invalid requests must not execute")
        code, result, records, _ = self.call_run(execute, request=request)
        self.assertEqual((code, result["status"]), (1, "failed"))
        self.assertEqual(result["job_id"], request["job_id"])
        self.assertEqual(result["attempt_id"], request["attempt_id"])
        self.assertEqual(result["error"]["code"], "invalid_request")
        self.assertEqual(len(records), 1)

    def test_existing_result_preserved_and_adapter_not_run(self):
        destination = self.base / "result.json"
        original = '{"old_attempt":"retained"}\n'
        destination.write_text(original, encoding="utf-8")
        def execute(*args):
            self.fail("a request with an existing result must not execute")
        code, result, records, _ = self.call_run(execute)
        self.assertEqual(code, 1)
        self.assertEqual(destination.read_text(encoding="utf-8"), original)
        self.assertEqual(records[-1]["stage"], "result_write_failed")

    def test_json_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        samples = ['{"job_id":"a","job_id":"b"}', '{"parameters":{"temperature":NaN}}', "not JSON"]
        for index, raw in enumerate(samples):
            with self.subTest(raw=raw):
                code, result, records, _ = self.call_run(lambda *args: self.fail("must not execute"), raw=raw,
                                                        result_path=self.base / f"result-{index}.json")
                self.assertEqual((code, result["status"]), (1, "failed"))
                self.assert_progress_schema(records)

    def test_request_fields_types_and_operation_requirements(self):
        valid = request_fixture()
        self.assertEqual(protocol.validate_request(valid, self.root), valid)
        changes = [
            {"schema_version": "2.0"}, {"job_id": ""}, {"attempt_id": None},
            {"assets": {}}, {"parameters": []}, {"parameters": {}},
            {"operation": "pose"}, {"output_dir": "render/handoff"},
            {"parameters": {"model_id": "x", "temperature": float("nan")}},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(protocol.InvalidRequest):
                protocol.validate_request({**copy.deepcopy(valid), **change}, self.root)
        for key in valid:
            incomplete = valid.copy()
            del incomplete[key]
            with self.subTest(missing=key), self.assertRaises(protocol.InvalidRequest):
                protocol.validate_request(incomplete, self.root)
        with self.assertRaises(protocol.InvalidRequest):
            protocol.validate_request({**valid, "shell": "ignored-by-nobody"}, self.root)

    def test_full_asset_checks_and_source_path_rejection(self):
        request = request_fixture()
        request["operation"] = "pose"
        request["assets"] = [asset_fixture()]
        self.assertEqual(protocol.validate_request(request, self.root), request)
        changes = [{"relative_path": "../outside.mp4"}, {"size_bytes": True}, {"sha256": "none"},
                   {"fps_den": 0}, {"time_base": "0/1"}, {"source_type": "fake"},
                   {"acquired_at": "2026-09-28"}, {"players": "x"}, {"rights": {}}]
        for change in changes:
            bad = copy.deepcopy(request)
            bad["assets"][0].update(change)
            with self.subTest(change=change), self.assertRaises(protocol.InvalidRequest):
                protocol.validate_request(bad, self.root)
        duplicate = copy.deepcopy(request)
        duplicate["assets"] *= 2
        with self.assertRaises(protocol.InvalidRequest):
            protocol.validate_request(duplicate, self.root)

    def test_relative_path_rejects_windows_and_posix_escape_forms(self):
        invalid = ["../escape", "/absolute", r"C:\\video\\models\\a", "C:relative", "models/../data/x",
                   "models//x", "models/./x", "models/x/", r"models\x", "models/CON", "models/x ", "models/NUL.txt"]
        for relative in invalid:
            with self.subTest(relative=relative), self.assertRaises(protocol.InvalidRequest):
                protocol.resolve_relative(self.root, relative)
        self.assertEqual(protocol.resolve_relative(self.root, "models/jobs/x", owner="models"), self.root / "models/jobs/x")
        for relative in ["models", "data/jobs/x"]:
            with self.assertRaises(protocol.InvalidRequest):
                protocol.resolve_relative(self.root, relative, owner="models")

    def test_symlink_escape_and_cross_owner_symlink_are_rejected(self):
        models = self.root / "models"
        models.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        data = self.root / "data"
        data.mkdir()
        try:
            (models / "escape").symlink_to(outside, target_is_directory=True)
            (models / "other_owner").symlink_to(data, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"This test environment cannot create symlinks: {type(exc).__name__}")
        with self.assertRaises(protocol.InvalidRequest):
            protocol.resolve_relative(self.root, "models/escape/new.json")
        with self.assertRaises(protocol.InvalidRequest):
            protocol.resolve_relative(self.root, "models/other_owner/new.json", owner="models")

    def test_atomic_exclusive_publication_has_one_winner_and_no_partial_json(self):
        path = self.base / "contended.json"
        def publish(index):
            try:
                protocol.atomic_write_json(path, {"writer": index, "body": "已完整写入" * 1000})
                return index
            except FileExistsError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            winners = [value for value in pool.map(publish, range(8)) if value is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["writer"], winners[0])
        self.assertEqual(list(path.parent.glob(".btv-models-*.tmp")), [])

    def test_make_artifact_hashes_complete_file_with_exact_seven_fields(self):
        path = self.root / "models/handoff/query.json"
        protocol.atomic_write_json(path, {"test": "中文"})
        artifact = protocol.make_artifact(self.root, path, "query", "protocol-test")
        self.assertEqual(set(artifact), {"artifact_id", "kind", "relative_path", "sha256", "size_bytes", "created_at", "producer"})
        self.assertEqual(artifact["relative_path"], "models/handoff/query.json")
        self.assertEqual(artifact["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(artifact["size_bytes"], path.stat().st_size)
        with self.assertRaises(protocol.InvalidRequest):
            protocol.make_artifact(self.root, self.base / "outside.json", "query", "protocol-test")
        with self.assertRaises(FileNotFoundError):
            protocol.make_artifact(self.root, "models/missing.json", "query", "protocol-test")

    def test_catalog_is_lazy_and_uses_registry_result(self):
        fake_registry = types.ModuleType("packages.models.registry")
        fake_registry.catalog = lambda: {"schema_version": "1.0", "models": []}
        stream = io.StringIO()
        with patch.dict(sys.modules, {"packages.models.registry": fake_registry}), contextlib.redirect_stdout(stream):
            code = protocol.main(["catalog"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stream.getvalue()), fake_registry.catalog())


if __name__ == "__main__":
    unittest.main()
