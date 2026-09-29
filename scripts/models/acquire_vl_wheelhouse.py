"""Stage pinned Linux CPython 3.11 wheels with native Windows HTTP transport.

Default is read-only dry-run. This does not install packages, stop pip, or measure
the WSL runtime quota. --execute requires a separately captured runtime preflight.
Only D:/video/runtime/models/vl-wheelhouse is a CLI destination.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.request
from urllib.parse import unquote, urlsplit
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.models.protocol import atomic_write_json
from scripts.models.download_weights import fetch
from scripts.models.range_transfer import append_ranges

DESTINATION = Path("D:/video/runtime/models/vl-wheelhouse")
PRESERVE_SOURCE = Path("D:/video/runtime/models/vl-tmp")
HOSTS = {"files.pythonhosted.org", "pypi.org", "download.pytorch.org"}
MAX_FILES, MAX_WHEEL_BYTES, MAX_TOTAL_BYTES = 100, 3_000_000_000, 15_000_000_000
METADATA_ALLOWANCE = 1_000_000
PREFLIGHT_CHECKS = {"models_35GB", "shared_15GB", "runtime_70GB", "free_5GB_margin"}


def read_json(path, limit=256_000):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError("JSON exceeds its bounded metadata size")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def trusted_url(url, filename=None):
    if not isinstance(url, str) or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("Invalid wheel URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("Only fixed public PyPI/PyTorch HTTPS hosts are allowed")
    if filename is not None and (parsed.query or unquote(parsed.path.rsplit("/", 1)[-1]) != filename):
        raise ValueError("Wheel URL must name its exact manifest filename")
    return url


def validate_manifest(manifest):
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "platform", "python", "files"}
            or manifest["schema_version"] != "1.0" or manifest["platform"] != "linux_x86_64" or manifest["python"] != "cp311"):
        raise ValueError("Expected the explicit Linux x86_64 / cp311 wheel manifest v1")
    entries, seen = manifest["files"], set()
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES:
        raise ValueError("Manifest requires 1..100 explicit wheels")
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"filename", "url", "size_bytes", "sha256"}:
            raise ValueError("Every wheel needs filename/url/size_bytes/sha256 only")
        name = entry["filename"]
        if not isinstance(name, str) or len(name) > 230 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+\-]*\.whl", name):
            raise ValueError("Wheel filename must be a safe basename")
        parts = name[:-4].split("-")
        if len(parts) not in (5, 6) or any(not p for p in parts):
            raise ValueError("Malformed wheel filename")
        python, abi, platforms = parts[-3:]
        linux = all(re.fullmatch(r"(?:linux|manylinux[0-9]+|manylinux_[0-9]+_[0-9]+)_x86_64", p)
                    for p in platforms.split("."))
        if not ((python, abi) == ("cp311", "cp311") and linux
                or (python, abi) == ("py3", "none") and (platforms == "any" or linux)):
            raise ValueError("Only cp311 Linux x86_64 or py3-none compatible wheels are allowed")
        if name.casefold() in seen:
            raise ValueError("Duplicate wheel filename")
        seen.add(name.casefold())
        trusted_url(entry["url"], name)
        if type(entry["size_bytes"]) is not int or not 0 < entry["size_bytes"] <= MAX_WHEEL_BYTES:
            raise ValueError("Wheel byte size must be a positive bounded integer")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("A complete lowercase SHA256 is required")
    if sum(e["size_bytes"] for e in entries) > MAX_TOTAL_BYTES:
        raise ValueError("Wheel manifest exceeds the 15 GB transfer bound")
    return entries


def linked(path):
    path = Path(path)
    return path.is_symlink() or (path.exists() and bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400))


def local_path(path):
    path = Path(path).absolute()
    if any(linked(p) for p in (path, *path.parents)):
        raise ValueError("Symlinks/junctions/reparse points are refused")
    return path


def verify_complete(path, entry):
    path = local_path(path)
    digest, consumed = hashlib.sha256(), 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size != entry["size_bytes"]:
            raise ValueError("File is not the exact complete wheel size; preserved")
        while block := stream.read(1024*1024):
            consumed += len(block)
            if consumed > entry["size_bytes"]:
                raise ValueError("Wheel changed while hashing; preserved")
            digest.update(block)
        after = os.fstat(stream.fileno())
    if ((before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino)
            or consumed != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]):
        raise ValueError("Complete wheel SHA256 mismatch or concurrent change; preserved")
    return {"sha256": digest.hexdigest(), "size_bytes": consumed}


def identity(entry):
    return {"url": entry["url"], "maximum": entry["size_bytes"], "sha256": entry["sha256"], "blob": None, "hash_prefix": None}


def partial_info(target, entry):
    partial = local_path(target.with_name(target.name+".partial"))
    marker = local_path(partial.with_name(partial.name+".source.json"))
    if marker.exists() and read_json(marker)[0] != identity(entry):
        raise ValueError("Partial source identity differs; all existing files preserved")
    if partial.exists() and not marker.exists():
        raise ValueError("Unverified existing partial preserved without renaming")
    count = partial.stat().st_size if partial.exists() else 0
    if count > entry["size_bytes"]:
        raise ValueError("Oversize partial preserved")
    return partial, marker, count


def scan_complete_candidates(source, entries):
    """Read-only bounded search; .partial files are never candidate wheels."""
    source = local_path(source)
    if not source.is_dir():
        raise ValueError("The fixed vl-tmp preservation source must exist")
    wanted = {e["filename"]: e for e in entries}
    candidates, verified, visited = [], {}, 0
    for directory, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not linked(Path(directory)/d))
        visited += len(dirs)+len(files)+1
        if visited > 20000:
            raise ValueError("vl-tmp inventory exceeds the bounded 20,000-entry scan")
        for filename in sorted(files):
            if filename not in wanted:
                continue
            path = Path(directory)/filename
            row = {"source": str(path), "filename": filename}
            try:
                verify_complete(path, wanted[filename])
            except (OSError, ValueError) as exc:
                row.update(status="not_verified_preserved", reason=str(exc))
            else:
                row["status"] = "complete_sha256_verified"
                verified.setdefault(filename, path)
            candidates.append(row)
    return candidates, verified


def plan(entries, destination, preserve_source=None):
    destination = local_path(destination)
    candidates, verified = scan_complete_candidates(preserve_source, entries) if preserve_source else ([], {})
    rows, additional = [], 0
    for entry in entries:
        target = destination/entry["filename"]
        if target.exists():
            verify_complete(target, entry)
            action, offset = "verified_existing_skip", entry["size_bytes"]
        else:
            _, _, offset = partial_info(target, entry)
            action = "protect_complete_hardlink" if entry["filename"] in verified else "download_or_resume"
            if action == "download_or_resume":
                additional += entry["size_bytes"]-offset
        rows.append({"filename": entry["filename"], "action": action, "partial_bytes": offset})
    return {"wheels": rows, "candidates": candidates, "additional_download_bytes": additional,
            "minimum_additional_runtime_peak_bytes": additional+METADATA_ALLOWANCE}, verified


def approved_preflight(path, required_peak):
    if path is None:
        raise ValueError("--execute needs --approved-runtime-manifest from a separate WSL runtime preflight")
    record, sha = read_json(path)
    if (not isinstance(record, dict) or record.get("passed") is not True
            or not isinstance(record.get("checks"), dict)
            or any(record["checks"].get(k) is not True for k in PREFLIGHT_CHECKS)
            or type(record.get("additional_models_peak_bytes")) is not int
            or record["additional_models_peak_bytes"] < required_peak):
        raise ValueError("External runtime preflight does not record passing checks and enough additional models-runtime peak")
    return {"path": str(Path(path).absolute()), "sha256": sha, "record": record,
            "scope": "external_preflight_evidence_only; this Windows process did not measure the WSL runtime quota"}


@contextmanager
def writer_lock(destination):
    lock = destination/".wheelhouse-writer.json"
    token = uuid.uuid4().hex
    atomic_write_json(lock, {"token": token, "pid": os.getpid()})
    try:
        yield
    finally:
        if not linked(lock) and lock.exists() and read_json(lock)[0].get("token") == token:
            lock.unlink()


class TrustedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


@contextmanager
def trusted_transport():
    previous = urllib.request._opener
    urllib.request.install_opener(urllib.request.build_opener(TrustedRedirects()))
    try:
        yield
    finally:
        urllib.request.install_opener(previous)


def protect_complete(source, target, entry):
    """Protect from pip's unlink cleanup, not from later in-place source writes."""
    if target.exists():
        return verify_complete(target, entry)
    verify_complete(source, entry)
    staged = target.with_name(target.name+".preserved-"+uuid.uuid4().hex+".partial")
    os.link(source, staged, follow_symlinks=False)
    result = verify_complete(staged, entry)
    os.link(staged, target, follow_symlinks=False)  # exclusive: never replace an existing file
    staged.unlink()
    return result


def acquire_one(entry, destination, concurrency):
    target = destination/entry["filename"]
    if target.exists():
        return verify_complete(target, entry)
    partial, marker, _ = partial_info(target, entry)
    if not marker.exists():
        atomic_write_json(marker, identity(entry))
    stats = append_ranges(entry["url"], partial, entry["size_bytes"], concurrency=concurrency,
                          chunk_bytes=8_388_608, pause_file=destination/"PAUSE")
    print(json.dumps({"filename": entry["filename"], "range_transfer": stats}), flush=True)
    if stats["status"] == "paused":
        return {"status": "paused", "partial_bytes": stats["final_offset"]}
    # Completed transport is not publication: the shared downloader streams a
    # full SHA256 check and uses an exclusive hardlink before removing its partial.
    return fetch(entry["url"], target, entry["size_bytes"], expected_sha=entry["sha256"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Pinned Linux wheel manifest; never resolved by Windows pip")
    parser.add_argument("--execute", action="store_true", help="Write/download after reviewing the default read-only dry-run")
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--preserve-complete-from", help="Only 'vl-tmp' or the fixed D:/video/runtime/models/vl-tmp; read/hash candidates first")
    parser.add_argument("--preserve-only", action="store_true", help="Protect only full-SHA candidates; do not download missing wheels")
    parser.add_argument("--approved-runtime-manifest", help="Separate passing WSL runtime_preflight_reuse JSON; evidence, not a live quota check")
    parser.add_argument("--additional-runtime-peak", type=int, help="Extra models-runtime bytes reserved externally, including transfer/install coexistence")
    args = parser.parse_args(argv)
    if os.name != "nt":
        raise ValueError("This transfer entrypoint is for native Windows; the target is fixed on D:")
    manifest, manifest_sha = read_json(args.manifest)
    entries = validate_manifest(manifest)
    preserve = None
    if args.preserve_complete_from:
        if args.preserve_complete_from != "vl-tmp" and Path(args.preserve_complete_from).absolute() != PRESERVE_SOURCE.absolute():
            raise ValueError("Preservation is restricted to D:/video/runtime/models/vl-tmp")
        preserve = PRESERVE_SOURCE
    if args.preserve_only and preserve is None:
        raise ValueError("--preserve-only requires --preserve-complete-from vl-tmp")
    overview, verified = plan(entries, DESTINATION, preserve)
    minimum = METADATA_ALLOWANCE if args.preserve_only else overview["minimum_additional_runtime_peak_bytes"]
    peak = args.additional_runtime_peak if args.additional_runtime_peak is not None else minimum
    if peak < minimum:
        raise ValueError("--additional-runtime-peak is below the planned transfer plus metadata bound")
    print(json.dumps({"mode": "execute" if args.execute else "dry_run", "destination": str(DESTINATION),
                      "manifest_sha256": manifest_sha, "additional_runtime_peak_bytes": peak, **overview}), flush=True)
    if not args.execute:
        return 0
    approval = approved_preflight(args.approved_runtime_manifest, peak)
    # This free-space guard is separate from the external models/shared/runtime
    # quota evidence. No models/180GB storage reservation is used for runtime files.
    free = shutil.disk_usage(DESTINATION.parent).free
    if free < peak+5_000_000_000:
        raise ValueError("D: free space is below the declared peak plus 5 GB")
    local_path(DESTINATION).mkdir(parents=True, exist_ok=True)
    results = []
    with writer_lock(DESTINATION), trusted_transport():
        for entry in entries:
            target = DESTINATION/entry["filename"]
            if target.exists():
                result = verify_complete(target, entry)
            elif entry["filename"] in verified:
                result = protect_complete(verified[entry["filename"]], target, entry)
            elif args.preserve_only:
                result = {"status": "not_preserved_not_downloaded"}
            else:
                result = acquire_one(entry, DESTINATION, args.concurrency)
            results.append({"filename": entry["filename"], **result})
            if result.get("status") == "paused":
                break
        receipt = {"schema_version": "1.0", "manifest_sha256": manifest_sha, "files": results,
                   "runtime_preflight": approval, "declared_additional_runtime_peak_bytes": peak,
                   "native_free_bytes_before": free, "hardlink_scope": "protects against unlink cleanup, not in-place modification",
                   "dependency_scope": "only the explicit manifest; not a claim of a complete offline install dependency closure"}
        receipt_path = DESTINATION/("acquisition-"+uuid.uuid4().hex+".json")
        atomic_write_json(receipt_path, receipt)
    print(json.dumps({"receipt": str(receipt_path), "files_processed": len(results)}), flush=True)
    return 75 if any(r.get("status") == "paused" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
