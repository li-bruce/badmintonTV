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
        from packages.contracts import Event

        if actor not in ('human', 'automatic'):
            raise ValueError('actor 必须由服务端设为 human 或 automatic')
        saved = []
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
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

    def revisions(self, id):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM event_revisions WHERE event_id=? ORDER BY revision', (id,))]
