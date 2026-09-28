"""Single-host SQLite business data; all writes use short transactions."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
            INSERT OR IGNORE INTO schema_migrations VALUES(1);
            CREATE TABLE IF NOT EXISTS objects(kind TEXT, id TEXT, body TEXT NOT NULL,
              PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL,
              library_id TEXT NOT NULL, match_id TEXT NOT NULL, split TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
              revision INTEGER NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS event_revisions(event_id TEXT, revision INTEGER,
              body TEXT NOT NULL, reviewer TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(event_id,revision));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def put(self, kind, id, body):
        with self.connect() as db:
            db.execute('INSERT INTO objects VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body',
                       (kind, id, json.dumps(body, ensure_ascii=False)))
        return body

    def create_label_studio_snapshot(self, snapshot_id, task):
        """Insert an export-time seed/PTS baseline exactly once; never replace it."""
        if task['data']['btv'].get('snapshot_id') != snapshot_id:
            raise ValueError('Label Studio snapshot_id 与任务不一致')
        try:
            with self.connect() as db:
                db.execute('INSERT INTO objects VALUES(?,?,?)',
                           ('ls_task_snapshot', snapshot_id, json.dumps(task, ensure_ascii=False)))
        except sqlite3.IntegrityError:
            raise Conflict('Label Studio 导出快照已存在，不可覆盖') from None
        return task

    def get(self, kind, id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM objects WHERE kind=? AND id=?', (kind,id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM objects WHERE kind=? ORDER BY rowid', (kind,))]

    def import_assets(self, assets, library_id):
        result = []
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for a in assets:
                a={**a,'sha256':a['sha256'].lower()}
                prior = db.execute('SELECT body FROM assets WHERE sha256=?', (a['sha256'],)).fetchone()
                if prior:
                    result.append({'asset':json.loads(prior[0]), 'duplicate':True})
                    continue
                split = db.execute("SELECT split FROM assets WHERE match_id=? AND split != 'unassigned' LIMIT 1", (a['match_id'],)).fetchone()
                if split and a['split'] not in ('unassigned',split[0]):
                    raise Conflict('同场比赛不可跨训练/验证/测试划分')
                db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)', (a['asset_id'],a['sha256'],library_id,a['match_id'],a['split'],json.dumps(a,ensure_ascii=False)))
                result.append({'asset':a, 'duplicate':False})
        return result

    def assets(self, library_id=None):
        with self.connect() as db:
            rows = db.execute('SELECT body,library_id FROM assets' + (' WHERE library_id=?' if library_id else ''), (library_id,) if library_id else ()).fetchall()
        return [{**json.loads(r[0]), 'library_id':r[1]} for r in rows]

    def asset(self, id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM assets WHERE id=?', (id,)).fetchone()
        return json.loads(row[0]) if row else None

    def update_asset_probe(self, asset_id, probe):
        """Merge newly verified probe data without replacing source metadata."""
        from packages.contracts import Asset

        if not isinstance(probe, dict):
            raise ValueError('probe 必须是对象')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM assets WHERE id=?', (asset_id,)).fetchone()
            if row is None:
                raise KeyError(asset_id)
            asset = json.loads(row[0])
            asset['probe'] = {**asset.get('probe', {}), **probe}
            asset = Asset.model_validate(asset).model_dump(mode='json')
            db.execute('UPDATE assets SET body=? WHERE id=?', (json.dumps(asset, ensure_ascii=False), asset_id))
        return asset

    def events(self, asset_id=None):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM events' + (' WHERE asset_id=?' if asset_id else '') + ' ORDER BY rowid', (asset_id,) if asset_id else ()).fetchall()
        return [json.loads(r[0]) for r in rows]

    def event(self, id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM events WHERE id=?', (id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_event(self, event, expected_revision, reviewer, reviewer_type='human', *, actor='human'):
        return self.save_events([(event, expected_revision, reviewer, reviewer_type)], actor=actor)[0]

    def save_events(self, updates, *, actor='human'):
        """Save one import batch and its revision history in a single transaction.

        Each update is (event, expected_revision, reviewer, reviewer_type).  A
        conflict or invalid event anywhere in the batch rolls everything back.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            saved = self._save_events(db, updates, actor=actor)
        return saved

    @staticmethod
    def _save_events(db, updates, *, actor):
        """The caller owns the write transaction, including accompanying sync state."""
        from packages.contracts import Event

        if actor not in ('human', 'automatic'):
            raise ValueError('actor 必须由服务端设为 human 或 automatic')
        saved = []
        for event, expected_revision, reviewer, reviewer_type in updates:
            if type(expected_revision) is not int or expected_revision < 0:
                raise ValueError('expected_revision 必须是非负整数')
            if reviewer_type not in ('human', 'agent'):
                raise ValueError('reviewer_type 必须是 human 或 agent')
            row = db.execute('SELECT revision,body FROM events WHERE id=?', (event['event_id'],)).fetchone()
            actual = row[0] if row else 0
            if actual != expected_revision:
                raise Conflict(f'标注版本冲突：当前{actual}，提交基于{expected_revision}')
            if row:
                prior = json.loads(row[1])
                if prior['asset_id'] != event['asset_id'] or prior['match_id'] != event['match_id']:
                    raise Conflict('修订不可更换源素材或比赛')
                if prior['review_status'] == 'confirmed' and actor == 'automatic':
                    raise Conflict('自动结果不得覆盖已确认标注')
            timestamp = now()
            event = Event.model_validate({
                **event, 'revision': actual + 1, 'reviewer': reviewer,
                'reviewer_type': reviewer_type, 'reviewed_at': timestamp,
                'previous_revision': actual or None,
                'provenance': {**event.get('provenance', {}), 'reviewer_type': reviewer_type},
            }).model_dump(mode='json')
            body = json.dumps(event,ensure_ascii=False)
            db.execute('INSERT INTO events VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, body=excluded.body', (event['event_id'],event['asset_id'],actual+1,body))
            db.execute('INSERT INTO event_revisions VALUES(?,?,?,?,?)', (event['event_id'],actual+1,body,reviewer,timestamp))
            saved.append(event)
        return saved

    def import_label_studio(self, batches, reviewer, reviewer_type='human'):
        """Atomically advance trusted per-annotation revision cursors.

        A cursor records only revisions this importer wrote, never the latest
        platform revision. Thus even an unconfirmed local edit remains protected.
        Accepted annotation hashes are immutable receipts: replay does no writes.
        """
        from .labelstudio import annotation_timestamp

        saved, tracks, warnings = [], [], []
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for batch in batches:
                converted = batch['converted']
                key = json.dumps([batch['snapshot_id'], batch['asset_id'], batch['task_id'], batch['annotation_id']], separators=(',', ':'))
                row = db.execute("SELECT body FROM objects WHERE kind='ls_sync' AND id=?", (key,)).fetchone()
                cursor = json.loads(row[0]) if row else None
                if cursor is None:
                    cursor = self._legacy_label_studio_cursor(db, batch)
                digest = batch['annotation_sha256']
                warnings.extend(converted['warnings'])
                if cursor and digest in cursor['accepted_hashes']:
                    # Do not roll back tracks either when replaying an old export.
                    continue
                incoming_time = annotation_timestamp(batch.get('updated_at'))
                if cursor:
                    prior_time = annotation_timestamp(cursor.get('updated_at'))
                    if incoming_time is None or prior_time is None or incoming_time <= prior_time:
                        raise Conflict('Label Studio 导出不是可验证的新版本；请重新导出含递增 updated_at 的标注')
                baseline = cursor['event_revisions'] if cursor else {}
                updates = []
                for event in converted['events']:
                    event_id = event['event_id']
                    expected = baseline.get(event_id, converted['expected_revisions'].get(event_id) or 0)
                    # The adapter's seed revision is only an initial baseline.
                    event = {**event, 'revision': expected + 1, 'previous_revision': expected or None,
                             'provenance': {**event['provenance'], 'previous_revision': expected or None}}
                    updates.append((event, expected, reviewer, reviewer_type))
                applied = self._save_events(db, updates, actor='automatic')
                saved.extend(applied)
                for track in converted['tracks']:
                    db.execute('INSERT INTO objects VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body',
                               ('track', track['track_id'], json.dumps(track, ensure_ascii=False)))
                    tracks.append(track)
                new_cursor = {
                    'snapshot_id': batch['snapshot_id'], 'asset_id': batch['asset_id'], 'task_id': batch['task_id'], 'annotation_id': batch['annotation_id'],
                    'annotation_sha256': digest, 'updated_at': batch.get('updated_at'),
                    'event_revisions': {**baseline, **{event['event_id']: event['revision'] for event in applied}},
                    'accepted_hashes': [*(cursor['accepted_hashes'] if cursor else []), digest],
                }
                db.execute('INSERT INTO objects VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body',
                           ('ls_sync', key, json.dumps(new_cursor, ensure_ascii=False)))
        return {'events': saved, 'tracks': tracks, 'warnings': warnings}

    @staticmethod
    def _legacy_label_studio_cursor(db, batch):
        """Recover only historical import revisions, excluding later local edits.

        Older releases retained annotation hashes in each revision, but lacked
        cursors. Local edits may preserve that provenance, so the first revision
        for each event/hash is the only defensible imported baseline.
        """
        from .labelstudio import annotation_timestamp

        receipts, revisions, timestamps = {}, {}, {}
        rows = db.execute('SELECT r.body FROM event_revisions r JOIN events e ON e.id=r.event_id WHERE e.asset_id=? ORDER BY r.revision',
                          (batch['asset_id'],))
        for row in rows:
            event = json.loads(row[0])
            provenance = event.get('provenance', {})
            digest = provenance.get('annotation_sha256')
            if (provenance.get('tool') != 'label-studio' or not digest
                    or provenance.get('snapshot_id') != batch['snapshot_id']
                    or provenance.get('task_id') != batch['task_id']
                    or provenance.get('annotation_id') != batch['annotation_id']):
                continue
            # Subsequent local revisions with the same hash are not LS imports.
            first = receipts.setdefault(digest, {})
            if event['event_id'] not in first:
                first[event['event_id']] = event['revision']
                revisions[event['event_id']] = max(revisions.get(event['event_id'], 0), event['revision'])
            timestamps.setdefault(digest, provenance.get('annotation_updated_at'))
        if not receipts:
            return None
        try:
            latest = max(receipts, key=lambda digest: annotation_timestamp(timestamps[digest]) or datetime.min.replace(tzinfo=timezone.utc))
        except ValueError:
            # An unverifiable legacy ordering permits replays but not new writes.
            latest = next(reversed(receipts))
            timestamps[latest] = None
        return {'event_revisions': revisions, 'accepted_hashes': list(receipts),
                'annotation_sha256': latest, 'updated_at': timestamps[latest]}

    def revisions(self, id):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM event_revisions WHERE event_id=? ORDER BY revision', (id,))]
