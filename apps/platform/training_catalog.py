"""Read-only, library-owned training catalog and native file identity proofs.

Public selectors are asset IDs, never paths. Run verification and JSONL pages in
a worker/thread: they do bounded-memory I/O, not event-loop work. Registration
objects belong only in the training store; no production gate is relaxed here.
"""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from packages.contracts import Asset
from packages.contracts.usage import TrainingRegistry
from packages.runtime.artifact_identity import (
    ArtifactIdentityError, check_proof, file_identity, hash_identity,
)
from packages.runtime.storage import resolve_owner_path

CATALOG_PATH = 'data/training/handoff/annotation-catalog.v1.json'
LEGACY_MANIFEST_PATH = 'data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json'
REGISTRY_PATH = 'data/training/handoff/training-registry.v1.json'
MAX_CATALOG_BYTES = 32_000_000
MAX_ASSETS = 10_000
MAX_SOURCE_BYTES = 20_000_000_000
MAX_INDEX_BYTES = 64_000_000
MAX_ROW_BYTES = 65_536
MAX_FRAMES = 2_000_000
REGISTERED_FORMAT = 'btv.training.registered-source'


class TrainingCatalogError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


def _fail(code, message):
    raise TrainingCatalogError(code, message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _source_metadata(asset):
    """An aggregate sidecar address changes when unrelated entries are added."""
    source = deepcopy(asset)
    source['provenance'].pop('annotation_catalog', None)
    return source


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _json(raw):
    def nonfinite(_):
        raise ValueError('nonfinite JSON number')
    return json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=nonfinite)


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        _fail('TRAINING_METADATA_INVALID', f'{label} is outside its integer bounds')
    return value


class TrainingCatalog:
    def __init__(self, storage_root):
        self.storage_root = Path(storage_root)

    def _path(self, relative, *, must_exist=True):
        try:
            path = resolve_owner_path(self.storage_root, relative, 'data/training', must_exist=must_exist)
            if must_exist and not path.is_file():
                raise ValueError('not a regular file')
            return path
        except (ValueError, OSError):
            _fail('TRAINING_PATH_INVALID', 'training path is unavailable, outside its owner, or uses an alias')

    def _read_document(self, relative):
        path = self._path(relative)
        try:
            proof = hash_identity(path, max_bytes=MAX_CATALOG_BYTES)
            with path.open('rb') as stream:
                if file_identity(os.fstat(stream.fileno())) != proof['descriptor_identity']:
                    raise ValueError('document changed')
                raw = stream.read(MAX_CATALOG_BYTES + 1)
            if len(raw) > MAX_CATALOG_BYTES or hashlib.sha256(raw).hexdigest() != proof['sha256']:
                raise ValueError('document changed or too large')
            check_proof(path, proof)
            return _json(raw), {**proof, 'relative_path': relative}
        except (ValueError, OSError, UnicodeError):
            _fail('TRAINING_CATALOG_INVALID', 'trusted JSON is malformed, oversized, or changed while reading')

    def _load(self):
        # Only these fixed administrator/library paths are considered. No glob,
        # manifest URL, environment path, or browser-supplied filename is read.
        newer = self._path(CATALOG_PATH, must_exist=False)
        relative = CATALOG_PATH if newer.exists() else LEGACY_MANIFEST_PATH
        catalog, manifest_proof = self._read_document(relative)
        registry, registry_proof = self._read_document(REGISTRY_PATH)
        try:
            if catalog.get('schema_version') != '1.0':
                raise ValueError('catalog schema')
            rows = catalog.get('assets')
            if rows is None and isinstance(catalog.get('entries'), list):
                rows = [item['asset'] for item in catalog['entries']]
            if not isinstance(rows, list) or len(rows) > MAX_ASSETS:
                raise ValueError('catalog asset count')
            registry_rows = TrainingRegistry.model_validate(registry).model_dump(mode='json')['assets']
            if len(registry_rows) > MAX_ASSETS:
                raise ValueError('registry asset count')
            registry_by_id = {}
            for registered in registry_rows:
                registry_by_id.setdefault(registered['asset_id'], []).append(registered)
            assets = {}
            for row in rows:
                asset = Asset.model_validate(row).model_dump(mode='json')
                asset['sha256'] = asset['sha256'].lower()
                if isinstance(asset['probe'].get('pts_index'), dict) and isinstance(asset['probe']['pts_index'].get('sha256'), str):
                    asset['probe']['pts_index']['sha256'] = asset['probe']['pts_index']['sha256'].lower()
                if asset['asset_id'] in assets:
                    raise ValueError('duplicate asset_id')
                self._metadata(asset)
                assets[asset['asset_id']] = asset
            bindings, details, sidecar_cache = {}, {}, {}
            for key, asset in assets.items():
                matches = registry_by_id.get(key, [])
                if not matches:
                    raise ValueError('asset is absent from training registry')
                if any(r['sha256'].lower() != asset['sha256'].lower()
                       or r['relative_path'] != asset['relative_path'] for r in matches):
                    raise ValueError('registry identity differs')
                if len({_digest(row) for row in matches}) != 1:
                    raise ValueError('ambiguous registry metadata')
                registered = matches[0]
                for field in ('size_bytes', 'match_id'):
                    if field in registered and registered[field] != asset[field]:
                        raise ValueError('registry source metadata differs')
                provenance = registered.get('provenance', {})
                if provenance.get('usage_scope', 'training_only') != 'training_only':
                    raise ValueError('registry provenance downgraded')
                for field in ('source_asset_id', 'source_sha256', 'dataset_id', 'source_archive_sha256', 'archive_member'):
                    if field in provenance and provenance[field] != asset['provenance'].get(field):
                        raise ValueError('registry provenance differs')
                details[key] = self._annotation_entry(asset, sidecar_cache)
                bindings[key] = {'asset_metadata_sha256': _digest(_source_metadata(asset)),
                                 'registry_entry_sha256': _digest(registered),
                                 'annotation_entry_sha256': _digest(details[key])}
            return assets, bindings, {'manifest': manifest_proof, 'registry': registry_proof,
                                      'catalog_revision': _digest([manifest_proof['sha256'], registry_proof['sha256']]),
                                      'annotation_details': details}
        except TrainingCatalogError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            _fail('TRAINING_CATALOG_INVALID', 'catalog/registry schema, identity, provenance, or source metadata conflicts')

    def _annotation_entry(self, asset, cache):
        ref = asset['provenance'].get('annotation_catalog')
        if ref is None:
            return {'asset_id': asset['asset_id'], 'usage_scope': 'training_only',
                    'match_group': {'status': 'unconfirmed', 'confirmed_group_id': None,
                                    'publisher_match_id': asset['match_id'], 'source_sha256': asset['sha256'],
                                    'split': 'unassigned', 'independent_match_confirmed': False},
                    'training_truth_eligible': False, 'blockers': ['legacy_catalog_has_no_group_confirmation']}
        if not isinstance(ref, dict) or ref.get('schema_version') != 'library.annotation-catalog/1':
            _fail('TRAINING_CATALOG_INVALID', 'annotation sidecar schema is unsupported')
        digest = ref.get('sha256')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            _fail('TRAINING_CATALOG_INVALID', 'annotation sidecar needs a content SHA256')
        expected = f'data/training/handoff/annotation-catalog/{digest}.details.json'
        if ref.get('relative_path') != expected:
            _fail('TRAINING_CATALOG_INVALID', 'annotation details must use the fixed content-addressed directory')
        _integer(ref.get('size_bytes'), 1, MAX_CATALOG_BYTES, 'annotation details size')
        if expected not in cache:
            content, proof = self._read_document(expected)
            if proof['sha256'] != digest or proof['size_bytes'] != ref['size_bytes']:
                _fail('TRAINING_CATALOG_INVALID', 'annotation details bytes differ from their reference')
            if content.get('schema_version') != 'library.annotation-catalog/1' or content.get('usage_scope') != 'training_only':
                _fail('TRAINING_CATALOG_INVALID', 'annotation details cannot downgrade training scope')
            rows = content.get('assets')
            if not isinstance(rows, list) or len(rows) > MAX_ASSETS:
                _fail('TRAINING_CATALOG_INVALID', 'annotation details count is invalid')
            selected = {}
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('asset_id'), str) or row['asset_id'] in selected:
                    _fail('TRAINING_CATALOG_INVALID', 'annotation details have duplicate or invalid asset IDs')
                selected[row['asset_id']] = row
            cache[expected] = selected
        entry = cache[expected].get(asset['asset_id'])
        if not entry or entry.get('usage_scope') != 'training_only':
            _fail('TRAINING_CATALOG_INVALID', 'annotation details omit the selected training source')
        source = Asset.model_validate(entry['source_asset']).model_dump(mode='json')
        if _source_metadata(source) != _source_metadata(asset):
            _fail('TRAINING_CATALOG_INVALID', 'annotation details source snapshot differs from catalog asset')
        if entry.get('original_pts') != asset['probe']['pts_index']:
            _fail('TRAINING_CATALOG_INVALID', 'annotation details PTS reference differs')
        group = entry.get('match_group', {})
        if group.get('source_sha256') != asset['sha256'] or group.get('publisher_match_id') != asset['match_id']:
            _fail('TRAINING_CATALOG_INVALID', 'annotation grouping refers to a different source')
        # This library schema publishes unreviewed acquisition hints, not an
        # authority to create human truth or independently confirmed matches.
        if group.get('status') != 'unconfirmed' or group.get('independent_match_confirmed') is not False or group.get('confirmed_group_id') is not None or entry.get('training_truth_eligible') is not False:
            _fail('TRAINING_CATALOG_INVALID', 'acquisition hints cannot assert confirmed groups or human truth')
        return deepcopy(entry)

    def _metadata(self, asset):
        if asset['usage_scope'] != 'training_only' or asset['provenance'].get('usage_scope', 'training_only') != 'training_only':
            _fail('TRAINING_METADATA_INVALID', 'catalog entries must remain training_only')
        _integer(asset['size_bytes'], 1, MAX_SOURCE_BYTES, 'source size')
        _integer(asset['duration_ms'], 1, 86_400_000, 'duration')
        _integer(asset['width'], 1, 16384, 'width')
        _integer(asset['height'], 1, 16384, 'height')
        self._path(asset['relative_path'], must_exist=False)
        probe = asset['probe']
        if not isinstance(probe.get('source_sha256'), str) or probe['source_sha256'].lower() != asset['sha256'] or probe.get('source_size_bytes') != asset['size_bytes']:
            _fail('TRAINING_METADATA_INVALID', 'probe is not bound to the declared source bytes')
        index = probe.get('pts_index')
        if not isinstance(index, dict) or index.get('format') != 'jsonl' or index.get('complete') is not True:
            _fail('TRAINING_PTS_INVALID', 'a complete actual source JSONL PTS reference is required')
        self._path(index.get('relative_path'), must_exist=False)
        _integer(index.get('size_bytes'), 1, MAX_INDEX_BYTES, 'PTS index size')
        _integer(index.get('frame_count'), 1, MAX_FRAMES, 'PTS frame count')
        if not isinstance(index.get('sha256'), str) or len(index['sha256']) != 64 or any(c not in '0123456789abcdefABCDEF' for c in index['sha256']):
            _fail('TRAINING_PTS_INVALID', 'PTS reference requires SHA256')
        try:
            if Fraction(asset['time_base']) <= 0 or Fraction(index['time_base']) != Fraction(asset['time_base']):
                raise ValueError
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            _fail('TRAINING_PTS_INVALID', 'PTS time base is absent or inconsistent')

    def list_catalog(self, offset=0, limit=100):
        _integer(offset, 0, MAX_ASSETS, 'offset')
        _integer(limit, 1, 1000, 'limit')
        assets, _, proof = self._load()
        ordered = sorted(assets.values(), key=lambda item: item['asset_id'])
        return {'assets': ordered[offset:offset + limit], 'total': len(ordered),
                'offset': offset, 'limit': limit, 'catalog_revision': proof['catalog_revision'],
                'catalog_relative_path': proof['manifest']['relative_path'], 'usage_scope': 'training_only',
                'annotation_details': {a['asset_id']: proof['annotation_details'][a['asset_id']] for a in ordered[offset:offset + limit]}}

    def _selected(self, asset_id):
        if not isinstance(asset_id, str) or not asset_id.strip():
            _fail('TRAINING_ASSET_UNKNOWN', 'select a catalog asset_id')
        assets, bindings, proof = self._load()
        if asset_id not in assets:
            _fail('TRAINING_ASSET_UNKNOWN', 'asset_id is not in the trusted training catalog')
        selected_details = proof.pop('annotation_details')[asset_id]
        return assets[asset_id], bindings[asset_id], {**proof, 'catalog_metadata': selected_details}

    def get_asset(self, asset_id):
        """Trusted metadata lookup across all entries; not limited to a UI page."""
        return self._selected(asset_id)[0]

    def _scan_pts(self, asset, *, offset_frame=0, limit=1, at_ms=None, check=None, progress=None):
        _integer(offset_frame, 0, MAX_FRAMES, 'offset_frame')
        _integer(limit, 1, 1000, 'limit')
        try:
            target = Fraction(str(at_ms)) if at_ms is not None else None
            if target is not None and not 0 <= target < asset['duration_ms']:
                raise ValueError
        except (ValueError, ZeroDivisionError):
            _fail('TRAINING_PTS_INVALID', 'at_ms must be finite and inside the source duration')
        ref = asset['probe']['pts_index']
        path = self._path(ref['relative_path'])
        duration, time_base = Fraction(asset['duration_ms']), Fraction(asset['time_base'])
        before = file_identity(path)
        if before[2] != ref['size_bytes']:
            _fail('TRAINING_PTS_CHANGED', 'PTS reference size changed')
        digest, consumed, count, origin, previous = hashlib.sha256(), 0, 0, None, None
        frames = []
        selected_offset = offset_frame if target is None else None
        emit = progress or (lambda event: None)
        emit({'stage': 'pts_verify', 'current': 0, 'total': ref['size_bytes'], 'unit': 'bytes'})

        def take(number, pts, start, end):
            nonlocal selected_offset
            if not 0 <= start < end <= duration:
                _fail('TRAINING_PTS_INVALID', 'source PTS must increase within the declared duration')
            if selected_offset is None and start <= target < end:
                selected_offset = number
            if selected_offset is not None and selected_offset <= number < selected_offset + limit:
                frames.append({'source_frame_index': number, 'source_pts': pts,
                               'source_pts_ms': float(start), 'source_end_ms': float(end)})

        try:
            with path.open('rb') as stream:
                descriptor = file_identity(os.fstat(stream.fileno()))
                if descriptor[:4] != before[:4]:
                    raise ArtifactIdentityError('PTS replaced')
                while raw := stream.readline(MAX_ROW_BYTES + 1):
                    if check:
                        check()
                    consumed += len(raw)
                    if len(raw) > MAX_ROW_BYTES or consumed > ref['size_bytes'] or count >= MAX_FRAMES:
                        _fail('TRAINING_PTS_INVALID', 'PTS file exceeds bounded rows/bytes')
                    digest.update(raw)
                    row = _json(raw)
                    if type(row.get('frame_index')) is not int or row['frame_index'] != count or type(row.get('pts')) is not int:
                        _fail('TRAINING_PTS_INVALID', 'PTS ordinal or integer timestamp is invalid')
                    if origin is None:
                        origin = row['pts']
                    start = (row['pts'] - origin) * time_base * 1000
                    if previous is not None:
                        take(*previous, start)
                    previous = count, row['pts'], start
                    count += 1
                    if count % 2048 == 0:
                        emit({'stage': 'pts_verify', 'current': consumed, 'total': ref['size_bytes'], 'unit': 'bytes'})
                if previous is None:
                    _fail('TRAINING_PTS_INVALID', 'PTS index is empty')
                take(*previous, duration)
                if file_identity(os.fstat(stream.fileno())) != descriptor:
                    raise ArtifactIdentityError('PTS changed during verification')
            proof = {'relative_path': ref['relative_path'], 'sha256': digest.hexdigest(), 'size_bytes': consumed,
                     'identity': before, 'descriptor_identity': descriptor, 'stat': before}
            check_proof(path, proof)
            if consumed != ref['size_bytes'] or proof['sha256'] != ref['sha256'].lower() or count != ref['frame_count']:
                _fail('TRAINING_PTS_CHANGED', 'PTS bytes/hash/frame count differ from trusted reference')
        except TrainingCatalogError:
            raise
        except (ValueError, KeyError, TypeError, OSError, UnicodeError):
            _fail('TRAINING_PTS_INVALID', 'PTS bytes or identity cannot be verified')
        emit({'stage': 'pts_verify', 'current': consumed, 'total': ref['size_bytes'], 'unit': 'bytes'})
        proof.update(reference=deepcopy(ref), source_sha256=asset['sha256'], frame_count=count,
                     first_pts=origin, last_pts=previous[1], time_base=str(time_base))
        return {'source_frames': frames, 'total': count, 'offset_frame': selected_offset,
                'limit': limit, 'source_index_scope': 'full_source', 'source_time_base': str(time_base),
                'source_duration_ms': asset['duration_ms']}, proof

    def verify_asset(self, asset_id, *, check=None, progress=None):
        """Blocking hash/index verification; persist only the returned server object."""
        asset, binding, catalog_proof = self._selected(asset_id)
        if check:
            check()
        path = self._path(asset['relative_path'])
        emit = progress or (lambda event: None)
        emit({'stage': 'source_hash', 'current': 0, 'total': asset['size_bytes'], 'unit': 'bytes'})
        try:
            proof = hash_identity(path, max_bytes=asset['size_bytes'], check=check)
        except (ArtifactIdentityError, OSError):
            _fail('TRAINING_SOURCE_CHANGED', 'source bytes or identity cannot be verified')
        if proof['sha256'] != asset['sha256'].lower() or proof['size_bytes'] != asset['size_bytes']:
            _fail('TRAINING_SOURCE_CHANGED', 'source hash/size differs from trusted catalog')
        emit({'stage': 'source_hash', 'current': proof['size_bytes'], 'total': asset['size_bytes'], 'unit': 'bytes'})
        _, pts_proof = self._scan_pts(asset, check=check, progress=progress)
        if check:
            check()
        _, current_binding, _ = self._selected(asset_id)
        if current_binding != binding:
            _fail('TRAINING_REGISTRATION_STALE', 'selected catalog metadata changed during verification')
        try:
            check_proof(self._path(asset['relative_path']), proof)
            check_proof(self._path(pts_proof['relative_path']), pts_proof)
        except (ArtifactIdentityError, OSError):
            _fail('TRAINING_SOURCE_CHANGED', 'source or PTS identity changed after verification')
        proof.update(relative_path=asset['relative_path'], stat=proof['identity'],
                     verified_at=datetime.now(timezone.utc).isoformat())
        return {'format': REGISTERED_FORMAT, 'schema_version': '1.0', 'usage_scope': 'training_only',
                'asset': asset, 'identity_proof': proof, 'pts_proof': pts_proof,
                'catalog_metadata': catalog_proof.pop('catalog_metadata'),
                'catalog_proof': {**catalog_proof, **binding}}

    def validate_registered(self, record):
        """Check a trusted stored registration before opening VerifiedArtifactResponse.

        The response must retain identity_proof and serve that verified descriptor;
        returning a checked Path alone does not close a later-open race.
        """
        try:
            if record['format'] != REGISTERED_FORMAT or record['schema_version'] != '1.0' or record['usage_scope'] != 'training_only':
                raise ValueError('wrong registration type')
            asset, binding, _ = self._selected(record['asset']['asset_id'])
            if _digest(_source_metadata(record['asset'])) != binding['asset_metadata_sha256']:
                raise ValueError('asset snapshot changed')
            if _digest(record['catalog_metadata']) != binding['annotation_entry_sha256']:
                raise ValueError('annotation metadata changed')
            if any(record['catalog_proof'].get(key) != value for key, value in binding.items()):
                raise ValueError('selected catalog or registry entry changed')
            source, pts = record['identity_proof'], record['pts_proof']
            ref = asset['probe']['pts_index']
            if any(source[field] != asset[field] for field in ('relative_path', 'sha256', 'size_bytes')):
                raise ValueError('source proof binding changed')
            if any(pts[field] != ref[field] for field in ('relative_path', 'sha256', 'size_bytes')) or pts['source_sha256'] != asset['sha256']:
                raise ValueError('PTS proof binding changed')
            path = self._path(asset['relative_path'])
            check_proof(path, source)
            check_proof(self._path(ref['relative_path']), pts)
            return path
        except TrainingCatalogError:
            raise
        except (ValueError, TypeError, KeyError, OSError):
            _fail('TRAINING_REGISTRATION_STALE', 'registered source/PTS identity or trusted metadata changed; verify again')

    def read_frames(self, record, offset_frame=0, limit=128, at_ms=None):
        self.validate_registered(record)
        page, _ = self._scan_pts(record['asset'], offset_frame=offset_frame, limit=limit, at_ms=at_ms)
        self.validate_registered(record)
        return page
