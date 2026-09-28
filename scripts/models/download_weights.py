"""Bounded official-source downloads; immutable revision and SHA256 manifest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.models.storage import reserve
from packages.models.protocol import resolve_relative, atomic_write_json


def json_url(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('metadata too large')
    return json.loads(data)


def fetch(url, target, maximum, expected_sha=None, expected_blob=None, hash_prefix=None):
    if target.is_symlink():
        raise ValueError('weight target symlink is forbidden')
    if target.exists():
        if target.stat().st_size != maximum:
            raise ValueError('existing file size differs from expected; preserved')
        with target.open('rb') as existing:
            digest = hashlib.file_digest(existing, 'sha256').hexdigest()
        if expected_sha and digest != expected_sha:
            raise ValueError('existing weight hash mismatch')
        if hash_prefix and not digest.startswith(hash_prefix):
            raise ValueError('existing torch weight hash mismatch')
        if expected_blob:
            blob = hashlib.sha1(f'blob {maximum}\0'.encode()+target.read_bytes()).hexdigest()
            if blob != expected_blob:
                raise ValueError('existing HF git blob hash mismatch')
        return {'sha256': digest, 'size_bytes': target.stat().st_size}
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.partial')
    if temp.is_symlink():
        raise ValueError('partial symlink is forbidden')
    meta_path = temp.with_name(temp.name + '.source.json')
    metadata = {'url':url,'maximum':maximum,'sha256':expected_sha,'blob':expected_blob,'hash_prefix':hash_prefix}
    if meta_path.is_symlink():
        raise ValueError('partial metadata symlink is forbidden')
    if meta_path.exists() and json.loads(meta_path.read_text()) != metadata:
        raise ValueError('partial source identity changed; existing file preserved')
    if temp.exists() and not meta_path.exists():
        retained = temp.with_name(temp.name + '.unverified-' + uuid.uuid4().hex[:8])
        temp.rename(retained)
        print(json.dumps({'retained_unverified_partial':str(retained),'bytes':retained.stat().st_size}),flush=True)
    if not meta_path.exists():
        atomic_write_json(meta_path,metadata)
    digest = hashlib.sha256()
    count = 0
    if temp.exists():
        with temp.open('rb') as partial:
            while chunk := partial.read(1024*1024):
                digest.update(chunk)
                count += len(chunk)
        if count > maximum:
            raise ValueError('existing partial exceeds limit; preserved for inspection')
        print(json.dumps({'resume_file':target.name,'existing_bytes':count}),flush=True)
    if count != maximum:
        request = urllib.request.Request(url,headers={'Range':f'bytes={count}-'} if count else {})
        # An authenticated zero-byte partial can remain after a first-read
        # timeout. Its source metadata was checked above; append mode also
        # permits retrying that case without replacing an unknown file.
        with urllib.request.urlopen(request, timeout=45) as response, temp.open('ab' if temp.exists() else 'xb') as output:
            if count and (response.status != 206 or not response.headers.get('Content-Range','').startswith(f'bytes {count}-')):
                raise ValueError('server did not honor bounded resume; partial preserved')
            length = response.headers.get('Content-Length')
            if length and int(length) + count > maximum:
                raise ValueError('remote file exceeds reserved byte limit')
            while chunk := response.read(min(1024 * 1024, maximum - count + 1)):
                count += len(chunk)
                if count > maximum:
                    raise ValueError('actual download byte limit exceeded')
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
    if expected_sha and digest.hexdigest() != expected_sha:
        raise ValueError('download SHA256 mismatch; partial retained')
    if hash_prefix and not digest.hexdigest().startswith(hash_prefix):
        raise ValueError('official torch hash prefix mismatch')
    if count != maximum:
        raise ValueError('download size differs from expected; partial retained')
    if expected_blob and hashlib.sha1(f'blob {count}\0'.encode()+temp.read_bytes()).hexdigest() != expected_blob:
        raise ValueError('HF git blob hash mismatch')
    os.link(temp, target)
    temp.unlink()
    print(json.dumps({'file': target.name, 'bytes': count}), flush=True)
    return {'sha256': digest.hexdigest(), 'size_bytes': count}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/mnt/d/video')
    parser.add_argument('--model', choices=['qwen','pose','clip'], required=True)
    args = parser.parse_args()
    root = Path(args.root)
    manifest = {'schema_version': '1.0', 'files': []}
    if args.model == 'pose':
        filename = 'keypointrcnn_resnet50_fpn_coco-fc266e95.pth'
        url = 'https://download.pytorch.org/models/' + filename
        with urllib.request.urlopen(urllib.request.Request(url,method='HEAD'),timeout=45) as response:
            length = int(response.headers['Content-Length'])
        if not 0 < length <= 250_000_000:
            raise ValueError('torch weight outside expected size bound')
        entries = [{'name':filename,'url':url,'maximum':length,'hash_prefix':'fc266e95'}]
        folder = resolve_relative(root,'models/weights/torchvision-pose',owner='models')
        manifest.update(source='https://github.com/pytorch/vision', revision='v0.22.1',
                        license_url='https://github.com/pytorch/vision/blob/v0.22.1/LICENSE',
                        weight_license_note='COCO pretrained; dataset/image terms separate from code BSD-3-Clause')
    else:
        repo = 'Qwen/Qwen3-0.6B' if args.model == 'qwen' else 'openai/clip-vit-base-patch32'
        meta = json_url('https://huggingface.co/api/models/' + repo + '?blobs=true')
        revision = meta['sha']
        wanted = (['config.json','generation_config.json','tokenizer.json','tokenizer_config.json','vocab.json','merges.txt','model.safetensors']
                  if args.model == 'qwen' else ['config.json','preprocessor_config.json','tokenizer_config.json','special_tokens_map.json','vocab.json','merges.txt','pytorch_model.bin'])
        entries = []
        files = {f['rfilename']: f for f in meta['siblings']}
        for name in wanted:
            info = files[name]
            entries.append({'name': name, 'url': f'https://huggingface.co/{repo}/resolve/{revision}/{name}',
                            'maximum': info['size'], 'expected_sha': info.get('lfs',{}).get('sha256'),
                            'expected_blob':None if info.get('lfs') else info.get('blobId')})
        folder = resolve_relative(root,'models/weights/' + ('qwen3-0.6b' if args.model == 'qwen' else 'clip-vit-base-patch32'),owner='models')
        manifest.update(source='https://huggingface.co/' + repo, revision=revision,
                        license_url=f'https://huggingface.co/{repo}/blob/{revision}/README.md')
    with reserve(root, sum(e['maximum'] for e in entries) + 5_000_000):
        for entry in entries:
            target_file = resolve_relative(root,(folder / entry['name']).relative_to(root).as_posix(),owner='models')
            result = fetch(entry['url'], target_file, entry['maximum'], entry.get('expected_sha'),entry.get('expected_blob'),entry.get('hash_prefix'))
            manifest['files'].append({'relative_path': (folder / entry['name']).relative_to(root).as_posix(), **result,
                                      'source_url':entry['url'], 'license_url':manifest['license_url']})
        target = folder / 'weights-manifest.json'
        if not target.exists():
            atomic_write_json(target,manifest)
    print(json.dumps({'manifest':str(target), 'revision':manifest['revision']}))


if __name__ == '__main__':
    main()
