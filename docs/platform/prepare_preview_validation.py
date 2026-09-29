"""Explicit CPU-only R-02 browser fixture setup, isolated from the production DB."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path('D:/video')

from packages.runtime import Queue, CapacityLedger
from packages.contracts import Asset
from packages.runtime.storage import resolve_owner_path, resolve_relative_path
from apps.platform.store import Store


def refresh_fixture_asset(source, storage_root, ffprobe):
    """Read current fixture bytes; never inherit a parent's probe/PTS sidecar."""
    asset = json.loads(json.dumps(source))
    path = resolve_relative_path(storage_root, asset['relative_path'], must_exist=True)
    with path.open('rb') as handle:
        actual_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
    if path.stat().st_size != asset['size_bytes'] or actual_hash != asset['sha256']:
        raise ValueError('fixture no longer matches its preserved report')
    info = json.loads(subprocess.check_output([
        ffprobe, '-v', 'error', '-show_entries',
        'stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,time_base,duration,start_time,start_pts:format=duration',
        '-of', 'json', str(path),
    ], timeout=30))
    video = next(item for item in info['streams'] if item['codec_type'] == 'video')
    rate, fps_source = None, None
    for key in ('avg_frame_rate', 'r_frame_rate'):
        try:
            candidate = Fraction(video.get(key, '0/0'))
        except (ValueError, ZeroDivisionError):
            continue
        if candidate > 0:
            rate, fps_source = candidate, key
            break
    duration, duration_source = None, None
    for value, label in ((video.get('duration'), 'stream.duration'),
                         (info.get('format', {}).get('duration'), 'format.duration')):
        try:
            candidate = Fraction(str(value))
        except (ValueError, ZeroDivisionError):
            continue
        if candidate > 0:
            duration, duration_source = candidate, label
            break
    if duration is None or Fraction(video['time_base']) <= 0:
        raise ValueError('fixture requires an actual positive duration and time base')
    asset.update(width=video['width'], height=video['height'],
                 fps_num=rate.numerator if rate else None,
                 fps_den=rate.denominator if rate else None,
                 time_base=video['time_base'], duration_ms=round(duration * 1000))
    # In particular, a 139-frame parent index cannot describe a 278-frame derivative.
    asset['probe'] = {
        'codec_name': video.get('codec_name'), 'stream_index': video.get('index', 0),
        'fps_source': fps_source, 'duration_source': duration_source,
        'time_base': video['time_base'], 'start_time': video.get('start_time'),
        'start_pts': video.get('start_pts'), 'source_sha256': actual_hash,
        'pts_index_status': 'not_attached; proxy creates an actual source index',
    }
    provenance = asset.get('provenance', {})
    if provenance.get('test_derivative'):
        # Parent hashes remain explicit lineage, never a publisher hash for new bytes.
        asset['provenance'] = {key: provenance[key] for key in (
            'test_derivative', 'source_asset_id', 'source_sha256', 'derivation', 'usage_scope'
        ) if key in provenance}
    return asset


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', help='New platform-relative directory; existing contents are refused')
    parser.add_argument('--evidence-root', default='platform/media-proxy-test-20260929-r2')
    args = parser.parse_args(argv)
    default_state = 'platform/research-20260929/browser-fixture-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    state = resolve_owner_path(ROOT, args.state or default_state, 'platform')
    evidence_root = resolve_owner_path(ROOT, args.evidence_root, 'platform', must_exist=True)
    if state.exists() and any(state.iterdir()):
        raise FileExistsError('fixture state must be empty; preserved evidence is never overwritten')
    ffprobe = os.environ['BTV_FFPROBE']
    os.environ['BTV_STORAGE_ROOT'] = str(ROOT)
    os.environ['BTV_DB_PATH'] = str(state/'platform.sqlite3')
    os.environ['BTV_RENDER_BACKEND'] = 'cpu'
    queue=Queue(state/'runtime.sqlite3')
    ledger=CapacityLedger(queue.db_path,ROOT)
    reservation=ledger.reserve('platform',16_000_000,'prepare-r02-browser')
    try:
        store=Store(state/'platform.sqlite3',ROOT)
        store.put('library','preview-research',{'library_id':'preview-research','name':'R-02 代理预览验证（仅既有研究原片及明确派生）','storage_root':str(ROOT)})
        jobs=[]
        for name in ('real_cfr','derived_vfr','derived_ffv1','derived_60_to_30'):
            report=json.loads((evidence_root/name/'R-02a-report.json').read_text(encoding='utf-8'))
            asset=Asset.model_validate(refresh_fixture_asset(report['source'], ROOT, ffprobe)).model_dump(mode='json')
            asset['title']='R-02 '+name+' · '+asset['title']
            imported=store.import_assets([asset],'preview-research')[0]['asset']
            jobs.append(queue.enqueue('media_proxy',{'asset':imported,'start_ms':0,'end_ms':asset['duration_ms'],'max_height':720,'max_fps':30 if name=='derived_60_to_30' else None},idempotency_key='r02-browser-'+name)['job_id'])
        with (state/'setup.json').open('x', encoding='utf-8') as output:
            json.dump({'jobs':jobs,'database':str(state/'platform.sqlite3'),'port':18082,'disk_free_bytes':shutil.disk_usage(ROOT).free,'usage':ledger.usage()},output,ensure_ascii=False,indent=2)
        print(json.dumps({'jobs':jobs,'state':str(state)},ensure_ascii=False))
    finally:
        ledger.release(reservation)


if __name__=='__main__':
    main()
