"""Engineering fixtures only: never evidence of real video or human truth."""
import copy
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault('BTV_STORAGE_ROOT', tempfile.mkdtemp(prefix='btv-training-import-'))
from apps.platform.main import create_app
from apps.platform.training_catalog import TrainingCatalog
from packages.runtime.artifact_identity import check_proof, hash_identity
from packages.contracts.training import TrainingSnapshot


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('BTV_TRAINING_ACTOR_TYPE', 'agent')
    monkeypatch.delenv('BTV_TRAINING_TAXONOMY', raising=False)
    root = tmp_path / 'video'
    path = root / 'data/training/fixture.mp4'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'engineering-fixture-not-a-video')
    proof = hash_identity(path)
    asset = {'schema_version': '1.0', 'asset_id': 'training-a', 'relative_path': 'data/training/fixture.mp4',
             'sha256': proof['sha256'], 'size_bytes': proof['size_bytes'], 'duration_ms': 10000,
             'title': '工程夹具', 'width': 100, 'height': 100, 'usage_scope': 'training_only',
             'match_id': 'unknown-match', 'provenance': {}, 'probe': {}}
    registry = root / 'data/training/handoff/training-registry.v1.json'
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({'schema_version': '1.0', 'assets': [asset]}), encoding='utf-8')
    def listing(self, offset=0, limit=100):
        return {'assets': [asset][offset:offset+limit], 'catalog_revision': 'fixture-v1', 'total': 1}
    def verify(self, asset_id, **kwargs):
        assert asset_id == asset['asset_id']
        return {'asset': copy.deepcopy(asset), 'identity_proof': proof}
    def validate(self, record):
        check_proof(path, record['identity_proof'])
        return path
    monkeypatch.setattr(TrainingCatalog, 'list_catalog', listing)
    def get_asset(self, asset_id):
        if asset_id != asset['asset_id']:
            raise ValueError('not catalogued')
        return copy.deepcopy(asset)
    monkeypatch.setattr(TrainingCatalog, 'get_asset', get_asset)
    monkeypatch.setattr(TrainingCatalog, 'verify_asset', verify)
    monkeypatch.setattr(TrainingCatalog, 'validate_registered', validate)
    app = create_app(root, root / 'platform/state.sqlite3')
    with TestClient(app) as client:
        response = client.post('/api/v1/training/registrations', json={'asset_id': 'training-a'})
        assert response.status_code == 202, response.text
        task = response.json()
        for _ in range(200):
            task = client.get('/api/v1/training/registrations/' + task['registration_id']).json()
            if task['status'] in ('ready', 'failed'):
                break
            time.sleep(.01)
        assert task['status'] == 'ready', task
        project = client.post('/api/v1/training/projects', json={'name': '工程验收'}).json()
        pid = project['project_id']
        r = client.post(f'/api/v1/training/projects/{pid}/assets', json={'asset_id': 'training-a', 'expected_revision': project['revision']})
        assert r.status_code == 200, r.text
        yield client, app, pid, path


def bundle_url(pid):
    return f'/api/v1/training/projects/{pid}/bundles/training-a'


def seed(client, pid):
    b = client.get(bundle_url(pid)).json()
    base = {'project_id': pid, 'asset_id': 'training-a', 'visibility': 'partial', 'review': {'status': 'pending'}}
    b['people'] = [{'person_id': 'near', 'display_name': '近端球员', 'team_id': 'a', 'identity_status': 'unconfirmed'},
                   {'person_id': 'far', 'display_name': '远端球员', 'team_id': 'b', 'identity_status': 'unconfirmed'}]
    b['records'] = [
        {**base, 'record_id': 'rally', 'kind': 'rally', 'start_ms': 1000, 'end_ms': 5000, 'dead_ball_id': 'dead'},
        {**base, 'record_id': 'dead', 'kind': 'dead_ball', 'at_ms': 5000, 'rally_id': 'rally'},
        {**base, 'record_id': 'contact-1', 'kind': 'contact', 'at_ms': 2000, 'person_id': 'near', 'team_id': 'a', 'rally_id': 'rally'},
        {**base, 'record_id': 'contact-2', 'kind': 'contact', 'at_ms': 3500, 'person_id': 'far', 'team_id': 'b', 'rally_id': 'rally'},
        {**base, 'record_id': 'action', 'kind': 'segment', 'segment_type': 'stroke', 'start_ms': 1500, 'end_ms': 2500, 'rally_id': 'rally', 'person_id': 'near',
         'state': {'self': {'person_id': 'near', 'position': {'coordinate_system': 'image_normalized', 'x': .3, 'y': .8, 'source': 'agent'}},
                   'opponent': {'person_id': 'far', 'position': {'coordinate_system': 'image_normalized', 'x': .6, 'y': .2, 'source': 'agent'}},
                   'incoming_ball': 'unknown', 'missing_reasons': ['工程测试，无视频标签真值']}}]
    return b


def save(client, pid, b, expected=0):
    return client.put(bundle_url(pid), json={'bundle': b, 'expected_revision': expected})


def test_cas_history_snapshot_frozen_and_restart(workspace):
    c, app, pid, _ = workspace
    r = save(c, pid, seed(c, pid))
    assert r.status_code == 200, r.text
    first = r.json()
    assert first['revision'] == 1
    stale = copy.deepcopy(first)
    modified = copy.deepcopy(first)
    modified['records'][2]['at_ms'] = 2100
    r = save(c, pid, modified, 1)
    assert r.status_code == 200, r.text
    assert r.json()['records'][2]['revision'] == 2
    assert save(c, pid, stale, 1).status_code == 409
    assert c.get(bundle_url(pid), params={'revision': 1}).json() == first
    detail = c.get(f'/api/v1/training/projects/{pid}').json()
    snap = c.post(f'/api/v1/training/projects/{pid}/snapshots', json={'expected_revision': detail['project']['revision']})
    assert snap.status_code == 201, snap.text
    frozen = snap.json()
    TrainingSnapshot.model_validate(frozen)
    assert frozen['training_view'] == []
    assert not frozen['quality_summary']['trainable']
    current = c.get(bundle_url(pid)).json()
    current['records'][2]['at_ms'] = 2200
    assert save(c, pid, current, 2).status_code == 200
    assert c.get('/api/v1/training/snapshots/' + frozen['snapshot_id']).json() == frozen
    for view in ('audit', 'training'):
        for fmt in ('json', 'jsonl'):
            download = c.get('/api/v1/training/snapshots/' + frozen['snapshot_id'] + '/download', params={'view': view, 'format': fmt})
            if view == 'training':
                assert download.status_code == 409
                assert not download.json()['detail']['quality_summary']['trainable']
                continue
            assert download.status_code == 200
            if fmt == 'jsonl':
                assert json.loads(download.text.splitlines()[0])['snapshot_id'] == frozen['snapshot_id']
    assert c.put('/api/v1/training/snapshots/' + frozen['snapshot_id'], json=frozen).status_code == 405
    restarted = create_app(app.state.storage_root, app.state.store.path)
    with TestClient(restarted) as other:
        assert other.get(bundle_url(pid)).json()['revision'] == 3
        assert other.get('/api/v1/training/snapshots/' + frozen['snapshot_id']).json() == frozen
        assert other.get('/api/v1/assets').json() == []
        assert other.get('/api/v1/events').json() == []


def test_agent_cannot_grant_human_truth_or_rewrite_asset(workspace):
    c, _, pid, _ = workspace
    b = seed(c, pid)
    b['records'][2]['review'] = {'status': 'confirmed', 'reviewer_type': 'human', 'reviewer': 'forged'}
    assert save(c, pid, b).status_code == 422
    b = seed(c, pid)
    b['asset']['relative_path'] = 'data/elsewhere.mp4'
    assert save(c, pid, b).status_code == 422
    assert c.get(bundle_url(pid)).json()['revision'] == 0


def test_invalid_labels_bounds_relation_and_court_coordinates(workspace):
    c, _, pid, _ = workspace
    changes = [lambda b: b['records'][2].update(at_ms=99999),
               lambda b: b['records'][2].update(rally_id='missing'),
               lambda b: b['records'][2].update(judgements=[{'label_id': 'invented-technique', 'value': 'present'}]),
               lambda b: b['records'][4]['state']['self']['position'].update(coordinate_system='court_m'),
               lambda b: b['records'][1].update(at_ms=4900)]
    for change in changes:
        b = seed(c, pid)
        change(b)
        r = save(c, pid, b)
        assert r.status_code == 422, r.text


def test_media_is_pinned_registered_readonly_and_production_isolation(workspace):
    c, app, pid, path = workspace
    base = '/api/v1/training/assets/training-a/media'
    r = c.get(base, headers={'Range': 'bytes=0-4'})
    assert r.status_code == 206 and r.content == path.read_bytes()[:5]
    assert c.get('/api/v1/training/assets/unregistered/media').status_code == 404
    assert c.get('/api/v1/assets/training-a/media').status_code == 404
    assert c.post('/api/v1/training/registrations', json={'asset_id': 'training-a', 'allow_training': True, 'path': 'C:/secret'}).status_code == 422
    assert c.post('/api/v1/training/registrations', json={'asset_id': 'missing'}).status_code == 422
    assert c.get('/api/v1/assets').json() == []
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM assets').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0
    path.write_bytes(b'changed source bytes')
    assert c.get(base).status_code == 409


def test_unknown_group_cannot_be_assigned_and_stale_project_rejected(workspace):
    c, _, pid, _ = workspace
    detail = c.get(f'/api/v1/training/projects/{pid}').json()
    rev = detail['project']['revision']
    r = c.put(f'/api/v1/training/projects/{pid}/splits', json={'expected_revision': rev, 'splits': [{'group_id': 'unknown-match', 'split': 'train'}]})
    assert r.status_code == 422, r.text
    assert c.post(f'/api/v1/training/projects/{pid}/snapshots', json={'expected_revision': 0}).status_code == 409
    assert c.get(f'/api/v1/training/projects/{pid}').json()['project']['revision'] == rev


def test_training_and_guide_navigation(workspace):
    c, _, _, _ = workspace
    assert c.get('/training').status_code == 200
    assert '训练标注工作台' in c.get('/').text
    response = c.get('/guide', follow_redirects=False)
    assert response.status_code == 307 and response.headers['location'] == '/guide/'
    response = c.get('/guide/')
    assert response.status_code in (200, 503)
    assert c.get('/guide/%2e%2e/%2e%2e/pyproject.toml').status_code != 200
