"""Independent review regressions: explicit engineering bytes, no media/GPU run."""
import copy
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

from test_training_api import workspace, seed, save, bundle_url
from apps.platform.main import create_app
from apps.platform.training_api import GuideFiles
from apps.platform.training_catalog import TrainingCatalog
from packages.contracts.training import TrainingSnapshot


def register_again(client, monkeypatch, verified):
    # The trusted verifier is replaced only for these explicit persistence/API
    # fixtures. Real catalog/hash verification is covered independently.
    monkeypatch.setattr(TrainingCatalog, 'verify_asset', lambda self, asset_id, **kwargs: copy.deepcopy(verified))
    response = client.post('/api/v1/training/registrations', json={'asset_id': verified['asset']['asset_id']})
    assert response.status_code == 202, response.text
    task = response.json()
    deadline = time.monotonic() + 3
    while task['status'] not in ('ready', 'failed') and time.monotonic() < deadline:
        task = client.get('/api/v1/training/registrations/' + task['registration_id']).json()
        if task['status'] not in ('ready', 'failed'):
            time.sleep(.01)
    assert task['status'] in ('ready', 'failed'), task
    return task


def snapshot(client, project_id):
    revision = client.get(f'/api/v1/training/projects/{project_id}').json()['project']['revision']
    response = client.post(f'/api/v1/training/projects/{project_id}/snapshots', json={'expected_revision': revision})
    assert response.status_code == 201, response.text
    TrainingSnapshot.model_validate(response.json())
    return response.json()


def test_repeat_registration_refreshes_metadata_without_stranding_saved_work(workspace, monkeypatch):
    client, app, project_id, _ = workspace
    first_response = save(client, project_id, seed(client, project_id))
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    before_snapshot = snapshot(client, project_id)
    original = app.state.training_store.registered('training-a')
    verified = copy.deepcopy(original)
    verified.pop('training_asset_ref', None)  # A fresh catalog verification never carries a store-frozen ref.
    verified['asset']['title'] = 'New trusted publisher title'
    verified['asset']['provenance']['new_audit_note'] = 'Metadata refresh, same source bytes and PTS'
    task = register_again(client, monkeypatch, verified)
    assert task['status'] == 'ready', task
    current = app.state.training_store.registered('training-a')
    assert current['asset']['title'] == 'New trusted publisher title'
    assert current['training_asset_ref'] == first['asset']
    assert current['asset']['provenance'] != original['asset']['provenance']
    assert client.get(bundle_url(project_id)).json() == first

    draft = copy.deepcopy(first)
    draft['records'][2]['at_ms'] = 2100
    saved = save(client, project_id, draft, 1)
    assert saved.status_code == 200, saved.text
    assert saved.json()['revision'] == 2 and saved.json()['asset'] == first['asset']
    after_snapshot = snapshot(client, project_id)
    assert after_snapshot['assets'][0] == first['asset']
    assert client.get('/api/v1/training/snapshots/' + before_snapshot['snapshot_id']).json() == before_snapshot
    assert client.get(bundle_url(project_id), params={'revision': 1}).json() == first


@pytest.mark.parametrize('field', ['sha256', 'relative_path', 'size_bytes', 'duration_ms', 'pts_reference'])
def test_source_critical_refresh_fails_without_replacing_old_proof_or_bundle(workspace, monkeypatch, field):
    client, app, project_id, path = workspace
    saved_response = save(client, project_id, seed(client, project_id))
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()
    original = app.state.training_store.registered('training-a')
    verified = copy.deepcopy(original)
    verified.pop('training_asset_ref', None)
    asset = verified['asset']
    if field == 'sha256':
        asset[field] = 'f' * 64
    elif field == 'relative_path':
        asset[field] = 'data/training/different-source.mp4'
    elif field in ('size_bytes', 'duration_ms'):
        asset[field] += 1
    else:
        asset['probe']['pts_index'] = {'relative_path': 'data/training/different.pts.jsonl',
                                      'sha256': 'e' * 64, 'frame_count': 2}
    # Distinct sentinel proves a failed refresh does not accidentally replace
    # the old proof while retaining only its source metadata.
    verified['identity_proof']['identity'][0] += 1
    task = register_again(client, monkeypatch, verified)
    assert task['status'] == 'failed' and task.get('error'), task
    assert app.state.training_store.registered('training-a') == original
    assert client.get(bundle_url(project_id)).json() == saved
    media = client.get('/api/v1/training/assets/training-a/media', headers={'Range': 'bytes=0-4'})
    assert media.status_code == 206 and media.content == path.read_bytes()[:5]


@pytest.mark.parametrize('layer', ['site', 'docs', 'repo'])
def test_guide_rejects_real_windows_junction_at_root_or_ancestor(tmp_path, layer):
    if os.name != 'nt':
        pytest.skip('Windows native junction regression')
    shell = shutil.which('powershell.exe')
    if not shell:
        pytest.skip('PowerShell is unavailable for native junction creation')
    base = tmp_path.resolve()
    repo, outside = base / 'repo', base / 'outside-guide-root'
    outside.mkdir()
    junction = {'site': repo / 'docs/site', 'docs': repo / 'docs', 'repo': repo}[layer]
    target_site = {'site': outside, 'docs': outside / 'site', 'repo': outside / 'docs/site'}[layer]
    target_site.mkdir(parents=True, exist_ok=True)
    (target_site / 'index.html').write_text('Explicit guide junction fixture', encoding='utf-8')
    secret = 'This fixture must not be served outside the configured guide root.'
    (target_site / 'private-fixture.txt').write_text(secret, encoding='utf-8')
    junction.parent.mkdir(parents=True, exist_ok=True)
    assert junction.absolute().is_relative_to(base) and outside.is_relative_to(base)
    quote = lambda value: str(value).replace("'", "''")
    created = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command',
        f"$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path '{quote(junction)}' -Target '{quote(outside)}' | Out-Null"],
        capture_output=True, text=True, timeout=15)
    if created.returncode:
        pytest.skip('Native junction creation permission/capability unavailable')
    try:
        app = Starlette(routes=[Mount('/guide', GuideFiles(directory=repo / 'docs/site', html=True, check_dir=False))])
        with TestClient(app) as client:
            response = client.get('/guide/private-fixture.txt')
        assert response.status_code in (403, 404, 503)
        assert secret not in response.text
    finally:
        # Remove only our junction itself, never recurse through its target.
        assert junction.absolute().is_relative_to(base)
        os.rmdir(junction)


def test_agent_cannot_store_new_position_with_human_source(workspace):
    client, _, project_id, _ = workspace
    draft = seed(client, project_id)
    draft['records'][4]['state']['self']['position']['source'] = 'human'
    response = save(client, project_id, draft)
    assert response.status_code == 422, response.text
    assert client.get(bundle_url(project_id)).json()['revision'] == 0


def test_unregistered_calibration_cannot_turn_clicks_into_court_metres(workspace):
    client, _, project_id, _ = workspace
    draft = seed(client, project_id)
    draft['records'][4]['state']['self']['position'].update(
        coordinate_system='court_m', calibration_id='never-registered-calibration', x=10000.0, y=10000.0)
    response = save(client, project_id, draft)
    assert response.status_code == 422, response.text
    assert client.get(bundle_url(project_id)).json()['revision'] == 0


@pytest.mark.parametrize('prior_status', ['queued', 'running'])
def test_startup_marks_interrupted_registration_failed_and_allows_explicit_retry(workspace, prior_status):
    _, app, _, _ = workspace
    old, created = app.state.training_store.begin_registration('training-a')
    assert created
    if prior_status == 'running':
        app.state.training_store.update_registration(old['registration_id'], status='running')
    restarted = create_app(app.state.storage_root, app.state.store.path)
    with TestClient(restarted) as client:
        recovered = client.get('/api/v1/training/registrations/' + old['registration_id']).json()
        assert recovered['status'] == 'failed' and recovered.get('error')
        response = client.post('/api/v1/training/registrations', json={'asset_id': 'training-a'})
        assert response.status_code == 202, response.text
        retry = response.json()
        assert retry['registration_id'] != old['registration_id']
        deadline = time.monotonic() + 3
        while retry['status'] not in ('ready', 'failed') and time.monotonic() < deadline:
            retry = client.get('/api/v1/training/registrations/' + retry['registration_id']).json()
            if retry['status'] not in ('ready', 'failed'):
                time.sleep(.01)
        assert retry['status'] == 'ready', retry
        assert client.get('/api/v1/training/registrations/' + old['registration_id']).json()['status'] == 'failed'
