"""R-04b production isolation regressions; all media bytes are synthetic.

These exercise real Store/API/worker guards, without FFmpeg or training data.
The SQL mutations deliberately simulate databases/jobs created before isolation.
"""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from packages.contracts import TRAINING_REGISTRY_PATH, UsageScopeError
from packages.runtime.production import check_job_sources, check_sources


@pytest.fixture
def production(tmp_path, monkeypatch):
    root = tmp_path / "video"
    (root / "data").mkdir(parents=True)
    raw = b"synthetic production-isolation fixture, not playable video"
    (root / "data/source.mp4").write_bytes(raw)
    db = root / "platform/platform.sqlite3"
    monkeypatch.setenv("BTV_STORAGE_ROOT", str(root))
    monkeypatch.setenv("BTV_DB_PATH", str(db))
    from apps.platform.main import create_app
    app = create_app(root, db)
    client = TestClient(app)
    library = client.post("/api/v1/libraries", json={"name": "Synthetic R-04b"}).json()["library_id"]
    asset = {
        "schema_version": "1.0", "asset_id": "synthetic-source", "relative_path": "data/source.mp4",
        "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw), "duration_ms": 1000,
        "width": 320, "height": 180, "fps_num": 25, "fps_den": 1, "time_base": "1/12800",
        "title": "Synthetic isolation fixture", "match_id": "synthetic-match", "source_type": "synthetic",
        "players": [], "split": "unassigned", "usage_scope": "general", "provenance": {},
        "rights": {"status": "owned", "allowed_uses": ["test"], "evidence": "synthetic unit test"},
    }
    app.state.store.import_assets([asset], library)
    return SimpleNamespace(root=root, raw=raw, asset=asset, library=library, app=app, client=client,
                           store=app.state.store, queue=app.state.queue)


def registry(p, *, restricted=True):
    path = p.root / TRAINING_REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"asset_id": "training-original", "sha256": p.asset["sha256"],
             "relative_path": "data/training/synthetic/source.mp4", "usage_scope": "training_only"}] if restricted else []
    path.write_text(json.dumps({"schema_version": "1.0", "assets": rows}), encoding="utf-8")
    return path


def historical_training_row(p):
    historical = {**p.asset, "usage_scope": "training_only"}
    with p.store.connect() as db:
        db.execute("UPDATE assets SET body=? WHERE id=?", (json.dumps(historical), historical["asset_id"]))


def assert_denied(response, code="TRAINING_ONLY"):
    assert response.status_code == 422, response.text
    assert code in response.text, response.text


def context(p, operation, payload):
    def no_execute(*args, **kwargs):
        pytest.fail("restricted source reached a media subprocess")
    return SimpleNamespace(storage_root=p.root, queue=p.queue,
        job={"job_id": "synthetic-job", "attempt": 1, "operation": operation, "payload": payload},
        check=lambda: None, log=lambda *args, **kwargs: None, execute=no_execute)


def completed_job(p, operation, payload, result=None, status="succeeded"):
    job = p.queue.enqueue(operation, payload)
    claimed = p.queue.claim("synthetic-worker")
    assert claimed["job_id"] == job["job_id"]
    return p.queue.finish(job["job_id"], "synthetic-worker", status, result=result,
                          error={"code": "SYNTHETIC_TEST"} if status == "failed" else None)


def test_store_checks_incoming_scope_before_same_sha_dedup(production):
    p = production
    for declaration in ({"usage_scope": "training_only"}, {"provenance": {"usage_scope": "training_only"}}):
        alias = {**p.asset, "asset_id": "incoming-alias", **declaration}
        with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
            p.store.import_assets([alias], p.library)
    assert len(p.store._raw_assets()) == 1
    assert p.store.asset(p.asset["asset_id"])["usage_scope"] == "general"


def test_store_cannot_dedup_to_restricted_historical_row_after_fields_removed(production):
    p = production
    historical_training_row(p)
    incoming = {key: value for key, value in p.asset.items() if key not in ("usage_scope", "provenance")}
    incoming["asset_id"] = "renamed-copy"
    with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
        p.store.import_assets([incoming], p.library)


def test_registry_sha_blocks_renamed_copy_without_usage_or_source_fields(production):
    p = production
    registry(p)
    incoming = {key: value for key, value in p.asset.items() if key not in ("usage_scope", "provenance")}
    incoming.update(asset_id="renamed-copy", relative_path="data/innocent-copy.mp4")
    (p.root / incoming["relative_path"]).write_bytes(p.raw)
    response = p.client.post("/api/v1/assets/import", json={"library_id": p.library, "manifest": {"assets": [incoming]}})
    assert_denied(response)
    assert len(p.store._raw_assets()) == 1


@pytest.mark.parametrize("failure", ["pending_empty", "invalid_filtered"])
def test_empty_or_filtered_listing_still_surfaces_global_registry_failure(production, failure):
    p = production
    if failure == "pending_empty":
        (p.root / "data/training").mkdir()
        with p.store.connect() as db:
            db.execute("DELETE FROM assets")
        library_id, code = None, "TRAINING_REGISTRY_PENDING"
    else:
        registry(p).write_text('{"schema_version":"1.0","assets":[', encoding="utf-8")
        library_id, code = "no-assets-in-this-library", "TRAINING_REGISTRY_INVALID"
    with pytest.raises(UsageScopeError, match=code):
        p.store.assets(library_id)
    response = p.client.get("/api/v1/assets", params={"library_id": library_id} if library_id else {})
    assert_denied(response, code)


def test_import_path_preflight_rejects_training_path_before_queueing(production):
    p = production
    registry(p, restricted=False)
    source = p.root / "data/training/synthetic/source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(p.raw)
    response = p.client.post("/api/v1/assets/import-path", json={"library_id": p.library,
                             "relative_path": source.relative_to(p.root).as_posix(), "metadata": {}})
    assert_denied(response)
    assert p.queue.list() == []


@pytest.mark.parametrize("boundary", ["media", "candidate", "timeline", "from_candidates", "research_render"])
def test_existing_asset_production_boundaries_recheck_updated_registry(production, boundary):
    p = production
    candidate = {"candidate_id": "old-candidate", "asset_id": p.asset["asset_id"], "start_ms": 0,
                 "end_ms": 500, "event_ids": [], "review_status": "confirmed", "reviewer": "test", "reviewer_type": "agent"}
    p.store.put("candidate", candidate["candidate_id"], candidate)
    timeline = {"schema_version": "1.0", "timeline_id": "old-timeline", "title": "Synthetic",
        "segments": [{"segment_id": "old-segment", "asset_id": p.asset["asset_id"], "in_ms": 0,
                      "out_ms": 500, "speed": 1.0, "event_ids": [], "fit": "contain", "audio": "source",
                      "review_status": "confirmed"}],
        "output": {"width": 1080, "height": 1920, "fps": 30, "video_codec": "h264", "audio_codec": "aac"}}
    assert p.client.post("/api/v1/timelines", json=timeline).status_code == 200
    before = copy.deepcopy(p.store.get("timeline", "old-timeline"))
    registry(p)
    if boundary == "media":
        response = p.client.get(f"/api/v1/assets/{p.asset['asset_id']}/media")
    elif boundary == "candidate":
        response = p.client.post("/api/v1/candidates/old-candidate/confirm", json={"review_status": "rejected", "reviewer": "test"})
    elif boundary == "timeline":
        response = p.client.post("/api/v1/timelines", json={**timeline, "title": "must not save"})
    elif boundary == "from_candidates":
        response = p.client.post("/api/v1/timelines/from-candidates", json={"candidate_ids": ["old-candidate"]})
    else:
        response = p.client.post("/api/v1/timelines/old-timeline/render", json={"research_preview": True})
    assert_denied(response)
    assert p.store.get("candidate", "old-candidate") == candidate
    assert p.store.get("timeline", "old-timeline") == before
    assert len(p.store.list("timeline")) == 1
    assert p.queue.list() == []


@pytest.mark.parametrize("boundary", ["artifact", "retry", "apply_probe", "apply_verify"])
def test_preexisting_job_cannot_reenter_production_after_registry_update(production, boundary):
    p = production
    if boundary == "artifact":
        output = p.root / "render/synthetic-old.mp4"
        output.parent.mkdir()
        output.write_bytes(b"synthetic old artifact")
        job = completed_job(p, "render", {"assets": [p.asset]}, {"artifacts": [
            {"artifact_id": "old-output", "kind": "video", "relative_path": "render/synthetic-old.mp4"}]})
    elif boundary == "retry":
        job = completed_job(p, "render", {"assets": [p.asset]}, status="failed")
    elif boundary == "apply_probe":
        job = completed_job(p, "probe", {"relative_path": p.asset["relative_path"], "library_id": p.library}, {"asset": p.asset})
    else:
        job = completed_job(p, "verify_manifest", {"assets": [p.asset], "library_id": p.library}, {"assets": [p.asset]})
    registry(p)
    base = f"/api/v1/jobs/{job['job_id']}"
    response = p.client.get(base + "/artifacts/old-output") if boundary == "artifact" else p.client.post(
        base + ("/retry" if boundary == "retry" else "/apply"))
    assert_denied(response)
    assert p.queue.get(job["job_id"])["status"] == job["status"]
    assert p.store._raw_assets()[0]["usage_scope"] == "general"


def test_worker_checks_actual_sha_when_declared_sha_and_identity_are_forged(production):
    p = production
    registry(p)
    forged = {**p.asset, "asset_id": "unknown-copy", "sha256": "f" * 64}
    ctx = context(p, "render", {"assets": [forged]})
    with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
        check_sources(ctx, [forged], verify_bytes=True)


def test_worker_rechecks_authoritative_scope_for_old_queued_snapshot(production):
    p = production
    ctx = context(p, "render", {"assets": [copy.deepcopy(p.asset)]})
    historical_training_row(p)
    with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
        check_job_sources(ctx)


def test_verify_manifest_rechecks_registry_after_hashing(production):
    from packages.runtime.worker import verify_manifest
    p = production
    registry(p, restricted=False)
    ctx = context(p, "verify_manifest", {"assets": [p.asset], "library_id": p.library})
    check_job_sources(ctx)  # Simulate the worker's initial accepted preflight.
    def log(event, **fields):
        if fields.get("stage") == "verify_manifest" and fields.get("current") == 0:
            registry(p)  # Library publishes restrictions while the old job runs.
    ctx.log = log
    with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
        verify_manifest(ctx, p.root / "platform/unused-exchange")


def test_probe_computed_sha_rejects_alias_before_media_subprocess(production, monkeypatch):
    from packages.runtime import worker
    p = production
    registry(p)
    monkeypatch.setattr(worker, "_binary", lambda *args: "unused-synthetic-tool")
    ctx = context(p, "probe", {"relative_path": p.asset["relative_path"], "asset_metadata": {}})
    check_job_sources(ctx)  # No declared ID/hash: only actual bytes expose alias.
    with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
        worker.probe(ctx, p.root / "platform/unused-exchange")
