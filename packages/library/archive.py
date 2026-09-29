"""Inspect ZIP directories and extract one explicitly selected, bounded member.

The archive remains read-only in the library owner and is counted alongside the
new member. No extractall, implicit path mapping, or partial-file resume is used.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import struct
import uuid
import zipfile

from .storage import QuotaManager, UnsafePath


MAX_MEMBERS = 10_000
MAX_DIRECTORY_BYTES = 16_777_216
METADATA_ALLOWANCE_BYTES = 65_536
CHUNK_BYTES = 65_536


class ArchiveError(RuntimeError):
    def __init__(self, code: str, message: str, metadata_path: Path | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.metadata_path = metadata_path


@dataclass(frozen=True)
class ExtractionResult:
    path: Path
    size_bytes: int
    sha256: str
    archive_sha256: str
    member_name: str
    metadata_path: Path


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(stream) -> str:
    stream.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


def _safe_source_path(path: Path | str) -> Path:
    source = Path(os.path.abspath(path))
    for ancestor in (source, *source.parents):
        if ancestor.is_symlink() or getattr(ancestor, "is_junction", lambda: False)():
            raise UnsafePath("ZIP source paths cannot include symbolic links or junctions")
    if not source.is_file():
        raise ArchiveError("missing_archive", "Source ZIP is not an existing regular file")
    return source


def _strict_member_name(name: str) -> None:
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 4096:
        raise ArchiveError("unsafe_member_name", "Member name must be a nonempty POSIX name of at most 4096 UTF-8 bytes")
    if "\\" in name or "\x00" in name or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive:
        raise ArchiveError("unsafe_member_name", "Absolute, Windows, and NUL-containing member names are forbidden")
    if any(part in ("", ".", "..") or ":" in part for part in name.split("/")):
        raise ArchiveError("unsafe_member_name", "Empty, dot, parent, and alternate-stream member components are forbidden")


def _zip64_directory(stream, end_offset: int, classic: tuple) -> tuple[int, int, int, int]:
    """Resolve one fixed ZIP64 EOCD and verify its locator/classic agreement.

    Python 3.12 zipfile ignores the locator's offset and assumes a 56-byte EOCD
    immediately before it. Require both interpretations to identify the same
    record; extensible-data sectors need another parser and are rejected here.
    """
    locator_offset = end_offset - 20
    stream.seek(locator_offset)
    locator = stream.read(20)
    if len(locator) != 20:
        raise ArchiveError("invalid_zip64", "Truncated ZIP64 locator")
    signature, record_disk, record_offset, disks = struct.unpack("<4sIQI", locator)
    if signature != b"PK\x06\x07":
        raise ArchiveError("invalid_zip64", "Missing ZIP64 locator")
    if record_disk != 0 or disks != 1:
        raise ArchiveError("unsupported_multivolume", "ZIP64 locator must describe exactly one disk")
    if record_offset > locator_offset - 56:
        raise ArchiveError("invalid_zip64", "ZIP64 end record is outside its permitted bounds")
    stream.seek(record_offset)
    raw = stream.read(56)
    if len(raw) != 56:
        raise ArchiveError("invalid_zip64", "Truncated ZIP64 end record")
    signature, length, _, needed, disk, directory_disk, disk_entries, entries, size, offset = struct.unpack("<4sQ2H2I4Q", raw)
    if signature != b"PK\x06\x06" or needed < 45:
        raise ArchiveError("invalid_zip64", "ZIP64 end record signature or minimum version is invalid")
    if length != 44:
        raise ArchiveError("unsupported_zip64_extension", "ZIP64 extensible-data sectors are not supported")
    if record_offset + 56 != locator_offset:
        raise ArchiveError("invalid_zip64", "ZIP64 locator and fixed end-record positions disagree")
    if disk != 0 or directory_disk != 0 or disk_entries != entries:
        raise ArchiveError("unsupported_multivolume", "ZIP64 end record must describe a single-volume directory")
    expanded = (disk, directory_disk, disk_entries, entries, size, offset)
    for previous, actual, sentinel in zip(classic, expanded, (0xFFFF,) * 4 + (0xFFFFFFFF,) * 2):
        if previous != sentinel and previous != actual:
            raise ArchiveError("invalid_zip64", "Classic and ZIP64 end-record fields disagree")
    return entries, size, offset, record_offset


def _member_bounds(header: bytes, extra: bytes, directory_offset: int) -> None:
    """Validate per-member ZIP64 sizes/offset/disk before ZipInfo decodes extras."""
    compressed, size = struct.unpack_from("<2I", header, 20)
    disk = struct.unpack_from("<H", header, 34)[0]
    offset = struct.unpack_from("<I", header, 42)[0]
    values = [size, compressed, offset, disk]
    sentinels = (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF)
    required = [index for index, (value, sentinel) in enumerate(zip(values, sentinels)) if value == sentinel]
    seen_zip64 = False
    position = 0
    while position < len(extra):
        if len(extra) - position < 4:
            raise ArchiveError("invalid_zip", "Truncated ZIP extra-field header")
        kind, length = struct.unpack_from("<2H", extra, position)
        position += 4
        if position + length > len(extra):
            raise ArchiveError("invalid_zip", "ZIP extra-field length exceeds its declared boundary")
        if kind == 1:
            if seen_zip64:
                raise ArchiveError("invalid_zip64", "Duplicate ZIP64 member extra fields are ambiguous")
            seen_zip64 = True
            expected = sum(4 if index == 3 else 8 for index in required)
            if length != expected:
                raise ArchiveError("invalid_zip64", "ZIP64 member extra fields must match the sentinel fields in order")
            cursor = position
            for index in required:
                fmt = "<I" if index == 3 else "<Q"
                values[index] = struct.unpack_from(fmt, extra, cursor)[0]
                cursor += struct.calcsize(fmt)
        position += length
    if required and not seen_zip64:
        raise ArchiveError("invalid_zip64", "ZIP64 member sentinel has no matching extra field")
    _, compressed, offset, disk = values
    if disk != 0:
        raise ArchiveError("unsupported_multivolume", "A ZIP member refers to another disk")
    if offset + 30 + compressed > directory_offset:
        raise ArchiveError("invalid_zip", "ZIP member offset or compressed data exceeds the file-data region")


def _preflight_directory(stream, max_members: int, max_directory_bytes: int) -> None:
    """Bound ordinary/ZIP64 single-volume directory parsing before ZipFile.

    ZIP64 fixed end records are supported. Extended ZIP64 end records,
    appended trailers, and multi-volume archives fail explicitly.
    """
    stream.seek(0, os.SEEK_END)
    archive_size = stream.tell()
    tail_size = min(archive_size, 65_535 + 22)
    stream.seek(archive_size - tail_size)
    tail = stream.read(tail_size)
    position = tail.rfind(b"PK\x05\x06")
    # Match ZipFile's last-signature selection. Falling back to an earlier end
    # record could validate different bounds from the directory it later loads.
    if position < 0 or position + 22 > len(tail):
        raise ArchiveError("invalid_zip", "ZIP end record is missing, truncated, or has unsupported trailing bytes")
    record = struct.unpack_from("<4s4H2IH", tail, position)
    if position + 22 + record[-1] != len(tail):
        raise ArchiveError("invalid_zip", "ZIP end-record comment length or embedded signature is ambiguous")
    _, disk, directory_disk, disk_entries, entries, directory_size, directory_offset, _ = record
    end_offset = archive_size - tail_size + position
    directory_end = end_offset
    has_locator = False
    if end_offset >= 20:
        stream.seek(end_offset - 20)
        has_locator = stream.read(4) == b"PK\x06\x07"
    if has_locator:
        entries, directory_size, directory_offset, directory_end = _zip64_directory(stream, end_offset, record[1:7])
    else:
        if 0xFFFF in (disk, directory_disk, disk_entries, entries) or 0xFFFFFFFF in (directory_size, directory_offset):
            raise ArchiveError("invalid_zip64", "ZIP64 sentinel fields require a valid ZIP64 locator and end record")
        if disk != 0 or directory_disk != 0 or disk_entries != entries:
            raise ArchiveError("unsupported_multivolume", "Multi-volume ZIPs are not supported")
    if entries > max_members or directory_size > max_directory_bytes:
        raise ArchiveError("inventory_limit", "ZIP directory exceeds the configured member or metadata limit")
    if directory_offset + directory_size != directory_end:
        raise ArchiveError("invalid_zip", "ZIP central-directory offset/length does not match the end record")
    stream.seek(directory_offset)
    consumed, seen = 0, 0
    while consumed < directory_size:
        header = stream.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise ArchiveError("invalid_zip", "Malformed ZIP central-directory entry")
        name_size, extra_size, comment_size = struct.unpack_from("<3H", header, 28)
        consumed += 46 + name_size + extra_size + comment_size
        seen += 1
        if consumed > directory_size or seen > max_members or seen > entries:
            raise ArchiveError("inventory_limit", "ZIP directory count or entry lengths exceed their declared bounds")
        stream.seek(name_size, os.SEEK_CUR)
        extra = stream.read(extra_size)
        if len(extra) != extra_size:
            raise ArchiveError("invalid_zip", "ZIP member extra fields are truncated")
        _member_bounds(header, extra, directory_offset)
        stream.seek(comment_size, os.SEEK_CUR)
    if seen != entries:
        raise ArchiveError("invalid_zip", "ZIP directory entry count does not match its end record")
    stream.seek(0)


def _inventory_item(info: zipfile.ZipInfo) -> dict:
    mode = info.external_attr >> 16
    return {
        "name": info.orig_filename,
        "size_bytes": info.file_size,
        "compressed_bytes": info.compress_size,
        "compression": info.compress_type,
        "encrypted": bool(info.flag_bits & 1),
        "is_directory": info.is_dir() or bool(info.external_attr & 0x10),
        "is_symlink": stat.S_ISLNK(mode),
        "crc32": f"{info.CRC:08x}",
    }


def inspect_zip(
    path: Path | str, *, max_members: int = MAX_MEMBERS,
    max_directory_bytes: int = MAX_DIRECTORY_BYTES,
) -> list[dict]:
    """Return bounded metadata only; does not decompress any archive member."""
    if type(max_members) is not int or not 0 < max_members <= MAX_MEMBERS:
        raise ValueError(f"max_members must be in 1..{MAX_MEMBERS}")
    if type(max_directory_bytes) is not int or not 0 < max_directory_bytes <= MAX_DIRECTORY_BYTES:
        raise ValueError(f"max_directory_bytes must be in 1..{MAX_DIRECTORY_BYTES}")
    try:
        with _safe_source_path(path).open("rb") as source:
            _preflight_directory(source, max_members, max_directory_bytes)
            with zipfile.ZipFile(source) as archive:
                return [_inventory_item(info) for info in archive.infolist()]
    except zipfile.BadZipFile as error:
        raise ArchiveError("invalid_zip", "ZIP directory could not be decoded") from error


def _save_metadata(path: Path, metadata: dict, quota: QuotaManager) -> None:
    quota.resolve_path(path.relative_to(quota.data_root))
    metadata["updated_at"] = _utcnow()
    payload = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
    if len(payload) > METADATA_ALLOWANCE_BYTES // 4:
        raise ArchiveError("metadata_limit", "Extraction metadata exceeds its bounded allowance", path)
    temporary = path.with_name(path.name + ".tmp." + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _archive_error(error: BaseException, metadata_path: Path) -> ArchiveError:
    if isinstance(error, ArchiveError):
        error.metadata_path = metadata_path
        return error
    if isinstance(error, zipfile.BadZipFile):
        return ArchiveError("invalid_zip_or_crc", "ZIP structure or member CRC validation failed", metadata_path)
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return ArchiveError("interrupted", "Extraction interrupted before publication", metadata_path)
    return ArchiveError("extraction_failed", f"Extraction failed: {type(error).__name__}", metadata_path)


def extract_member(
    archive: Path | str, member_name: str, relative_path: Path | str, *,
    quota: QuotaManager, max_bytes: int, expected_archive_sha256: str | None = None,
) -> ExtractionResult:
    """Extract exactly one selected member under the existing owner quota.

    The original ZIP must already be within ``quota.data_root``. The payload is
    streamed to ``.extract.part``; ``.lock`` is shared with the downloader and
    ``.extract.json`` records source hash, member CRC, outcome, and errors. Failed
    partials/records are retained and never silently reused. Crashed locks and
    reservations require explicit recovery after confirming no writer is active.
    Only STORED and DEFLATED members are supported: ZipExtFile's other codecs
    can expand unbounded internal buffers even when read() requests are small.
    """
    _strict_member_name(member_name)
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if expected_archive_sha256 is not None:
        expected_archive_sha256 = expected_archive_sha256.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_archive_sha256):
            raise ValueError("expected_archive_sha256 must be 64 hexadecimal digits")
    source_path = Path(os.path.abspath(archive))
    try:
        source_relative = source_path.relative_to(quota.data_root)
    except ValueError as error:
        raise UnsafePath("Source ZIP must live under the library data owner to be counted") from error
    quota.resolve_path(source_relative)
    _safe_source_path(source_path)
    destination = quota.resolve_path(relative_path)
    if destination.name.startswith(".library-") or destination.name.endswith((".part", ".lock", ".download.json", ".extract.json")):
        raise UnsafePath("Destination name conflicts with library bookkeeping")
    partial = destination.with_name(destination.name + ".extract.part")
    record_path = destination.with_name(destination.name + ".extract.json")
    lock_path = destination.with_name(destination.name + ".lock")
    for path in (partial, record_path, lock_path):
        quota.resolve_path(path.relative_to(quota.data_root))
    if source_path in (destination, partial, record_path, lock_path):
        raise UnsafePath("Extraction destination or bookkeeping would collide with the source ZIP")
    for path in (destination, partial, record_path):
        if path.exists():
            raise FileExistsError(f"Existing extraction output/record is preserved: {path}")
    metadata = {
        "schema_version": "1.0", "operation": "extract_zip_member",
        "archive_relative_path": source_path.relative_to(quota.project_root).as_posix(),
        "relative_path": destination.relative_to(quota.project_root).as_posix(),
        "member_name": member_name, "max_bytes": max_bytes,
        "expected_archive_sha256": expected_archive_sha256,
        "created_at": _utcnow(), "state": "validating",
    }
    with ExitStack() as contexts:
        validation_error = None
        try:
            source = contexts.enter_context(source_path.open("rb"))
            archive_hash = _sha256(source)
            metadata["archive_sha256"] = archive_hash
            if expected_archive_sha256 is not None and archive_hash != expected_archive_sha256:
                raise ArchiveError("archive_checksum_mismatch", "Source ZIP SHA256 differs from the expected hash")
            _preflight_directory(source, MAX_MEMBERS, MAX_DIRECTORY_BYTES)
            container = contexts.enter_context(zipfile.ZipFile(source))
            matches = [info for info in container.infolist() if info.orig_filename == member_name or info.filename == member_name]
            if len(matches) != 1:
                raise ArchiveError("member_not_unique", "Selected ZIP member must exist exactly once")
            info = matches[0]
            _strict_member_name(info.orig_filename)
            if info.orig_filename != info.filename:
                raise ArchiveError("unsafe_member_name", "ZIP member name was normalized or truncated")
            member = _inventory_item(info)
            metadata["member"] = member
            if member["is_directory"] or member["is_symlink"] or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ArchiveError("unsafe_member_type", "Selected ZIP member must be a regular file")
            if member["encrypted"]:
                raise ArchiveError("encrypted_member", "Encrypted ZIP members are not extracted")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ArchiveError("unsupported_compression", "Only ZIP_STORED and ZIP_DEFLATED members support bounded extraction")
            if info.file_size > max_bytes:
                raise ArchiveError("size_limit", "Selected member's declared size exceeds max_bytes")
        except Exception as error:
            validation_error = _archive_error(error, record_path)
        # Failed preflights reserve only enough to persist a failure record.
        peak = METADATA_ALLOWANCE_BYTES + (max_bytes if validation_error is None else 0)
        try:
            reservation = quota.reserve(peak, purpose=f"extract:{destination.relative_to(quota.data_root).as_posix()}")
        except Exception as reservation_error:
            if validation_error is not None:
                validation_error.add_note(f"Failure record could not be reserved: {type(reservation_error).__name__}")
                raise validation_error from reservation_error
            raise
        with reservation:
            destination.parent.mkdir(parents=True, exist_ok=True)
            quota.resolve_path(relative_path)
            primary_error = None
            try:
                lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as error:
                raise ArchiveError("locked", "Another active or interrupted writer owns the destination", record_path) from error
            try:
                with os.fdopen(lock_fd, "w", encoding="utf-8") as lock_stream:
                    json.dump({"pid": os.getpid(), "reservation_id": reservation.reservation_id, "created_at": _utcnow()}, lock_stream)
                    lock_stream.flush()
                    os.fsync(lock_stream.fileno())
                for path in (destination, partial, record_path):
                    if path.exists():
                        raise FileExistsError(f"Existing extraction output/record is preserved: {path}")
                metadata.update({"reservation_id": reservation.reservation_id, "peak_bytes": peak})
                if validation_error is not None:
                    raise validation_error
                _save_metadata(record_path, metadata, quota)
                metadata["state"] = "extracting"
                _save_metadata(record_path, metadata, quota)
                digest, size = hashlib.sha256(), 0
                with container.open(info, "r") as selected, partial.open("xb") as output:
                    while True:
                        chunk = selected.read(min(CHUNK_BYTES, max_bytes - size + 1))
                        if not chunk:
                            break
                        if size + len(chunk) > max_bytes:
                            raise ArchiveError("size_limit", "Decompressed member exceeded the streaming byte limit")
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                # ZipExtFile validates CRC on reaching EOF. Verify size too.
                if size != info.file_size:
                    raise ArchiveError("member_size_mismatch", "Decompressed size disagrees with ZIP directory metadata")
                if _sha256(source) != archive_hash:
                    raise ArchiveError("archive_changed", "Source ZIP changed while extracting; output will not be published")
                actual_hash = digest.hexdigest()
                quota.resolve_path(relative_path)
                os.link(partial, destination, follow_symlinks=False)
                partial.unlink()
                metadata.update({"state": "succeeded", "size_bytes": size, "sha256": actual_hash, "crc_verified": True, "completed_at": _utcnow()})
                _save_metadata(record_path, metadata, quota)
                return ExtractionResult(destination, size, actual_hash, archive_hash, member_name, record_path)
            except BaseException as error:
                failure = _archive_error(error, record_path)
                primary_error = error if isinstance(error, (KeyboardInterrupt, SystemExit, FileExistsError)) else failure
                # Never replace an unknown record that raced with lock creation.
                if not isinstance(error, FileExistsError) or metadata.get("reservation_id") == reservation.reservation_id:
                    try:
                        metadata.update({"state": "failed", "size_bytes": partial.stat().st_size if partial.exists() else 0,
                                         "error": {"code": failure.code, "message": str(failure), "at": _utcnow()}})
                        _save_metadata(record_path, metadata, quota)
                    except Exception as record_error:
                        primary_error.add_note(f"Failure record could not be persisted: {type(record_error).__name__}")
                if isinstance(error, (KeyboardInterrupt, SystemExit, FileExistsError)):
                    raise
                if failure is error:
                    raise
                raise failure from error
            finally:
                try:
                    lock_path.unlink()
                except OSError as cleanup_error:
                    if primary_error is None:
                        raise
                    primary_error.add_note(f"Destination lock cleanup failed: {type(cleanup_error).__name__}")
