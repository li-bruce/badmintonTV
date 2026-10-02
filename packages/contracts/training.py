"""Independent training-workspace contracts; never aliases production Events.

The service authenticates actors and verifies source bytes/catalog identity.
Contracts validate structure, time, references, taxonomy, and frozen snapshots.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .models import Identifier, NonEmpty, RelativePath, Sha256, Milliseconds, PositiveInt, NonNegativeInt

ActorType = Literal["human", "agent", "model", "import"]
RecordKind = Literal["rally", "contact", "dead_ball", "segment", "state"]
JudgementValue = Literal["present", "absent", "unknown", "not_applicable", "unlabeled", "unobservable"]
Split = Literal["train", "validation", "test", "unassigned"]
SubjectRole = Literal["self", "opponent", "partner", "opponent_partner"]
Finite = Annotated[float, Field(allow_inf_nan=False, strict=True)]


def utc_now():
    return datetime.now(timezone.utc)


def _immutable(*_args, **_kwargs):
    raise TypeError("training contract metadata is immutable")


class _FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self


class _FrozenList(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo):
        return self


def _freeze(value):
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _unique(values, description):
    values = list(values)
    if len(values) != len(set(values)):
        raise ValueError("duplicate " + description)


class TrainingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    @field_validator("*", mode="after")
    @classmethod
    def immutable_metadata(cls, value):
        return _freeze(value)


class TrainingProject(TrainingModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: Identifier
    name: NonEmpty
    usage_scope: Literal["training_only"] = "training_only"
    catalog_version: NonEmpty
    taxonomy_id: Identifier
    taxonomy_version: NonEmpty
    asset_ids: tuple[Identifier, ...] = ()
    revision: PositiveInt = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_assets(self):
        _unique(self.asset_ids, "project asset_id")
        return self


class TrainingAssetRef(TrainingModel):
    asset_id: Identifier
    sha256: Sha256
    relative_path: RelativePath
    size_bytes: PositiveInt
    duration_ms: PositiveInt
    title: str = ""
    usage_scope: Literal["training_only"] = "training_only"
    source_usage_scope: Literal["general", "training_only"] = "training_only"
    match_id: Identifier | None = None
    group_id: Identifier | None = None
    group_status: Literal["unknown", "unconfirmed", "confirmed"] = "unknown"
    root_asset_ids: tuple[Identifier, ...] = ()
    source_sha256s: tuple[Sha256, ...] = ()
    recording_session_id: Identifier | None = None
    source_group_ids: tuple[Identifier, ...] = ()
    pts_reference: dict[str, JsonValue] | None = None
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def group_and_pts(self):
        _unique(self.root_asset_ids, "root asset_id")
        _unique((value.lower() for value in self.source_sha256s), "source SHA256")
        _unique(self.source_group_ids, "source group_id")
        if self.group_status == "confirmed" and not self.group_id:
            raise ValueError("confirmed group requires group_id")
        if self.pts_reference:
            from .models import validate_relative_path
            for key in ("relative_path", "path"):
                if key in self.pts_reference:
                    if not isinstance(self.pts_reference[key], str):
                        raise ValueError("PTS reference path must be a string")
                    validate_relative_path(self.pts_reference[key])
            for key in ("sha256", "source_sha256"):
                value = self.pts_reference.get(key)
                if key in self.pts_reference and (not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value)):
                    raise ValueError("PTS reference hash must be SHA256")
            if self.pts_reference.get("source_sha256", self.sha256).lower() != self.sha256.lower():
                raise ValueError("PTS reference belongs to a different source hash")
            value = self.pts_reference.get("frame_count")
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("PTS frame_count must be positive")
        return self


class TrainingPerson(TrainingModel):
    person_id: Identifier
    display_name: NonEmpty
    team_id: Identifier | None = None
    identity_status: Literal["unknown", "unconfirmed", "confirmed"] = "unknown"
    provenance: dict[str, JsonValue] = Field(default_factory=dict)


class TrainingReview(TrainingModel):
    status: Literal["draft", "pending", "confirmed", "rejected"] = "draft"
    reviewer_type: ActorType | None = None
    reviewer: NonEmpty | None = None
    reviewed_at: datetime | None = None
    note: str = ""

    @model_validator(mode="after")
    def review_identity(self):
        if self.status in {"confirmed", "rejected"} and (not self.reviewer_type or not self.reviewer):
            raise ValueError("reviewed records require explicit reviewer and reviewer_type")
        return self


class TrainingJudgement(TrainingModel):
    label_id: Identifier
    subject_role: SubjectRole = "self"
    subject_person_id: Identifier | None = None
    value: JudgementValue
    reason: str | None = None
    confidence: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)] | None = None
    source_label: str | None = None
    mapping_status: Literal["manual", "exact", "coarse", "unverified"] = "manual"

    @model_validator(mode="after")
    def uncertainty_reason(self):
        if self.value in {"unknown", "unobservable"} and not (self.reason and self.reason.strip()):
            raise ValueError("unknown/unobservable judgement requires a reason")
        return self


class TrainingPosition(TrainingModel):
    coordinate_system: Literal["image_normalized", "court_m"]
    x: Finite
    y: Finite
    calibration_id: Identifier | None = None
    source: Literal["human", "agent", "model", "import"] = "agent"

    @model_validator(mode="after")
    def valid_position(self):
        if self.coordinate_system == "image_normalized" and not (0 <= self.x <= 1 and 0 <= self.y <= 1):
            raise ValueError("normalized image coordinates must be within [0,1]")
        if self.coordinate_system == "court_m" and not self.calibration_id:
            raise ValueError("court metre coordinates require an explicit calibration_id")
        if self.coordinate_system == "image_normalized" and self.calibration_id:
            raise ValueError("image coordinates must not claim court calibration")
        return self


class TrainingActorState(TrainingModel):
    person_id: Identifier | None = None
    team_id: Identifier | None = None
    position: TrainingPosition | None = None
    movement: str | None = None
    missing_reasons: tuple[NonEmpty, ...] = ()


class TrainingState(TrainingModel):
    self: TrainingActorState | None = None
    opponent: TrainingActorState | None = None
    partner: TrainingActorState | None = None
    opponent_partner: TrainingActorState | None = None
    incoming_ball: str | None = None
    outgoing_ball: str | None = None
    missing_reasons: tuple[NonEmpty, ...] = ()
    provenance: dict[str, JsonValue] = Field(default_factory=dict)


class TrainingRecord(TrainingModel):
    record_id: Identifier
    project_id: Identifier
    asset_id: Identifier
    kind: RecordKind
    at_ms: Milliseconds | None = None
    start_ms: Milliseconds | None = None
    end_ms: Milliseconds | None = None
    uncertainty_start_ms: Milliseconds | None = None
    uncertainty_end_ms: Milliseconds | None = None
    person_id: Identifier | None = None
    team_id: Identifier | None = None
    rally_id: Identifier | None = None
    dead_ball_id: Identifier | None = None
    segment_type: Literal["stroke", "footwork", "tactic", "other"] | None = None
    judgements: tuple[TrainingJudgement, ...] = ()
    state: TrainingState | None = None
    visibility: Literal["clear", "partial", "unobservable", "unknown"] = "unknown"
    unknown_reasons: tuple[NonEmpty, ...] = ()
    raw_labels: tuple[str, ...] = ()
    evidence: tuple[dict[str, JsonValue], ...] = ()
    review: TrainingReview = Field(default_factory=TrainingReview)
    revision: PositiveInt = 1
    previous_revision: PositiveInt | None = None
    deleted: bool = False
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def record_shape(self):
        if self.kind in {"contact", "dead_ball", "state"}:
            if self.at_ms is None or self.start_ms is not None or self.end_ms is not None:
                raise ValueError("point records require at_ms and cannot have interval bounds")
        elif self.at_ms is not None or self.start_ms is None or self.end_ms is None or self.start_ms >= self.end_ms:
            raise ValueError("interval records require ordered half-open start_ms/end_ms and no at_ms")
        if (self.uncertainty_start_ms is None) != (self.uncertainty_end_ms is None):
            raise ValueError("uncertainty requires both bounds")
        if self.uncertainty_start_ms is not None:
            if self.at_ms is None or not self.uncertainty_start_ms <= self.at_ms <= self.uncertainty_end_ms:
                raise ValueError("point uncertainty bounds must bracket at_ms")
        if self.kind == "rally" and self.rally_id is not None:
            raise ValueError("rally cannot reference another rally")
        if self.kind != "rally" and self.dead_ball_id is not None:
            raise ValueError("only a rally can reference dead_ball_id")
        if self.kind != "segment" and self.segment_type is not None:
            raise ValueError("only segments have segment_type")
        if self.kind == "state" and self.state is None:
            raise ValueError("state record requires state data")
        if self.revision == 1 and self.previous_revision is not None:
            raise ValueError("first revision has no previous_revision")
        if self.revision > 1 and self.previous_revision != self.revision - 1:
            raise ValueError("previous_revision must immediately precede revision")
        _unique(((j.label_id, j.subject_role, j.subject_person_id) for j in self.judgements), "judgement label/subject")
        return self


class TrainingAnnotationBundle(TrainingModel):
    schema_version: Literal["1.0"] = "1.0"
    format: Literal["badmintontv.training.annotations.v1"] = "badmintontv.training.annotations.v1"
    project_id: Identifier
    asset: TrainingAssetRef
    revision: PositiveInt = 1
    people: tuple[TrainingPerson, ...] = ()
    records: tuple[TrainingRecord, ...] = ()

    @model_validator(mode="after")
    def relationships(self):
        _unique((p.person_id for p in self.people), "person_id")
        _unique((r.record_id for r in self.records), "record_id")
        people = {p.person_id: p for p in self.people}
        records = {r.record_id: r for r in self.records if not r.deleted}
        duration = self.asset.duration_ms
        def person(person_id, team_id):
            if person_id and person_id not in people:
                raise ValueError("unknown person_id")
            if person_id and team_id and people[person_id].team_id != team_id:
                raise ValueError("person/team relation does not match")
        for record in self.records:
            if record.project_id != self.project_id or record.asset_id != self.asset.asset_id:
                raise ValueError("record project/asset identity differs from bundle")
            if record.at_ms is not None and not (record.at_ms <= duration if record.kind == "dead_ball" else record.at_ms < duration):
                raise ValueError("point is outside source duration")
            if record.end_ms is not None and record.end_ms > duration:
                raise ValueError("interval is outside source duration")
            if record.uncertainty_end_ms is not None and record.uncertainty_end_ms > duration:
                raise ValueError("uncertainty is outside source duration")
            if record.deleted:
                continue
            person(record.person_id, record.team_id)
            resolved_judgements = []
            for judgement in record.judgements:
                person(judgement.subject_person_id, None)
                role = getattr(record.state, judgement.subject_role) if record.state else None
                if judgement.subject_role != "self" and role is None:
                    raise ValueError("judgement subject role requires corresponding state role")
                expected_person = role.person_id if role else record.person_id
                if judgement.subject_person_id and expected_person and judgement.subject_person_id != expected_person:
                    raise ValueError("judgement subject person differs from state/record role")
                resolved_judgements.append((judgement.label_id, judgement.subject_role,
                                            judgement.subject_person_id or expected_person))
            _unique(resolved_judgements, "resolved judgement label/subject")
            if record.rally_id:
                rally = records.get(record.rally_id)
                if rally is None or rally.kind != "rally":
                    raise ValueError("rally_id must refer to a live rally")
                if record.at_ms is not None:
                    valid = rally.start_ms <= record.at_ms <= rally.end_ms if record.kind == "dead_ball" else rally.start_ms <= record.at_ms < rally.end_ms
                else:
                    valid = rally.start_ms <= record.start_ms < record.end_ms <= rally.end_ms
                if not valid:
                    raise ValueError("record time is outside its rally")
            if record.dead_ball_id:
                dead = records.get(record.dead_ball_id)
                if dead is None or dead.kind != "dead_ball" or dead.rally_id != record.record_id or dead.at_ms != record.end_ms:
                    raise ValueError("rally end requires its independent dead-ball mark at end_ms")
            if record.state:
                actors = [s for s in (record.state.self, record.state.opponent, record.state.partner, record.state.opponent_partner) if s]
                for actor in actors:
                    person(actor.person_id, actor.team_id)
                _unique((s.person_id for s in actors if s.person_id), "state role person")
                own, opponent, partner = record.state.self, record.state.opponent, record.state.partner
                if own and record.person_id and own.person_id != record.person_id:
                    raise ValueError("state self must match record person")
                def team(actor):
                    return (actor.team_id or (people[actor.person_id].team_id if actor.person_id else None)) if actor else None
                if team(own) and team(opponent) == team(own):
                    raise ValueError("opponent cannot be on self team")
                if team(own) and team(partner) and team(partner) != team(own):
                    raise ValueError("partner must be on self team")
                opponent_partner = record.state.opponent_partner
                if team(own) and team(opponent_partner) == team(own):
                    raise ValueError("opponent partner cannot be on self team")
                if team(opponent) and team(opponent_partner) and team(opponent_partner) != team(opponent):
                    raise ValueError("opponent partners must share a team")
        return self


class TrainingBundleUpdate(TrainingModel):
    bundle: TrainingAnnotationBundle
    expected_revision: NonNegativeInt


class TrainingLabel(TrainingModel):
    label_id: Identifier
    name: NonEmpty
    dimension: NonEmpty
    parent_id: Identifier | None = None
    description: NonEmpty
    kinds: tuple[RecordKind, ...]
    status: Literal["provisional", "defined"] = "provisional"
    selectable: bool = True
    requires_person: bool = True


class TrainingTaxonomy(TrainingModel):
    schema_version: Literal["1.0"] = "1.0"
    format: Literal["badmintontv.training.taxonomy.v1"] = "badmintontv.training.taxonomy.v1"
    taxonomy_id: Identifier
    version: NonEmpty
    status: Literal["provisional", "reviewed"] = "provisional"
    labels: tuple[TrainingLabel, ...]
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def taxonomy_graph(self):
        _unique((label.label_id for label in self.labels), "taxonomy label_id")
        labels = {label.label_id: label for label in self.labels}
        for label in self.labels:
            if not label.kinds:
                raise ValueError("label requires at least one record kind")
            _unique(label.kinds, "label kind")
            seen, cursor = {label.label_id}, label
            while cursor.parent_id:
                if cursor.parent_id not in labels or cursor.parent_id in seen:
                    raise ValueError("taxonomy parent is missing or cyclic")
                seen.add(cursor.parent_id)
                cursor = labels[cursor.parent_id]
                if cursor.dimension != label.dimension:
                    raise ValueError("taxonomy parent must retain dimension")
        return self


def get_default_training_taxonomy() -> TrainingTaxonomy:
    """Explicit provisional fallback; callers freeze the chosen taxonomy per project."""
    return TrainingTaxonomy.model_validate_json((Path(__file__).parent / "fixtures/training.taxonomy.provisional.v1.json").read_text(encoding="utf-8"))


def validate_training_bundle(bundle, taxonomy) -> TrainingAnnotationBundle:
    bundle = TrainingAnnotationBundle.model_validate(bundle)
    taxonomy = TrainingTaxonomy.model_validate(taxonomy)
    labels = {label.label_id: label for label in taxonomy.labels}
    for record in bundle.records:
        for judgement in record.judgements:
            label = labels.get(judgement.label_id)
            if label is None:
                raise ValueError("unknown taxonomy label_id: " + judgement.label_id)
            if not label.selectable:
                raise ValueError("taxonomy group is not a selectable judgement: " + judgement.label_id)
            if record.kind not in label.kinds:
                raise ValueError("label kind is not allowed: " + judgement.label_id)
    return bundle


def _record_content(record):
    value = record.model_dump(mode="json")
    for key in ("revision", "previous_revision"):
        value.pop(key)
    provenance = value.get("provenance", {})
    provenance.pop("revision_audit", None)
    return value


def _semantic_record(record):
    value = _record_content(record)
    value.pop("review")
    return value


def _referenced_people(record):
    result = {record.person_id} if record.person_id else set()
    result.update(j.subject_person_id for j in record.judgements if j.subject_person_id)
    if record.state:
        result.update(actor.person_id for actor in (record.state.self, record.state.opponent, record.state.partner, record.state.opponent_partner) if actor and actor.person_id)
    return result


def validate_training_revision(current, incoming, expected_revision, *, actor_type="agent"):
    if actor_type not in {"human", "agent", "model", "import"}:
        raise ValueError("invalid trusted actor_type")
    incoming = TrainingAnnotationBundle.model_validate(incoming)
    current = TrainingAnnotationBundle.model_validate(current) if current is not None else None
    if type(expected_revision) is not int or expected_revision != (current.revision if current else 0):
        raise ValueError("training bundle revision conflict")
    if current and (incoming.project_id != current.project_id or incoming.asset != current.asset):
        raise ValueError("bundle project/asset identity is immutable")
    prior_people = {p.person_id: p for p in current.people} if current else {}
    for person in incoming.people:
        old = prior_people.get(person.person_id)
        if actor_type != "human" and person.identity_status == "confirmed" and old != person:
            raise ValueError("trusted actor does not permit new or changed confirmed person identity")
    prior = {r.record_id: r for r in current.records} if current else {}
    for record in incoming.records:
        old = prior.get(record.record_id)
        if record.review.reviewer_type == "human" and actor_type != "human" and (old is None or record.review != old.review):
            raise ValueError("trusted actor does not permit human review")
        if record.state and actor_type != "human":
            for role in ("self", "opponent", "partner", "opponent_partner"):
                state = getattr(record.state, role)
                old_state = getattr(old.state, role) if old and old.state else None
                if state and state.position and state.position.source == "human" and (not old_state or state.position != old_state.position):
                    raise ValueError("trusted actor does not permit new or changed human position")
    return incoming


def next_bundle_revision(current, incoming, expected_revision, *, actor_type="agent", reviewer):
    """Server CAS helper: increment changed records, retain tombstones, stamp actor.

    The caller authenticates actor_type and validates taxonomy/current AssetRef.
    Return values must be persisted atomically with the CAS and previous bundle.
    """
    incoming = validate_training_revision(current, incoming, expected_revision, actor_type=actor_type)
    current = TrainingAnnotationBundle.model_validate(current) if current is not None else None
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("trusted reviewer must be nonblank")
    prior = {r.record_id: r for r in current.records} if current else {}
    old_people = {p.person_id: p for p in current.people} if current else {}
    new_people = {p.person_id: p for p in incoming.people}
    changed_people = {key for key in set(old_people) | set(new_people) if old_people.get(key) != new_people.get(key)}
    values, seen = [], set()
    for record in incoming.records:
        old = prior.get(record.record_id)
        seen.add(record.record_id)
        semantics_changed = old is not None and (_semantic_record(old) != _semantic_record(record)
            or bool((_referenced_people(old) | _referenced_people(record)) & changed_people))
        changed = old is None or _record_content(old) != _record_content(record) or semantics_changed
        if not changed:
            values.append(old.model_dump(mode="json"))
            continue
        value = record.model_dump(mode="json")
        value.update(revision=old.revision + 1 if old else 1, previous_revision=old.revision if old else None)
        if semantics_changed:
            value["review"] = {"status": "pending", "reviewer_type": None, "reviewer": None, "reviewed_at": None,
                               "note": "Content or referenced person changed; review required"}
        else:
            value["review"].update(reviewer=reviewer, reviewer_type=actor_type, reviewed_at=utc_now().isoformat())
        value["provenance"] = {**value["provenance"], "revision_audit": {"actor_type": actor_type, "reviewer": reviewer, "at": utc_now().isoformat()}}
        values.append(value)
    for key, old in prior.items():
        if key not in seen:
            value = old.model_dump(mode="json")
            if not old.deleted:
                value.update(deleted=True, revision=old.revision + 1, previous_revision=old.revision)
                value["review"] = {"status": "pending", "reviewer_type": None, "reviewer": None, "reviewed_at": None}
                value["provenance"] = {**value["provenance"], "revision_audit": {"actor_type": actor_type, "reviewer": reviewer, "at": utc_now().isoformat()}}
            values.append(value)
    body = incoming.model_dump(mode="json")
    body.update(revision=expected_revision + 1, records=values)
    return TrainingAnnotationBundle.model_validate(body)


class TrainingSplit(TrainingModel):
    group_id: Identifier
    split: Split = "unassigned"


class TrainingExample(TrainingModel):
    asset_id: Identifier
    record_id: Identifier
    record_revision: PositiveInt
    label_id: Identifier
    subject_role: SubjectRole = "self"
    subject_person_id: Identifier | None = None
    value: Literal["present", "absent"]
    split: Split


class TrainingExclusion(TrainingModel):
    asset_id: Identifier
    record_id: Identifier
    label_id: Identifier | None = None
    subject_role: SubjectRole = "self"
    subject_person_id: Identifier | None = None
    reasons: tuple[NonEmpty, ...]


class TrainingQualitySummary(TrainingModel):
    record_count: NonNegativeInt
    eligible_judgement_count: NonNegativeInt
    excluded_judgement_count: NonNegativeInt
    unassigned_asset_ids: tuple[Identifier, ...]
    unconfirmed_match_asset_ids: tuple[Identifier, ...] = ()
    missing_dead_ball_rally_ids: tuple[Identifier, ...]
    trainable: bool
    blockers: tuple[NonEmpty, ...]


def _has_observation_evidence(record):
    for item in record.evidence:
        if any(isinstance(item.get(key), str) and item[key].strip() for key in
               ("reference", "ref", "relative_path", "source", "evidence_id")):
            return True
        if any(type(item.get(key)) is int and item[key] >= 0 for key in ("at_ms", "source_frame_index")):
            return True
    return False


def _confirmed_match_group(asset):
    proof = asset.provenance.get("group_evidence")
    return bool(asset.match_id and asset.group_status == "confirmed" and asset.group_id and asset.group_id != asset.asset_id
        and isinstance(proof, dict) and proof.get("verified") is True
        and all(isinstance(proof.get(key), str) and proof[key].strip() for key in ("source", "reference")))


def _derive_training_view(assets, bundles, taxonomy, splits):
    assignment = {s.group_id: s.split for s in splits}
    if len(assignment) != len(splits):
        raise ValueError("duplicate group split")
    known_groups = {a.group_id for a in assets if a.group_id}
    if set(assignment) - known_groups:
        raise ValueError("split refers to unknown group")
    actual_split, connected = {}, {}
    for asset in assets:
        split = assignment.get(asset.group_id, "unassigned")
        if split != "unassigned" and asset.group_status != "confirmed":
            raise ValueError("unconfirmed/unknown group cannot have assigned split")
        if split != "unassigned" and asset.group_id == asset.asset_id:
            raise ValueError("asset_id cannot pretend to be an independent match group")
        actual_split[asset.asset_id] = split
        tokens = [("hash", asset.sha256.lower()), ("asset", asset.asset_id)]
        tokens.extend(("hash", key.lower()) for key in asset.source_sha256s)
        tokens.extend(("asset", key) for key in asset.root_asset_ids)
        tokens.extend(("group", key) for key in asset.source_group_ids)
        tokens.extend((kind, key) for kind, key in (("match", asset.match_id),
            ("group", asset.group_id), ("session", asset.recording_session_id)) if key)
        for token in tokens:
            previous = connected.setdefault(token, split)
            if previous != split:
                raise ValueError("same source hash, match, lineage or recording session cannot leak across group splits")
    labels = {label.label_id: label for label in taxonomy.labels}
    examples, excluded, missing_ends = [], [], []
    count = 0
    for bundle in bundles:
        validate_training_bundle(bundle, taxonomy)
        people = {p.person_id: p for p in bundle.people}
        for record in bundle.records:
            count += 1
            if record.kind == "rally" and not record.deleted and not record.dead_ball_id:
                missing_ends.append(record.record_id)
            for judgement in record.judgements:
                label = labels[judgement.label_id]
                reasons = []
                if record.deleted:
                    reasons.append("deleted")
                if record.review.status != "confirmed":
                    reasons.append("not_confirmed")
                if record.review.reviewer_type != "human":
                    reasons.append("not_human_review")
                if taxonomy.status != "reviewed" or label.status != "defined":
                    reasons.append("provisional_semantics")
                if judgement.value not in {"present", "absent"}:
                    reasons.append(judgement.value)
                if judgement.mapping_status in {"coarse", "unverified"}:
                    reasons.append("mapping_not_semantically_confirmed")
                role = getattr(record.state, judgement.subject_role) if record.state else None
                subject = judgement.subject_person_id or (role.person_id if role else record.person_id)
                person = people.get(subject)
                if label.requires_person and (person is None or person.identity_status != "confirmed"):
                    reasons.append("identity_unknown")
                if judgement.value in {"present", "absent"}:
                    if record.visibility not in {"clear", "partial"}:
                        reasons.append("observation_visibility_insufficient")
                    if not _has_observation_evidence(record):
                        reasons.append("observation_evidence_missing")
                if judgement.value == "absent":
                    if not judgement.reason or judgement.reason.strip().lower() in {"", "unknown", "unobservable", "未知", "不明", "看不清"}:
                        reasons.append("negative_reason_missing")
                if reasons:
                    excluded.append(TrainingExclusion(asset_id=record.asset_id, record_id=record.record_id, label_id=judgement.label_id,
                        subject_role=judgement.subject_role, subject_person_id=subject, reasons=reasons))
                else:
                    examples.append(TrainingExample(asset_id=record.asset_id, record_id=record.record_id, record_revision=record.revision,
                        label_id=judgement.label_id, subject_role=judgement.subject_role, subject_person_id=subject,
                        value=judgement.value, split=actual_split[record.asset_id]))
    unassigned = tuple(a.asset_id for a in assets if actual_split[a.asset_id] == "unassigned")
    unknown_match = tuple(a.asset_id for a in assets if not _confirmed_match_group(a))
    blockers = []
    if not examples:
        blockers.append("no_human_confirmed_semantically_defined_judgements")
    if unassigned:
        blockers.append("unassigned_or_unconfirmed_groups")
    if missing_ends:
        blockers.append("rally_dead_ball_missing")
    if unknown_match:
        blockers.append("independent_match_group_unconfirmed")
    summary = TrainingQualitySummary(record_count=count, eligible_judgement_count=len(examples), excluded_judgement_count=len(excluded),
        unassigned_asset_ids=unassigned, unconfirmed_match_asset_ids=unknown_match,
        missing_dead_ball_rally_ids=tuple(missing_ends), trainable=not blockers, blockers=blockers)
    return tuple(examples), tuple(excluded), summary


class _SnapshotPayload(TrainingModel):
    schema_version: Literal["1.0"] = "1.0"
    format: Literal["badmintontv.training.snapshot.v1"] = "badmintontv.training.snapshot.v1"
    snapshot_id: Identifier
    usage_scope: Literal["training_only"] = "training_only"
    project: TrainingProject
    taxonomy: TrainingTaxonomy
    assets: tuple[TrainingAssetRef, ...]
    bundles: tuple[TrainingAnnotationBundle, ...]
    splits: tuple[TrainingSplit, ...] = ()
    training_view: tuple[TrainingExample, ...]
    exclusions: tuple[TrainingExclusion, ...]
    quality_summary: TrainingQualitySummary
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def snapshot_relationships(self):
        if (self.project.taxonomy_id, self.project.taxonomy_version) != (self.taxonomy.taxonomy_id, self.taxonomy.version):
            raise ValueError("project taxonomy version differs from frozen taxonomy")
        _unique((a.asset_id for a in self.assets), "snapshot asset_id")
        _unique((b.asset.asset_id for b in self.bundles), "snapshot bundle asset")
        assets = {a.asset_id: a for a in self.assets}
        if set(self.project.asset_ids) != set(assets):
            raise ValueError("snapshot assets must exactly match project asset_ids")
        for bundle in self.bundles:
            if bundle.project_id != self.project.project_id or assets.get(bundle.asset.asset_id) != bundle.asset:
                raise ValueError("snapshot bundle differs from frozen project/asset")
        examples, excluded, summary = _derive_training_view(self.assets, self.bundles, self.taxonomy, self.splits)
        if (self.training_view, self.exclusions, self.quality_summary) != (examples, excluded, summary):
            raise ValueError("snapshot training view/summary must be derived from frozen annotations")
        return self


def training_content_sha256(payload):
    value = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else dict(payload)
    value.pop("content_sha256", None)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class TrainingSnapshot(_SnapshotPayload):
    content_sha256: Sha256

    @model_validator(mode="after")
    def valid_content_hash(self):
        if self.content_sha256.lower() != training_content_sha256(self):
            raise ValueError("snapshot content hash mismatch")
        return self


def build_training_snapshot(*, snapshot_id, project, taxonomy, assets, bundles, splits=(), created_at=None) -> TrainingSnapshot:
    project = TrainingProject.model_validate(project)
    taxonomy = TrainingTaxonomy.model_validate(taxonomy)
    assets = tuple(TrainingAssetRef.model_validate(a) for a in assets)
    bundles = tuple(validate_training_bundle(b, taxonomy) for b in bundles)
    splits = tuple(TrainingSplit.model_validate(s) for s in splits)
    examples, excluded, quality = _derive_training_view(assets, bundles, taxonomy, splits)
    payload = _SnapshotPayload(snapshot_id=snapshot_id, project=project, taxonomy=taxonomy, assets=assets, bundles=bundles,
        splits=splits, training_view=examples, exclusions=excluded, quality_summary=quality, created_at=created_at or utc_now())
    body = payload.model_dump(mode="json")
    return TrainingSnapshot.model_validate({**body, "content_sha256": training_content_sha256(body)})


TRAINING_CONTRACT_TYPES = {cls.__name__: cls for cls in (TrainingProject, TrainingAssetRef, TrainingAnnotationBundle,
    TrainingBundleUpdate, TrainingTaxonomy, TrainingSnapshot)}


def training_schemas():
    return {name: cls.model_json_schema() for name, cls in TRAINING_CONTRACT_TYPES.items()}


__all__ = ["ActorType", "RecordKind", "JudgementValue", "SubjectRole", "TrainingProject", "TrainingAssetRef", "TrainingPerson",
    "TrainingReview", "TrainingJudgement", "TrainingPosition", "TrainingActorState", "TrainingState", "TrainingRecord",
    "TrainingAnnotationBundle", "TrainingBundleUpdate", "TrainingLabel", "TrainingTaxonomy", "TrainingSplit",
    "TrainingExample", "TrainingExclusion", "TrainingQualitySummary", "TrainingSnapshot", "validate_training_bundle",
    "validate_training_revision", "next_bundle_revision", "get_default_training_taxonomy", "build_training_snapshot",
    "training_content_sha256", "training_schemas", "TRAINING_CONTRACT_TYPES"]
