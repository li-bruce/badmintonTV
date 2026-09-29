"""Synthetic CPU/filesystem checks; no pip, network, installed-library or GPU run."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.models import resume_vl_from_wheelhouse as resume


class ResumeWheelhouseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wheels = self.root / "vl-wheelhouse"
        self.wheels.mkdir()
        self.shared = self.root / ".models-bootstrap-lock"

    def wheel(self, name="synthetic.whl", body=b"wheel-test-only"):
        (self.wheels / name).write_bytes(body)
        return {"filename": name, "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(), "url": "https://example.invalid/never-requested"}

    def test_reviewed_manifest_exact_17_bytes_and_versions(self):
        entries = resume.load_manifest()
        self.assertEqual(len(entries), 17)
        self.assertEqual(sum(e["size_bytes"] for e in entries), 3_916_256_631)

    def test_changed_manifest_rejected_before_any_execution(self):
        manifest = self.root / "changed.json"
        manifest.write_text("{}")
        with patch.object(resume, "MANIFEST", manifest), self.assertRaisesRegex(ValueError, "hash changed"):
            resume.load_manifest()

    def test_lf_and_crlf_checkouts_both_accept_identical_manifest(self):
        raw = resume.MANIFEST.read_bytes().replace(b"\r\n", b"\n")
        original = resume.load_manifest()
        for name, body in [("lf.json", raw), ("crlf.json", raw.replace(b"\n", b"\r\n"))]:
            manifest = self.root / name
            manifest.write_bytes(body)
            with patch.object(resume, "MANIFEST", manifest):
                self.assertEqual(resume.load_manifest(), original)

    def test_semantic_manifest_field_mutation_rejected(self):
        data = json.loads(resume.MANIFEST.read_bytes())
        data["files"][0]["size_bytes"] += 1
        manifest = self.root / "mutated.json"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(resume, "MANIFEST", manifest), self.assertRaisesRegex(ValueError, "hash changed"):
            resume.load_manifest()

    def test_verified_wheel_full_sha_and_source_untouched(self):
        entry = self.wheel()
        before = (self.wheels / entry["filename"]).read_bytes()
        result = resume.verify_wheels([entry], self.wheels)
        self.assertEqual(result[0]["sha256"], entry["sha256"])
        self.assertEqual((self.wheels / entry["filename"]).read_bytes(), before)

    def test_truncated_oversize_and_same_size_bad_sha_are_preserved(self):
        for body in (b"short", b"much-longer-than-expected", b"badbadbadbadbad"):
            entry = self.wheel()
            target = self.wheels / entry["filename"]
            target.write_bytes(body)
            with self.assertRaises(ValueError):
                resume.verify_wheels([entry], self.wheels)
            self.assertEqual(target.read_bytes(), body)

    def test_symlink_refused_without_touching_target(self):
        entry = self.wheel()
        target = self.wheels / entry["filename"]
        other = self.root / "original"
        other.write_bytes(target.read_bytes())
        target.unlink()
        try:
            target.symlink_to(other)
        except OSError:
            self.skipTest("Host does not permit creating test symlinks")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            resume.verify_wheels([entry], self.wheels)
        self.assertTrue(other.exists())

    def test_existing_bootstrap_lock_preserved(self):
        self.shared.mkdir()
        marker = self.shared / "owner"
        marker.write_text("original bootstrap")
        with self.assertRaisesRegex(RuntimeError, "Shared bootstrap lock"):
            with resume.installation_locks(self.shared, self.wheels):
                self.fail("must not acquire an existing lock")
        self.assertEqual(marker.read_text(), "original bootstrap")

    def test_existing_wheelhouse_writer_preserved_and_own_shared_lock_released(self):
        writer = self.wheels / ".wheelhouse-writer.json"
        writer.write_text('{"token":"other"}')
        with self.assertRaises(FileExistsError):
            with resume.installation_locks(self.shared, self.wheels):
                self.fail("must not overlap downloader")
        self.assertEqual(json.loads(writer.read_text()), {"token": "other"})
        self.assertFalse(self.shared.exists())

    def test_exception_releases_only_own_locks_and_retains_partial(self):
        partial = self.wheels / "keep.partial"
        partial.write_bytes(b"real prefix remains")
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with resume.installation_locks(self.shared, self.wheels):
                raise RuntimeError("synthetic failure")
        self.assertFalse(self.shared.exists())
        self.assertFalse((self.wheels / ".wheelhouse-writer.json").exists())
        self.assertEqual(partial.read_bytes(), b"real prefix remains")

    def test_paused_pip_detected_from_cmdline_not_ignored_by_state(self):
        proc = self.root / "proc"
        proc.mkdir()
        environment = self.root / "vl-env"
        for pid, argv in [("123", [str(environment / "bin/python"), "-m", "pip", "install"]),
                          ("124", ["/other/env/bin/python", "-m", "pip"]),
                          ("125", [str(environment / "bin/python"), "real_cpu_job.py"]),
                          ("126", ["/usr/bin/python3", str(environment / "bin/pip"), "install"])]:
            folder = proc / pid
            folder.mkdir()
            (folder / "cmdline").write_bytes(("\0".join(argv) + "\0").encode())
            (folder / "status").write_text("State:\tT (stopped)\n")
        self.assertEqual(resume.active_environment_pip(environment, proc), [123, 126])

    def test_controlled_environment_removes_pip_overrides_and_user_python(self):
        with patch.dict(os.environ, {"PIP_EXTRA_INDEX_URL": "https://example.invalid", "PIP_TARGET": "/elsewhere",
                                     "PYTHONPATH": "/user", "PYTHONHOME": "/other"}):
            env = resume.controlled_environment()
        for name in ("PIP_EXTRA_INDEX_URL", "PIP_TARGET", "PYTHONPATH", "PYTHONHOME"):
            self.assertNotIn(name, env)
        self.assertEqual(env["PIP_CONFIG_FILE"], os.devnull)
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")

    def test_commands_install_all_core_offline_then_constrained_official_pypi(self):
        entries = resume.load_manifest()
        core, phase2 = resume.install_commands(Path("/existing/env/bin/python"), entries,
                                              self.wheels, self.root / "constraints.txt")
        self.assertIn("--no-index", core)
        self.assertIn("--no-deps", core)
        self.assertEqual(sum(arg.endswith(".whl") for arg in core), 17)
        self.assertEqual(phase2[phase2.index("--index-url") + 1], "https://pypi.org/simple")
        self.assertIn("--constraint", phase2)
        self.assertEqual(core[core.index("--report") + 1], str(self.root / "core-pip-report.json"))
        self.assertEqual(phase2[phase2.index("--report") + 1], str(self.root / "phase2-pip-report.json"))
        for name, version in resume.PHASE2_VERSIONS.items():
            self.assertIn(name + "==" + version, phase2)
        self.assertNotIn("--no-deps", phase2)
        self.assertNotIn("--upgrade", phase2)

    def fake_runtime(self, active=None):
        environment = self.root / "vl-env"
        (environment / "bin").mkdir(parents=True)
        (environment / "bin/python").write_bytes(b"never executed in test")
        stack = ExitStack()
        for name, value in {"ENVIRONMENT": environment, "RUNTIME": self.root,
                            "WHEELHOUSE": self.wheels, "SHARED_LOCK": self.shared}.items():
            stack.enter_context(patch.object(resume, name, value))
        stack.enter_context(patch.object(resume.platform, "system", return_value="Linux"))
        stack.enter_context(patch.object(resume.platform, "machine", return_value="x86_64"))
        stack.enter_context(patch.object(resume, "active_environment_pip", return_value=active or []))
        self.addCleanup(stack.close)

    def test_still_alive_pip_refuses_installation_even_without_old_lock(self):
        self.fake_runtime(active=[159553])
        with patch.object(resume, "run_step") as command, self.assertRaisesRegex(RuntimeError, "still alive"):
            resume.resume([self.wheel()])
        command.assert_not_called()
        self.assertFalse(self.shared.exists())

    def test_last_wheel_missing_prevents_every_install_step(self):
        self.fake_runtime()
        first, missing = self.wheel("one.whl"), self.wheel("two.whl")
        (self.wheels / "two.whl").unlink()
        with patch.object(resume, "run_step") as command, self.assertRaises(FileNotFoundError):
            resume.resume([first, missing])
        command.assert_not_called()
        self.assertEqual((self.wheels / "one.whl").read_bytes(), b"wheel-test-only")

    def test_mock_execution_order_constraints_and_no_conda(self):
        self.fake_runtime()
        calls = []
        with patch.object(resume, "run_step", side_effect=lambda label, argv, *args: calls.append((label, argv))):
            run_dir = resume.resume([self.wheel()])
        self.assertEqual([x[0] for x in calls], ["00-existing-python", "01-capacity-before", "02-core-offline",
                         "03-phase2-pypi", "04-pip-check", "05-cpu-import-versions", "06-pip-freeze", "07-capacity-after"])
        constraints = (run_dir / "core-constraints.txt").read_text().splitlines()
        self.assertEqual(set(constraints), {n + "==" + v for n, v in resume.CORE_VERSIONS.items()})
        self.assertFalse(any("conda" in arg for _, argv in calls for arg in argv))
        self.assertEqual(json.loads((run_dir / "result.json").read_text())["status"], "complete")
        self.assertTrue((self.wheels / "synthetic.whl").exists())

    def test_mock_install_failure_keeps_evidence_and_all_sources(self):
        self.fake_runtime()
        with patch.object(resume, "run_step", side_effect=RuntimeError("mock install failure")):
            with self.assertRaisesRegex(RuntimeError, "mock install failure"):
                resume.resume([self.wheel()])
        reports = list((self.root / "vl-resume-runs").glob("*/result.json"))
        self.assertEqual(len(reports), 1)
        self.assertEqual(json.loads(reports[0].read_text())["status"], "failed")
        self.assertTrue((self.wheels / "synthetic.whl").exists())
        self.assertFalse(self.shared.exists())


if __name__ == "__main__":
    unittest.main()
