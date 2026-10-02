"""A-14 API engineering fixtures: synthetic bytes/annotations, no media or GPU.

The shared fixture uses a temporary private DB and mocked trusted catalog. The
optional historical snapshot check only reads its existing JSON file.
"""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_training_api import workspace, seed, save, bundle_url
from apps.platform.main import create_app
from packages.contracts.training import TrainingSnapshot, training_content_sha256


def roi(record, shape="rectangle", **changes):
    points = [{"x": .2, "y": .3}, {"x": .6, "y": .8}]
    if shape == "polygon":
        points = [{"x": .2, "y": .2}, {"x": .7, "y": .2}, {"x": .6, "y": .8}, {"x": .3, "y": .7}]
    value = {"type": "image_region", "schema_version": "1.0", "evidence_id": "roi-" + shape,
             "record_id": record["record_id"], "asset_id": record["asset_id"],
             "at_ms": record.get("at_ms", record.get("start_ms")),
             "coordinate_system": "image_normalized", "shape": shape, "points": points,
             "subject_role": "self", "observation_source": "agent", "precision": "browser_time"}
    value.update(changes)
    return value


def saved_regions(client, project_id):
    draft = seed(client, project_id)
    for index, shape in ((2, "rectangle"), (4, "polygon")):
        record = draft["records"][index]
        record["evidence"] = [roi(record, shape)]
    response = save(client, project_id, draft)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("shape,index", [("rectangle", 2), ("polygon", 4)])
def test_region_save_reload_preserves_geometry_and_opaque_legacy_evidence(workspace, shape, index):
    client, _, project_id, _ = workspace
    draft = seed(client, project_id)
    record = draft["records"][index]
    legacy = {"type": "legacy-note", "points": "opaque original shape", "at_ms": -5, "source": "synthetic evidence"}
    region = roi(record, shape)
    record["evidence"] = [legacy, region]
    response = save(client, project_id, draft)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["records"][index]["evidence"] == [legacy, region]
    assert "subject_person_id" not in saved["records"][index]["evidence"][1]
    assert saved["records"][index]["review"]["reviewer_type"] == "agent"
    assert client.get(bundle_url(project_id)).json() == saved
    assert client.get(bundle_url(project_id), params={"revision": 1}).json() == saved


@pytest.mark.parametrize("invalid", ["zero-width", "self-intersection", "boolean-coordinate", "record-id",
                                      "asset-id", "point-time", "frame-precision", "missing-person",
                                      "opponent-is-self", "duplicate-id"])
def test_invalid_roi_returns_422_and_preserves_bundle_project_and_history(workspace, invalid):
    client, _, project_id, _ = workspace
    original = saved_regions(client, project_id)
    project_before = client.get(f"/api/v1/training/projects/{project_id}").json()
    history_before = client.get(bundle_url(project_id) + "/revisions").json()
    draft = copy.deepcopy(original)
    record = draft["records"][2]
    region = record["evidence"][0]
    if invalid == "zero-width":
        region["points"][1]["x"] = region["points"][0]["x"]
    elif invalid == "self-intersection":
        region.update(shape="polygon", points=[{"x": 0., "y": 0.}, {"x": 1., "y": 1.},
                                               {"x": 0., "y": 1.}, {"x": 1., "y": 0.}])
    elif invalid == "boolean-coordinate":
        region["points"][0]["x"] = True
    elif invalid == "record-id":
        region["record_id"] = "contact-2"
    elif invalid == "asset-id":
        region["asset_id"] = "not-the-source"
    elif invalid == "point-time":
        region["at_ms"] += 1
    elif invalid == "frame-precision":
        region["precision"] = "exact_frame"
    elif invalid == "missing-person":
        region["subject_person_id"] = "not-a-person"
    elif invalid == "opponent-is-self":
        record["state"] = {"opponent": {"person_id": "near", "team_id": "a"}}
        region.update(subject_role="opponent", subject_person_id="near")
    else:
        record["evidence"].append(copy.deepcopy(region))
    response = save(client, project_id, draft, 1)
    assert response.status_code == 422, response.text
    assert client.get(bundle_url(project_id)).json() == original
    assert client.get(f"/api/v1/training/projects/{project_id}").json() == project_before
    assert client.get(bundle_url(project_id) + "/revisions").json() == history_before


def test_http_actor_claim_cannot_authorize_human_region(workspace):
    client, _, project_id, _ = workspace
    original = saved_regions(client, project_id)
    draft = copy.deepcopy(original)
    draft["records"][2]["evidence"][0]["observation_source"] = "human"
    response = client.put(bundle_url(project_id), json={"bundle": draft, "expected_revision": 1,
                                                      "actor_type": "human", "reviewer": "claimed-human"})
    assert response.status_code == 422, response.text
    assert client.get(bundle_url(project_id)).json() == original
    assert client.get(f"/api/v1/training/projects/{project_id}").json()["actor_type"] == "agent"


def test_roi_stale_cas_409_retains_newest_geometry_and_old_revision(workspace):
    client, _, project_id, _ = workspace
    first = saved_regions(client, project_id)
    latest_draft = copy.deepcopy(first)
    latest_draft["records"][2]["evidence"][0]["points"][0]["x"] = .25
    response = save(client, project_id, latest_draft, 1)
    assert response.status_code == 200, response.text
    latest = response.json()
    assert latest["revision"] == 2 and latest["records"][2]["revision"] == 2
    stale = copy.deepcopy(first)
    stale["records"][2]["evidence"] = []
    response = save(client, project_id, stale, 1)
    assert response.status_code == 409, response.text
    assert client.get(bundle_url(project_id)).json() == latest
    assert client.get(bundle_url(project_id), params={"revision": 1}).json() == first
    assert len(client.get(bundle_url(project_id) + "/revisions").json()) == 2


def test_region_snapshot_download_remains_frozen_after_edit_and_app_restart(workspace):
    client, app, project_id, _ = workspace
    first = saved_regions(client, project_id)
    project = client.get(f"/api/v1/training/projects/{project_id}").json()["project"]
    response = client.post(f"/api/v1/training/projects/{project_id}/snapshots", json={"expected_revision": project["revision"]})
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert snapshot["bundles"][0] == first
    assert TrainingSnapshot.model_validate(snapshot).content_sha256 == training_content_sha256(snapshot)
    url = "/api/v1/training/snapshots/" + snapshot["snapshot_id"]
    audit = client.get(url + "/download", params={"view": "audit", "format": "json"})
    assert audit.status_code == 200 and audit.json() == snapshot
    lines = client.get(url + "/download", params={"view": "audit", "format": "jsonl"})
    assert lines.status_code == 200
    assert json.loads(lines.text.splitlines()[1]) == first
    assert snapshot["usage_scope"] == "training_only" and snapshot["training_view"] == []
    assert not snapshot["quality_summary"]["trainable"]
    assert client.get(url + "/download", params={"view": "training"}).status_code == 409
    changed = copy.deepcopy(first)
    changed["records"][4]["evidence"][0]["points"][0]["x"] = .25
    updated = save(client, project_id, changed, 1)
    assert updated.status_code == 200, updated.text
    assert client.get(url).json() == snapshot
    restarted = create_app(app.state.storage_root, app.state.store.path)
    with TestClient(restarted) as reopened:
        assert reopened.get(bundle_url(project_id)).json() == updated.json()
        assert reopened.get(url).json() == snapshot
        assert reopened.get(url + "/download", params={"view": "audit"}).json() == snapshot
        assert reopened.get("/api/v1/assets").json() == []
        assert reopened.get("/api/v1/events").json() == []


@pytest.mark.parametrize("action", ["delete", "downgrade"])
def test_old_human_roi_cannot_be_rebound_but_can_be_removed_or_downgraded(workspace, monkeypatch, action):
    client, app, project_id, _ = workspace
    draft = seed(client, project_id)
    draft["records"][2]["evidence"] = [roi(draft["records"][2], observation_source="human")]
    # Trusted server configuration is explicit and local to this synthetic test;
    # a request body cannot select it. No real source or production DB is used.
    with monkeypatch.context() as config:
        config.setenv("BTV_TRAINING_ACTOR_TYPE", "human")
        human_app = create_app(app.state.storage_root, app.state.store.path)
    with TestClient(human_app) as human:
        response = save(human, project_id, draft)
        assert response.status_code == 200, response.text
        reviewed = response.json()
        reviewed["records"][2]["review"] = {"status": "confirmed", "reviewer_type": "human", "reviewer": "synthetic-human"}
        response = save(human, project_id, reviewed, 1)
        assert response.status_code == 200, response.text
        original = response.json()
    inherited_rebind = copy.deepcopy(original)
    inherited_rebind["records"][2].update(person_id="far", team_id="b")
    assert save(client, project_id, inherited_rebind, 2).status_code == 422
    assert client.get(bundle_url(project_id)).json() == original
    edit = copy.deepcopy(original)
    if action == "delete":
        edit["records"][2]["evidence"] = []
    else:
        edit["records"][2]["evidence"][0]["observation_source"] = "agent"
        edit["records"][2]["evidence"][0]["points"][0]["x"] = .25
    response = save(client, project_id, edit, 2)
    assert response.status_code == 200, response.text
    review = response.json()["records"][2]["review"]
    assert review["status"] == "pending" and review["reviewer_type"] is None
    assert client.get(bundle_url(project_id), params={"revision": 2}).json() == original


def test_actual_pre_region_snapshot_canonical_hash_and_dump_remain_unchanged():
    path = Path("D:/video/platform/integration-20261002/snapshot-before-restart.json")
    if not path.is_file():
        pytest.skip("read-only integration snapshot is absent on this host")
    before = path.read_bytes()
    body = json.loads(before.decode("utf-8-sig"))
    parsed = TrainingSnapshot.model_validate(body)
    assert parsed.model_dump(mode="json") == body
    assert training_content_sha256(parsed) == "d2deb51291cbb8ad5ac100e7a95d60afb6670e8c3762f05304daee77410a67dd"
    assert body["content_sha256"] == parsed.content_sha256
    assert path.read_bytes() == before
