"""Bounded public BST source and coarse-stroke checkpoint acquisition."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from packages.models.protocol import atomic_write_json, resolve_relative, storage_root
from packages.models.storage import reserve
from scripts.models.download_weights import fetch, json_url
from scripts.models.acquire_tracknet_reuse import public_drive

COMMIT='fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df'
REPO='Va6lue/BST-Badminton-Stroke-type-Transformer'
FILE_ID='1snqpEEww-GG6xFUBzkuctYAPHcBP360B'
NAMES=['stroke_classification/model/bst.py','stroke_classification/model/tempose.py','LICENSE','README.md']

def main():
    root=storage_root(); code={}; review={}
    with reserve(root,30_000_000):
        for name in NAMES:
            meta=json_url(f'https://api.github.com/repos/{REPO}/contents/{name}?ref={COMMIT}')
            if meta.get('type')!='file' or not 0<meta['size']<500_000:
                raise ValueError('unexpected upstream source metadata')
            url=f'https://raw.githubusercontent.com/{REPO}/{COMMIT}/{name}'
            target=resolve_relative(root,f'models/upstream/bst/{COMMIT}/{name}',owner='models')
            info=fetch(url,target,meta['size'],expected_blob=meta['sha'])
            item={'relative_path':target.relative_to(root).as_posix(),'source_url':url,**info}
            review[name]=item
            if name.endswith('.py'): code[Path(name).name]=item
        target=resolve_relative(root,'models/weights/bst/bst_CG_AP_JnB_bone_between_2_hits_with_max_limits_seq_100_merged_2.pt',owner='models')
        acquisition=public_drive(FILE_ID,target,8_000_000)
        if acquisition['size_bytes']!=7_514_133:
            raise ValueError('public checkpoint differs from reviewed size; preserved')
        manifest={'schema_version':'1.0','source_commit':COMMIT,'license':'MIT',
            'architecture':'BST_CG_AP','pose_style':'JnB_bone','seq_len':100,'n_classes':25,
            'code':code,'checkpoint':{'relative_path':target.relative_to(root).as_posix(),
                'sha256':acquisition['sha256'],'size_bytes':acquisition['size_bytes'],
                'source_url':acquisition['source_url'],'drive_file_id':FILE_ID},
            'weight_license_status':'not_separately_stated','review_sources':review,
            'acquisition':acquisition}
        output=target.parent/'reuse-manifest.json'
        if output.exists():
            if json.loads(output.read_text())!=manifest: raise ValueError('existing manifest differs; preserved')
        else: atomic_write_json(output,manifest)
        print(json.dumps(manifest),flush=True)

if __name__=='__main__': main()
