"""Identity-proof/API review: synthetic temporary bytes, never real training data."""
import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.platform.store import Store
from packages.contracts import TRAINING_REGISTRY_PATH
from packages.runtime import Queue
from packages.runtime.production import current_source_records


@pytest.fixture
def identity_api(tmp_path, monkeypatch):
    root = tmp_path / "video"
    (root / "data").mkdir(parents=True)
    db = root / "platform/custom-catalog.sqlite3"
    monkeypatch.setenv("BTV_STORAGE_ROOT", str(root))
    monkeypatch.setenv("BTV_DB_PATH", str(db))
    from apps.platform.main import create_app
    app = create_app(root, db)
    client = TestClient(app)
    library = client.post("/api/v1/libraries", json={"name": "Identity review fixture"}).json()["library_id"]
    return SimpleNamespace(root=root, db=db, app=app, client=client, library=library,
                           store=app.state.store, queue=app.state.queue)


def media(p, *, large=False):
    raw = b"a" * (8_000_001 if large else 128)
    path = p.root / "data/synthetic.mp4"
    path.write_bytes(raw)
    asset = {"asset_id": "identity-source", "relative_path": "data/synthetic.mp4",
        "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw), "duration_ms": 1000,
        "width": 16, "height": 16, "fps_num": 1, "fps_den": 1, "time_base": "1/1000",
        "match_id": "synthetic-match", "source_type": "synthetic", "split": "unassigned", "title": "Synthetic identity bytes"}
    return asset, path


def succeeded_import(p, asset, *, operation="verify_manifest", proof=True):
    payload = {"library_id": p.library, "assets": [asset]} if operation == "verify_manifest" else {
        "library_id": p.library, "relative_path": asset["relative_path"]}
    result = {"assets": [asset]} if operation == "verify_manifest" else {"asset": asset}
    if proof:
        result["source_identities"] = {asset["asset_id"]: p.store._file_identity(p.root / asset["relative_path"])}
    job = p.queue.enqueue(operation, payload)
    assert p.queue.claim("identity-fixture")["job_id"] == job["job_id"]
    p.queue.finish(job["job_id"], "identity-fixture", "succeeded", result=result)
    return job["job_id"]


def forbid_hash(*args, **kwargs):
    pytest.fail("Web process must not synchronously rehash this source")


def replace_same_size(path):
    before = path.stat()
    replacement = path.with_name("replacement.synthetic")
    replacement.write_bytes(b"b" * before.st_size)
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, path)
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("operation", ["verify_manifest", "probe"])
def test_large_apply_trusted_proof_avoids_web_hash_and_records_playback_identity(identity_api, monkeypatch, operation):
    p = identity_api
    asset, path = media(p, large=True)
    job = succeeded_import(p, asset, operation=operation)
    monkeypatch.setattr(hashlib, "file_digest", forbid_hash)
    response = p.client.post(f"/api/v1/jobs/{job}/apply")
    assert response.status_code == 200, response.text
    assert response.json()["integrity"] == "worker_sha256_verified"
    assert p.store.verified_source_path(p.store.asset(asset["asset_id"])) == path


def test_stale_proof_rejects_same_size_same_mtime_replacement(identity_api, monkeypatch):
    p = identity_api
    asset, path = media(p)
    job = succeeded_import(p, asset)
    replace_same_size(path)
    monkeypatch.setattr(hashlib, "file_digest", forbid_hash)
    response = p.client.post(f"/api/v1/jobs/{job}/apply")
    assert response.status_code == 409 and "SOURCE_CHANGED" in response.text, response.text
    assert p.store._raw_assets() == []


def test_legacy_large_apply_rejects_missing_proof_even_with_asset_probe_claim(identity_api, monkeypatch):
    p = identity_api
    asset, path = media(p, large=True)
    asset["probe"] = {"source_identities": {asset["asset_id"]: p.store._file_identity(path)}}
    job = succeeded_import(p, asset, proof=False)
    monkeypatch.setattr(hashlib, "file_digest", forbid_hash)
    response = p.client.post(f"/api/v1/jobs/{job}/apply")
    assert response.status_code == 409 and "SOURCE_REVERIFY_REQUIRED" in response.text, response.text
    assert p.store._raw_assets() == []


@pytest.mark.parametrize("registered_training", [False, True])
def test_legacy_small_apply_hashes_actual_bytes_then_checks_registry(identity_api, monkeypatch, registered_training):
    p = identity_api
    asset, path = media(p)
    job = succeeded_import(p, asset, proof=False)
    replace_same_size(path)
    if registered_training:
        registry = p.root / TRAINING_REGISTRY_PATH
        registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps({"schema_version": "1.0", "assets": [{"asset_id": "training-alias",
            "relative_path": "data/training/synthetic/original.mp4", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "usage_scope": "training_only"}]}), encoding="utf-8")
    actual_digest, calls = hashlib.file_digest, []
    def tracked(stream, *args, **kwargs):
        calls.append(stream.name)
        return actual_digest(stream, *args, **kwargs)
    monkeypatch.setattr(hashlib, "file_digest", tracked)
    response = p.client.post(f"/api/v1/jobs/{job}/apply")
    assert response.status_code == (422 if registered_training else 409), response.text
    assert ("TRAINING_ONLY" if registered_training else "SOURCE_CHANGED") in response.text
    assert len(calls) == 1
    assert p.store._raw_assets() == []


def test_newly_imported_raw_media_rejects_changed_file_identity(identity_api, monkeypatch):
    p = identity_api
    asset, path = media(p)
    response = p.client.post("/api/v1/assets/import", json={"library_id": p.library, "manifest": {"assets": [asset]}})
    assert response.status_code == 200, response.text
    url = f"/api/v1/assets/{asset['asset_id']}/media"
    response = p.client.get(url, headers={"Range": "bytes=0-3"})
    assert response.status_code == 206 and response.content == b"aaaa"
    assert response.headers["cache-control"] == "no-store"
    replace_same_size(path)
    monkeypatch.setattr(hashlib, "file_digest", forbid_hash)
    response = p.client.get(url, headers={"Range": "bytes=0-3"})
    assert response.status_code == 409 and "SOURCE_CHANGED" in response.text, response.text


def test_custom_business_binding_survives_browser_payload_environment_and_rebind(identity_api, monkeypatch):
    p = identity_api
    asset, path = media(p)
    p.store.import_assets([asset], p.library)
    decoy = p.root / "other/decoy.sqlite3"
    Store(decoy, p.root)
    response = p.client.post("/api/v1/assets/import-path", json={"library_id": p.library,
        "relative_path": asset["relative_path"], "business_database": str(decoy), "db_path": str(decoy),
        "metadata": {"business_database": str(decoy)}})
    assert response.status_code == 202, response.text
    monkeypatch.setenv("BTV_DB_PATH", str(decoy))
    assert [row["asset_id"] for row in current_source_records(p.queue.db_path)] == [asset["asset_id"]]
    restarted = Queue(p.queue.db_path)
    restarted.bind_business_database(p.db)  # Same binding is idempotent.
    with pytest.raises(ValueError, match="already bound"):
        restarted.bind_business_database(decoy)
    assert [row["asset_id"] for row in current_source_records(p.queue.db_path)] == [asset["asset_id"]]


def test_missing_bound_business_database_fails_closed_without_fallback(identity_api, monkeypatch):
    p = identity_api
    decoy = p.root / "other/fallback.sqlite3"
    Store(decoy, p.root)
    monkeypatch.setenv("BTV_DB_PATH", str(decoy))
    p.db.rename(p.db.with_suffix(".saved"))  # Simulate unavailable configured DB, keep its data.
    with pytest.raises(ValueError, match="SOURCE_DATABASE_UNAVAILABLE"):
        current_source_records(p.queue.db_path)
    assert not p.db.exists()


def test_apply_does_not_bless_source_changed_between_proof_check_and_import(identity_api, monkeypatch):
    p = identity_api
    asset, path = media(p)
    job = succeeded_import(p, asset)
    original = p.store.import_assets
    def concurrent_writer(assets, library_id, *args, **kwargs):
        # A regular source writer finishes between preflight and the insert;
        # no database tampering or forged internal worker result is involved.
        replace_same_size(path)
        return original(assets, library_id, *args, **kwargs)
    monkeypatch.setattr(p.store, "import_assets", concurrent_writer)
    response = p.client.post(f"/api/v1/jobs/{job}/apply")
    assert response.status_code == 409 and "SOURCE_CHANGED" in response.text, response.text
    assert p.store._raw_assets() == []
