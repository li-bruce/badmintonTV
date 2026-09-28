"""Regression coverage from independent platform review; synthetic records only."""

from copy import deepcopy

import pytest

from apps.platform.retrieval import merge_segments
from apps.platform.store import Conflict, Store
from packages.contracts import Asset, Event


@pytest.fixture
def review_store(tmp_path):
    store = Store(tmp_path / "review.sqlite3")
    asset = Asset(
        asset_id="review-asset", relative_path="data/review-fixture.mp4", sha256="c" * 64,
        size_bytes=10, duration_ms=10000, width=100, height=100, match_id="review-match",
        source_type="synthetic", rights={"status": "research_only", "evidence": "fixture"},
        provenance={"source": "independent-regression-fixture"}, split="test",
        probe={"pts_index": {"complete": True}},
    ).model_dump(mode="json")
    store.import_assets([asset], "review-library")
    return store, asset


def review_event(identifier, **changes):
    return Event.model_validate({
        "event_id": identifier, "asset_id": "review-asset", "match_id": "review-match",
        "kind": "stroke", "start_ms": 100, "end_ms": 500,
        "labels": {"stroke": "net_shot", "hand_technique": "unknown"},
        "review_status": "confirmed", "provenance": {"source": "model"}, **changes,
    }).model_dump(mode="json")


def test_batch_import_rolls_back_events_and_history_on_late_conflict(review_store):
    store, _ = review_store
    confirmed = store.save_event(review_event("confirmed-model-origin"), 0, "human-reviewer")
    with pytest.raises(Conflict, match="已确认"):
        store.save_events([
            (review_event("new-prediction", review_status="unreviewed"), 0, "model-import", "agent"),
            (confirmed, 1, "model-import", "agent"),
        ], actor="automatic")
    assert store.event("new-prediction") is None
    assert store.revisions("new-prediction") == []
    assert len(store.revisions("confirmed-model-origin")) == 1


def test_human_can_revise_confirmed_model_origin_without_rewriting_provenance(review_store):
    store, _ = review_store
    original = store.save_event(review_event("reviewed-prediction"), 0, "human-reviewer", "human")
    changed = {**original, "labels": {"stroke": "smash"}}
    saved = store.save_event(changed, 1, "human-reviewer", "human", actor="human")
    assert saved["revision"] == 2 and saved["previous_revision"] == 1
    assert saved["provenance"]["source"] == "model"
    assert saved["reviewer_type"] == saved["provenance"]["reviewer_type"] == "human"


def test_agent_review_is_recorded_without_claiming_human_review(review_store):
    store, _ = review_store
    saved = store.save_event(review_event("agent-review"), 0, "Codex", "agent")
    assert saved["reviewer_type"] == "agent"
    assert store.revisions("agent-review")[0]["provenance"]["reviewer_type"] == "agent"


@pytest.mark.parametrize("expected", [True, False, "0", -1])
def test_revision_compare_and_swap_rejects_non_integer_revisions(review_store, expected):
    store, _ = review_store
    with pytest.raises(ValueError, match="非负整数"):
        store.save_event(review_event("bad-revision"), expected, "reviewer")
    assert store.events() == []


def test_probe_refresh_preserves_existing_rights_provenance_and_split(review_store):
    store, original = review_store
    updated = store.update_asset_probe("review-asset", {"thumbnail_relative_path": "platform/jobs/test/thumbnail.jpg"})
    assert updated["probe"]["pts_index"] == {"complete": True}
    assert updated["probe"]["thumbnail_relative_path"].endswith("thumbnail.jpg")
    for field in ("rights", "provenance", "split", "sha256", "relative_path", "match_id"):
        assert updated[field] == original[field]
    assert store.asset("review-asset") == updated


def test_transitive_candidate_merge_removes_all_overlaps_and_preserves_evidence():
    segments = [
        {"segment_id": "a", "asset_id": "source", "in_ms": 0, "out_ms": 1000, "event_ids": ["e1"]},
        {"segment_id": "b", "asset_id": "source", "in_ms": 2000, "out_ms": 3000, "event_ids": ["e2"]},
        {"segment_id": "c", "asset_id": "source", "in_ms": 500, "out_ms": 2500, "event_ids": ["e3", "e1"]},
    ]
    original = deepcopy(segments)
    merged = merge_segments(segments)
    assert len(merged) == 1
    assert (merged[0]["in_ms"], merged[0]["out_ms"]) == (0, 3000)
    assert merged[0]["event_ids"] == ["e1", "e2", "e3"]
    assert segments == original


def test_segment_merge_keeps_separate_assets_and_selection_order():
    segments = [
        {"segment_id": "a", "asset_id": "source-a", "in_ms": 0, "out_ms": 1000, "event_ids": ["e1"]},
        {"segment_id": "b", "asset_id": "source-b", "in_ms": 0, "out_ms": 1000, "event_ids": ["e2"]},
        {"segment_id": "c", "asset_id": "source-a", "in_ms": 900, "out_ms": 2000, "event_ids": ["e3"]},
    ]
    merged = merge_segments(segments)
    assert [item["asset_id"] for item in merged] == ["source-a", "source-b"]
    assert merged[0]["event_ids"] == ["e1", "e3"]
    assert merge_segments([]) == []
