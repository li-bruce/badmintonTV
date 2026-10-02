"""A-14 region transport/authority assertions; all annotations are synthetic."""
import copy
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.training import (
    TrainingAnnotationBundle, TrainingImageRegion, TrainingSnapshot,
    build_training_snapshot, next_bundle_revision, training_content_sha256,
)


FIXTURES = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures"


@pytest.fixture
def bundle():
    return json.loads((FIXTURES / "training.annotations.v1.json").read_text(encoding="utf-8"))


def region(record, **changes):
    value = {"type": "image_region", "schema_version": "1.0", "evidence_id": "region-synthetic",
             "record_id": record["record_id"], "asset_id": record["asset_id"],
             "at_ms": record.get("at_ms") if record.get("at_ms") is not None else record["start_ms"],
             "coordinate_system": "image_normalized", "shape": "rectangle",
             "points": [{"x": .2, "y": .3}, {"x": .6, "y": .8}],
             "subject_role": "self", "subject_person_id": record.get("person_id"),
             "observation_source": "agent", "precision": "browser_time"}
    value.update(changes)
    return value


def attach(bundle, index=1, **changes):
    record = bundle["records"][index]
    value = region(record, **changes)
    record["evidence"].append(value)
    return value


@pytest.mark.parametrize("shape,points", [
    ("rectangle", [(0., 0.), (1., 1.)]),
    ("rectangle", [(1., 1.), (0., 0.)]),
    ("polygon", [(0., 0.), (1., 0.), (1., 1.), (.5, .5), (0., 1.)]),
    ("polygon", [(0., 1.), (.5, .5), (1., 1.), (1., 0.), (0., 0.)]),
    ("polygon", [(0., 0.), (.5, 0.), (1., 0.), (1., 1.), (0., 1.)]),
])
def test_valid_geometry_round_trips_without_rewriting_evidence(bundle, shape, points):
    item = attach(bundle, shape=shape, points=[{"x": x, "y": y} for x, y in points])
    item.pop("subject_person_id")
    saved = TrainingAnnotationBundle.model_validate(bundle)
    assert saved.model_dump(mode="json")["records"][1]["evidence"][-1] == item
    assert "subject_person_id" not in saved.records[1].evidence[-1]


@pytest.mark.parametrize("points", [
    [(0., 0.), (0., 1.)], [(0., 0.), (1., 0.)], [(.2, .3), (.2, .3)],
    [(0., 0.), (1., 1.), (0., 1.)],
])
def test_degenerate_rectangles_are_rejected(bundle, points):
    attach(bundle, points=[{"x": x, "y": y} for x, y in points])
    with pytest.raises(ValidationError):
        TrainingAnnotationBundle.model_validate(bundle)


@pytest.mark.parametrize("points", [
    [(0., 0.), (1., 1.)],
    [(0., 0.), (.5, .5), (1., 1.)],
    [(0., 0.), (1., 0.), (1., 1.), (0., 0.)],
    [(0., 0.), (1., 1.), (0., 1.), (1., 0.)],
    [(0., 0.), (1., 1.), (0., 1.), (1., 0.), (.5, .2)],
    [(0., 0.), (1., 0.), (.5, 0.), (1., 1.), (0., 1.)],
    [(0., 0.), (1., 0.), (1., 1.), (.5, 0.), (0., 1.)],
])
def test_polygons_reject_repeat_zero_area_overlap_and_self_intersection(bundle, points):
    attach(bundle, shape="polygon", points=[{"x": x, "y": y} for x, y in points])
    with pytest.raises(ValidationError):
        TrainingAnnotationBundle.model_validate(bundle)


@pytest.mark.parametrize("coordinate", [True, False, "0.3", -.001, 1.001, float("nan"), float("inf"), float("-inf")])
def test_coordinates_are_finite_strict_normalized_numbers(bundle, coordinate):
    item = attach(bundle)
    item["points"][0]["x"] = coordinate
    with pytest.raises(ValidationError):
        TrainingAnnotationBundle.model_validate(bundle)


def test_polygon_vertex_budget_is_bounded(bundle):
    item = attach(bundle, shape="polygon", points=[{"x": .5 + .4 * math.cos(i * 2 * math.pi / 64),
                                                   "y": .5 + .4 * math.sin(i * 2 * math.pi / 64)} for i in range(64)])
    TrainingAnnotationBundle.model_validate(bundle)
    item["points"].append({"x": 0., "y": 0.})
    with pytest.raises(ValidationError):
        TrainingAnnotationBundle.model_validate(bundle)


@pytest.mark.parametrize("change", [
    {"record_id": "different-record"}, {"asset_id": "different-asset"}, {"at_ms": 2001},
    {"at_ms": True}, {"precision": "exact_frame"}, {"coordinate_system": "court_m"},
    {"subject_person_id": "missing-person"}, {"subject_person_id": "person-b"},
    {"subject_role": "opponent"}, {"observation_source": "import"},
    {"source_frame_index": 100}, {"schema_version": "2.0"},
])
def test_region_identity_time_subject_and_precision_are_bound(bundle, change):
    attach(bundle, **change)
    with pytest.raises(ValidationError):
        TrainingAnnotationBundle.model_validate(bundle)


def test_interval_region_start_allowed_end_excluded_and_contact_never_retimed(bundle):
    item = attach(bundle, index=4)
    TrainingAnnotationBundle.model_validate(bundle)
    item["at_ms"] = bundle["records"][4]["end_ms"]
    with pytest.raises(ValidationError, match="interval"):
        TrainingAnnotationBundle.model_validate(bundle)
    assert bundle["records"][1]["at_ms"] == 2000


def test_image_cannot_be_observed_at_media_end_even_for_dead_ball(bundle):
    bundle["records"][0]["end_ms"] = bundle["asset"]["duration_ms"]
    bundle["records"][3]["at_ms"] = bundle["asset"]["duration_ms"]
    attach(bundle, index=3)
    with pytest.raises(ValidationError, match="source duration"):
        TrainingAnnotationBundle.model_validate(bundle)


def test_duplicate_evidence_id_is_rejected(bundle):
    item = attach(bundle)
    bundle["records"][1]["evidence"].append(copy.deepcopy(item))
    with pytest.raises(ValidationError, match="evidence_id"):
        TrainingAnnotationBundle.model_validate(bundle)


def test_opponent_region_tracks_state_role_and_team(bundle):
    attach(bundle, index=5, subject_role="opponent", subject_person_id="person-b")
    TrainingAnnotationBundle.model_validate(bundle)
    bundle["records"][5]["state"]["opponent"]["team_id"] = "team-a"
    with pytest.raises(ValidationError, match="team"):
        TrainingAnnotationBundle.model_validate(bundle)


@pytest.mark.parametrize("team", ["team-b", None])
def test_region_subject_cannot_bypass_role_team_with_unknown_state_person(bundle, team):
    bundle["records"][5]["state"]["opponent"].update(person_id=None, team_id=team)
    attach(bundle, index=5, subject_role="opponent", subject_person_id="person-a")
    with pytest.raises(ValidationError, match="team|role"):
        TrainingAnnotationBundle.model_validate(bundle)


@pytest.mark.parametrize("evidence_kind", ["region", "judgement"])
def test_record_self_fallback_cannot_reappear_as_opponent(bundle, evidence_kind):
    record = bundle["records"][1]
    record["state"] = {"opponent": {"person_id": "person-a", "team_id": "team-a"}}
    if evidence_kind == "region":
        attach(bundle, subject_role="opponent", subject_person_id="person-a")
    else:
        record["judgements"][0].update(subject_role="opponent", subject_person_id="person-a")
    with pytest.raises(ValidationError, match="duplicate subject role person"):
        TrainingAnnotationBundle.model_validate(bundle)


@pytest.mark.parametrize("role,team", [("opponent", "team-a"), ("opponent_partner", "team-a"), ("partner", "team-b")])
def test_record_self_team_fallback_enforces_side_relationships(bundle, role, team):
    bundle["people"].append({"person_id": "person-c", "display_name": "Synthetic C", "team_id": team, "identity_status": "unknown"})
    bundle["records"][1]["state"] = {role: {"person_id": "person-c", "team_id": team}}
    attach(bundle, subject_role=role, subject_person_id="person-c")
    with pytest.raises(ValidationError, match="team"):
        TrainingAnnotationBundle.model_validate(bundle)


def test_valid_four_distinct_roles_with_self_record_fallback(bundle):
    bundle["people"].extend([
        {"person_id": "person-c", "display_name": "Synthetic C", "team_id": "team-a", "identity_status": "unknown"},
        {"person_id": "person-d", "display_name": "Synthetic D", "team_id": "team-b", "identity_status": "unknown"},
    ])
    bundle["records"][1]["state"] = {
        "opponent": {"person_id": "person-b", "team_id": "team-b"},
        "partner": {"person_id": "person-c", "team_id": "team-a"},
        "opponent_partner": {"person_id": "person-d", "team_id": "team-b"},
    }
    attach(bundle, subject_role="opponent_partner", subject_person_id="person-d")
    TrainingAnnotationBundle.model_validate(bundle)


@pytest.mark.parametrize("actor", ["agent", "model", "import"])
def test_nonhuman_cannot_add_or_edit_human_region_but_can_keep_original(bundle, actor):
    original = TrainingAnnotationBundle.model_validate(bundle)
    item = attach(bundle, observation_source="human")
    with pytest.raises(ValueError, match="human image region"):
        next_bundle_revision(original, bundle, original.revision, actor_type=actor, reviewer="trusted actor")
    existing = TrainingAnnotationBundle.model_validate(bundle)
    kept = next_bundle_revision(existing, bundle, existing.revision, actor_type=actor, reviewer="trusted actor")
    assert kept.records[1].evidence[-1] == item
    item["points"][0]["x"] = .25
    with pytest.raises(ValueError, match="human image region"):
        next_bundle_revision(existing, bundle, existing.revision, actor_type=actor, reviewer="trusted actor")


@pytest.mark.parametrize("action", ["delete", "edit"])
@pytest.mark.parametrize("source", ["agent", "human"])
def test_changing_region_clears_confirmed_record_review(bundle, action, source):
    attach(bundle, observation_source=source)
    bundle["records"][1]["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-human"}
    current = TrainingAnnotationBundle.model_validate(bundle)
    if action == "delete":
        bundle["records"][1]["evidence"].pop()
    else:
        bundle["records"][1]["evidence"][-1]["points"][0]["x"] = .25
        bundle["records"][1]["evidence"][-1]["observation_source"] = "agent"
    changed = next_bundle_revision(current, bundle, current.revision, actor_type="agent", reviewer="test-agent")
    assert changed.records[1].revision == 2
    assert changed.records[1].review.status == "pending"
    assert changed.records[1].review.reviewer_type is None


def test_human_position_inherited_subject_cannot_be_rebound_by_agent(bundle):
    record = bundle["records"][5]
    record["state"]["opponent"]["position"]["source"] = "human"
    bundle["people"].append({"person_id": "person-c", "display_name": "Synthetic C", "team_id": "team-b", "identity_status": "unknown"})
    current = TrainingAnnotationBundle.model_validate(bundle)
    record["state"]["opponent"]["person_id"] = "person-c"
    with pytest.raises(ValueError, match="human position"):
        next_bundle_revision(current, bundle, current.revision, actor_type="agent", reviewer="agent")
    record["state"]["opponent"]["position"]["source"] = "agent"
    saved = next_bundle_revision(current, bundle, current.revision, actor_type="agent", reviewer="agent")
    assert saved.records[5].state.opponent.position.source == "agent"
    assert saved.records[5].review.status == "pending"


def test_human_actor_can_write_human_region_without_auto_confirming(bundle):
    current = TrainingAnnotationBundle.model_validate(bundle)
    attach(bundle, observation_source="human")
    changed = next_bundle_revision(current, bundle, current.revision, actor_type="human", reviewer="synthetic-human")
    assert changed.records[1].evidence[-1]["observation_source"] == "human"
    assert changed.records[1].review.status == "pending"


@pytest.mark.parametrize("explicit_null", [False, True])
def test_agent_cannot_rebind_inherited_human_region_by_changing_record_person(bundle, explicit_null):
    item = attach(bundle, observation_source="human", subject_person_id=None)
    if not explicit_null:
        item.pop("subject_person_id")
    current = TrainingAnnotationBundle.model_validate(bundle)
    bundle["records"][1].update(person_id="person-b", team_id="team-b")
    assert bundle["records"][1]["review"]["status"] == "pending"
    with pytest.raises(ValueError, match="human image region"):
        next_bundle_revision(current, bundle, current.revision, actor_type="agent", reviewer="agent")


def test_agent_cannot_rebind_human_region_via_state_role(bundle):
    bundle["people"].append({"person_id": "person-c", "display_name": "Synthetic C", "team_id": "team-b", "identity_status": "unknown"})
    attach(bundle, index=5, observation_source="human", subject_role="opponent", subject_person_id=None)
    current = TrainingAnnotationBundle.model_validate(bundle)
    bundle["records"][5]["state"]["opponent"]["person_id"] = "person-c"
    with pytest.raises(ValueError, match="human image region"):
        next_bundle_revision(current, bundle, current.revision, actor_type="agent", reviewer="agent")


def test_agent_cannot_change_effective_human_region_person_team(bundle):
    bundle["people"].append({"person_id": "person-c", "display_name": "Synthetic C", "team_id": "team-c", "identity_status": "unknown"})
    bundle["records"][1].update(person_id="person-c", team_id=None)
    attach(bundle, observation_source="human", subject_person_id=None)
    current = TrainingAnnotationBundle.model_validate(bundle)
    bundle["people"][-1]["team_id"] = "team-d"
    with pytest.raises(ValueError, match="human image region"):
        next_bundle_revision(current, bundle, current.revision, actor_type="agent", reviewer="agent")


def test_agent_cannot_change_human_region_inherited_team_with_unknown_person(bundle):
    bundle["records"][1].update(person_id=None, team_id="team-a")
    attach(bundle, observation_source="human", subject_person_id=None)
    current = TrainingAnnotationBundle.model_validate(bundle)
    bundle["records"][1]["team_id"] = "team-b"
    with pytest.raises(ValueError, match="human image region"):
        next_bundle_revision(current, bundle, current.revision, actor_type="agent", reviewer="agent")


def test_agent_cannot_rebind_human_region_through_judgement_subject(bundle):
    bundle["records"][1].update(person_id=None, team_id=None)
    bundle["records"][1]["judgements"][0]["subject_person_id"] = "person-a"
    attach(bundle, observation_source="human", subject_person_id=None)
    current = TrainingAnnotationBundle.model_validate(bundle)
    bundle["records"][1]["judgements"][0]["subject_person_id"] = "person-b"
    with pytest.raises(ValueError, match="human image region"):
        next_bundle_revision(current, bundle, current.revision, actor_type="agent", reviewer="agent")


def test_human_can_rebind_human_region_with_review_reset(bundle):
    attach(bundle, observation_source="human", subject_person_id=None)
    bundle["records"][1]["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-human"}
    current = TrainingAnnotationBundle.model_validate(bundle)
    bundle["records"][1].update(person_id="person-b", team_id="team-b")
    result = next_bundle_revision(current, bundle, current.revision, actor_type="human", reviewer="synthetic-human")
    assert result.records[1].review.status == "pending"
    assert result.records[1].review.reviewer_type is None


def test_non_region_evidence_is_preserved_without_new_validation(bundle):
    item = {"type": "legacy-unstructured", "points": "opaque", "at_ms": -20, "source": "old-format"}
    bundle["records"][1]["evidence"].append(item)
    assert TrainingAnnotationBundle.model_validate(bundle).model_dump(mode="json")["records"][1]["evidence"][-1] == item


def test_new_region_snapshot_preserves_evidence_and_training_gates(bundle):
    old = TrainingSnapshot.model_validate_json((FIXTURES / "training.snapshot.v1.json").read_text(encoding="utf-8"))
    item = attach(bundle)
    snap = build_training_snapshot(snapshot_id="region-synthetic", project=old.project, taxonomy=old.taxonomy,
                                   assets=old.assets, bundles=[bundle], created_at=old.created_at)
    assert snap.bundles[0].records[1].evidence[-1] == item
    assert snap.usage_scope == "training_only"
    assert snap.training_view == () and not snap.quality_summary.trainable
    assert TrainingSnapshot.model_validate_json(snap.model_dump_json()) == snap


def test_existing_canonical_snapshot_dump_and_hash_are_unchanged():
    body = json.loads((FIXTURES / "training.snapshot.v1.json").read_text(encoding="utf-8"))
    model = TrainingSnapshot.model_validate(body)
    assert model.model_dump(mode="json") == body
    assert training_content_sha256(model) == body["content_sha256"]


def test_actual_historical_snapshot_dump_and_hash_are_unchanged():
    path = Path("D:/video/platform/integration-20261002/snapshot-before-restart.json")
    if not path.is_file():
        pytest.skip("read-only real integration snapshot is not available on this host")
    body = json.loads(path.read_text(encoding="utf-8-sig"))
    model = TrainingSnapshot.model_validate(body)
    assert model.model_dump(mode="json") == body
    assert model.content_sha256 == "d2deb51291cbb8ad5ac100e7a95d60afb6670e8c3762f05304daee77410a67dd"
    assert training_content_sha256(model) == body["content_sha256"]


def test_standalone_region_schema_is_current_without_old_schema_changes():
    path = FIXTURES.parent / "schemas/TrainingImageRegion.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == TrainingImageRegion.model_json_schema()
