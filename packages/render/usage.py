"""Render entrypoint adapter for the platform-owned production-use contract."""
from __future__ import annotations

from copy import deepcopy

from .storage import sha256
from .timeline import RenderError, require, safe_path


def referenced_assets(timeline, assets):
    require(isinstance(timeline, dict), "timeline must be an object")
    segments = timeline.get("segments")
    require(isinstance(segments, list) and 1 <= len(segments) <= 200, "Timeline requires 1..200 segments")
    result = {}
    for segment in segments:
        require(isinstance(segment, dict), "segment must be an object")
        aid = segment.get("asset_id")
        require(isinstance(aid, str) and aid in assets, "unknown asset_id", "unknown_asset")
        result[aid] = assets[aid]
    return list(result.values())


def check_usage(selected, assets, root, research_preview=False):
    try:
        from packages.contracts.usage import assert_production_allowed, UsageScopeError
    except ImportError as exc:
        raise RenderError("usage_guard_unavailable", "Install the shared production-use contract and its runtime dependency", "blocked") from exc
    try:
        assert_production_allowed(selected, root, source_assets=list(assets.values()), research_preview=research_preview)
    except UsageScopeError as exc:
        raise RenderError(exc.code, str(exc), "blocked") from exc


def lineage_assets(selected, assets):
    """Include every available ancestor reachable by declared source ID/hash.

    Metadata can forge both ends of a source link consistently. Only checking
    the selected derivative's bytes would then miss a renamed training parent.
    The shared helper still owns source conflict/cycle and usage semantics.
    """
    by_hash = {}
    for asset in assets.values():
        by_hash.setdefault(asset["sha256"].lower(), []).append(asset)
    pending, found = list(selected), {}
    while pending:
        asset = pending.pop(0)
        aid = asset["asset_id"]
        if aid in found:
            continue
        found[aid] = asset
        provenance = asset.get("provenance", {})
        parent_id = provenance.get("source_asset_id")
        parent_hash = provenance.get("source_sha256")
        if parent_id in assets:
            pending.append(assets[parent_id])
        if parent_hash:
            pending.extend(by_hash.get(parent_hash.lower(), ()))
    return list(found.values())


def verify_source_bytes(selected, assets, root, check, research_preview=False):
    """Check original inputs and reachable ancestors before editing or media I/O."""
    verified = []
    paths = {}
    closure = lineage_assets(selected, assets)
    check_usage(closure, assets, root, research_preview)
    for asset in closure:
        aid = asset["asset_id"]
        path = safe_path(root, asset.get("relative_path"))
        require(path.is_file(), f"Asset file unavailable: {aid}", "missing_asset")
        require(path.stat().st_size == asset["size_bytes"], f"Asset size mismatch: {aid}", "asset_mismatch")
        digest = sha256(path, check)
        actual = deepcopy(asset)
        actual["sha256"] = digest
        # Query with actual bytes first, so a copied registered asset never gets
        # downgraded to a harmless mismatch just by forging request metadata.
        check_usage([actual], assets, root, research_preview)
        require(digest.lower() == asset["sha256"].lower(), f"Asset hash mismatch: {aid}", "asset_mismatch")
        verified.append(actual)
        paths[aid] = path
    check_usage(verified, assets, root, research_preview)
    return paths
