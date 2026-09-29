"""Acquire one fixed official public Qwen VL embedding revision, bounded bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.models.protocol import atomic_write_json, resolve_relative, storage_root
from packages.models.storage import reserve
from scripts.models.download_weights import fetch, json_url

MODEL = 'Qwen/Qwen3-VL-Embedding-2B'
REVISION = '9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda'
SOURCE = 'https://huggingface.co/' + MODEL
ROOT_RELATIVE = 'models/weights/qwen3-vl-embedding-2b'
MAXIMUM = 4_500_000_000


class AcquisitionPaused(RuntimeError):
    """Administrator requested a cooperative yield at a flushed Range boundary."""


def fetch_large_ranges(url,target,size,sha,*,pause_file=None,concurrency=1):
    """Normal HTTP Range, one append-only partial, same immutable source identity.

    Full-response transfer stalled before its first MiB on this host. Ranges
    are validated strictly and never bypass authentication or server limits.
    """
    if target.exists():
        return fetch(url,target,size,expected_sha=sha)
    partial=target.with_name(target.name+'.partial')
    marker=partial.with_name(partial.name+'.source.json')
    identity={'url':url,'maximum':size,'sha256':sha,'blob':None,'hash_prefix':None}
    target.parent.mkdir(parents=True,exist_ok=True)
    if partial.is_symlink() or marker.is_symlink(): raise ValueError('linked partial refused')
    if marker.exists():
        if json.loads(marker.read_text())!=identity: raise ValueError('partial source differs')
    elif partial.exists():
        raise ValueError('unverified existing partial preserved')
    else: atomic_write_json(marker,identity)
    count=partial.stat().st_size if partial.exists() else 0
    if count>size: raise ValueError('oversize partial preserved')
    if concurrency != 1:
        from scripts.models.range_transfer import append_ranges
        stats=append_ranges(url,partial,size,concurrency=concurrency,pause_file=pause_file)
        print(json.dumps({'range_transfer':stats}),flush=True)
        if stats['status']=='paused':
            raise AcquisitionPaused(f"partial retained at {stats['final_offset']} bytes; models writer released")
        return fetch(url,target,size,expected_sha=sha)
    started=time.monotonic()
    with partial.open('ab' if partial.exists() else 'xb') as out:
        while count<size:
            if pause_file is not None and Path(pause_file).exists():
                raise AcquisitionPaused(f'partial retained at {count} bytes; models writer released')
            end=min(size-1,count+8_388_608-1)
            expected=f'bytes {count}-{end}/{size}'
            request=urllib.request.Request(url,headers={'Range':f'bytes={count}-{end}'})
            segment_started=time.monotonic()
            with urllib.request.urlopen(request,timeout=30) as response:
                if response.status!=206 or response.headers.get('Content-Range')!=expected:
                    raise ValueError('server did not honor exact bounded Range')
                if response.headers.get('Content-Length') and int(response.headers['Content-Length'])!=end-count+1:
                    raise ValueError('unexpected Range length')
                while count<=end:
                    block=response.read(min(65536,end-count+1))
                    if not block: raise ValueError('truncated Range; partial preserved')
                    if time.monotonic()-segment_started>180 or time.monotonic()-started>7200:
                        raise TimeoutError('bounded Range transfer deadline; partial preserved')
                    out.write(block); count+=len(block)
                if response.read(1): raise ValueError('Range body exceeds requested byte interval')
            out.flush(); os.fsync(out.fileno())
            if count%(128*1024*1024)==0 or count==size:
                print(json.dumps({'file':target.name,'bytes':count,'total':size}),flush=True)
    # Existing downloader verifies complete SHA256 and publishes exclusively.
    return fetch(url,target,size,expected_sha=sha)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pause-file',help='Administrator control file; presence yields between flushed ranges')
    parser.add_argument('--concurrency',type=int,choices=[1,2,3,4],default=1)
    args=parser.parse_args()
    root = storage_root()
    metadata = json_url(f'https://huggingface.co/api/models/{MODEL}/revision/{REVISION}?blobs=true')
    if metadata.get('sha') != REVISION or metadata.get('private') or metadata.get('gated'):
        raise ValueError('expected a fixed, public, ungated official revision')
    files = metadata['siblings']
    if not files or any(type(f.get('size')) is not int or f['size'] < 0 for f in files):
        raise ValueError('missing finite file metadata')
    total = sum(f['size'] for f in files)
    if total > MAXIMUM:
        raise ValueError('official revision exceeds acquisition bound')
    manifest = {'schema_version':'1.0','source':SOURCE,'revision':REVISION,
                'license':'Apache-2.0','license_url':f'{SOURCE}/blob/{REVISION}/README.md',
                'expected_total_bytes':total,'files':[]}
    with reserve(root, MAXIMUM + 100_000_000):
        for entry in files:
            filename = entry['rfilename']
            target = resolve_relative(root,ROOT_RELATIVE+'/'+filename,owner='models')
            url = f'{SOURCE}/resolve/{REVISION}/{quote(filename,safe="/")}'
            lfs = entry.get('lfs')
            info = (fetch_large_ranges(url,target,entry['size'],lfs['sha256'],pause_file=args.pause_file,concurrency=args.concurrency) if lfs and entry['size']>64_000_000
                    else fetch(url,target,entry['size'],expected_sha=lfs['sha256'] if lfs else None,
                               expected_blob=None if lfs else entry['blobId']))
            manifest['files'].append({'relative_path':target.relative_to(root).as_posix(),
                'source_url':url,'license_url':manifest['license_url'],**info})
            print(json.dumps({'downloaded':filename,'size_bytes':info['size_bytes']},ensure_ascii=False),flush=True)
        output = resolve_relative(root,ROOT_RELATIVE+'/weights-manifest.json',owner='models')
        if output.exists():
            if json.loads(output.read_text(encoding='utf-8')) != manifest:
                raise ValueError('existing manifest differs; preserved')
        else:
            atomic_write_json(output,manifest)
    print(json.dumps({'manifest':output.relative_to(root).as_posix(),'total_bytes':total}))


if __name__ == '__main__':
    try:
        main()
    except AcquisitionPaused as exc:
        print(json.dumps({'status':'paused','reason':str(exc)}),flush=True)
        raise SystemExit(75)
