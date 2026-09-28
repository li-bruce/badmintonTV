import copy
import hashlib
import json

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


@pytest.fixture
def ls_api(tmp_path, monkeypatch, mapping):
    from fastapi.testclient import TestClient

    root = tmp_path / 'video'
    (root / 'data').mkdir(parents=True)
    (root / 'data/test.mp4').write_bytes(b'not-real-video')
    monkeypatch.setenv('BTV_STORAGE_ROOT', str(root))
    from apps.platform.main import create_app

    app = create_app(root, root / 'platform/platform.sqlite3')
    client = TestClient(app)
    library = client.post('/api/v1/libraries', json={'name': 'LS regression'}).json()
    asset = {'asset_id': 'a', 'match_id': 'm', 'relative_path': 'data/test.mp4',
             'sha256': hashlib.sha256(b'not-real-video').hexdigest(), 'size_bytes': 14,
             'duration_ms': 200, 'width': 2, 'height': 2, 'title': 'LS contract fixture',
             'source_type': 'synthetic', 'rights': {'status': 'owned'}}
    response = client.post('/api/v1/assets/import', json={'library_id': library['library_id'],
                           'manifest': {'assets': [asset]}})
    assert response.status_code == 200, response.text
    return client, app, mapping


def ls_snapshot(client, mapping, *, seed=None):
    if seed:
        response = client.post('/api/v1/events', json={'event': seed, 'expected_revision': 0, 'reviewer': 'tester'})
        assert response.status_code == 200, response.text
    task = client.post('/api/v1/annotation/label-studio/task',
                       json={'asset_id': 'a', 'frame_map': mapping.as_dict()}).json()
    task['id'] = 11
    regions = task.get('annotations', [{'result': [{
        'id': 'new-region', 'from_name': 'events', 'to_name': 'video', 'type': 'timelinelabels',
        'value': {'ranges': [{'start': 1, 'end': 1}], 'timelinelabels': ['stroke.net_shot']},
    }]}])[0]['result']
    task['annotations'] = [{'id': 22, 'updated_at': '2026-09-28T00:00:01Z', 'result': regions}]
    return task


def edit_snapshot(task, second=2, end_frame=2):
    edited = copy.deepcopy(task)
    edited['annotations'][0]['updated_at'] = f'2026-09-28T00:00:{second:02d}Z'
    edited['annotations'][0]['result'][0]['value']['ranges'][0]['end'] = end_frame
    return edited


def post_ls(client, task):
    return client.post('/api/v1/annotation/label-studio/import', json={
        'export': [task], 'reviewer': 'agent-regression', 'reviewer_type': 'agent', 'tool_version': '1.23.1'})


@pytest.mark.parametrize('seeded', [False, True])
def test_api_import_then_edit_uses_last_imported_revision(ls_api, event, seeded):
    c, app, mapping = ls_api
    seed = {**event, 'revision': 1, 'review_status': 'unreviewed', 'start_ms': 0, 'end_ms': 33, 'contact_ms': None} if seeded else None
    task = ls_snapshot(c, mapping, seed=seed)
    initial = post_ls(c, task)
    assert initial.status_code == 200, initial.text
    first = initial.json()['events'][0]
    second = post_ls(c, edit_snapshot(task))
    assert second.status_code == 200, second.text
    changed = second.json()['events'][0]
    assert changed['event_id'] == first['event_id']
    assert changed['revision'] == first['revision'] + 1
    assert changed['end_ms'] == 100 and changed['review_status'] == 'unreviewed'
    assert changed['provenance']['previous_revision'] == first['revision']
    # Replaying either accepted snapshot never restores old time bounds or tracks.
    assert post_ls(c, task).json()['events'] == []
    assert post_ls(c, edit_snapshot(task)).json()['events'] == []
    current = app.state.store.event(first['event_id'])
    assert current['end_ms'] == 100 and current['revision'] == changed['revision']
    # A never-before-imported stale snapshot is rejected based on updated_at.
    assert post_ls(c, edit_snapshot(task, second=0, end_frame=3)).status_code == 409


@pytest.mark.parametrize('status', ['unreviewed', 'confirmed'])
def test_api_local_edit_conflicts_even_if_hash_is_preserved(ls_api, status):
    c, app, mapping = ls_api
    task = ls_snapshot(c, mapping)
    first = post_ls(c, task).json()['events'][0]
    local = {**first, 'labels': {'stroke': 'smash'}, 'review_status': status}
    response = c.post('/api/v1/events', json={'event': local, 'expected_revision': 1, 'reviewer': 'local-human'})
    assert response.status_code == 200, response.text
    assert post_ls(c, edit_snapshot(task)).status_code == 409
    assert post_ls(c, task).json()['events'] == []
    retained = app.state.store.event(first['event_id'])
    assert retained['revision'] == 2 and retained['labels'] == {'stroke': 'smash'}
    assert retained['review_status'] == status


def test_api_ls_batch_conflict_rolls_back_events_tracks_and_cursor(ls_api):
    c, app, mapping = ls_api
    task = ls_snapshot(c, mapping)
    second_region = copy.deepcopy(task['annotations'][0]['result'][0])
    second_region['id'] = 'region-two'
    task['annotations'][0]['result'].append(second_region)
    first = post_ls(c, task).json()['events']
    local = c.post('/api/v1/events', json={'event': first[1], 'expected_revision': 1, 'reviewer': 'local-human'})
    assert local.status_code == 200
    before_cursor = app.state.store.list('ls_sync')
    assert post_ls(c, edit_snapshot(task)).status_code == 409
    assert app.state.store.event(first[0]['event_id'])['revision'] == 1
    assert app.state.store.event(first[1]['event_id'])['revision'] == 2
    assert app.state.store.list('ls_sync') == before_cursor


def test_api_changed_snapshot_needs_newer_timestamp(ls_api):
    c, _, mapping = ls_api
    task = ls_snapshot(c, mapping)
    assert post_ls(c, task).status_code == 200
    changed = edit_snapshot(task)
    changed['annotations'][0].pop('updated_at')
    assert post_ls(c, changed).status_code == 409


def test_legacy_import_history_does_not_treat_local_audit_as_sync(ls_api):
    c, app, mapping = ls_api
    task = ls_snapshot(c, mapping)
    converted = convert(task, task['annotations'][0])
    # Simulate pre-cursor importer and a later local change preserving its hash.
    first = app.state.store.save_event(converted['events'][0], 0, 'legacy-import')
    local = app.state.store.save_event({**first, 'labels': {'stroke': 'smash'}}, 1, 'local-human')
    assert post_ls(c, task).json()['events'] == []
    assert post_ls(c, edit_snapshot(task)).status_code == 409
    assert app.state.store.event(first['event_id']) == local


def test_legacy_import_can_continue_from_actual_import_revision(ls_api):
    c, app, mapping = ls_api
    task = ls_snapshot(c, mapping)
    converted = convert(task, task['annotations'][0])
    first = app.state.store.save_event(converted['events'][0], 0, 'legacy-import')
    response = post_ls(c, edit_snapshot(task))
    assert response.status_code == 200, response.text
    assert response.json()['events'][0]['revision'] == first['revision'] + 1
