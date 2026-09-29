import hashlib
import json
import tracemalloc
from pathlib import Path

import pytest

from apps.platform.frame_index import read_label_studio_frame_map, read_source_frame_page


def fixture_index(tmp_path, pts=(90000, 92999, 99000), *, duration=200, declared=True):
    path = tmp_path / 'index.jsonl'
    with path.open('wb') as stream:
        for number, value in enumerate(pts):
            stream.write((json.dumps({'frame_index': number, 'pts': value}) + '\n').encode())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    index = {'relative_path': 'index.jsonl', 'complete': True, 'format': 'jsonl', 'sha256': digest, 'time_base': '1/90000'}
    if declared:
        index['frame_count'] = len(pts)
    asset = {'time_base': '1/90000', 'duration_ms': duration, 'probe': {'pts_index': index}}
    return asset, path, digest


def test_short_map_keeps_old_shape_digest_pts_and_floor_boundaries(tmp_path):
    asset, _, digest = fixture_index(tmp_path)
    assert read_label_studio_frame_map(asset, tmp_path) == {
        'mapping_id': 'pts-' + digest[:20], 'source_duration_ms': 200,
        'frames': [
            {'ls_frame': 1, 'source_start_ms': 0, 'source_end_ms': 33, 'source_pts': 90000},
            {'ls_frame': 2, 'source_start_ms': 33, 'source_end_ms': 100, 'source_pts': 92999},
            {'ls_frame': 3, 'source_start_ms': 100, 'source_end_ms': 200, 'source_pts': 99000},
        ]}


def test_page_lookahead_retains_vfr_end_even_outside_requested_page(tmp_path):
    asset, _, _ = fixture_index(tmp_path)
    page = read_source_frame_page(asset, tmp_path, offset_frame=1, limit=1)
    assert page['total'] == 3 and page['offset_frame'] == 1
    assert len(page['source_frames']) == 1
    frame = page['source_frames'][0]
    assert frame['source_frame_index'] == 1
    assert frame['source_pts_ms'] == pytest.approx(2999 / 90)
    assert frame['source_end_ms'] == 100


@pytest.mark.parametrize('target,expected', [(0, 0), (33.33, 1), (99.99, 1), (100, 2), (200, 2), (999, 2)])
def test_at_ms_selects_containing_frame_and_clamps_after_end(tmp_path, target, expected):
    asset, _, _ = fixture_index(tmp_path)
    page = read_source_frame_page(asset, tmp_path, offset_frame=99, at_ms=target, limit=1)
    assert page['offset_frame'] == expected
    assert page['source_frames'][0]['source_frame_index'] == expected


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': 1001}, {'offset_frame': -1}, {'limit': True}, {'at_ms': float('nan')}, {'at_ms': -1}])
def test_invalid_pagination_is_rejected(tmp_path, kwargs):
    asset, _, _ = fixture_index(tmp_path)
    with pytest.raises(ValueError):
        read_source_frame_page(asset, tmp_path, **kwargs)


def test_offset_after_eof_is_empty_but_count_and_hash_verified(tmp_path):
    asset, _, digest = fixture_index(tmp_path)
    page = read_source_frame_page(asset, tmp_path, offset_frame=20, limit=2)
    assert page['source_frames'] == [] and page['total'] == 3
    assert page['mapping_id'] == 'pts-' + digest[:20]


def test_long_page_uses_bounded_memory_and_no_whole_file_read(tmp_path, monkeypatch):
    asset, _, _ = fixture_index(tmp_path, range(0, 900000, 90), duration=10000)
    def forbidden(*args, **kwargs):
        raise AssertionError('whole-file reads are forbidden')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setattr(Path, 'read_text', forbidden)
    tracemalloc.start()
    try:
        page = read_source_frame_page(asset, tmp_path, offset_frame=9000, limit=3)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert page['total'] == 10000
    assert [f['source_frame_index'] for f in page['source_frames']] == [9000, 9001, 9002]
    assert peak < 512_000, f'page reader accumulated too much memory: {peak} bytes'


def test_large_ls_export_rejected_before_open_when_count_declares_large(tmp_path, monkeypatch):
    asset, _, _ = fixture_index(tmp_path)
    asset['probe']['pts_index']['frame_count'] = 1001
    def forbidden(*args, **kwargs):
        raise AssertionError('known large export should fail before reading')
    monkeypatch.setattr(Path, 'open', forbidden)
    with pytest.raises(ValueError, match='最多1000帧'):
        read_label_studio_frame_map(asset, tmp_path)


@pytest.mark.parametrize('declared', [True, False])
def test_ls_actual_count_bound_cannot_be_bypassed_by_metadata(tmp_path, declared):
    asset, _, _ = fixture_index(tmp_path, range(0, 90090, 90), duration=1001, declared=declared)
    if declared:
        asset['probe']['pts_index']['frame_count'] = 3
    with pytest.raises(ValueError, match='最多1000帧'):
        read_label_studio_frame_map(asset, tmp_path)


def test_unknown_count_short_legacy_index_is_proven_bounded_by_scan(tmp_path):
    asset, path, _ = fixture_index(tmp_path, declared=False)
    # Very old rows can omit ordinal, but timing always requires actual integer PTS.
    path.write_text('\n'.join(json.dumps({'pts': pts}) for pts in [90000, 92999, 99000]), encoding='utf-8')
    asset['probe']['pts_index'].pop('sha256')
    assert len(read_label_studio_frame_map(asset, tmp_path)['frames']) == 3


@pytest.mark.parametrize('mutation,match', [('hash', 'hash'), ('count', '实际帧数'), ('incomplete', '完整'), ('timebase', 'time_base')])
def test_index_integrity_is_required(tmp_path, mutation, match):
    asset, _, _ = fixture_index(tmp_path)
    index = asset['probe']['pts_index']
    index[{'hash': 'sha256', 'count': 'frame_count', 'incomplete': 'complete', 'timebase': 'time_base'}[mutation]] = {
        'hash': '0' * 64, 'count': 4, 'incomplete': False, 'timebase': '1/1000'}[mutation]
    with pytest.raises(ValueError, match=match):
        read_source_frame_page(asset, tmp_path)


@pytest.mark.parametrize('rows', [
    [{'pts': 0}, {'pts': 0}], [{'pts': 90}, {'pts': 0}],
    [{'pts': True}], [{'pts': '9000'}], [{'frame_index': 1, 'pts': 0}],
])
def test_bad_pts_or_source_ordinal_are_not_guessed(tmp_path, rows):
    asset, path, _ = fixture_index(tmp_path, declared=False)
    path.write_text('\n'.join(map(json.dumps, rows)), encoding='utf-8')
    asset['probe']['pts_index'].pop('sha256')
    with pytest.raises(ValueError):
        read_source_frame_page(asset, tmp_path)


def test_long_json_row_is_rejected_without_unbounded_readline(tmp_path):
    asset, path, _ = fixture_index(tmp_path)
    path.write_bytes(b' ' * 65537)
    with pytest.raises(ValueError, match='超过读取上限'):
        read_source_frame_page(asset, tmp_path)


def test_index_cannot_escape_storage_root(tmp_path):
    asset, _, _ = fixture_index(tmp_path)
    asset['probe']['pts_index']['relative_path'] = '../outside.jsonl'
    with pytest.raises(ValueError):
        read_source_frame_page(asset, tmp_path)
