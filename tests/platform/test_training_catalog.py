"""A-02 catalog security/PTS tests; bytes are explicit fixtures, not video QA."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from apps.platform.training_catalog import (
    CATALOG_PATH, LEGACY_MANIFEST_PATH, REGISTRY_PATH,
    TrainingCatalog, TrainingCatalogError,
)
from packages.runtime.artifact_identity import check_proof


def write_json(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def asset_fixture(root, name='one', pts=(100, 140, 200), duration=130):
    source = root / f'data/training/dataset/{name}.mp4'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'explicit non-media fixture ' + name.encode())
    index = source.with_suffix('.pts.jsonl')
    index.write_bytes(b''.join(json.dumps({'frame_index': i, 'pts': p}).encode() + b'\n' for i, p in enumerate(pts)))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return {'schema_version': '1.0', 'asset_id': 'asset-' + name,
            'relative_path': source.relative_to(root).as_posix(), 'sha256': digest,
            'size_bytes': source.stat().st_size, 'duration_ms': duration, 'width': 1280, 'height': 720,
            'time_base': '1/1000', 'match_id': 'unconfirmed-publisher-group', 'source_type': 'dataset',
            'usage_scope': 'training_only', 'title': 'Explicit metadata fixture',
            'players': [{'player_id': 'publisher-player', 'display_name': 'Unconfirmed', 'identity_status': 'unconfirmed'}],
            'provenance': {'usage_scope': 'training_only', 'dataset_id': 'test-dataset', 'identity_basis': 'publisher filename only'},
            'probe': {'source_sha256': digest, 'source_size_bytes': source.stat().st_size,
                      'pts_index': {'relative_path': index.relative_to(root).as_posix(),
                                    'sha256': hashlib.sha256(index.read_bytes()).hexdigest(), 'size_bytes': index.stat().st_size,
                                    'format': 'jsonl', 'complete': True, 'frame_count': len(pts), 'time_base': '1/1000'}}}


def publish(root, assets, *, newer=False):
    manifest = {'schema_version': '1.0', 'assets': assets}
    registry = {'schema_version': '1.0', 'assets': [
        {key: a[key] for key in ('asset_id', 'relative_path', 'sha256', 'size_bytes', 'usage_scope', 'match_id', 'provenance')}
        for a in assets]}
    write_json(root, CATALOG_PATH if newer else LEGACY_MANIFEST_PATH, manifest)
    write_json(root, REGISTRY_PATH, registry)


def publish_annotation_catalog(root, assets, *, modify_entry=None):
    entries = []
    for asset in assets:
        entry = {'asset_id': asset['asset_id'], 'source_asset': copy.deepcopy(asset),
                 'usage_scope': 'training_only', 'original_pts': asset['probe']['pts_index'],
                 'match_group': {'status': 'unconfirmed', 'confirmed_group_id': None,
                                 'publisher_match_id': asset['match_id'], 'source_sha256': asset['sha256'],
                                 'split': 'unassigned', 'independent_match_confirmed': False},
                 'training_truth_eligible': False, 'blockers': ['unverified_fixture_annotations']}
        if modify_entry:
            modify_entry(entry)
        entries.append(entry)
    details = {'schema_version': 'library.annotation-catalog/1', 'usage_scope': 'training_only', 'assets': entries}
    raw = json.dumps(details).encode()
    digest = hashlib.sha256(raw).hexdigest()
    relative = f'data/training/handoff/annotation-catalog/{digest}.details.json'
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    published = copy.deepcopy(assets)
    for item in published:
        item['provenance']['annotation_catalog'] = {'schema_version': 'library.annotation-catalog/1',
            'relative_path': relative, 'sha256': digest, 'size_bytes': len(raw)}
    publish(root, published, newer=True)
    # The actual library registry remains the original acquisition snapshot.
    registry = json.loads((root / REGISTRY_PATH).read_text())
    for item in registry['assets']:
        item['provenance'].pop('annotation_catalog', None)
    write_json(root, REGISTRY_PATH, registry)
    return path


@pytest.fixture
def catalog(tmp_path):
    asset = asset_fixture(tmp_path)
    publish(tmp_path, [asset])
    return TrainingCatalog(tmp_path), tmp_path, asset


def test_catalog_listing_reads_only_trusted_metadata(catalog, monkeypatch):
    helper, root, asset = catalog
    original = Path.open

    def controlled(path, *args, **kwargs):
        assert path.suffix not in ('.mp4', '.jsonl'), 'listing must not hash/read source or PTS'
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', controlled)
    listing = helper.list_catalog()
    assert listing['total'] == 1 and listing['assets'][0]['asset_id'] == asset['asset_id']
    assert listing['assets'][0]['players'][0]['identity_status'] == 'unconfirmed'
    assert listing['usage_scope'] == 'training_only'


def test_asset_lookup_is_not_limited_to_first_catalog_page(catalog):
    helper, root, asset = catalog
    entries = [{**copy.deepcopy(asset), 'asset_id': f'asset-{number:03d}'} for number in range(105)]
    publish(root, entries)
    assert len(helper.list_catalog()['assets']) == 100
    assert helper.get_asset('asset-104')['asset_id'] == 'asset-104'
    with pytest.raises(TrainingCatalogError, match='TRAINING_ASSET_UNKNOWN'):
        helper.get_asset('asset-999')


def test_registered_proofs_support_native_descriptor_response_and_real_pts(catalog):
    helper, root, asset = catalog
    progress = []
    record = helper.verify_asset(asset['asset_id'], progress=progress.append)
    assert record['usage_scope'] == record['asset']['usage_scope'] == 'training_only'
    assert record['asset']['provenance'] == asset['provenance']
    path = helper.validate_registered(record)
    assert path == (root / asset['relative_path']).resolve()
    check_proof(path, record['identity_proof'])
    assert len(record['identity_proof']['descriptor_identity']) == 5
    assert record['pts_proof']['first_pts'] == 100 and record['pts_proof']['last_pts'] == 200
    assert progress[0]['current'] == 0
    assert any(p['stage'] == 'source_hash' and p['current'] == asset['size_bytes'] for p in progress)
    assert progress[-1]['current'] == asset['probe']['pts_index']['size_bytes']
    page = helper.read_frames(record, at_ms=50, limit=2)
    assert page['offset_frame'] == 1 and page['total'] == 3
    assert page['source_frames'] == [
        {'source_frame_index': 1, 'source_pts': 140, 'source_pts_ms': 40.0, 'source_end_ms': 100.0},
        {'source_frame_index': 2, 'source_pts': 200, 'source_pts_ms': 100.0, 'source_end_ms': 130.0}]
    assert helper.read_frames(record, offset_frame=5)['source_frames'] == []


@pytest.mark.parametrize('asset_id', ['../outside', 'data/training/dataset/one.mp4', 'absent', None, {}])
def test_registration_accepts_only_listed_asset_id(catalog, asset_id):
    helper, _, _ = catalog
    with pytest.raises(TrainingCatalogError, match='TRAINING_ASSET_UNKNOWN'):
        helper.verify_asset(asset_id)


@pytest.mark.parametrize('change', ['size', 'same_size_bytes'])
def test_source_actual_bytes_must_match_catalog(catalog, change):
    helper, root, asset = catalog
    path = root / asset['relative_path']
    path.write_bytes(b'x' * (asset['size_bytes'] + (change == 'size')))
    with pytest.raises(TrainingCatalogError, match='TRAINING_SOURCE_CHANGED'):
        helper.verify_asset(asset['asset_id'])


@pytest.mark.parametrize('target', ['source', 'pts'])
def test_serving_rejects_mutated_file_even_size_and_mtime_restored(catalog, target):
    helper, root, asset = catalog
    record = helper.verify_asset(asset['asset_id'])
    path = root / (asset['relative_path'] if target == 'source' else asset['probe']['pts_index']['relative_path'])
    before = path.stat()
    replacement = path.with_suffix('.replacement')
    replacement.write_bytes(b'x' * before.st_size)
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, path)
    with pytest.raises(TrainingCatalogError, match='TRAINING_REGISTRATION_STALE'):
        helper.validate_registered(record)


def test_unrelated_catalog_publication_does_not_invalidate_registration(catalog):
    helper, root, asset = catalog
    record = helper.verify_asset(asset['asset_id'])
    previous_revision = record['catalog_proof']['catalog_revision']
    publish(root, [asset, asset_fixture(root, 'two')])
    assert helper.list_catalog()['catalog_revision'] != previous_revision
    assert helper.validate_registered(record).is_file()


@pytest.mark.parametrize('change', ['duration', 'provenance', 'registry_missing', 'record_source', 'record_proof'])
def test_corresponding_metadata_and_proof_changes_invalidate(catalog, change):
    helper, root, asset = catalog
    record = helper.verify_asset(asset['asset_id'])
    if change == 'duration':
        asset['duration_ms'] += 1
        publish(root, [asset])
    elif change == 'provenance':
        asset['provenance']['identity_basis'] = 'new audit note'
        publish(root, [asset])
    elif change == 'registry_missing':
        write_json(root, REGISTRY_PATH, {'schema_version': '1.0', 'assets': []})
    elif change == 'record_source':
        record['asset']['relative_path'] = 'data/private.mp4'
    else:
        record['identity_proof']['descriptor_identity'][0] += 1
    with pytest.raises(TrainingCatalogError):
        helper.validate_registered(record)


@pytest.mark.parametrize('change', ['outside', 'probe_hash', 'time_base', 'scope', 'registry_hash', 'registry_provenance'])
def test_manifest_binding_conflicts_are_not_registered(catalog, change):
    helper, root, asset = catalog
    if change == 'outside':
        asset['relative_path'] = 'data/general/source.mp4'
    elif change == 'probe_hash':
        asset['probe']['source_sha256'] = 'f' * 64
    elif change == 'time_base':
        asset['probe']['pts_index']['time_base'] = '1/999'
    elif change == 'scope':
        asset['usage_scope'] = 'general'
    publish(root, [asset])
    if change.startswith('registry_'):
        reg = json.loads((root / REGISTRY_PATH).read_text())
        if change == 'registry_hash':
            reg['assets'][0]['sha256'] = 'f' * 64
        else:
            reg['assets'][0]['provenance']['dataset_id'] = 'another-dataset'
        write_json(root, REGISTRY_PATH, reg)
    with pytest.raises(TrainingCatalogError):
        helper.verify_asset(asset['asset_id'])


@pytest.mark.parametrize('points,duration', [((0, 0, 40), 80), ((20, 10, 40), 80), ((0, 40, 80), 80)])
def test_actual_pts_order_and_duration_are_checked(tmp_path, points, duration):
    asset = asset_fixture(tmp_path, pts=points, duration=duration)
    publish(tmp_path, [asset])
    with pytest.raises(TrainingCatalogError, match='TRAINING_PTS_INVALID'):
        TrainingCatalog(tmp_path).verify_asset(asset['asset_id'])


@pytest.mark.parametrize('mutation', ['hash', 'frame_count', 'ordinal'])
def test_pts_reference_and_content_are_verified(catalog, mutation):
    helper, root, asset = catalog
    ref = asset['probe']['pts_index']
    if mutation == 'hash':
        ref['sha256'] = 'f' * 64
    elif mutation == 'frame_count':
        ref['frame_count'] += 1
    else:
        path = root / ref['relative_path']
        path.write_bytes(path.read_bytes().replace(b'"frame_index": 1', b'"frame_index": 9'))
        ref['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    publish(root, [asset])
    with pytest.raises(TrainingCatalogError, match='TRAINING_PTS_'):
        helper.verify_asset(asset['asset_id'])


@pytest.mark.parametrize('kwargs', [{'at_ms': float('nan')}, {'at_ms': float('inf')}, {'at_ms': -1},
                                    {'at_ms': 130}, {'limit': 1001}, {'limit': 0}, {'offset_frame': -1}])
def test_page_bounds_fail_explicitly(catalog, kwargs):
    helper, _, asset = catalog
    record = helper.verify_asset(asset['asset_id'])
    with pytest.raises(TrainingCatalogError):
        helper.read_frames(record, **kwargs)


def test_cancel_check_stops_hash_without_returning_a_registration(catalog):
    helper, _, asset = catalog
    class Cancelled(RuntimeError):
        pass
    def check():
        raise Cancelled('explicit fixture cancellation')
    with pytest.raises(Cancelled):
        helper.verify_asset(asset['asset_id'], check=check)


def test_metadata_changed_while_hashing_rejected(catalog):
    helper, root, asset = catalog
    def progress(event):
        if event['stage'] == 'source_hash' and event['current']:
            asset['title'] = 'republished title'
            publish(root, [asset])
    with pytest.raises(TrainingCatalogError, match='TRAINING_REGISTRATION_STALE'):
        helper.verify_asset(asset['asset_id'], progress=progress)


def test_fixed_new_catalog_preferred_and_invalid_one_never_falls_back(catalog):
    helper, root, asset = catalog
    publish(root, [asset], newer=True)
    assert helper.list_catalog()['catalog_relative_path'] == CATALOG_PATH
    (root / CATALOG_PATH).write_text('{broken', encoding='utf-8')
    with pytest.raises(TrainingCatalogError, match='TRAINING_CATALOG_INVALID'):
        helper.list_catalog()


def test_actual_library_sidecar_shape_and_unrelated_publication(catalog):
    helper, root, asset = catalog
    publish_annotation_catalog(root, [asset])
    listing = helper.list_catalog()
    details = listing['annotation_details'][asset['asset_id']]
    assert details['match_group']['status'] == 'unconfirmed'
    assert details['match_group']['independent_match_confirmed'] is False
    record = helper.verify_asset(asset['asset_id'])
    original_ref = record['asset']['provenance']['annotation_catalog']['sha256']
    publish_annotation_catalog(root, [asset, asset_fixture(root, 'two')])
    current = helper.list_catalog()['assets'][0]['provenance']['annotation_catalog']['sha256']
    assert current != original_ref
    assert helper.validate_registered(record).is_file()


@pytest.mark.parametrize('change', ['bytes', 'source_snapshot', 'group_source', 'truth'])
def test_sidecar_bytes_source_binding_and_unconfirmed_semantics_are_enforced(catalog, change):
    helper, root, asset = catalog
    def modify(entry):
        if change == 'source_snapshot':
            entry['source_asset']['duration_ms'] += 10
        elif change == 'group_source':
            entry['match_group']['source_sha256'] = 'f'*64
        elif change == 'truth':
            entry['training_truth_eligible'] = True
    path = publish_annotation_catalog(root, [asset], modify_entry=modify)
    if change == 'bytes':
        path.write_bytes(path.read_bytes().replace(b'unverified_fixture_annotations', b'changed___fixture_annotations'))
    with pytest.raises(TrainingCatalogError, match='TRAINING_CATALOG_INVALID'):
        helper.list_catalog()


def test_duplicate_json_keys_are_not_silently_accepted(catalog):
    helper, root, _ = catalog
    (root / REGISTRY_PATH).write_text('{"schema_version":"1.0","assets":[],"assets":[]}', encoding='utf-8')
    with pytest.raises(TrainingCatalogError, match='TRAINING_CATALOG_INVALID'):
        helper.list_catalog()


def test_symlink_source_rejected_even_inside_training_owner(catalog):
    helper, root, asset = catalog
    source = root / asset['relative_path']
    target = source.with_suffix('.real')
    source.rename(target)
    try:
        source.symlink_to(target)
    except OSError:
        target.rename(source)
        pytest.skip('native symlink creation permission unavailable')
    with pytest.raises(TrainingCatalogError, match='TRAINING_PATH_INVALID'):
        helper.verify_asset(asset['asset_id'])
