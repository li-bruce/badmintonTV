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

    def make_zip64(self, *, sentinels=False):
        # Force genuine stdlib ZIP64 output using tiny fixture payloads, never
        # allocate a multi-GB temporary file merely to exercise 64-bit metadata.
        with mock.patch.object(zipfile, "ZIP64_LIMIT", 1):
            self.make_zip(compression=zipfile.ZIP_DEFLATED)
        raw = bytearray(self.archive.read_bytes())
        end = raw.rindex(b"PK\x05\x06")
        locator = end - 20
        record = struct.unpack_from("<Q", raw, locator + 8)[0]
        self.assertEqual(raw[record:record + 4], b"PK\x06\x06")
        if sentinels:
            struct.pack_into("<2H2I", raw, end + 8, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
            self.archive.write_bytes(raw)
        return raw, record, locator, end

    def assert_rejected_before_zipfile(self, code):
        with mock.patch("packages.library.archive.zipfile.ZipFile", side_effect=AssertionError("preflight must reject before allocation")) as constructor:
            with self.assertRaises(ArchiveError) as caught:
                inspect_zip(self.archive)
        self.assertEqual(caught.exception.code, code)
        constructor.assert_not_called()

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
        self.assertEqual(caught.exception.code, "invalid_zip64")

    def test_zip64_fixed_records_and_member_extras_extract_successfully(self):
        self.make_zip64()
        inventory = inspect_zip(self.archive)
        self.assertEqual(len(inventory), 3)
        self.assertEqual(inventory[0]["size_bytes"], len(self.payload))
        expected = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        result = self.extract(expected_archive_sha256=expected)
        self.assertEqual(result.path.read_bytes(), self.payload)
        self.assertEqual(result.archive_sha256, expected)
        self.assertTrue(self.metadata()["crc_verified"])

    def test_zip64_classic_sentinels_resolve_to_checked_64bit_values(self):
        self.make_zip64(sentinels=True)
        self.assertEqual(len(inspect_zip(self.archive)), 3)
        self.assertEqual(self.extract().path.read_bytes(), self.payload)

    def test_zip64_locator_position_and_classic_fields_must_agree(self):
        for mutation in ("locator_offset", "classic_count", "classic_size", "missing_locator", "truncated_record"):
            with self.subTest(mutation=mutation):
                raw, record, locator, end = self.make_zip64()
                if mutation == "locator_offset":
                    struct.pack_into("<Q", raw, locator + 8, record + 1)
                elif mutation == "classic_count":
                    struct.pack_into("<H", raw, end + 10, 4)
                elif mutation == "classic_size":
                    struct.pack_into("<I", raw, end + 12, 1)
                elif mutation == "missing_locator":
                    raw[locator:locator + 4] = b"BAD!"
                    struct.pack_into("<I", raw, end + 16, 0xFFFFFFFF)
                else:
                    del raw[record + 24:record + 32]
                self.archive.write_bytes(raw)
                self.assert_rejected_before_zipfile("invalid_zip64")

    def test_zip64_multivolume_and_extended_end_records_are_rejected(self):
        for offset_name in ("locator_disk", "locator_disks", "record_disk", "directory_disk", "count_per_disk", "extension"):
            with self.subTest(field=offset_name):
                raw, record, locator, _ = self.make_zip64()
                expected = "unsupported_multivolume"
                if offset_name == "locator_disk":
                    struct.pack_into("<I", raw, locator + 4, 1)
                elif offset_name == "locator_disks":
                    struct.pack_into("<I", raw, locator + 16, 2)
                elif offset_name == "record_disk":
                    struct.pack_into("<I", raw, record + 16, 1)
                elif offset_name == "directory_disk":
                    struct.pack_into("<I", raw, record + 20, 1)
                elif offset_name == "count_per_disk":
                    struct.pack_into("<Q", raw, record + 24, 1)
                else:
                    struct.pack_into("<Q", raw, record + 4, 45)
                    expected = "unsupported_zip64_extension"
                self.archive.write_bytes(raw)
                self.assert_rejected_before_zipfile(expected)

    def test_zip64_directory_limits_apply_before_allocation(self):
        for field in ("count", "bytes"):
            with self.subTest(field=field):
                raw, record, _, _ = self.make_zip64(sentinels=True)
                if field == "count":
                    struct.pack_into("<2Q", raw, record + 24, 10_001, 10_001)
                else:
                    struct.pack_into("<Q", raw, record + 40, 16_777_217)
                self.archive.write_bytes(raw)
                self.assert_rejected_before_zipfile("inventory_limit")

    def test_zip64_directory_boundary_and_member_extra_corruption_are_rejected(self):
        for mutation in ("directory_offset", "missing_extra", "short_extra", "foreign_disk", "out_of_bounds_member"):
            with self.subTest(mutation=mutation):
                raw, record, _, end = self.make_zip64(sentinels=True)
                central = struct.unpack_from("<Q", raw, record + 48)[0]
                name_size, extra_size, comment_size = struct.unpack_from("<3H", raw, central + 28)
                extra = central + 46 + name_size
                expected = "invalid_zip64"
                if mutation == "directory_offset":
                    struct.pack_into("<Q", raw, record + 48, central + 1)
                    expected = "invalid_zip"
                elif mutation == "missing_extra":
                    struct.pack_into("<H", raw, extra, 0xCAFE)
                elif mutation == "short_extra":
                    struct.pack_into("<H", raw, extra + 2, 8)
                elif mutation == "foreign_disk":
                    struct.pack_into("<H", raw, central + 34, 1)
                    expected = "unsupported_multivolume"
                else:
                    second = central + 46 + name_size + extra_size + comment_size
                    second_name_size = struct.unpack_from("<H", raw, second + 28)[0]
                    # The second forced ZIP64 entry carries size, compressed
                    # size, and its (> ZIP64_LIMIT=1) local-header offset.
                    second_extra = second + 46 + second_name_size
                    struct.pack_into("<Q", raw, second_extra + 4 + 16, 0x1_0000_0000)
                    expected = "invalid_zip"
                self.archive.write_bytes(raw)
                self.assert_rejected_before_zipfile(expected)

    def test_duplicate_zip64_member_extras_are_rejected(self):
        info = zipfile.ZipInfo("match/one.bin")
        info.extra = struct.pack("<2H", 1, 0) * 2
        self.make_zip(entries=[(info, b"payload")])
        self.assert_rejected_before_zipfile("invalid_zip64")

    def test_zip64_offsets_above_4gib_use_bounded_virtual_reads(self):
        self.make_zip(entries=[("match/one.bin", b"payload")])
        raw = self.archive.read_bytes()
        central_start = raw.index(b"PK\x01\x02")
        local = raw[:central_start]
        central_header = bytearray(raw[central_start:central_start + 46])
        name_size = struct.unpack_from("<H", central_header, 28)[0]
        name = raw[central_start + 46:central_start + 46 + name_size]
        base = 0x1_0000_0000 + 123
        extra = struct.pack("<2HQ", 1, 8, base)
        struct.pack_into("<H", central_header, 6, 45)
        struct.pack_into("<H", central_header, 30, len(extra))
        struct.pack_into("<I", central_header, 42, 0xFFFFFFFF)
        central = bytes(central_header) + name + extra
        directory_offset = base + len(local)
        record_offset = directory_offset + len(central)
        end = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, 1, 1, len(central), directory_offset)
        end += struct.pack("<4sIQI", b"PK\x06\x07", 0, record_offset, 1)
        end += struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1, len(central), 0xFFFFFFFF, 0)
        regions = [(base, local), (directory_offset, central), (record_offset, end)]
        virtual_size = record_offset + len(end)

        class VirtualZip(io.BytesIO):
            position = 0
            largest_read = 0

            def seek(self, offset, whence=0):
                origin = 0 if whence == 0 else self.position if whence == 1 else virtual_size
                self.position = origin + offset
                if self.position < 0:
                    raise OSError("negative seek")
                return self.position

            def tell(self):
                return self.position

            def read(self, size=-1):
                if size < 0 or size > 1_000_000:
                    raise AssertionError("Test must not allocate a virtual multi-GB archive")
                size = min(size, max(0, virtual_size - self.position))
                self.largest_read = max(self.largest_read, size)
                chunk = bytearray(size)
                for start, contents in regions:
                    left, right = max(start, self.position), min(start + len(contents), self.position + size)
                    if right > left:
                        chunk[left - self.position:right - self.position] = contents[left - start:right - start]
                self.position += size
                return bytes(chunk)

        stream = VirtualZip()
        with mock.patch.object(Path, "open", return_value=stream):
            inventory = inspect_zip(self.archive)
        self.assertEqual(inventory[0]["name"], "match/one.bin")
        self.assertEqual(inventory[0]["size_bytes"], len(b"payload"))
        self.assertLessEqual(stream.largest_read, 65_557)

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
