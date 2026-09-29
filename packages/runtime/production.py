"""Production-source checks at durable worker boundaries; models are separate."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from collections import deque

from packages.contracts import UsageScopeError, assert_production_allowed
from .storage import resolve_relative_path


MAX_LINEAGE_NODES = 100_000
MAX_LINEAGE_EDGES = 500_000


def current_source_records(queue_path):
    """Read current native business metadata without opening or creating a DB."""
    with sqlite3.connect(Path(queue_path).resolve().as_uri()+'?mode=ro',uri=True) as queue_db:
        table=queue_db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runtime_metadata'").fetchone()
        bound=queue_db.execute("SELECT value FROM runtime_metadata WHERE key='business_database'").fetchone() if table else None
    path=Path(bound[0] if bound else os.environ.get('BTV_DB_PATH') or Path(queue_path).with_name('platform.sqlite3'))
    if not path.exists():
        if bound:
            raise ValueError('SOURCE_DATABASE_UNAVAILABLE: bound business database is missing')
        return []  # A controlled standalone CLI has no platform business store.
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT body FROM assets')]


def _reachable_sources(roots, records):
    """Follow declared lineage and parent SHA aliases, visiting each DB row once.

    Unknown external references remain unknown; no unrelated media are opened.
    Metadata indexing is linear in library size, traversal in reachable edges.
    """
    if len(records) + len(roots) > MAX_LINEAGE_NODES:
        raise UsageScopeError('USAGE_SOURCE_CONFLICT', 'source graph exceeds the supported node budget')
    by_id, by_hash = {}, {}
    for index, item in enumerate(records):
        if not isinstance(item, dict) or any(item.get(field) is not None and not isinstance(item[field], str)
                                             for field in ('asset_id', 'sha256')):
            raise UsageScopeError('USAGE_METADATA_INVALID', 'source identity metadata is invalid')
        if item.get('asset_id'):
            by_id.setdefault(item['asset_id'], []).append(index)
        if item.get('sha256'):
            by_hash.setdefault(item['sha256'].lower(), []).append(index)
    pending, visited, alias_groups, selected = deque(roots), set(), set(), []
    edges = 0
    def add(indices):
        nonlocal edges
        edges += len(indices)
        if edges > MAX_LINEAGE_EDGES:
            raise UsageScopeError('USAGE_SOURCE_CONFLICT', 'source graph exceeds the supported edge budget')
        for index in indices:
            if index not in visited:
                visited.add(index)
                selected.append(records[index])
                pending.append(records[index])
    while pending:
        item = pending.popleft()
        provenance = item.get('provenance') or {}
        if not isinstance(provenance, dict):
            raise UsageScopeError('USAGE_METADATA_INVALID', 'source provenance must be an object')
        source_id, source_sha = provenance.get('source_asset_id'), provenance.get('source_sha256')
        if any(value is not None and not isinstance(value, str) for value in (source_id, source_sha)):
            raise UsageScopeError('USAGE_METADATA_INVALID', 'source references must be strings')
        id_matches = by_id.get(source_id, []) if source_id else []
        add(id_matches)
        # An ID-only reference also reaches any same-SHA physical copies of its
        # parent. Expand each alias group once, avoiding a quadratic clique.
        digests = [records[index].get('sha256') for index in id_matches]
        if source_sha:
            digests.append(source_sha)
        for digest in digests:
            digest = digest.lower() if digest else None
            if digest and digest not in alias_groups:
                alias_groups.add(digest)
                add(by_hash.get(digest, []))
    return selected


def _actual_source(context, asset, verified_files):
    """Hash real bytes with stable file identity; never trust claimed parent SHA."""
    claimed_sha, size = asset.get('sha256'), asset.get('size_bytes')
    if not isinstance(claimed_sha, str) or type(size) is not int or size < 0:
        raise ValueError('SOURCE_METADATA_INVALID: reachable source needs its declared sha256 and size_bytes')
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    try:
        path = resolve_relative_path(context.storage_root, asset['relative_path'], must_exist=True)
        if not path.is_file():
            raise ValueError('SOURCE_UNAVAILABLE: reachable source is not a regular file')
        before = path.stat()
        if before.st_size != size:
            raise ValueError('SOURCE_CHANGED: reachable source size differs from its declaration')
        # Same physical path aliases reuse only this call's verified bytes, and
        # only while all five path-stat identity fields still match.
        cached = verified_files.get(path)
        if cached and cached[0] == identity(before):
            return {**asset, 'sha256': cached[1]}
        digest = hashlib.sha256(); read = 0; last = time.monotonic()
        context.log('progress', stage='usage_verification', current=0, total=size, unit='bytes',
                    message='验证制作源文件及可追溯父资产实际字节')
        with path.open('rb') as stream:
            # Windows stat/fstat ctime semantics differ; compare shared fields.
            if identity(os.fstat(stream.fileno()))[:4] != identity(before)[:4]:
                raise ValueError('SOURCE_CHANGED: source replaced before verification')
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                context.check(); digest.update(chunk); read += len(chunk)
                if read > size:
                    raise ValueError('SOURCE_CHANGED: source grew during verification')
                if time.monotonic() - last >= .5:
                    context.log('progress', stage='usage_verification', current=read, total=size, unit='bytes')
                    last = time.monotonic()
            if identity(os.fstat(stream.fileno()))[:4] != identity(before)[:4]:
                raise ValueError('SOURCE_CHANGED: source mutated during verification')
        if identity(path.stat()) != identity(before) or read != size:
            raise ValueError('SOURCE_CHANGED: source mutated during verification')
    except OSError as exc:
        raise ValueError('SOURCE_UNAVAILABLE: reachable source bytes cannot be read') from exc
    actual = digest.hexdigest()
    verified_files[path] = identity(before), actual
    return {**asset, 'sha256': actual}


def check_sources(context, assets, *, verify_bytes=False):
    records = current_source_records(context.queue.db_path)
    current = {a['asset_id']: a for a in records}
    authoritative = [current[a['asset_id']] for a in assets if a.get('asset_id') in current]
    guard = lambda values: assert_production_allowed(values, context.storage_root, source_assets=records)
    parents = _reachable_sources([*assets, *authoritative], records)
    # Batch guards construct the trusted registry/source indexes once each.
    guard([*assets, *authoritative, *parents])
    for asset in assets:
        context.check()
        stored = current.get(asset.get('asset_id'))
        if stored and (('sha256' in asset and stored['sha256'].lower() != asset['sha256'].lower())
                       or stored['relative_path'] != asset['relative_path']):
            raise ValueError('SOURCE_CHANGED: queued source no longer matches current asset metadata')
    targets = [*parents, *(assets if verify_bytes else [])]
    actual, verified_files = [], {}
    for source in targets:
        context.check()
        actual.append(_actual_source(context, source, verified_files))
    # Refresh the registry after byte reads, including hashes that differ from
    # the claims. A copied training source must not be treated as ordinary data.
    guard(actual)
    for declared, verified in zip(targets, actual):
        if declared['sha256'].lower() != verified['sha256']:
            raise ValueError('SOURCE_CHANGED: source digest differs from its declaration')
    for path, (before, _) in verified_files.items():
        context.check()
        stat = path.stat()
        if before != (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
            raise ValueError('SOURCE_CHANGED: source changed after lineage verification')


def check_job_sources(context):
    if context.job['operation']=='model':
        return
    payload=context.job['payload']
    assets=payload.get('assets',[])
    if payload.get('asset'):
        assets=[*assets,payload['asset']]
    if payload.get('relative_path'):
        assets=[*assets,{**payload.get('asset_metadata',{}),'relative_path':payload['relative_path']}]
    check_sources(context,assets,verify_bytes=context.job['operation']=='render')
