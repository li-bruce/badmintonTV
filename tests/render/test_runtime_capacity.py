"""Runtime capacity regressions without downloads or writes outside temporary storage."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.render import prepare_runtime


class RuntimeCapacityTests(unittest.TestCase):
    def setUp(self):
        disk = patch.object(prepare_runtime.shutil, "disk_usage",
                            return_value=SimpleNamespace(free=600_000_000_000))
        self.disk_usage = disk.start()
        self.addCleanup(disk.stop)

    def test_existing_360gb_and_600gb_free_allow_small_install(self):
        with patch.object(prepare_runtime, "safe_size", side_effect=[400_000_000, 360_000_000_000]):
            value = prepare_runtime.capacity(prepare_runtime.PEAK_LIMIT)
        self.assertEqual(value["measured_shared_peak_bytes"], 360_870_000_000)
        self.assertEqual(value["allocated_owner_peak_bytes"], 646_270_000_000)
        self.assertIsNone(value["other_active_reserved_bytes"])

    def test_free_space_below_peak_plus_margin_fails(self):
        self.disk_usage.return_value = SimpleNamespace(free=prepare_runtime.PEAK_LIMIT + 256_000_000 - 1)
        with patch.object(prepare_runtime, "safe_size", side_effect=[0, 360_000_000_000]):
            with self.assertRaisesRegex(RuntimeError, "Insufficient physical disk"):
                prepare_runtime.capacity(prepare_runtime.PEAK_LIMIT)

    def test_free_space_exactly_peak_plus_margin_succeeds(self):
        self.disk_usage.return_value = SimpleNamespace(free=prepare_runtime.PEAK_LIMIT + 256_000_000)
        with patch.object(prepare_runtime, "safe_size", side_effect=[0, 360_000_000_000]):
            value = prepare_runtime.capacity(prepare_runtime.PEAK_LIMIT)
        self.assertEqual(value["physical_safety_margin_bytes"], 256_000_000)

    def test_measured_shared_limit_is_still_enforced(self):
        with patch.object(prepare_runtime, "safe_size", side_effect=[0, 699_999_999_999]):
            with self.assertRaisesRegex(RuntimeError, "Shared capacity check failed"):
                prepare_runtime.capacity(2)

    def test_existing_files_count_against_runtime_owner_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory)
            owner = shared / "runtime" / "render"
            owner.mkdir(parents=True)
            retained = owner / "existing.bin"
            retained.write_bytes(b"x" * 32)
            with patch.object(prepare_runtime, "SHARED_ROOT", shared), \
                    patch.object(prepare_runtime, "OWNER_ROOT", owner), \
                    patch.object(prepare_runtime, "OWNER_LIMIT", 33):
                with self.assertRaisesRegex(RuntimeError, "runtime/render quota exceeded"):
                    prepare_runtime.capacity(2)
            self.assertEqual(retained.read_bytes(), b"x" * 32)

    def test_allocation_envelope_is_checked_separately_from_shared_usage(self):
        with patch.object(prepare_runtime, "safe_size", side_effect=[0, 1]), \
                patch.object(prepare_runtime, "OTHER_OWNER_CEILING", 700_000_000_000):
            with self.assertRaisesRegex(RuntimeError, "Shared capacity check failed"):
                prepare_runtime.capacity(1)


if __name__ == "__main__":
    unittest.main()
