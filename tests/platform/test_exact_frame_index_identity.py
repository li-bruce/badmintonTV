"""Queue/dependency boundary tests; synthetic JPEG bytes do not test decoding."""
import hashlib
import os
from pathlib import Path

import pytest

from test_preview_api import api_factory, publish_registry
from packages.runtime import media_proxy, worker
from packages.runtime.artifact_identity import hash_identity


def bound_preview(api, *, proof=True, large=False):
    client, app, asset, _, root = api
    response = client.post('/api/v1/assets/asset-a/preview', json={'start_ms': 0, 'end_ms': 3000})
    assert response.status_code == 202, response.text
    job = app.state.queue.claim('index-fixture', lease_seconds=120)
    directory = root / 'platform/jobs' / job['job_id'] / f"attempt-{job['attempt']}"
    directory.mkdir(parents=True)
    index = directory / 'frame-index.sqlite3'
    with media_proxy._connect(index) as db:
        db.executescript('''
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE source_frames(source_frame_index INTEGER PRIMARY KEY,source_pts INTEGER,
                source_pts_ms REAL,source_end_ms REAL,key_frame INTEGER);
            CREATE TABLE proxy_frames(proxy_frame_index INTEGER PRIMARY KEY,proxy_pts_ms REAL,
                source_frame_index INTEGER,source_pts INTEGER,source_pts_ms REAL,coverage_start_ms REAL,coverage_end_ms REAL);
            INSERT INTO source_frames VALUES(0,0,0,1000,1),(1,1000,1000,2000,0),(2,2000,2000,3000,0);
            INSERT INTO proxy_frames VALUES(0,0,0,0,0,0,1000),(1,1000,1,1000,1000,1000,2000),(2,2000,2,2000,2000,2000,3000);
        ''')
        media_proxy._set_metadata(db, {'source_asset_id': asset['asset_id'], 'source_sha256': asset['sha256'],
                                      'source_time_base': '1/1000', 'source_width': 640, 'source_height': 360})
    if large:
        with index.open('ab') as stream:
            stream.truncate(8_000_001)
    (directory / 'preview.mp4').write_bytes(b'explicit-nonvideo-fixture')
    (directory / 'thumbnails.jpg').write_bytes(b'explicit-nonimage-fixture')
    prefix = directory.relative_to(root).as_posix()
    preview = {'source_asset_id': asset['asset_id'], 'source_sha256': asset['sha256'], 'usage_scope': 'general',
               'source_frame_count': 3, 'proxy_frame_count': 3, 'source_index_scope': 'full_source',
               'window_start_ms': 0, 'window_end_ms': 3000, 'relative_path': prefix + '/preview.mp4',
               'index_relative_path': prefix + '/frame-index.sqlite3', 'thumbnail_relative_path': prefix + '/thumbnails.jpg'}
    artifacts, proofs = [], {}
    for name, kind in (('preview.mp4', 'preview'), ('frame-index.sqlite3', 'frame_index'), ('thumbnails.jpg', 'thumbnail')):
        identity = {**hash_identity(directory / name), 'relative_path': prefix + '/' + name}
        artifact = {'artifact_id': kind, 'kind': kind, **{key: identity[key] for key in ('relative_path', 'sha256', 'size_bytes')}}
        artifacts.append(artifact)
        proofs[kind] = identity
    app.state.queue.finish(job['job_id'], 'index-fixture', 'succeeded', result={'preview': preview, 'artifacts': artifacts},
                           artifact_identities=proofs if proof else None)
    return app.state.queue.get(job['job_id']), index


def enqueue_exact(api, preview, *, via_api=True, changes=None):
    if via_api:
        response = api[0].post('/api/v1/assets/asset-a/source-frame', json={'preview_job_id': preview['job_id'], 'source_frame_index': 1})
        assert response.status_code == 202, response.text
        return response.json()
    payload = {'asset': api[2], 'preview_job_id': preview['job_id'], 'source_frame_index': 1,
               'index_relative_path': preview['result']['preview']['index_relative_path'], **(changes or {})}
    return api[1].state.queue.enqueue('exact_frame', payload)


def run_exact(api, monkeypatch, *, during_decode=None, expect_decode=False):
    calls = []
    def decode(context, argv, *args, **kwargs):
        assert expect_decode, 'untrusted index reached the decoder'
        calls.append(argv)
        if during_decode:
            during_decode()
        Path(argv[-1]).write_bytes(b'fake-jpeg-boundary-fixture')
    monkeypatch.setattr(media_proxy, '_run', decode)
    monkeypatch.setattr(media_proxy, '_binary', lambda name: name)
    result = worker.run_once(api[1].state.queue, api[4], lease_seconds=120)
    assert bool(calls) == expect_decode, result
    return result


def assert_failed_without_proof(api, result, message):
    assert result['status'] == 'failed' and message in result['error']['message'], result
    with api[1].state.queue.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM artifact_identities WHERE job_id=?', (result['job_id'],)).fetchone()[0] == 0


@pytest.mark.parametrize('sql', [
    'UPDATE source_frames SET source_pts=1001,source_pts_ms=1001 WHERE source_frame_index=1',
    '''UPDATE metadata SET value='"1/1001"' WHERE key='source_time_base' ''',
])
def test_queued_exact_rejects_changed_index_pts_or_timebase(api_factory, monkeypatch, sql):
    api = api_factory()
    preview, index = bound_preview(api)
    enqueue_exact(api, preview)
    before = index.stat()
    with media_proxy._connect(index) as db:
        db.execute(sql)
    os.utime(index, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert index.stat().st_size == before.st_size
    result = run_exact(api, monkeypatch)
    assert_failed_without_proof(api, result, 'ARTIFACT_CHANGED')


def test_queued_exact_rejects_same_size_index_replacement(api_factory, monkeypatch):
    api = api_factory()
    preview, index = bound_preview(api)
    enqueue_exact(api, preview)
    before = index.stat()
    replacement = index.with_suffix('.replacement')
    replacement.write_bytes(index.read_bytes())
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, index)
    assert_failed_without_proof(api, run_exact(api, monkeypatch), 'ARTIFACT_CHANGED')


@pytest.mark.parametrize('proof', [False, True])
def test_unchanged_bound_index_publishes_true_pts_and_image_proof(api_factory, monkeypatch, proof):
    api = api_factory()
    preview, _ = bound_preview(api, proof=proof)
    # Legacy queued jobs have not visited the newer API's proof-upgrade path.
    enqueue_exact(api, preview, via_api=proof)
    result = run_exact(api, monkeypatch, expect_decode=True)
    assert result['status'] == 'succeeded', result
    frame = result['result']['frame']
    assert (frame['source_frame_index'], frame['source_pts'], frame['source_pts_ms'], frame['source_time_base']) == (1, 1000, 1000, '1/1000')
    artifact = result['result']['artifacts'][0]
    queue = api[1].state.queue
    assert queue.artifact_identity(result['job_id'], result['attempt'], artifact['artifact_id'])
    assert queue.artifact_identity(preview['job_id'], preview['attempt'], 'frame_index')


def test_legacy_large_index_rejects_before_hash_or_decode(api_factory, monkeypatch):
    api = api_factory()
    preview, index = bound_preview(api, proof=False, large=True)
    enqueue_exact(api, preview, via_api=False)
    original = Path.open
    def no_index_reads(path, *args, **kwargs):
        assert path != index, 'large unproven index must not be opened for hashing'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_index_reads)
    assert_failed_without_proof(api, run_exact(api, monkeypatch), 'ARTIFACT_REVERIFY_REQUIRED')


@pytest.mark.parametrize('changes,reason', [
    ({'preview_job_id': None}, 'ARTIFACT_REVERIFY_REQUIRED'),
    ({'preview_job_id': 'missing-preview'}, 'ARTIFACT_CHANGED'),
    ({'index_relative_path': 'platform/jobs/foreign/attempt-1/frame-index.sqlite3'}, 'ARTIFACT_CHANGED'),
])
def test_exact_requires_trusted_preview_binding(api_factory, monkeypatch, changes, reason):
    api = api_factory()
    preview, _ = bound_preview(api)
    enqueue_exact(api, preview, via_api=False, changes=changes)
    assert_failed_without_proof(api, run_exact(api, monkeypatch), reason)


def test_index_changed_during_decode_cannot_publish_result(api_factory, monkeypatch):
    api = api_factory()
    preview, index = bound_preview(api)
    enqueue_exact(api, preview)
    def mutate():
        with media_proxy._connect(index) as db:
            db.execute('UPDATE source_frames SET source_pts=1001 WHERE source_frame_index=1')
    result = run_exact(api, monkeypatch, during_decode=mutate, expect_decode=True)
    assert_failed_without_proof(api, result, 'ARTIFACT_CHANGED')


def test_legacy_index_checks_actual_training_digest_before_declared_mismatch(api_factory, monkeypatch):
    api = api_factory()
    preview, index = bound_preview(api, proof=False)
    enqueue_exact(api, preview, via_api=False)
    with media_proxy._connect(index) as db:
        db.execute('UPDATE source_frames SET source_pts=1001 WHERE source_frame_index=1')
    publish_registry(api[4], hashlib.sha256(index.read_bytes()).hexdigest())
    result = run_exact(api, monkeypatch)
    assert result['status'] == 'blocked' and result['error']['code'] == 'TRAINING_ONLY', result
    assert api[1].state.queue.artifact_identity(preview['job_id'], preview['attempt'], 'frame_index') is None
