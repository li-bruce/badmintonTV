"""Bounded HTTP downloads with durable provenance and validator-checked resume."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .storage import QuotaManager, UnsafePath


METADATA_ALLOWANCE_BYTES = 65_536
CHUNK_BYTES = 65_536


class DownloadError(RuntimeError):
    def __init__(self, code: str, message: str, metadata_path: Path | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.metadata_path = metadata_path


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    size_bytes: int
    sha256: str
    metadata_path: Path
    resumed_bytes: int


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Only HTTP(S) download URLs are accepted")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Embedded URL credentials are not accepted")
    if len(url) > 4096:
        raise ValueError("URL exceeds 4096 characters")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        _validate_url(newurl)
        if request.full_url.startswith("https:") and not newurl.startswith("https:"):
            raise DownloadError("unsafe_redirect", "HTTPS to HTTP redirects are refused")
        return super().redirect_request(request, response, code, message, headers, newurl)


def _save_metadata(path: Path, metadata: dict, quota: QuotaManager) -> None:
    quota.resolve_path(path.relative_to(quota.data_root))
    metadata["updated_at"] = _utcnow()
    payload = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
    # Includes room for atomic old/new copies, lock, and SQLite growth.
    if len(payload) > METADATA_ALLOWANCE_BYTES // 4:
        raise DownloadError("metadata_too_large", "Download metadata exceeds bounded allowance", path)
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


def _validator(headers) -> tuple[str | None, str | None]:
    etag = headers.get("ETag")
    if etag and not etag.lstrip().startswith("W/"):
        return "ETag", etag
    modified = headers.get("Last-Modified")
    return ("Last-Modified", modified) if modified else (None, None)


def _content_length(headers) -> int | None:
    value = headers.get("Content-Length")
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]+", value.strip()):
        raise DownloadError("invalid_length", "Invalid Content-Length")
    return int(value)


def download(
    url: str,
    relative_path: Path | str,
    *,
    quota: QuotaManager,
    max_bytes: int,
    expected_sha256: str | None = None,
    peak_bytes: int | None = None,
    timeout: float = 30,
    resume: bool = True,
) -> DownloadResult:
    """Download to a path relative to the data owner, without replacing files.

    ``max_bytes`` limits the complete payload, including any retained partial.
    ``peak_bytes`` reserves additional extraction/derivative headroom when given;
    it must cover ``max_bytes + 65536``. A returned reservation is not held after
    this download: subsequent extraction must take its own reservation.

    Errors retain the partial file and a bounded attempt history. A process kill
    also retains its exclusive .lock and reservation; recovery is deliberately
    manual, after confirming that the writer has stopped.
    """
    _validate_url(url)
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a finite positive integer")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if expected_sha256 is not None:
        expected_sha256 = expected_sha256.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("expected_sha256 must be a 64-digit SHA256 hex digest")
    minimum_peak = max_bytes + METADATA_ALLOWANCE_BYTES
    if peak_bytes is None:
        peak_bytes = minimum_peak
    if type(peak_bytes) is not int or peak_bytes < minimum_peak:
        raise ValueError("peak_bytes must cover max_bytes plus the 65536-byte metadata allowance")
    path = quota.resolve_path(relative_path)
    if path.name.startswith(".library-") or path.name.endswith((".part", ".lock", ".download.json")):
        raise UnsafePath("Download name conflicts with library bookkeeping files")
    partial = path.with_name(path.name + ".part")
    metadata_path = path.with_name(path.name + ".download.json")
    lock_path = path.with_name(path.name + ".lock")
    for candidate in (partial, metadata_path, lock_path):
        quota.resolve_path(candidate.relative_to(quota.data_root))
    if path.exists():
        raise FileExistsError(f"Destination already exists and will not be overwritten: {path}")

    with quota.reserve(peak_bytes, purpose=f"download:{path.relative_to(quota.data_root).as_posix()}") as reservation:
        path.parent.mkdir(parents=True, exist_ok=True)
        quota.resolve_path(relative_path)
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise DownloadError("locked", "An active or interrupted download owns the destination lock", metadata_path) from error
        metadata: dict | None = None
        offset = 0
        try:
            with os.fdopen(lock_fd, "w", encoding="utf-8") as lock_stream:
                json.dump({"pid": os.getpid(), "created_at": _utcnow(), "reservation_id": reservation.reservation_id}, lock_stream)
                lock_stream.flush()
                os.fsync(lock_stream.fileno())
            if path.exists():
                raise FileExistsError(f"Destination already exists: {path}")
            if metadata_path.exists():
                if metadata_path.stat().st_size > METADATA_ALLOWANCE_BYTES // 4:
                    raise DownloadError("invalid_metadata", "Existing download metadata is too large", metadata_path)
                saved = json.loads(metadata_path.read_text(encoding="utf-8"))
                if saved.get("schema_version") != "1.0" or saved.get("url") != url:
                    raise DownloadError("metadata_conflict", "Existing metadata belongs to another download", metadata_path)
                if saved.get("expected_sha256") != expected_sha256 or saved.get("max_bytes") != max_bytes:
                    raise DownloadError("metadata_conflict", "Resume must retain the original byte limit and expected hash", metadata_path)
                metadata = saved
            elif partial.exists():
                raise DownloadError("missing_metadata", "Existing partial has no trusted response metadata", metadata_path)
            else:
                metadata = {
                    "schema_version": "1.0", "url": url,
                    "relative_path": path.relative_to(quota.data_root).as_posix(),
                    "max_bytes": max_bytes, "peak_bytes": peak_bytes,
                    "expected_sha256": expected_sha256, "created_at": _utcnow(),
                    "attempts": [],
                }
            if partial.exists():
                if not resume:
                    raise DownloadError("partial_exists", "Partial file retained; enable safe resume or choose a new destination")
                offset = partial.stat().st_size
                if offset > max_bytes:
                    raise DownloadError("size_limit", "Existing partial already exceeds max_bytes")
                if metadata.get("error", {}).get("code") == "checksum_mismatch":
                    raise DownloadError("checksum_mismatch", "A failed checksum needs explicit inspection, not append/retry")
                if offset and (not metadata.get("validator") or not metadata.get("validator_header")):
                    raise DownloadError("unsafe_resume", "Resume requires a saved strong ETag or Last-Modified validator")
            metadata["state"] = "requesting"
            metadata["reservation_id"] = reservation.reservation_id
            metadata["attempts"] = metadata.get("attempts", [])[-7:] + [{"started_at": _utcnow(), "resumed_bytes": offset}]
            metadata.pop("error", None)
            _save_metadata(metadata_path, metadata, quota)
            headers = {"User-Agent": "badmintonTV-library/0.1", "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
                headers["If-Range"] = metadata["validator"]
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.build_opener(_SafeRedirect()).open(request, timeout=timeout) as response:
                _validate_url(response.url)
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise DownloadError("content_encoding", "Encoded transport is unsafe for byte-offset resume")
                response_length = _content_length(response.headers)
                validator_header, validator = _validator(response.headers)
                expected_total = response_length
                range_length = None
                if offset:
                    if response.status != 206:
                        raise DownloadError("unsafe_resume", "Server did not honor the conditional byte range")
                    if response.headers.get(metadata["validator_header"]) != metadata["validator"]:
                        raise DownloadError("validator_changed", "Response validator differs from the saved partial")
                    content_range = response.headers.get("Content-Range", "")
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                    if not match:
                        raise DownloadError("invalid_range", "Resume requires a concrete Content-Range")
                    start, end, expected_total = map(int, match.groups())
                    if start != offset or not start <= end < expected_total:
                        raise DownloadError("invalid_range", "Content-Range does not match the saved byte offset")
                    if response_length is not None and response_length != end - start + 1:
                        raise DownloadError("invalid_range", "Content-Length disagrees with Content-Range")
                    range_length = end - start + 1
                    if metadata.get("expected_total") is not None and metadata["expected_total"] != expected_total:
                        raise DownloadError("invalid_range", "Content-Range total changed since the initial request")
                elif response.status != 200:
                    raise DownloadError("unexpected_status", "Initial download requires HTTP 200")
                if expected_total is not None and expected_total > max_bytes:
                    raise DownloadError("size_limit", "Server payload exceeds the configured byte limit")
                metadata.update({
                    # Redirects may contain ephemeral signed credentials. Keep
                    # only their origin; the original public URL is above.
                    "state": "downloading", "final_origin": urllib.parse.urlsplit(response.url).scheme + "://" + urllib.parse.urlsplit(response.url).netloc,
                    "validator_header": validator_header, "validator": validator,
                    "expected_total": expected_total, "content_type": response.headers.get("Content-Type"),
                })
                # Persist response identity BEFORE opening/writing the partial.
                _save_metadata(metadata_path, metadata, quota)
                digest = hashlib.sha256()
                if offset:
                    with partial.open("rb") as previous:
                        for chunk in iter(lambda: previous.read(CHUNK_BYTES), b""):
                            digest.update(chunk)
                size = offset
                mode = "ab" if partial.exists() else "xb"
                with partial.open(mode) as stream:
                    while True:
                        # Read at most one byte past the cap; never persist it.
                        chunk = response.read(min(CHUNK_BYTES, max_bytes - size + 1))
                        if not chunk:
                            break
                        if size + len(chunk) > max_bytes:
                            raise DownloadError("size_limit", "Streaming payload exceeded the configured byte limit")
                        if range_length is not None and size - offset + len(chunk) > range_length:
                            raise DownloadError("invalid_range", "Response payload exceeds its declared Content-Range")
                        stream.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if expected_total is not None and size != expected_total:
                    raise DownloadError("incomplete", f"Download interrupted at {size} of {expected_total} bytes")
                actual_sha256 = digest.hexdigest()
                metadata.update({"size_bytes": size, "sha256": actual_sha256})
                if expected_sha256 is not None and actual_sha256 != expected_sha256:
                    raise DownloadError("checksum_mismatch", "Downloaded SHA256 differs from the expected SHA256")
            quota.resolve_path(relative_path)
            # link() publishes atomically and fails if the final name exists on
            # both Windows and POSIX; rename() alone would overwrite on POSIX.
            os.link(partial, path, follow_symlinks=False)
            partial.unlink()
            metadata["state"] = "succeeded"
            metadata["completed_at"] = _utcnow()
            metadata["attempts"][-1]["state"] = "succeeded"
            _save_metadata(metadata_path, metadata, quota)
            return DownloadResult(path, size, actual_sha256, metadata_path, offset)
        except BaseException as error:
            if metadata is not None:
                code = getattr(error, "code", None)
                if not isinstance(code, str):
                    code = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "download_failed"
                metadata["state"] = "failed"
                metadata["size_bytes"] = partial.stat().st_size if partial.exists() else (path.stat().st_size if path.exists() else 0)
                # Avoid persisting HTTP exception strings that may expose signed URLs.
                message = str(error)[:512] if isinstance(error, DownloadError) else type(error).__name__
                metadata["error"] = {"code": code, "message": message, "at": _utcnow()}
                if metadata.get("attempts"):
                    metadata["attempts"][-1].update({"state": "failed", "error": metadata["error"]})
                _save_metadata(metadata_path, metadata, quota)
            if isinstance(error, (DownloadError, KeyboardInterrupt, SystemExit, FileExistsError)):
                if isinstance(error, DownloadError):
                    error.metadata_path = metadata_path
                raise
            raise DownloadError("download_failed", f"Download failed: {type(error).__name__}", metadata_path) from error
        finally:
            lock_path.unlink()
