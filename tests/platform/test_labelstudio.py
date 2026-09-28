import copy

import pytest

from apps.platform.labelstudio import FrameMap, LabelStudioClient, LabelStudioError, build_task, import_annotation, label_config


@pytest.fixture
def mapping():
    # Deliberately VFR and one-based; FPS arithmetic would produce wrong results.
    return FrameMap.from_dict({"mapping_id": "pts-fixture", "source_duration_ms": 200,
        "frames": [{"ls_frame": 1, "source_start_ms": 0, "source_end_ms": 33, "source_pts": 0},
                   {"ls_frame": 2, "source_start_ms": 33, "source_end_ms": 100, "source_pts": 2970},
                   {"ls_frame": 3, "source_start_ms": 100, "source_end_ms": 200, "source_pts": 9000}]})


@pytest.fixture
def event():
    return {"event_id": "manual-1", "asset_id": "a", "match_id": "m", "kind": "stroke", "revision": 4,
            "start_ms": 40, "end_ms": 90, "contact_ms": 60, "player_id": "p", "rally_id": "r",
            "labels": {"stroke": "net_shot", "hand_technique": "unknown"}, "review_status": "confirmed"}


def sample_task(mapping, events=None):
    task = build_task({"asset_id": "a", "match_id": "m", "duration_ms": 200},
                      "http://127.0.0.1:18080/api/v1/assets/a/media", mapping, events)
    task["id"] = 11
    return task


def convert(task, annotation):
    return import_annotation(task, annotation, tool_version="1.23.1",
                             raw_export_relative_path="platform/labelstudio/export-1.json")


def test_vfr_single_frame_and_last_frame(mapping):
    assert mapping.interval(2, 2) == (33, 100)
    assert mapping.interval(1, 3) == (0, 200)
    with pytest.raises(LabelStudioError):
        mapping.interval(0, 2)
    with pytest.raises(LabelStudioError):
        mapping.interval(3, 2)


def test_unchanged_roundtrip_preserves_precise_manual_interval(mapping, event):
    task = sample_task(mapping, [event])
    annotation = {"id": 22, "result": task["annotations"][0]["result"]}
    imported = convert(task, annotation)
    restored = imported["events"][0]
    assert (restored["start_ms"], restored["end_ms"], restored["contact_ms"]) == (40, 90, 60)
    assert restored["event_id"] == "manual-1"
    assert restored["revision"] == 5
    assert restored["review_status"] == "unreviewed"
    assert restored["labels"]["hand_technique"] == "unknown"
    assert imported["expected_revisions"] == {"manual-1": 4}
    assert restored["provenance"]["annotation_id"] == 22


def test_edit_boundaries_uses_pts_and_drops_outside_contact(mapping, event):
    task = sample_task(mapping, [event])
    regions = copy.deepcopy(task["annotations"][0]["result"])
    regions[0]["value"]["ranges"] = [{"start": 3, "end": 3}]
    restored = convert(task, {"id": 22, "result": regions})["events"][0]
    assert (restored["start_ms"], restored["end_ms"], restored["contact_ms"]) == (100, 200, None)


def test_video_rectangle_is_evidence_not_action(mapping):
    task = sample_task(mapping)
    annotation = {"id": 22, "result": [{"id": "box1", "type": "videorectangle", "to_name": "video",
        "value": {"labels": ["player_unconfirmed"], "sequence": [
            {"frame": 2, "time": 99, "x": 10, "y": 20, "width": 10, "height": 20, "enabled": True}]}}]}
    result = convert(task, annotation)
    assert not result["events"]
    assert result["tracks"][0]["keyframes"][0]["source_start_ms"] == 33
    assert result["tracks"][0]["player_id"] is None


def test_new_event_ids_stable_and_unknown_stays_unknown(mapping):
    task = sample_task(mapping)
    annotation = {"id": 22, "result": [{"id": "event1", "type": "timelinelabels", "to_name": "video",
        "value": {"timelinelabels": ["stroke.net_shot"], "ranges": [{"start": 1, "end": 2}]}}]}
    first, second = convert(task, annotation), convert(task, annotation)
    assert first == second
    assert first["events"][0]["labels"]["hand_technique"] == "unknown"
    assert first["events"][0]["player_id"] is None


def test_reject_malformed_map_and_unmapped_frame(mapping):
    bad = mapping.as_dict()
    bad["frames"][1]["source_end_ms"] = 300
    with pytest.raises(LabelStudioError):
        FrameMap.from_dict(bad)
    with pytest.raises(LabelStudioError):
        mapping.frame(1.5)
    gap = mapping.as_dict()
    gap["frames"].pop(1)
    with pytest.raises(LabelStudioError):
        FrameMap.from_dict(gap).interval(1, 3)


def test_no_raw_path_traversal(mapping):
    with pytest.raises(LabelStudioError):
        import_annotation(sample_task(mapping), {"id": 22, "result": []}, tool_version="1.23.1",
                          raw_export_relative_path="../secret.json")


def test_duplicate_proxy_frames_and_unmapped_source_gap(mapping):
    body = mapping.as_dict()
    body["frames"].insert(1, {"ls_frame": 2, "source_start_ms": 0, "source_end_ms": 33})
    body["frames"][2]["ls_frame"] = 3
    body["frames"][3]["ls_frame"] = 4
    proxy = FrameMap.from_dict(body)
    assert proxy.interval(1, 3) == (0, 100)
    assert proxy.range_for(1, 30) == {"start": 1, "end": 2}
    body["frames"][2]["source_start_ms"] = 34
    with pytest.raises(LabelStudioError, match="unmapped source"):
        FrameMap.from_dict(body).interval(1, 3)


def test_removed_seed_does_not_silently_delete_platform_event(mapping, event):
    result = convert(sample_task(mapping, [event]), {"id": 22, "result": []})
    assert result["events"] == []
    assert "not deleted" in result["warnings"][0]


def test_client_local_only_and_secret_masked(monkeypatch):
    with pytest.raises(LabelStudioError):
        LabelStudioClient("https://example.com")
    with pytest.raises(LabelStudioError):
        LabelStudioClient("http://secret@localhost:18081")
    monkeypatch.delenv("BTV_LABEL_STUDIO_TOKEN", raising=False)
    with pytest.raises(LabelStudioError, match="not set"):
        LabelStudioClient().create_project("test")
    assert "VideoRectangle" in label_config()
    assert "TimelineLabels" in label_config()
