"""Contract fixtures are synthetic JSON records, never recognition evidence."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts import (
    Artifact, Asset, AssetManifest, Candidate, Event, EventCollection, EventManifest,
    JobRequest, JobResult, ModelManifest, ProgressEvent, QuerySpec, RevisionConflict,
    Timeline, resolve_relative_path, schemas, validate_candidate_assets,
    validate_event_assets, validate_event_revision, validate_output_dir,
    validate_timeline_assets, validate_job_result,
)


def asset_payload(**updates):
    return {
        "asset_id": "asset-test", "relative_path": "data/raw/fixture.mp4",
        "sha256": "a" * 64, "size_bytes": 100, "duration_ms": 10000,
        "width": 1920, "height": 1080, "fps_num": 30000, "fps_den": 1001,
        "time_base": "1/90000", "match_id": "match-test", "source_type": "synthetic",
        **updates,
    }


def event_payload(**updates):
    return {
        "event_id": "event-test", "asset_id": "asset-test", "match_id": "match-test",
        "kind": "stroke", "start_ms": 1000, "end_ms": 2000, "contact_ms": 1500,
        "labels": {"stroke": "net_shot", "hand_technique": "unknown", "footwork": None},
        "provenance": {"source": "manual"}, **updates,
    }


def timeline_payload(**segment_updates):
    return {
        "timeline_id": "timeline-test", "title": "结构测试，非真实素材",
        "segments": [{
            "segment_id": "clip-test", "asset_id": "asset-test", "in_ms": 0,
            "out_ms": 2000, "review_status": "confirmed", **segment_updates,
        }],
    }


def test_roundtrip_preserves_unknown_and_extensions():
    asset = Asset.model_validate(asset_payload(probe={"vfr": True, "pts_asset_id": None}))
    assert Asset.model_validate_json(asset.model_dump_json()) == asset
    event = Event.model_validate(event_payload(provenance={"source": "import", "annotation_id": 42}))
    assert event.labels == {"stroke": "net_shot", "hand_technique": "unknown", "footwork": None}
    assert event.player_id is None and event.rally_id is None and event.confidence is None
    assert Event.model_validate_json(event.model_dump_json()) == event
    assert event.model_dump(mode="json")["provenance"]["annotation_id"] == 42
    assert EventCollection is EventManifest


@pytest.mark.parametrize("path", [
    "/data/a.mp4", "../a.mp4", "data/../a.mp4", "data/./a.mp4", "data//a.mp4",
    "data/a.mp4/", "D:/video/a.mp4", "D:a.mp4", r"data\a.mp4", r"\\server\file",
    "data/a.mp4:stream", "data/a.mp4\x00", "data/a.", "data/a ", "data/CON.mp4",
    "data/lpt1", "data/a?.mp4", "", ".", "..",
])
def test_reject_unsafe_paths(path):
    with pytest.raises(ValidationError):
        Asset.model_validate(asset_payload(relative_path=path))


def test_path_resolution_stays_inside_native_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    media = root / "data"
    media.mkdir()
    source = media / "clip.mp4"
    source.write_bytes(b"structure-only fixture")
    assert resolve_relative_path(root, "data/clip.mp4", must_exist=True) == source
    with pytest.raises(FileNotFoundError):
        resolve_relative_path(root, "data/missing.mp4", must_exist=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Junctions exercise Windows reparse-point escape checks without the
        # elevated privilege required by symbolic links on this workstation.
        import _winapi
        _winapi.CreateJunction(str(outside), str(link))
    with pytest.raises(ValueError, match="escapes"):
        resolve_relative_path(root, "link/new.mp4")


@pytest.mark.parametrize("updates", [
    {"start_ms": -1}, {"start_ms": 1.1}, {"start_ms": "1000"}, {"start_ms": True},
    {"end_ms": 1000}, {"end_ms": 999}, {"contact_ms": 2000}, {"contact_ms": 999},
    {"revision": 0}, {"previous_revision": 1}, {"revision": 3, "previous_revision": 1},
    {"labels": {"hand_technique": False}}, {"confidence": float("nan")},
    {"confidence": 1.1}, {"confidence": -0.1}, {"schema_version": "2.0"},
    {"duration_ms": 1000},
])
def test_event_invalid_intervals_revision_and_types(updates):
    with pytest.raises(ValidationError):
        Event.model_validate(event_payload(**updates))


def test_duplicate_ids_and_match_level_split():
    first = asset_payload(split="train")
    second = asset_payload(asset_id="asset-two", relative_path="data/raw/two.mp4", split="test")
    with pytest.raises(ValidationError, match="same assigned split"):
        AssetManifest(assets=[first, second])
    with pytest.raises(ValidationError, match="duplicate asset_id"):
        AssetManifest(assets=[first, first])
    with pytest.raises(ValidationError, match="duplicate event_id"):
        EventManifest(events=[event_payload(), event_payload()])


@pytest.mark.parametrize("updates", [
    {"fps_den": 0}, {"fps_num": None}, {"time_base": "1/0"}, {"time_base": "0/1"},
    {"time_base": "30"}, {"sha256": "x" * 64}, {"size_bytes": True},
])
def test_invalid_asset_metadata(updates):
    with pytest.raises(ValidationError):
        Asset.model_validate(asset_payload(**updates))


def test_cross_object_source_boundaries():
    asset = Asset.model_validate(asset_payload())
    event = Event.model_validate(event_payload())
    validate_event_assets([event], [asset])
    for change in ({"end_ms": 10001}, {"match_id": "other-match"}, {"asset_id": "missing"}):
        with pytest.raises(ValueError):
            validate_event_assets([Event.model_validate(event_payload(**change))], [asset])
    invalid_evidence = Event.model_validate(event_payload(evidence=[{
        "type": "source_interval", "asset_id": asset.asset_id, "start_ms": 5000, "end_ms": 10001,
    }]))
    with pytest.raises(ValueError, match="evidence exceeds"):
        validate_event_assets([invalid_evidence], [asset])


def test_human_revisions_and_model_predictions_stay_separate():
    current = Event.model_validate(event_payload(review_status="confirmed"))
    replacement = Event.model_validate(event_payload(
        revision=2, previous_revision=1, reviewer="reviewer-test", reviewed_at=datetime.now(timezone.utc),
    ))
    validate_event_revision(current, replacement, 1, actor="human")
    with pytest.raises(RevisionConflict):
        validate_event_revision(current, replacement, 0)
    with pytest.raises(RevisionConflict):
        validate_event_revision(current, replacement, True)
    prediction = Event.model_validate({**replacement.model_dump(), "provenance": {"source": "model"}})
    with pytest.raises(RevisionConflict, match="cannot overwrite"):
        validate_event_revision(current, prediction, 1)
    unaudited = Event.model_validate(event_payload(revision=2, previous_revision=1))
    with pytest.raises(ValueError, match="reviewer"):
        validate_event_revision(current, unaudited, 1, actor="human")


def test_review_origin_remains_explicit_and_optional():
    old_event = Event.model_validate(event_payload())
    assert old_event.reviewer_type is None
    assert old_event.provenance.reviewer_type is None
    agent_event = Event.model_validate(event_payload(reviewer="agent-review", reviewer_type="agent"))
    assert agent_event.reviewer_type == "agent"
    candidate = Candidate(candidate_id="review-test", asset_id="asset-test", start_ms=0, end_ms=1)
    assert candidate.reviewer_type is None
    assert Candidate.model_validate({**candidate.model_dump(), "reviewer_type": "human", "reviewer": "tester"}).reviewer_type == "human"
    with pytest.raises(ValidationError):
        Event.model_validate(event_payload(reviewer_type="model"))


@pytest.mark.parametrize("source", ["model", "rule", "manual", "import"])
def test_confirmed_revision_protection_depends_on_trusted_actor_not_event_source(source):
    current = Event.model_validate(event_payload(review_status="confirmed", provenance={"source": source}))
    revised = Event.model_validate(event_payload(
        revision=2, previous_revision=1, reviewer="tester", reviewed_at="2026-09-28T12:00:00Z",
        reviewer_type="human", provenance={"source": source},
    ))
    with pytest.raises(RevisionConflict, match="cannot overwrite"):
        validate_event_revision(current, revised, 1, actor="automatic")
    with pytest.raises(RevisionConflict, match="cannot overwrite"):
        validate_event_revision(current, revised, 1)  # Fail closed when omitted.
    validate_event_revision(current, revised, 1, actor="human")


def test_query_relations_reference_steps_and_are_not_event_adjacency():
    query = QuerySpec.model_validate({
        "query_id": "query-test", "text": "同一球员先网前后杀球",
        "steps": [{"step_id": "net", "kind": "stroke", "labels": {"stroke": "net_shot"}},
                  {"step_id": "smash", "kind": "stroke", "labels": {"stroke": "smash"}}],
        "relations": [{"from_step": "net", "to_step": "smash", "relation": "before"}],
    })
    assert query.relations[0].same_player is True and query.relations[0].same_rally is True
    assert "adjacent" not in query.model_dump_json()
    invalid = query.model_dump(mode="json")
    invalid["relations"][0]["to_step"] = "absent"
    with pytest.raises(ValidationError, match="unknown step_id"):
        QuerySpec.model_validate(invalid)
    invalid = query.model_dump(mode="json")
    invalid["relations"].append({"from_step": "smash", "to_step": "net", "relation": "before"})
    with pytest.raises(ValidationError, match="cycle"):
        QuerySpec.model_validate(invalid)


def test_candidate_ranking_is_not_probability():
    candidate = Candidate(candidate_id="candidate-test", asset_id="asset-test", start_ms=0,
                          end_ms=1000, rank_score=42.0, uncertainty_reasons=["手腕不可见"])
    validate_candidate_assets([candidate], [Asset.model_validate(asset_payload())])
    assert candidate.rank_score == 42.0
    with pytest.raises(ValidationError):
        Candidate.model_validate({**candidate.model_dump(), "rank_score": float("inf")})


def test_model_unavailability_and_job_result_truthfulness():
    card = {"model_id": "uninstalled-test", "version": "0.1", "display_name": "未安装测试",
            "status": "not_installed"}
    with pytest.raises(ValidationError, match="reason"):
        ModelManifest.model_validate(card)
    assert ModelManifest.model_validate({**card, "reason": "weights absent"}).status == "not_installed"
    with pytest.raises(ValidationError, match="error"):
        JobResult(job_id="job-test", attempt_id="attempt-01", status="blocked")
    result = JobResult(job_id="job-test", attempt_id="attempt-01", status="failed", error={"code": "WORKER_INTERRUPTED", "message": "lease expired"})
    assert result.error.code == "WORKER_INTERRUPTED"
    with pytest.raises(ValidationError):
        JobResult(job_id="job-test", attempt_id="attempt-01", status="succeeded", error={"code": "ERR", "message": "bad"})


def test_cli_request_owner_relative_path(tmp_path):
    request = JobRequest(job_id="job-test", attempt_id="attempt-01", operation="render", assets=[asset_payload()], output_dir="render/jobs/test")
    assert isinstance(request.assets, list)
    for value in ("D:/video/render/jobs/test", "/mnt/d/video/render/jobs/test", "render", "other/jobs/test", "render/../platform"):
        with pytest.raises(ValidationError):
            JobRequest(job_id="job-test", attempt_id="attempt-01", operation="render", output_dir=value)
    with pytest.raises(ValidationError):
        JobRequest(job_id="job-test", attempt_id="attempt-01", operation="render", assets={"asset-test": asset_payload()}, output_dir="render/jobs/test")
    root = tmp_path / "render"
    root.mkdir()
    assert validate_output_dir(request.output_dir, root) == root / "jobs" / "test"
    with pytest.raises(ValueError, match="expected owner"):
        validate_output_dir("models/jobs/test", root)


def test_attempt_and_exit_code_must_match_request():
    request = JobRequest(job_id="job-test", attempt_id="attempt-02", operation="render", output_dir="render/jobs/test")
    result = JobResult(job_id="job-test", attempt_id="attempt-02", status="succeeded")
    validate_job_result(request, result, 0)
    with pytest.raises(ValueError, match="exit code"):
        validate_job_result(request, result, 1)
    for changes in ({"attempt_id": "attempt-01"}, {"job_id": "old-job"}):
        with pytest.raises(ValueError, match="current"):
            validate_job_result(request, JobResult.model_validate({**result.model_dump(), **changes}), 0)
    with pytest.raises(ValidationError):
        JobRequest(job_id="job-test", operation="render", output_dir="render/jobs/test")
    with pytest.raises(ValidationError):
        JobResult(job_id="job-test", status="succeeded")
    with pytest.raises(ValidationError, match="top-level"):
        JobRequest(job_id="job-test", attempt_id="attempt-01", operation="render", output_dir="render/jobs/test", parameters={"assets": []})


@pytest.mark.parametrize("current,total", [(2, 1), (-1, 2), (float("inf"), None), (True, 5)])
def test_no_impossible_progress(current, total):
    with pytest.raises(ValidationError):
        ProgressEvent(job_id="job-test", seq=1, event="progress", current=current, total=total)


def test_unknown_progress_total_is_allowed():
    progress = ProgressEvent(job_id="job-test", seq=0, event="progress", stage="probe")
    assert progress.current is None and progress.total is None


def test_timeline_source_intervals_confirmation_and_crop():
    asset = Asset.model_validate(asset_payload())
    timeline = Timeline.model_validate(timeline_payload(speed=0.5))
    validate_timeline_assets(timeline, [asset], require_confirmed=True)
    for update in ({"out_ms": 0}, {"speed": 0}, {"speed": float("nan")}, {"fit": "crop"},
                   {"fit": "crop", "crop": {"x": 0.8, "y": 0.0, "width": 0.3, "height": 1.0}}):
        with pytest.raises(ValidationError):
            Timeline.model_validate(timeline_payload(**update))
    cropped = Timeline.model_validate(timeline_payload(fit="crop", crop={"x": 0.2, "y": 0.0, "width": 0.6, "height": 1.0}))
    assert cropped.segments[0].crop.width == 0.6
    with pytest.raises(ValueError, match="confirmed"):
        validate_timeline_assets(Timeline.model_validate(timeline_payload(review_status="unreviewed")), [asset], require_confirmed=True)
    with pytest.raises(ValueError, match="duration"):
        validate_timeline_assets(Timeline.model_validate(timeline_payload(out_ms=10001)), [asset])


def test_artifacts_have_required_integrity_metadata():
    artifact = Artifact(artifact_id="artifact-test", kind="mp4", relative_path="render/outputs/test.mp4",
                        sha256="1" * 64, size_bytes=5, created_at="2026-09-28T00:00:00Z", producer="contract-test")
    assert artifact.model_dump(mode="json")["created_at"] == "2026-09-28T00:00:00Z"
    with pytest.raises(ValidationError):
        Artifact.model_validate({**artifact.model_dump(), "sha256": "missing"})


def test_schema_export_covers_all_public_transport_types(tmp_path, monkeypatch, capsys):
    from packages.contracts.__main__ import main

    exported = schemas()
    assert len(exported) == 12
    for name, schema in exported.items():
        assert schema["properties"]["schema_version"]["const"] == "1.0", name
        assert schema["additionalProperties"] is False
        json.dumps(schema, ensure_ascii=False, allow_nan=False)
    monkeypatch.setattr("sys.argv", ["packages.contracts", "--output", str(tmp_path)])
    main()
    assert "Exported 12" in capsys.readouterr().out
    assert len(list(tmp_path.glob("*.schema.json"))) == 12
    assert json.loads((tmp_path / "Asset.schema.json").read_text(encoding="utf-8"))["title"] == "Asset"


def test_canonical_fixtures_validate_across_envelopes_and_assets():
    fixture_dir = Path(__file__).parents[2] / "packages" / "contracts" / "fixtures"

    def read(name, model):
        return model.model_validate_json((fixture_dir / name).read_text(encoding="utf-8"))

    manifest = read("asset-manifest.json", AssetManifest)
    events = read("events.json", EventManifest)
    read("query.json", QuerySpec)
    candidate = read("candidate.json", Candidate)
    read("model-manifest.json", ModelManifest)
    read("model-request.json", JobRequest)
    timeline = read("timeline.json", Timeline)
    request = read("render-request.json", JobRequest)
    assert request.assets == manifest.assets
    assert request.parameters["timeline"] == timeline.model_dump(mode="json")
    assert timeline.segments
    validate_event_assets(events.events, manifest.assets)
    validate_candidate_assets([candidate], manifest.assets)
    validate_timeline_assets(timeline, manifest.assets, require_confirmed=True)
    for status, code in (("succeeded", 0), ("failed", 1), ("blocked", 2), ("cancelled", 130)):
        result = read(f"result-{status}.json", JobResult)
        validate_job_result(request, result, code)
    progress = [ProgressEvent.model_validate_json(line) for line in (fixture_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(item.job_id == request.job_id for item in progress)
    assert [item.seq for item in progress] == sorted(set(item.seq for item in progress))


def test_checked_in_schemas_match_current_python_types():
    schema_dir = Path(__file__).parents[2] / "packages" / "contracts" / "schemas"
    for name, schema in schemas().items():
        assert json.loads((schema_dir / f"{name}.schema.json").read_text(encoding="utf-8")) == schema
