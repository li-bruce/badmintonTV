"""Local, explicitly trusted training domain, separate from production media gates."""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

from packages.runtime import CapacityLedger
from packages.runtime.storage import _is_linklike
from .artifact_response import VerifiedArtifactResponse
from .training_store import TrainingStore


class GuideFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        root = Path(self.directory)
        if not root.is_dir() or any(_is_linklike(p) for p in (root, root.parent, root.parent.parent)) or not (root / 'index.html').is_file():
            response = HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>框架手册尚未生成</title>'
                                    '<main><h1>框架手册尚未生成</h1><p>请由主任务从 docs/FRAMEWORK_GUIDE.md 构建 docs/site/index.html。</p>'
                                    '<p><a href="/training">返回训练工作台</a> · <a href="/">制作工作台</a></p></main></html>', status_code=503)
            return await response(scope, receive, send)
        return await super().__call__(scope, receive, send)

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'"
        return response


def asset_ref(registered):
    from packages.contracts.training import TrainingAssetRef
    if registered.get('training_asset_ref'):
        return TrainingAssetRef.model_validate(registered['training_asset_ref']).model_dump(mode='json')
    asset = registered['asset']
    group = registered.get('catalog_metadata', {}).get('match_group', {})
    provenance = {k: v for k, v in asset.get('provenance', {}).items() if k != 'annotation_catalog'}
    return TrainingAssetRef(
        asset_id=asset['asset_id'], sha256=asset['sha256'], relative_path=asset['relative_path'],
        size_bytes=asset['size_bytes'], duration_ms=asset['duration_ms'], title=asset.get('title', ''), source_usage_scope=asset.get('usage_scope', 'training_only'),
        match_id=asset.get('match_id'), group_id=group.get('confirmed_group_id') or group.get('publisher_match_id') or asset.get('match_id'),
        group_status=group.get('status', 'unconfirmed'), pts_reference=asset.get('probe', {}).get('pts_index'),
        root_asset_ids=tuple(provenance.get('root_asset_ids', [])) + ((provenance['source_asset_id'],) if provenance.get('source_asset_id') else ()),
        source_sha256s=tuple(provenance.get('source_sha256s', [])) + ((provenance['source_sha256'],) if provenance.get('source_sha256') else ()),
        recording_session_id=provenance.get('recording_session_id'), source_group_ids=tuple(provenance.get('source_group_ids', [])),
        provenance={**provenance, 'title': asset.get('title'), 'source_page': asset.get('source_page'),
                    'source_url': asset.get('source_url'), 'rights': asset.get('rights'),
                    'annotation_entry_sha256': registered.get('catalog_proof', {}).get('annotation_entry_sha256'),
                    'group_evidence': group.get('evidence', '旧目录仅含发布者比赛名，未独立确认比赛分组')},
    ).model_dump(mode='json')


def install_training(app, store, queue, templates):
    from .training_catalog import TrainingCatalog
    from .training_taxonomy import load_training_taxonomy
    training, catalog = TrainingStore(store), TrainingCatalog(store.storage_root)
    app.state.training_store, app.state.training_catalog = training, catalog
    actor_type = os.getenv('BTV_TRAINING_ACTOR_TYPE', 'agent')
    if actor_type not in ('agent', 'human'):
        raise ValueError('BTV_TRAINING_ACTOR_TYPE 必须为 agent 或 human')
    app.state.training_actor_type = actor_type
    executor, stop = ThreadPoolExecutor(max_workers=1, thread_name_prefix='training-register'), threading.Event()
    app.state.training_executor = executor
    ledger = CapacityLedger(queue.db_path, store.storage_root)

    @app.on_event('startup')
    def recover():
        training.recover_registrations()

    @app.on_event('shutdown')
    def shutdown():
        stop.set()
        executor.shutdown(wait=True, cancel_futures=True)

    @contextmanager
    def budget(size=16_000_000):
        reservation = ledger.reserve('platform', size)
        try:
            yield
        finally:
            ledger.release(reservation)

    def taxonomy():
        # Admin supplied local file, never a browser supplied path. Freeze it in each project.
        return load_training_taxonomy(os.getenv('BTV_TRAINING_TAXONOMY')).model_dump(mode='json')

    def registered(asset_id):
        record = training.registered(asset_id)
        catalog.validate_registered(record)
        return record

    def public_asset(record):
        a = record['asset']
        return {**asset_ref(record), 'title': a.get('title', a['asset_id']), 'width': a.get('width'), 'height': a.get('height'),
                'media_url': '/api/v1/training/assets/' + a['asset_id'] + '/media', 'probe': a.get('probe', {})}

    def project_refs(project):
        return [asset_ref(registered(a)) for a in project.get('asset_ids', [])]

    @app.get('/training', response_class=HTMLResponse)
    def workspace(request: Request):
        return templates.TemplateResponse(request=request, name='training.html', context={})

    @app.get('/guide')
    def guide():
        return RedirectResponse('/guide/')

    app.mount('/guide', GuideFiles(directory=Path(__file__).resolve().parents[2] / 'docs' / 'site', html=True, check_dir=False), name='guide')

    @app.get('/api/v1/training/taxonomy')
    def get_taxonomy():
        return taxonomy()

    @app.get('/api/v1/training/catalog')
    def get_catalog(offset: int = 0, limit: int = 100):
        return catalog.list_catalog(offset=offset, limit=limit)

    def run_registration(registration_id, asset_id):
        last_progress = [0.0]
        def check():
            if stop.is_set():
                raise ValueError('服务正在停止，校验未完成，请重试')
        def progress(value):
            if time.monotonic() - last_progress[0] >= .25:
                training.update_registration(registration_id, progress=value)
                last_progress[0] = time.monotonic()
        try:
            with budget():
                check()
                training.update_registration(registration_id, status='running')
                verified = catalog.verify_asset(asset_id, check=check, progress=progress)
                check()
                asset_ref(verified)
                training.publish_registration(registration_id, verified)
        except Exception as exc:
            training.update_registration(registration_id, status='failed', error=str(exc))

    @app.post('/api/v1/training/registrations', status_code=202)
    def register(body: dict):
        if set(body) != {'asset_id'} or not isinstance(body['asset_id'], str):
            raise ValueError('只能选择可信目录中的 asset_id，不接受路径或用途覆盖参数')
        # Validate selection before enqueuing; verification remains bounded/background.
        catalog.get_asset(body['asset_id'])
        with budget():
            item, created = training.begin_registration(body['asset_id'])
        if created:
            executor.submit(run_registration, item['registration_id'], body['asset_id'])
        return item

    @app.get('/api/v1/training/registrations/{registration_id}')
    def registration(registration_id: str):
        return training.registration(registration_id)

    @app.get('/api/v1/training/assets')
    def assets():
        return [public_asset(r) for r in training.registered()]

    @app.get('/api/v1/training/assets/{asset_id}/media')
    @app.head('/api/v1/training/assets/{asset_id}/media')
    def media(asset_id: str):
        record = registered(asset_id)
        path = catalog.validate_registered(record)
        return VerifiedArtifactResponse(path, record['identity_proof'], media_type='video/mp4',
                                        headers={'Cache-Control': 'no-store'}, content_disposition_type='inline')

    @app.get('/api/v1/training/assets/{asset_id}/source-frames')
    def source_frames(asset_id: str, offset_frame: int = 0, limit: int = 128, at_ms: int | None = None):
        return catalog.read_frames(registered(asset_id), offset_frame=offset_frame, limit=limit, at_ms=at_ms)

    @app.get('/api/v1/training/projects')
    def projects():
        return training.projects()

    @app.post('/api/v1/training/projects', status_code=201)
    def create_project(body: dict):
        if set(body) != {'name'} or not isinstance(body['name'], str) or not 1 <= len(body['name'].strip()) <= 120:
            raise ValueError('项目名称须为1–120个字符')
        version = catalog.list_catalog(limit=1)['catalog_revision']
        with budget():
            return training.create_project(body['name'].strip(), taxonomy(), version)

    @app.get('/api/v1/training/projects/{project_id}')
    def project(project_id: str):
        context = training.project(project_id)
        return {**context, 'actor_type': actor_type, 'assets': [public_asset(training.registered(a)) for a in context['project']['asset_ids']]}

    @app.post('/api/v1/training/projects/{project_id}/assets')
    def add_asset(project_id: str, body: dict):
        registered(body['asset_id'])
        with budget():
            return training.update_project(project_id, body['expected_revision'], asset_id=body['asset_id'])

    @app.get('/api/v1/training/projects/{project_id}/bundles/{asset_id}')
    def bundle(project_id: str, asset_id: str, revision: int | None = None):
        context = training.project(project_id)
        if asset_id not in context['project']['asset_ids']:
            raise HTTPException(404, '素材不属于此训练项目')
        saved = training.bundle(project_id, asset_id, revision)
        if saved is not None:
            return saved
        if revision is not None:
            raise HTTPException(404, '标注历史版本不存在')
        return {'schema_version': '1.0', 'format': 'badmintontv.training.annotations.v1', 'project_id': project_id,
                'asset': asset_ref(registered(asset_id)), 'revision': 0, 'people': [], 'records': []}

    @app.put('/api/v1/training/projects/{project_id}/bundles/{asset_id}')
    def save_bundle(project_id: str, asset_id: str, body: dict):
        with budget():
            return training.save_bundle(project_id, asset_id, body['bundle'], body['expected_revision'],
                                        actor_type=actor_type, asset_ref=asset_ref(registered(asset_id)))

    @app.get('/api/v1/training/projects/{project_id}/bundles/{asset_id}/revisions')
    def revisions(project_id: str, asset_id: str):
        return training.revisions(project_id, asset_id)

    @app.put('/api/v1/training/projects/{project_id}/splits')
    def splits(project_id: str, body: dict):
        from packages.contracts.training import build_training_snapshot
        context = training.project(project_id)
        # Shared snapshot validator enforces group status and same-source leakage.
        build_training_snapshot(snapshot_id='split-validation', project=context['project'], taxonomy=context['taxonomy'],
                                assets=project_refs(context['project']), bundles=[], splits=body['splits'])
        with budget():
            return training.update_project(project_id, body['expected_revision'], splits=body['splits'])

    @app.post('/api/v1/training/projects/{project_id}/snapshots', status_code=201)
    def create_snapshot(project_id: str, body: dict):
        context = training.project(project_id)
        refs = project_refs(context['project'])
        with budget(96_000_000):
            return training.create_snapshot(project_id, body['expected_revision'], refs)

    @app.get('/api/v1/training/projects/{project_id}/snapshots')
    def snapshots(project_id: str):
        return training.snapshots(project_id)

    @app.get('/api/v1/training/snapshots/{snapshot_id}')
    def snapshot(snapshot_id: str):
        return training.snapshot(snapshot_id)

    @app.get('/api/v1/training/snapshots/{snapshot_id}/download')
    def download(snapshot_id: str, view: str = 'audit', format: str = 'json'):
        result = training.snapshot(snapshot_id)
        if view not in ('audit', 'training') or format not in ('json', 'jsonl'):
            raise ValueError('仅支持 audit/training 与 json/jsonl')
        if view == 'training' and not result['quality_summary']['trainable']:
            raise HTTPException(409, {'message': '此快照仍有质量阻塞，暂不能导出正式训练视图；请下载审计快照查看待补项',
                                      'quality_summary': result['quality_summary'],
                                      'audit_url': f'/api/v1/training/snapshots/{snapshot_id}/download?view=audit'})
        value = result if view == 'audit' else {'format': 'badmintontv.training.view.v1', 'snapshot_id': snapshot_id,
                                               'usage_scope': 'training_only', 'content_sha256': result['content_sha256'],
                                               'training_view': result['training_view'], 'quality_summary': result['quality_summary']}
        if format == 'jsonl':
            # First line remains self-contained metadata; rows retain source and immutable snapshot linkage.
            rows = value.get('training_view', []) if view == 'training' else value.get('bundles', [])
            header = {k: v for k, v in value.items() if k not in ('training_view', 'bundles')}
            data = '\n'.join(json.dumps(row, ensure_ascii=False) for row in [{'type': 'snapshot', **header}, *rows]) + '\n'
        else:
            data = json.dumps(value, ensure_ascii=False, indent=2)
        return Response(data, media_type='application/json' if format == 'json' else 'application/x-ndjson',
                        headers={'Content-Disposition': f'attachment; filename="{snapshot_id}-{view}.{format}"', 'Cache-Control': 'no-store'})
