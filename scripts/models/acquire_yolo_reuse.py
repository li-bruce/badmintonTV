"""Official fixed YOLO pose package/checkpoint; no execution on download."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from packages.models.protocol import atomic_write_json, resolve_relative, storage_root
from packages.models.storage import reserve
from scripts.models.download_weights import fetch

WHEEL_URL='https://files.pythonhosted.org/packages/19/62/aede3a7915ec845107a9a74f2f4a67f2b2971903e656c2ca38aa15751678/ultralytics-8.3.203-py3-none-any.whl'
WEIGHT_URL='https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.pt'

def main():
    root=storage_root()
    with reserve(root,20_000_000):
        wheel=resolve_relative(root,'models/upstream/ultralytics/8.3.203/ultralytics-8.3.203-py3-none-any.whl',owner='models')
        package=fetch(WHEEL_URL,wheel,1_072_183,expected_sha='7103994cfb14f8779fa0a6b7e7908708137309645a3723dbe2ceb73ea7afc63c')
        weight=resolve_relative(root,'models/weights/yolo11n-pose/yolo11n-pose.pt',owner='models')
        # GitHub release does not publish a digest for this asset. Preserve
        # the local observed hash explicitly, never call it publisher verified.
        checkpoint=fetch(WEIGHT_URL,weight,6_255_593,
                         expected_sha='869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0')
        manifest={'schema_version':'1.0','model_id':'yolo11n-pose-bytetrack','package_version':'8.3.203',
            'license':'AGPL-3.0','license_url':'https://github.com/ultralytics/ultralytics/blob/v8.3.203/LICENSE',
            'license_note':'Enterprise licensing is a separate option; local research does not clear closed-source public deployment or video rights',
            'package':{'relative_path':wheel.relative_to(root).as_posix(),'source_url':WHEEL_URL,**package},
            'checkpoint':{'relative_path':weight.relative_to(root).as_posix(),'source_url':WEIGHT_URL,**checkpoint},
            'checkpoint_publisher_hash_available':False}
        output=weight.parent/'reuse-manifest.json'
        if output.exists():
            if json.loads(output.read_text())!=manifest: raise ValueError('existing manifest differs; preserved')
        else: atomic_write_json(output,manifest)
        print(json.dumps(manifest),flush=True)

if __name__=='__main__': main()
