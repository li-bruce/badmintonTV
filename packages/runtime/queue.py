"""Small persistent job queue with leased ownership and explicit retries."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


TERMINAL = frozenset({"succeeded", "failed", "blocked", "cancelled"})


class Queue:
    def __init__(self, db_path):
        self.db_path = str(Path(db_path).resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runtime_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, operation TEXT NOT NULL,
                    payload TEXT NOT NULL, idempotency_key TEXT UNIQUE,
                    status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    worker_id TEXT, lease_expires_at REAL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    result TEXT, error TEXT, progress TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_claim ON jobs(status, created_at);
                CREATE TABLE IF NOT EXISTS artifact_identities (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id), attempt INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL, relative_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, identity TEXT NOT NULL,
                    PRIMARY KEY(job_id, attempt, artifact_id)
                );
                CREATE TABLE IF NOT EXISTS job_logs (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id), seq INTEGER NOT NULL,
                    created_at REAL NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(job_id, seq)
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    peak_bytes INTEGER NOT NULL, job_id TEXT,
                    created_at REAL NOT NULL, released_at REAL
                );
                PRAGMA user_version=1;
            """)

    def bind_business_database(self, path):
        """Administrator app configuration, never accepted from job payloads."""
        value=str(Path(path).resolve())
        with self.connection(write=True) as db:
            existing=db.execute("SELECT value FROM runtime_metadata WHERE key='business_database'").fetchone()
            if existing and existing[0]!=value:
                raise ValueError('runtime queue is already bound to a different business database')
            db.execute("INSERT OR IGNORE INTO runtime_metadata VALUES('business_database',?)",(value,))

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _job(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("payload", "result", "error", "progress"):
            result[key] = json.loads(result[key]) if result[key] is not None else None
        result["cancel_requested"] = bool(result["cancel_requested"])
        return result

    @staticmethod
    def _require(db, job_id):
        row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return row

    @staticmethod
    def _log(db, job_id, body):
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM job_logs WHERE job_id=?", (job_id,)).fetchone()[0]
        body = {**body, "schema_version": "1.0", "job_id": job_id, "seq": seq, "created_at": time.time()}
        db.execute("INSERT INTO job_logs VALUES(?,?,?,?)", (job_id, seq, body["created_at"], json.dumps(body, ensure_ascii=False)))
        return body

    def enqueue(self, operation, payload, idempotency_key=None, max_attempts=3):
        if not isinstance(operation, str) or not operation or not isinstance(payload, dict):
            raise ValueError("operation must be a nonempty string and payload an object")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        with self.connection(write=True) as db:
            now = time.time()
            if idempotency_key is not None:
                existing = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if existing is not None:
                    if existing["operation"] != operation or json.loads(existing["payload"]) != payload:
                        raise ValueError("idempotency key already belongs to a different request")
                    return self._job(existing)
            job_id = "job-" + uuid.uuid4().hex
            db.execute("INSERT INTO jobs(job_id,operation,payload,idempotency_key,status,max_attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (job_id, operation, encoded, idempotency_key, "queued", max_attempts, now, now))
            self._log(db, job_id, {"event": "state", "stage": "queued", "message": "任务已持久入队"})
            return self._job(self._require(db, job_id))

    def get(self, job_id):
        with self.connection() as db:
            return self._job(db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def list(self, status=None, limit=100):
        limit = max(1, min(int(limit), 1000))
        with self.connection() as db:
            sql = "SELECT * FROM jobs" + (" WHERE status=?" if status else "") + " ORDER BY created_at DESC LIMIT ?"
            return [self._job(row) for row in db.execute(sql, (status, limit) if status else (limit,))]

    def logs(self, job_id, after_seq=0, limit=1000):
        with self.connection() as db:
            self._require(db, job_id)
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM job_logs WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?", (job_id, after_seq, max(1, min(int(limit), 5000))))]

    def claim(self, worker_id, lease_seconds=30):
        if not worker_id or lease_seconds <= 0:
            raise ValueError("worker_id and positive lease_seconds required")
        with self.connection(write=True) as db:
            now = time.time()
            row = db.execute("SELECT * FROM jobs WHERE status='queued' AND cancel_requested=0 AND attempt<max_attempts ORDER BY created_at,job_id LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='running',worker_id=?,lease_expires_at=?,attempt=attempt+1,updated_at=? WHERE job_id=?", (worker_id, now + lease_seconds, now, row["job_id"]))
            self._log(db, row["job_id"], {"event": "state", "stage": "running", "message": "worker 已领取", "worker_id": worker_id, "attempt": row["attempt"] + 1})
            return self._job(self._require(db, row["job_id"]))

    def heartbeat(self, job_id, worker_id, lease_seconds=30, expected_attempt=None):
        if lease_seconds <= 0:
            raise ValueError("positive lease_seconds required")
        with self.connection(write=True) as db:
            now = time.time()
            cursor = db.execute("UPDATE jobs SET lease_expires_at=?,updated_at=? WHERE job_id=? AND worker_id=? AND status='running' AND lease_expires_at>? AND (? IS NULL OR attempt=?)", (now + lease_seconds, now, job_id, worker_id, now, expected_attempt, expected_attempt))
            return cursor.rowcount == 1

    def append_log(self, job_id, event, stage=None, current=None, total=None, unit=None, message="", **data):
        body = {**data, "event": event, "stage": stage, "current": current, "total": total, "unit": unit, "message": message}
        with self.connection(write=True) as db:
            self._require(db, job_id)
            result = self._log(db, job_id, body)
            if event == "progress":
                db.execute("UPDATE jobs SET progress=?,updated_at=? WHERE job_id=?", (json.dumps(result, ensure_ascii=False), time.time(), job_id))
            return result

    def finish(self, job_id, worker_id, status, result=None, error=None, expected_attempt=None, artifact_identities=None):
        if status not in TERMINAL:
            raise ValueError("finish requires a terminal status")
        with self.connection(write=True) as db:
            now = time.time()
            row = self._require(db, job_id)
            if row["status"] != "running" or row["worker_id"] != worker_id or row["lease_expires_at"] <= now or (expected_attempt is not None and row["attempt"] != expected_attempt):
                raise RuntimeError("job lease is no longer owned by this worker")
            if row["cancel_requested"] and status == "succeeded":
                status = "cancelled"
                error = {"code": "cancelled", "message": "取消请求在任务完成前到达"}
            if status == 'succeeded' and artifact_identities:
                for artifact in (result or {}).get('artifacts', []):
                    proof = artifact_identities.get(artifact['artifact_id'])
                    if proof is None:
                        raise ValueError('worker artifact identity is missing')
                    self._record_artifact_identity(db, job_id, row['attempt'], artifact, proof)
            db.execute("UPDATE jobs SET status=?,result=?,error=?,lease_expires_at=NULL,updated_at=? WHERE job_id=?", (status, json.dumps(result, ensure_ascii=False) if result is not None else None, json.dumps(error, ensure_ascii=False) if error is not None else None, now, job_id))
            self._log(db, job_id, {"event": "state", "stage": status, "message": (error or {}).get("message", status)})
            return self._job(self._require(db, job_id))

    @staticmethod
    def _record_artifact_identity(db, job_id, attempt, artifact, proof):
        from .artifact_identity import ArtifactIdentityError
        identity = proof.get('identity')
        descriptor = proof.get('descriptor_identity')
        if (not isinstance(identity, list) or len(identity) != 5 or any(type(value) is not int for value in identity)
                or not isinstance(descriptor, list) or len(descriptor) != 5 or any(type(value) is not int for value in descriptor)
                or descriptor[:4] != identity[:4]
                or any(proof.get(field) != artifact.get(field) for field in ('relative_path', 'sha256', 'size_bytes'))
                or identity[2] != artifact.get('size_bytes')):
            raise ArtifactIdentityError('ARTIFACT_CHANGED: 可信产物身份与声明不一致')
        db.execute('INSERT OR REPLACE INTO artifact_identities VALUES(?,?,?,?,?,?,?)',
                   (job_id, attempt, artifact['artifact_id'], proof['relative_path'], proof['sha256'], proof['size_bytes'],
                    json.dumps({'path':identity,'descriptor':descriptor})))

    def artifact_identity(self, job_id, attempt, artifact_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM artifact_identities WHERE job_id=? AND attempt=? AND artifact_id=?',
                             (job_id, attempt, artifact_id)).fetchone()
        if not row:
            return None
        result = dict(row)
        identities = json.loads(result['identity'])
        result['identity'] = identities['path']
        result['descriptor_identity'] = identities['descriptor']
        return result

    def remember_legacy_artifact_identity(self, job_id, attempt, artifact, proof):
        """Only the Web bounded hash path calls this; result JSON is not proof."""
        from .artifact_identity import ArtifactIdentityError
        with self.connection(write=True) as db:
            row = self._require(db, job_id)
            result = json.loads(row['result']) if row['result'] else {}
            declared = next((value for value in result.get('artifacts', []) if value.get('artifact_id') == artifact['artifact_id']), None)
            if row['status'] != 'succeeded' or row['attempt'] != attempt or declared != artifact:
                raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物任务或attempt已变化')
            self._record_artifact_identity(db, job_id, attempt, artifact, proof)

    def request_cancel(self, job_id):
        with self.connection(write=True) as db:
            row = self._require(db, job_id)
            if row["status"] in TERMINAL:
                return self._job(row)
            status = "cancelled" if row["status"] == "queued" else row["status"]
            db.execute("UPDATE jobs SET cancel_requested=1,status=?,updated_at=? WHERE job_id=?", (status, time.time(), job_id))
            self._log(db, job_id, {"event": "state", "stage": "cancel_requested", "message": "已请求取消"})
            return self._job(self._require(db, job_id))

    def retry(self, job_id):
        with self.connection(write=True) as db:
            row = self._require(db, job_id)
            if row["status"] not in {"failed", "blocked", "cancelled"}:
                raise ValueError("only failed, blocked or cancelled jobs can be retried")
            if row["attempt"] >= row["max_attempts"]:
                raise ValueError("maximum attempts reached")
            db.execute("UPDATE jobs SET status='queued',cancel_requested=0,worker_id=NULL,lease_expires_at=NULL,result=NULL,error=NULL,progress=NULL,updated_at=? WHERE job_id=?", (time.time(), job_id))
            self._log(db, job_id, {"event": "state", "stage": "queued", "message": "用户显式重试", "previous_status": row["status"]})
            return self._job(self._require(db, job_id))

    def recover_expired(self):
        recovered = []
        with self.connection(write=True) as db:
            now = time.time()
            for row in db.execute("SELECT job_id,worker_id FROM jobs WHERE status='running' AND lease_expires_at<=?", (now,)).fetchall():
                error = {"code": "WORKER_INTERRUPTED", "message": "worker 租约已过期；保留产物，需要显式重试", "worker_id": row["worker_id"]}
                db.execute("UPDATE jobs SET status='failed',error=?,lease_expires_at=NULL,updated_at=? WHERE job_id=?", (json.dumps(error, ensure_ascii=False), now, row["job_id"]))
                self._log(db, row["job_id"], {"event": "error", "stage": "interrupted", **error})
                recovered.append(row["job_id"])
        return recovered
