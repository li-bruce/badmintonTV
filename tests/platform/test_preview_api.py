"""API binding/production isolation tests. Media bytes here are explicit fixtures,
never evidence of decoding, model inference, or real R-02a media acceptance.
"""

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("BTV_STORAGE_ROOT", tempfile.mkdtemp(prefix="btv-preview-api-import-"))
from apps.platform.main import create_app


@pytest.fixture
def api_factory(tmp_path, monkeypatch):
    monkeypatch.delenv("BTV_DB_PATH", raising=False)
    def make(name="default", db_name="platform.sqlite3"):
        root = tmp_path / name
        (root / "data").mkdir(parents=True)
        app = create_app(root, root / "platform" / db_name)
        client = TestClient(app, raise_server_exceptions=False)
        library = client.post("/api/v1/libraries", json={"name": "Explicit API fixture"}).json()
        asset = import_asset(client, root, library["library_id"], "asset-a")
        return client, app, asset, library, root
    return make


def import_asset(client, root, library_id, asset_id, *, suffix="mp4", probe=None):
    raw = ("test-only-nonvideo-" + asset_id).encode()
    relative = f"data/{asset_id}.{suffix}"
    (root / relative).write_bytes(raw)
    asset = {"schema_version": "1.0", "asset_id": asset_id, "relative_path": relative,
             "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw), "duration_ms": 3000,
             "width": 640, "height": 360, "fps_num": 30, "fps_den": 1, "time_base": "1/1000",
             "title": "API fixture, not real media", "match_id": "fixture-match", "source_type": "synthetic", "players": [], "split": "test",
             "rights": {"status": "owned", "allowed_uses": ["test"], "evidence": "Test fixture bytes"}, "probe": probe or {}}
    response = client.post("/api/v1/assets/import", json={"library_id": library_id, "manifest": {"schema_version": "1.0", "assets": [asset]}})
    assert response.status_code == 200, response.text
    return response.json()["imported"][0]["asset"]


def seed_preview(api, *, preview_changes=None):
    """Simulate only the trusted worker result boundary, without a fake codec."""
    client, app, asset, _, root = api
    response = client.post(f"/api/v1/assets/{asset['asset_id']}/preview", json={"start_ms": 0, "end_ms": 3000})
    assert response.status_code == 202, response.text
    job = response.json()
    claimed = app.state.queue.claim("fixture-worker", lease_seconds=120)
    assert claimed["job_id"] == job["job_id"]
    directory = root / "platform/jobs" / job["job_id"] / "attempt-1"
    directory.mkdir(parents=True)
    for name in ("preview.mp4", "thumbnails.jpg"):
        (directory / name).write_bytes(("test-only-" + name).encode())
    index_path = directory / "frame-index.sqlite3"
    with sqlite3.connect(index_path) as db:
        db.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE source_frames(source_frame_index INTEGER PRIMARY KEY,source_pts INTEGER,
                source_pts_ms REAL,source_end_ms REAL,key_frame INTEGER);
            CREATE TABLE proxy_frames(proxy_frame_index INTEGER PRIMARY KEY,proxy_pts_ms REAL,
                source_frame_index INTEGER,source_pts INTEGER,source_pts_ms REAL,coverage_start_ms REAL,coverage_end_ms REAL);
            INSERT INTO source_frames VALUES(0,0,0,1000,1),(1,1000,1000,2000,0),(2,2000,2000,3000,0);
            INSERT INTO proxy_frames VALUES(0,0,0,0,0,0,1000),(1,1000,1,1000,1000,1000,2000),(2,2000,2,2000,2000,2000,3000);
        """)
    prefix = directory.relative_to(root).as_posix()
    preview = {"schema_version": "1.0", "source_asset_id": asset["asset_id"], "source_sha256": asset["sha256"], "usage_scope": "general",
               "source_frame_count": 3, "proxy_frame_count": 3, "source_index_scope": "full_source", "source_time_base": "1/1000", "source_origin_pts": 0,
               "requested_start_ms": 0, "window_start_ms": 0, "window_end_ms": 3000, "relative_path": prefix + "/preview.mp4",
               "index_relative_path": prefix + "/frame-index.sqlite3", "thumbnail_relative_path": prefix + "/thumbnails.jpg", "has_audio": False,
               "width": 640, "height": 360, "max_height": 720, "max_fps": None, "thumbnail_count": 1, "thumbs": [], **(preview_changes or {})}
    artifacts = []
    for name, kind in (("preview.mp4", "preview"), ("frame-index.sqlite3", "frame_index"), ("thumbnails.jpg", "thumbnail")):
        raw = (directory / name).read_bytes()
        artifacts.append({"artifact_id": "fixture-" + kind, "kind": kind, "relative_path": prefix + "/" + name,
                          "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw), "created_at": "2026-09-29T00:00:00Z", "producer": "test_fixture"})
    result = {"schema_version": "1.0", "job_id": job["job_id"], "attempt_id": "attempt-1", "status": "succeeded", "preview": preview,
              "artifacts": artifacts, "events": [], "error": None}
    app.state.queue.finish(job["job_id"], "fixture-worker", "succeeded", result=result)
    return app.state.queue.get(job["job_id"])


def update_authoritative_asset(app, asset, **changes):
    current = {**asset, **changes}
    with app.state.store.connect() as db:
        db.execute("UPDATE assets SET body=? WHERE id=?", (json.dumps(current), asset["asset_id"]))


def publish_registry(root, digest):
    path = root / "data/training/handoff/training-registry.v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "1.0", "assets": [{"asset_id": "training-reference", "relative_path": "data/training/reference.mp4",
                                    "sha256": digest, "usage_scope": "training_only", "provenance": {}}]}), encoding="utf-8")
    return path


def test_preview_and_exact_requests_cannot_override_trusted_source_or_paths(api_factory):
    api = api_factory()
    client, app, asset, *_ = api
    forged = {**asset, "asset_id": "different", "relative_path": "data/training/forbidden.mp4", "sha256": "f" * 64}
    response = client.post("/api/v1/assets/asset-a/preview", json={"asset": forged, "assets": [forged], "gpu_required": True,
                          "command": ["arbitrary"], "index_relative_path": "data/foreign.sqlite3", "start_ms": 10, "end_ms": 1000})
    assert response.status_code == 202
    payload = response.json()["payload"]
    assert payload["asset"] == app.state.store.asset("asset-a")
    assert payload["start_ms"] == 10
    assert not {"command", "assets", "gpu_required", "index_relative_path"}.intersection(payload)
    app.state.queue.request_cancel(response.json()["job_id"])
    job = seed_preview(api)
    response = client.post("/api/v1/assets/asset-a/source-frame", json={"preview_job_id": job["job_id"], "source_frame_index": 1,
                          "asset": forged, "index_relative_path": "data/foreign.sqlite3", "output_dir": "models/stolen", "gpu_required": True})
    assert response.status_code == 202, response.text
    payload = response.json()["payload"]
    assert payload["asset"] == asset
    assert payload["index_relative_path"] == job["result"]["preview"]["index_relative_path"]
    assert not {"gpu_required", "output_dir"}.intersection(payload)


@pytest.mark.parametrize("endpoint", ["media", "thumbnails", "frame-map", "source-frames"])
def test_preview_id_is_bound_to_current_asset(api_factory, endpoint):
    api = api_factory()
    client, _, _, library, root = api
    job = seed_preview(api)
    import_asset(client, root, library["library_id"], "asset-b")
    assert client.get(f"/api/v1/assets/asset-b/previews/{job['job_id']}/{endpoint}").status_code == 404
    assert client.post("/api/v1/assets/asset-b/source-frame", json={"preview_job_id": job["job_id"], "source_frame_index": 0}).status_code == 404


@pytest.mark.parametrize("suffix", ["limit=0", "limit=1001", "offset_frame=-1", "at_ms=-1", "at_ms=nan", "limit=x"])
@pytest.mark.parametrize("endpoint", ["frame-map", "source-frames"])
def test_frame_pagination_rejects_invalid_requests_without_server_error(api_factory, suffix, endpoint):
    api = api_factory()
    client = api[0]
    job = seed_preview(api)
    assert client.get(f"/api/v1/assets/asset-a/previews/{job['job_id']}/{endpoint}?{suffix}").status_code == 422


def test_media_mime_and_source_vs_proxy_time_pages(api_factory):
    api = api_factory()
    client, _, _, library, root = api
    job = seed_preview(api)
    other = import_asset(client, root, library["library_id"], "asset-mkv", suffix="mkv")
    assert client.get(f"/api/v1/assets/{other['asset_id']}/media").headers["content-type"] == "video/x-matroska"
    assert client.get(f"/api/v1/assets/asset-a/previews/{job['job_id']}/media").headers["content-type"] == "video/mp4"
    assert client.get(f"/api/v1/assets/asset-a/previews/{job['job_id']}/thumbnails").headers["content-type"] == "image/jpeg"
    page = client.get(f"/api/v1/assets/asset-a/previews/{job['job_id']}/source-frames?at_ms=1500&limit=1").json()
    assert page["source_frames"][0]["source_frame_index"] == 1
    assert page["source_index_scope"] == "full_source"


@pytest.mark.parametrize("change", ["typed_metadata", "registry_hash"])
def test_dynamic_use_restriction_revokes_completed_preview_and_exact_access(api_factory, change):
    api = api_factory()
    client, app, asset, _, root = api
    job = seed_preview(api)
    if change == "typed_metadata":
        update_authoritative_asset(app, asset, usage_scope="training_only")
    else:
        path = publish_registry(root, "f" * 64)
        previous = path.stat()
        publish_registry(root, asset["sha256"])
        assert path.stat().st_size == previous.st_size
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert client.get("/api/v1/assets").json() == []
    for endpoint in ("media", "thumbnails", "frame-map", "source-frames"):
        response = client.get(f"/api/v1/assets/asset-a/previews/{job['job_id']}/{endpoint}")
        assert response.status_code == 422, response.text
        assert "TRAINING_ONLY" in response.text
    assert client.get("/api/v1/assets/asset-a/media").status_code == 422
    assert client.post("/api/v1/assets/asset-a/source-frame", json={"preview_job_id": job["job_id"], "source_frame_index": 0}).status_code == 422


def test_source_hash_change_invalidates_old_preview(api_factory):
    api = api_factory()
    client, app, asset, *_ = api
    job = seed_preview(api)
    update_authoritative_asset(app, asset, sha256="f" * 64)
    assert client.get(f"/api/v1/assets/asset-a/previews/{job['job_id']}/media").status_code == 409


def test_source_frame_requires_explicit_preview_id_without_500(api_factory):
    client, *_ = api_factory()
    response = client.post("/api/v1/assets/asset-a/source-frame", json={"source_frame_index": 0})
    assert response.status_code in (404, 422), response.text


def test_imported_probe_cannot_point_thumbnail_at_reserved_training_file(api_factory):
    client, _, original, library, root = api_factory()
    training = root / "data/training/private.jpg"
    training.parent.mkdir(parents=True)
    training.write_bytes(b"training-only-thumbnail-fixture")
    registry = root / "data/training/handoff/training-registry.v1.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"schema_version": "1.0", "assets": []}), encoding="utf-8")
    raw = b"ordinary-general-fixture"
    # A real import route accepts arbitrary probe metadata from a manifest.
    (root / "data/asset-probe.mp4").write_bytes(raw)
    asset = {**original, "asset_id": "asset-probe", "relative_path": "data/asset-probe.mp4", "size_bytes": len(raw),
             "sha256": hashlib.sha256(raw).hexdigest(), "probe": {"thumbnail_relative_path": "data/training/private.jpg"}}
    response = client.post("/api/v1/assets/import", json={"library_id": library["library_id"], "manifest": {"schema_version": "1.0", "assets": [asset]}})
    if response.status_code in (403, 422):
        return  # A purposeful import rejection is also safe; 500 is not.
    assert response.status_code == 200, response.text
    response = client.get(f"/api/v1/assets/{asset['asset_id']}/thumbnail")
    assert response.status_code in (403, 404, 422), response.content
    assert b"training-only-thumbnail-fixture" not in response.content


def test_raw_media_cannot_serve_replaced_training_bytes_under_stale_asset_hash(api_factory):
    client, _, asset, _, root = api_factory()
    replacement = b"x" * asset["size_bytes"]
    publish_registry(root, hashlib.sha256(replacement).hexdigest())
    source = root / asset["relative_path"]
    source.write_bytes(replacement)
    response = client.get("/api/v1/assets/asset-a/media")
    assert response.status_code in (403, 404, 409, 422), response.content
    assert response.content != replacement


def test_worker_reads_authoritative_custom_business_db_before_preview(api_factory, monkeypatch):
    from packages.runtime.worker import run_once
    api = api_factory(db_name="custom-business.sqlite3")
    client, app, asset, _, root = api
    response = client.post("/api/v1/assets/asset-a/preview", json={"start_ms": 0, "end_ms": 1000})
    assert response.status_code == 202
    update_authoritative_asset(app, asset, usage_scope="training_only")
    executed = []
    def fixture_handler(context, exchange_dir):
        executed.append(context.job["job_id"])
        return {"schema_version": "1.0", "job_id": context.job["job_id"], "attempt_id": f"attempt-{context.job['attempt']}",
                "status": "succeeded", "preview": {"fixture": True}, "artifacts": [], "events": [], "error": None}
    monkeypatch.setattr("packages.runtime.media_proxy.create_proxy", fixture_handler)
    result = run_once(app.state.queue, root, worker_id="fixture-worker", lease_seconds=120)
    assert result["status"] == "blocked", result
    assert result["error"]["code"] == "TRAINING_ONLY"
    assert executed == []


@pytest.mark.parametrize("mismatch", [{"source_asset_id": "foreign-asset"}, {"source_sha256": "f" * 64}])
def test_completed_preview_result_must_match_payload_and_authoritative_asset(api_factory, mismatch):
    api = api_factory()
    client = api[0]
    job = seed_preview(api, preview_changes=mismatch)
    response = client.get(f"/api/v1/assets/asset-a/previews/{job['job_id']}/media")
    assert response.status_code in (409, 422), response.content
