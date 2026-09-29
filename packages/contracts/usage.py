"""Shared production-use gate; training use remains separate from rights/split.

This module reads one library-owned registry and never writes it. Media byte
hash verification is the caller's responsibility, followed by a fresh check.
"""

from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from .models import Asset, Identifier, RelativePath, Sha256, VersionedModel
from .validation import resolve_relative_path


TRAINING_REGISTRY_PATH = "data/training/handoff/training-registry.v1.json"
MAX_REGISTRY_BYTES = 32_000_000
UsageScope = Literal["general", "training_only"]


class TrainingRegistryEntry(BaseModel):
    """Small registry record; does not pretend probe metadata is available."""

    model_config = ConfigDict(extra="allow", validate_default=True)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    asset_id: Identifier
    sha256: Sha256
    relative_path: RelativePath
    usage_scope: Literal["training_only"]
    provenance: dict[str, JsonValue] = Field(default_factory=dict)


class TrainingRegistry(VersionedModel):
    schema_version: Literal["1.0"]
    assets: list[TrainingRegistryEntry]

    @model_validator(mode="after")
    def stable_identifiers(self):
        by_id, by_path = {}, {}
        for asset in self.assets:
            digest = asset.sha256.lower()
            path = asset.relative_path.casefold()
            if asset.asset_id in by_id and by_id[asset.asset_id] != digest:
                raise ValueError("registry asset_id has conflicting hash records")
            if path in by_path and by_path[path] != digest:
                raise ValueError("registry path has conflicting hash records")
            by_id[asset.asset_id], by_path[path] = digest, digest
        return self


class _UsageRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_default=True)
    asset_id: Identifier | None = None
    sha256: Sha256 | None = None
    relative_path: RelativePath
    usage_scope: UsageScope = "general"
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def source_fields(self):
        scope = self.provenance.get("usage_scope")
        if scope is not None and scope not in ("general", "training_only"):
            raise ValueError("provenance.usage_scope is invalid")
        source_id = self.provenance.get("source_asset_id")
        source_sha = self.provenance.get("source_sha256")
        if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
            raise ValueError("provenance.source_asset_id must be a nonempty string")
        if source_sha is not None and (not isinstance(source_sha, str) or len(source_sha) != 64 or any(char not in "0123456789abcdefABCDEF" for char in source_sha)):
            raise ValueError("provenance.source_sha256 must be a SHA256 string")
        return self


class UsageScopeError(ValueError):
    def __init__(self, code: str, reasons, *, asset_id=None):
        self.code, self.asset_id = code, asset_id
        self.reasons = (reasons,) if isinstance(reasons, str) else tuple(reasons)
        super().__init__(f"{code}: " + "; ".join(self.reasons))


@dataclass(frozen=True)
class UsageDecision:
    allowed: bool
    usage_scope: UsageScope
    reasons: tuple[str, ...]
    registry_sha256: str | None


def _records(values):
    if isinstance(values, (Mapping, BaseModel)):
        values = [values]
    elif not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise UsageScopeError("USAGE_METADATA_INVALID", "assets must be metadata objects or a sequence of them")
    parsed = []
    for value in values:
        try:
            raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
            parsed.append(_UsageRecord.model_validate(raw))
        except (ValidationError, TypeError, ValueError) as exc:
            raise UsageScopeError("USAGE_METADATA_INVALID", "asset usage/path/source metadata is invalid") from exc
    return parsed


def _path_key(value):
    # Case-insensitive protection is intentional for the Windows/WSL shared root.
    return value.casefold()


def _training_path(value):
    parts = value.casefold().split("/")
    return len(parts) >= 2 and parts[:2] == ["data", "training"]


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite JSON number")


class UsageScopeGuard:
    def __init__(self, storage_root):
        try:
            self.storage_root = Path(storage_root).resolve(strict=True)
        except OSError as exc:
            raise UsageScopeError("USAGE_PATH_INVALID", "storage root is unavailable") from exc

    def _physical(self, record):
        try:
            path = resolve_relative_path(self.storage_root, record.relative_path)
            return path.relative_to(self.storage_root).as_posix()
        except (OSError, ValueError, RuntimeError) as exc:
            raise UsageScopeError("USAGE_PATH_INVALID", "asset path cannot be resolved safely under the shared root", asset_id=record.asset_id) from exc

    def _registry(self):
        """Read on every public check, including same-size/same-mtime updates."""
        path = self.storage_root
        training_present = False
        try:
            for index, component in enumerate(TRAINING_REGISTRY_PATH.split("/")):
                path /= component
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                if index == 1:
                    training_present = True
                if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                    raise UsageScopeError("TRAINING_REGISTRY_INVALID", "fixed training registry path must not use symlink/junction aliases")
            try:
                with path.open("rb") as handle:
                    raw = handle.read(MAX_REGISTRY_BYTES + 1)
            except FileNotFoundError:
                if training_present:
                    raise UsageScopeError("TRAINING_REGISTRY_PENDING", "data/training exists but the trusted registry has not been published")
                return [], None
        except UsageScopeError:
            raise
        except OSError as exc:
            raise UsageScopeError("TRAINING_REGISTRY_UNAVAILABLE", "cannot read the fixed training registry") from exc
        if len(raw) > MAX_REGISTRY_BYTES:
            raise UsageScopeError("TRAINING_REGISTRY_INVALID", "training registry exceeds 32 MB")
        try:
            payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
            registry = TrainingRegistry.model_validate(payload)
            records = _records(registry.assets)
            # Path failures in trusted data are a global registry error.
            for record in records:
                self._physical(record)
        except (ValueError, UnicodeError, TypeError) as exc:
            raise UsageScopeError("TRAINING_REGISTRY_INVALID", "training registry JSON/schema/paths/source metadata are invalid") from exc
        return records, hashlib.sha256(raw).hexdigest()

    def _evaluate(self, record, available, registry, registry_hash):
        registry_ids = {item.asset_id for item in registry}
        registry_hashes = {item.sha256.lower() for item in registry}
        registry_paths = {_path_key(item.relative_path) for item in registry}
        registry_physical = {_path_key(self._physical(item)) for item in registry}
        by_id, by_hash = {}, {}
        for item in available:
            if item.asset_id:
                by_id.setdefault(item.asset_id, []).append(item)
            if item.sha256:
                by_hash.setdefault(item.sha256.lower(), []).append(item)

        def walk(item, active):
            if len(active) > 128:
                raise UsageScopeError("USAGE_SOURCE_CONFLICT", "source chain exceeds 128 supported relationships", asset_id=record.asset_id)
            physical = self._physical(item)
            restrictions = []
            if item.usage_scope == "training_only":
                restrictions.append("typed usage_scope=training_only")
            if item.provenance.get("usage_scope") == "training_only":
                restrictions.append("provenance.usage_scope=training_only")
            if _training_path(item.relative_path):
                restrictions.append("logical path is under data/training")
            if _training_path(physical):
                restrictions.append("physical path is under data/training")
            if item.asset_id and item.asset_id in registry_ids:
                restrictions.append("asset_id is in the trusted training registry")
            if item.sha256 and item.sha256.lower() in registry_hashes:
                restrictions.append("sha256 is in the trusted training registry")
            if _path_key(item.relative_path) in registry_paths or _path_key(physical) in registry_physical:
                restrictions.append("path is in the trusted training registry")
            if restrictions:
                return restrictions, []

            identity = (item.asset_id, item.sha256.lower() if item.sha256 else None, _path_key(item.relative_path))
            if identity in active:
                raise UsageScopeError("USAGE_SOURCE_CONFLICT", "source_asset_id/source_sha256 chain contains a cycle", asset_id=record.asset_id)
            source_id = item.provenance.get("source_asset_id")
            source_sha = item.provenance.get("source_sha256")
            source_sha = source_sha.lower() if source_sha else None
            if not source_id and not source_sha:
                return [], []
            id_matches = by_id.get(source_id, []) if source_id else []
            if source_sha and any(parent.sha256 and parent.sha256.lower() != source_sha for parent in id_matches):
                raise UsageScopeError("USAGE_SOURCE_CONFLICT", "declared source_asset_id and source_sha256 contradict available source metadata", asset_id=record.asset_id)
            parents = id_matches + (by_hash.get(source_sha, []) if source_sha else [])
            if not parents:
                return [], ["source reference is unresolved in available metadata; external erased lineage cannot be detected"]
            notes, blocked, seen = [], [], set()
            for parent in parents:
                key = (parent.asset_id, parent.sha256, parent.relative_path)
                if key in seen:
                    continue
                seen.add(key)
                parent_restrictions, parent_notes = walk(parent, active | {identity})
                blocked.extend("source chain: " + reason for reason in parent_restrictions)
                notes.extend(parent_notes)
            return blocked, notes

        blocked, notes = walk(record, set())
        return UsageDecision(not blocked, "training_only" if blocked else "general", tuple(dict.fromkeys(blocked + notes)), registry_hash)

    def check(self, asset, *, source_assets=()):
        registry, digest = self._registry()
        records = _records(asset)
        if len(records) != 1:
            raise UsageScopeError("USAGE_METADATA_INVALID", "check requires exactly one asset")
        available = records + _records(source_assets) + registry
        return self._evaluate(records[0], available, registry, digest)

    def assert_allowed(self, assets, *, source_assets=(), research_preview=False):
        # research_preview is accepted for call-site clarity and never bypasses use restrictions.
        registry, digest = self._registry()
        records = _records(assets)
        available = records + _records(source_assets) + registry
        for record in records:
            decision = self._evaluate(record, available, registry, digest)
            if not decision.allowed:
                raise UsageScopeError("TRAINING_ONLY", decision.reasons, asset_id=record.asset_id)


def assert_production_allowed(assets, storage_root, *, source_assets=(), research_preview=False):
    UsageScopeGuard(storage_root).assert_allowed(assets, source_assets=source_assets, research_preview=research_preview)


def inherit_usage_scope(derived, source, storage_root, *, source_assets=()):
    """Return derived metadata retaining direct source identity/hash and strict use."""
    sources = _records(source)
    if len(sources) != 1:
        raise UsageScopeError("USAGE_METADATA_INVALID", "derivation requires exactly one direct source")
    source_record = sources[0]
    if not source_record.asset_id or not source_record.sha256:
        raise UsageScopeError("USAGE_METADATA_INVALID", "derivation requires a verified source asset_id and sha256")
    _records(derived)
    result = deepcopy(derived.model_dump(mode="json") if isinstance(derived, BaseModel) else dict(derived))
    provenance = dict(result.get("provenance", {}))
    for field, expected in (("source_asset_id", source_record.asset_id), ("source_sha256", source_record.sha256.lower())):
        existing = provenance.get(field)
        if existing is not None and (existing.lower() if field == "source_sha256" and isinstance(existing, str) else existing) != expected:
            raise UsageScopeError("USAGE_SOURCE_CONFLICT", "derivation cannot overwrite an existing source relationship")
        provenance[field] = expected
    result["provenance"] = provenance
    decision = UsageScopeGuard(storage_root).check(result, source_assets=[source_record, *_records(source_assets)])
    result["usage_scope"] = decision.usage_scope
    result["provenance"]["usage_scope"] = decision.usage_scope
    return result
