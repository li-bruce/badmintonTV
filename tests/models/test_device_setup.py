"""Installer policy/plan tests. They never install packages or run a GPU job."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import sys
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "scripts/models/device_setup.py"
spec = importlib.util.spec_from_file_location("btv_device_setup", SOURCE)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class DeviceSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "storage with spaces"
        self.root.mkdir()

    def plan(self, profile="cpu-prep", **kw):
        return setup.build_plan(profile, self.root, **kw)

    def test_cpu_no_torch_cuda_parent_or_legacy_locations(self):
        plan = self.plan()
        lines = (setup.REPO / plan["requirements"]).read_text()
        for bad in ("torch", "cuda", "file://", "/mnt/d/", "/home/ubuntu", "system-site-packages"):
            self.assertNotIn(bad, "\n".join(x for x in lines.splitlines() if not x.startswith("#")))
        self.assertFalse(plan["gpu_required"])
        self.assertEqual(plan["environment"]["CUDA_VISIBLE_DEVICES"], "")
        self.assertEqual(len(plan["commands"]), 3)

    def test_profiles_separate_prefixes_and_torch_versions(self):
        plans = [self.plan(name) for name in setup.PROFILES]
        self.assertEqual(len({p["env_prefix"] for p in plans}), 4)
        self.assertIn("torch==2.7.1", plans[1]["commands"][1])
        self.assertIn("torch==2.8.0", plans[3]["commands"][1])
        for plan in plans:
            self.assertEqual(plan["training_loop"], "not_implemented")
            self.assertEqual(plan["model_status"], "unavailable")

    def test_plan_does_not_write_or_execute(self):
        before = list(self.root.rglob("*"))
        with patch.object(setup.subprocess, "run", side_effect=AssertionError("executed")), patch.object(setup.subprocess, "Popen", side_effect=AssertionError("executed")):
            plan = self.plan()
        self.assertEqual(before, list(self.root.rglob("*")))
        self.assertEqual(plan["status"], "plan_only")

    def test_special_characters_remain_single_argv(self):
        prefix = self.root / "runtime/models/envs/a ; touch HACK $(id)"
        plan = self.plan(env_prefix=prefix)
        self.assertEqual(plan["commands"][0][4], str(prefix))
        self.assertFalse((self.root / "HACK").exists())

    def test_outside_prefix_parent_traversal_and_root_refused(self):
        for prefix in (self.root.parent / "escape", self.root / "runtime/models", self.root / "runtime/models/../escape", self.root / "runtime/models/device-cache/bad"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                self.plan(env_prefix=prefix)
        with self.assertRaises(ValueError):
            setup.build_plan("cpu-prep", Path(self.root.anchor))
        with self.assertRaises(ValueError):
            setup.build_plan("cpu-prep", "relative")

    def test_symlink_ancestor_refused(self):
        link = self.root / "runtime"
        target = self.root.parent / "outside"
        target.mkdir()
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("host does not permit creating test symlink; WSL test covers this")
        with self.assertRaises(ValueError):
            self.plan()

    def test_conda_is_executable_path_not_shell(self):
        with self.assertRaises(ValueError):
            self.plan(conda_executable="conda --anything")
        with self.assertRaises(ValueError):
            self.plan(conda_executable=self.root / "malicious.sh")
        path = self.root / "conda installation/bin/conda"
        self.assertEqual(self.plan(conda_executable=path)["commands"][0][0], str(path))

    def test_child_environment_clears_inheritance_and_pins_caches(self):
        with patch.dict(os.environ, {"PYTHONPATH": "/foreign", "PIP_EXTRA_INDEX_URL": "https://bad.invalid", "CONDA_PREFIX": "/base", "VIRTUAL_ENV": "/foreign", "HF_HOME": "/outside", "CONDARC": "/outside"}):
            env = setup.child_environment(self.plan())
        for key in ("PYTHONPATH", "PIP_EXTRA_INDEX_URL", "CONDA_PREFIX", "VIRTUAL_ENV"):
            self.assertNotIn(key, env)
        for key in ("HF_HOME", "TORCH_HOME", "PIP_CACHE_DIR", "TMPDIR", "CONDA_PKGS_DIRS"):
            self.assertTrue(Path(env[key]).is_relative_to(self.root))
        self.assertEqual(env["CONDA_REGISTER_ENVS"], "false")

    def capacity(self, mapping=None, free=1000*setup.GB, plan=None):
        mapping = mapping or {}
        return setup.capacity(plan or self.plan(), measure_fn=lambda p, exclude=None: mapping.get(str(p), 0), disk_fn=lambda p: SimpleNamespace(free=free))

    def test_capacity_pass_and_runtime_refusal(self):
        self.assertTrue(self.capacity()["passed"])
        out = self.capacity({str(self.root / "runtime/models"): 34*setup.GB})
        self.assertFalse(out["checks"]["models_runtime_35GB"])

    def test_global_and_disk_refusal(self):
        out = self.capacity({str(self.root): 699*setup.GB})
        self.assertFalse(out["checks"]["global_actual_700GB"])
        self.assertFalse(self.capacity(free=6*setup.GB)["passed"])

    def test_external_conda_counts_toward_shared_and_global(self):
        base = self.root.parent / "conda"
        out = self.capacity({str(base): 16*setup.GB}, plan=self.plan(conda_executable=base / "bin/conda"))
        self.assertEqual(out["external_conda_base_bytes"], 16*setup.GB)
        self.assertFalse(out["checks"]["shared_conda_15GB"])

    def test_existing_prefix_not_repaired(self):
        plan = self.plan()
        Path(plan["env_prefix"]).mkdir(parents=True)
        with patch.object(setup, "host_status", return_value={"apply_supported": True}), self.assertRaises(FileExistsError):
            setup.apply(plan)

    def test_native_linux_apply_blocked(self):
        with patch.object(setup, "host_status", return_value={"apply_supported": False}), self.assertRaisesRegex(ValueError, "WSL Ubuntu"):
            setup.apply(self.plan())

    def test_missing_conda_no_output_created(self):
        with patch.object(setup, "host_status", return_value={"apply_supported": True}), self.assertRaisesRegex(ValueError, "Conda not installed"):
            setup.apply(self.plan())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_doctor_absent_dependencies_never_claims_model_ready(self):
        with patch.object(setup.shutil, "which", return_value=None):
            report = setup.doctor(self.plan("gpu-base"))
        self.assertEqual(report["environment"], "not_installed")
        self.assertEqual(report["gpu"], "unavailable")
        self.assertEqual(report["models"]["status"], "unavailable")

    def test_cli_plan_json_and_mutually_exclusive_actions(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(setup.main(["--storage-root", str(self.root)]), 0)
        self.assertEqual(json.loads(stream.getvalue())["status"], "plan_only")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            setup.main(["--storage-root", str(self.root), "--apply", "--dry-run"])

    def test_each_requirements_file_is_portable_exact_pins(self):
        for profile in setup.PROFILES.values():
            lines = (setup.REPO / profile["requirements"]).read_text().splitlines()
            pins = [x for x in lines if x and not x.startswith("#")]
            self.assertTrue(pins)
            names = []
            for line in pins:
                self.assertRegex(line, r"^[A-Za-z0-9_-]+==[A-Za-z0-9.+_-]+$")
                names.append(line.split("==")[0].replace("_", "-").lower())
            self.assertEqual(len(names), len(set(names)))

    def test_registry_follows_storage_and_selected_environment(self):
        from packages.models.registry import catalog
        prefix = self.root / "runtime/models/envs/gpu-pose-tracknet"
        with patch.dict(os.environ, {"BTV_STORAGE_ROOT": str(self.root), "BTV_MODELS_ENV": str(prefix)}), patch("importlib.util.find_spec", return_value=None):
            rows = catalog()["models"]
        for row in rows:
            if row["environment"]["prefix"]:
                self.assertEqual(row["environment"]["prefix"], str(prefix))
                self.assertEqual(row["status"], "not_installed")

    def test_wrong_dependency_version_is_not_ready(self):
        plan = self.plan()
        python = Path(plan["env_prefix"]) / "bin/python"
        python.parent.mkdir(parents=True)
        python.touch()
        probe = {"packages": {name: {"status": "installed", "version": "0.0.0"} for name in setup.PROFILES["cpu-prep"]["packages"]},
                 "prefix": plan["env_prefix"], "base_prefix": plan["env_prefix"], "python": [3, 11]}
        with patch.object(setup.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(probe))):
            self.assertEqual(setup.doctor(plan)["environment"], "unavailable")

    def test_registry_windows_drive_maps_to_wsl_with_explicit_override(self):
        from packages.models.environment import runtime_prefix
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime_prefix("E:/sports data", "env"), "/mnt/e/sports data/runtime/models/env")
            self.assertEqual(runtime_prefix("/srv/sports", "vl-env"), "/srv/sports/runtime/models/vl-env")
        with patch.dict(os.environ, {"BTV_MODELS_ENV": "/custom/mount/env"}):
            self.assertEqual(runtime_prefix("E:/sports data", "env"), "/custom/mount/env")

    @unittest.skipUnless(sys.platform == "linux", "uses Linux process groups and GNU du")
    def test_real_argv_does_not_execute_shell_metacharacters(self):
        plan = self.plan()
        log = self.root / "command.log"
        literal = "value; touch SHOULD_NOT_EXIST $(id)"
        setup.bounded_command([sys.executable, "-c", "import sys; print(sys.argv[1])", literal], plan, log, 0)
        self.assertEqual(log.read_text().strip(), literal)
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    @unittest.skipUnless(sys.platform == "linux", "executable bit required")
    def test_failed_install_retains_report_and_releases_own_lock(self):
        conda = self.root / "runtime/shared/conda/bin/conda"
        conda.parent.mkdir(parents=True)
        conda.write_text("#!/bin/sh\nexit 99\n")
        conda.chmod(0o700)
        plan = self.plan(conda_executable=conda)
        with patch.object(setup, "host_status", return_value={"apply_supported": True}), patch.object(setup, "capacity", return_value={"passed": True}), patch.object(setup, "bounded_command", side_effect=RuntimeError("expected test failure")):
            with self.assertRaisesRegex(RuntimeError, "expected test failure"):
                setup.apply(plan)
        reports = list((self.root / "runtime/models/device-reports").glob("*/report.json"))
        self.assertEqual(len(reports), 1)
        self.assertEqual(json.loads(reports[0].read_text())["status"], "failed")
        self.assertFalse((self.root / "runtime/shared/.models-bootstrap-lock").exists())

    @unittest.skipUnless(sys.platform == "linux", "executable bit required")
    def test_existing_installer_lock_never_removed(self):
        conda = self.root / "runtime/shared/conda/bin/conda"
        conda.parent.mkdir(parents=True)
        conda.touch()
        conda.chmod(0o700)
        lock = self.root / "runtime/shared/.models-bootstrap-lock"
        lock.mkdir()
        plan = self.plan(conda_executable=conda)
        with patch.object(setup, "host_status", return_value={"apply_supported": True}), patch.object(setup, "capacity", return_value={"passed": True}), patch.object(setup, "bounded_command") as command:
            with self.assertRaises(FileExistsError):
                setup.apply(plan)
        command.assert_not_called()
        self.assertTrue(lock.is_dir())


if __name__ == "__main__":
    unittest.main()
