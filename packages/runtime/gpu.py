"""Administrator-authorized GPU windows and fail-closed native SQLite leases.

There is deliberately no web grant endpoint and no payload authorization token.
The caller of release() must have verified its compute process tree has stopped.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .queue import Queue


MAX_WINDOW_SECONDS = 3600
MAX_LEASE_SECONDS = 300


class GPUUnavailable(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a nonempty string without control characters")
    return value


def _seconds(value, maximum, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{label} must be finite and within (0, {maximum}] seconds")
    return value


class GPUCoordinator:
    def __init__(self, db_path, resource="gpu0", *, clock=None):
        if resource != "gpu0":
            raise ValueError("this initial scheduler coordinates only physical gpu0")
        self.queue = Queue(db_path)
        self.db_path, self.resource = self.queue.db_path, resource
        self.clock = clock or time.time
        with self.queue.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS gpu_windows (
                    window_id TEXT PRIMARY KEY, resource TEXT NOT NULL,
                    model_ids TEXT NOT NULL, starts_at REAL NOT NULL,
                    expires_at REAL NOT NULL, granted_by TEXT NOT NULL,
                    coordination_note TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS gpu_windows_resource
                    ON gpu_windows(resource, expires_at);
                CREATE TABLE IF NOT EXISTS resource_leases (
                    lease_id TEXT PRIMARY KEY, resource TEXT NOT NULL,
                    window_id TEXT NOT NULL REFERENCES gpu_windows(window_id),
                    model_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    attempt INTEGER NOT NULL, worker_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','orphaned','released')),
                    acquired_at REAL NOT NULL, expires_at REAL NOT NULL,
                    updated_at REAL NOT NULL, released_at REAL,
                    orphan_reason TEXT, release_evidence TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS resource_one_live_lease
                    ON resource_leases(resource) WHERE status IN ('active','orphaned');
                CREATE TABLE IF NOT EXISTS gpu_window_revocations (
                    window_id TEXT PRIMARY KEY REFERENCES gpu_windows(window_id),
                    revoked_at REAL NOT NULL, reason TEXT NOT NULL
                );
            """)

    @staticmethod
    def _window(row):
        if row is None:
            return None
        value = dict(row)
        value["model_ids"] = json.loads(value["model_ids"])
        return value

    @staticmethod
    def _lease(row):
        if row is None:
            return None
        value = dict(row)
        if value.get("release_evidence"):
            value["release_evidence"] = json.loads(value["release_evidence"])
        return value

    def _expire(self, db, now):
        # Expiration is a loss of knowledge, never evidence of stopped compute.
        db.execute("UPDATE resource_leases SET status='orphaned',updated_at=?,orphan_reason='GPU lease expired; compute stop is unverified' WHERE resource=? AND status='active' AND expires_at<=?", (now, self.resource, now))

    def _get(self, db, lease_id):
        return db.execute("SELECT r.*,w.expires_at AS window_expires_at FROM resource_leases r JOIN gpu_windows w USING(window_id) WHERE r.lease_id=? AND r.resource=?", (lease_id, self.resource)).fetchone()

    def _get_window(self, db, window_id):
        return db.execute("SELECT w.*,r.revoked_at,r.reason AS revocation_reason FROM gpu_windows w LEFT JOIN gpu_window_revocations r USING(window_id) WHERE w.window_id=? AND w.resource=?", (window_id, self.resource)).fetchone()

    def get_window(self, window_id):
        with self.queue.connection() as db:
            return self._window(self._get_window(db, window_id))

    def revoke_window(self, window_id, *, reason):
        """Return an unused window early; never revoke around a live/orphaned lease."""
        _identifier(window_id, "window_id")
        _identifier(reason, "reason")
        failure, result = None, None
        with self.queue.connection(write=True) as db:
            now = self.clock()
            self._expire(db, now)
            window = self._get_window(db, window_id)
            if window is None:
                failure = KeyError(window_id)
            elif db.execute("SELECT 1 FROM resource_leases WHERE window_id=? AND status IN ('active','orphaned')", (window_id,)).fetchone():
                failure = GPUUnavailable("GPU_WINDOW_IN_USE", "窗口仍有 active/orphaned GPU 租约；必须先核实计算停止并释放租约")
            else:
                db.execute("UPDATE gpu_windows SET expires_at=MIN(expires_at,?) WHERE window_id=?", (now, window_id))
                db.execute("INSERT INTO gpu_window_revocations VALUES(?,?,?) ON CONFLICT(window_id) DO NOTHING", (window_id, now, reason))
                result = self._window(self._get_window(db, window_id))
        # Retain any active->orphaned transition even when revocation is denied.
        if failure:
            raise failure
        return result

    def grant_window(self, window_id, model_ids, seconds, *, granted_by=None, coordination_note=""):
        """Trusted administrative entry point; call only after models coordination."""
        _identifier(window_id, "window_id")
        _seconds(seconds, MAX_WINDOW_SECONDS, "window duration")
        if not isinstance(model_ids, (list, tuple)) or not model_ids:
            raise ValueError("at least one explicitly allowed model_id is required")
        models = list(dict.fromkeys(_identifier(model, "model_id") for model in model_ids))
        granted_by = _identifier(granted_by or getpass.getuser(), "granted_by")
        _identifier(coordination_note, "coordination_note")
        with self.queue.connection(write=True) as db:
            now = self.clock()
            if db.execute("SELECT 1 FROM gpu_windows WHERE window_id=?", (window_id,)).fetchone():
                raise GPUUnavailable("GPU_WINDOW_EXISTS", "window_id 已使用，不能覆盖或隐式延长授权")
            if db.execute("SELECT 1 FROM gpu_windows WHERE resource=? AND starts_at<=? AND expires_at>?", (self.resource, now, now)).fetchone():
                raise GPUUnavailable("GPU_WINDOW_ACTIVE", "已有未到期授权窗口，请等待窗口结束")
            db.execute("INSERT INTO gpu_windows VALUES(?,?,?,?,?,?,?,?)", (window_id, self.resource, json.dumps(models), now, now + seconds, granted_by, coordination_note, now))
            return self._window(db.execute("SELECT * FROM gpu_windows WHERE window_id=?", (window_id,)).fetchone())

    def claim(self, model_id, job_id, attempt, worker_id, lease_seconds=30, window_id=None):
        """Atomically lease gpu0 for the worker that owns this running job attempt."""
        for value, name in ((model_id, "model_id"), (job_id, "job_id"), (worker_id, "worker_id")):
            _identifier(value, name)
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        _seconds(lease_seconds, MAX_LEASE_SECONDS, "lease duration")
        failure, claimed = None, None
        with self.queue.connection(write=True) as db:
            now = self.clock()
            self._expire(db, now)
            existing = db.execute("SELECT * FROM resource_leases WHERE resource=? AND status IN ('active','orphaned')", (self.resource,)).fetchone()
            windows = db.execute("SELECT * FROM gpu_windows WHERE resource=? AND starts_at<=? AND expires_at>?", (self.resource, now, now)).fetchall()
            window = next((w for w in windows if model_id in json.loads(w["model_ids"]) and (window_id is None or w["window_id"] == window_id)), None)
            job = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if existing:
                code = "GPU_LEASE_ORPHANED" if existing["status"] == "orphaned" else "GPU_BUSY"
                failure = GPUUnavailable(code, f"{self.resource} 仍由 {existing['job_id']} attempt-{existing['attempt']} / {existing['worker_id']} 占用；状态 {existing['status']}")
            elif window is None:
                failure = GPUUnavailable("GPU_LEASE_REQUIRED", "没有允许该模型的有效管理员 GPU 授权窗口")
            elif job is None or job["status"] != "running" or job["worker_id"] != worker_id or job["attempt"] != attempt or not job["lease_expires_at"] or job["lease_expires_at"] <= now:
                failure = GPUUnavailable("GPU_JOB_LEASE_MISMATCH", "GPU 领取者不拥有当前运行中的 job attempt")
            elif json.loads(job["payload"]).get("model_id") != model_id:
                failure = GPUUnavailable("GPU_MODEL_MISMATCH", "GPU 模型与已持久化任务快照不符")
            else:
                lease_id = "gpu-lease-" + uuid.uuid4().hex
                db.execute("INSERT INTO resource_leases(lease_id,resource,window_id,model_id,job_id,attempt,worker_id,status,acquired_at,expires_at,updated_at) VALUES(?,?,?,?,?,?,?,'active',?,?,?)", (lease_id, self.resource, window["window_id"], model_id, job_id, attempt, worker_id, now, min(now + lease_seconds, window["expires_at"]), now))
                claimed = self._lease(self._get(db, lease_id))
        # Raise outside the transaction so expiry -> orphaned cannot roll back.
        if failure:
            raise failure
        return claimed

    def heartbeat(self, lease_id, worker_id, lease_seconds=30):
        _seconds(lease_seconds, MAX_LEASE_SECONDS, "lease duration")
        with self.queue.connection(write=True) as db:
            now = self.clock()
            self._expire(db, now)
            row = self._get(db, lease_id)
            if row is None or row["worker_id"] != worker_id or row["status"] != "active" or row["window_expires_at"] <= now:
                return False
            db.execute("UPDATE resource_leases SET expires_at=?,updated_at=? WHERE lease_id=?", (min(now + lease_seconds, row["window_expires_at"]), now, lease_id))
            return True

    def release(self, lease_id, worker_id, *, compute_stopped):
        """Trusted worker only: caller verified bridge.done job/attempt + stopped.

        Orphaned/expired leases require the administrator prove-stopped CLI even
        when a late done marker arrives. A client JSON flag is not authorization.
        """
        if compute_stopped is not True:
            raise GPUUnavailable("GPU_STOP_UNVERIFIED", "未核实本任务计算进程全部停止，不能释放 GPU")
        with self.queue.connection(write=True) as db:
            now = self.clock()
            self._expire(db, now)
            row = self._get(db, lease_id)
            if row is None or row["worker_id"] != worker_id or row["status"] != "active":
                return False
            evidence = {"method": "trusted_worker_compute_stopped", "worker_id": worker_id, "job_id": row["job_id"], "attempt": row["attempt"], "verified_at": now}
            db.execute("UPDATE resource_leases SET status='released',released_at=?,updated_at=?,release_evidence=? WHERE lease_id=?", (now, now, json.dumps(evidence), lease_id))
            return True

    def mark_orphaned(self, lease_id, worker_id, reason):
        _identifier(reason, "reason")
        with self.queue.connection(write=True) as db:
            now = self.clock()
            row = self._get(db, lease_id)
            if row is None or row["worker_id"] != worker_id or row["status"] == "released":
                return False
            db.execute("UPDATE resource_leases SET status='orphaned',orphan_reason=?,updated_at=? WHERE lease_id=?", (reason, now, lease_id))
            return True

    def get(self, lease_id):
        with self.queue.connection(write=True) as db:
            self._expire(db, self.clock())
            return self._lease(self._get(db, lease_id))

    def status(self):
        with self.queue.connection(write=True) as db:
            now = self.clock()
            self._expire(db, now)
            window = self._window(db.execute("SELECT * FROM gpu_windows WHERE resource=? AND starts_at<=? AND expires_at>? ORDER BY starts_at DESC LIMIT 1", (self.resource, now, now)).fetchone())
            row = db.execute("SELECT lease_id FROM resource_leases WHERE resource=? AND status IN ('active','orphaned')", (self.resource,)).fetchone()
            lease = self._lease(self._get(db, row["lease_id"])) if row else None
        code = ("GPU_LEASE_ORPHANED" if lease["status"] == "orphaned" else "GPU_BUSY") if lease else ("GPU_WINDOW_READY" if window else "GPU_LEASE_REQUIRED")
        return {"resource": self.resource, "code": code, "available": window is not None and lease is None, "active_window": window, "lease": lease}

    def prove_stopped(self, lease_id, done_file, *, nvidia_smi=None, administrator=None, note=""):
        """Administrator-only recovery, with a matching bridge marker + live check.

        Refuse recovery without a trustworthy completion marker. An empty GPU
        process list alone is not proof: an untracked process could acquire CUDA
        later. This method never kills any process.
        """
        _identifier(note, "verification note")
        administrator = _identifier(administrator or getpass.getuser(), "administrator")
        lease = self.get(lease_id)
        if lease is None:
            raise KeyError(lease_id)
        if lease["status"] != "orphaned":
            raise GPUUnavailable("GPU_NOT_ORPHANED", "只允许显式核验 orphaned GPU 租约")
        done_path = Path(done_file).resolve(strict=True)
        if not done_path.is_file() or done_path.stat().st_size > 65536:
            raise GPUUnavailable("GPU_STOP_UNVERIFIED", "bridge.done 文件无效或超过 64 KiB")
        done = json.loads(done_path.read_text(encoding="utf-8"))
        if not isinstance(done, dict):
            raise GPUUnavailable("GPU_STOP_UNVERIFIED", "bridge.done 必须是对象")
        attempt_matches = done.get("attempt_id") == f"attempt-{lease['attempt']}" if "attempt_id" in done else type(done.get("attempt")) is int and done["attempt"] == lease["attempt"]
        if done.get("job_id") != lease["job_id"] or not attempt_matches or done.get("compute_stopped") is not True:
            raise GPUUnavailable("GPU_STOP_UNVERIFIED", "bridge.done 未确认此 job/attempt 的计算已停止")
        executable = str(nvidia_smi or shutil.which("nvidia-smi") or "")
        if not executable:
            raise GPUUnavailable("GPU_STOP_UNVERIFIED", "nvidia-smi 不可用，不能实时核验 GPU")
        try:
            checked = subprocess.run([executable, "--id=0", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], check=False, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GPUUnavailable("GPU_STOP_UNVERIFIED", "nvidia-smi 执行失败；保留 GPU 锁") from exc
        if checked.returncode != 0 or checked.stdout.strip():
            raise GPUUnavailable("GPU_STOP_UNVERIFIED", "GPU 上仍有计算进程或状态无法确认；保留 GPU 锁")
        with self.queue.connection(write=True) as db:
            now = self.clock()
            current = self._get(db, lease_id)
            if current is None or current["status"] != "orphaned":
                return False
            evidence = {"method": "administrator_bridge_done_and_nvidia_smi", "administrator": administrator, "note": note,
                        "done_file": str(done_path), "job_id": lease["job_id"], "attempt": lease["attempt"], "compute_stopped": True, "verified_at": now}
            db.execute("UPDATE resource_leases SET status='released',released_at=?,updated_at=?,release_evidence=? WHERE lease_id=?", (now, now, json.dumps(evidence, ensure_ascii=False), lease_id))
            return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    grant = commands.add_parser("grant-window", help="Administrator only: models must first confirm a GPU idle window")
    grant.add_argument("--db", required=True)
    grant.add_argument("--window-id", required=True)
    grant.add_argument("--models", required=True, nargs="+", help="Allowed model IDs; comma separation also accepted")
    grant.add_argument("--seconds", required=True, type=float)
    grant.add_argument("--coordination-note", required=True)
    revoke = commands.add_parser("revoke-window", help="Return a GPU window after all its compute leases have stopped")
    revoke.add_argument("--db", required=True)
    revoke.add_argument("--window-id", required=True)
    revoke.add_argument("--reason", required=True)
    status = commands.add_parser("status")
    status.add_argument("--db", required=True)
    prove = commands.add_parser("prove-stopped", help="Verify an orphaned lease without killing processes")
    prove.add_argument("--db", required=True)
    prove.add_argument("--lease-id", required=True)
    prove.add_argument("--done-file", required=True)
    prove.add_argument("--nvidia-smi")
    prove.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    coordinator = GPUCoordinator(args.db)
    try:
        if args.command == "grant-window":
            models = [value for group in args.models for value in group.split(",") if value]
            result = coordinator.grant_window(args.window_id, models, args.seconds, coordination_note=args.coordination_note)
        elif args.command == "revoke-window":
            result = coordinator.revoke_window(args.window_id, reason=args.reason)
        elif args.command == "prove-stopped":
            released = coordinator.prove_stopped(args.lease_id, args.done_file, nvidia_smi=args.nvidia_smi, note=args.note)
            result = {"released": released, "lease": coordinator.get(args.lease_id)}
        else:
            result = coordinator.status()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (GPUUnavailable, ValueError, KeyError, OSError) as exc:
        print(json.dumps({"status": "blocked", "error": {"code": getattr(exc, "code", "GPU_CONFIGURATION_ERROR"), "message": str(exc)}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
