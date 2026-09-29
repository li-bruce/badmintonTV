"""Synthetic bytes test artifact trust boundaries, not media/ML performance."""
import hashlib
import gc
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_preview_api import api_factory, seed_preview, publish_registry
from packages.runtime import worker
from packages.runtime.artifact_identity import ArtifactIdentityError, hash_identity, check_proof


def completed_artifact(api, raw=b'A' * 64, *, proof=False, embedded_proof=False):
    _, app, asset, _, root = api
    job = app.state.queue.enqueue('exact_frame', {'asset': asset})
    claimed = app.state.queue.claim('artifact-fixture', lease_seconds=120)
    directory = root / f"platform/jobs/{job['job_id']}/attempt-{claimed['attempt']}"
    directory.mkdir(parents=True)
    path = directory / 'frame.jpg'
    path.write_bytes(raw)
    artifact = {'artifact_id': 'image', 'kind': 'source_frame', 'relative_path': path.relative_to(root).as_posix(),
                'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw), 'usage_scope': 'general'}
    trusted = {**hash_identity(path), 'relative_path': artifact['relative_path']}
    result = {'artifacts': [artifact]}
    if embedded_proof:
        artifact['identity'] = trusted['identity']
        result['artifact_identities'] = {'image': trusted}
    app.state.queue.finish(job['job_id'], 'artifact-fixture', 'succeeded', result=result,
                           artifact_identities={'image': trusted} if proof else None)
    return app.state.queue.get(job['job_id']), artifact, path


def url(job, artifact):
    return f"/api/v1/jobs/{job['job_id']}/artifacts/{artifact['artifact_id']}"


def replace_same_size(path):
    before = path.stat()
    replacement = path.with_name('replacement.fixture')
    replacement.write_bytes(b'B' * before.st_size)
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, path)
    assert path.stat().st_size == before.st_size and path.stat().st_mtime_ns == before.st_mtime_ns


def rewrite_same_size(path):
    before = path.stat()
    with path.open('r+b') as stream:
        stream.write(b'B' * before.st_size)
        stream.flush()
        os.fsync(stream.fileno())
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_ino == before.st_ino and path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize('proof', [False, True])
def test_same_length_training_byte_replacement_never_downloads(api_factory, proof):
    api = api_factory()
    job, artifact, path = completed_artifact(api, proof=proof, embedded_proof=True)
    replace_same_size(path)
    publish_registry(api[4], hashlib.sha256(path.read_bytes()).hexdigest())
    response = api[0].get(url(job, artifact))
    assert response.status_code == (409 if proof else 422), response.text
    assert ('ARTIFACT_CHANGED' if proof else 'TRAINING_ONLY') in response.text
    assert b'B' * 64 not in response.content
    if not proof:
        assert api[1].state.queue.artifact_identity(job['job_id'], job['attempt'], artifact['artifact_id']) is None


def test_legacy_small_hashes_once_then_remains_stat_gated(api_factory, monkeypatch):
    api = api_factory()
    job, artifact, path = completed_artifact(api)
    from apps.platform import main
    original, calls = main.hash_identity, []
    def tracked(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(main, 'hash_identity', tracked)
    for _ in range(2):
        response = api[0].get(url(job, artifact), headers={'Range': 'bytes=0-3'})
        assert response.status_code == 206 and response.content == b'AAAA', response.text
    assert calls == [path]
    replace_same_size(path)
    assert api[0].get(url(job, artifact)).status_code == 409
    assert calls == [path]


@pytest.mark.parametrize('proof', [False, True])
def test_large_artifact_never_hashes_in_web_or_trusts_embedded_proof(api_factory, monkeypatch, proof):
    api = api_factory()
    job, artifact, _ = completed_artifact(api, b'A' * 8_000_001, proof=proof, embedded_proof=True)
    import packages.runtime.artifact_identity as identities
    monkeypatch.setattr(identities.hashlib, 'sha256', lambda *args, **kwargs: pytest.fail('Web must not hash large artifacts'))
    response = api[0].get(url(job, artifact), headers={'Range': 'bytes=0-3'})
    if proof:
        assert response.status_code == 206 and response.content == b'AAAA'
    else:
        assert response.status_code == 409 and 'ARTIFACT_REVERIFY_REQUIRED' in response.text


@pytest.mark.parametrize('endpoint,field', [('media','relative_path'),('thumbnails','thumbnail_relative_path'),
    ('frame-map','index_relative_path'),('source-frames','index_relative_path'),('status','relative_path'),('exact','index_relative_path')])
def test_preview_specific_routes_cannot_bypass_actual_artifact_gate(api_factory, endpoint, field):
    api = api_factory()
    job = seed_preview(api)
    # The older test fixture uses sqlite3's transaction-only context manager;
    # collect its closed-over cursor cycle before replacing the file on Windows.
    gc.collect()
    path = api[4] / job['result']['preview'][field]
    replace_same_size(path)
    publish_registry(api[4], hashlib.sha256(path.read_bytes()).hexdigest())
    base = f"/api/v1/assets/asset-a/previews/{job['job_id']}"
    if endpoint == 'exact':
        response = api[0].post('/api/v1/assets/asset-a/source-frame', json={'preview_job_id': job['job_id'], 'source_frame_index': 1})
    else:
        response = api[0].get('/api/v1/assets/asset-a/preview' if endpoint == 'status' else base+'/'+endpoint)
    assert response.status_code == 422 and 'TRAINING_ONLY' in response.text, response.text


def test_download_checks_open_descriptor_after_route_validation(api_factory, monkeypatch):
    api = api_factory()
    job, artifact, path = completed_artifact(api, proof=True)
    import apps.platform.artifact_response as module
    original = module.anyio.open_file
    async def replaced_before_open(*args, **kwargs):
        if Path(args[0]) == path:
            replace_same_size(path)
        return await original(*args, **kwargs)
    monkeypatch.setattr(module.anyio, 'open_file', replaced_before_open)
    response = api[0].get(url(job, artifact), headers={'Range': 'bytes=0-3'})
    assert response.status_code == 409 and 'ARTIFACT_CHANGED' in response.text
    assert b'BBBB' not in response.content


@pytest.mark.parametrize('range_header,expected', [('bytes=3-6',206),('bytes=0-1,4-5',206),('bytes=999-',416),('not-bytes',400)])
def test_verified_download_preserves_range_behavior(api_factory, range_header, expected):
    api = api_factory()
    job, artifact, _ = completed_artifact(api, b'0123456789', proof=True)
    response = api[0].get(url(job, artifact), headers={'Range': range_header})
    assert response.status_code == expected, response.text
    if expected==206:
        assert response.headers['cache-control']=='no-store'
    if range_header == 'bytes=3-6':
        assert response.content == b'3456' and response.headers['content-range'] == 'bytes 3-6/10'
    if ',' in range_header:
        assert b'01' in response.content and b'45' in response.content
        assert len(response.content) == int(response.headers['content-length'])


@pytest.mark.parametrize('outcome', ['succeeded','failed','changed','cancelled'])
def test_worker_alone_publishes_proofs_in_success_transaction(api_factory, monkeypatch, outcome):
    api = api_factory()
    _, app, asset, _, root = api
    def handler(context, exchange):
        path = exchange / 'frame.jpg'
        path.write_bytes(b'worker verified fixture')
        artifact = worker._artifact(path, context, 'source_frame')
        if outcome == 'changed':
            replace_same_size(path)
        if outcome == 'cancelled':
            context.queue.request_cancel(context.job['job_id'])
        return {'status': 'failed' if outcome == 'failed' else 'succeeded', 'artifacts': [artifact], 'events': [],
                'artifact_identities': {'forged': {'identity': []}}, 'error': {'code': 'fixture'} if outcome == 'failed' else None}
    monkeypatch.setattr('packages.runtime.media_proxy.exact_frame', handler)
    queued = app.state.queue.enqueue('exact_frame', {'asset': asset})
    result = worker.run_once(app.state.queue, root, lease_seconds=120)
    with app.state.queue.connection() as db:
        rows = db.execute('SELECT * FROM artifact_identities WHERE job_id=?', (queued['job_id'],)).fetchall()
    if outcome == 'succeeded':
        assert result['status'] == 'succeeded' and len(rows) == 1, result
        artifact = result['result']['artifacts'][0]
        proof = app.state.queue.artifact_identity(result['job_id'], result['attempt'], artifact['artifact_id'])
        check_proof(root / artifact['relative_path'], proof)
        assert api[0].get(url(result, artifact)).status_code == 200
    else:
        assert result['status'] != 'succeeded' and rows == [], result


def test_hash_keeps_independent_path_and_descriptor_ctime_proofs(tmp_path, monkeypatch):
    path = tmp_path / 'modified.fixture'
    path.write_bytes(b'A')
    original = os.fstat
    def different_ctime(fd):
        actual = original(fd)
        fields = ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
        return SimpleNamespace(**{name:getattr(actual,name)+(123 if name=='st_ctime_ns' else 0) for name in fields})
    monkeypatch.setattr(os,'fstat',different_ctime)
    proof = hash_identity(path)
    assert proof['identity'][:4] == proof['descriptor_identity'][:4]
    assert proof['identity'][4] != proof['descriptor_identity'][4]
    check_proof(path, proof)


def test_changed_during_hash_cannot_publish_a_new_stat_under_old_digest(tmp_path):
    path = tmp_path / 'mutable.fixture'
    path.write_bytes(b'A' * 32)
    def mutate():
        rewrite_same_size(path)
    with pytest.raises(ArtifactIdentityError, match='ARTIFACT_CHANGED'):
        hash_identity(path, check=mutate)


def test_worker_preview_index_hash_runs_after_connection_close(tmp_path, monkeypatch):
    from packages.runtime import media_proxy
    path = tmp_path / 'index.sqlite3'
    with media_proxy._connect(path) as db:
        db.execute('CREATE TABLE fixture(value INTEGER)')
        db.execute('INSERT INTO fixture VALUES(1)')
    import sqlite3
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        db.execute('SELECT * FROM fixture')
    context = SimpleNamespace(storage_root=tmp_path, check=lambda:None)
    artifact = media_proxy._artifact(path,context,'frame_index')
    check_proof(path,context.artifact_identities[artifact['artifact_id']])


@pytest.mark.parametrize('proof',[False,True])
def test_in_place_same_size_same_mtime_rewrite_is_rejected(api_factory,proof):
    api=api_factory()
    job,artifact,path=completed_artifact(api,proof=proof)
    rewrite_same_size(path)
    publish_registry(api[4],hashlib.sha256(path.read_bytes()).hexdigest())
    response=api[0].get(url(job,artifact))
    assert response.status_code in (409,422) and b'B'*64 not in response.content,response.text


@pytest.mark.parametrize('range_header',[None,'bytes=3-6','bytes=0-1,4-5'])
def test_head_keeps_proven_size_range_headers_and_no_store(api_factory,range_header):
    api=api_factory()
    job,artifact,_=completed_artifact(api,b'0123456789',proof=True)
    response=api[0].head(url(job,artifact),headers={'Range':range_header} if range_header else {})
    assert response.status_code==(206 if range_header else 200) and response.content==b''
    assert response.headers['cache-control']=='no-store' and int(response.headers['content-length'])>0


def test_legacy_upgrade_never_replaces_hash_time_identity_with_later_stat(api_factory,monkeypatch):
    api=api_factory()
    job,artifact,path=completed_artifact(api)
    queue=api[1].state.queue
    original=queue.remember_legacy_artifact_identity
    def replace_before_store(*args):
        replace_same_size(path)
        return original(*args)
    monkeypatch.setattr(queue,'remember_legacy_artifact_identity',replace_before_store)
    response=api[0].get(url(job,artifact))
    assert response.status_code==409 and 'ARTIFACT_CHANGED' in response.text
    proof=queue.artifact_identity(job['job_id'],job['attempt'],artifact['artifact_id'])
    assert proof['sha256']==artifact['sha256']
    with pytest.raises(ArtifactIdentityError):
        check_proof(path,proof)
