"""Lossless source-preserving adapter for the models-owned draft taxonomy."""
import hashlib
import json
from pathlib import Path

from packages.contracts.training import TrainingTaxonomy, get_default_training_taxonomy


def adapt_taxonomy(source):
    if source.get('format') != 'badminton_taxonomy':
        return TrainingTaxonomy.model_validate(source)
    if source.get('schema_version') != '1.0':
        raise ValueError('不支持的模型词表 schema_version')
    labels = []
    kind_map = {'contact': 'contact', 'interval': 'segment', 'state': 'state'}
    for node in source['labels']:
        if node.get('node_type') not in ('label', 'group'):
            raise ValueError('词表节点必须为 label 或 group')
        kinds = tuple(dict.fromkeys(kind_map[k] for k in node['applicability']['record_kinds']))
        text = node['definition_draft'] + ' 证据要求：' + '；'.join(node.get('evidence_requirements', []))
        text += ' 易混项：' + '；'.join(node.get('counterexamples', []))
        text += ' 支持状态：' + node.get('support_status', 'unavailable') + '；专家定义未冻结。'
        labels.append({'label_id': node['id'], 'name': node['name_zh'], 'dimension': node['domain'],
                       'parent_id': node.get('parent_id'), 'description': text, 'kinds': kinds,
                       'status': 'provisional', 'selectable': node['node_type'] == 'label',
                       'requires_person': node['domain'] not in ('shuttle', 'outcome')})
    canonical = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return TrainingTaxonomy.model_validate({'taxonomy_id': source['taxonomy_id'], 'version': source['version'],
                                           'status': 'provisional', 'labels': labels,
                                           'provenance': {'adapter': 'platform-models-taxonomy-v1', 'source_sha256': hashlib.sha256(canonical).hexdigest(),
                                                          'source_taxonomy': source, 'annotation_state_mapping': {'unannotated': 'unlabeled', 'not_visible': 'unobservable'},
                                                          'note': '保留完整原词表；目录group不得作标签；草案不能升级为正式训练语义'}})


def load_training_taxonomy(configured=None):
    path = Path(configured) if configured else Path(__file__).resolve().parents[2] / 'configs/models/taxonomy.v1.json'
    if not path.is_file():
        if configured:
            raise ValueError('管理员配置的训练词表不存在')
        return get_default_training_taxonomy()
    if path.stat().st_size > 2_000_000:
        raise ValueError('训练词表超过2MB上限')
    return adapt_taxonomy(json.loads(path.read_text(encoding='utf-8')))
