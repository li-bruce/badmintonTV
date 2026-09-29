"""Local control plane. Media computation belongs to packages.runtime.worker."""
import json
import hashlib
import mimetypes
import math
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from packages.contracts import AssetManifest, Candidate, Event, EventManifest, QuerySpec, Timeline
from packages.runtime import Queue, CapacityLedger, resolve_relative_path
from packages.runtime.storage import resolve_owner_path
from packages.runtime.artifact_identity import ArtifactIdentityError, hash_identity, check_proof
from .artifact_response import VerifiedArtifactResponse
from .retrieval import parse_rules, search, merge_segments
from .store import Conflict, Store


def uid(prefix):
    return prefix + '-' + uuid.uuid4().hex[:16]


def create_app(storage_root=None, db_path=None):
    root = Path(storage_root or os.getenv('BTV_STORAGE_ROOT', 'D:/video' if os.name == 'nt' else '/mnt/d/video')).resolve()
    state = Path(db_path or os.getenv('BTV_DB_PATH', str(root/'platform'/'platform.sqlite3')))
    store = Store(state, root)
    queue = Queue(state.with_name('runtime.sqlite3'))
    queue.bind_business_database(state)
    app = FastAPI(title='badmintonTV 本地工作台', version='0.1.0')
    app.state.store, app.state.queue, app.state.storage_root = store, queue, root
    templates = Jinja2Templates(directory=str(Path(__file__).parent/'templates'))
    app.mount('/static', StaticFiles(directory=Path(__file__).parent/'static'), name='static')
    code_snapshot={'platform_version':'0.1.0','git_revision':os.getenv('BTV_CODE_REVISION','unknown'),
                   'source_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ('main.py','store.py','retrieval.py')}}

    def enqueue(operation,payload,**options):
        return queue.enqueue(operation,{**payload,'platform_snapshot':code_snapshot},**options)

    @app.middleware('http')
    async def local_only(request, call_next):
        if request.url.hostname not in ('127.0.0.1','localhost','::1','testserver'):
            return JSONResponse({'detail':'仅允许本机访问'}, status_code=403)
        origin = request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'跨来源写入被拒绝'}, status_code=403)
        return await call_next(request)

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse({'detail':str(exc)},status_code=409)

    @app.exception_handler(ArtifactIdentityError)
    async def artifact_identity_handler(request, exc):
        return JSONResponse({'detail':str(exc)},status_code=409)

    @app.exception_handler(ValidationError)
    async def validation_handler(request, exc):
        return JSONResponse({'detail':json.loads(exc.json(include_url=False,include_context=False))},status_code=422)

    @app.exception_handler(ValueError)
    async def value_handler(request, exc):
        return JSONResponse({'detail':str(exc)},status_code=422)

    @app.exception_handler(KeyError)
    async def key_handler(request, exc):
        return JSONResponse({'detail':'不存在的资源'},status_code=404)

    def asset_or_404(id):
        a = store.asset(id)
        if not a:
            raise HTTPException(404,'素材不存在')
        return a

    def production_assets(assets):
        from packages.contracts import assert_production_allowed
        assert_production_allowed(assets,root,source_assets=store._raw_assets())

    def production_job(j):
        payload=j['payload']
        snapshots=payload.get('assets',[]) + ([payload['asset']] if payload.get('asset') else [])
        production_assets(snapshots)
        for a in snapshots:
            if a.get('asset_id'):
                store.asset(a['asset_id'])  # Recheck current authoritative metadata.
        if payload.get('relative_path'):
            production_assets([{**payload.get('asset_metadata',{}),'relative_path':payload['relative_path']}])
        if j.get('result'):
            result=j['result']
            production_assets(result.get('assets',[]) + ([result['asset']] if result.get('asset') else []))

    def resource(kind,id):
        obj = store.get(kind,id)
        if obj is None:
            raise HTTPException(404,'资源不存在')
        return obj

    def validate_event(event):
        e = Event.model_validate(event).model_dump(mode='json')
        a = asset_or_404(e['asset_id'])
        if e['end_ms'] > a['duration_ms'] or e['match_id'] != a['match_id']:
            raise ValueError('标注必须位于同场原片有效时间内')
        return e

    @app.get('/',response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request=request,name='index.html',context={})

    @app.get('/api/v1/health')
    def health():
        return {'status':'ready','schema_version':'1.0','database':str(state),'storage_root':str(root),
                'torch_loaded':'torch' in sys.modules,'worker_required':True}

    @app.get('/api/v1/workflow')
    def workflow():
        events = store.events()
        return {'assets':len(store.assets()),'events':len(events),'confirmed_events':sum(e['review_status']=='confirmed' and e.get('reviewer_type')=='human' for e in events),
                'timelines':len(store.list('timeline')),'jobs':queue.list(limit=30),
                'stages':[{'stage':'导入','status':'ready'},{'stage':'人工标注/检索','status':'ready'},
                          {'stage':'模型分析','status':'adapter_required'},{'stage':'渲染','status':'adapter_required'}]}

    @app.get('/api/v1/libraries')
    def libraries():
        return store.list('library')

    @app.post('/api/v1/libraries',status_code=201)
    def add_library(body:dict):
        name = str(body.get('name','')).strip()
        if not name or len(name)>200:
            raise ValueError('填写资料库名称（最多200字）')
        obj = {'library_id':body.get('library_id') or uid('library'),'name':name,'storage_root':str(root)}
        return store.put('library',obj['library_id'],obj)

    @app.get('/api/v1/assets')
    def assets(library_id:str|None=None, player_id:str|None=None, tag:str|None=None, q:str|None=None):
        result=store.assets(library_id)
        if player_id:
            event_ids={e['asset_id'] for e in store.events() if e.get('player_id')==player_id}
            result=[a for a in result if a['asset_id'] in event_ids or any(p['player_id']==player_id for p in a['players'])]
        if tag:
            ids={e['asset_id'] for e in store.events() if tag in e['labels'].values()}
            result=[a for a in result if a['asset_id'] in ids]
        return [a for a in result if not q or q.casefold() in (a['title']+' '+a['match_id']).casefold()]

    @app.post('/api/v1/assets/import')
    def import_manifest(body:dict):
        library_id=body['library_id']
        resource('library',library_id)
        manifest=AssetManifest.model_validate(body['manifest']).model_dump(mode='json')
        production_assets(manifest['assets'])
        if len(manifest['assets'])>1000:
            raise ValueError('单次清单最多1000条素材')
        for a in manifest['assets']:
            p=resolve_relative_path(root,a['relative_path'])
            if not p.is_file() or p.stat().st_size!=a['size_bytes']:
                raise ValueError('素材缺失或大小不符：'+a['asset_id'])
        if sum(a['size_bytes'] for a in manifest['assets'])>8_000_000:
            return JSONResponse(enqueue('verify_manifest',{'assets':manifest['assets'],'library_id':library_id}),status_code=202)
        # A bounded small manifest avoids queue overhead; larger media is hashed by the worker.
        identities={}; actual_assets=[]
        for a in manifest['assets']:
            path=resolve_relative_path(root,a['relative_path']); before=store._file_identity(path)
            with path.open('rb') as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if before!=store._file_identity(path):
                raise Conflict('SOURCE_CHANGED: 素材校验期间变化，未导入')
            actual_assets.append({**a,'sha256':digest})
            identities[a['asset_id']]=before
        production_assets(actual_assets)
        for declared,actual in zip(manifest['assets'],actual_assets):
            if actual['sha256'].lower()!=declared['sha256'].lower():
                raise ValueError('素材SHA-256不符，未导入：'+declared['asset_id'])
        return {'imported':store.import_assets(manifest['assets'],library_id,verified_identities=identities), 'integrity':'sha256_verified'}

    @app.post('/api/v1/assets/import-path',status_code=202)
    def import_path(body:dict):
        resource('library',body['library_id'])
        relative=str(body['relative_path'])
        production_assets([{**body.get('metadata',{}),'relative_path':relative}])
        if not resolve_relative_path(root,relative).is_file():
            raise ValueError('源文件不存在')
        return enqueue('probe',{'relative_path':relative,'asset_metadata':body.get('metadata',{}), 'library_id':body['library_id']},idempotency_key=body.get('idempotency_key'))

    @app.get('/api/v1/assets/{asset_id}/media')
    def media(asset_id:str):
        a=asset_or_404(asset_id)
        return FileResponse(store.verified_source_path(a),media_type=mimetypes.guess_type(a['relative_path'])[0] or 'application/octet-stream',filename=Path(a['relative_path']).name,content_disposition_type='inline',headers={'Cache-Control':'no-store'})

    def artifact_usage(j,a,digest):
        # Separate each declaration so a general layer cannot overwrite a
        # restriction. The own-hash gate uses proven bytes, never claimed SHA.
        result=j.get('result') or {}
        base={'relative_path':a['relative_path'],'sha256':digest}
        declarations=[a,result]
        for value in (a.get('producer'),result.get('producer'),result.get('preview'),result.get('frame')):
            if isinstance(value,dict):
                declarations.append(value)
        records=[]
        for declaration in declarations:
            records.append({**base,**{key:declaration[key] for key in ('usage_scope','provenance') if key in declaration}})
            source={key:declaration[key] for key in ('source_asset_id','source_sha256') if key in declaration}
            if source:
                records.append({**base,'provenance':source})
        sources=[*store._raw_assets(),*j['payload'].get('assets',[]),*result.get('assets',[])]
        sources.extend(value for value in (j['payload'].get('asset'),result.get('asset')) if value)
        from packages.contracts import assert_production_allowed
        assert_production_allowed(records,root,source_assets=sources)

    def verified_artifact(j,a):
        path=resolve_relative_path(root,a['relative_path'],must_exist=True)
        proof=queue.artifact_identity(j['job_id'],j['attempt'],a['artifact_id'])
        if proof is None:
            # A legacy result's embedded proof/declared hash grants no trust.
            # Only a bounded read may upgrade old small artifacts in the Web.
            proof={**hash_identity(path,max_bytes=8_000_000),'relative_path':a['relative_path']}
            artifact_usage(j,a,proof['sha256'])
            if any(proof[key]!=a.get(key) for key in ('relative_path','sha256','size_bytes')):
                raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物实际内容与声明不一致')
            check_proof(path,proof)
            queue.remember_legacy_artifact_identity(j['job_id'],j['attempt'],a,proof)
        else:
            if any(proof[key]!=a.get(key) for key in ('relative_path','sha256','size_bytes')):
                raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物声明与可信记录不一致')
            check_proof(path,proof)
            artifact_usage(j,a,proof['sha256'])
        check_proof(path,proof)
        return path,proof

    def preview_artifact(selected,relative):
        matches=[a for a in (selected.get('result') or {}).get('artifacts',[]) if a.get('relative_path')==relative]
        if len(matches)!=1:
            raise ArtifactIdentityError('ARTIFACT_REVERIFY_REQUIRED: 预览路径没有唯一产物记录，请重新生成')
        return verified_artifact(selected,matches[0])

    def preview_job(asset_id, job_id=None):
        asset=asset_or_404(asset_id)
        if job_id:
            selected=queue.get(job_id)
            if not selected or selected['operation']!='media_proxy' or selected['payload'].get('asset',{}).get('asset_id')!=asset_id:
                raise HTTPException(404,'预览任务与当前素材不匹配')
        else:
            with queue.connection() as db:
                found=db.execute("SELECT job_id FROM jobs WHERE operation='media_proxy' AND json_extract(payload,'$.asset.asset_id')=? ORDER BY created_at DESC LIMIT 1",(asset_id,)).fetchone()
            selected=queue.get(found[0]) if found else None
        if selected:
            production_job(selected)
            snapshot=selected['payload']['asset']
            if snapshot['sha256']!=asset['sha256'] or snapshot['relative_path']!=asset['relative_path']:
                raise Conflict('素材已变化，请重新创建预览')
        return selected

    def ready_preview(asset_id, job_id):
        if not isinstance(job_id,str) or not job_id.strip():
            raise ValueError('必须指定已完成预览的preview_job_id')
        selected=preview_job(asset_id,job_id)
        if selected['status']!='succeeded' or not (selected.get('result') or {}).get('preview'):
            raise Conflict('兼容预览尚未完成')
        p=selected['result']['preview']; source=selected['payload']['asset']
        if p.get('source_asset_id')!=source['asset_id'] or p.get('source_sha256')!=source['sha256']:
            raise Conflict('预览结果来源与任务素材不匹配')
        prefix=f"platform/jobs/{selected['job_id']}/attempt-{selected['attempt']}/"
        for key in ('relative_path','index_relative_path','thumbnail_relative_path'):
            relative=p.get(key)
            if not isinstance(relative,str) or not relative.startswith(prefix):
                raise ValueError('预览产物必须属于当前任务attempt目录')
            resolve_owner_path(root,relative,'platform',must_exist=True)
            production_assets([{'relative_path':relative,'usage_scope':p.get('usage_scope','general'),'provenance':{'source_asset_id':source['asset_id'],'source_sha256':source['sha256']}}])
            preview_artifact(selected,relative)
        return selected,p

    @app.post('/api/v1/assets/{asset_id}/preview',status_code=202)
    def create_preview(asset_id:str,body:dict):
        from packages.runtime.media_proxy import estimate_peak_bytes
        payload={'asset':asset_or_404(asset_id),**{key:body[key] for key in ('start_ms','end_ms','max_height','max_fps') if key in body}}
        estimate_peak_bytes(payload)  # Validate bounds; the worker owns actual reservation.
        return enqueue('media_proxy',payload,idempotency_key=body.get('idempotency_key'))

    @app.get('/api/v1/assets/{asset_id}/preview')
    def get_preview(asset_id:str):
        selected=preview_job(asset_id)
        if not selected:
            return {'status':'not_ready','job_id':None}
        response={'status':selected['status'],'job_id':selected['job_id'],'error':selected.get('error')}
        if selected['status']=='succeeded':
            _,p=ready_preview(asset_id,selected['job_id']); base=f"/api/v1/assets/{asset_id}/previews/{selected['job_id']}"
            response['preview']={**p,'media_url':base+'/media','frame_map_url':base+'/frame-map','source_frames_url':base+'/source-frames','thumbnail_url':base+'/thumbnails'}
        return response

    @app.get('/api/v1/assets/{asset_id}/previews/{job_id}/frame-map')
    def preview_map(asset_id:str,job_id:str,offset_frame:int=0,limit:int=1000,at_ms:float|None=None):
        from packages.runtime.media_proxy import read_frame_map
        selected,p=ready_preview(asset_id,job_id)
        path,identity=preview_artifact(selected,p['index_relative_path'])
        result=read_frame_map(path,offset_frame=offset_frame,limit=limit,at_ms=at_ms)
        check_proof(path,identity)
        return result

    @app.get('/api/v1/assets/{asset_id}/previews/{job_id}/source-frames')
    def preview_source_frames(asset_id:str,job_id:str,offset_frame:int=0,limit:int=128,at_ms:float|None=None):
        from packages.runtime.media_proxy import read_source_frames
        selected,p=ready_preview(asset_id,job_id)
        path,identity=preview_artifact(selected,p['index_relative_path'])
        result=read_source_frames(path,offset_frame=offset_frame,limit=limit,at_ms=at_ms)
        check_proof(path,identity)
        return result

    @app.head('/api/v1/assets/{asset_id}/previews/{job_id}/media')
    @app.get('/api/v1/assets/{asset_id}/previews/{job_id}/media')
    def preview_media(asset_id:str,job_id:str):
        selected,p=ready_preview(asset_id,job_id)
        path,identity=preview_artifact(selected,p['relative_path'])
        return VerifiedArtifactResponse(path,identity,media_type='video/mp4',headers={'Cache-Control':'no-store'})

    @app.head('/api/v1/assets/{asset_id}/previews/{job_id}/thumbnails')
    @app.get('/api/v1/assets/{asset_id}/previews/{job_id}/thumbnails')
    def preview_thumbnails(asset_id:str,job_id:str):
        selected,p=ready_preview(asset_id,job_id)
        path,identity=preview_artifact(selected,p['thumbnail_relative_path'])
        return VerifiedArtifactResponse(path,identity,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    @app.post('/api/v1/assets/{asset_id}/source-frame',status_code=202)
    def source_frame(asset_id:str,body:dict):
        from packages.runtime.media_proxy import estimate_peak_bytes
        _,p=ready_preview(asset_id,str(body.get('preview_job_id','')))
        number=body.get('source_frame_index')
        if type(number) is not int or not 0<=number<p['source_frame_count']:
            raise ValueError('source_frame_index必须是有效的0起始原片帧序号')
        payload={'asset':asset_or_404(asset_id),'source_frame_index':number,'index_relative_path':p['index_relative_path'],'preview_job_id':body['preview_job_id']}
        estimate_peak_bytes(payload,'exact_frame')
        return enqueue('exact_frame',payload)

    @app.head('/api/v1/assets/{asset_id}/thumbnail')
    @app.get('/api/v1/assets/{asset_id}/thumbnail')
    def thumbnail(asset_id:str):
        a=asset_or_404(asset_id)
        relative=a.get('probe',{}).get('thumbnail_relative_path')
        if not relative:
            raise HTTPException(404,'尚无缩略图，请运行探测任务')
        linked={'relative_path':relative,'provenance':{'source_asset_id':a['asset_id'],'source_sha256':a['sha256']}}
        production_assets([linked])
        path=resolve_relative_path(root,relative,must_exist=True)
        proof=hash_identity(path,max_bytes=8_000_000)
        production_assets([{**linked,'sha256':proof['sha256']}])
        check_proof(path,proof)
        return VerifiedArtifactResponse(path,proof,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    @app.get('/api/v1/assets/{asset_id}/frame-map')
    def frame_map(asset_id:str):
        from .frame_index import read_label_studio_frame_map
        a=asset_or_404(asset_id)
        index=a.get('probe',{}).get('pts_index') or {}
        if index.get('relative_path'):
            production_assets([{'relative_path':index['relative_path'],'sha256':index.get('sha256'),'provenance':{'source_asset_id':a['asset_id'],'source_sha256':a['sha256']}}])
        return read_label_studio_frame_map(a,root)

    @app.get('/api/v1/assets/{asset_id}/source-frames')
    def source_frame_page(asset_id:str,offset_frame:int=0,limit:int=128,at_ms:float|None=None):
        from .frame_index import read_source_frame_page
        a=asset_or_404(asset_id)
        index=a.get('probe',{}).get('pts_index') or {}
        if index.get('relative_path'):
            production_assets([{'relative_path':index['relative_path'],'sha256':index.get('sha256'),'provenance':{'source_asset_id':a['asset_id'],'source_sha256':a['sha256']}}])
        return read_source_frame_page(a,root,offset_frame=offset_frame,limit=limit,at_ms=at_ms)

    @app.get('/api/v1/players')
    def players():
        data={p['player_id']:p for a in store.assets() for p in a['players']}
        data.update({p['player_id']:p for p in store.list('player')})
        return list(data.values())

    @app.post('/api/v1/players')
    def add_player(body:dict):
        if not body.get('display_name'):
            raise ValueError('球员显示名称不能为空')
        p={'player_id':body.get('player_id') or uid('player'),'display_name':str(body['display_name']),
           'identity_status':body.get('identity_status','unconfirmed')}
        return store.put('player',p['player_id'],p)

    @app.get('/api/v1/events')
    def events(asset_id:str|None=None):
        return store.events(asset_id)

    @app.get('/api/v1/events/export')
    def export_events(asset_id:str|None=None):
        return {'schema_version':'1.0','events':store.events(asset_id)}

    @app.post('/api/v1/events')
    def save_event(body:dict):
        e=validate_event(body['event'])
        if not body.get('reviewer'):
            raise ValueError('须填写审阅者')
        reviewer_type=body.get('reviewer_type','human')
        if reviewer_type not in ('human','agent'):
            raise ValueError('reviewer_type 须为 human 或 agent')
        return store.save_event(e,body['expected_revision'],body['reviewer'],reviewer_type)

    @app.post('/api/v1/events/import')
    def import_events(body:dict):
        parsed=EventManifest.model_validate(body['manifest']).model_dump(mode='json')
        validated=[validate_event(e) for e in parsed['events']]
        expected=body.get('expected_revisions',{})
        return {'events':store.save_events([(e,expected.get(e['event_id'],0),body.get('reviewer','import'),body.get('reviewer_type','human')) for e in validated],actor='human')}

    @app.get('/api/v1/events/{event_id}/revisions')
    def revisions(event_id:str):
        return store.revisions(event_id)

    @app.post('/api/v1/queries/parse')
    async def parse(body:dict):
        if body.get('use_llm'):
            config=llm_config()
            secret=os.getenv(config['key_env'],'')
            if not config.get('model') or not config.get('base_url'):
                raise ValueError('尚未配置 LLM')
            payload={'model':config['model'],'messages':[{'role':'system','content':'把用户羽毛球检索条件转为JSON QuerySpec。只解析请求，不判断视频事实。严格遵守JSON Schema: '+json.dumps(QuerySpec.model_json_schema(),ensure_ascii=False)},
                  {'role':'user','content':str(body['text'])}], 'response_format':{'type':'json_object'}}
            try:
                async with httpx.AsyncClient(timeout=config['timeout'],follow_redirects=False) as client:
                    r=await client.post(config['base_url'].rstrip('/')+'/chat/completions',json=payload,headers={'Authorization':'Bearer '+secret} if secret else {})
                    r.raise_for_status()
                    output=json.loads(r.json()['choices'][0]['message']['content'])
                output['query_id']=uid('query')
                output['player_id']=body.get('player_id') or output.get('player_id')
                q=QuerySpec.model_validate(output).model_dump(mode='json')
            except (httpx.HTTPError,KeyError,ValueError) as exc:
                raise HTTPException(502,'LLM连接或结构化输出验证失败；可切换规则解析') from None
        else:
            q=QuerySpec.model_validate(parse_rules(str(body['text']),body.get('player_id'))).model_dump(mode='json')
        return q

    @app.post('/api/v1/queries/search')
    def search_events(body:dict):
        q=QuerySpec.model_validate(body).model_dump(mode='json')
        store.put('query',q['query_id'],q)
        result=[Candidate.model_validate(c).model_dump(mode='json') for c in search(q,store.events(),store.assets())]
        for candidate in result:
            store.put('candidate',candidate['candidate_id'],candidate)
        return {'query':q,'candidates':result,'limit':500,'rank_score_meaning':'仅供排序，不是准确率'}

    @app.post('/api/v1/candidates/{id}/confirm')
    def confirm(id:str,body:dict):
        candidate=resource('candidate',id)
        asset_or_404(candidate['asset_id'])
        if body.get('review_status') not in ('confirmed','rejected') or not body.get('reviewer'):
            raise ValueError('须明确确认/拒绝并填写审阅者')
        reviewer_type=body.get('reviewer_type','human')
        if reviewer_type not in ('human','agent'):
            raise ValueError('reviewer_type 须为 human 或 agent')
        from .store import now
        candidate.update({'review_status':body['review_status'],'reviewer':body['reviewer'],'reviewer_type':reviewer_type,'reviewed_at':now()})
        return store.put('candidate',id,candidate)

    @app.get('/api/v1/timelines')
    def timelines():
        return store.list('timeline')

    def render_options(timeline):
        current=store.get('render_options',timeline['timeline_id'])
        if current:
            return current
        fps=timeline['output']['fps']
        expected={'width':1080,'height':1920,'fps':fps,'video_codec':'h264','audio_codec':'aac'}
        return {'schema_version':'1.0','timeline_id':timeline['timeline_id'],'revision':0,'options':{
            'export_preset':f'portrait_1080p{int(fps)}' if fps in (30,60) and timeline['output']==expected else None,
            'safe_area':{'x':0.06,'y':0.10,'width':0.82,'height':0.78},'platform_profile':None}}

    def validate_render_options(options,timeline):
        if not isinstance(options,dict) or set(options)!={'export_preset','safe_area','platform_profile'}:
            raise ValueError('导出设置必须包含export_preset、safe_area、platform_profile')
        preset=options['export_preset']
        if preset not in (None,'portrait_1080p30','portrait_1080p60'):
            raise ValueError('仅支持portrait_1080p30或portrait_1080p60预设')
        if preset is not None:
            expected={'width':1080,'height':1920,'fps':30 if preset.endswith('30') else 60,'video_codec':'h264','audio_codec':'aac'}
            if timeline['output']!=expected:
                raise Conflict('preset_conflict: 时间线输出与预设不一致，请同步输出参数')
        safe=options['safe_area']
        if not isinstance(safe,dict) or set(safe)!={'x','y','width','height'} or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in safe.values()):
            raise ValueError('安全区必须包含0到1之间的有限x/y/width/height')
        if safe['width']<=0 or safe['height']<=0 or safe['x']+safe['width']>1 or safe['y']+safe['height']>1:
            raise ValueError('安全区必须位于完整输出画面内且有正面积')
        profile=options['platform_profile']
        if profile not in (None,'youtube_shorts'):
            raise ValueError('platform_profile仅支持null或youtube_shorts')
        # Renderer rechecks final frame-quantized duration; reject clear overruns early.
        duration=sum((s['out_ms']-s['in_ms'])/s['speed'] for s in timeline['segments'])
        if profile=='youtube_shorts' and duration>180000:
            raise ValueError('youtube_shorts输出不能超过180000ms')
        return {**options,'safe_area':dict(safe)}

    @app.get('/api/v1/timelines/{id}/render-options')
    def get_render_options(id:str):
        return render_options(resource('timeline',id))

    @app.put('/api/v1/timelines/{id}/render-options')
    def put_render_options(id:str,body:dict):
        timeline=resource('timeline',id)
        for segment in timeline['segments']:
            asset_or_404(segment['asset_id'])
        options=validate_render_options(body.get('options'),timeline)
        return store.save_render_options(id,options,body.get('expected_revision'))

    def timeline_digest(t):
        return hashlib.sha256(json.dumps(t,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

    def record_timeline_review(t, reviewers, candidates=None):
        from .store import now
        roles={r.get('reviewer_type') for r in reviewers}
        record={'timeline_sha256':timeline_digest(t),'reviewer_type':next(iter(roles)) if len(roles)==1 else 'mixed',
                'reviewers':reviewers,'reviewed_at':now(),'candidates':candidates or [],
                'event_revisions':{eid:store.event(eid)['revision'] for s in t['segments'] for eid in s['event_ids']}}
        return store.put('timeline_review',t['timeline_id'],record)

    def save_timeline(body):
        t=Timeline.model_validate(body).model_dump(mode='json')
        for s in t['segments']:
            a=asset_or_404(s['asset_id'])
            if s['out_ms']>a['duration_ms']:
                raise ValueError('剪辑结束超出原片')
            for event_id in s['event_ids']:
                event=store.event(event_id)
                if not event or event['asset_id']!=s['asset_id']:
                    raise ValueError('剪辑事件必须来自同一素材')
        return store.put('timeline',t['timeline_id'],t)

    @app.post('/api/v1/timelines')
    def put_timeline(body:dict):
        if 'timeline' in body:
            if not body.get('reviewer') or body.get('reviewer_type') not in ('human','agent'):
                raise ValueError('保存剪辑审核须填写审阅者及 human/agent 类型')
        t=save_timeline(body.get('timeline',body))
        if 'timeline' in body:
            record_timeline_review(t,[{'reviewer':body['reviewer'],'reviewer_type':body['reviewer_type']}])
        return t

    @app.post('/api/v1/timelines/from-candidates')
    def from_candidates(body:dict):
        segments=[]; selected=[]
        for id in body['candidate_ids']:
            c=resource('candidate',id)
            if c['review_status']!='confirmed':
                raise Conflict('先人工确认候选，再加入时间线')
            a=asset_or_404(c['asset_id'])
            selected.append(c)
            segments.append({'segment_id':uid('clip'),'asset_id':c['asset_id'],'in_ms':max(0,c['start_ms']-int(body.get('pre_ms',1000))),
              'out_ms':min(a['duration_ms'],c['end_ms']+int(body.get('post_ms',1000))),'speed':1.0,'event_ids':c['event_ids'],
              'fit':'contain','title':a['title'],'audio':'source','review_status':'confirmed'})
        merged=merge_segments(segments)
        t=save_timeline({'schema_version':'1.0','timeline_id':uid('timeline'),'title':body.get('title','羽毛球集锦'),
            'segments':merged,'output':{'width':1080,'height':1920,'fps':30,'video_codec':'h264','audio_codec':'aac'}})
        record_timeline_review(t,[{'reviewer':c.get('reviewer'),'reviewer_type':c.get('reviewer_type')} for c in selected],selected)
        return t

    @app.post('/api/v1/timelines/{id}/render',status_code=202)
    def render(id:str,body:dict):
        t=resource('timeline',id)
        research=body.get('research_preview',False) is True
        selection=store.get('timeline_review',id)
        selection_valid=bool(selection and selection['timeline_sha256']==timeline_digest(t))
        if not research and any(s['review_status']!='confirmed' for s in t['segments']):
            raise Conflict('导出前须确认所有片段')
        if not research:
            reviewed=[store.event(eid) for s in t['segments'] for eid in s['event_ids']]
            if not reviewed or any(not e or e['review_status']!='confirmed' or e.get('reviewer_type')!='human' for e in reviewed):
                raise Conflict('正式导出需要人工确认记录；可勾选待人工确认的本地研究样片')
            if not selection_valid or selection.get('reviewer_type')!='human' or any(selection['event_revisions'].get(e['event_id'])!=e['revision'] for e in reviewed):
                raise Conflict('剪辑或事件已变化，请由人类重新保存审核当前时间线')
            if any(resource('candidate',c['candidate_id'])!=c for c in selection.get('candidates',[])):
                raise Conflict('候选审核已变化，请重新确认当前剪辑')
        assets=[asset_or_404(aid) for aid in dict.fromkeys(s['asset_id'] for s in t['segments'])]
        editorial=selection if selection_valid else {'reviewer_type':'unknown','reason':'当前时间线没有对应审核记录'}
        from packages.runtime.worker import render_backend
        backend=render_backend()
        settings=render_options(t)
        options=validate_render_options(settings['options'],t)
        parameters={key:value for key,value in options.items() if key!='export_preset' or value is not None}
        return enqueue('render',{'assets':assets,'render_backend':backend,'gpu_required':backend in ('nvenc','auto'),
            'model_id':'render-nvenc' if backend in ('nvenc','auto') else 'render-cpu','render_options_revision':settings['revision'],'parameters':{**parameters,'timeline':t,'research_preview':research,
            'segment_options':{s['segment_id']:{'editorial_review':editorial} for s in t['segments']}}},idempotency_key=body.get('idempotency_key'))

    @app.get('/api/v1/models')
    def models():
        from packages.contracts import ModelManifest
        entries={m['model_id']:m for m in store.list('model')}
        configured=os.getenv('BTV_MODEL_CATALOG_PATH')
        if configured:
            path=Path(configured)
            if not path.is_file() or path.stat().st_size>16_000_000:
                raise ValueError('管理员模型目录不存在或超过16MB上限')
            catalog=json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(catalog,dict) or catalog.get('schema_version')!='1.0' or not isinstance(catalog.get('models'),list):
                raise ValueError('管理员模型目录须为schema_version=1.0/models列表')
            for item in catalog['models']:
                m=ModelManifest.model_validate(item).model_dump(mode='json')
                entries[m['model_id']]=m  # Local administrator catalog is current authority.
        result=list(entries.values())
        for m in result:
            if m['status'] in ('ready','experimental') and not model_command_registered(m['model_id']):
                m['status']='unavailable';m['reason']='模型卡存在，但管理员尚未登记对应独立运行环境'
        if not result:
            return [{'model_id':'models-adapter','version':None,'display_name':'模型模块','capabilities':[],
                'status':'not_installed','reason':'尚未导入模型卡与登记执行环境','parameters_schema':{}}]
        return result

    def configured_model(id):
        result=next((m for m in models() if m['model_id']==id),None)
        if result is None:
            raise HTTPException(404,'模型不存在')
        return result

    def model_command_registered(model_id):
        mapping=os.getenv('BTV_MODEL_COMMANDS_JSON')
        if mapping:
            try:
                return bool(json.loads(mapping).get(model_id))
            except (ValueError,AttributeError):
                return False
        return False

    @app.get('/api/v1/resources/gpu')
    def gpu_status():
        from packages.runtime.gpu import GPUCoordinator
        return GPUCoordinator(state.with_name('runtime.sqlite3')).status()

    @app.post('/api/v1/models/import')
    def import_model(body:dict):
        from packages.contracts import ModelManifest
        m=ModelManifest.model_validate(body).model_dump(mode='json')
        # A manifest cannot grant command execution; environment registration is mandatory.
        if m['status']=='ready' and not model_command_registered(m['model_id']):
            m['status']='unavailable'; m['reason']='模型卡存在，但管理员未注册独立运行环境'
        return store.put('model',m['model_id'],m)

    @app.get('/api/v1/models/{id}/health')
    def model_health(id:str):
        m=configured_model(id)
        return {'model_id':id,'status':m['status'],'reason':m.get('reason'),'command_registered':model_command_registered(id)}

    @app.post('/api/v1/models/{id}/run',status_code=202)
    def model_run(id:str,body:dict):
        m=configured_model(id)
        operation=body.get('operation') or (m['capabilities'][0] if m['capabilities'] else None)
        if operation not in m['capabilities']:
            raise ValueError('操作不在模型已登记能力中')
        requirements=m.get('resource_requirements') or {}
        parameters=body.get('parameters',{})
        return enqueue('model',{'model_id':id,'model_version':m['version'],'model_status':m['status'],
            'adapter_operation':operation,'gpu_required':bool(requirements.get('gpu_required') or requirements.get('gpu') or requirements.get('gpu_memory_gb') or requirements.get('device') in ('cuda','gpu') or str(parameters.get('device','')).startswith(('cuda','gpu'))),
            'assets':[asset_or_404(x) for x in body.get('asset_ids',[])], 'parameters':parameters})

    @app.get('/api/v1/jobs')
    def jobs(status:str|None=None):
        return queue.list(status=status)

    @app.get('/api/v1/reports')
    def reports():
        return [{'job_id':j['job_id'],'operation':j['operation'],'status':j['status'],
                 'reports':[a for a in (j.get('result') or {}).get('artifacts',[]) if 'report' in a['kind'] or a['kind']=='source_map']}
                for j in queue.list(limit=100) if j['status'] in ('succeeded','failed','blocked')]

    @app.get('/api/v1/jobs/{id}')
    def job(id:str):
        j=queue.get(id)
        if not j:
            raise HTTPException(404,'任务不存在')
        return j

    @app.get('/api/v1/jobs/{id}/logs')
    def job_logs(id:str,after_seq:int=0):
        return queue.logs(id,after_seq=after_seq)

    @app.post('/api/v1/jobs/{id}/cancel')
    def cancel(id:str):
        return queue.request_cancel(id)

    @app.post('/api/v1/jobs/{id}/retry')
    def retry(id:str):
        production_job(job(id))
        try:
            return queue.retry(id)
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from None

    @app.post('/api/v1/jobs/{id}/apply')
    def apply_result(id:str):
        j=job(id)
        if j['status']!='succeeded':
            raise Conflict('只可应用成功完成的结果')
        result=j.get('result') or {}
        production_job(j)
        def verified_apply_assets(assets):
            identities={}
            for asset in assets:
                path=resolve_relative_path(root,asset['relative_path'],must_exist=True)
                before=store._file_identity(path)
                proof=result.get('source_identities',{}).get(asset['asset_id'])
                if proof is not None:
                    if proof!=before:
                        raise Conflict('SOURCE_CHANGED: 后台校验后原片变化，请重新运行任务')
                else:
                    if before[2]>8_000_000:
                        raise Conflict('SOURCE_REVERIFY_REQUIRED: 旧任务缺少源文件身份，请重新运行探测/校验')
                    with path.open('rb') as stream:
                        digest=hashlib.file_digest(stream,'sha256').hexdigest()
                    production_assets([{**asset,'sha256':digest}])
                    if before!=store._file_identity(path) or digest!=asset['sha256']:
                        raise Conflict('SOURCE_CHANGED: 后台校验后原片内容变化，请重新运行任务')
                if before[2]!=asset['size_bytes']:
                    raise Conflict('SOURCE_CHANGED: 原片大小变化，请重新运行任务')
                identities[asset['asset_id']]=before
            return identities
        if j['operation']=='verify_manifest':
            verified=AssetManifest.model_validate({'assets':result['assets']}).model_dump(mode='json')['assets']
            identities=verified_apply_assets(verified)
            return {'imported':store.import_assets(verified,j['payload']['library_id'],verified_identities=identities),'integrity':'worker_sha256_verified'}
        if j['operation']=='probe':
            asset=result.get('asset') or (result.get('assets') or [None])[0]
            if not asset:
                raise ValueError('探测结果没有Asset')
            asset=AssetManifest.model_validate({'assets':[asset]}).model_dump(mode='json')['assets'][0]
            identities=verified_apply_assets([asset])
            # Probe already hashes the complete source in the independent worker.
            # Do not route a large successful result back into asynchronous import.
            source=resolve_relative_path(root,asset['relative_path'],must_exist=True)
            if not source.is_file() or source.stat().st_size!=asset['size_bytes']:
                raise Conflict('探测后源文件缺失或大小变化，请重新探测')
            imported={'imported':store.import_assets([asset],j['payload']['library_id'],verified_identities=identities),'integrity':'worker_sha256_verified'}
            target=imported['imported'][0]['asset']
            store.update_asset_probe(target['asset_id'],asset.get('probe',{}))
            return imported
        if j['operation']=='model':
            model_events=[]
            for event in result.get('events',[]):
                event={**event,'review_status':'unreviewed','reviewer_type':None,'reviewer':None,'reviewed_at':None}
                model_events.append(validate_event(event))
            return {'events':store.save_events([(e,0,'model-import','agent') for e in model_events],actor='automatic')}
        return result

    @app.head('/api/v1/jobs/{id}/artifacts/{artifact_id}')
    @app.get('/api/v1/jobs/{id}/artifacts/{artifact_id}')
    def artifact(id:str,artifact_id:str):
        j=job(id)
        production_job(j)
        if j['status']!='succeeded':
            raise HTTPException(409,'产物尚未完成')
        a=next((a for a in (j.get('result') or {}).get('artifacts',[]) if a['artifact_id']==artifact_id),None)
        if not a:
            raise HTTPException(404,'产物不存在')
        path,identity=verified_artifact(j,a)
        media_type=mimetypes.guess_type(a['relative_path'])[0] or 'application/octet-stream'
        inline=media_type.startswith(('video/','image/'))
        return VerifiedArtifactResponse(path,identity,filename=Path(a['relative_path']).name,
                            media_type=media_type,content_disposition_type='inline' if inline else 'attachment',headers={'Cache-Control':'no-store'})

    def llm_config():
        return store.get('setting','llm') or {'provider':'openai-compatible','base_url':'','model':'','timeout':20,'key_env':'BTV_LLM_API_KEY'}

    @app.get('/api/v1/settings/llm')
    def get_llm():
        config=llm_config()
        return {**config,'key_present':bool(os.getenv(config['key_env'])),'key_masked':'••••••••' if os.getenv(config['key_env']) else '未配置'}

    @app.put('/api/v1/settings/llm')
    def set_llm(body:dict):
        if set(body)-{'provider','base_url','model','timeout','key_env'}:
            raise ValueError('只接受密钥环境变量名，不接受明文密钥')
        config={**llm_config(),**body}
        u=urlsplit(config['base_url'])
        if config['base_url'] and (u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment):
            raise ValueError('端点须为不含凭据或查询参数的HTTP(S) URL')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,100}',config['key_env']):
            raise ValueError('密钥环境变量名称无效')
        config['timeout']=max(1,min(60,float(config['timeout'])))
        store.put('setting','llm',config)
        return get_llm()

    @app.post('/api/v1/settings/llm/test')
    async def test_llm():
        c=llm_config()
        if not c['base_url']:
            return {'status':'not_configured'}
        secret=os.getenv(c['key_env'],'')
        try:
            async with httpx.AsyncClient(timeout=c['timeout'],follow_redirects=False) as client:
                r=await client.get(c['base_url'].rstrip('/')+'/models',headers={'Authorization':'Bearer '+secret} if secret else {})
            return {'status':'ready' if r.is_success else 'unavailable','http_status':r.status_code}
        except httpx.HTTPError:
            return {'status':'unavailable','reason':'连接失败或超时（不显示响应内容以避免泄露密钥）'}

    @app.get('/api/v1/annotation/label-studio/status')
    def labelstudio_status():
        from .labelstudio import LabelStudioClient
        return {**LabelStudioClient().health(),'adapter':'TimelineLabels + VideoRectangle / PTS',
                'sync':'导出任务 → 编辑 → 导出JSON → 验证回写'}

    @app.post('/api/v1/annotation/label-studio/task')
    def labelstudio_task(body:dict):
        from .labelstudio import FrameMap, build_task
        a=asset_or_404(body['asset_id'])
        fm=FrameMap.from_dict(body.get('frame_map') or frame_map(a['asset_id']))
        task=build_task(a,'http://127.0.0.1:18080/api/v1/assets/'+a['asset_id']+'/media',fm,store.events(a['asset_id']))
        snapshot_id=uid('ls-snapshot')
        task['data']['btv']['snapshot_id']=snapshot_id
        store.create_label_studio_snapshot(snapshot_id,task)
        return task

    @app.post('/api/v1/annotation/label-studio/import')
    def labelstudio_import(body:dict):
        from .labelstudio import FrameMap, annotation_hash, import_annotation
        tasks=body['export'] if isinstance(body['export'],list) else [body['export']]
        raw=json.dumps(tasks,ensure_ascii=False).encode('utf-8')
        if len(raw)>32_000_000:
            raise ValueError('单次标注导出最多32MB')
        digest=hashlib.sha256(raw).hexdigest()
        relative='platform/annotations/labelstudio-'+digest+'.json'
        ledger=CapacityLedger(state.with_name('runtime.sqlite3'),root)
        reservation=ledger.reserve('platform',len(raw)*2)
        try:
            path=resolve_relative_path(root,relative)
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():
                temp=path.with_suffix('.json.part')
                temp.write_bytes(raw); os.replace(temp,path)
        finally:
            ledger.release(reservation)
        batches=[]
        for task in tasks:
            a=asset_or_404(task['data']['asset_id'])
            snapshot_id=task['data'].get('btv',{}).get('snapshot_id')
            if not isinstance(snapshot_id,str) or not snapshot_id:
                raise Conflict('Label Studio 任务缺少不可变 snapshot_id；请从平台重新导出任务')
            trusted=store.get('ls_task_snapshot',snapshot_id)
            if trusted is None or trusted['data']['asset_id']!=a['asset_id']:
                raise Conflict('Label Studio 导出快照不存在或素材不匹配；请从平台重新导出任务')
            safe_task={**task,'data':trusted['data']}
            fm=FrameMap.from_dict(trusted['data']['btv']['frame_map'])
            for annotation in task.get('annotations',[]):
                converted=import_annotation(safe_task,annotation,frame_map=fm,
                  tool_version=str(body.get('tool_version','1.23.1')),raw_export_relative_path=relative)
                converted['events']=[validate_event(e) for e in converted['events']]
                batches.append({'snapshot_id':snapshot_id,'asset_id':a['asset_id'],'task_id':task['id'],'annotation_id':annotation['id'],
                                'annotation_sha256':annotation_hash(annotation),'updated_at':annotation.get('updated_at'),
                                'converted':converted})
        imported=store.import_label_studio(batches,body.get('reviewer','label-studio-import'),body.get('reviewer_type','human'))
        return {**imported,'raw_export_relative_path':relative}

    return app


app=create_app()
