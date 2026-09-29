"""Library-owned, monotonic SHA registry and validated training-only handoff.

No media are copied or changed. All writers must use this publisher and the
same QuotaManager ledger. Consumer-side SHA enforcement belongs to contracts.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import time
from typing import Callable, Iterable, Mapping

from .cli import publication_audit
from .manifest import (ManifestError, SplitRegistry, _atomic_json, sha256_file,
                       stable_asset_id, validate_asset, write_manifest)
from .storage import QuotaManager


REGISTRY_RELATIVE_PATH = "training/handoff/training-registry.v1.json"
SPLITS_RELATIVE_PATH = "training/handoff/training-splits.v1.json"
MAX_JSON_BYTES = 10_000_000


class TrainingError(ManifestError):
    """A training-only provenance, ownership or publication invariant failed."""


def _version(value: str) -> str:
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value)
            or ".." in value or value.endswith(".") or value.lower() == "handoff"
            or value.split(".", 1)[0].upper() in reserved):
        raise TrainingError("dataset_version must be a safe, non-handoff directory name")
    return value


def _limit(value: int) -> int:
    if type(value) is not int or not 0 < value <= MAX_JSON_BYTES:
        raise TrainingError(f"max_json_bytes must be in 1..{MAX_JSON_BYTES}")
    return value


def _bounded(value: object, limit: int) -> None:
    size = len((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    if size > limit:
        raise TrainingError("Training JSON exceeds the configured byte limit")


def _source_path(relative: str, quota: QuotaManager, version: str | None = None) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise TrainingError("Training path must be project-relative POSIX")
    if any(ord(char) < 32 or char in ':*?"<>|' for char in relative):
        raise TrainingError("Training path contains an unsafe character")
    parts = relative.split("/")
    if len(parts) < 4 or parts[:2] != ["data", "training"]:
        raise TrainingError("Source must be below data/training/<dataset-version>/")
    _version(parts[2])
    if version is not None and parts[2] != version:
        raise TrainingError("Source belongs to another dataset_version")
    return quota.resolve_path("/".join(parts[1:]))


@contextmanager
def _locked(registry: Path, quota: QuotaManager, timeout: float):
    if timeout < 0:
        raise TrainingError("lock timeout cannot be negative")
    lock = quota.resolve_path(str(registry.relative_to(quota.data_root)) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TrainingError(f"Training registry busy; inspect retained lock: {lock}") from None
            time.sleep(0.05)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.fsync(fd)
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock.unlink()


def tag_training_asset(asset: Mapping) -> dict:
    """Copy and explicitly mark both fields; never silently override a conflict."""
    if not isinstance(asset, Mapping):
        raise TrainingError("Asset must be an object")
    result = copy.deepcopy(dict(asset))
    provenance = result.setdefault("provenance", {})
    if not isinstance(provenance, dict):
        raise TrainingError("provenance must be an object")
    for container in (result, provenance):
        if "usage_scope" in container and container["usage_scope"] != "training_only":
            raise TrainingError("Conflicting usage_scope cannot be silently overwritten")
        container["usage_scope"] = "training_only"
    if result.get("split") != "unassigned":
        raise TrainingError("This acquisition publisher requires split=unassigned")
    return result


def _entry(entry: Mapping, quota: QuotaManager, *, version: str | None,
           verify_file: bool) -> dict:
    if not isinstance(entry, Mapping):
        raise TrainingError("Registry entry must be an object")
    result = copy.deepcopy(dict(entry))
    for key in ("asset_id", "sha256", "relative_path", "usage_scope"):
        if key not in result:
            raise TrainingError(f"Registry entry missing {key}")
    if (not isinstance(result["asset_id"], str) or not result["asset_id"].strip()
            or any(ord(char) < 32 for char in result["asset_id"])):
        raise TrainingError("asset_id must be nonempty")
    stable_asset_id(result["sha256"])
    if result["usage_scope"] != "training_only":
        raise TrainingError("Trusted registry cannot contain a downgraded usage_scope")
    if "schema_version" in result and result["schema_version"] != "1.0":
        raise TrainingError("Unsupported registry entry schema")
    if not isinstance(result.get("provenance_history", []), list):
        raise TrainingError("provenance_history must be a list")
    for provenance in [result.get("provenance", {}), *result.get("provenance_history", [])]:
        if not isinstance(provenance, dict) or provenance.get("usage_scope", "training_only") != "training_only":
            raise TrainingError("Registry provenance cannot contradict training_only")
        source_id, source_sha = provenance.get("source_asset_id"), provenance.get("source_sha256")
        if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
            raise TrainingError("provenance.source_asset_id must be a nonempty string or null")
        if source_sha is not None and (not isinstance(source_sha, str)
                                       or not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha)):
            raise TrainingError("provenance.source_sha256 must be a SHA256 string or null")
    if "match_id" in result:
        match = result["match_id"]
        if not isinstance(match, str) or match != match.strip():
            raise TrainingError("match_id must be a canonical string when supplied")
    if "split" in result and result["split"] != "unassigned":
        raise TrainingError("Registry acquisition split must remain unassigned")
    for singular, plural in (("asset_id", "asset_ids"), ("relative_path", "relative_paths")):
        aliases = result.get(plural, [])
        if not isinstance(aliases, list) or any(not isinstance(value, str) or not value.strip()
                                               or any(ord(char) < 32 for char in value) for value in aliases):
            raise TrainingError(f"{plural} must be a list of nonempty strings")
        result[plural] = list(dict.fromkeys([result[singular], *aliases]))
    for relative in result["relative_paths"]:
        path = _source_path(relative, quota, version)
        if verify_file:
            if not path.is_file() or sha256_file(path) != result["sha256"]:
                raise TrainingError("Training source is missing or its SHA does not match")
            if "size_bytes" in result and (type(result["size_bytes"]) is not int or path.stat().st_size != result["size_bytes"]):
                raise TrainingError("Training source size does not match")
    return result


def _read_registry(path: Path, quota: QuotaManager, limit: int) -> dict:
    if not path.exists():
        return {"schema_version": "1.0", "assets": []}
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise TrainingError("Duplicate JSON keys invalidate the whole training registry")
            result[key] = value
        return result
    def invalid_number(value):
        raise TrainingError("Non-finite JSON number in training registry")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise TrainingError("Trusted training registry exceeds the byte limit")
    state = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_keys, parse_constant=invalid_number)
    if (not isinstance(state, dict) or set(state) != {"schema_version", "assets"}
            or state.get("schema_version") != "1.0" or not isinstance(state.get("assets"), list)):
        raise TrainingError("Invalid trusted training registry; refusing to reset it")
    # Do not demand that all previously registered aliases still exist: moving
    # or removing media must never remove a SHA's training-only restriction.
    return state


def _merge_registry(state: dict, incoming: Iterable[Mapping], quota: QuotaManager) -> dict:
    merged = copy.deepcopy(state)
    entries: dict[tuple[str, str, str], dict] = {}
    identities: dict[str, str] = {}
    paths: dict[str, str] = {}
    matches: dict[str, str] = {}
    for raw in [*state["assets"], *incoming]:
        entry = _entry(raw, quota, version=None, verify_file=False)
        sha = entry["sha256"]
        if "match_id" in entry:
            if sha in matches and matches[sha] != entry["match_id"]:
                raise TrainingError("Same SHA cannot change canonical match_id")
            matches[sha] = entry["match_id"]
        for alias in entry["asset_ids"]:
            if alias in identities and identities[alias] != sha:
                raise TrainingError("An asset_id cannot identify multiple SHA values")
            identities[alias] = sha
        for relative in entry["relative_paths"]:
            # Match the platform helper's deliberate Windows/WSL case folding.
            normalized = relative.casefold()
            if normalized in paths and paths[normalized] != sha:
                raise TrainingError("A source path cannot identify multiple SHA values")
            paths[normalized] = sha
        # Consumers index scalar fields only. New aliases remain independent
        # verified rows. Legacy arrays expand conservatively so no indexed ID or
        # path disappears; SHA equality is the basis, not an asserted old pair.
        aliases = [(entry["asset_id"], entry["relative_path"])]
        aliases.extend((alias, entry["relative_path"]) for alias in entry["asset_ids"][1:])
        aliases.extend((entry["asset_id"], relative) for relative in entry["relative_paths"][1:])
        for index, (asset_id, relative) in enumerate(aliases):
            row = copy.deepcopy(entry)
            row.pop("asset_ids", None)
            row.pop("relative_paths", None)
            row.update(asset_id=asset_id, relative_path=relative)
            if index:
                row["registry_alias_expansion"] = "Legacy alias restriction materialized by verified SHA; original ID/path pairing unspecified"
            key = (sha, asset_id, relative)
            if key not in entries:
                entries[key] = row
                continue
            prior = entries[key]
            if "provenance" not in prior and "provenance" in row:
                prior["provenance"] = copy.deepcopy(row["provenance"])
            history = prior.get("provenance_history", [])
            for evidence in [row.get("provenance"), *row.get("provenance_history", [])]:
                if evidence is not None and evidence != prior.get("provenance") and evidence not in history:
                    history.append(copy.deepcopy(evidence))
            if history:
                prior["provenance_history"] = history
    for entry in entries.values():
        if entry["sha256"] in matches:
            entry["match_id"] = matches[entry["sha256"]]
    merged["assets"] = list(entries.values())
    return merged


def _record_registry(state: dict, path: Path, quota: QuotaManager, limit: int) -> None:
    _bounded(state, limit)
    with publication_audit([path], quota, reason="Append verified training-only SHA sources"):
        _atomic_json(path, state, limit)


def register_training_sources(
    entries: Iterable[Mapping], *, dataset_version: str, quota: QuotaManager,
    max_json_bytes: int = MAX_JSON_BYTES, lock_timeout_seconds: float = 10,
) -> dict:
    """Verify minimal source records and atomically append SHA usage restrictions.

    Empty input initializes an absent registry; a present valid registry is
    retained. This can run before expensive media decode/PTS generation. A
    missing match_id may be filled once later; an explicit value never changes.
    """
    version, limit = _version(dataset_version), _limit(max_json_bytes)
    verified = [_entry(entry, quota, version=version, verify_file=True) for entry in entries]
    _bounded(verified, limit)
    path = quota.resolve_path(REGISTRY_RELATIVE_PATH)
    with quota.reserve(5 * limit + 262_144, purpose="verified training SHA registry publication"):
        with _locked(path, quota, lock_timeout_seconds):
            existing = _read_registry(path, quota, limit)
            merged = _merge_registry(existing, verified, quota)
            _bounded(merged, limit)
            if not path.exists() or merged != existing:
                _record_registry(merged, path, quota, limit)
            # A valid empty call never wipes previously registered sources.
            result = {"registry": merged, "registry_path": str(path),
                      "registry_sha256": sha256_file(path)}
    return result


def _typed_asset(asset: Mapping, validator: Callable, quota: QuotaManager, version: str) -> dict:
    original = tag_training_asset(asset)
    _source_path(original.get("relative_path"), quota, version)
    pts = original.get("probe", {}).get("pts_index")
    if pts:
        _source_path(pts["relative_path"], quota, version)
    original = validate_asset(original, storage_root=quota.project_root)
    validated = validator(copy.deepcopy(original))
    if hasattr(validated, "model_dump"):
        validated = validated.model_dump(mode="json")
    if not isinstance(validated, Mapping):
        raise TrainingError("asset_validator must return the validated typed object or mapping")
    if (validated.get("usage_scope") != "training_only"
            or validated.get("provenance", {}).get("usage_scope") != "training_only"):
        raise TrainingError("Typed contract did not retain both training_only scope fields")
    for field in ("asset_id", "sha256", "relative_path", "size_bytes", "match_id", "split"):
        if validated.get(field) != original[field]:
            raise TrainingError(f"Typed contract changed identity/grouping field: {field}")
    return validate_asset(validated, storage_root=quota.project_root, verify_file=False)


def publish_training_manifest(
    assets: Iterable[Mapping], *, dataset_version: str, quota: QuotaManager,
    asset_validator: Callable, max_json_bytes: int = MAX_JSON_BYTES,
    lock_timeout_seconds: float = 10,
) -> dict:
    """Validate new typed assets, then publish trusted usage before the manifest."""
    version, limit = _version(dataset_version), _limit(max_json_bytes)
    if not callable(asset_validator):
        raise TrainingError("A new typed Asset contract validator is required")
    checked = [_typed_asset(asset, asset_validator, quota, version) for asset in assets]
    if not checked:
        raise TrainingError("Use register_training_sources([]) for an empty registry; no empty training manifest is published")
    _bounded({"schema_version": "1.0", "assets": checked}, limit)
    registry_path = quota.resolve_path(REGISTRY_RELATIVE_PATH)
    manifest_path = quota.resolve_path(f"training/handoff/{version}.assets.v1.json")
    splits_path = quota.resolve_path(SPLITS_RELATIVE_PATH)
    sources = [{key: copy.deepcopy(asset[key]) for key in
                ("asset_id", "sha256", "relative_path", "usage_scope", "provenance", "match_id", "split")}
               for asset in checked]
    with quota.reserve(5 * limit + 262_144, purpose="typed training-only registry and manifest publication"):
        with _locked(registry_path, quota, lock_timeout_seconds):
            existing = _read_registry(registry_path, quota, limit)
            merged = _merge_registry(existing, sources, quota)
            _bounded(merged, limit)
            with publication_audit([registry_path, splits_path, manifest_path], quota,
                                   reason="Publish typed training-only handoff after trusted SHA registry"):
                # Split conflicts stop before the usage snapshot is replaced.
                SplitRegistry(splits_path, max_bytes=limit).register_many(checked)
                _atomic_json(registry_path, merged, limit)
                # Re-check bytes before publication. A failure leaves the
                # conservative SHA restriction intact and the old manifest whole.
                manifest = write_manifest(manifest_path, checked, storage_root=quota.project_root,
                                          max_bytes=limit)
            result = {"manifest": manifest, "manifest_path": str(manifest_path),
                      "registry_path": str(registry_path), "registry_sha256": sha256_file(registry_path),
                      "manifest_sha256": sha256_file(manifest_path)}
    return result
