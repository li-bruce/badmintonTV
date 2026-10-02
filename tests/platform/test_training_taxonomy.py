from pathlib import Path

import pytest

from apps.platform.training_taxonomy import adapt_taxonomy, load_training_taxonomy


def test_models_taxonomy_preserves_source_ids_groups_and_uncertainty():
    path = Path(__file__).resolve().parents[2] / 'configs/models/taxonomy.v1.json'
    if not path.exists():
        pytest.skip('models draft taxonomy not integrated in this checkout')
    result = load_training_taxonomy(path)
    source = result.provenance['source_taxonomy']
    assert [label.label_id for label in result.labels] == [node['id'] for node in source['labels']]
    for node, label in zip(source['labels'], result.labels):
        assert label.selectable == (node['node_type'] == 'label')
        assert label.status == 'provisional'
        assert label.parent_id == node['parent_id']
        assert label.name == node['name_zh']
        assert all(e in label.description for e in node['evidence_requirements'])
    assert result.status == 'provisional'
    assert result.provenance['annotation_state_mapping']['not_visible'] == 'unobservable'
    assert adapt_taxonomy(result.model_dump(mode='json')) == result
