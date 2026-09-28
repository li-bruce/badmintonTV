"""Version 1.0 transport contracts. No database, media, or ML dependencies."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, model_validator


def _nonblank(value: str) -> str:
    if not value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError("must contain non-whitespace text without control characters")
    return value


def validate_relative_path(value: str) -> str:
    """Accept one canonical, portable POSIX path without URL or Windows aliases."""
    if not value or value.startswith("/") or "\\" in value:
        raise ValueError("relative_path must be a relative POSIX path")
    if any(ord(char) < 32 for char in value) or any(char in value for char in ':*?"<>|'):
        raise ValueError("relative_path contains an unsafe character")
    for part in value.split("/"):
        if part in ("", ".", "..") or part.endswith((" ", ".")):
            raise ValueError("relative_path contains a non-canonical or traversal component")
        if part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
            raise ValueError("relative_path contains a Windows reserved device name")
    return value


NonEmpty = Annotated[str, Field(strict=True, min_length=1), AfterValidator(_nonblank)]
Identifier = NonEmpty
RelativePath = Annotated[str, Field(strict=True, min_length=1), AfterValidator(validate_relative_path)]
Sha256 = Annotated[str, Field(strict=True, pattern=r"^[0-9a-fA-F]{64}$")]
Milliseconds = Annotated[int, Field(strict=True, ge=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Confidence = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
PositiveFloat = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
SourceType = Literal["broadcast", "personal", "dataset", "synthetic"]
CameraType = Literal["rear", "side", "overhead", "handheld", "mixed", "unknown"]
ReviewStatus = Literal["unreviewed", "confirmed", "rejected"]
EventKind = Literal["shot", "rally", "stroke", "movement"]
Labels = dict[NonEmpty, NonEmpty | None]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class VersionedModel(ContractModel):
    schema_version: Literal["1.0"] = "1.0"


class Player(ContractModel):
    player_id: Identifier
    display_name: NonEmpty
    identity_status: Literal["unconfirmed", "confirmed", "unknown"] = "unconfirmed"


class Rights(ContractModel):
    status: Literal["unknown", "research_only", "permitted", "owned"] = "unknown"
    license_url: str | None = None
    evidence: str | list[JsonValue] | dict[str, JsonValue] = Field(default_factory=list)
    allowed_uses: list[NonEmpty] = Field(default_factory=list)


class Asset(VersionedModel):
    asset_id: Identifier
    relative_path: RelativePath
    sha256: Sha256
    size_bytes: NonNegativeInt
    duration_ms: Milliseconds
    width: NonNegativeInt
    height: NonNegativeInt
    fps_num: NonNegativeInt | None = None
    fps_den: PositiveInt | None = None
    time_base: str | None = None
    title: str = ""
    match_id: Identifier
    source_type: SourceType
    source_url: str | None = None
    source_page: str | None = None
    acquired_at: datetime | None = None
    camera_type: CameraType = "unknown"
    discipline: Literal["singles", "doubles", "unknown"] = "unknown"
    players: list[Player] = Field(default_factory=list)
    rights: Rights = Field(default_factory=Rights)
    split: Literal["unassigned", "train", "validation", "test"] = "unassigned"
    probe: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def media_metadata(self) -> Asset:
        if (self.fps_num is None) != (self.fps_den is None):
            raise ValueError("fps_num and fps_den must both be present or both be null")
        if self.time_base is not None and not re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", self.time_base):
            raise ValueError("time_base must be a positive rational string such as 1/90000")
        _unique([player.player_id for player in self.players], "player_id")
        return self


def _unique(values: list[str], name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {name}")


class AssetManifest(VersionedModel):
    assets: list[Asset]

    @model_validator(mode="after")
    def unique_assets_and_match_splits(self) -> AssetManifest:
        _unique([asset.asset_id for asset in self.assets], "asset_id")
        splits: dict[str, set[str]] = {}
        for asset in self.assets:
            if asset.split != "unassigned":
                splits.setdefault(asset.match_id, set()).add(asset.split)
        if any(len(values) > 1 for values in splits.values()):
            raise ValueError("all assets from the same match_id must use the same assigned split")
        return self


class Evidence(ContractModel):
    """Typed source intervals plus open evidence metadata (PTS, method, score)."""

    model_config = ConfigDict(extra="allow", validate_default=True)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    type: NonEmpty
    asset_id: Identifier | None = None
    start_ms: Milliseconds | None = None
    end_ms: Milliseconds | None = None

    @model_validator(mode="after")
    def interval(self) -> Evidence:
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("evidence interval requires both start_ms and end_ms")
        if self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("evidence end_ms must be greater than start_ms")
        if self.type == "source_interval" and (self.asset_id is None or self.start_ms is None):
            raise ValueError("source_interval evidence requires asset_id, start_ms, and end_ms")
        return self


class EventProvenance(ContractModel):
    model_config = ConfigDict(extra="allow", validate_default=True)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    source: Literal["manual", "model", "rule", "import"] = "manual"
    model_id: Identifier | None = None
    model_version: NonEmpty | None = None
    run_id: Identifier | None = None


class Event(VersionedModel):
    event_id: Identifier
    asset_id: Identifier
    match_id: Identifier
    rally_id: Identifier | None = None
    shot_id: Identifier | None = None
    player_id: Identifier | None = None
    track_id: Identifier | None = None
    kind: EventKind
    start_ms: Milliseconds
    end_ms: Milliseconds
    contact_ms: Milliseconds | None = None
    labels: Labels = Field(default_factory=dict)
    visibility: Literal["clear", "partial", "insufficient"] = "insufficient"
    confidence: Confidence | None = None
    review_status: ReviewStatus = "unreviewed"
    revision: PositiveInt = 1
    provenance: EventProvenance = Field(default_factory=EventProvenance)
    evidence: list[Evidence] = Field(default_factory=list)
    unknown_reason: str | None = None
    reviewer: NonEmpty | None = None
    reviewed_at: datetime | None = None
    previous_revision: PositiveInt | None = None

    @model_validator(mode="after")
    def interval_and_revision(self) -> Event:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        if self.contact_ms is not None and not self.start_ms <= self.contact_ms < self.end_ms:
            raise ValueError("contact_ms must lie inside [start_ms,end_ms)")
        if self.previous_revision is not None and self.previous_revision != self.revision - 1:
            raise ValueError("previous_revision must equal revision - 1")
        return self


class EventManifest(VersionedModel):
    events: list[Event]

    @model_validator(mode="after")
    def unique_events(self) -> EventManifest:
        _unique([event.event_id for event in self.events], "event_id")
        return self


EventCollection = EventManifest
Manifest = AssetManifest


class QueryScope(ContractModel):
    library_ids: list[Identifier] = Field(default_factory=list)
    asset_ids: list[Identifier] = Field(default_factory=list)
    match_ids: list[Identifier] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)


class QueryStep(ContractModel):
    step_id: Identifier
    kind: EventKind | None = None
    labels: Labels = Field(default_factory=dict)


class QueryRelation(ContractModel):
    from_step: Identifier
    to_step: Identifier
    relation: Literal["before", "overlaps", "near"]
    max_gap_ms: Milliseconds | None = None
    same_player: bool = True
    same_rally: bool = True


class QuerySpec(VersionedModel):
    query_id: Identifier
    text: str = ""
    player_id: Identifier | None = None
    scope: QueryScope = Field(default_factory=QueryScope)
    steps: list[QueryStep] = Field(default_factory=list)
    relations: list[QueryRelation] = Field(default_factory=list)
    include_uncertain: bool = False

    @model_validator(mode="after")
    def valid_relations(self) -> QuerySpec:
        ids = [step.step_id for step in self.steps]
        _unique(ids, "step_id")
        before: dict[str, list[str]] = {key: [] for key in ids}
        for relation in self.relations:
            if relation.from_step not in before or relation.to_step not in before:
                raise ValueError("relation references an unknown step_id")
            if relation.from_step == relation.to_step:
                raise ValueError("a relation must connect two different steps")
            if relation.relation == "before":
                before[relation.from_step].append(relation.to_step)
        active: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in active:
                raise ValueError("before relations cannot contain a cycle")
            if key in visited:
                return
            active.add(key)
            for next_key in before[key]:
                visit(next_key)
            active.remove(key)
            visited.add(key)

        for key in ids:
            visit(key)
        return self


class Candidate(VersionedModel):
    candidate_id: Identifier
    asset_id: Identifier
    start_ms: Milliseconds
    end_ms: Milliseconds
    player_id: Identifier | None = None
    event_ids: list[Identifier] = Field(default_factory=list)
    matched_conditions: list[str | dict[str, JsonValue]] = Field(default_factory=list)
    missing_conditions: list[str | dict[str, JsonValue]] = Field(default_factory=list)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    rank_score: FiniteFloat | None = None
    review_status: ReviewStatus = "unreviewed"
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def interval(self) -> Candidate:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        _unique(self.event_ids, "event_id")
        return self


class Weight(ContractModel):
    relative_path: RelativePath
    sha256: Sha256
    license_url: str | None = None


class ModelManifest(VersionedModel):
    model_id: Identifier
    version: NonEmpty
    display_name: NonEmpty
    capabilities: list[NonEmpty] = Field(default_factory=list)
    status: Literal["not_installed", "ready", "experimental", "unavailable"]
    reason: NonEmpty | None = None
    entrypoint: list[NonEmpty] | NonEmpty | None = None
    environment: str | dict[str, JsonValue] | None = None
    weights: list[Weight] = Field(default_factory=list)
    parameters_schema: dict[str, JsonValue] = Field(default_factory=dict)
    input_schema: dict[str, JsonValue] | str | None = None
    output_schema: dict[str, JsonValue] | str | None = None
    supported_labels: dict[str, list[NonEmpty]] | list[NonEmpty] = Field(default_factory=dict)
    supported_camera_types: list[CameraType] = Field(default_factory=list)
    evaluation_report: str | dict[str, JsonValue] | None = None
    license: str | dict[str, JsonValue] | None = None
    resource_requirements: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unavailable_is_explicit(self) -> ModelManifest:
        if self.status in ("not_installed", "unavailable") and self.reason is None:
            raise ValueError("not_installed/unavailable models must explain reason")
        return self


class Artifact(VersionedModel):
    artifact_id: Identifier
    kind: NonEmpty
    relative_path: RelativePath
    sha256: Sha256
    size_bytes: NonNegativeInt
    created_at: datetime
    producer: NonEmpty | dict[str, JsonValue]


class CropWindow(ContractModel):
    """Normalized source-image rectangle; not a raw FFmpeg expression."""

    x: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    y: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    width: Annotated[float, Field(strict=True, gt=0, le=1, allow_inf_nan=False)]
    height: Annotated[float, Field(strict=True, gt=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def inside_source(self) -> CropWindow:
        if self.x + self.width > 1.000000001 or self.y + self.height > 1.000000001:
            raise ValueError("crop window must remain within the source image")
        return self


class TimelineSegment(ContractModel):
    segment_id: Identifier
    asset_id: Identifier
    in_ms: Milliseconds
    out_ms: Milliseconds
    speed: PositiveFloat = 1.0
    event_ids: list[Identifier] = Field(default_factory=list)
    fit: Literal["contain", "crop"] = "contain"
    crop: CropWindow | None = None
    title: str = ""
    audio: Literal["source", "mute"] = "source"
    review_status: ReviewStatus = "unreviewed"

    @model_validator(mode="after")
    def source_interval(self) -> TimelineSegment:
        if self.out_ms <= self.in_ms:
            raise ValueError("out_ms must be greater than in_ms")
        if self.fit == "crop" and self.crop is None:
            raise ValueError("fit=crop requires an explicit crop window")
        if self.fit == "contain" and self.crop is not None:
            raise ValueError("crop window requires fit=crop")
        _unique(self.event_ids, "event_id")
        return self


class TimelineOutput(ContractModel):
    width: PositiveInt = 1080
    height: PositiveInt = 1920
    fps: PositiveFloat = 30.0
    video_codec: Literal["h264"] = "h264"
    audio_codec: Literal["aac"] = "aac"


class Timeline(VersionedModel):
    timeline_id: Identifier
    title: str = ""
    segments: list[TimelineSegment] = Field(default_factory=list)
    output: TimelineOutput = Field(default_factory=TimelineOutput)

    @model_validator(mode="after")
    def unique_segments(self) -> Timeline:
        _unique([segment.segment_id for segment in self.segments], "segment_id")
        return self


class JobRequest(VersionedModel):
    job_id: Identifier
    attempt_id: Identifier
    operation: NonEmpty
    assets: list[Asset] = Field(default_factory=list)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    output_dir: RelativePath

    @model_validator(mode="after")
    def asset_mapping(self) -> JobRequest:
        _unique([asset.asset_id for asset in self.assets], "asset_id")
        parts = self.output_dir.split("/")
        if len(parts) < 2 or parts[0] not in {"platform", "data", "models", "render"}:
            raise ValueError("output_dir must be a child of a controlled owner directory")
        if self.operation == "render" and "assets" in self.parameters:
            raise ValueError("render assets belong in the top-level assets array only")
        return self


class JobError(ContractModel):
    code: NonEmpty
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class JobResult(VersionedModel):
    job_id: Identifier
    attempt_id: Identifier
    status: Literal["succeeded", "failed", "cancelled", "blocked"]
    artifacts: list[Artifact] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    error: JobError | None = None

    @model_validator(mode="after")
    def truthful_status(self) -> JobResult:
        if self.status in ("failed", "blocked") and self.error is None:
            raise ValueError("failed/blocked results require an error with a code")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("a succeeded result cannot contain an error")
        _unique([artifact.artifact_id for artifact in self.artifacts], "artifact_id")
        _unique([event.event_id for event in self.events], "event_id")
        return self


class ProgressEvent(VersionedModel):
    job_id: Identifier
    seq: NonNegativeInt
    event: Literal["progress", "artifact", "warning", "error"]
    stage: str | None = None
    current: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] | None = None
    total: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] | None = None
    unit: str | None = None
    message: str = ""

    @model_validator(mode="after")
    def measured_progress(self) -> ProgressEvent:
        if self.current is not None and self.total is not None and self.current > self.total:
            raise ValueError("current cannot be greater than total")
        return self
