import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from packages.models.protocol import atomic_write_json, storage_root
from packages.models.storage import reserve

root = storage_root()
asset = json.loads((root/'data/handoff/assets.doubles.v1.json').read_text())['assets'][0]
request = {'schema_version':'1.0','job_id':'real-pose-doubles-001','attempt_id':'attempt-01','operation':'pose',
           'assets':[asset],'parameters':{'model_id':'torchvision-keypointrcnn','start_ms':0,'end_ms':asset['duration_ms'],
                                         'sample_fps':2,'max_frames':10},
           'output_dir':'models/handoff/real-pose-doubles-001/attempt-01'}
with reserve(root,1_000_000):
    atomic_write_json(root/'models/handoff/requests/real-pose-doubles-001.json',request)
