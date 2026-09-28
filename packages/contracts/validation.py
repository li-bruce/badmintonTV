"""Validation that requires another object or the native filesystem."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from .models import Asset, Candidate, Event, JobRequest, JobResult, Timeline, validate_relative_path


RESULT_EXIT_CODES = {"succeeded": 0, "failed": 1, "blocked": 2, "cancelled": 130}


def validate_job_result(request: JobRequest, result: JobResult, returncode: int) -> None:
    """Reject mismatched jobs, stale attempts, and false process success."""
    if result.job_id != request.job_id or result.attempt_id != request.attempt_id:
        raise ValueError("result does not match the current job_id and attempt_id")
    if type(returncode) is not int or returncode != RESULT_EXIT_CODES[result.status]:
        raise ValueError("process exit code does not match result status")


class RevisionConflict(ValueError):
    """Platform adapters should return HTTP 409 for this exception."""


def resolve_relative_path(root: str | Path, relative_path: str, *, must_exist: bool = False) -> Path:
    """Resolve under a native root, including symlinks in existing parents.

    Call at the actual I/O boundary as filesystem contents can change after a check.
    The shared media root must not be writable by untrusted concurrent processes.
    """
    validate_relative_path(relative_path)
    resolved_root = Path(root).resolve(strict=True)
    candidate = resolved_root.joinpath(*relative_path.split("/")).resolve(strict=must_exist)
    if not candidate.is_relative_to(resolved_root) or candidate == resolved_root:
        raise ValueError("resolved path escapes the storage root")
    return candidate


def validate_output_dir(output_dir: str, owner_root: str | Path) -> Path:
    """Resolve root-relative output_dir under a native owner directory.

    Example: validate_output_dir('render/jobs/123', Path('D:/video/render')).
    The owner root must exist; an output subdirectory need not exist yet.
    """
    validate_relative_path(output_dir)
    root = Path(owner_root).resolve(strict=True)
    parts = output_dir.split("/")
    if len(parts) < 2 or parts[0] != root.name or parts[0] not in {"platform", "data", "models", "render"}:
        raise ValueError("output_dir does not belong to the expected owner")
    target = root.joinpath(*parts[1:]).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("output_dir must be a controlled child of the owner root")
    return target


def _asset_map(assets: Mapping[str, Asset] | Sequence[Asset]) -> Mapping[str, Asset]:
    if isinstance(assets, Mapping):
        if any(key != value.asset_id for key, value in assets.items()):
            raise ValueError("asset map keys do not match asset_id")
        return assets
    result = {asset.asset_id: asset for asset in assets}
    if len(result) != len(assets):
        raise ValueError("duplicate asset_id")
    return result


def validate_event_assets(events: Sequence[Event], assets: Mapping[str, Asset] | Sequence[Asset]) -> None:
    lookup = _asset_map(assets)
    for event in events:
        asset = lookup.get(event.asset_id)
        if asset is None:
            raise ValueError(f"unknown event asset_id: {event.asset_id}")
        if event.match_id != asset.match_id:
            raise ValueError(f"event match_id differs from asset: {event.event_id}")
        if event.end_ms > asset.duration_ms:
            raise ValueError(f"event exceeds asset duration: {event.event_id}")
        _validate_evidence(event.evidence, lookup)


def _validate_evidence(evidence: Sequence, lookup: Mapping[str, Asset]) -> None:
    for item in evidence:
        if item.asset_id is None:
            continue
        asset = lookup.get(item.asset_id)
        if asset is None:
            raise ValueError(f"unknown evidence asset_id: {item.asset_id}")
        if item.end_ms is not None and item.end_ms > asset.duration_ms:
            raise ValueError("evidence exceeds asset duration")


def validate_candidate_assets(candidates: Sequence[Candidate], assets: Mapping[str, Asset] | Sequence[Asset]) -> None:
    lookup = _asset_map(assets)
    for candidate in candidates:
        asset = lookup.get(candidate.asset_id)
        if asset is None or candidate.end_ms > asset.duration_ms:
            raise ValueError("candidate has unknown asset or exceeds duration")
        _validate_evidence(candidate.evidence, lookup)


def validate_timeline_assets(timeline: Timeline, assets: Mapping[str, Asset] | Sequence[Asset], *, require_confirmed: bool = False) -> None:
    lookup = _asset_map(assets)
    if require_confirmed and not timeline.segments:
        raise ValueError("rendering requires at least one confirmed segment")
    for segment in timeline.segments:
        asset = lookup.get(segment.asset_id)
        if asset is None or segment.out_ms > asset.duration_ms:
            raise ValueError("timeline segment has unknown asset or exceeds duration")
        if require_confirmed and segment.review_status != "confirmed":
            raise ValueError("rendering requires confirmed segments")


def validate_event_revision(current: Event, replacement: Event, expected_revision: int, *, actor: str = "automatic") -> None:
    """Validate a complete replacement before the platform's atomic DB CAS.

    The service must supply actor from its trusted execution path, never from
    event JSON.  This helper neither locks the database nor performs an update.
    """
    if actor not in ("human", "automatic"):
        raise ValueError("actor must identify a trusted human or automatic execution path")
    if type(expected_revision) is not int or expected_revision != current.revision:
        raise RevisionConflict("expected_revision does not match the current event revision")
    if (replacement.event_id, replacement.asset_id, replacement.match_id) != (current.event_id, current.asset_id, current.match_id):
        raise ValueError("a revision cannot change event_id, asset_id, or match_id")
    if replacement.revision != current.revision + 1 or replacement.previous_revision != current.revision:
        raise RevisionConflict("replacement must identify and increment the current revision")
    if current.review_status == "confirmed" and actor == "automatic":
        raise RevisionConflict("automatic predictions cannot overwrite confirmed events")
    if actor == "human":
        if not replacement.reviewer or replacement.reviewed_at is None:
            raise ValueError("human revisions require reviewer and reviewed_at")
