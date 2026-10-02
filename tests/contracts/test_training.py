"""A-01/A-04/A-05 contract assertions use synthetic metadata, not expert truth."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.training import (
    TrainingAnnotationBundle, TrainingAssetRef, TrainingProject, TrainingSnapshot,
    TrainingTaxonomy, build_training_snapshot, next_bundle_revision,
    get_default_training_taxonomy, validate_training_bundle, training_content_sha256,
)


FIXTURES = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures"


@pytest.fixture
def bundle_data():
    return json.loads((FIXTURES / "training.annotations.v1.json").read_text(encoding="utf-8"))


def test_canonical_bundle_and_old_contracts_remain_independent(bundle_data):
    from packages.contracts import EventManifest
    bundle = TrainingAnnotationBundle.model_validate(bundle_data)
    assert len([r for r in bundle.records if r.kind == "contact"]) == 2
    assert {r.kind for r in bundle.records} == {"rally", "contact", "dead_ball", "segment", "state"}
    with pytest.raises(ValidationError):
        EventManifest.model_validate(bundle.model_dump(mode="json"))


@pytest.mark.parametrize("change", [
    lambda d: d["records"][1].update(at_ms=-1),
    lambda d: d["records"][1].update(at_ms=10000),
    lambda d: d["records"][1].update(start_ms=100, end_ms=200),
    lambda d: d["records"][0].update(start_ms=1000, end_ms=1000),
    lambda d: d["records"][0].update(end_ms=10001),
    lambda d: d["records"][1].update(at_ms=True),
    lambda d: d["records"][1].update(person_id="missing-person"),
    lambda d: d["records"][1].update(rally_id="missing-rally"),
    lambda d: d["records"][1].update(at_ms=9000),
    lambda d: d["records"][0].update(dead_ball_id="contact-1"),
    lambda d: d["records"][3].update(at_ms=4900),
    lambda d: d["records"][1].update(team_id="team-b"),
    lambda d: d["records"][1].update(asset_id="other-asset"),
    lambda d: d["records"][1].update(record_id="rally-1"),
])
def test_time_and_relationship_errors_are_rejected(bundle_data, change):
    change(bundle_data)
    with pytest.raises(ValidationError):
        TrainingAnnotationBundle.model_validate(bundle_data)


def test_dead_ball_is_independent_and_may_reach_media_end(bundle_data):
    bundle_data["records"][0]["end_ms"] = 10000
    bundle_data["records"][3]["at_ms"] = 10000
    TrainingAnnotationBundle.model_validate(bundle_data)


@pytest.mark.parametrize("position", [
    {"coordinate_system": "image_normalized", "x": 1.1, "y": .2},
    {"coordinate_system": "image_normalized", "x": .1, "y": float("nan")},
    {"coordinate_system": "court_m", "x": 1., "y": 2.},
])
def test_positions_require_valid_coordinates_and_calibration(bundle_data, position):
    bundle_data["records"][-1]["state"]["self"]["position"] = position
    with pytest.raises(ValidationError):
        TrainingAnnotationBundle.model_validate(bundle_data)


def test_agent_cannot_write_human_review_and_revision_is_server_derived(bundle_data):
    current = TrainingAnnotationBundle.model_validate(bundle_data)
    incoming = current.model_dump(mode="json")
    incoming["records"][1]["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "claimed-human"}
    with pytest.raises(ValueError, match="actor"):
        next_bundle_revision(current, incoming, current.revision, actor_type="agent", reviewer="test-agent")
    incoming = current.model_dump(mode="json")
    incoming["records"][1]["at_ms"] += 1
    updated = next_bundle_revision(current, incoming, current.revision, actor_type="agent", reviewer="test-agent")
    assert updated.revision == current.revision + 1
    assert updated.records[1].revision == 2 and updated.records[1].previous_revision == 1
    assert updated.records[0].revision == current.records[0].revision
    with pytest.raises(ValueError, match="revision"):
        next_bundle_revision(current, incoming, 0, actor_type="agent", reviewer="test-agent")


def test_deletion_keeps_revision_tombstone(bundle_data):
    current = TrainingAnnotationBundle.model_validate(bundle_data)
    incoming = current.model_dump(mode="json")
    incoming["records"] = incoming["records"][:-1]
    updated = next_bundle_revision(current, incoming, current.revision, actor_type="agent", reviewer="test-agent")
    assert updated.records[-1].record_id == current.records[-1].record_id
    assert updated.records[-1].deleted and updated.records[-1].revision == 2


def snapshot(bundle_data, *, reviewed=False):
    taxonomy = json.loads((FIXTURES / "training.taxonomy.provisional.v1.json").read_text(encoding="utf-8"))
    if reviewed:
        taxonomy["status"] = "reviewed"
        for label in taxonomy["labels"]:
            label["status"] = "defined"
    taxonomy = TrainingTaxonomy.model_validate(taxonomy)
    project = TrainingProject(project_id="project-synthetic", name="Synthetic contract fixture", catalog_version="fixture-1",
                              taxonomy_id=taxonomy.taxonomy_id, taxonomy_version=taxonomy.version,
                              asset_ids=[bundle_data["asset"]["asset_id"]])
    return build_training_snapshot(snapshot_id="snapshot-synthetic", project=project, taxonomy=taxonomy,
                                   assets=[bundle_data["asset"]], bundles=[bundle_data], splits=[])


def test_snapshot_is_deeply_frozen_and_hash_detects_mutation(bundle_data):
    frozen = snapshot(bundle_data)
    original = frozen.model_dump(mode="json")
    bundle_data["asset"]["provenance"]["fixture"] = "changed outside"
    assert frozen.model_dump(mode="json") == original
    with pytest.raises((TypeError, ValidationError)):
        frozen.project.name = "mutated"
    with pytest.raises(TypeError):
        frozen.assets[0].provenance["fixture"] = "mutated"
    changed = copy.deepcopy(original)
    changed["bundles"][0]["records"][1]["at_ms"] += 1
    with pytest.raises(ValidationError, match="hash"):
        TrainingSnapshot.model_validate(changed)
    assert TrainingSnapshot.model_validate_json(frozen.model_dump_json()) == frozen


def test_provisional_and_agent_records_do_not_become_human_training_truth(bundle_data):
    frozen = snapshot(bundle_data)
    assert frozen.training_view == ()
    assert frozen.exclusions
    reviewed = snapshot(bundle_data, reviewed=True)
    assert reviewed.training_view == ()  # Canonical annotations are Agent fixtures.


def test_human_defined_labels_only_and_unknown_is_not_negative(bundle_data):
    for record in bundle_data["records"]:
        record["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "SYNTHETIC role fixture"}
        record["visibility"] = "clear"
        record["evidence"] = [{"source": "synthetic-contract-evidence"}]
    frozen = snapshot(bundle_data, reviewed=True)
    assert frozen.training_view
    assert all(item.value in {"present", "absent"} for item in frozen.training_view)
    assert any("unknown" in entry.reasons for entry in frozen.exclusions)


def test_illegal_label_is_rejected_against_snapshot_taxonomy(bundle_data):
    bundle_data["records"][1]["judgements"][0]["label_id"] = "invented.label"
    with pytest.raises(ValueError, match="label"):
        snapshot(bundle_data)


def test_unconfirmed_group_cannot_receive_training_split(bundle_data):
    frozen = snapshot(bundle_data)
    body = frozen.model_dump(mode="json")
    body["splits"] = [{"group_id": bundle_data["asset"]["group_id"], "split": "train"}]
    body.pop("content_sha256")
    with pytest.raises(ValueError, match="group"):
        build_training_snapshot(**{key: body[key] for key in ("snapshot_id", "project", "taxonomy", "assets", "bundles", "splits", "created_at")})


@pytest.mark.parametrize("path", ["../bad.mp4", "/absolute.mp4", "data\\bad.mp4"])
def test_training_asset_paths_remain_root_relative(bundle_data, path):
    bundle_data["asset"]["relative_path"] = path
    with pytest.raises(ValidationError):
        TrainingAssetRef.model_validate(bundle_data["asset"])


@pytest.mark.parametrize("actor", ["human", "agent", "model", "import"])
def test_content_edit_always_clears_old_human_review(bundle_data, actor):
    bundle_data["records"][1]["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-reviewer"}
    current = TrainingAnnotationBundle.model_validate(bundle_data)
    incoming = current.model_dump(mode="json")
    incoming["records"][1]["at_ms"] += 1
    updated = next_bundle_revision(current, incoming, current.revision, actor_type=actor, reviewer="trusted-actor")
    review = updated.records[1].review
    assert review.status == "pending"
    assert review.reviewer is review.reviewer_type is review.reviewed_at is None
    assert updated.records[1].provenance["revision_audit"]["actor_type"] == actor


def test_review_only_confirmation_is_stamped_with_trusted_actor(bundle_data):
    current = TrainingAnnotationBundle.model_validate(bundle_data)
    incoming = current.model_dump(mode="json")
    incoming["records"][1]["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "client-name"}
    updated = next_bundle_revision(current, incoming, current.revision, actor_type="human", reviewer="trusted-reviewer")
    assert updated.records[1].review.status == "confirmed"
    assert updated.records[1].review.reviewer == "trusted-reviewer"
    assert updated.records[1].review.reviewed_at is not None


def test_person_change_clears_direct_and_state_role_review(bundle_data):
    for record in bundle_data["records"]:
        record["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-reviewer"}
    current = TrainingAnnotationBundle.model_validate(bundle_data)
    incoming = current.model_dump(mode="json")
    incoming["people"][1]["display_name"] = "Corrected identity"
    updated = next_bundle_revision(current, incoming, current.revision, actor_type="human", reviewer="trusted-reviewer")
    assert updated.records[2].review.status == "pending"  # Direct person-b.
    assert updated.records[5].review.status == "pending"  # Opponent person-b.
    assert updated.records[1].review.status == "confirmed"  # Unrelated person-a.


@pytest.mark.parametrize("actor", ["agent", "model", "import"])
def test_nonhuman_cannot_confirm_or_change_confirmed_people(bundle_data, actor):
    current = TrainingAnnotationBundle.model_validate(bundle_data)
    incoming = current.model_dump(mode="json")
    incoming["people"][0]["display_name"] = "Changed identity"
    with pytest.raises(ValueError, match="confirmed person"):
        next_bundle_revision(current, incoming, current.revision, actor_type=actor, reviewer="actor")
    with pytest.raises(ValueError, match="confirmed person"):
        next_bundle_revision(None, bundle_data, 0, actor_type=actor, reviewer="actor")


def test_first_save_stamps_revision_and_preserves_unknown_identity(bundle_data):
    for person in bundle_data["people"]:
        person["identity_status"] = "unknown"
    bundle_data["revision"] = 100
    bundle_data["records"][1].update(revision=100, previous_revision=99)
    saved = next_bundle_revision(None, bundle_data, 0, actor_type="agent", reviewer="test-agent")
    assert saved.revision == 1
    assert all(r.revision == 1 and r.previous_revision is None for r in saved.records)


@pytest.mark.parametrize("key,value", [("source_sha256", None), ("source_sha256", "b" * 64), ("path", "../index.json"), ("frame_count", True)])
def test_pts_reference_is_source_bound_and_structurally_valid(bundle_data, key, value):
    bundle_data["asset"]["pts_reference"][key] = value
    with pytest.raises(ValidationError):
        TrainingAssetRef.model_validate(bundle_data["asset"])


def test_taxonomy_group_cannot_be_selected_and_kind_is_checked(bundle_data):
    taxonomy = get_default_training_taxonomy().model_dump(mode="json")
    target = next(label for label in taxonomy["labels"] if label["label_id"] == "stroke.net_shot")
    target["selectable"] = False
    with pytest.raises(ValueError, match="selectable"):
        validate_training_bundle(bundle_data, taxonomy)
    target.update(selectable=True, kinds=["rally"])
    with pytest.raises(ValueError, match="kind"):
        validate_training_bundle(bundle_data, taxonomy)


def test_taxonomy_cycles_are_rejected():
    taxonomy = get_default_training_taxonomy().model_dump(mode="json")
    taxonomy["labels"][0]["parent_id"] = taxonomy["labels"][1]["label_id"]
    taxonomy["labels"][1]["parent_id"] = taxonomy["labels"][0]["label_id"]
    with pytest.raises(ValidationError, match="cyclic"):
        TrainingTaxonomy.model_validate(taxonomy)


@pytest.mark.parametrize("relation", ["hash", "match"])
def test_aliases_and_same_match_cannot_leak_across_splits(bundle_data, relation):
    frozen = snapshot(bundle_data)
    asset = frozen.assets[0].model_dump(mode="json")
    asset.update(group_status="confirmed", match_id="synthetic-match")
    other = copy.deepcopy(asset)
    other.update(asset_id="other-asset", group_id="other-group", relative_path="data/training/synthetic/other.mp4")
    if relation == "match":
        other["sha256"] = "c" * 64
        other["pts_reference"] = None
    else:
        other["match_id"] = "different-match"
    project = frozen.project.model_dump(mode="json")
    project["asset_ids"].append(other["asset_id"])
    with pytest.raises(ValueError, match="leak"):
        build_training_snapshot(snapshot_id="snapshot-split", project=project, taxonomy=frozen.taxonomy,
            assets=[asset, other], bundles=[], splits=[{"group_id": asset["group_id"], "split": "train"},
                                                     {"group_id": other["group_id"], "split": "test"}])


def test_snapshot_rejects_forged_view_even_with_recomputed_hash(bundle_data):
    bundle_data["asset"]["provenance"]["nested"] = {"tags": ["synthetic"]}
    frozen = snapshot(bundle_data)
    changed = frozen.model_dump(mode="json")
    changed["quality_summary"]["trainable"] = True
    changed["content_sha256"] = training_content_sha256(changed)
    with pytest.raises(ValidationError, match="derived"):
        TrainingSnapshot.model_validate(changed)
    with pytest.raises(TypeError):
        frozen.assets[0].provenance["nested"]["tags"].append("mutated")


def test_checked_in_training_schemas_are_current():
    from packages.contracts.training import training_schemas
    schema_dir = FIXTURES.parent / "schemas"
    for name, schema in training_schemas().items():
        assert json.loads((schema_dir / f"{name}.schema.json").read_text(encoding="utf-8")) == schema


def test_canonical_snapshot_hash_and_payload_are_valid():
    saved = TrainingSnapshot.model_validate_json((FIXTURES / "training.snapshot.v1.json").read_text(encoding="utf-8"))
    assert not saved.quality_summary.trainable
    assert saved.training_view == ()


@pytest.mark.parametrize("link", ["root_asset_ids", "source_sha256s", "recording_session_id", "source_group_ids"])
def test_different_hash_transcodes_cannot_cross_lineage_splits(bundle_data, link):
    original = snapshot(bundle_data)
    first = original.assets[0].model_dump(mode="json")
    first.update(group_status="confirmed", match_id="match-a")
    second = copy.deepcopy(first)
    second.update(asset_id="derived-b", sha256="c" * 64, pts_reference=None, group_id="group-b", match_id="match-b")
    if link == "root_asset_ids":
        second[link] = [first["asset_id"]]
    elif link == "source_sha256s":
        second[link] = [first["sha256"]]
    elif link == "source_group_ids":
        second[link] = [first["group_id"]]
    else:
        first[link] = second[link] = "recording-a"
    project = original.project.model_dump(mode="json")
    project["asset_ids"] = [first["asset_id"], second["asset_id"]]
    with pytest.raises(ValueError, match="leak"):
        build_training_snapshot(snapshot_id="lineage-split", project=project, taxonomy=original.taxonomy,
            assets=[first, second], bundles=[], splits=[{"group_id": first["group_id"], "split": "train"}, {"group_id": "group-b", "split": "test"}])


def _reviewed_observation(bundle_data, value="present"):
    record = bundle_data["records"][1]
    record["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-human"}
    record["visibility"] = "clear"
    record["evidence"] = [{"source_frame_index": 50}]
    record["judgements"] = [{"label_id": "stroke.net_shot", "value": value, "reason": "Visible complete synthetic observation"}]
    return record


@pytest.mark.parametrize("value", ["present", "absent"])
@pytest.mark.parametrize("invalid", ["unknown_visibility", "unobservable_visibility", "empty_evidence", "unidentified_evidence"])
def test_unobservable_or_unsupported_judgements_are_excluded(bundle_data, value, invalid):
    record = _reviewed_observation(bundle_data, value)
    if invalid.endswith("visibility"):
        record["visibility"] = invalid.split("_")[0]
    else:
        record["evidence"] = [] if invalid == "empty_evidence" else [{"arbitrary": True}]
    frozen = snapshot(bundle_data, reviewed=True)
    assert not any(item.record_id == record["record_id"] for item in frozen.training_view)
    assert any(any(reason.startswith("observation_") for reason in item.reasons) for item in frozen.exclusions if item.record_id == record["record_id"])


@pytest.mark.parametrize("reason", [None, "", "不明", "unknown"])
def test_absent_without_explicit_observation_reason_is_excluded(bundle_data, reason):
    record = _reviewed_observation(bundle_data, "absent")
    record["judgements"][0]["reason"] = reason
    frozen = snapshot(bundle_data, reviewed=True)
    assert any("negative_reason_missing" in item.reasons for item in frozen.exclusions if item.record_id == record["record_id"])


def test_supported_explicit_absent_is_not_conflated_with_unknown(bundle_data):
    record = _reviewed_observation(bundle_data, "absent")
    frozen = snapshot(bundle_data, reviewed=True)
    assert any(item.record_id == record["record_id"] and item.value == "absent" for item in frozen.training_view)


@pytest.mark.parametrize("missing", ["match_id", "group_evidence"])
def test_forged_independence_does_not_make_snapshot_trainable(bundle_data, missing):
    _reviewed_observation(bundle_data)
    asset = bundle_data["asset"]
    asset.update(group_status="confirmed", match_id="synthetic-match")
    asset["provenance"]["group_evidence"] = {"verified": True, "source": "synthetic catalog", "reference": "synthetic grouping review"}
    if missing == "match_id":
        asset[missing] = None
    else:
        asset["provenance"].pop(missing)
    frozen = snapshot(bundle_data, reviewed=True)
    rebuilt = build_training_snapshot(snapshot_id="group-check", project=frozen.project, taxonomy=frozen.taxonomy,
        assets=frozen.assets, bundles=frozen.bundles, splits=[{"group_id": asset["group_id"], "split": "train"}])
    assert rebuilt.training_view
    assert not rebuilt.quality_summary.trainable
    assert "independent_match_group_unconfirmed" in rebuilt.quality_summary.blockers


def test_multiple_subjects_preserve_distinct_label_judgements(bundle_data):
    record = bundle_data["records"][-1]
    record["judgements"] = [
        {"label_id": "state.balance", "subject_role": "self", "subject_person_id": "person-a", "value": "present"},
        {"label_id": "state.balance", "subject_role": "opponent", "subject_person_id": "person-b", "value": "absent", "reason": "Synthetic observed imbalance"},
    ]
    record["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-human"}
    record["visibility"] = "clear"
    record["evidence"] = [{"source_frame_index": 50}]
    validate_training_bundle(bundle_data, get_default_training_taxonomy())
    frozen = snapshot(bundle_data, reviewed=True)
    assert {(item.subject_role, item.subject_person_id, item.value)
            for item in frozen.training_view if item.record_id == record["record_id"]} == {
                ("self", "person-a", "present"), ("opponent", "person-b", "absent")}
    record["judgements"][1]["subject_person_id"] = "person-a"
    with pytest.raises(ValidationError, match="subject"):
        TrainingAnnotationBundle.model_validate(bundle_data)


@pytest.mark.parametrize("inheritance", ["record_person", "state_self", "state_opponent"])
def test_implicit_and_explicit_same_subject_cannot_duplicate_label(bundle_data, inheritance):
    record = bundle_data["records"][1 if inheritance == "record_person" else -1]
    role = "opponent" if inheritance == "state_opponent" else "self"
    person = "person-b" if role == "opponent" else "person-a"
    label = "stroke.net_shot" if inheritance == "record_person" else "state.balance"
    if inheritance == "state_self":
        record["person_id"] = record["team_id"] = None
    record["judgements"] = [
        {"label_id": label, "subject_role": role, "subject_person_id": None, "value": "present"},
        {"label_id": label, "subject_role": role, "subject_person_id": person,
         "value": "absent", "reason": "Conflicting synthetic judgement"},
    ]
    record["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-human"}
    record["visibility"] = "clear"
    record["evidence"] = [{"source_frame_index": 50}]
    with pytest.raises(ValidationError, match="duplicate resolved judgement"):
        TrainingAnnotationBundle.model_validate(bundle_data)
    with pytest.raises(ValidationError, match="duplicate resolved judgement"):
        snapshot(bundle_data, reviewed=True)


def test_opponent_partner_role_requires_opponent_team(bundle_data):
    bundle_data["people"].append({"person_id": "person-d", "display_name": "Synthetic D", "team_id": "team-b", "identity_status": "unknown"})
    record = bundle_data["records"][-1]
    record["state"]["opponent_partner"] = {"person_id": "person-d", "team_id": "team-b"}
    record["judgements"] = [{"label_id": "state.balance", "subject_role": "opponent_partner", "subject_person_id": "person-d", "value": "unknown", "reason": "Synthetic missing observation"}]
    validate_training_bundle(bundle_data, get_default_training_taxonomy())
    record["state"]["opponent_partner"]["team_id"] = "team-a"
    with pytest.raises(ValidationError):
        TrainingAnnotationBundle.model_validate(bundle_data)


def test_agent_cannot_create_human_position_but_can_preserve_old_one(bundle_data):
    current = TrainingAnnotationBundle.model_validate(bundle_data)
    incoming = current.model_dump(mode="json")
    incoming["records"][-1]["state"]["self"]["position"]["source"] = "human"
    with pytest.raises(ValueError, match="human position"):
        next_bundle_revision(current, incoming, current.revision, actor_type="agent", reviewer="agent")
    prior = TrainingAnnotationBundle.model_validate(incoming)
    saved = next_bundle_revision(prior, incoming, prior.revision, actor_type="agent", reviewer="agent")
    assert saved.records[-1].state.self.position.source == "human"
    incoming["records"][-1]["state"]["self"]["position"]["x"] = .5
    with pytest.raises(ValueError, match="human position"):
        next_bundle_revision(prior, incoming, prior.revision, actor_type="agent", reviewer="agent")
