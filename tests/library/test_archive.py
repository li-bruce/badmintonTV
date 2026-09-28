"""ZIP fixtures verify extraction safety, not video or annotation quality."""

import hashlib
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

from packages.library.archive import ArchiveError, extract_member, inspect_zip
from packages.library.storage import QuotaExceeded, QuotaManager, UnsafePath


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="library-archive-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.quota = QuotaManager(self.root / "data", allow_test_root=True, min_free_bytes=0)
        self.archive = self.quota.data_root / "source.zip"
        self.output = self.quota.data_root / "selected" / "one.bin"
        self.record = self.output.with_name("one.bin.extract.json")
        self.partial = self.output.with_name("one.bin.extract.part")
        self.payload = bytes(range(256)) * 600

    def make_zip(self, entries=None, compression=zipfile.ZIP_STORED):
        if entries is None:
            entries = [("match/one.bin", self.payload), ("match/labels.csv", b"frame,x,y\n0,1,2\n"), ("other/never-extract.bin", b"not selected")]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w", compression=compression) as container:
                for name, data in entries:
                    container.writestr(name, data)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def extract(self, member="match/one.bin", **kwargs):
        kwargs.setdefault("max_bytes", len(self.payload))
        return extract_member(self.archive, member, "selected/one.bin", quota=self.quota, **kwargs)

    def metadata(self):
        return json.loads(self.record.read_text(encoding="utf-8"))

    @contextmanager
    def directory_link(self, link, target):
        try:
            if os.name == "nt":
                subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                               check=True, capture_output=True, text=True)
                self.assertTrue(link.is_junction())
            else:
                link.symlink_to(target, target_is_directory=True)
                self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), target.resolve())
            yield
        finally:
            if getattr(link, "is_junction", lambda: False)():
                link.rmdir()
            elif link.is_symlink():
                link.unlink()

    def test_bounded_inventory_does_not_read_member_payloads(self):
        self.make_zip()
        with mock.patch("packages.library.archive.zipfile.ZipFile.open", side_effect=AssertionError("no decompression during inspection")):
            inventory = inspect_zip(self.archive)
        self.assertEqual([item["name"] for item in inventory], ["match/one.bin", "match/labels.csv", "other/never-extract.bin"])
        self.assertEqual(inventory[0]["size_bytes"], len(self.payload))
        self.assertFalse(inventory[0]["encrypted"])
        self.assertEqual(len(inventory[0]["crc32"]), 8)

    def test_selected_member_only_preserves_archive_and_verifies_crc_and_hash(self):
        archive_hash = self.make_zip(compression=zipfile.ZIP_DEFLATED)
        before = self.archive.read_bytes()
        result = self.extract(expected_archive_sha256=archive_hash)
        self.assertEqual(result.path, self.output)
        self.assertEqual(result.path.read_bytes(), self.payload)
        self.assertEqual(result.size_bytes, len(self.payload))
        self.assertEqual(result.sha256, hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(result.archive_sha256, archive_hash)
        self.assertEqual(result.member_name, "match/one.bin")
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertFalse((self.quota.data_root / "match").exists())
        self.assertFalse((self.quota.data_root / "other").exists())
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.output.with_name("one.bin.lock").exists())
        self.assertEqual(self.metadata()["state"], "succeeded")
        self.assertTrue(self.metadata()["crc_verified"])
        self.assertEqual(self.metadata()["archive_relative_path"], "data/source.zip")
        self.assertEqual(self.quota.active_reservations(), [])
        self.assertGreaterEqual(self.quota.snapshot()["owner_used_bytes"], self.archive.stat().st_size + len(self.payload))

    def test_expected_archive_hash_failure_is_recorded_before_decompression(self):
        archive_hash = self.make_zip()
        with mock.patch("packages.library.archive.zipfile.ZipFile.open", side_effect=AssertionError("must reject before reading member")):
            with self.assertRaises(ArchiveError) as caught:
                self.extract(expected_archive_sha256="0" * 64)
        self.assertEqual(caught.exception.code, "archive_checksum_mismatch")
        self.assertEqual(self.metadata()["archive_sha256"], archive_hash)
        self.assertEqual(self.metadata()["state"], "failed")
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.output.exists())
        self.assertEqual(self.quota.active_reservations(), [])

    def test_declared_member_size_limit_prevents_decompression(self):
        self.make_zip()
        with mock.patch("packages.library.archive.zipfile.ZipFile.open", side_effect=AssertionError("metadata size must reject first")):
            with self.assertRaises(ArchiveError) as caught:
                self.extract(max_bytes=1000)
        self.assertEqual(caught.exception.code, "size_limit")
        self.assertEqual(self.metadata()["member"]["size_bytes"], len(self.payload))
        self.assertFalse(self.partial.exists())

    def assert_compression_rejected_before_member_open(self, compression):
        payload = b"\0" * (1024 * 1024)
        archive_hash = self.make_zip(entries=[("match/one.bin", payload)], compression=compression)
        self.assertEqual(inspect_zip(self.archive)[0]["compression"], compression)
        with mock.patch("packages.library.archive.zipfile.ZipFile.open", side_effect=AssertionError("unsupported codec must not open a member")) as member_open:
            with self.assertRaises(ArchiveError) as caught:
                self.extract(max_bytes=len(payload))
        self.assertEqual(caught.exception.code, "unsupported_compression")
        member_open.assert_not_called()
        self.assertEqual(self.metadata()["error"]["code"], "unsupported_compression")
        self.assertEqual(self.metadata()["member"]["compression"], compression)
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), archive_hash)
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name("one.bin.lock").exists())
        self.assertEqual(self.quota.active_reservations(), [])

    def test_bzip2_is_rejected_before_member_open(self):
        self.assert_compression_rejected_before_member_open(zipfile.ZIP_BZIP2)

    def test_lzma_is_rejected_before_member_open(self):
        self.assert_compression_rejected_before_member_open(zipfile.ZIP_LZMA)

    def test_streaming_limit_is_independent_of_declared_size(self):
        self.make_zip(entries=[("match/one.bin", b"declared small")])
        with mock.patch("packages.library.archive.zipfile.ZipFile.open", return_value=io.BytesIO(self.payload)):
            with self.assertRaises(ArchiveError) as caught:
                self.extract(max_bytes=100_000)
        self.assertEqual(caught.exception.code, "size_limit")
        self.assertLessEqual(self.partial.stat().st_size, 100_000)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.metadata()["error"]["code"], "size_limit")

    def test_actual_crc_corruption_keeps_partial_and_never_publishes(self):
        self.make_zip()
        source = bytearray(self.archive.read_bytes())
        name_size, extra_size = struct.unpack_from("<2H", source, 26)
        source[30 + name_size + extra_size + 70_000] ^= 1
        self.archive.write_bytes(source)
        with self.assertRaises(ArchiveError) as caught:
            self.extract()
        self.assertEqual(caught.exception.code, "invalid_zip_or_crc")
        self.assertTrue(self.partial.exists())
        self.assertGreater(self.partial.stat().st_size, 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.metadata()["error"]["code"], "invalid_zip_or_crc")
        self.assertEqual(self.archive.read_bytes(), bytes(source))

    def test_duplicate_and_missing_member_are_rejected(self):
        self.make_zip(entries=[("match/one.bin", b"first"), ("match/one.bin", b"second")])
        with self.assertRaises(ArchiveError) as caught:
            self.extract()
        self.assertEqual(caught.exception.code, "member_not_unique")
        self.assertFalse(self.output.exists())
        with self.assertRaises(ArchiveError) as missing:
            extract_member(self.archive, "missing.bin", "missing.bin", quota=self.quota, max_bytes=100)
        self.assertEqual(missing.exception.code, "member_not_unique")

    def test_symlink_and_directory_members_are_rejected(self):
        link = zipfile.ZipInfo("match/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        directory = zipfile.ZipInfo("match/directory")
        directory.create_system = 3
        directory.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
        self.make_zip(entries=[(link, b"outside"), (directory, b"")])
        inventory = inspect_zip(self.archive)
        self.assertTrue(inventory[0]["is_symlink"])
        self.assertTrue(inventory[1]["is_directory"])
        for member, destination in (("match/link", "link.bin"), ("match/directory", "directory.bin")):
            with self.subTest(member=member), self.assertRaises(ArchiveError) as caught:
                extract_member(self.archive, member, destination, quota=self.quota, max_bytes=100)
            self.assertEqual(caught.exception.code, "unsafe_member_type")

    def test_encrypted_member_is_rejected_before_password_or_payload_processing(self):
        self.make_zip(entries=[("match/one.bin", b"content")])
        source = bytearray(self.archive.read_bytes())
        central = source.index(b"PK\x01\x02")
        struct.pack_into("<H", source, 6, struct.unpack_from("<H", source, 6)[0] | 1)
        struct.pack_into("<H", source, central + 8, struct.unpack_from("<H", source, central + 8)[0] | 1)
        self.archive.write_bytes(source)
        self.assertTrue(inspect_zip(self.archive)[0]["encrypted"])
        with self.assertRaises(ArchiveError) as caught:
            self.extract()
        self.assertEqual(caught.exception.code, "encrypted_member")
        self.assertFalse(self.partial.exists())

    def test_unsafe_member_names_are_never_mapped_to_output_paths(self):
        self.make_zip()
        for member in ("../one.bin", "/one.bin", "a/../one", "a//one", "a/./one", "a\\one", "C:/one", "a:one", "one\x00evil", "directory/"):
            with self.subTest(member=member), self.assertRaises(ArchiveError) as caught:
                self.extract(member=member)
            self.assertEqual(caught.exception.code, "unsafe_member_name")
        self.assertFalse(self.output.parent.exists())

    def test_inventory_limits_are_checked_before_zipfile_allocates_entries(self):
        self.make_zip()
        with mock.patch("packages.library.archive.zipfile.ZipFile", side_effect=AssertionError("preflight must reject first")):
            with self.assertRaises(ArchiveError) as members:
                inspect_zip(self.archive, max_members=2)
            self.assertEqual(members.exception.code, "inventory_limit")
            with self.assertRaises(ArchiveError) as directory:
                inspect_zip(self.archive, max_directory_bytes=1)
            self.assertEqual(directory.exception.code, "inventory_limit")

    def test_declared_directory_count_cannot_hide_extra_members(self):
        self.make_zip()
        source = bytearray(self.archive.read_bytes())
        end = source.rindex(b"PK\x05\x06")
        struct.pack_into("<2H", source, end + 8, 1, 1)
        self.archive.write_bytes(source)
        with self.assertRaises(ArchiveError) as caught:
            inspect_zip(self.archive)
        self.assertEqual(caught.exception.code, "inventory_limit")

    def test_comment_cannot_make_zipfile_select_different_unbounded_directory(self):
        self.make_zip()
        fake_end = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1, 900_000_000, 0, 1)
        with zipfile.ZipFile(self.archive, "a") as container:
            container.comment = b"comment prefix" + fake_end
        with mock.patch("packages.library.archive.zipfile.ZipFile", side_effect=AssertionError("ambiguous EOCD must reject before ZipFile")):
            with self.assertRaises(ArchiveError) as caught:
                inspect_zip(self.archive)
        self.assertEqual(caught.exception.code, "invalid_zip")

    def test_hidden_zip64_locator_cannot_override_classic_directory_bounds(self):
        info = zipfile.ZipInfo("match/one.bin")
        zip64_end = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, 1, 1, 900_000_000, 0)
        locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, 0, 1)
        info.comment = zip64_end + locator
        self.make_zip(entries=[(info, b"payload")])
        with mock.patch("packages.library.archive.zipfile.ZipFile", side_effect=AssertionError("ZIP64 locator must reject before ZipFile")):
            with self.assertRaises(ArchiveError) as caught:
                inspect_zip(self.archive)
        self.assertEqual(caught.exception.code, "unsupported_zip64")

    def test_failed_record_write_preserves_original_archive_hash_error(self):
        self.make_zip()
        with mock.patch("packages.library.archive._save_metadata", side_effect=OSError("record disk failure")):
            with self.assertRaises(ArchiveError) as caught:
                self.extract(expected_archive_sha256="0" * 64)
        self.assertEqual(caught.exception.code, "archive_checksum_mismatch")
        self.assertTrue(any("could not be persisted" in note for note in caught.exception.__notes__))
        self.assertFalse(self.record.exists())
        self.assertFalse(self.output.exists())
        self.assertEqual(self.quota.active_reservations(), [])

    def test_failed_record_write_preserves_original_crc_error_and_partial(self):
        self.make_zip()
        source = bytearray(self.archive.read_bytes())
        name_size, extra_size = struct.unpack_from("<2H", source, 26)
        source[30 + name_size + extra_size + 70_000] ^= 1
        self.archive.write_bytes(source)
        from packages.library import archive
        save = archive._save_metadata

        def cannot_save_failure(path, metadata, quota):
            if metadata["state"] == "failed":
                raise OSError("record disk failure")
            return save(path, metadata, quota)

        with mock.patch("packages.library.archive._save_metadata", side_effect=cannot_save_failure):
            with self.assertRaises(ArchiveError) as caught:
                self.extract()
        self.assertEqual(caught.exception.code, "invalid_zip_or_crc")
        self.assertIsInstance(caught.exception.__cause__, zipfile.BadZipFile)
        self.assertTrue(any("could not be persisted" in note for note in caught.exception.__notes__))
        self.assertTrue(self.partial.exists())
        self.assertFalse(self.output.exists())

    def test_failed_record_reservation_preserves_original_validation_error(self):
        self.make_zip()
        with mock.patch.object(self.quota, "reserve", side_effect=QuotaExceeded("full")):
            with self.assertRaises(ArchiveError) as caught:
                self.extract(expected_archive_sha256="0" * 64)
        self.assertEqual(caught.exception.code, "archive_checksum_mismatch")
        self.assertTrue(any("could not be reserved" in note for note in caught.exception.__notes__))
        self.assertFalse(self.output.exists())

    def test_existing_destination_record_partial_and_shared_lock_are_preserved(self):
        self.make_zip()
        self.output.parent.mkdir()
        for path in (self.output, self.record, self.partial, self.output.with_name("one.bin.lock")):
            with self.subTest(path=path.name):
                path.write_bytes(b"existing data")
                if path.name.endswith(".lock"):
                    with self.assertRaises(ArchiveError) as caught:
                        self.extract()
                    self.assertEqual(caught.exception.code, "locked")
                else:
                    with self.assertRaises(FileExistsError):
                        self.extract()
                self.assertEqual(path.read_bytes(), b"existing data")
                path.unlink()
        self.assertEqual(self.quota.active_reservations(), [])

    def test_atomic_publication_does_not_overwrite_racing_destination(self):
        self.make_zip()
        original_link = os.link

        def race(source, destination, **kwargs):
            Path(destination).write_bytes(b"racing existing file")
            return original_link(source, destination, **kwargs)

        with mock.patch("packages.library.archive.os.link", side_effect=race):
            with self.assertRaises(FileExistsError):
                self.extract()
        self.assertEqual(self.output.read_bytes(), b"racing existing file")
        self.assertEqual(self.partial.read_bytes(), self.payload)
        self.assertEqual(self.metadata()["state"], "failed")

    def test_archive_and_member_both_count_against_quota(self):
        self.make_zip()
        limited = QuotaManager(self.quota.data_root, allow_test_root=True, min_free_bytes=0,
                               owner_limit_bytes=self.archive.stat().st_size + len(self.payload))
        with self.assertRaises(QuotaExceeded):
            extract_member(self.archive, "match/one.bin", "selected/one.bin", quota=limited, max_bytes=len(self.payload))
        self.assertFalse(self.output.exists())
        self.assertFalse(self.record.exists())

    def test_source_archive_outside_data_and_source_collision_are_rejected(self):
        self.make_zip()
        outside = self.root / "outside.zip"
        outside.write_bytes(self.archive.read_bytes())
        with self.assertRaises(UnsafePath):
            extract_member(outside, "match/one.bin", "one.bin", quota=self.quota, max_bytes=len(self.payload))
        with self.assertRaises(UnsafePath):
            extract_member(self.archive, "match/one.bin", "source.zip", quota=self.quota, max_bytes=len(self.payload))

    def test_actual_source_and_destination_directory_links_are_rejected(self):
        self.make_zip()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "source.zip").write_bytes(self.archive.read_bytes())
        marker = outside / "preserve.txt"
        marker.write_bytes(b"target must stay unchanged")
        source_link = self.quota.data_root / "linked-source"
        with self.directory_link(source_link, outside):
            with self.assertRaises(UnsafePath):
                extract_member(source_link / "source.zip", "match/one.bin", "one.bin", quota=self.quota, max_bytes=len(self.payload))
            with self.assertRaises(UnsafePath):
                inspect_zip(source_link / "source.zip")
        with self.directory_link(self.output.parent, outside):
            with self.assertRaises(UnsafePath):
                self.extract()
        self.assertEqual(marker.read_bytes(), b"target must stay unchanged")
        self.assertFalse((outside / "one.bin").exists())
        self.assertEqual(self.quota.active_reservations(), [])


if __name__ == "__main__":
    unittest.main()
