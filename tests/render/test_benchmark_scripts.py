"""Benchmark safety regressions with temporary bytes and mocked version queries."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts/render"
with patch.object(sys, "path", [str(SCRIPT_DIR), *sys.path]):
    import benchmark_presets as presets
    import benchmark_nvenc as controlled

from packages.render.timeline import RenderError


class StopBeforeWrites(Exception):
    """Capture a real entrypoint's initial manifest without starting a render."""


class BenchmarkSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.checks = {}
        for name in ("ffmpeg", "ffprobe"):
            binary = self.root / (name + ".exe")
            binary.write_bytes((name + " fake binary v1").encode())
            self.checks[name] = str(binary)
            self.checks[name + "_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        self.checks["version"] = "ffmpeg version fixture"
        self.environment = {"checks": self.checks}
        self.version_detail = "configuration: fixture"

    def version_query(self, argv, **kwargs):
        self.assertEqual(argv[1:], ["-version"])
        return SimpleNamespace(returncode=0, stderr="",
            stdout=Path(argv[0]).stem + " version fixture\n" + self.version_detail + "\n")

    def test_actual_hash_and_full_version_are_recorded(self):
        self.checks["ffmpeg_sha256"] = self.checks["ffmpeg_sha256"].upper()
        with patch.object(presets.subprocess, "run", side_effect=self.version_query) as run:
            fingerprint = presets.runtime_fingerprint(self.environment)
        self.assertEqual(run.call_count, 2)
        for name in ("ffmpeg", "ffprobe"):
            self.assertEqual(fingerprint[name]["sha256"], hashlib.sha256(Path(self.checks[name]).read_bytes()).hexdigest())
            self.assertEqual(fingerprint[name]["version"], name + " version fixture\nconfiguration: fixture")

    def test_stale_declared_hash_rejects_before_any_version_execution(self):
        self.checks["ffprobe_sha256"] = "0" * 64
        with patch.object(presets.subprocess, "run") as run, self.assertRaises(RenderError) as error:
            presets.runtime_fingerprint(self.environment)
        self.assertEqual(error.exception.code, "runtime_hash_mismatch")
        run.assert_not_called()

    def test_declared_version_mismatch_is_rejected(self):
        self.checks["version"] = "ffmpeg version other"
        with patch.object(presets.subprocess, "run", side_effect=self.version_query), self.assertRaises(RenderError) as error:
            presets.runtime_fingerprint(self.environment)
        self.assertEqual(error.exception.code, "runtime_version_mismatch")

    def test_failed_or_timed_out_version_query_is_rejected(self):
        for response in (SimpleNamespace(returncode=1, stdout="", stderr="fail"),
                         subprocess.TimeoutExpired("fixture", 15)):
            with self.subTest(response=type(response).__name__):
                with patch.object(presets.subprocess, "run", return_value=response,
                                  side_effect=response if isinstance(response, Exception) else None), \
                        self.assertRaises(RenderError) as error:
                    presets.runtime_fingerprint(self.environment)
                self.assertEqual(error.exception.code, "runtime_version_failed")

    def test_resume_entrypoint_rejects_same_path_binary_and_full_version_changes(self):
        environment_path = self.root / "environment.json"
        batch = self.root / "render/benchmarks/presets-regression"
        argv = ["benchmark_presets.py", "--storage-root", str(self.root), "--environment", str(environment_path),
                "--batch-dir", str(batch), "--repeats", "1"]
        environment_path.write_text(json.dumps(self.environment), encoding="utf-8")
        manifests = []

        def save_manifest(root, folder, records):
            manifests.append(deepcopy(records["batch.json"]))
            raise StopBeforeWrites()

        # Use run() to generate its real continuation config. Source validation
        # is unrelated here; no real source file or media executable is needed.
        with patch.object(sys, "argv", argv), patch.object(presets, "source_preflight", return_value={}), \
                patch.object(presets.subprocess, "run", side_effect=self.version_query), \
                patch.object(presets, "persist", side_effect=save_manifest), self.assertRaises(StopBeforeWrites):
            presets.run()
        self.assertEqual(set(manifests[0]["config"]["runtime"]), {"ffmpeg", "ffprobe"})
        batch.mkdir(parents=True)
        (batch / "batch.json").write_text(json.dumps(manifests[0]), encoding="utf-8")
        original_bytes = Path(self.checks["ffmpeg"]).read_bytes()
        for mode in ("same-path-new-binary", "changed-full-version"):
            with self.subTest(mode=mode):
                Path(self.checks["ffmpeg"]).write_bytes(
                    original_bytes + b"changed" if mode == "same-path-new-binary" else original_bytes)
                self.checks["ffmpeg_sha256"] = hashlib.sha256(Path(self.checks["ffmpeg"]).read_bytes()).hexdigest()
                self.version_detail = "configuration: changed" if mode == "changed-full-version" else "configuration: fixture"
                environment_path.write_text(json.dumps(self.environment), encoding="utf-8")
                with patch.object(sys, "argv", argv), patch.object(presets, "source_preflight", return_value={}), \
                        patch.object(presets.subprocess, "run", side_effect=self.version_query), \
                        patch.object(presets, "reservation") as reserve, patch.object(presets, "render") as render, \
                        self.assertRaises(RenderError) as error:
                    presets.run()
                self.assertIn("runtime fingerprint differ", str(error.exception))
                reserve.assert_not_called()
                render.assert_not_called()

    def test_normal_batch_is_accepted_and_other_parents_are_rejected(self):
        expected = self.root / "render/benchmarks/presets-good"
        self.assertEqual(presets.resolve_batch_dir(self.root, expected), expected)
        for bad in (self.root / "platform/presets-bad", expected / "presets-nested",
                    self.root / "render/benchmarks/wrong-prefix"):
            with self.subTest(path=bad), self.assertRaises(RenderError):
                presets.resolve_batch_dir(self.root, bad)

    def test_real_junctions_cannot_redirect_owner_parent_or_batch(self):
        for number, part in enumerate(("render", "render/benchmarks", "render/benchmarks/presets-junction")):
            with self.subTest(part=part):
                root = self.root / f"storage-{number}"
                root.mkdir()
                target = self.root / f"outside-owner-{number}"
                target.mkdir()
                (target / "sentinel").write_text("preserve target", encoding="utf-8")
                link = root / part
                link.parent.mkdir(parents=True, exist_ok=True)
                self.assertTrue(link.parent.resolve().is_relative_to(self.root))
                self.assertTrue(target.resolve().is_relative_to(self.root))
                try:
                    if os.name == "nt":
                        import _winapi
                        _winapi.CreateJunction(str(target), str(link))
                    else:
                        link.symlink_to(target, target_is_directory=True)
                except (AttributeError, NotImplementedError, OSError) as exc:
                    self.skipTest(f"Creating real directory junctions/links unavailable: {exc}")
                try:
                    batch = root / "render/benchmarks/presets-junction"
                    with patch.object(presets, "reservation") as reserve, \
                            patch.object(presets, "atomic_json") as atomic, self.assertRaises(RenderError) as error:
                        presets.persist(root, batch, {"probe.json": {}})
                    self.assertEqual(error.exception.code, "unsafe_path")
                    reserve.assert_not_called()
                    atomic.assert_not_called()
                    self.assertEqual((target / "sentinel").read_text(encoding="utf-8"), "preserve target")
                finally:
                    if os.name == "nt":
                        os.rmdir(link)  # Remove only the reparse entry before temp-root cleanup.
                    else:
                        link.unlink()
                self.assertTrue(target.is_dir())

    def test_worker_cancel_and_attempt_checks_remain_enforced(self):
        summary = {"checks": {"technical_qa": True}, "technical_status": "PASS"}
        for status, attempt, expected in (("succeeded", 1, "PASS"), ("cancelled", 1, "FAIL"),
                                          ("succeeded", 2, "FAIL")):
            with self.subTest(status=status, attempt=attempt):
                checked = controlled.apply_runtime_checks(deepcopy(summary), {"status": status, "attempt": attempt}, 1)
                self.assertEqual(checked["technical_status"], expected)


if __name__ == "__main__":
    unittest.main()
