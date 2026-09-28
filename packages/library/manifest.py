"""v1.0 Asset handoff: verified files, stable identities and match-level splits.

Media are never copied by this module. The registry uses a local lock file and
atomic JSON replacement; do not share its lock between Windows and WSL writers.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from fractions import Fraction
from typing import Iterable, Mapping


class ManifestError(ValueError):
    """An Asset or its persistent grouping is unsafe or inconsistent."""


REQUIRED_FIELDS = {
    "schema_version", "asset_id", "relative_path", "sha256", "size_bytes",
    "duration_ms", "width", "height", "fps_num", "fps_den", "time_base",
    "title", "match_id", "source_type", "source_url", "source_page",
    "acquired_at", "camera_type", "discipline", "players", "rights", "split",
    "probe", "provenance",
}
SPLITS = {"unassigned", "train", "validation", "test"}
UNKNOWN_MATCH_IDS = {"", "unknown"}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_asset_id(sha256: str) -> str:
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ManifestError("sha256 must be 64 lowercase hexadecimal characters")
    return "asset-" + sha256


def safe_asset_path(relative_path: str, storage_root: str | Path = "D:/video") -> Path:
    """Resolve a strictly POSIX-relative name; reject root escapes and symlinks out."""
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise ManifestError("relative_path must be a nonempty POSIX relative path")
    parts = relative_path.split("/")
    if (
        PurePosixPath(relative_path).is_absolute()
        or PureWindowsPath(relative_path).drive
        or any(part in {"", ".", ".."} for part in parts)
        or any(":" in part or "\x00" in part for part in parts)
    ):
        raise ManifestError("absolute paths, traversal and alternate streams are forbidden")
    root = Path(storage_root).resolve()
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root):
        raise ManifestError("relative_path resolves outside storage_root")
    return target


def _integer(value: object, name: str, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestError(f"{name} must be an integer >= {minimum}")


def _enum(value: object, allowed: set[str], name: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ManifestError(f"invalid {name}: {value!r}")


def validate_asset(
    asset: Mapping, *, storage_root: str | Path = "D:/video", verify_file: bool = True
) -> dict:
    """Validate contract fields and, by default, original bytes; return a copy."""
    if not isinstance(asset, Mapping):
        raise ManifestError("Asset must be an object")
    missing = REQUIRED_FIELDS - asset.keys()
    if missing:
        raise ManifestError("missing Asset fields: " + ", ".join(sorted(missing)))
    if asset["schema_version"] != "1.0":
        raise ManifestError("unsupported schema_version")
    for name in ("asset_id", "title", "match_id"):
        if not isinstance(asset[name], str):
            raise ManifestError(f"{name} must be a string")
    if not asset["asset_id"] or asset["match_id"] != asset["match_id"].strip():
        raise ManifestError("asset_id must be nonempty and match_id must be canonical")
    stable_asset_id(asset["sha256"])
    for name in ("size_bytes", "duration_ms", "width", "height"):
        _integer(asset[name], name)
    for name in ("fps_num", "fps_den"):
        _integer(asset[name], name, 1)
    if not isinstance(asset["time_base"], str):
        raise ManifestError("time_base must be a positive rational string")
    try:
        if Fraction(asset["time_base"]) <= 0:
            raise ValueError()
    except (ValueError, ZeroDivisionError):
        raise ManifestError("time_base must be a positive rational string") from None
    _enum(asset["source_type"], {"broadcast", "personal", "dataset", "synthetic"}, "source_type")
    _enum(asset["camera_type"], {"rear", "side", "overhead", "handheld", "mixed", "unknown"}, "camera_type")
    _enum(asset["discipline"], {"singles", "doubles", "unknown"}, "discipline")
    _enum(asset["split"], SPLITS, "split")
    if asset["match_id"] in UNKNOWN_MATCH_IDS and asset["split"] != "unassigned":
        raise ManifestError("unknown match_id must remain unassigned")
    for name in ("source_url", "source_page"):
        if asset[name] is not None and not isinstance(asset[name], str):
            raise ManifestError(f"{name} must be a string or null")
    try:
        acquired = datetime.fromisoformat(asset["acquired_at"].replace("Z", "+00:00"))
        if acquired.tzinfo is None:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        raise ManifestError("acquired_at must be an ISO8601 time with timezone") from None
    if not isinstance(asset["players"], list):
        raise ManifestError("players must be a list")
    for player in asset["players"]:
        if not isinstance(player, dict) or any(
            not isinstance(player.get(key), str)
            for key in ("player_id", "display_name", "identity_status")
        ):
            raise ManifestError("each player needs player_id, display_name, identity_status")
    rights = asset["rights"]
    if not isinstance(rights, dict) or not {"status", "license_url", "evidence", "allowed_uses"} <= rights.keys():
        raise ManifestError("rights must separately describe original video permission")
    _enum(rights["status"], {"unknown", "research_only", "permitted", "owned"}, "rights.status")
    if rights["license_url"] is not None and not isinstance(rights["license_url"], str):
        raise ManifestError("rights.license_url must be a string or null")
    if not isinstance(rights["allowed_uses"], list) or any(not isinstance(x, str) for x in rights["allowed_uses"]):
        raise ManifestError("rights.allowed_uses must be a list of strings")
    for name in ("probe", "provenance"):
        if not isinstance(asset[name], dict):
            raise ManifestError(f"{name} must be an object")
    probe = asset["probe"]
    pts_index = probe.get("pts_index")
    if probe.get("vfr_status") == "vfr_observed" and not pts_index:
        raise ManifestError("VFR requires a PTS index reference")
    path = safe_asset_path(asset["relative_path"], storage_root)
    if verify_file:
        if not path.is_file():
            raise ManifestError("Asset original file does not exist")
        if path.stat().st_size != asset["size_bytes"] or sha256_file(path) != asset["sha256"]:
            raise ManifestError("Asset original size/hash mismatch")
    if pts_index:
        if not isinstance(pts_index, dict) or "relative_path" not in pts_index:
            raise ManifestError("PTS index needs a relative_path")
        index_path = safe_asset_path(pts_index["relative_path"], storage_root)
        if verify_file and (not index_path.is_file() or
                index_path.stat().st_size != pts_index.get("size_bytes") or
                sha256_file(index_path) != pts_index.get("sha256")):
            raise ManifestError("PTS index missing or size/hash mismatch")
    return copy.deepcopy(dict(asset))


def build_asset(
    path: str | Path, metadata: Mapping, probe_result: Mapping, *,
    storage_root: str | Path = "D:/video",
) -> dict:
    """Create a publishable Asset after a successful probe and full CPU decode.

    ``rights`` always refers to video. Put separately investigated annotation
    rights under ``provenance.annotation_rights``; no license is inferred here.
    """
    root = Path(storage_root).resolve()
    media = Path(path).resolve()
    if not media.is_relative_to(root):
        raise ManifestError("original file is outside storage_root")
    if probe_result.get("probe", {}).get("decode", {}).get("status") != "passed":
        raise ManifestError("publishable Asset requires a passed full decode report")
    result = copy.deepcopy(dict(metadata))
    digest = sha256_file(media)
    evidence = probe_result["probe"]
    if evidence.get("source_sha256", digest) != digest or evidence.get("source_size_bytes", media.stat().st_size) != media.stat().st_size:
        raise ManifestError("original file no longer matches the probed bytes")
    result.update({
        "schema_version": "1.0", "asset_id": stable_asset_id(digest),
        "relative_path": media.relative_to(root).as_posix(), "sha256": digest,
        "size_bytes": media.stat().st_size,
    })
    for field in ("duration_ms", "width", "height", "fps_num", "fps_den", "time_base", "probe"):
        if field not in probe_result:
            raise ManifestError(f"probe_result missing {field}")
        result[field] = copy.deepcopy(probe_result[field])
    result.setdefault("provenance", {})
    return validate_asset(result, storage_root=root)


def _atomic_json(path: Path, data: object, max_bytes: int | None = None) -> None:
    payload = None
    if max_bytes is not None:
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if len(payload.encode("utf-8")) > max_bytes:
            raise ManifestError("serialized JSON exceeds the configured byte limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            name = stream.name
            if payload is None:
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
            else:
                stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


class SplitRegistry:
    """Persistent SHA-to-match and match-to-split invariants, atomic per batch.

    Even unassigned-to-train is a change: any deliberate repartition requires an
    audited new registry/snapshot, rather than an accidental import side effect.
    A crashed lock is retained for manual investigation, not guessed stale.
    """
    def __init__(self, path: str | Path, *, lock_timeout_seconds: float = 10,
                 max_bytes: int | None = None):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.lock_timeout_seconds = lock_timeout_seconds
        self.max_bytes = max_bytes

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ManifestError(f"split registry busy; inspect lock {self.lock_path}") from None
                time.sleep(0.05)
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            fd = None
            yield
        finally:
            if fd is not None:
                os.close(fd)
            self.lock_path.unlink()

    def register(self, asset: Mapping) -> None:
        self.register_many([asset])

    def register_many(self, assets: Iterable[Mapping]) -> None:
        with self._lock():
            if self.path.exists():
                try:
                    if self.max_bytes is None:
                        state = json.loads(self.path.read_text(encoding="utf-8"))
                    else:
                        with self.path.open("rb") as stream:
                            raw = stream.read(self.max_bytes + 1)
                        if len(raw) > self.max_bytes:
                            raise ManifestError("split registry exceeds configured byte limit")
                        state = json.loads(raw.decode("utf-8"))
                except (OSError, ValueError) as exc:
                    raise ManifestError("cannot read split registry") from exc
                if (not isinstance(state, dict) or state.get("schema_version") != "1.0"
                        or not isinstance(state.get("matches"), dict)
                        or not isinstance(state.get("sha256"), dict)):
                    raise ManifestError("invalid split registry")
            else:
                state = {"schema_version": "1.0", "matches": {}, "sha256": {}}
            for asset in assets:
                sha, match, split = asset["sha256"], asset["match_id"], asset["split"]
                stable_asset_id(sha)
                if not isinstance(match, str) or match != match.strip():
                    raise ManifestError("match_id must be a canonical string")
                _enum(split, SPLITS, "split")
                if match in UNKNOWN_MATCH_IDS and split != "unassigned":
                    raise ManifestError("unknown match_id must remain unassigned")
                if sha in state["sha256"] and state["sha256"][sha] != match:
                    raise ManifestError("same SHA assigned to a different canonical match")
                if match not in UNKNOWN_MATCH_IDS:
                    if match in state["matches"] and state["matches"][match] != split:
                        raise ManifestError("canonical match split cannot change")
                    state["matches"][match] = split
                state["sha256"][sha] = match
            _atomic_json(self.path, state, self.max_bytes)


def write_manifest(
    path: str | Path, assets: Iterable[Mapping], *,
    storage_root: str | Path = "D:/video", registry: SplitRegistry | None = None,
    max_bytes: int | None = None,
) -> dict:
    """Validate, SHA-deduplicate and atomically publish a JSON v1.0 manifest.

    The first occurrence wins only when duplicate SHA grouping agrees. Register
    the entire batch before publication so conflicts leave the old manifest intact.
    """
    unique = {}
    matches = {}
    ids = {}
    for entry in assets:
        asset = validate_asset(entry, storage_root=storage_root)
        sha, match, split = asset["sha256"], asset["match_id"], asset["split"]
        if sha in unique and (unique[sha]["match_id"], unique[sha]["split"]) != (match, split):
            raise ManifestError("duplicate SHA has inconsistent match/split")
        if match not in UNKNOWN_MATCH_IDS:
            if match in matches and matches[match] != split:
                raise ManifestError("same canonical match has conflicting splits")
            matches[match] = split
        if asset["asset_id"] in ids and ids[asset["asset_id"]] != sha:
            raise ManifestError("asset_id identifies multiple SHA values")
        ids[asset["asset_id"]] = sha
        unique.setdefault(sha, asset)
    manifest = {"schema_version": "1.0", "assets": list(unique.values())}
    # Check the bound before registry mutation as well as at publication.
    if max_bytes is not None and len((json.dumps(manifest, ensure_ascii=False, indent=2,
                                                allow_nan=False) + "\n").encode("utf-8")) > max_bytes:
        raise ManifestError("manifest exceeds configured byte limit")
    if registry is not None:
        registry.register_many(unique.values())
    _atomic_json(Path(path), manifest, max_bytes)
    return manifest
