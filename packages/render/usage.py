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


def verify_source_bytes(selected, assets, root, check, research_preview=False):
    """Check even replay inputs later discarded. No media process or reservation."""
    verified = []
    paths = {}
    for asset in selected:
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
