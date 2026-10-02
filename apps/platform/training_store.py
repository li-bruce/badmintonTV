"""Isolated training persistence. No writes to production assets/events/objects."""
import copy
import json
import uuid
from datetime import datetime, timezone

from .store import Conflict


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return prefix + '-' + uuid.uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class TrainingStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS training_projects(id TEXT PRIMARY KEY, body TEXT NOT NULL, taxonomy TEXT NOT NULL, splits TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS training_assets(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS training_registrations(id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS training_bundles(project_id TEXT, asset_id TEXT, revision INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(project_id,asset_id));
            CREATE TABLE IF NOT EXISTS training_revisions(project_id TEXT, asset_id TEXT, revision INTEGER, body TEXT NOT NULL, saved_at TEXT NOT NULL, PRIMARY KEY(project_id,asset_id,revision));
            CREATE TABLE IF NOT EXISTS training_snapshots(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, body TEXT NOT NULL);
            ''')
            # Preserve the trusted first project reference from pre-release registrations.
            # Updating catalog presentation metadata must not change saved annotation identities.
            from packages.contracts.training import TrainingAssetRef
            for row in db.execute('SELECT id,body FROM training_assets').fetchall():
                registration = json.loads(row['body'])
                if 'training_asset_ref' in registration:
                    continue
                prior = db.execute('SELECT body FROM training_bundles WHERE asset_id=? ORDER BY rowid LIMIT 1', (row['id'],)).fetchone()
                if prior:
                    registration['training_asset_ref'] = TrainingAssetRef.model_validate(json.loads(prior[0])['asset']).model_dump(mode='json')
                    db.execute('UPDATE training_assets SET body=? WHERE id=?', (encode(registration), row['id']))

    def registered(self, asset_id=None):
        with self.store.connect() as db:
            if asset_id is None:
                return [json.loads(r[0]) for r in db.execute('SELECT body FROM training_assets ORDER BY rowid')]
            row = db.execute('SELECT body FROM training_assets WHERE id=?', (asset_id,)).fetchone()
        if not row:
            raise KeyError(asset_id)
        return json.loads(row[0])

    def registration(self, registration_id):
        with self.store.connect() as db:
            row = db.execute('SELECT body FROM training_registrations WHERE id=?', (registration_id,)).fetchone()
        if not row:
            raise KeyError(registration_id)
        return json.loads(row[0])

    def update_registration(self, registration_id, **updates):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM training_registrations WHERE id=?', (registration_id,)).fetchone()
            if not row:
                raise KeyError(registration_id)
            body = {**json.loads(row[0]), **updates, 'updated_at': now()}
            db.execute('UPDATE training_registrations SET body=? WHERE id=?', (encode(body), registration_id))
        return body

    def begin_registration(self, asset_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = [json.loads(r[0]) for r in db.execute('SELECT body FROM training_registrations')]
            active = [r for r in rows if r['status'] in ('queued', 'running')]
            existing = next((r for r in active if r['asset_id'] == asset_id), None)
            if existing:
                return existing, False
            if len(active) >= 16:
                raise Conflict('登记队列已满，请等待已有校验完成')
            body = {'registration_id': uid('training-registration'), 'asset_id': asset_id,
                    'status': 'queued', 'created_at': now(), 'updated_at': now()}
            db.execute('INSERT INTO training_registrations VALUES(?,?,?)', (body['registration_id'], asset_id, encode(body)))
        return body, True

    def recover_registrations(self):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT id,body FROM training_registrations').fetchall():
                body = json.loads(row['body'])
                if body['status'] in ('queued', 'running'):
                    body.update(status='failed', error='服务已重启，原校验未完成；请重新登记', updated_at=now())
                    db.execute('UPDATE training_registrations SET body=? WHERE id=?', (encode(body), row['id']))

    def publish_registration(self, registration_id, verified):
        from .training_api import asset_ref
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM training_registrations WHERE id=?', (registration_id,)).fetchone()
            body = json.loads(row[0])
            if body['status'] != 'running' or body['asset_id'] != verified['asset']['asset_id']:
                raise Conflict('登记尝试已经失效')
            incoming_ref = asset_ref(verified)
            previous = db.execute('SELECT body FROM training_assets WHERE id=?', (body['asset_id'],)).fetchone()
            if previous:
                old_ref = asset_ref(json.loads(previous[0]))
                for field in ('asset_id', 'sha256', 'relative_path', 'size_bytes', 'duration_ms', 'pts_reference'):
                    if old_ref[field] != incoming_ref[field]:
                        raise Conflict('已登记素材的源身份或时间映射变化，不能替换旧标注使用的引用')
                incoming_ref = old_ref
            verified = {**verified, 'training_asset_ref': incoming_ref}
            db.execute('INSERT INTO training_assets VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                       (body['asset_id'], encode(verified)))
            body.update(status='ready', updated_at=now(), error=None)
            db.execute('UPDATE training_registrations SET body=? WHERE id=?', (encode(body), registration_id))

    def projects(self):
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM training_projects ORDER BY rowid')]

    def project(self, project_id, db=None):
        if db is None:
            with self.store.connect() as conn:
                return self.project(project_id, conn)
        row = db.execute('SELECT * FROM training_projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise KeyError(project_id)
        return {'project': json.loads(row['body']), 'taxonomy': json.loads(row['taxonomy']), 'splits': json.loads(row['splits'])}

    def create_project(self, name, taxonomy, catalog_version):
        from packages.contracts.training import TrainingProject
        stamp = now()
        project = TrainingProject(project_id=uid('training-project'), name=name, taxonomy_id=taxonomy['taxonomy_id'],
                                  taxonomy_version=taxonomy['version'], catalog_version=catalog_version,
                                  revision=1, created_at=stamp, updated_at=stamp).model_dump(mode='json')
        with self.store.connect() as db:
            db.execute('INSERT INTO training_projects VALUES(?,?,?,?)', (project['project_id'], encode(project), encode(taxonomy), '[]'))
        return project

    @staticmethod
    def check_revision(project, expected):
        if type(expected) is not int or expected < 0:
            raise ValueError('expected_revision 必须为非负整数')
        if project['revision'] != expected:
            raise Conflict('项目已有新版本，请重载；本次没有覆盖任何内容')

    def update_project(self, project_id, expected, *, asset_id=None, splits=None):
        from packages.contracts.training import TrainingProject
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            context = self.project(project_id, db)
            project = context['project']
            self.check_revision(project, expected)
            if asset_id is not None:
                if not db.execute('SELECT 1 FROM training_assets WHERE id=?', (asset_id,)).fetchone():
                    raise KeyError(asset_id)
                project['asset_ids'] = list(dict.fromkeys([*project.get('asset_ids', []), asset_id]))
            project.update(revision=expected + 1, updated_at=now())
            project = TrainingProject.model_validate(project).model_dump(mode='json')
            db.execute('UPDATE training_projects SET body=?,splits=? WHERE id=?',
                       (encode(project), encode(context['splits'] if splits is None else splits), project_id))
        return project

    def bundle(self, project_id, asset_id, revision=None):
        with self.store.connect() as db:
            if revision is None:
                row = db.execute('SELECT body FROM training_bundles WHERE project_id=? AND asset_id=?', (project_id, asset_id)).fetchone()
            else:
                row = db.execute('SELECT body FROM training_revisions WHERE project_id=? AND asset_id=? AND revision=?', (project_id, asset_id, revision)).fetchone()
        return json.loads(row[0]) if row else None

    def save_bundle(self, project_id, asset_id, incoming, expected, *, actor_type, asset_ref):
        from packages.contracts.training import TrainingAssetRef, next_bundle_revision, validate_training_bundle
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            context = self.project(project_id, db)
            if asset_id not in context['project'].get('asset_ids', []):
                raise ValueError('素材未加入当前训练项目')
            row = db.execute('SELECT body FROM training_bundles WHERE project_id=? AND asset_id=?', (project_id, asset_id)).fetchone()
            current = json.loads(row[0]) if row else None
            actual = current['revision'] if current else 0
            if type(expected) is not int or expected != actual:
                raise Conflict(f'标注已有新版本（当前 {actual}），本次草稿未覆盖；请重载后合并')
            incoming_ref = TrainingAssetRef.model_validate(incoming.get('asset')).model_dump(mode='json')
            if incoming.get('project_id') != project_id or incoming_ref != asset_ref:
                raise ValueError('标注的项目或可信源引用不匹配')
            for record in incoming.get('records', []):
                for role in ('self', 'opponent', 'partner', 'opponent_partner'):
                    position = ((record.get('state') or {}).get(role) or {}).get('position')
                    if position and position.get('coordinate_system') != 'image_normalized':
                        raise ValueError('当前工作台尚无受信场地校准，只能保存归一图像坐标')
            incoming = {**incoming, 'asset': asset_ref, 'revision': actual + 1}
            saved = next_bundle_revision(current, incoming, expected, actor_type=actor_type, reviewer='local-' + actor_type)
            saved = saved.model_dump(mode='json') if hasattr(saved, 'model_dump') else saved
            validate_training_bundle(saved, context['taxonomy'])
            body = encode(saved)
            if len(body.encode('utf-8')) > 2_000_000:
                raise ValueError('单片标注超过2MB上限，请分项目整理')
            db.execute('INSERT INTO training_bundles VALUES(?,?,?,?) ON CONFLICT(project_id,asset_id) DO UPDATE SET revision=excluded.revision,body=excluded.body',
                       (project_id, asset_id, saved['revision'], body))
            db.execute('INSERT INTO training_revisions VALUES(?,?,?,?,?)', (project_id, asset_id, saved['revision'], body, now()))
            project = {**context['project'], 'revision': context['project']['revision'] + 1, 'updated_at': now()}
            db.execute('UPDATE training_projects SET body=? WHERE id=?', (encode(project), project_id))
        return saved

    def revisions(self, project_id, asset_id):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT revision,saved_at FROM training_revisions WHERE project_id=? AND asset_id=? ORDER BY revision', (project_id, asset_id))]

    def snapshots(self, project_id):
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM training_snapshots WHERE project_id=? ORDER BY rowid DESC', (project_id,))]

    def snapshot(self, snapshot_id):
        with self.store.connect() as db:
            row = db.execute('SELECT body FROM training_snapshots WHERE id=?', (snapshot_id,)).fetchone()
        if not row:
            raise KeyError(snapshot_id)
        return json.loads(row[0])

    def create_snapshot(self, project_id, expected, refs):
        from packages.contracts.training import build_training_snapshot
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            context = self.project(project_id, db)
            self.check_revision(context['project'], expected)
            if set(a['asset_id'] for a in refs) != set(context['project']['asset_ids']):
                raise Conflict('项目素材已变化，请重载')
            bundles = [json.loads(r[0]) for r in db.execute('SELECT body FROM training_bundles WHERE project_id=? ORDER BY asset_id', (project_id,))]
            snap = build_training_snapshot(snapshot_id=uid('training-snapshot'), project=context['project'], taxonomy=context['taxonomy'],
                                           assets=refs, bundles=bundles, splits=context['splits'], created_at=now())
            result = snap.model_dump(mode='json') if hasattr(snap, 'model_dump') else snap
            body = encode(result)
            if len(body.encode('utf-8')) > 32_000_000:
                raise ValueError('快照超过32MB上限，请拆分训练项目')
            db.execute('INSERT INTO training_snapshots VALUES(?,?,?)', (result['snapshot_id'], project_id, body))
        return copy.deepcopy(result)
