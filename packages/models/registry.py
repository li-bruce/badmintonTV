"""Small, truthful model registry: presence is not task accuracy."""
import importlib.util
import json
import os
from pathlib import Path

VERSION = '0.1.0'
REQUIRED_FILES = {
    'qwen3-0.6b': {'config.json','generation_config.json','tokenizer.json','tokenizer_config.json','vocab.json','merges.txt','model.safetensors'},
    'torchvision-pose': {'keypointrcnn_resnet50_fpn_coco-fc266e95.pth'},
    'clip-vit-base-patch32': {'config.json','preprocessor_config.json','tokenizer_config.json','special_tokens_map.json','vocab.json','merges.txt','pytorch_model.bin'},
}
DEFINITIONS = [
    ('query-rule-v1','受限中文规则解析','query_parse',None,[], 'ready'),
    ('query-endpoint-v1','管理员配置的兼容LLM端点','query_parse',None,[], 'unavailable'),
    ('qwen3-0.6b','Qwen3 0.6B 中文条件实验','query_parse','qwen3-0.6b',['torch','transformers'],'experimental'),
    ('torchvision-keypointrcnn','COCO17 姿态预标注','pose','torchvision-pose',['torch','torchvision','av'],'experimental'),
    ('clip-frame-mean','CLIP 短窗抽帧均值基线','video_embedding','clip-vit-base-patch32',['torch','transformers','av'],'experimental'),
    ('skeleton-temporal-v1','骨骼细动作分类（未训练）','movement_classification',None,[], 'unavailable'),
]


def storage_root():
    return Path(os.environ.get('BTV_STORAGE_ROOT', 'D:/video' if os.name == 'nt' else '/mnt/d/video'))


def catalog():
    root = storage_root()
    models = []
    for model_id, name, capability, folder, modules, intended in DEFINITIONS:
        status, reason, weights = intended, None, []
        if folder:
            manifest = root / 'models/weights' / folder / 'weights-manifest.json'
            missing = [name for name in modules if importlib.util.find_spec(name) is None]
            if not manifest.is_file():
                status, reason = 'not_installed', '本环境没有已校验权重清单'
            else:
                try:
                    from .protocol import resolve_relative
                    files = json.loads(manifest.read_text(encoding='utf-8'))['files']
                    names = set()
                    for f in files:
                        path = resolve_relative(root,f['relative_path'],owner='models')
                        if path.parent != manifest.parent.resolve() or not path.is_file() or path.stat().st_size != f['size_bytes']:
                            raise ValueError('incomplete weights')
                        names.add(path.name)
                    if not REQUIRED_FILES[folder].issubset(names):
                        raise ValueError('missing required weights')
                    weights = [{k:f[k] for k in ('relative_path','sha256','license_url')} for f in files]
                except (ValueError,KeyError,TypeError,OSError):
                    status, reason = 'unavailable', '权重清单损坏或文件缺失/大小不符；未执行模型'
            if missing:
                status, reason = 'not_installed', '当前Python缺少依赖: ' + ', '.join(missing)
        elif model_id == 'query-endpoint-v1':
            configured = os.environ.get('BTV_LLM_CONFIG')
            status = 'experimental' if configured and Path(configured).is_file() else 'unavailable'
            reason = '端点配置存在但连接/输出仍需实测' if status == 'experimental' else '未设置管理员 BTV_LLM_CONFIG'
        elif model_id == 'skeleton-temporal-v1':
            reason = '缺少专家冻结细标签、跨比赛真值和训练checkpoint；不产生预测'
        models.append({
            'schema_version':'1.0','model_id':model_id,'version':VERSION,'display_name':name,
            'capabilities':[capability],'status':status,'reason':reason,
            'entrypoint':['python','-m','packages.models','run','--request','{request}','--result','{result}'],
            'environment':{'kind':'stdlib' if not modules else 'wsl-conda','prefix':None if not modules else '/mnt/d/video/runtime/models/env'},
            'weights':weights,'parameters_schema':{'type':'object','required':['model_id'],
                'properties':{'model_id':{'const':model_id},'text':{'type':'string'},'start_ms':{'type':'integer','minimum':0},
                              'end_ms':{'type':'integer','minimum':1},'sample_fps':{'type':'number','minimum':.5,'maximum':30},
                              'max_frames':{'type':'integer','minimum':1,'maximum':120}}},
            'input_schema':'JobRequest@1.0','output_schema':'JobResult@1.0',
            'supported_labels':[],'supported_camera_types':[],
            'evaluation_report':'docs/models/HANDOFF.md',
            'license':{'code':'project license not yet declared; upstream licenses recorded separately',
                       'upstream':'see weight manifests and docs/models/SOURCES.md'},
            'resource_requirements':{'device':'cpu' if not modules else 'cuda','gpu_exclusive':bool(modules),
                                     'max_clip_ms':30000,'max_frames':120}})
    from .reuse_catalog import catalog_entries
    return {'schema_version':'1.0','models':models+catalog_entries(root)}
