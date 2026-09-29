"""Bounded official TrackNet code/checkpoints; public Drive confirmation only.

No upstream code is executed. Checkpoint publisher does not provide a digest;
the locally computed SHA256 is provenance, not a claim of publisher attestation.
"""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import stat
import sys
import time
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from packages.models.protocol import atomic_write_json, resolve_relative, storage_root
from packages.models.storage import reserve
from scripts.models.download_weights import fetch, json_url

COMMIT='6eda442ada1740573f200f836d93edc9a541ee86'
FILE_ID='1CfzE87a0f6LhBp0kniSl1-89zaLCZ8cA'


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__(); self.action=None; self.fields={}; self.inside=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form' and a.get('id')=='download-form':
            self.action=a.get('action'); self.inside=True
        if self.inside and tag=='input' and a.get('type')=='hidden':
            self.fields[a.get('name')]=a.get('value')
    def handle_endtag(self,tag):
        if tag=='form': self.inside=False


def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def extract_verified(z, info, target):
    """Verify existing content against ZIP bytes, or publish exclusively."""
    if target.is_symlink():
        raise ValueError('linked extraction target refused')
    with z.open(info) as source:
        expected = hashlib.file_digest(source, 'sha256').hexdigest()
    if target.exists():
        if target.stat().st_size != info.file_size or digest(target) != expected:
            raise ValueError('existing checkpoint differs from archive; preserved')
        return expected
    partial = target.with_name(target.name + '.extract.partial')
    with z.open(info) as source, partial.open('xb') as out:
        count = 0
        while block := source.read(65536):
            count += len(block)
            if count > info.file_size:
                raise ValueError('extraction bound exceeded')
            out.write(block)
        out.flush(); os.fsync(out.fileno())
    if count != info.file_size or digest(partial) != expected:
        raise ValueError('checkpoint extraction incomplete; partial preserved')
    os.link(partial, target)
    partial.unlink()
    return expected


def public_drive(file_id,target,maximum):
    """Follow the displayed anonymous Download anyway form; no auth/limit bypass."""
    source=f'https://drive.google.com/uc?export=download&id={file_id}'
    marker=target.with_name(target.name+'.source.json')
    if target.exists():
        saved=json.loads(marker.read_text())
        if saved['file_id']!=file_id or target.stat().st_size>maximum or digest(target)!=saved['sha256']:
            raise ValueError('existing public download differs; preserved')
        return saved
    response=urllib.request.urlopen(source,timeout=30)
    if 'text/html' in response.headers.get('Content-Type',''):
        page=response.read(64_001); response.close()
        if len(page)>64_000: raise ValueError('Drive confirmation exceeds bound')
        form=DownloadForm(); form.feed(page.decode('utf-8'))
        if form.action!='https://drive.usercontent.google.com/download' or form.fields.get('id')!=file_id:
            raise ValueError('Public download not available: no normal Drive download form; no bypass attempted')
        if set(form.fields)-{'id','export','confirm','uuid','at'}:
            raise ValueError('unrecognized download form')
        response=urllib.request.urlopen(form.action+'?'+urllib.parse.urlencode(form.fields),timeout=30)
    if 'text/html' in response.headers.get('Content-Type',''):
        response.close(); raise ValueError('Drive returned restriction/error HTML; not a checkpoint')
    length=response.headers.get('Content-Length')
    if length and not 0<int(length)<=maximum:
        response.close(); raise ValueError('remote file exceeds finite reserved limit')
    partial=target.with_name(target.name+'.partial')
    target.parent.mkdir(parents=True,exist_ok=True)
    count=0; sha=hashlib.sha256(); started=time.monotonic()
    with response, partial.open('xb') as out:
        while True:
            block=response.read(min(65536,maximum-count+1))
            if not block: break
            count+=len(block)
            if count>maximum or time.monotonic()-started>1800:
                raise ValueError('public download byte/time bound exceeded; partial retained')
            out.write(block); sha.update(block)
    if not count or (length and count!=int(length)):
        raise ValueError('incomplete public download; partial retained')
    if target.exists(): raise FileExistsError('target appeared during download')
    os.link(partial, target)
    partial.unlink()
    info={'file_id':file_id,'source_url':f'https://drive.google.com/file/d/{file_id}/view',
          'size_bytes':count,'sha256':sha.hexdigest(),'publisher_hash_available':False,
          'download_access':'anonymous public download; followed displayed normal confirmation'}
    atomic_write_json(marker,info)
    return info


def main():
    root=storage_root(); files={}
    with reserve(root,500_000_000):
        upstream=f'models/upstream/tracknetv3/{COMMIT}'
        for name in ['model.py','LICENSE','README.md','dataset.py','predict.py','test.py']:
            meta=json_url(f'https://api.github.com/repos/qaz812345/TrackNetV3/contents/{name}?ref={COMMIT}')
            if meta.get('type')!='file' or not 0<meta['size']<2_000_000:
                raise ValueError('unexpected upstream source metadata')
            url=f'https://raw.githubusercontent.com/qaz812345/TrackNetV3/{COMMIT}/{name}'
            target=resolve_relative(root,upstream+'/'+name,owner='models')
            info=fetch(url,target,meta['size'],expected_blob=meta['sha'])
            files[name]={'relative_path':target.relative_to(root).as_posix(),'source_url':url,**info}
        archive=resolve_relative(root,'models/weights/tracknetv3/TrackNetV3_ckpts.zip',owner='models')
        acquisition=public_drive(FILE_ID,archive,200_000_000)
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist()
            if len(infos)>30 or sum(i.file_size for i in infos)>250_000_000:
                raise ValueError('checkpoint archive extraction bound exceeded')
            chosen={}
            for info in infos:
                p=Path(info.filename)
                if info.is_dir(): continue
                if p.is_absolute() or '..' in p.parts or '\\' in info.filename or stat.S_ISLNK(info.external_attr>>16):
                    raise ValueError('unsafe checkpoint archive entry')
                if p.name in {'TrackNet_best.pt','InpaintNet_best.pt'}:
                    if p.name in chosen: raise ValueError('duplicate checkpoint name')
                    chosen[p.name]=info
            if set(chosen)!={'TrackNet_best.pt','InpaintNet_best.pt'}:
                raise ValueError('expected official checkpoint names missing')
            checkpoints={}
            for name,info in chosen.items():
                target=archive.parent/name
                checkpoint_hash = extract_verified(z, info, target)
                checkpoints[name]={'relative_path':target.relative_to(root).as_posix(),
                    'size_bytes':target.stat().st_size,'sha256':checkpoint_hash}
        manifest={'schema_version':'1.0','source_commit':COMMIT,'code':files['model.py'],
            'checkpoint':checkpoints['TrackNet_best.pt'],'inpaint_checkpoint':checkpoints['InpaintNet_best.pt'],
            'license':'MIT','license_url':files['LICENSE']['source_url'],'checkpoint_url':acquisition['source_url'],
            'acquisition':acquisition,'review_sources':files,'publisher_hash_available':False}
        output=archive.parent/'reuse-manifest.json'
        if output.exists():
            if json.loads(output.read_text())!=manifest: raise ValueError('existing manifest differs')
        else: atomic_write_json(output,manifest)
        print(json.dumps(manifest,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
