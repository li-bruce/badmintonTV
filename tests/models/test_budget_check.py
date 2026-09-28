"""Read-only accounting tests using small temporary files; no WSL or GPU."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts.models import budget_check


class BudgetCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='btv-budget-test-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'storage'
        self.root.mkdir()
        self.native = self.base / 'miniforge'
        self.write(self.root / 'runtime/models/env.bin', 7)
        self.write(self.root / 'runtime/shared/pkgs/new.bin', 11)
        self.write(self.root / 'data/source.bin', 13)
        self.write(self.root / 'models/weights.bin', 19)
        self.make_native(self.native)
        disk = patch.object(budget_check.shutil, 'disk_usage', side_effect=lambda path:
                            types.SimpleNamespace(free=0 if Path(path) == self.native else 1_000_000_000_000))
        disk.start()
        self.addCleanup(disk.stop)

    @staticmethod
    def write(path, count):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * count)

    def make_native(self, path):
        self.write(path / 'bin/conda', 17)
        self.write(path / 'pkgs/old-package.bin', 23)
        self.write(path / 'envs/old-user-env/unrelated.bin', 1000)

    def test_base_and_old_pkgs_count_once_without_visiting_user_envs(self):
        original_scandir = os.scandir
        def checked_scandir(path):
            self.assertFalse(Path(path).is_relative_to(self.native / 'envs'), 'old user envs must not be traversed')
            return original_scandir(path)
        with patch.object(budget_check.os, 'scandir', side_effect=checked_scandir):
            report = budget_check.budget_report(self.root, self.native)
        self.assertEqual(report['native_base']['size_bytes'], 40)
        self.assertTrue(report['native_base']['reused'])
        self.assertEqual(report['disk_usage_bytes']['runtime'], 18)
        self.assertEqual(report['usage_bytes']['runtime_shared'], 51)
        self.assertEqual(report['usage_bytes']['runtime'], 58)
        self.assertEqual(report['usage_bytes']['runtime_models'], 7)
        self.assertEqual(report['project_total_bytes'], 90)
        self.assertEqual(report['native_base']['free_bytes_reference'], 0)
        self.assertTrue(report['checks_passed'], 'native free space is read-only reference, not a D-root write gate')

    def test_native_base_inside_shared_directory_is_not_added_twice(self):
        native = self.root / 'runtime/shared/miniforge'
        self.make_native(native)
        report = budget_check.budget_report(self.root, native)
        self.assertEqual(report['native_base']['size_bytes'], 40)
        self.assertEqual(report['usage_bytes']['runtime_shared'], 51)
        self.assertEqual(report['usage_bytes']['runtime'], 58)
        self.assertEqual(report['project_total_bytes'], 90)

    def test_missing_native_base_is_explicit_zero_not_reused(self):
        report = budget_check.budget_report(self.root, self.base / 'missing-miniforge')
        self.assertEqual(report['native_base']['size_bytes'], 0)
        self.assertFalse(report['native_base']['reused'])
        self.assertEqual(report['native_base']['status'], 'not_found')
        self.assertIsNone(report['native_base']['free_bytes_reference'])
        self.assertEqual(report['usage_bytes']['runtime'], 18)
        self.assertEqual(report['project_total_bytes'], 50)

    def test_native_usage_triggers_shared_15gb_failure_through_cli(self):
        original_size = budget_check.size
        def reported_size(path, **kwargs):
            # Simulate a large base without writing a multi-GB test file.
            return 15_000_000_000 if Path(path) == self.native else original_size(path, **kwargs)
        stdout = io.StringIO()
        with patch.object(budget_check, 'size', side_effect=reported_size), redirect_stdout(stdout):
            with self.assertRaisesRegex(SystemExit, 'capacity preflight failed'):
                budget_check.main(['--root', str(self.root), '--native-base', str(self.native)])
        report = json.loads(stdout.getvalue())
        self.assertEqual(report['usage_bytes']['runtime_shared'], 15_000_000_011)
        self.assertFalse(report['checks']['runtime_shared_quota'])
        self.assertFalse(report['checks_passed'])
        self.assertTrue(report['checks']['storage_root_free_space'])

    def test_negative_reservations_cannot_reduce_the_accounted_usage(self):
        with self.assertRaises(ValueError):
            budget_check.budget_report(self.root, self.native, reserve_runtime=-1)


if __name__ == '__main__':
    unittest.main()
