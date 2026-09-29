"""Metadata-only registry for bounded reuse experiments; never loads ML code."""
import importlib.util
import json
from .protocol import resolve_relative


def catalog_entries(root):
    entries=[]
    specs=[
        ('tracknetv3-reuse','TrackNetV3 连续球点实验','tracking','tracknetv3/reuse-manifest.json',
         ['torch','av','cv2','numpy','PIL'],'env','TRACKNET_REUSE.md'),
        ('qwen3-vl-embedding-2b','Qwen3-VL 短视频中文检索实验','video_embedding','qwen3-vl-embedding-2b/weights-manifest.json',
         ['torch','torchvision','transformers','qwen_vl_utils','av'],'vl-env','VL_EMBEDDING_REUSE.md'),
        ('torchvision-continuous-pose','COCO17 连续帧姿态实验','pose','torchvision-pose/weights-manifest.json',
         ['torch','torchvision','av'],'env','CONTINUOUS_POSE_REUSE.md'),
        ('bst-cg-ap-reuse','BST 单打离线粗球种实验','stroke_classification','bst/reuse-manifest.json',
         ['torch','av','positional_encodings','torchinfo'],'env','BST_REUSE.md'),
    ]
    for mid,name,capability,relative,modules,environment,report in specs:
        status,reason,weights='experimental','本地文件存在；执行时重验hash/版本，识别质量未经真值验证',[]
        manifest_path=resolve_relative(root,'models/weights/'+relative,owner='models')
        if not manifest_path.is_file():
            status,reason='not_installed','本环境缺少完整本地权重清单'
        else:
            try:
                if manifest_path.stat().st_size>100_000: raise ValueError('manifest too large')
                manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
                if manifest['schema_version']!='1.0': raise ValueError('manifest version')
                if mid=='tracknetv3-reuse':
                    from .tracknet_reuse import COMMIT
                    if manifest['source_commit']!=COMMIT: raise ValueError('source commit')
                    files=[manifest['code'],manifest['checkpoint']]
                elif mid=='qwen3-vl-embedding-2b':
                    from .vl_embedding_reuse import REVISION, FILES
                    if manifest['revision']!=REVISION: raise ValueError('source revision')
                    files=manifest['files']
                    prefix='models/weights/qwen3-vl-embedding-2b/'
                    if {f['relative_path'].removeprefix(prefix) for f in files}!=set(FILES):
                        raise ValueError('incomplete files')
                elif mid=='bst-cg-ap-reuse':
                    from .bst_reuse import COMMIT
                    if manifest['source_commit']!=COMMIT: raise ValueError('source commit')
                    files=[*manifest['code'].values(),manifest['checkpoint']]
                else:
                    files=manifest['files']
                    if not any(f['relative_path']=='models/weights/torchvision-pose/keypointrcnn_resnet50_fpn_coco-fc266e95.pth' for f in files):
                        raise ValueError('missing pose weights')
                for item in files:
                    path=resolve_relative(root,item['relative_path'],owner='models')
                    if not path.is_file() or path.stat().st_size!=item['size_bytes']:
                        raise ValueError('file missing or wrong size')
                    weights.append({k:item[k] for k in ('relative_path','sha256')})
            except (KeyError,ValueError,TypeError,OSError):
                status,reason='unavailable','权重清单损坏或文件不完整；未执行模型'
        missing=[module for module in modules if importlib.util.find_spec(module) is None]
        if missing: status,reason='not_installed','当前Python缺少依赖: '+', '.join(missing)
        entries.append({'schema_version':'1.0','model_id':mid,'version':'0.1.0','display_name':name,
            'capabilities':[capability],'status':status,'reason':reason,
            'entrypoint':['python','-m','packages.models','run','--request','{request}','--result','{result}'],
            'environment':{'kind':'wsl-conda','prefix':'/mnt/d/video/runtime/models/'+environment},
            'weights':weights,'parameters_schema':{'type':'object','required':['model_id'],
                'properties':{'model_id':{'const':mid}},'description':'See bounded adapter parameters in docs/models/'+report},
            'input_schema':'JobRequest@1.0','output_schema':'JobResult@1.0','supported_labels':[],
            'supported_camera_types':[],'evaluation_report':'docs/models/'+report,
            'license':{'code':'project license not declared','upstream':{'tracknetv3-reuse':'MIT','qwen3-vl-embedding-2b':'Apache-2.0','torchvision-continuous-pose':'BSD-3-Clause; COCO terms separate','bst-cg-ap-reuse':'MIT code; weights not separately stated'}[mid],
                       'media':'Source Asset rights remain separate'},
            'resource_requirements':{'device':'cuda','gpu_exclusive':True,'max_clip_ms':3000 if mid=='torchvision-continuous-pose' else 30000,
                                     'diagnostic_only':True,'accuracy_validated':False}})
    return entries
