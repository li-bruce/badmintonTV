"""Plot measured COCO17 detections on one source frame for human QA."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from packages.models.protocol import resolve_relative, storage_root
from packages.models.storage import reserve
from packages.models.inference import decode_samples

parser = argparse.ArgumentParser()
parser.add_argument('--request',required=True)
parser.add_argument('--features',required=True)
parser.add_argument('--output',required=True,help='models/ relative PNG, must not exist')
parser.add_argument('--time-ms',type=int,default=1000)
args = parser.parse_args()
root = storage_root()
request = json.loads(Path(args.request).read_text())
features = json.loads(Path(args.features).read_text())
asset = request['assets'][0]
if features.get('asset_id') != asset['asset_id'] or features.get('source_sha256') != asset['sha256']:
    raise ValueError('features do not reference this source asset')
row = min(features['frames'],key=lambda f:abs(f['source_ms']-args.time_ms))
source = resolve_relative(root,asset['relative_path'])
with source.open('rb') as stream:
    if hashlib.file_digest(stream,'sha256').hexdigest() != asset['sha256']:
        raise ValueError('source asset hash mismatch')
frames,_,_ = decode_samples(source,asset,{'start_ms':row['source_ms'],'end_ms':min(asset['duration_ms'],row['source_ms']+100),'sample_fps':1,'max_frames':1})
if frames[0][1] != row['pts'] or frames[0][2] != row['time_base']:
    raise ValueError('decoded source PTS does not match measured pose frame')
from PIL import ImageDraw
picture = frames[0][3]
draw = ImageDraw.Draw(picture)
edges = [(5,7),(7,9),(6,8),(8,10),(5,6),(5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16)]
colors = ['#ff4c4c','#4cffff','#ffe44c','#ff70ff']
for i,det in enumerate(row['detections']):
    color=colors[i%len(colors)]
    draw.rectangle(det['box_xyxy'],outline=color,width=3)
    draw.text((det['box_xyxy'][0],max(0,det['box_xyxy'][1]-14)),f'detection {i}; identity unknown',fill=color)
    points=det['keypoints_xyv']
    for a,b in edges:
        draw.line((points[a][0],points[a][1],points[b][0],points[b][1]),fill=color,width=2)
    for x,y,_ in points:
        draw.ellipse((x-3,y-3,x+3,y+3),fill=color)
draw.text((8,8),f'COCO17 preannotation, source {row["source_ms"]}ms; NOT action labels',fill='white',stroke_width=1,stroke_fill='black')
target=resolve_relative(root,args.output,owner='models')
# Encode the bounded 4K source frame before disk reservation, so PNG size is
# known. The original 5 MB estimate was 31 KB too small for one doubles frame.
buffer = io.BytesIO()
picture.save(buffer,format='PNG')
payload = buffer.getvalue()
if len(payload) > 32_000_000:
    raise ValueError('preview PNG exceeds 32 MB bound')
with reserve(root,len(payload)):
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as output:
        output.write(payload)
print(str(target))
