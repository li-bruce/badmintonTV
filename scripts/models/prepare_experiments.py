"""Create traceable requests from the real library handoff; never fabricate labels."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from packages.models.protocol import atomic_write_json
from packages.models.storage import reserve

root = Path(os.environ.get('BTV_STORAGE_ROOT','D:/video' if os.name == 'nt' else '/mnt/d/video'))
assets = json.loads((root/'data/handoff/assets.v1.json').read_text(encoding='utf-8'))['assets']
with reserve(root,5_000_000):
    requests = root/'models/handoff/requests'
    requests.mkdir(parents=True,exist_ok=True)
    for model_id,operation in [('torchvision-keypointrcnn','pose'),('clip-frame-mean','video_embedding')]:
        asset = next(a for a in assets if '001951' in a['relative_path'])
        job = 'real-'+operation+'-001'
        request = {'schema_version':'1.0','job_id':job,'attempt_id':'attempt-01','operation':operation,
                   'assets':[asset],'parameters':{'model_id':model_id,'start_ms':0,'end_ms':asset['duration_ms'],'sample_fps':4,'max_frames':30},
                   'output_dir':f'models/handoff/{job}/attempt-01'}
        target = requests/(job+'.json')
        if not target.exists(): atomic_write_json(target,request)
    for model_id in ['query-rule-v1','qwen3-0.6b']:
        job = model_id+'-001'
        request = {'schema_version':'1.0','job_id':job,'attempt_id':'attempt-01','operation':'query_parse','assets':[],
                   'parameters':{'model_id':model_id,'text':'交叉步后退，随后起跳杀球，然后上网扑球'},
                   'output_dir':f'models/handoff/{job}/attempt-01'}
        target = requests/(job+'.json')
        if not target.exists(): atomic_write_json(target,request)
print(str(requests))
