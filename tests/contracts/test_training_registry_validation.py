"""Public publisher validation must reject the same bad lineage as the guard."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts import (
    TRAINING_REGISTRY_PATH, TrainingRegistry, TrainingRegistryEntry,
    UsageScopeError, UsageScopeGuard,
)


def entry(provenance):
    return {'asset_id': 'training-derived', 'sha256': 'a' * 64,
            'relative_path': 'data/training/set/derived.mp4',
            'usage_scope': 'training_only', 'provenance': provenance}


INVALID_PROVENANCE = [
    {'source_asset_id': 123}, {'source_asset_id': True},
    {'source_asset_id': ''}, {'source_asset_id': ' \t\n'},
    {'source_asset_id': []}, {'source_asset_id': {}},
    {'source_sha256': 'not-a-sha256'}, {'source_sha256': 'a' * 63},
    {'source_sha256': 'a' * 65}, {'source_sha256': 'g' * 64},
    {'source_sha256': 123}, {'source_sha256': True},
    {'source_sha256': []}, {'source_sha256': {}},
    {'usage_scope': 'Training_only'}, {'usage_scope': ''},
    {'usage_scope': 123}, {'usage_scope': True},
    {'usage_scope': []}, {'usage_scope': {}},
]


@pytest.mark.parametrize('provenance', INVALID_PROVENANCE)
def test_public_entry_rejects_bad_source_metadata(provenance):
    with pytest.raises(ValidationError, match='provenance\\.'):
        TrainingRegistryEntry.model_validate(entry(provenance))


@pytest.mark.parametrize('provenance', INVALID_PROVENANCE)
def test_registry_publisher_cannot_validate_and_serialize_bad_lineage(provenance):
    payload = {'schema_version': '1.0', 'assets': [entry(provenance)]}
    for validate, value in ((TrainingRegistry.model_validate, payload),
                            (TrainingRegistry.model_validate_json, json.dumps(payload))):
        with pytest.raises(ValidationError, match='provenance\\.'):
            validate(value)


@pytest.mark.parametrize('provenance', [
    {}, {'source_asset_id': None, 'source_sha256': None, 'usage_scope': None},
    {'source_asset_id': 'upstream-source'}, {'source_sha256': 'ABCDEF0123456789' * 4},
    {'source_asset_id': 'upstream-source', 'source_sha256': 'b' * 64,
     'usage_scope': 'training_only', 'notes': {'nullable': None, 'tags': ['research', 2]}},
    {'usage_scope': 'general'},
])
def test_valid_provenance_is_preserved_without_weakening_typed_training_scope(tmp_path, provenance):
    validated = TrainingRegistry.model_validate({'schema_version': '1.0', 'assets': [entry(provenance)]})
    assert validated.assets[0].provenance == provenance
    assert validated.model_dump(mode='json')['assets'][0]['provenance'] == provenance
    # Typed training_only remains restrictive even when source scope is general.
    decision = UsageScopeGuard(tmp_path).check(validated.assets[0])
    assert not decision.allowed and decision.usage_scope == 'training_only'


@pytest.mark.parametrize('provenance', INVALID_PROVENANCE)
def test_guard_still_fails_closed_for_invalid_asset_and_registry(tmp_path, provenance):
    guard = UsageScopeGuard(tmp_path)
    with pytest.raises(UsageScopeError) as direct:
        guard.check({'relative_path': 'data/raw/local.mp4', 'provenance': provenance})
    assert direct.value.code == 'USAGE_METADATA_INVALID'

    path = tmp_path / TRAINING_REGISTRY_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'schema_version': '1.0', 'assets': [entry(provenance)]}), encoding='utf-8')
    with pytest.raises(UsageScopeError) as registry:
        guard.check({'relative_path': 'data/raw/unrelated.mp4'})
    assert registry.value.code == 'TRAINING_REGISTRY_INVALID'


def test_semantic_validator_does_not_change_the_published_json_schema():
    path = Path(__file__).parents[2] / 'packages/contracts/schemas/TrainingRegistry.schema.json'
    assert TrainingRegistry.model_json_schema() == json.loads(path.read_text(encoding='utf-8'))
