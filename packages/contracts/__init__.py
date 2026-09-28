"""Public badmintonTV v1.0 schemas and cross-object validation helpers."""

from .models import (
    Artifact, Asset, AssetManifest, CameraType, Candidate, ContractModel, CropWindow,
    Event, EventCollection, EventKind, EventManifest, EventProvenance, Evidence,
    JobError, JobRequest, JobResult, Manifest, ModelManifest, Player, ProgressEvent,
    QueryRelation, QueryScope, QuerySpec, QueryStep, Rights, Timeline,
    TimelineOutput, TimelineSegment, Weight, validate_relative_path,
)
from .validation import (
    RESULT_EXIT_CODES, RevisionConflict, resolve_relative_path, validate_candidate_assets,
    validate_event_assets, validate_event_revision, validate_output_dir,
    validate_timeline_assets, validate_job_result,
)

CONTRACT_TYPES = {
    cls.__name__: cls for cls in (
        Asset, AssetManifest, Event, EventManifest, QuerySpec, Candidate,
        ModelManifest, Artifact, Timeline, JobRequest, JobResult, ProgressEvent,
    )
}


def schemas() -> dict[str, dict]:
    """Fresh, standalone JSON Schemas; Python semantic checks still apply."""
    return {name: cls.model_json_schema() for name, cls in CONTRACT_TYPES.items()}


__all__ = [
    "Artifact", "Asset", "AssetManifest", "CameraType", "Candidate", "ContractModel",
    "CropWindow", "Event", "EventCollection", "EventKind", "EventManifest",
    "EventProvenance", "Evidence", "JobError", "JobRequest", "JobResult", "Manifest",
    "ModelManifest", "Player", "ProgressEvent", "QueryRelation", "QueryScope",
    "QuerySpec", "QueryStep", "Rights", "Timeline", "TimelineOutput", "TimelineSegment",
    "Weight", "RESULT_EXIT_CODES", "RevisionConflict", "resolve_relative_path", "validate_candidate_assets",
    "validate_event_assets", "validate_event_revision", "validate_output_dir",
    "validate_timeline_assets", "validate_job_result", "validate_relative_path", "CONTRACT_TYPES", "schemas",
]
